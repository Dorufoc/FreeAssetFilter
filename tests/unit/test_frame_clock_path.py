"""vsync 时钟泵路径的单元测试（用假桥，不依赖真实 DLL / 显示器）。

真实运行时 :class:`FrameScheduler` 优先用 Rust ``spk_frameclock`` 在后台线程
等 vblank，再把每帧投递回主线程；这里用假桥验证「接管 / 投递 / 改档 / 回收」
四条契约，真实 vsync 抖动由实机探针覆盖。
"""
from __future__ import annotations

import threading

import pytest

from sopeek.core.managers.frame_scheduler import FrameScheduler


class _FakeClockBridge:
    """最小假桥：按测试放行次数返回帧，记录所有调用。"""

    def __init__(self) -> None:
        self.slots: threading.Semaphore = threading.Semaphore(0)
        self.created: list[float] = []
        self.rates: list[float] = []
        self.freed: list[int] = []
        self.stopped: list[int] = []
        self.resumed: list[int] = []
        self._seq: int = 0

    def frameclock_create(self, hz: float) -> int:
        self.created.append(hz)
        return 77

    def frameclock_set_rate(self, handle: int, hz: float) -> bool:
        self.rates.append(hz)
        return True

    def frameclock_wait(self, handle: int, timeout_ms: int) -> int:
        if self.slots.acquire(timeout=max(1, timeout_ms) / 1000.0):
            self._seq += 1
            return self._seq
        return -3

    def frameclock_stop(self, handle: int) -> bool:
        self.stopped.append(handle)
        return True

    def frameclock_resume(self, handle: int) -> bool:
        self.resumed.append(handle)
        return True

    def frameclock_free(self, handle: int) -> bool:
        self.freed.append(handle)
        return True

    def frameclock_stats(self, handle: int) -> dict:
        return {"mode": "vsync", "panel_hz": 240.0, "divisor": 1}


@pytest.fixture()
def clocked(qapp, monkeypatch) -> tuple[FrameScheduler, _FakeClockBridge]:
    """打开时钟路径、装上假桥的调度器。"""
    monkeypatch.setenv("SPK_FRAME_CLOCK", "1")
    sched = FrameScheduler()
    sched._panel_hz = 240.0
    sched._idle = False
    fake = _FakeClockBridge()
    monkeypatch.setattr(sched, "_clock_bridge", lambda: fake)
    yield sched, fake
    sched.shutdown()


def _pump(qapp, frames: int, timeout_s: float = 3.0) -> int:
    """放行 ``frames`` 帧并驱动事件循环，返回实际回调次数。"""
    import time

    hits = {"n": 0}

    def tick() -> None:
        hits["n"] += 1

    sched = FrameScheduler()
    sched.subscribe("clock.test", tick)
    fake = sched._clock_bridge()
    deadline = time.monotonic() + timeout_s
    for _ in range(frames):
        fake.slots.release()
        while time.monotonic() < deadline:
            qapp.processEvents()
            if hits["n"] >= 1:
                break
            time.sleep(0.001)
        hits["n"] = 0
    return hits["n"]


def test_clock_takes_over_and_feeds_frames(clocked, qapp) -> None:
    """时钟可用时接管节拍，并把每帧投递到主线程执行订阅者。"""
    sched, fake = clocked
    seen: list[int] = []

    sched.subscribe("clock.count", lambda: seen.append(1))
    sched.ensure_running()
    assert sched.stats()["vsync_clock"] is True
    assert fake.created == [pytest.approx(240.0)]

    import time

    deadline = time.monotonic() + 3.0
    while len(seen) < 3 and time.monotonic() < deadline:
        fake.slots.release()
        qapp.processEvents()
        time.sleep(0.002)
    assert len(seen) >= 3


def test_clock_rate_follows_cadence(clocked) -> None:
    """改档（进入空闲降频）会把新帧率同步给 native 时钟。"""
    sched, fake = clocked
    sched.subscribe("clock.full", lambda: None)
    sched.ensure_running()
    assert fake.rates == []  # 创建即满帧，无需改档

    sched._idle = True
    sched._retune(force=True)
    assert fake.rates, "期望空闲降频时下发一次帧率"
    assert fake.rates[-1] == pytest.approx(30.0)


def test_clock_pauses_without_freeing_and_reuses_handle(clocked) -> None:
    """空转时停线程但保留句柄，再次启动直接 resume（不重建）。"""
    sched, fake = clocked
    sched.subscribe("clock.tmp", lambda: None)
    sched.ensure_running()
    sched.stop()
    assert fake.stopped == [77]
    assert fake.freed == []
    sched.ensure_running()
    assert fake.resumed == [77]
    assert fake.created == [pytest.approx(240.0)]


def test_shutdown_frees_handle(clocked) -> None:
    """shutdown 释放 native 句柄，避免泄漏。"""
    sched, fake = clocked
    sched.subscribe("clock.tmp", lambda: None)
    sched.ensure_running()
    sched.shutdown()
    assert fake.freed == [77]


def test_clock_disabled_by_env_falls_back_to_timer(qapp, monkeypatch) -> None:
    """``SPK_FRAME_CLOCK=0`` 时完全不起线程（单测默认路径）。"""
    monkeypatch.setenv("SPK_FRAME_CLOCK", "0")
    sched = FrameScheduler()
    sched._panel_hz = 240.0
    sched._idle = False
    called: list[int] = []
    try:
        sched.subscribe("timer.path", lambda: called.append(1))
        sched.ensure_running()
        assert sched.stats()["vsync_clock"] is False
    finally:
        sched.shutdown()
