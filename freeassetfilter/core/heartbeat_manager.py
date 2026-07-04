#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter Heartbeat Manager

Singleton heartbeat coordinator for all main-thread periodic work.
Provides dual-tick-rate registration, priority-ordered dispatch,
cross-thread main-thread request queue, and owner-aware lifecycle.

Usage:
    hm = HeartbeatManager()
    hm.start()
    hm.register_tick_callback("my_cb", my_func, priority=2, owner=self)
    ...
    hm.stop_all()
"""

from __future__ import annotations

import threading
import time
import weakref
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Signal, QMetaObject, Qt

from freeassetfilter.utils.app_logger import info, warning, error


class _OwnerRef:
    """Thread-safe weak reference wrapper for QObject owner detection.

    Stores a plain reference for identity comparison and provides
    a liveness check without keeping the QObject alive.
    """

    __slots__ = ("_ref", "_uid")

    def __init__(self, owner: QObject) -> None:
        self._ref: weakref.ref = weakref.ref(owner)
        self._uid: int = id(owner)

    @property
    def is_dead(self) -> bool:
        """Check whether the referenced QObject has been deleted."""
        return self._ref() is None

    @property
    def uid(self) -> int:
        return self._uid

    def matches(self, owner: QObject) -> bool:
        """Check if this ref wraps the given owner QObject."""
        return self._uid == id(owner)


@dataclass
class _CallbackEntry:
    """Internal storage for a registered tick callback."""

    callback_id: str
    priority: int = 3
    every_n_ticks: int = 1
    owner_ref: Optional[_OwnerRef] = None
    use_fast_tick: bool = False

    # One of these is populated depending on callback type
    callback: Optional[Callable] = None  # Strong ref (for non-method callables)
    weak_method: Optional[weakref.WeakMethod] = None  # Weak ref (for bound methods)

    # Tick counter for every_n_ticks support
    _tick_counter: int = field(default=0, repr=False)

    def resolve(self) -> Optional[Callable]:
        """Resolve the callable, returning None if the weak ref is dead."""
        if self.weak_method is not None:
            cb = self.weak_method()
            if cb is None:
                return None
            return cb
        return self.callback


class FutureHandle:
    """Lightweight future returned by request_main_thread.

    Provides:
        - result(timeout=None) -> Any
        - done() -> bool
        - add_done_callback(cb)
    """

    __slots__ = ("_done", "_result", "_exception", "_callbacks", "_event")

    def __init__(self) -> None:
        self._done: bool = False
        self._result: Any = None
        self._exception: Optional[BaseException] = None
        self._callbacks: list[Callable[["FutureHandle"], None]] = []
        self._event: threading.Event = threading.Event()

    def add_done_callback(
        self, callback: Callable[["FutureHandle"], None]
    ) -> None:
        """Add a callback invoked when the future completes."""
        if self._done:
            try:
                callback(self)
            except Exception:
                pass
        else:
            self._callbacks.append(callback)

    def result(self, timeout: Optional[float] = None) -> Any:
        """Block until the result is available, then return it.

        Raises the stored exception if the callable raised.
        """
        self._event.wait(timeout=timeout)
        if self._exception is not None:
            raise self._exception
        return self._result

    def done(self) -> bool:
        return self._done

    def _set_result(self, value: Any) -> None:
        self._result = value
        self._done = True
        self._event.set()
        self._run_done_callbacks()

    def _set_exception(self, exc: BaseException) -> None:
        self._exception = exc
        self._done = True
        self._event.set()
        self._run_done_callbacks()

    def _run_done_callbacks(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception:
                pass


class HeartbeatManager(QObject):
    """Singleton heartbeat coordinator for main-thread periodic work.

    Manages two QTimer loops:
        - Normal tick (~30 fps / 33ms): all registered callbacks
        - Fast tick (~60 fps / 16ms): animation callbacks only

    Features:
        - Priority-ordered dispatch within each tick
        - Weak-reference callback storage via weakref.WeakMethod
        - Cross-thread request queue (thread-safe deque + main-thread drain)
        - Owner-aware lifecycle with automatic cleanup on destroy
        - Tick overrun detection and warning logging
        - Empty-tick optimization: timers stop when no callbacks registered
    """

    _instance: Optional["HeartbeatManager"] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    NORMAL_TICK_MS: int = 33  # ~30fps
    FAST_TICK_MS: int = 16  # ~60fps (animation only)
    _TICK_PRUNING_INTERVAL: int = 100  # prune dead weak refs every N ticks

    def __new__(cls, parent: Optional[QObject] = None) -> "HeartbeatManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, parent: Optional[QObject] = None) -> None:
        with self._lock:
            if HeartbeatManager._initialized:
                return
            HeartbeatManager._initialized = True

        super().__init__(parent)

        # Callback registry
        self._callbacks: dict[str, _CallbackEntry] = {}
        self._callback_lock: threading.RLock = threading.RLock()

        # Cross-thread dispatch queue
        self._pending_calls: deque = deque()
        self._pending_calls_lock: threading.RLock = threading.RLock()

        # Normal tick timer
        self._normal_timer: QTimer = QTimer(self)
        self._normal_timer.setInterval(self.NORMAL_TICK_MS)
        self._normal_timer.timeout.connect(self._process_normal_tick)
        self._normal_tick_interval: int = self.NORMAL_TICK_MS

        # Fast tick timer (only active when animation callbacks registered)
        self._fast_timer: QTimer = QTimer(self)
        self._fast_timer.setInterval(self.FAST_TICK_MS)
        self._fast_timer.timeout.connect(self._process_fast_tick)

        # Tick counters for pruning
        self._normal_tick_count: int = 0
        self._fast_tick_count: int = 0
        self._animation_callback_count: int = 0

        # Running state
        self._running: bool = False

        info("HeartbeatManager initialized")

    # ================================================================
    # Lifecycle
    # ================================================================

    def start(self) -> None:
        """Start the heartbeat timers.

        Timers only activate when at least one callback is registered
        (empty-tick optimization).
        """
        if self._running:
            return
        self._running = True
        with self._callback_lock:
            if self._callbacks:
                self._normal_timer.start()
        info("HeartbeatManager started")

    def stop(self) -> None:
        """Stop all heartbeat timers. Registered callbacks are preserved."""
        self._running = False
        self._normal_timer.stop()
        self._fast_timer.stop()

    def stop_all(self) -> None:
        """Stop timers and clear all registered callbacks and pending requests."""
        self.stop()
        with self._callback_lock:
            self._callbacks.clear()
        with self._pending_calls_lock:
            self._pending_calls.clear()
        self._animation_callback_count = 0
        info("HeartbeatManager stopped all")

    # ================================================================
    # Callback registration
    # ================================================================

    def register_tick_callback(
        self,
        callback_id: str,
        callback: Callable,
        priority: int = 3,
        every_n_ticks: int = 1,
        owner: Optional[QObject] = None,
        use_fast_tick: bool = False,
    ) -> str:
        """Register a periodic callback.

        Args:
            callback_id: Unique identifier for this callback.
            callback: The callable to invoke each tick.
            priority: 0 (highest) to 4 (lowest). Default 3.
            every_n_ticks: Fire the callback every N ticks. Default 1 (every tick).
            owner: Optional QObject for owner-aware lifecycle management.
            use_fast_tick: If True, runs at FAST_TICK_MS rate instead of normal.

        Returns:
            The callback_id as a registration token.

        Raises:
            ValueError: If callback_id is already registered.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self._callback_lock:
            if callback_id in self._callbacks:
                raise ValueError(
                    f"Callback '{callback_id}' is already registered"
                )

            # Attempt WeakMethod for bound methods, fall back to strong ref
            weak_method: Optional[weakref.WeakMethod] = None
            try:
                weak_method = weakref.WeakMethod(callback)
            except TypeError:
                pass

            owner_ref: Optional[_OwnerRef] = None
            if owner is not None:
                owner_ref = _OwnerRef(owner)
                try:
                    owner.destroyed.connect(self._on_owner_destroyed)
                except (RuntimeError, TypeError):
                    pass

            entry = _CallbackEntry(
                callback_id=callback_id,
                priority=max(0, min(4, priority)),
                every_n_ticks=max(1, every_n_ticks),
                owner_ref=owner_ref,
                use_fast_tick=use_fast_tick,
                callback=None if weak_method is not None else callback,
                weak_method=weak_method,
            )
            self._callbacks[callback_id] = entry

        if use_fast_tick:
            self._animation_callback_count += 1
            self._maybe_start_fast_timer()

        # Start normal timer if not running (empty-tick optimization)
        if self._running and not self._normal_timer.isActive():
            self._normal_timer.start()

        return callback_id

    def unregister_tick_callback(self, callback_id: str) -> bool:
        """Unregister a previously registered callback.

        Args:
            callback_id: The identifier used during registration.

        Returns:
            True if the callback was found and removed, False otherwise.
        """
        with self._callback_lock:
            entry = self._callbacks.pop(callback_id, None)

        if entry is None:
            return False

        if entry.use_fast_tick:
            self._animation_callback_count -= 1
            self._maybe_stop_fast_timer()

        # Stop normal timer if no more callbacks (empty-tick optimization)
        if self._running:
            self._maybe_stop_normal_timer()

        return True

    def unregister_all_for_owner(self, owner: QObject) -> int:
        """Unregister all callbacks registered with the given owner.

        Args:
            owner: The QObject whose callbacks should be removed.

        Returns:
            Number of callbacks removed.
        """
        with self._callback_lock:
            cids = [
                cid
                for cid, entry in self._callbacks.items()
                if entry.owner_ref is not None and entry.owner_ref.matches(owner)
            ]

        count = 0
        for cid in cids:
            if self.unregister_tick_callback(cid):
                count += 1
        return count

    def set_normal_tick_rate(self, fps: int) -> None:
        """Adjust the normal tick rate by specifying frames per second.

        Always updates the timer interval, regardless of active state.

        Args:
            fps: Target frames per second (minimum 1).
        """
        interval = max(1, int(1000 / max(fps, 1)))
        self._normal_tick_interval = interval
        self._normal_timer.setInterval(interval)

    # ================================================================
    # Cross-thread dispatch
    # ================================================================

    def request_main_thread(
        self, fn: Callable, priority: int = 5
    ) -> FutureHandle:
        """Schedule a callable for execution on the main thread.

        Thread-safe. The callable is queued and executed during the
        next heartbeat tick on the main thread.

        Uses QMetaObject.invokeMethod to start the timer on the main thread,
        making this safe to call from any thread.

        Args:
            fn: The callable to execute on the main thread.
            priority: Callback priority (0=highest, 5=lowest). Default 5.

        Returns:
            A FutureHandle that resolves when the callable completes.
        """
        future = FutureHandle()
        with self._pending_calls_lock:
            self._pending_calls.append((priority, fn, future))

        # Ensure normal timer is running to drain the queue.
        # Use invokeMethod to safely start the timer from any thread.
        if self._running:
            QMetaObject.invokeMethod(
                self._normal_timer,
                "start",
                Qt.QueuedConnection,
            )

        return future

    # ================================================================
    # Internal: tick processing
    # ================================================================

    def _process_normal_tick(self) -> None:
        """Process a single normal-rate heartbeat tick."""
        if not self._running:
            return

        # Drain cross-thread queue first
        self._drain_pending_queue()

        # Collect and sort callbacks by priority
        with self._callback_lock:
            if not self._callbacks:
                self._maybe_stop_normal_timer()
                return
            entries = list(self._callbacks.values())

        self._normal_tick_count += 1
        entries.sort(key=lambda e: e.priority)

        start = time.monotonic()
        dead_ids: list[str] = []

        for entry in entries:
            # Skip entries using fast tick (handled by fast timer)
            if entry.use_fast_tick:
                continue

            # Every-N-ticks gating
            if entry.every_n_ticks > 1:
                entry._tick_counter += 1
                if entry._tick_counter % entry.every_n_ticks != 0:
                    continue

            # Resolve and execute
            cb = entry.resolve()
            if cb is None:
                dead_ids.append(entry.callback_id)
                continue

            try:
                cb()
            except Exception as exc:
                warning(
                    f"Heartbeat: callback '{entry.callback_id}' raised {type(exc).__name__}: {exc}"
                )

        # Prune dead weak-ref callbacks
        if dead_ids:
            with self._callback_lock:
                for cid in dead_ids:
                    entry = self._callbacks.pop(cid, None)
                    if entry and entry.use_fast_tick:
                        self._animation_callback_count -= 1

        # Periodic pruning sweep
        if self._normal_tick_count % self._TICK_PRUNING_INTERVAL == 0:
            self._prune_dead_callbacks()

        # Tick overrun detection
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > self._normal_tick_interval:
            warning(
                f"Heartbeat: normal tick overrun "
                f"({elapsed_ms:.1f}ms > {self._normal_tick_interval}ms interval)"
            )

        # Empty-tick optimization
        if self._running:
            self._maybe_stop_normal_timer()

    def _process_fast_tick(self) -> None:
        """Process a single fast-rate heartbeat tick for animation callbacks."""
        if not self._running:
            return

        with self._callback_lock:
            entries = [e for e in self._callbacks.values() if e.use_fast_tick]

        if not entries:
            self._fast_timer.stop()
            return

        self._fast_tick_count += 1
        entries.sort(key=lambda e: e.priority)

        start = time.monotonic()
        dead_ids: list[str] = []

        for entry in entries:
            cb = entry.resolve()
            if cb is None:
                dead_ids.append(entry.callback_id)
                continue

            try:
                cb()
            except Exception as exc:
                warning(
                    f"Heartbeat: fast callback '{entry.callback_id}' "
                    f"raised {type(exc).__name__}: {exc}"
                )

        if dead_ids:
            with self._callback_lock:
                for cid in dead_ids:
                    entry = self._callbacks.pop(cid, None)
                    if entry and entry.use_fast_tick:
                        self._animation_callback_count -= 1
                if self._animation_callback_count <= 0:
                    self._fast_timer.stop()

        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > self.FAST_TICK_MS:
            warning(
                f"Heartbeat: fast tick overrun "
                f"({elapsed_ms:.1f}ms > {self.FAST_TICK_MS}ms interval)"
            )

    def _drain_pending_queue(self) -> None:
        """Execute all queued cross-thread requests on the main thread."""
        with self._pending_calls_lock:
            if not self._pending_calls:
                return
            calls = list(self._pending_calls)
            self._pending_calls.clear()

        # Sort by priority (lower number = higher priority)
        calls.sort(key=lambda x: x[0])

        for _priority, fn, future in calls:
            try:
                result = fn()
                future._set_result(result)
            except BaseException as exc:
                future._set_exception(exc)

    # ================================================================
    # Internal: owner lifecycle
    # ================================================================

    def _on_owner_destroyed(self) -> None:
        """Slot connected to owner.destroyed signals.

        Scans all registered callbacks and removes any whose owner
        QObject has been destroyed (dead weak ref or deleted C++ object).
        """
        with self._callback_lock:
            dead: list[str] = []
            for cid, entry in self._callbacks.items():
                if entry.owner_ref is None:
                    continue
                # Check weak ref liveness
                if entry.owner_ref.is_dead:
                    dead.append(cid)
                    continue
                # Double-check via QObject liveness
                owner = entry.owner_ref._ref()
                if owner is not None:
                    try:
                        owner.objectName()
                    except RuntimeError:
                        dead.append(cid)

        for cid in dead:
            self.unregister_tick_callback(cid)

    # ================================================================
    # Internal: pruning and helpers
    # ================================================================

    def _prune_dead_callbacks(self) -> None:
        """Periodic maintenance: remove entries with dead weak refs or owners."""
        with self._callback_lock:
            dead: list[str] = []
            for cid, entry in self._callbacks.items():
                # Check weak method
                if entry.weak_method is not None and entry.weak_method() is None:
                    dead.append(cid)
                    continue
                # Check owner liveness
                if entry.owner_ref is not None and entry.owner_ref.is_dead:
                    dead.append(cid)

            for cid in dead:
                entry = self._callbacks.pop(cid, None)
                if entry and entry.use_fast_tick:
                    self._animation_callback_count -= 1

    def _maybe_start_fast_timer(self) -> None:
        """Start the fast tick timer if animation callbacks are present."""
        if self._animation_callback_count > 0 and not self._fast_timer.isActive():
            self._fast_timer.start()

    def _maybe_stop_fast_timer(self) -> None:
        """Stop the fast tick timer if no animation callbacks remain."""
        if self._animation_callback_count <= 0 and self._fast_timer.isActive():
            self._fast_timer.stop()
            self._fast_tick_count = 0

    def _maybe_stop_normal_timer(self) -> None:
        """Stop the normal timer if no callbacks or pending calls remain.

        Empty-tick optimization: prevents the timer from firing uselessly.
        """
        with self._callback_lock:
            has_callbacks = bool(self._callbacks)
        has_pending = bool(self._pending_calls)
        if not has_callbacks and not has_pending:
            if self._normal_timer.isActive():
                self._normal_timer.stop()
