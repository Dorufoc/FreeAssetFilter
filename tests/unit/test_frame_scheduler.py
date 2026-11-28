"""帧率调度与刷新率探测的单元测试。

覆盖三块新增逻辑：

1. :mod:`sopeek.core.managers.display_timing` 的刷新率清洗/吸附与回退；
2. :class:`~sopeek.core.managers.frame_scheduler.FrameScheduler` 的订阅节拍、
   空闲降频、活动唤醒与硬需求令牌；
3. :mod:`sopeek.ui.frame_pacing` 的开关（``SPK_REFRESH_ANIMATIONS=0``）。

调度器的面板刷新率在测试里用私有字段直接设定：真实运行时它由
:class:`DisplayTiming` 依据 ``QScreen.refreshRate()`` 驱动，测试不需要真屏幕。
"""
from __future__ import annotations

import pytest

from sopeek.core.managers.display_timing import (
    DEFAULT_REFRESH_HZ,
    MAX_REFRESH_HZ,
    MIN_REFRESH_HZ,
    frame_interval_ms,
    sanitize_refresh_hz,
)
from sopeek.core.managers.frame_scheduler import FrameScheduler


def test_sanitize_snaps_to_known_step() -> None:
    """接近已知档位的值吸附到整档（显示器常报 59.951 这类浮点）。"""
    assert sanitize_refresh_hz(59.951) == pytest.approx(60.0)
    assert sanitize_refresh_hz(143.98) == pytest.approx(144.0)
    assert sanitize_refresh_hz(239.7) == pytest.approx(240.0)


def test_sanitize_clamps_and_falls_back() -> None:
    """越界值夹到上下限，非法值回退默认 60Hz。"""
    assert sanitize_refresh_hz(1.0) == pytest.approx(MIN_REFRESH_HZ)
    assert sanitize_refresh_hz(9999.0) == pytest.approx(MAX_REFRESH_HZ)
    assert sanitize_refresh_hz(0.0) == pytest.approx(DEFAULT_REFRESH_HZ)
    assert sanitize_refresh_hz(None) == pytest.approx(DEFAULT_REFRESH_HZ)
    assert sanitize_refresh_hz(float("nan")) == pytest.approx(DEFAULT_REFRESH_HZ)


def test_frame_interval_ms() -> None:
    """单帧毫秒数 = 1000 / Hz；非法输入夹到下限档（恒为正）。"""
    assert frame_interval_ms(240.0) == pytest.approx(1000.0 / 240.0)
    assert frame_interval_ms(60.0) == pytest.approx(1000.0 / 60.0)
    assert frame_interval_ms(0.0) == pytest.approx(1000.0 / MIN_REFRESH_HZ)


@pytest.fixture()
def scheduler(qapp) -> FrameScheduler:
    """每个测试一个独立调度器实例，避免全局单例互相污染。"""
    sched = FrameScheduler()
    sched._panel_hz = 240.0
    sched._idle = False
    yield sched
    sched.shutdown()


def _force_idle(sched: FrameScheduler) -> None:
    """把调度器压到空闲档（等价于 1.2s 无键鼠活动后的状态）。"""
    sched._idle = True
    sched._retune(force=True)


def test_subscribe_and_cadence(scheduler: FrameScheduler) -> None:
    """满帧订阅把节拍抬到面板刷新率，注销后停表。"""
    scheduler.subscribe("unit.full", lambda: None, hz=None)
    stats = scheduler.stats()
    assert stats["cadence_hz"] == pytest.approx(240.0)
    assert stats["running"] is True

    assert scheduler.unsubscribe("unit.full") is True
    # 停表有 1.2s 宽限期（动画首尾相接时避免反复停钟/起钟）。
    assert scheduler.stats()["running"] is True
    scheduler._stop_after_grace()
    assert scheduler.stats()["running"] is False


def test_throttled_subscription_keeps_low_cadence(scheduler: FrameScheduler) -> None:
    """低帧率订阅不把节拍抬到面板刷新率。"""
    scheduler.subscribe("unit.low", lambda: None, hz=30.0)
    assert scheduler.stats()["cadence_hz"] <= 30.0


def test_idle_downgrade_and_wake(scheduler: FrameScheduler) -> None:
    """空闲后降频；新增满帧订阅视为活动，立即抬回面板刷新率。"""
    scheduler.subscribe("unit.low", lambda: None, hz=30.0)
    _force_idle(scheduler)
    assert scheduler.stats()["idle"] is True
    assert scheduler.stats()["cadence_hz"] <= 30.0

    scheduler.subscribe("unit.anim", lambda: None, hz=None)
    stats = scheduler.stats()
    assert stats["idle"] is False
    assert stats["cadence_hz"] == pytest.approx(240.0)


def test_high_rate_token_survives_idle(scheduler: FrameScheduler) -> None:
    """播放/拖拽等硬需求在空闲态也不被压低。"""
    scheduler.subscribe("unit.low", lambda: None, hz=30.0)
    scheduler.request_high_rate("unit.token")
    _force_idle(scheduler)
    assert scheduler.stats()["cadence_hz"] == pytest.approx(240.0)

    scheduler.release_high_rate("unit.token")
    _force_idle(scheduler)
    assert scheduler.stats()["cadence_hz"] <= 30.0


def test_unsubscribe_for_owner(scheduler: FrameScheduler) -> None:
    """按 owner 批量注销，未命中者保留。"""
    from PySide6.QtCore import QObject

    owner = QObject()
    scheduler.subscribe("unit.a", lambda: None, hz=None, owner=owner)
    scheduler.subscribe("unit.b", lambda: None, hz=None, owner=owner)
    scheduler.subscribe("unit.c", lambda: None, hz=None)
    assert scheduler.unsubscribe_for_owner(owner) == 2
    assert scheduler.is_subscribed("unit.c") is True


def test_frame_pacing_env_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SPK_REFRESH_ANIMATIONS=0`` 时不安装动画补丁。"""
    from sopeek.ui import frame_pacing

    monkeypatch.setenv("SPK_REFRESH_ANIMATIONS", "0")
    frame_pacing.uninstall_frame_pacing()
    assert frame_pacing.install_frame_pacing() is False
    assert frame_pacing.is_installed() is False

    monkeypatch.delenv("SPK_REFRESH_ANIMATIONS", raising=False)
    assert frame_pacing.install_frame_pacing() is True
    assert frame_pacing.is_installed() is True
