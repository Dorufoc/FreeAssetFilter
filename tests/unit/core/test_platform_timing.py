#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W5 高精度定时 + W6 交换链探测单测（todo 13）。

覆盖：引用计数、窗口期分辨率变化与恢复、timeGetDevCaps 上限、
powersave 永不开启、probe 字面量＋强制产物、帧抖动（N>=3）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from freeassetfilter.core.native import platform_timing as pt

IS_WINDOWS = sys.platform == "win32"

needs_winmm = pytest.mark.skipif(not IS_WINDOWS, reason="winmm 仅 Windows 可用")


@pytest.fixture(autouse=True)
def _isolated_timer_state():
    """用例间隔离：前后强制清零引用计数并恢复 balanced 档。"""
    pt.set_active_profile("balanced")
    pt.reset_highres_timer_state()
    yield
    pt.reset_highres_timer_state()
    pt.set_active_profile("balanced")
    assert pt.get_refcount() == 0
    assert not pt.is_elevated()


@needs_winmm
def test_refcount_begin3_end1_still_elevated() -> None:
    """begin×3 + end×1 后仍抬高；再 end×2 才恢复（stale state 对抗）。"""
    baseline = pt.get_current_timer_resolution_ms()
    assert pt.begin_highres_timer()
    assert pt.begin_highres_timer()
    assert pt.begin_highres_timer()
    assert pt.get_refcount() == 3
    assert pt.is_elevated()

    assert pt.end_highres_timer()
    assert pt.get_refcount() == 2
    assert pt.is_elevated()
    assert pt.get_current_timer_resolution_ms() <= 1.5

    assert pt.end_highres_timer()
    assert pt.end_highres_timer()
    assert pt.get_refcount() == 0
    assert not pt.is_elevated()
    assert pt.get_current_timer_resolution_ms() == pytest.approx(baseline)


@needs_winmm
def test_resolution_elevated_within_window_and_restored_after() -> None:
    """窗口期内分辨率 ≤1.5ms；end 后回读等于基线（防 stale）。"""
    baseline = pt.get_current_timer_resolution_ms()
    assert pt.begin_highres_timer()
    assert pt.get_current_timer_resolution_ms() <= 1.5
    assert pt.end_highres_timer()
    assert pt.get_current_timer_resolution_ms() == pytest.approx(baseline)


@needs_winmm
def test_timer_caps_support_1ms() -> None:
    """timeGetDevCaps 上报的最小周期 ≤1ms（winmm 路径真实可用）。"""
    period_min, period_max = pt.get_timer_caps()
    assert period_min <= 1
    assert period_max >= period_min


@needs_winmm
def test_powersave_never_begins() -> None:
    """powersave 档（全局或单次覆写）永远不开启、不计数、不抬高。"""
    baseline = pt.get_current_timer_resolution_ms()
    pt.set_active_profile("powersave")
    assert not pt.begin_highres_timer()
    assert pt.get_refcount() == 0
    assert not pt.is_elevated()
    assert pt.get_current_timer_resolution_ms() == pytest.approx(baseline)

    pt.set_active_profile("balanced")
    assert not pt.begin_highres_timer(profile="powersave")
    assert pt.get_refcount() == 0
    assert not pt.is_elevated()


def test_end_without_begin_is_noop() -> None:
    """无持有时 end 返回 False 且不触碰 winmm。"""
    assert not pt.end_highres_timer()
    assert pt.get_refcount() == 0


def test_context_manager_balances() -> None:
    """highres_timer_window 退出时严格成对释放（含嵌套）。"""
    if IS_WINDOWS:
        with pt.highres_timer_window() as opened:
            assert opened
            assert pt.get_refcount() == 1
            with pt.highres_timer_window() as nested:
                assert nested
                assert pt.get_refcount() == 2
            assert pt.get_refcount() == 1
        assert pt.get_refcount() == 0
        assert not pt.is_elevated()
    else:
        with pt.highres_timer_window() as opened:
            assert not opened
        assert pt.get_refcount() == 0


def test_probe_returns_literal_and_writes_mandatory_artifact(
    tmp_path: Path,
) -> None:
    """probe 返回二值字面量之一；产物存在、非空、含两行验收键。

    产物缺失/为空即失败（misleading success 对抗）；默认路径与
    显式路径双写验证。
    """
    verdict = pt.probe_swapchain_latency()
    assert verdict in ("reachable", "deferred-to-P3")

    default_artifact = pt.default_probe_artifact_path()
    assert default_artifact.is_file(), "swapchain_probe.txt 缺失即失败"
    content = default_artifact.read_text(encoding="utf-8")
    assert len(content.strip()) > 0
    assert "swapchain_latency=" in content
    assert "reason=" in content

    custom = tmp_path / "swapchain_probe.txt"
    verdict2 = pt.probe_swapchain_latency(custom)
    assert verdict2 == verdict
    assert custom.is_file() and custom.stat().st_size > 0


@needs_winmm
def test_jitter_within_window_and_timing_ok_artifact() -> None:
    """窗口期内 30×16ms 等待 stdev < 2ms；落盘 timing-ok.txt（含原始数）。

    N=30（≥3，flaky 对抗）；抖动断言 + 产物非空双验收。
    """
    assert pt.begin_highres_timer()
    try:
        stats = pt.measure_frame_jitter(samples=30, interval_ms=16.0)
    finally:
        assert pt.end_highres_timer()
    assert stats["samples"] >= 3
    assert stats["stdev_ms"] < 2.0

    evidence_dir = pt.default_probe_artifact_path().parent
    evidence_dir.mkdir(parents=True, exist_ok=True)
    timing_ok = evidence_dir / "timing-ok.txt"
    timing_ok.write_text(
        "\n".join(
            [
                f"samples={stats['samples']}",
                f"mean_ms={stats['mean_ms']:.3f}",
                f"stdev_ms={stats['stdev_ms']:.3f}",
                f"min_ms={stats['min_ms']:.3f}",
                f"max_ms={stats['max_ms']:.3f}",
                f"window_resolution_ms={stats['resolution_ms']:.3f}",
                f"restored_resolution_ms={pt.get_current_timer_resolution_ms():.3f}",
                "verdict=PASS",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert timing_ok.is_file() and timing_ok.stat().st_size > 0


@needs_winmm
def test_fallback_artifact_when_timer_unavailable() -> None:
    """powersave 下 probe 照常产出 deferred 产物（failure 分支不静默）。"""
    pt.set_active_profile("powersave")
    verdict = pt.probe_swapchain_latency()
    assert verdict == "deferred-to-P3"
    content = pt.default_probe_artifact_path().read_text(encoding="utf-8")
    assert "swapchain_latency=deferred-to-P3" in content
