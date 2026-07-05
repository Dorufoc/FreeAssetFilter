# -*- coding: utf-8 -*-
"""
Thread safety integration tests for HeartbeatManager.

Tests concurrent register/unregister operations, tick delivery to
registered components, and tick suppression after unregistration —
all from background threads (QThreadPool) to verify the heartbeat
manager's internal locking and cross-thread dispatch are correct.
"""

from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import QThreadPool

from freeassetfilter.core.heartbeat_manager import HeartbeatManager


# ================================================================
# Helpers: singleton lifecycle for test isolation
# ================================================================


def _reset_heartbeat_singleton() -> None:
    """Reset HeartbeatManager singleton state for test isolation.

    Must be called before and after each test that interacts with
    HeartbeatManager to guarantee no cross-test leakage.
    """
    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False


def _cleanup_heartbeat(hm: HeartbeatManager | None) -> None:
    """Stop timers, clear callbacks, and reset singleton state."""
    if hm is not None:
        hm.stop_all()
    _reset_heartbeat_singleton()


# ================================================================
# Tests
# ================================================================


class TestHeartbeatThreadSafety:
    """Thread safety tests for HeartbeatManager."""

    def test_concurrent_operations_no_deadlock(self, qapp) -> None:
        """100 concurrent register/unregister ops from QThreadPool, no deadlocks.

        100 worker tasks (one per QThreadPool thread) each register and
        immediately unregister a tick callback under concurrent load.
        Verifies all workers complete within 30 seconds with zero errors.
        """
        _reset_heartbeat_singleton()
        hm = HeartbeatManager()
        hm.start()

        results: list[int] = []
        errors: list[tuple[int, str]] = []
        lock: threading.Lock = threading.Lock()

        def worker_task(idx: int) -> None:
            try:
                cid = f"concurrent_test_{idx}"
                hm.register_tick_callback(cid, lambda: None, priority=4, owner=None)
                hm.unregister_tick_callback(cid)
                with lock:
                    results.append(idx)
            except Exception as e:
                with lock:
                    errors.append((idx, str(e)))

        pool = QThreadPool.globalInstance()
        for i in range(100):
            pool.start(lambda i=i: worker_task(i))

        # Wait for all workers, pumping Qt events to keep the main thread alive
        timeout: float = 30.0
        start: float = time.monotonic()
        while len(results) + len(errors) < 100 and time.monotonic() - start < timeout:
            qapp.processEvents()
            time.sleep(0.01)

        _cleanup_heartbeat(hm)

        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 100, (
            f"Only {len(results)}/100 completed within {timeout}s"
        )

    def test_tick_delivery_to_component(self, qapp) -> None:
        """Component registers with HeartbeatManager, verify tick delivery.

        A simple counter callback is registered and the test waits for
        at least one tick to be delivered via the normal-rate timer
        (33 ms interval). Proves the timer → callback path works.
        """
        _reset_heartbeat_singleton()
        hm = HeartbeatManager()
        hm.start()

        tick_count: list[int] = [0]

        def tick_callback() -> None:
            tick_count[0] += 1

        hm.register_tick_callback("tick_test", tick_callback, priority=4, owner=None)

        # Wait for at least 3 ticks (33 ms each → ≈100 ms normal case)
        timeout: float = 2.0
        start: float = time.monotonic()
        while tick_count[0] < 3 and time.monotonic() - start < timeout:
            qapp.processEvents()
            time.sleep(0.01)

        _cleanup_heartbeat(hm)

        assert tick_count[0] >= 1, f"No ticks delivered, count={tick_count[0]}"

    def test_no_ticks_after_unregister(self, qapp) -> None:
        """Component unregisters, verify no more ticks arrive.

        Register a counter callback, confirm ticks arrive, unregister,
        then wait long enough (200 ms >> 33 ms timer interval) and
        confirm the counter did not increase.
        """
        _reset_heartbeat_singleton()
        hm = HeartbeatManager()
        hm.start()

        tick_count: list[int] = [0]

        def tick_callback() -> None:
            tick_count[0] += 1

        hm.register_tick_callback(
            "unregister_test", tick_callback, priority=4, owner=None
        )

        # Wait for at least 2 ticks to confirm callback is live
        timeout: float = 2.0
        start: float = time.monotonic()
        while tick_count[0] < 2 and time.monotonic() - start < timeout:
            qapp.processEvents()
            time.sleep(0.01)

        count_before: int = tick_count[0]
        hm.unregister_tick_callback("unregister_test")

        # Wait long enough that any pending timer would have fired
        time.sleep(0.2)
        for _ in range(10):
            qapp.processEvents()
            time.sleep(0.01)

        count_after: int = tick_count[0]

        _cleanup_heartbeat(hm)

        assert count_after == count_before, (
            f"Ticks continued after unregister: {count_before} -> {count_after}"
        )
