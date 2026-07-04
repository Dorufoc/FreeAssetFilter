#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 心跳管理器

主线程周期性任务的单例协调器。
提供双频率注册、优先级调度、跨线程请求队列和生命周期管理。

用法：
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
    """QObject 所有者的线程安全弱引用包装。

    存储原始引用用于身份比较，提供存活检查而不保持 QObject 存活。
    """

    __slots__ = ("_ref", "_uid")

    def __init__(self, owner: QObject) -> None:
        self._ref: weakref.ref = weakref.ref(owner)
        self._uid: int = id(owner)

    @property
    def is_dead(self) -> bool:
        """检查引用的 QObject 是否已被删除"""
        return self._ref() is None

    @property
    def uid(self) -> int:
        return self._uid

    def matches(self, owner: QObject) -> bool:
        """检查此引用是否包装了指定的 QObject"""
        return self._uid == id(owner)


@dataclass
class _CallbackEntry:
    """已注册的 tick 回调的内部存储"""

    callback_id: str
    priority: int = 3
    every_n_ticks: int = 1
    owner_ref: Optional[_OwnerRef] = None
    use_fast_tick: bool = False

    # 根据回调类型填充其中一个
    callback: Optional[Callable] = None  # 强引用（非方法可调用对象）
    weak_method: Optional[weakref.WeakMethod] = None  # 弱引用（绑定方法）

    # every_n_ticks 的 tick 计数器
    _tick_counter: int = field(default=0, repr=False)

    def resolve(self) -> Optional[Callable]:
        """解析可调用对象，弱引用失效时返回 None"""
        if self.weak_method is not None:
            cb = self.weak_method()
            if cb is None:
                return None
            return cb
        return self.callback


class FutureHandle:
    """request_main_thread 返回的轻量级 Future。

    提供：
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
        """添加 future 完成时的回调"""
        if self._done:
            try:
                callback(self)
            except Exception:
                pass
        else:
            self._callbacks.append(callback)

    def result(self, timeout: Optional[float] = None) -> Any:
        """阻塞直到结果可用，然后返回。

        如果可调用对象抛异常，则抛出存储的异常。
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
    """主线程周期性任务的单例心跳协调器。

    管理两个 QTimer 循环：
        - 普通 tick（~30fps / 33ms）：所有已注册的回调
        - 快速 tick（~60fps / 16ms）：仅动画回调

    特性：
        - 每个 tick 内按优先级排序分发
        - 通过 weakref.WeakMethod 存储弱引用回调
        - 跨线程请求队列（线程安全 deque + 主线程消耗）
        - 所有者感知生命周期，销毁时自动清理
        - tick 超时检测和警告日志
        - 空 tick 优化：无回调时停止定时器
    """

    _instance: Optional["HeartbeatManager"] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    NORMAL_TICK_MS: int = 33  # ~30fps
    FAST_TICK_MS: int = 16  # ~60fps（仅动画）
    _TICK_PRUNING_INTERVAL: int = 100  # 每 N 次 tick 清理失效弱引用

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
    # 生命周期
    # ================================================================

    def start(self) -> None:
        """启动心跳定时器。

        仅在有回调注册时激活定时器（空 tick 优化）。
        """
        if self._running:
            return
        self._running = True
        with self._callback_lock:
            if self._callbacks:
                self._normal_timer.start()
        info("HeartbeatManager started")

    def stop(self) -> None:
        """停止所有心跳定时器，保留已注册的回调"""
        self._running = False
        self._normal_timer.stop()
        self._fast_timer.stop()

    def stop_all(self) -> None:
        """停止定时器并清除所有已注册的回调和待处理请求"""
        self.stop()
        with self._callback_lock:
            self._callbacks.clear()
        with self._pending_calls_lock:
            self._pending_calls.clear()
        self._animation_callback_count = 0
        info("HeartbeatManager stopped all")

    # ================================================================
    # 回调注册
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
        """注册一个周期性回调。

        Args:
            callback_id: 该回调的唯一标识符。
            callback: 每次 tick 调用的可调用对象。
            priority: 0（最高）到 4（最低）。默认 3。
            every_n_ticks: 每 N 次 tick 触发一次。默认 1（每次触发）。
            owner: 用于所有者感知生命周期管理的 QObject。
            use_fast_tick: 若为 True，则使用 FAST_TICK_MS 频率而非普通频率。

        Returns:
            作为注册令牌的 callback_id。

        Raises:
            ValueError: 如果 callback_id 已注册。
        """
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self._callback_lock:
            if callback_id in self._callbacks:
                raise ValueError(
                    f"Callback '{callback_id}' is already registered"
                )

            # 优先使用 WeakMethod 绑定方法，回退到强引用
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

        # 若定时器未运行则启动（空 tick 优化）
        if self._running and not self._normal_timer.isActive():
            self._normal_timer.start()

        return callback_id

    def unregister_tick_callback(self, callback_id: str) -> bool:
        """取消注册之前注册的回调。

        Args:
            callback_id: 注册时使用的标识符。

        Returns:
            找到并移除返回 True，否则返回 False。
        """
        with self._callback_lock:
            entry = self._callbacks.pop(callback_id, None)

        if entry is None:
            return False

        if entry.use_fast_tick:
            self._animation_callback_count -= 1
            self._maybe_stop_fast_timer()

        # 无回调时停止普通定时器（空 tick 优化）
        if self._running:
            self._maybe_stop_normal_timer()

        return True

    def unregister_all_for_owner(self, owner: QObject) -> int:
        """取消注册指定所有者的所有回调。

        Args:
            owner: 需要移除回调的 QObject。

        Returns:
            移除的回调数量。
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
        """通过指定每秒帧数调整普通 tick 频率。

        无论活动状态如何，始终更新定时器间隔。

        Args:
            fps: 目标每秒帧数（最小 1）。
        """
        interval = max(1, int(1000 / max(fps, 1)))
        self._normal_tick_interval = interval
        self._normal_timer.setInterval(interval)

    # ================================================================
    # 跨线程调度
    # ================================================================

    def request_main_thread(
        self, fn: Callable, priority: int = 5
    ) -> FutureHandle:
        """调度一个可调用对象在主线程执行。

        线程安全。可调用对象被排队并在下一个心跳 tick 中在主线程执行。

        使用 QMetaObject.invokeMethod 在主线程启动定时器。

        Args:
            fn: 要在主线程执行的可调用对象。
            priority: 回调优先级（0=最高，5=最低）。默认 5。

        Returns:
            可调用对象完成时解析的 FutureHandle。
        """
        future = FutureHandle()
        with self._pending_calls_lock:
            self._pending_calls.append((priority, fn, future))

        # 确保普通定时器运行以消耗队列
        # 使用 invokeMethod 从任意线程安全启动定时器
        if self._running:
            QMetaObject.invokeMethod(
                self._normal_timer,
                "start",
                Qt.QueuedConnection,
            )

        return future

    # ================================================================
    # 内部：tick 处理
    # ================================================================

    def _process_normal_tick(self) -> None:
        """处理一个普通的 tick"""
        if not self._running:
            return

        # 优先处理跨线程队列
        self._drain_pending_queue()

        # 收集并按优先级排序回调
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
            # 跳过使用快速 tick 的条目（由快速定时器处理）
            if entry.use_fast_tick:
                continue

            # 每 N 次 tick 触发控制
            if entry.every_n_ticks > 1:
                entry._tick_counter += 1
                if entry._tick_counter % entry.every_n_ticks != 0:
                    continue

            # 解析并执行
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

        # 清理失效的弱引用回调
        if dead_ids:
            with self._callback_lock:
                for cid in dead_ids:
                    entry = self._callbacks.pop(cid, None)
                    if entry and entry.use_fast_tick:
                        self._animation_callback_count -= 1

        # 定期清理扫描
        if self._normal_tick_count % self._TICK_PRUNING_INTERVAL == 0:
            self._prune_dead_callbacks()

        # tick 超时检测
        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > self._normal_tick_interval:
            warning(
                f"Heartbeat: normal tick overrun "
                f"({elapsed_ms:.1f}ms > {self._normal_tick_interval}ms interval)"
            )

        # 空 tick 优化
        if self._running:
            self._maybe_stop_normal_timer()

    def _process_fast_tick(self) -> None:
        """处理单个快速 tick（仅动画回调）"""
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
        """在主线程执行所有排队的跨线程请求"""
        with self._pending_calls_lock:
            if not self._pending_calls:
                return
            calls = list(self._pending_calls)
            self._pending_calls.clear()

        # 按优先级排序（数字越小优先级越高）
        calls.sort(key=lambda x: x[0])

        for _priority, fn, future in calls:
            try:
                result = fn()
                future._set_result(result)
            except BaseException as exc:
                future._set_exception(exc)

    # ================================================================
    # 内部：所有者生命周期
    # ================================================================

    def _on_owner_destroyed(self) -> None:
        """连接到 owner.destroyed 信号的槽。

        扫描所有已注册回调，移除所有者 QObject 已销毁的条目（失效弱引用或已删除的 C++ 对象）。
        """
        with self._callback_lock:
            dead: list[str] = []
            for cid, entry in self._callbacks.items():
                if entry.owner_ref is None:
                    continue
                # 检查弱引用是否存活
                if entry.owner_ref.is_dead:
                    dead.append(cid)
                    continue
                # 通过 QObject 存活状态二次确认
                owner = entry.owner_ref._ref()
                if owner is not None:
                    try:
                        owner.objectName()
                    except RuntimeError:
                        dead.append(cid)

        for cid in dead:
            self.unregister_tick_callback(cid)

    # ================================================================
    # 内部：清理与辅助
    # ================================================================

    def _prune_dead_callbacks(self) -> None:
        """定期维护：移除失效弱引用或所有者已销毁的条目"""
        with self._callback_lock:
            dead: list[str] = []
            for cid, entry in self._callbacks.items():
                # 检查弱方法
                if entry.weak_method is not None and entry.weak_method() is None:
                    dead.append(cid)
                    continue
                # 检查所有者存活状态
                if entry.owner_ref is not None and entry.owner_ref.is_dead:
                    dead.append(cid)

            for cid in dead:
                entry = self._callbacks.pop(cid, None)
                if entry and entry.use_fast_tick:
                    self._animation_callback_count -= 1

    def _maybe_start_fast_timer(self) -> None:
        """存在动画回调时启动快速 tick 定时器"""
        if self._animation_callback_count > 0 and not self._fast_timer.isActive():
            self._fast_timer.start()

    def _maybe_stop_fast_timer(self) -> None:
        """无动画回调时停止快速 tick 定时器"""
        if self._animation_callback_count <= 0 and self._fast_timer.isActive():
            self._fast_timer.stop()
            self._fast_tick_count = 0

    def _maybe_stop_normal_timer(self) -> None:
        """无回调或待处理调用时停止普通定时器。

        空 tick 优化：防止定时器无意义地触发。
        """
        with self._callback_lock:
            has_callbacks = bool(self._callbacks)
        has_pending = bool(self._pending_calls)
        if not has_callbacks and not has_pending:
            if self._normal_timer.isActive():
                self._normal_timer.stop()
