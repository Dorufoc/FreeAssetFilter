# -*- coding: utf-8 -*-
# targets: core.managers.heartbeat_manager
"""``HeartbeatManager``（core/managers/heartbeat_manager.py）单元测试。

覆盖（方法矩阵：happy + boundary/error 各至少一条）：

* 单例 / 生命周期（start/stop/stop_all 幂等，回调抛异常不影响 stop_all）
* 注册 / 注销回调（重复 ID ValueError、非可调用 TypeError、
  不存在 ID 返回 False）
* 定时触发（普通 tick / fast tick、优先级排序、
  every_n_ticks、空 tick 优化、错误隔离）
* ``set_normal_tick_rate`` 频率换算（含 0/负数边界）
* 所有者生命周期（``unregister_all_for_owner``、owner 销毁清理）
* 跨线程调度 ``request_main_thread`` + ``FutureHandle``
* **线程安全**：50 个并发注册 / 注销（threading + Barrier），
  之后回调计数保持一致

所有真实 tick 等待均走 ``QTest.qWait``（有界，由 pytest-timeout
30s 硬杀兜底）；后台线程一律 daemon=True 且 join 带超时。
"""

from __future__ import annotations

import threading
import time
from typing import Any, List

import pytest
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest

from freeassetfilter.core.managers.heartbeat_manager import (
    FutureHandle,
    HeartbeatManager,
)

_WORKER_COUNT: int = 50


def _reset_heartbeat_singleton() -> None:
    """手动重置 HeartbeatManager 单例（供少量非 fixture 测试使用）。"""
    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False


def _make_heartbeat() -> HeartbeatManager:
    """创建全新的 HeartbeatManager（调用方负责 stop_all + 重置）。"""
    _reset_heartbeat_singleton()
    return HeartbeatManager()


def _wait_for(condition: Any, timeout: float = 5.0, wait_ms: int = 20) -> None:
    """带超时地轮询条件并在等待间隔中处理 Qt 事件。

    Args:
        condition: 返回真值即视为满足的可调用对象。
        timeout: 最大等待秒数。
        wait_ms: 每轮 QTest.qWait 的毫秒数。
    """
    deadline: float = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        QTest.qWait(wait_ms)
    raise AssertionError("条件未在超时内满足")


# =============================================================================
# 单例 / 生命周期
# =============================================================================
class TestSingletonAndLifecycle:
    """单例与周期生命周期"""

    def test_singleton_returns_same_instance(self, heartbeat_manager: Any) -> None:
        """重复构造返回同一实例。"""
        again: HeartbeatManager = HeartbeatManager()
        assert again is heartbeat_manager

    def test_start_stop_lifecycle(self, qapp: Any) -> None:
        """start/stop 切换运行状态，不抛异常。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            assert hm._running is False
            hm.start()
            assert hm._running is True
            hm.start()  # 幂等：重复 start 不抛
            hm.stop()
            assert hm._running is False
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_stop_all_idempotent(self, qapp: Any) -> None:
        """stop_all 可连续调用且清除全部回调与定时器。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            hm.register_tick_callback("a", lambda: None)
            hm.register_tick_callback("b", lambda: None, use_fast_tick=True)
            hm.start()

            hm.stop_all()
            assert len(hm._callbacks) == 0
            assert not hm._normal_timer.isActive()
            assert not hm._fast_timer.isActive()
            assert hm._animation_callback_count == 0

            hm.stop_all()  # 幂等
        finally:
            _reset_heartbeat_singleton()

    def test_stop_all_after_callback_throws(self, heartbeat_manager: Any) -> None:
        """QA 场景：tick 期间回调抛异常，stop_all 必须干净完成。"""
        def bad_cb() -> None:
            raise ValueError("intentional failure")

        heartbeat_manager.NORMAL_TICK_MS = 5
        heartbeat_manager._normal_tick_interval = 5
        heartbeat_manager._normal_timer.setInterval(5)
        heartbeat_manager.register_tick_callback("bad", bad_cb)

        QTest.qWait(40)
        # 回调抛异常不影响 stop_all。
        heartbeat_manager.stop_all()
        assert len(heartbeat_manager._callbacks) == 0


# =============================================================================
# 注册 / 注销
# =============================================================================
class TestRegisterUnregister:
    """回调注册与注销"""

    def test_register_and_unregister_timer_fires(self, heartbeat_manager: Any) -> None:
        """注册后定时触发，注销后不再触发。"""
        heartbeat_manager.NORMAL_TICK_MS = 20
        heartbeat_manager._normal_tick_interval = 20
        fired: List[int] = []

        def my_callback() -> None:
            fired.append(1)

        heartbeat_manager.register_tick_callback("test", my_callback)
        _wait_for(lambda: len(fired) > 0, timeout=2.0)

        count_before: int = len(fired)
        heartbeat_manager.unregister_tick_callback("test")
        QTest.qWait(60)
        assert len(fired) == count_before

    def test_duplicate_register_raises_value_error(
        self, heartbeat_manager: Any
    ) -> None:
        """边界：重复 ID 注册抛 ValueError。"""
        heartbeat_manager.register_tick_callback("dup", lambda: None)
        with pytest.raises(ValueError, match="already registered"):
            heartbeat_manager.register_tick_callback("dup", lambda: None)

    def test_register_non_callable_raises_type_error(
        self, heartbeat_manager: Any
    ) -> None:
        """边界：非可调用对象注册抛 TypeError。"""
        with pytest.raises(TypeError, match="callable"):
            heartbeat_manager.register_tick_callback("x", "not-a-callable")  # type: ignore[arg-type]

    def test_unregister_nonexistent_returns_false(
        self, heartbeat_manager: Any
    ) -> None:
        """边界：注销不存在的 ID 返回 False。"""
        assert heartbeat_manager.unregister_tick_callback("nope") is False

    def test_unregister_existing_returns_true(self, heartbeat_manager: Any) -> None:
        """happy：注销已注册回调返回 True。"""
        heartbeat_manager.register_tick_callback("ok", lambda: None)
        assert heartbeat_manager.unregister_tick_callback("ok") is True


# =============================================================================
# 定时触发
# =============================================================================
class TestTicking:
    """tick 分发语义"""

    def test_priority_ordering(self, heartbeat_manager: Any) -> None:
        """高优先级回调先执行（同一 tick 内按 priority 升序）。"""
        heartbeat_manager.NORMAL_TICK_MS = 20
        heartbeat_manager._normal_tick_interval = 20
        execution_order: List[str] = []

        heartbeat_manager.register_tick_callback("low", lambda: execution_order.append("C"), priority=4)
        heartbeat_manager.register_tick_callback("high", lambda: execution_order.append("A"), priority=0)
        heartbeat_manager.register_tick_callback("mid", lambda: execution_order.append("B"), priority=2)

        _wait_for(lambda: len(execution_order) >= 3, timeout=2.0)
        idx_a: int = execution_order.index("A")
        idx_b: int = execution_order.index("B")
        idx_c: int = execution_order.index("C")
        assert idx_a < idx_b < idx_c

    def test_error_isolation(self, heartbeat_manager: Any) -> None:
        """一个回调抛异常不影响其他回调执行。"""
        heartbeat_manager.NORMAL_TICK_MS = 20
        heartbeat_manager._normal_tick_interval = 20
        results: List[str] = []

        def bad_cb() -> None:
            raise ValueError("intentional")

        heartbeat_manager.register_tick_callback("bad", bad_cb, priority=0)
        heartbeat_manager.register_tick_callback("good", lambda: results.append("ok"), priority=1)

        _wait_for(lambda: results == ["ok"], timeout=2.0)

    def test_every_n_ticks_fires_less_frequently(self, heartbeat_manager: Any) -> None:
        """every_n_ticks=5 的回调触发频率显著低于 every tick 回调。"""
        heartbeat_manager.NORMAL_TICK_MS = 5
        heartbeat_manager._normal_tick_interval = 5
        heartbeat_manager._normal_timer.setInterval(5)
        every_5: List[int] = [0]
        always: List[int] = [0]

        heartbeat_manager.register_tick_callback(
            "every5", lambda: every_5.__setitem__(0, every_5[0] + 1), every_n_ticks=5
        )
        heartbeat_manager.register_tick_callback(
            "always", lambda: always.__setitem__(0, always[0] + 1), every_n_ticks=1
        )

        _wait_for(lambda: always[0] >= 10, timeout=3.0)
        assert every_5[0] >= 1
        assert always[0] >= every_5[0] * 3, (
            f"every_n_ticks 未生效: always={always[0]}, every5={every_5[0]}"
        )

    def test_fast_tick_timer_start_stop(self, heartbeat_manager: Any) -> None:
        """fast tick 定时器随动画回调注册/注销而启动/停止。"""
        assert not heartbeat_manager._fast_timer.isActive()
        heartbeat_manager.register_tick_callback("anim", lambda: None, use_fast_tick=True)
        assert heartbeat_manager._animation_callback_count == 1
        assert heartbeat_manager._fast_timer.isActive()

        heartbeat_manager.unregister_tick_callback("anim")
        assert heartbeat_manager._animation_callback_count == 0
        assert not heartbeat_manager._fast_timer.isActive()

    def test_fast_tick_callback_fires(self, heartbeat_manager: Any) -> None:
        """注册到 fast tick 的回调应被周期性执行。"""
        fired: List[int] = []

        heartbeat_manager.register_tick_callback(
            "anim", lambda: fired.append(1), use_fast_tick=True
        )
        _wait_for(lambda: len(fired) > 0, timeout=2.0)

    def test_empty_tick_optimization(self, heartbeat_manager: Any) -> None:
        """无可注册回调时定时器不启动；回调清零后定时器停止。"""
        heartbeat_manager.NORMAL_TICK_MS = 10
        heartbeat_manager._normal_tick_interval = 10
        heartbeat_manager._normal_timer.setInterval(10)

        assert not heartbeat_manager._normal_timer.isActive()

        heartbeat_manager.register_tick_callback("test", lambda: None)
        _wait_for(lambda: heartbeat_manager._normal_timer.isActive(), timeout=1.0)

        heartbeat_manager.unregister_tick_callback("test")
        _wait_for(
            lambda: not heartbeat_manager._normal_timer.isActive(), timeout=2.0
        )

    def test_set_normal_tick_rate(self, heartbeat_manager: Any) -> None:
        """频率换算：60fps→16ms、10fps→100ms、默认 33ms。"""
        assert heartbeat_manager._normal_tick_interval == 33
        heartbeat_manager.set_normal_tick_rate(60)
        assert heartbeat_manager._normal_tick_interval == 16
        heartbeat_manager.set_normal_tick_rate(10)
        assert heartbeat_manager._normal_tick_interval == 100

    def test_set_normal_tick_rate_non_positive_clamps(
        self, heartbeat_manager: Any
    ) -> None:
        """边界：fps<=0 被钳制为 1，结果为 1000ms 且不抛异常。"""
        heartbeat_manager.set_normal_tick_rate(0)
        assert heartbeat_manager._normal_tick_interval == 1000
        heartbeat_manager.set_normal_tick_rate(-3)
        assert heartbeat_manager._normal_tick_interval == 1000


# =============================================================================
# 所有者生命周期
# =============================================================================
class TestOwnerLifecycle:
    """owner 绑定回谝的自动清理"""

    def test_unregister_all_for_owner(self, qapp: Any) -> None:
        """unregister_all_for_owner 移除指定所有者的全部回调。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            owner = QObject()
            hm.register_tick_callback("cb1", lambda: None, owner=owner)
            hm.register_tick_callback("cb2", lambda: None, owner=owner)
            hm.register_tick_callback("cb3", lambda: None)

            count: int = hm.unregister_all_for_owner(owner)
            assert count == 2
            assert "cb1" not in hm._callbacks
            assert "cb2" not in hm._callbacks
            assert "cb3" in hm._callbacks
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_unregister_all_for_owner_unknown_returns_zero(self, qapp: Any) -> None:
        """边界：未知 owner 返回 0。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            owner = QObject()
            hm.register_tick_callback("cb", lambda: None, owner=owner)
            assert hm.unregister_all_for_owner(QObject()) == 0
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_owner_destroyed_cleans_up_callbacks(self, qapp: Any) -> None:
        """owner 销毁后其回调整被移除，无主回调保留。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            hm.start()
            owner = QObject()
            hm.register_tick_callback("owner_cb", lambda: None, owner=owner)
            hm.register_tick_callback("independent", lambda: None)

            owner.deleteLater()
            QTest.qWait(80)

            assert "owner_cb" not in hm._callbacks
            assert "independent" in hm._callbacks
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_bound_method_uses_weak_reference(self, qapp: Any) -> None:
        """边界：绑定方法走 WeakMethod，不持强引用。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            class Handler(QObject):
                def tick(self) -> None:
                    pass

            handler = Handler()
            hm.register_tick_callback("bound", handler.tick)
            entry = hm._callbacks.get("bound")
            assert entry is not None
            assert entry.weak_method is not None
            assert entry.callback is None
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_lambda_uses_strong_reference(self, qapp: Any) -> None:
        """边界：lambda 无法弱引用，回退到强引用。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            hm.register_tick_callback("lam", lambda: None)
            entry = hm._callbacks.get("lam")
            assert entry is not None
            assert entry.weak_method is None
            assert entry.callback is not None
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()


# =============================================================================
# 跨线程调度（request_main_thread + FutureHandle）
# =============================================================================
class TestCrossThreadDispatch:
    """跨线程请求队列"""

    def test_request_main_thread_executes_on_main_thread(
        self, heartbeat_manager: Any
    ) -> None:
        """请求在主线程执行（与调用线程不同的后台线程发出的请求）。"""
        heartbeat_manager.set_normal_tick_rate(100)
        main_thread_id: int = threading.get_ident()
        executed: List[int] = []

        heartbeat_manager.request_main_thread(
            lambda: executed.append(threading.get_ident())
        )
        _wait_for(lambda: len(executed) > 0, timeout=2.0)
        assert executed[0] == main_thread_id

    def test_request_main_thread_future_result(self, heartbeat_manager: Any) -> None:
        """FutureHandle.result() 返回函数结果。"""
        heartbeat_manager.set_normal_tick_rate(100)
        future: FutureHandle = heartbeat_manager.request_main_thread(lambda: 42)
        _wait_for(lambda: future.done(), timeout=2.0)
        assert future.result() == 42

    def test_request_main_thread_future_exception(self, heartbeat_manager: Any) -> None:
        """FutureHandle 传播函数抛出的异常。"""
        heartbeat_manager.set_normal_tick_rate(100)

        def will_raise() -> None:
            raise ValueError("test error")

        future: FutureHandle = heartbeat_manager.request_main_thread(will_raise)
        _wait_for(lambda: future.done(), timeout=2.0)
        with pytest.raises(ValueError, match="test error"):
            future.result()

    def test_request_main_thread_from_background_thread(
        self, heartbeat_manager: Any
    ) -> None:
        """后台线程请求也能在主线程执行并回填结果。"""
        heartbeat_manager.set_normal_tick_rate(100)
        main_thread_id: int = threading.get_ident()
        executed: List[int] = []
        thread_result: List[Any] = []

        def bg_worker() -> None:
            future: FutureHandle = heartbeat_manager.request_main_thread(
                lambda: executed.append(threading.get_ident())
            )
            thread_result.append(future.result(timeout=3.0))

        bg: threading.Thread = threading.Thread(target=bg_worker, daemon=True)
        bg.start()

        _wait_for(lambda: len(executed) > 0, timeout=5.0)
        bg.join(timeout=2.0)
        assert not bg.is_alive()
        assert executed[0] == main_thread_id
        assert thread_result == [None]

    def test_future_done_callback_fires_after_completion(self, qapp: Any) -> None:
        """FutureHandle.add_done_callback 在完成后触发。"""
        future: FutureHandle = FutureHandle()
        done: List[bool] = []
        future.add_done_callback(lambda _f: done.append(True))
        assert done == []

        future._set_result(42)
        assert done == [True]
        assert future.done()
        assert future.result() == 42

    def test_future_done_callback_fires_immediately_when_complete(self, qapp: Any) -> None:
        """边界：对已完结的 Future 添加回调应立即触发。"""
        future: FutureHandle = FutureHandle()
        future._set_result("done")

        done: List[bool] = []
        future.add_done_callback(lambda _f: done.append(True))
        assert done == [True]


# =============================================================================
# 线程安全（50 并发注册 / 注销）
# =============================================================================
class TestThreadSafety:
    """高并发注册 / 注销的一致性"""

    def test_concurrent_register_50_callbacks(self, qapp: Any) -> None:
        """50 个线程并发注册：全部成功且计数一致。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            barrier: threading.Barrier = threading.Barrier(_WORKER_COUNT + 1)
            errors: List[BaseException] = []

            def worker(index: int) -> None:
                try:
                    barrier.wait(timeout=5)
                    hm.register_tick_callback(f"cb_{index}", lambda: None)
                except Exception as exc:  # 收集线程错误，不让线程静默失败
                    errors.append(exc)

            threads: List[threading.Thread] = [
                threading.Thread(target=worker, args=(i,), daemon=True)
                for i in range(_WORKER_COUNT)
            ]
            for t in threads:
                t.start()
            barrier.wait(timeout=5)
            for t in threads:
                t.join(timeout=5)

            assert not any(t.is_alive() for t in threads)
            assert errors == []
            assert len(hm._callbacks) == _WORKER_COUNT

            # 主线程启动后 tick 正常运转（有 50 个回调，定时器保持激活）。
            hm.start()
            QTest.qWait(50)
            assert hm._normal_timer.isActive()

            hm.stop_all()
            assert len(hm._callbacks) == 0
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_concurrent_unregister_50_callbacks(self, qapp: Any) -> None:
        """50 个线程并发注销：最终集合为空且无异常。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            for i in range(_WORKER_COUNT):
                hm.register_tick_callback(f"cb_{i}", lambda: None)

            barrier: threading.Barrier = threading.Barrier(_WORKER_COUNT + 1)
            errors: List[BaseException] = []

            def worker(index: int) -> None:
                try:
                    barrier.wait(timeout=5)
                    hm.unregister_tick_callback(f"cb_{index}")
                except Exception as exc:
                    errors.append(exc)

            threads: List[threading.Thread] = [
                threading.Thread(target=worker, args=(i,), daemon=True)
                for i in range(_WORKER_COUNT)
            ]
            for t in threads:
                t.start()
            barrier.wait(timeout=5)
            for t in threads:
                t.join(timeout=5)

            assert not any(t.is_alive() for t in threads)
            assert errors == []
            assert len(hm._callbacks) == 0
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()

    def test_concurrent_mixed_register_and_unregister(self, qapp: Any) -> None:
        """混合并发：注销既有回调的同时注册新回调，计数保持一致。"""
        hm: HeartbeatManager = _make_heartbeat()
        try:
            for i in range(_WORKER_COUNT):
                hm.register_tick_callback(f"old_{i}", lambda: None)

            barrier: threading.Barrier = threading.Barrier(_WORKER_COUNT + 1)
            errors: List[BaseException] = []

            def worker(index: int) -> None:
                try:
                    barrier.wait(timeout=5)
                    if index % 2 == 0:
                        hm.unregister_tick_callback(f"old_{index}")
                    else:
                        hm.register_tick_callback(f"new_{index}", lambda: None)
                except Exception as exc:
                    errors.append(exc)

            threads: List[threading.Thread] = [
                threading.Thread(target=worker, args=(i,), daemon=True)
                for i in range(_WORKER_COUNT)
            ]
            for t in threads:
                t.start()
            barrier.wait(timeout=5)
            for t in threads:
                t.join(timeout=5)

            assert not any(t.is_alive() for t in threads)
            assert errors == []
            # 25 个 old 被注销，25 个 new 被注册；old 偶数已被注销。
            assert len(hm._callbacks) == _WORKER_COUNT
            for i in range(_WORKER_COUNT):
                if i % 2 == 0:
                    assert f"old_{i}" not in hm._callbacks
                else:
                    assert f"new_{i}" in hm._callbacks
        finally:
            hm.stop_all()
            _reset_heartbeat_singleton()