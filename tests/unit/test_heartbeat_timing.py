"""HeartbeatManager 墙钟语义回归测试。

背景：心跳原先由两个固定间隔 QTimer 驱动（33ms / 16ms）。改成帧调度器驱动后，
分发节拍会随显示器刷新率（本机 240Hz）与空闲降档（30Hz）变化。这里锁定一条
不变量：**回调的真实周期只由调用方声明的时间决定，与分发节拍无关**。

测试用可替换的假时钟直接驱动 ``_process_normal_tick()``，不依赖真实定时器。
"""

from __future__ import annotations

from typing import Iterator

import pytest

from sopeek.core.managers import heartbeat_manager as hb_module
from sopeek.core.managers.heartbeat_manager import (
    LEGACY_NORMAL_HZ,
    LEGACY_NORMAL_TICK_MS,
    HeartbeatManager,
)

_CADENCE_MS = 33.333


class _FakeClock:
    """单调递增的假时钟（秒）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def monotonic(self) -> float:
        return self.t

    def perf_counter(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t

    def advance_ms(self, ms: float) -> None:
        self.t += ms / 1000.0


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeClock]:
    fake = _FakeClock()
    monkeypatch.setattr(hb_module, "time", fake)
    yield fake


@pytest.fixture()
def heartbeat(clock: _FakeClock) -> Iterator[HeartbeatManager]:
    HeartbeatManager._instance = None
    HeartbeatManager._initialized = False
    hm = HeartbeatManager()
    hm._running = True
    hm._normal_tick_interval = _CADENCE_MS
    try:
        yield hm
    finally:
        hm._callbacks.clear()
        hm._animation_callback_count = 0
        # 注册回调会订阅全局帧调度器：测试结束必须退订，否则会污染后续用例
        # 对 ``frame_scheduler().stats()["running"]`` 的断言。
        hm._unsubscribe_scheduler()
        HeartbeatManager._instance = None
        HeartbeatManager._initialized = False


def _drive(hm: HeartbeatManager, clock: _FakeClock, ticks: int) -> None:
    """按分发节拍推进假时钟，每次推进后跑一个普通 tick。"""
    for _ in range(ticks):
        clock.advance_ms(_CADENCE_MS)
        hm._process_normal_tick()


def test_period_ms_uses_legacy_tick_for_frame_counts(heartbeat: HeartbeatManager) -> None:
    """``every_n_ticks`` 仍按 33ms 折算，不随帧率变化。"""
    heartbeat.register_tick_callback("every1", lambda: None, every_n_ticks=1)
    heartbeat.register_tick_callback("every3", lambda: None, every_n_ticks=3)

    with heartbeat._callback_lock:
        assert heartbeat._callbacks["every1"].period_ms() == pytest.approx(
            LEGACY_NORMAL_TICK_MS
        )
        assert heartbeat._callbacks["every3"].period_ms() == pytest.approx(
            3 * LEGACY_NORMAL_TICK_MS
        )


def test_interval_ms_declares_wall_clock_period(heartbeat: HeartbeatManager) -> None:
    """``interval_ms`` 就是墙钟周期，原样使用。"""
    heartbeat.register_tick_callback("pump", lambda: None, interval_ms=100.0)

    with heartbeat._callback_lock:
        assert heartbeat._callbacks["pump"].period_ms() == pytest.approx(100.0)


def test_hundred_ms_callback_stays_hundred_ms(heartbeat: HeartbeatManager) -> None:
    """100ms 周期在 30Hz 分发节拍下仍然是 100ms。"""
    calls: list[float] = []
    heartbeat.register_tick_callback(
        "pump", lambda: calls.append(hb_module.time.monotonic()), interval_ms=100.0
    )

    _drive(heartbeat, _clock_of(heartbeat), 30)

    assert len(calls) >= 9
    intervals = [(b - a) * 1000.0 for a, b in zip(calls, calls[1:])]
    assert intervals, "回调没有被触发"
    for gap in intervals:
        assert 90.0 <= gap <= 110.0, f"周期漂移: {gap:.1f}ms"


def _clock_of(hm: HeartbeatManager) -> _FakeClock:
    """取当前 monkeypatch 生效的假时钟。"""
    clock = hb_module.time
    assert isinstance(clock, _FakeClock)
    return clock


def test_frame_count_callback_keeps_legacy_cadence(heartbeat: HeartbeatManager) -> None:
    """``every_n_ticks=3`` 在帧率提升后依然是 ~99ms 而不是 ~50ms。"""
    stamps: list[float] = []
    heartbeat.register_tick_callback(
        "every3", lambda: stamps.append(hb_module.time.monotonic()), every_n_ticks=3
    )

    _drive(heartbeat, _clock_of(heartbeat), 60)

    assert len(stamps) >= 15
    gaps = [(b - a) * 1000.0 for a, b in zip(stamps, stamps[1:])]
    assert gaps
    for gap in gaps:
        assert 90.0 <= gap <= 110.0, f"周期漂移: {gap:.1f}ms"


def test_desired_hz_never_below_legacy_rate(heartbeat: HeartbeatManager) -> None:
    """没有更快的回调时，分发频率停在历史 30Hz 档，不因面板高刷而飙升。"""
    heartbeat.register_tick_callback("idle", lambda: None, interval_ms=1000.0)

    assert heartbeat._desired_hz() == pytest.approx(LEGACY_NORMAL_HZ, rel=1e-3)


def test_desired_hz_tracks_faster_callbacks(heartbeat: HeartbeatManager) -> None:
    """有 16ms 级回调时才提速（仍受 ``_normal_hz`` 上限约束）。"""
    heartbeat._normal_hz = 60
    heartbeat.register_tick_callback("fastish", lambda: None, interval_ms=16.0)

    assert heartbeat._desired_hz() == pytest.approx(60.0)


def test_fast_tick_asks_for_every_frame(heartbeat: HeartbeatManager) -> None:
    """``use_fast_tick`` 动画回调要求每帧分发。"""
    heartbeat.register_tick_callback("anim", lambda: None, use_fast_tick=True)

    assert heartbeat._desired_hz() is None


def test_tick_rate_setter_does_not_change_period(heartbeat: HeartbeatManager) -> None:
    """``set_normal_tick_rate`` 只调整上限，不改变既有回调的周期。"""
    stamps: list[float] = []
    heartbeat.register_tick_callback(
        "pump", lambda: stamps.append(hb_module.time.monotonic()), interval_ms=100.0
    )

    heartbeat.set_normal_tick_rate(240)
    # 调度器只在确有更快的回调时才提速：这里没有，所以分发节拍仍是 30Hz。
    heartbeat._normal_tick_interval = _CADENCE_MS
    _drive(heartbeat, _clock_of(heartbeat), 45)

    gaps = [(b - a) * 1000.0 for a, b in zip(stamps, stamps[1:])]
    assert gaps
    for gap in gaps:
        assert 90.0 <= gap <= 110.0, f"周期漂移: {gap:.1f}ms"
