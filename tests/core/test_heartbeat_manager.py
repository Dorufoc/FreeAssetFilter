# -*- coding: utf-8 -*-
"""
HeartbeatManager 单元测试
"""

import threading
import time
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def _reset_singleton():
    """Reset the HeartbeatManager singleton for test isolation."""
    from freeassetfilter.core.heartbeat_manager import HeartbeatManager

    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False


class TestHeartbeatManager:
    """HeartbeatManager 单元测试"""

    # ---------------------------------------------------------------
    # Singleton
    # ---------------------------------------------------------------

    def test_singleton(self, qapp):
        """单例模式测试 — 每次调用返回相同实例"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm1 = HeartbeatManager()
        hm2 = HeartbeatManager()

        assert hm1 is hm2
        _reset_singleton()

    def test_singleton_reset(self, qapp):
        """单例重置后应创建新实例"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm1 = HeartbeatManager()
        _reset_singleton()
        hm2 = HeartbeatManager()

        assert hm1 is not hm2
        _reset_singleton()

    # ---------------------------------------------------------------
    # Register / unregister
    # ---------------------------------------------------------------

    def test_register_and_unregister(self, qapp):
        """注册后回调触发，取消注册后不再触发"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 20
        hm._normal_tick_interval = 20
        hm.start()

        fired: list[int] = []

        def my_callback() -> None:
            fired.append(1)

        hm.register_tick_callback("test", my_callback)

        # Let the timer fire a few times
        QTest.qWait(80)

        assert len(fired) > 0, "Callback should have fired during wait"

        count_before = len(fired)

        # Unregister and verify it stops
        hm.unregister_tick_callback("test")
        QTest.qWait(80)

        assert len(fired) == count_before, "Callback should not fire after unregister"

        hm.stop_all()
        _reset_singleton()

    def test_register_duplicate_raises(self, qapp):
        """重复注册同一 ID 应抛出 ValueError"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.register_tick_callback("dup", lambda: None)

        with pytest.raises(ValueError):
            hm.register_tick_callback("dup", lambda: None)

        hm.stop_all()
        _reset_singleton()

    def test_unregister_nonexistent_returns_false(self, qapp):
        """取消注册不存在的回调应返回 False"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        result = hm.unregister_tick_callback("does_not_exist")

        assert result is False
        _reset_singleton()

    # ---------------------------------------------------------------
    # Priority ordering
    # ---------------------------------------------------------------

    def test_priority_ordering(self, qapp):
        """高优先级回调应在低优先级之前执行"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 20
        hm._normal_tick_interval = 20
        hm.start()

        execution_order: list[str] = []

        hm.register_tick_callback("low", lambda: execution_order.append("C"), priority=4)
        hm.register_tick_callback("high", lambda: execution_order.append("A"), priority=0)
        hm.register_tick_callback("mid", lambda: execution_order.append("B"), priority=2)

        QTest.qWait(80)

        if len(execution_order) >= 3:
            idx_a = execution_order.index("A")
            idx_b = execution_order.index("B")
            idx_c = execution_order.index("C")
            assert idx_a < idx_b < idx_c, (
                f"Priority ordering violated: {execution_order}"
            )

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Fast tick (animation)
    # ---------------------------------------------------------------

    def test_fast_tick_animation_start_stop(self, qapp):
        """Fast tick 定时器随 animation 回调的注册/取消而启动/停止"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.start()

        assert not hm._fast_timer.isActive(), "Fast timer should not be active initially"

        hm.register_tick_callback("anim", lambda: None, use_fast_tick=True)

        assert hm._animation_callback_count == 1
        assert hm._fast_timer.isActive(), "Fast timer should start with animation callback"

        hm.unregister_tick_callback("anim")

        assert hm._animation_callback_count == 0
        assert not hm._fast_timer.isActive(), "Fast timer should stop without animation callbacks"

        hm.stop_all()
        _reset_singleton()

    def test_fast_tick_callback_fires(self, qapp):
        """注册到 fast tick 的回调应被执行"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.start()

        fired: list[int] = []

        def anim_cb() -> None:
            fired.append(1)

        hm.register_tick_callback("anim", anim_cb, use_fast_tick=True)

        QTest.qWait(50)

        assert len(fired) > 0, "Animation callback should have fired"

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Empty-tick optimization
    # ---------------------------------------------------------------

    def test_empty_tick_optimization(self, qapp):
        """无回调注册时 QTimer 应停止"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 10
        hm._normal_tick_interval = 10

        # Before start, timer should be inactive
        hm.start()
        # No callbacks registered, so timer should not start
        assert not hm._normal_timer.isActive(), "Timer should not start without callbacks"

        # Register a callback, timer should start
        hm.register_tick_callback("test", lambda: None)
        QTest.qWait(20)
        assert hm._normal_timer.isActive(), "Timer should be active with callbacks"

        # Unregister, timer should stop on next tick
        hm.unregister_tick_callback("test")
        QTest.qWait(30)
        assert not hm._normal_timer.isActive(), "Timer should stop when no callbacks remain"

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Error isolation
    # ---------------------------------------------------------------

    def test_error_isolation(self, qapp):
        """一个回调抛出异常不应阻止其他回调执行"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 20
        hm._normal_tick_interval = 20
        hm.start()

        results: list[str] = []

        def bad_cb() -> None:
            raise ValueError("intentional failure")

        def good_cb() -> None:
            results.append("ok")

        hm.register_tick_callback("bad", bad_cb, priority=0)
        hm.register_tick_callback("good", good_cb, priority=1)

        QTest.qWait(80)

        assert "ok" in results, "Good callback should have fired despite bad callback"

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Cross-thread dispatch (request_main_thread)
    # ---------------------------------------------------------------

    def test_request_main_thread(self, qapp):
        """request_main_thread 应在主线程执行指定函数"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.set_normal_tick_rate(100)
        hm.start()

        main_thread_id = threading.get_ident()
        executed: list[int] = []

        def check_thread() -> None:
            executed.append(threading.get_ident())

        hm.request_main_thread(check_thread)
        QTest.qWait(50)

        assert len(executed) > 0, "Function should have been executed"
        assert executed[0] == main_thread_id, "Function did not run on main thread"

        hm.stop_all()
        _reset_singleton()

    def test_request_main_thread_future_result(self, qapp):
        """request_main_thread 返回的 FutureHandle.result() 应返回函数结果"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.set_normal_tick_rate(100)
        hm.start()

        future = hm.request_main_thread(lambda: 42)
        QTest.qWait(50)

        assert future.done()
        assert future.result() == 42

        hm.stop_all()
        _reset_singleton()

    def test_request_main_thread_future_exception(self, qapp):
        """request_main_thread 函数抛出异常时 FutureHandle 应传播"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.set_normal_tick_rate(100)
        hm.start()

        def will_raise() -> None:
            raise ValueError("test error")

        future = hm.request_main_thread(will_raise)
        QTest.qWait(50)

        assert future.done()
        with pytest.raises(ValueError, match="test error"):
            future.result()

        hm.stop_all()
        _reset_singleton()

    def test_request_main_thread_from_background(self, qapp):
        """从后台线程调用 request_main_thread 应仍能在主线程执行"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.set_normal_tick_rate(100)
        hm.start()

        main_thread_id = threading.get_ident()
        executed: list[int] = []

        def bg_thread() -> None:
            future = hm.request_main_thread(
                lambda: executed.append(threading.get_ident())
            )
            future.result(timeout=3.0)

        thread = threading.Thread(target=bg_thread, daemon=True)
        thread.start()

        # Poll: process Qt events on main thread while bg thread is alive
        # (thread.join() would block event processing, preventing timer dispatch)
        import time as _time
        deadline = _time.monotonic() + 5.0
        while thread.is_alive() and _time.monotonic() < deadline:
            QTest.qWait(20)

        thread.join(timeout=1.0)

        assert len(executed) > 0, "Function should have been executed"
        assert executed[0] == main_thread_id, "Function did not run on main thread"

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Owner-aware lifecycle
    # ---------------------------------------------------------------

    def test_unregister_all_for_owner(self, qapp):
        """unregister_all_for_owner 应移除指定 QObject 的所有回调"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        owner = QObject()

        hm.register_tick_callback("cb1", lambda: None, owner=owner)
        hm.register_tick_callback("cb2", lambda: None, owner=owner)
        hm.register_tick_callback("cb3", lambda: None)  # No owner

        count = hm.unregister_all_for_owner(owner)

        assert count == 2
        assert hm._callbacks.get("cb3") is not None
        assert hm._callbacks.get("cb1") is None
        assert hm._callbacks.get("cb2") is None

        _reset_singleton()

    def test_unregister_all_for_owner_returns_zero(self, qapp):
        """未知 owner 调用 unregister_all_for_owner 应返回 0"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        owner = QObject()
        other = QObject()

        hm.register_tick_callback("cb", lambda: None, owner=owner)
        count = hm.unregister_all_for_owner(other)

        assert count == 0

        _reset_singleton()

    def test_owner_destroyed_cleans_up(self, qapp):
        """owner 的 QObject 销毁时应自动清理其回调"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 10
        hm._normal_tick_interval = 10
        hm.start()

        owner = QObject()
        fired: list[int] = []

        def owner_cb() -> None:
            fired.append(1)

        hm.register_tick_callback("owner_cb", owner_cb, owner=owner, priority=0)
        hm.register_tick_callback("independent", lambda: None)

        # Verify both callbacks are registered
        assert "owner_cb" in hm._callbacks
        assert "independent" in hm._callbacks

        # Delete the owner and process events
        owner.deleteLater()
        QTest.qWait(50)

        # owner_cb should be removed but independent remains
        assert "owner_cb" not in hm._callbacks or hm._callbacks.get(
            "owner_cb"
        ) is None
        assert "independent" in hm._callbacks

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Tick overrun detection
    # ---------------------------------------------------------------

    def test_tick_overrun_logging(self, qapp):
        """超过 tick 时间预算的回调应记录 warning 日志"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 5
        hm._normal_tick_interval = 5
        hm._normal_timer.setInterval(5)
        hm.start()

        def slow_callback() -> None:
            time.sleep(0.03)  # 30ms > 5ms budget

        hm.register_tick_callback("slow", slow_callback, priority=0)

        with patch(
            "freeassetfilter.core.heartbeat_manager.warning"
        ) as mock_warning:
            QTest.qWait(100)

            overrun_messages = [
                str(call) for call in mock_warning.call_args_list
                if "overrun" in str(call)
            ]
            assert len(overrun_messages) > 0, (
                f"Expected overrun warnings, got: {mock_warning.call_args_list}"
            )

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # FutureHandle
    # ---------------------------------------------------------------

    def test_future_handle_done_callbacks(self, qapp):
        """FutureHandle.add_done_callback 应在完成时触发"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import FutureHandle

        future = FutureHandle()
        cb_called: list[bool] = []

        def done_cb(f):
            cb_called.append(True)

        future.add_done_callback(done_cb)
        assert len(cb_called) == 0

        future._set_result(42)
        assert len(cb_called) == 1
        assert future.done()
        assert future.result() == 42

    def test_future_handle_done_callback_on_completed(self, qapp):
        """对已完成的 FutureHandle 添加回调应立即触发"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import FutureHandle

        future = FutureHandle()
        future._set_result("done")
        cb_called: list[bool] = []

        def done_cb(f):
            cb_called.append(True)

        future.add_done_callback(done_cb)
        assert len(cb_called) == 1

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    def test_start_stop(self, qapp):
        """start/stop 生命周期管理"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()

        assert not hm._running

        hm.start()
        assert hm._running

        hm.stop()
        assert not hm._running

        _reset_singleton()

    def test_stop_all_clears_all(self, qapp):
        """stop_all 应停止定时器并清除所有注册"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.register_tick_callback("a", lambda: None)
        hm.register_tick_callback("b", lambda: None, use_fast_tick=True)

        hm.stop_all()

        assert len(hm._callbacks) == 0
        assert not hm._normal_timer.isActive()
        assert not hm._fast_timer.isActive()
        assert hm._animation_callback_count == 0

        _reset_singleton()

    # ---------------------------------------------------------------
    # every_n_ticks
    # ---------------------------------------------------------------

    def test_every_n_ticks(self, qapp):
        """every_n_ticks=N 的回调应每 N 次 tick 触发一次"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.NORMAL_TICK_MS = 5
        hm._normal_tick_interval = 5
        hm._normal_timer.setInterval(5)
        hm.start()

        # Register a callback that fires every 5 ticks
        every_5_count: list[int] = [0]
        always_count: list[int] = [0]

        hm.register_tick_callback("every5", lambda: every_5_count.__setitem__(0, every_5_count[0] + 1), every_n_ticks=5)
        hm.register_tick_callback("always", lambda: always_count.__setitem__(0, always_count[0] + 1), every_n_ticks=1)

        QTest.qWait(100)

        always_fires = always_count[0]
        every5_fires = every_5_count[0]

        # The always callback should fire roughly 5x more than every5
        # At 5ms interval, ~20 ticks per 100ms
        # Always: ~20, Every5: ~4
        assert always_fires >= every5_fires * 3, (
            f"every_n_ticks not working: always={always_fires}, every5={every5_fires}"
        )
        assert every5_fires >= 1, "every_5 callback should have fired at least once"

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # set_normal_tick_rate
    # ---------------------------------------------------------------

    def test_set_normal_tick_rate(self, qapp):
        """set_normal_tick_rate 应更新 tick 间隔"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.start()

        # Default should be 33ms
        assert hm._normal_tick_interval == 33

        hm.set_normal_tick_rate(60)
        assert hm._normal_tick_interval == 16  # 1000/60 ≈ 16

        hm.set_normal_tick_rate(10)
        assert hm._normal_tick_interval == 100  # 1000/10 = 100

        hm.stop_all()
        _reset_singleton()

    # ---------------------------------------------------------------
    # Callback type handling
    # ---------------------------------------------------------------

    def test_bound_method_weak_ref(self, qapp):
        """使用 bound method 注册时内部应使用 WeakMethod"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()

        class Handler(QObject):
            def tick(self) -> None:
                pass

        handler = Handler()
        hm.register_tick_callback("bound", handler.tick, priority=0)

        entry = hm._callbacks.get("bound")
        assert entry is not None
        assert entry.weak_method is not None, "Bound method should use WeakMethod"
        assert entry.callback is None, "Bound method should not store strong ref"

        hm.stop_all()
        _reset_singleton()

    def test_lambda_strong_ref(self, qapp):
        """使用 lambda 注册时应使用强引用"""
        _reset_singleton()
        from freeassetfilter.core.heartbeat_manager import HeartbeatManager

        hm = HeartbeatManager()
        hm.register_tick_callback("lam", lambda: None)

        entry = hm._callbacks.get("lam")
        assert entry is not None
        assert entry.weak_method is None, "Lambda should not use WeakMethod"
        assert entry.callback is not None, "Lambda should store strong ref"

        hm.stop_all()
        _reset_singleton()
