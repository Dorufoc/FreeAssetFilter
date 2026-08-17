# -*- coding: utf-8 -*-
"""global_mouse_monitor.py（freeassetfilter/utils/global_mouse_monitor.py）单元测试。

覆盖 start/stop 幂等与状态机、属性（timeout/callbacks/is_monitoring）、
``_process_pending_signals`` 对 pending 标志的消费与信号发射、空闲超时
``_on_timeout``、暂停/恢复/重置隐藏计时器、以及 teardown/stop_all 的
实例生命周期清理。

**绝不安装真实 Windows 钩子**：``start()``/``stop()`` 通过
monkeypatch 绑定到假实现（``_install_fake_hook``），信号发射经
``_process_pending_signals`` 直接驱动，不触碰真实鼠标。
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QTimer

from freeassetfilter.utils.global_mouse_monitor import GlobalMouseMonitor

pytestmark = pytest.mark.unit


def _monkeypatch_windowed_hooks(monkeypatch: Any) -> None:
    """让 start/stop 走假实现，绝不安装真实 Windows 钩子。"""

    def _install_fake_hook(self: GlobalMouseMonitor) -> bool:
        if self._disposed:
            return False
        if self._is_monitoring:
            return True
        self._is_monitoring = True
        self._signal_timer.start()
        self._hide_timer.start(self._timeout)
        with GlobalMouseMonitor._active_instances_lock:
            GlobalMouseMonitor._active_instances.add(self)
        return True

    def _remove_fake_hook(self: GlobalMouseMonitor) -> None:
        if self._is_monitoring:
            with GlobalMouseMonitor._active_instances_lock:
                GlobalMouseMonitor._active_instances.discard(self)
        self._is_monitoring = False

    # 类上本无这两个属性，raising=False 允许新建（monkeypatch.setattr 默认 raising=True 会抛 AttributeError）
    monkeypatch.setattr(
        GlobalMouseMonitor, "_install_fake_hook", _install_fake_hook, raising=False
    )
    monkeypatch.setattr(
        GlobalMouseMonitor, "_remove_fake_hook", _remove_fake_hook, raising=False
    )
    monkeypatch.setattr(GlobalMouseMonitor, "start", _install_fake_hook)
    monkeypatch.setattr(GlobalMouseMonitor, "stop", _remove_fake_hook)


class TestDisposeGuard:
    """disposed 状态守卫。"""

    def test_disposed_start_returns_false(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        monitor._disposed = True
        assert monitor.start() is False
        assert not monitor.is_monitoring()

    def test_disposed_stop_is_noop(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        monitor.stop()  # 未启动 → 早退
        assert not monitor.is_monitoring()


class TestDefaults:
    """默认属性值。"""

    def test_default_timeout_is_3000(self, qapp: Any) -> None:
        assert GlobalMouseMonitor().timeout == 3000

    def test_default_callbacks_none(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        assert monitor.activity_callback is None
        assert monitor.timeout_callback is None

    def test_default_not_monitoring(self, qapp: Any) -> None:
        assert not GlobalMouseMonitor().is_monitoring()


class TestStartStop:
    """start/stop 幂等与状态机。"""

    def test_start_stop_state_transitions(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        monitor = GlobalMouseMonitor()
        assert monitor.start() is True
        assert monitor.is_monitoring()
        monitor.stop()
        assert not monitor.is_monitoring()

    def test_start_twice_is_idempotent(self, qapp: Any, monkeypatch: Any) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        monitor = GlobalMouseMonitor()
        assert monitor.start() is True
        assert monitor.start() is True  # 已监控 → 直接成功
        monitor.stop()
        assert not monitor.is_monitoring()
        assert monitor.start() is True  # 停止后可再次启动


class TestProperties:
    """timeout 与回调 setter。"""

    def test_timeout_setter_updates_value(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        monitor.timeout = 5000
        assert monitor.timeout == 5000

    def test_callback_setters(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        activity = lambda: None  # noqa: E731
        timeout = lambda: None  # noqa: E731
        monitor.activity_callback = activity
        monitor.timeout_callback = timeout
        assert monitor.activity_callback is activity
        assert monitor.timeout_callback is timeout


class TestPendingSignals:
    """_process_pending_signals 消费 flags 并发信号。"""

    def test_click_emits_mouse_clicked(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        monitor._is_monitoring = True  # 守卫要求监控中才消费 pending 标志
        monitor._pending_click = True
        fired = []

        monitor.mouse_clicked.connect(lambda: fired.append(1))
        monitor._process_pending_signals()

        assert fired == [1]
        assert not monitor._pending_click

    def test_move_throttle_emits_immediately(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        monitor._is_monitoring = True  # 守卫要求监控中才消费 pending 标志
        monitor._last_move_emit_time = 0.0
        monitor._pending_move = True
        fired = []

        monitor.mouse_moved.connect(lambda: fired.append(1))
        monitor._process_pending_signals()

        # 距上次发射足够久（>50ms），立即发射
        assert fired == [1]
        assert not monitor._pending_move

    def test_scroll_emits_mouse_scrolled(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor()
        monitor._is_monitoring = True  # 守卫要求监控中才消费 pending 标志
        monitor._pending_scroll = True
        fired = []

        monitor.mouse_scrolled.connect(lambda: fired.append(1))
        monitor._process_pending_signals()

        assert fired == [1]
        assert not monitor._pending_scroll


class TestTimeout:
    """_on_timeout 空闲超时发射。"""

    def test_timeout_reached_emits(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor(timeout=10)
        fired = []
        callback_called = []

        monitor.timeout_reached.connect(lambda: fired.append(1))
        monitor.timeout_callback = lambda: callback_called.append(1)

        monitor._on_timeout()

        assert fired == [1]
        assert callback_called == [1]

    def test_timeout_callback_error_is_caught(self, qapp: Any) -> None:
        monitor = GlobalMouseMonitor(timeout=10)

        def bad_callback() -> None:
            raise RuntimeError("boom")

        monitor.timeout_callback = bad_callback
        # 不应抛出，仅记录错误日志
        monitor._on_timeout()

    def test_timer_fires_timeout(self, qapp: Any) -> None:
        """真实 QTimer 触发 _on_timeout 路径。"""
        monitor = GlobalMouseMonitor(timeout=5)
        fired = []

        monitor.timeout_reached.connect(lambda: fired.append(1))
        monitor._signal_timer.stop()  # 干扰信号计时器
        monitor._hide_timer.setSingleShot(True)
        monitor._hide_timer.start(5)
        monitor._on_timeout()

        assert fired == [1]


class TestTimerControl:
    """pause/resume/reset 隐藏计时器。"""

    def test_pause_hide_timer_requires_monitoring(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        monitor = GlobalMouseMonitor()
        monitor.pause_hide_timer()  # 未启动 → 无副作用
        assert not monitor._hide_timer_paused
        monitor.start()
        monitor.pause_hide_timer()
        assert monitor._hide_timer_paused
        assert not monitor._hide_timer.isActive()
        monitor.stop()

    def test_resume_hide_timer_custom_timeout(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        monitor = GlobalMouseMonitor()
        monitor.start()
        monitor.resume_hide_timer(timeout_ms=1234)
        assert not monitor._hide_timer_paused
        assert monitor._hide_timer.interval() == 1234
        monitor.stop()

    def test_reset_timer(self, qapp: Any, monkeypatch: Any) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        monitor = GlobalMouseMonitor(timeout=2000)
        monitor.start()
        monitor.reset_timer()
        assert monitor._hide_timer.isActive()
        assert monitor._hide_timer.interval() == 2000
        monitor.stop()


class TestLifecycle:
    """stop_all 与 teardown 生命周期清理。"""

    def test_stop_all_clears_active_instances(
        self, qapp: Any, monkeypatch: Any
    ) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        GlobalMouseMonitor._active_instances.clear()
        first = GlobalMouseMonitor()
        second = GlobalMouseMonitor()
        first.start()
        second.start()

        GlobalMouseMonitor.stop_all()

        assert not GlobalMouseMonitor._active_instances
        assert not first.is_monitoring()
        assert not second.is_monitoring()

    def test_delete_calls_stop(self, qapp: Any, monkeypatch: Any) -> None:
        _monkeypatch_windowed_hooks(monkeypatch)
        monitor = GlobalMouseMonitor()
        monitor.start()
        stopped = []

        # 模拟 __del__ 触发 stop；未销毁钩子资源时安全
        original_stop = GlobalMouseMonitor.stop

        def _wrapped(self_m: Any) -> None:
            stopped.append(self_m)
            original_stop(self_m)

        monkeypatch.setattr(GlobalMouseMonitor, "stop", _wrapped)
        # start() 会把实例登记进 _active_instances，集合持有引用会阻止 __del__ 触发，
        # 先清空集合以释放引用，让 del 真正走到析构路径。
        GlobalMouseMonitor._active_instances.clear()
        del monitor
        assert stopped  # __del__ 调用了 stop

    def test_cleanup_dummy_threads_is_safe(self, qapp: Any) -> None:
        """清理 _DummyThread 在无钩子时安全运行。"""
        GlobalMouseMonitor._cleanup_dummy_threads()  # 不应抛出