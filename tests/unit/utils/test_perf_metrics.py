# -*- coding: utf-8 -*-
"""test_perf_metrics: perf_metrics.py 覆盖测试（todo-10, unit/utils 批 1）。

覆盖：PerfEventStats.add_sample/to_dict/_percentile、线程安全并发、
FAF_PERF_METRICS_ENABLED 禁用、export/clear/snapshot/summary_lines、
模块级便捷函数。
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from freeassetfilter.utils import perf_metrics
from freeassetfilter.utils.perf_metrics import (
    FRAME_RING_MAXLEN,
    PerfEventStats,
    PerfMetricsRegistry,
    _truthy_env,
    begin_frame,
    clear_perf_metrics,
    end_frame,
    export_perf_metrics,
    frame_sample,
    frame_time_stats,
    get_perf_registry,
    get_perf_snapshot,
    increment_perf_counter,
    record_frame_sample,
    record_perf_duration,
    reset_frame_times,
    set_frame_profiling_enabled,
    set_perf_metadata,
    track_perf,
)


@pytest.fixture()
def fresh_registry() -> PerfMetricsRegistry:
    """返回一个全新的、启用状态的注册表。

    Returns:
        PerfMetricsRegistry: 新实例。
    """
    return PerfMetricsRegistry()


class TestPerfEventStats:
    """PerfEventStats 统计累加与分位计算。"""

    def test_add_sample_accumulates(self) -> None:
        """add_sample 累加 calls/total/min/max。"""
        stats = PerfEventStats(name="evt")
        stats.add_sample(1.0)
        stats.add_sample(2.0)
        stats.add_sample(3.0)
        assert stats.calls == 3
        assert stats.total_ms == pytest.approx(6.0)
        assert stats.min_ms == pytest.approx(1.0)
        assert stats.max_ms == pytest.approx(3.0)
        assert stats.failures == 0

    def test_add_sample_clamps_negative(self) -> None:
        """负耗时被钳制为 0。"""
        stats = PerfEventStats(name="evt")
        stats.add_sample(-5.0)
        assert stats.calls == 1
        assert stats.total_ms == pytest.approx(0.0)
        assert stats.min_ms == pytest.approx(0.0)

    def test_add_sample_failure_tracked(self) -> None:
        """success=False 计入 failures。"""
        stats = PerfEventStats(name="evt")
        stats.add_sample(1.0, success=False)
        assert stats.failures == 1
        assert stats.calls == 1

    def test_increment_and_metadata(self) -> None:
        """increment 与 set_metadata 生效。"""
        stats = PerfEventStats(name="evt")
        stats.increment("cache_hit", 3)
        stats.increment("cache_miss", 1)
        stats.set_metadata("os", "windows")
        assert stats.counters["cache_hit"] == 3
        assert stats.counters["cache_miss"] == 1
        assert stats.metadata["os"] == "windows"

    def test_percentile_known_dataset(self) -> None:
        """小数据集上的 P50/P95/P99 精确值。"""
        stats = PerfEventStats(name="evt")
        for value in range(1, 11):
            stats.add_sample(float(value))
        assert stats._percentile(0.50) == pytest.approx(6.0)
        assert stats._percentile(0.95) == pytest.approx(10.0)
        assert stats._percentile(0.99) == pytest.approx(10.0)

    def test_percentile_single_sample(self) -> None:
        """单样本时全分位等于该样本。"""
        stats = PerfEventStats(name="evt")
        stats.add_sample(5.0)
        assert stats._percentile(0.50) == pytest.approx(5.0)
        assert stats._percentile(0.99) == pytest.approx(5.0)

    def test_percentile_empty(self) -> None:
        """无样本时返回 0.0。"""
        stats = PerfEventStats(name="evt")
        assert stats._percentile(0.50) == 0.0

    def test_to_dict_shape(self) -> None:
        """to_dict 输出完整字段与正确统计值。"""
        stats = PerfEventStats(name="evt")
        stats.add_sample(1.0)
        stats.add_sample(2.0)
        stats.add_sample(3.0)
        stats.add_sample(5.0, success=False)
        stats.increment("cache_hit", 7)
        stats.increment("cache_miss", 3)
        stats.set_metadata("os", "windows")

        data = stats.to_dict()
        assert data["name"] == "evt"
        assert data["calls"] == 4
        assert data["total_ms"] == pytest.approx(11.0)
        assert data["avg_ms"] == pytest.approx(2.75)
        assert data["min_ms"] == pytest.approx(1.0)
        assert data["max_ms"] == pytest.approx(5.0)
        assert data["failures"] == 1
        assert data["failure_rate"] == pytest.approx(0.25)
        assert data["cache_hit"] == 7
        assert data["cache_miss"] == 3
        assert data["cache_hit_rate"] == pytest.approx(0.7)
        assert data["counters"] == {"cache_hit": 7, "cache_miss": 3}
        assert data["metadata"] == {"os": "windows"}
        assert data["sample_count"] == 4

    def test_to_dict_empty(self) -> None:
        """空统计的默认字段值。"""
        data = PerfEventStats(name="evt").to_dict()
        assert data["avg_ms"] == 0.0
        assert data["min_ms"] is None
        assert data["cache_hit_rate"] is None
        assert data["sample_count"] == 0

    def test_sample_limit_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """样本上限（deque maxlen）约束保留的样本数。"""
        monkeypatch.setenv("FAF_PERF_SAMPLE_LIMIT", "100")
        registry = PerfMetricsRegistry()
        for value in range(1, 181):
            registry.record_duration("evt", float(value))
        snap = registry.snapshot()
        assert snap["events"]["evt"]["sample_count"] == 100


class TestPerfMetricsRegistry:
    """PerfMetricsRegistry 核心行为。"""

    def test_record_duration_creates_event(self, fresh_registry: PerfMetricsRegistry) -> None:
        """record_duration 惰性创建并累加事件。"""
        fresh_registry.record_duration("scan", 12.5)
        fresh_registry.record_duration("scan", 7.5)
        snap = fresh_registry.snapshot()
        event = snap["events"]["scan"]
        assert event["calls"] == 2
        assert event["total_ms"] == pytest.approx(20.0)

    def test_increment_and_global(self, fresh_registry: PerfMetricsRegistry) -> None:
        """事件计数器与全局计数器独立记录。"""
        fresh_registry.increment("evt", "cache_hit")
        fresh_registry.increment("evt", "cache_miss", 2)
        fresh_registry.increment_global("thumbnails_generated", 5)
        snap = fresh_registry.snapshot()
        assert snap["events"]["evt"]["counters"] == {"cache_hit": 1, "cache_miss": 2}
        assert snap["global_counters"] == {"thumbnails_generated": 5}

    def test_set_metadata(self, fresh_registry: PerfMetricsRegistry) -> None:
        """set_metadata 写入事件元数据。"""
        fresh_registry.set_metadata("evt", "source", "unit-test")
        snap = fresh_registry.snapshot()
        assert snap["events"]["evt"]["metadata"] == {"source": "unit-test"}

    def test_track_records_elapsed(self, fresh_registry: PerfMetricsRegistry) -> None:
        """track 上下文记录耗时并计入 calls。"""
        with fresh_registry.track("op"):
            pass
        snap = fresh_registry.snapshot()
        assert snap["events"]["op"]["calls"] == 1
        assert snap["events"]["op"]["failures"] == 0

    def test_track_propagates_exception_and_counts_failure(self, fresh_registry: PerfMetricsRegistry) -> None:
        """track 内抛异常时向上传播且记 failure。"""
        with pytest.raises(ValueError), fresh_registry.track("boom"):
            raise ValueError("bad")
        snap = fresh_registry.snapshot()
        assert snap["events"]["boom"]["calls"] == 1
        assert snap["events"]["boom"]["failures"] == 1

    def test_track_success_false_counts_failure(self, fresh_registry: PerfMetricsRegistry) -> None:
        """track(success=False) 无异常也记 failure。"""
        with fresh_registry.track("slow", success=False):
            pass
        snap = fresh_registry.snapshot()
        assert snap["events"]["slow"]["failures"] == 1

    def test_clear_empties_events_and_globals(self, fresh_registry: PerfMetricsRegistry) -> None:
        """clear 清空事件与全局计数器。"""
        fresh_registry.record_duration("evt", 1.0)
        fresh_registry.increment_global("g", 1)
        fresh_registry.clear()
        snap = fresh_registry.snapshot()
        assert snap["events"] == {}
        assert snap["global_counters"] == {}

    def test_snapshot_sorted_by_name(self, fresh_registry: PerfMetricsRegistry) -> None:
        """快照事件按名称排序。"""
        fresh_registry.record_duration("zebra", 1.0)
        fresh_registry.record_duration("alpha", 1.0)
        assert list(fresh_registry.snapshot()["events"].keys()) == ["alpha", "zebra"]

    def test_export_writes_json(self, fresh_registry: PerfMetricsRegistry, tmp_path) -> None:
        """export_snapshot 写出可解析的 JSON 快照。"""
        fresh_registry.record_duration("evt", 2.5)
        output = tmp_path / "perf.json"
        returned = fresh_registry.export_snapshot(str(output))
        assert returned == str(output)
        assert output.is_file()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["enabled"] is True
        assert "evt" in data["events"]

    def test_summary_lines(self, fresh_registry: PerfMetricsRegistry) -> None:
        """summary_lines 为每个事件产生一行摘要。"""
        fresh_registry.record_duration("scan", 3.0)
        fresh_registry.increment("scan", "cache_hit", 1)
        lines = list(fresh_registry.summary_lines())
        assert len(lines) == 1
        assert lines[0].startswith("scan:")

    def test_disabled_by_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """FAF_PERF_METRICS_ENABLED=0 时所有写入为空操作。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        assert registry.enabled is False
        registry.record_duration("evt", 1.0)
        registry.increment("evt", "cache_hit")
        registry.increment_global("g", 1)
        with registry.track("wrapped"):
            pass
        snap = registry.snapshot()
        assert snap["events"] == {}
        assert snap["global_counters"] == {}

    def test_set_enabled_runtime_toggle(self, fresh_registry: PerfMetricsRegistry) -> None:
        """运行时 set_enabled 立即生效。"""
        fresh_registry.set_enabled(False)
        fresh_registry.record_duration("evt", 1.0)
        assert fresh_registry.snapshot()["events"] == {}
        fresh_registry.set_enabled(True)
        fresh_registry.record_duration("evt", 1.0)
        assert "evt" in fresh_registry.snapshot()["events"]


class TestConcurrency:
    """线程安全：并发写入结果精确。"""

    def test_concurrent_record_and_increment(self) -> None:
        """多线程并发 record/increment 不丢计数。"""
        registry = PerfMetricsRegistry()
        thread_count = 8
        per_thread = 200

        def worker() -> None:
            for _ in range(per_thread):
                registry.record_duration("evt", 1.0)
                registry.increment("evt", "hits")

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snap = registry.snapshot()
        assert snap["events"]["evt"]["calls"] == thread_count * per_thread
        assert snap["events"]["evt"]["counters"]["hits"] == thread_count * per_thread

    def test_concurrent_global_counter(self) -> None:
        """多线程并发全局计数器不丢计数。"""
        registry = PerfMetricsRegistry()
        thread_count = 4
        per_thread = 500

        def worker() -> None:
            for _ in range(per_thread):
                registry.increment_global("total")

        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert registry.snapshot()["global_counters"]["total"] == thread_count * per_thread


class TestEnvHelpers:
    """环境变量解析辅助函数。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("2", True),
            ("0", False),
            ("false", False),
            ("off", False),
            ("no", False),
            ("", False),
        ],
        ids=["1", "true", "yes", "on", "2", "0", "false", "off", "no", "empty"],
    )
    def test_truthy_env(self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
        """_truthy_env 真值判定矩阵。

        Args:
            raw: 环境变量值。
            expected: 期望的真值。
        """
        monkeypatch.setenv("FAF_TEST_TRUTHY", raw)
        assert _truthy_env("FAF_TEST_TRUTHY", "1") is expected

    def test_truthy_env_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设置时使用默认值 "1"（启用）。"""
        monkeypatch.delenv("FAF_TEST_TRUTHY_DEFAULT", raising=False)
        assert _truthy_env("FAF_TEST_TRUTHY_DEFAULT", "1") is True

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("100", 100),
            ("5", 64),  # 低于下限被钳制
            ("abc", 2048),  # 非法值回退默认
            ("", 2048),  # 空串解析失败回退默认
        ],
        ids=["valid", "floor-clamped", "invalid", "empty"],
    )
    def test_read_sample_limit(self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: int) -> None:
        """FAF_PERF_SAMPLE_LIMIT 解析与钳制。

        Args:
            raw: 环境变量值。
            expected: 期望的样本上限。
        """
        monkeypatch.setenv("FAF_PERF_SAMPLE_LIMIT", raw)
        assert PerfMetricsRegistry._read_sample_limit() == expected

    def test_read_sample_limit_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设置时默认 2048。"""
        monkeypatch.delenv("FAF_PERF_SAMPLE_LIMIT", raising=False)
        assert PerfMetricsRegistry._read_sample_limit() == 2048


class TestModuleLevelFunctions:
    """模块级便捷函数委托到模块全局注册表。"""

    @pytest.fixture(autouse=True)
    def _swap_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """把模块全局注册表换成全新实例，避免污染真实全局。"""
        monkeypatch.setattr(perf_metrics, "_registry", PerfMetricsRegistry())

    def test_get_perf_registry_returns_global(self) -> None:
        """get_perf_registry 返回模块全局实例。"""
        assert get_perf_registry() is perf_metrics._registry

    def test_track_perf_context(self) -> None:
        """track_perf 记录事件。"""
        with track_perf("evt"):
            pass
        assert "evt" in get_perf_snapshot()["events"]

    def test_record_perf_duration_helper(self) -> None:
        """record_perf_duration 记录事件。"""
        record_perf_duration("evt", 4.0)
        assert get_perf_snapshot()["events"]["evt"]["total_ms"] == pytest.approx(4.0)

    def test_increment_and_set_metadata_helpers(self) -> None:
        """increment_perf_counter 与 set_perf_metadata 生效。"""
        increment_perf_counter("evt", "hits", 2)
        set_perf_metadata("evt", "os", "windows")
        event = get_perf_snapshot()["events"]["evt"]
        assert event["counters"] == {"hits": 2}
        assert event["metadata"] == {"os": "windows"}

    def test_clear_and_export_helpers(self, tmp_path) -> None:
        """clear_perf_metrics 与 export_perf_metrics 生效。"""
        record_perf_duration("evt", 1.0)
        output = tmp_path / "perf.json"
        returned = export_perf_metrics(str(output))
        assert returned == str(output)
        clear_perf_metrics()
        assert get_perf_snapshot()["events"] == {}


def test_snapshot_shape() -> None:
    """snapshot 顶层字段齐全（含 frame_times 帧通道与 gui_resources 句柄段）。"""
    registry = PerfMetricsRegistry()
    snap: dict[str, object] = registry.snapshot()
    assert set(snap.keys()) == {
        "enabled",
        "global_counters",
        "events",
        "frame_times",
        "gui_resources",
    }
    assert isinstance(registry.enabled, bool)


class TestFrameProfiling:
    """帧时间剖析通道：空数据、分位数学、环形界、快照导出、开销探针。"""

    @pytest.fixture(autouse=True)
    def _isolate_frame_state(self) -> None:
        """保存/恢复帧开关并清空环形缓冲（防 stale state 串扰）。

        Yields:
            None: 无返回。
        """
        was_enabled = perf_metrics.FRAME_PROFILING_ENABLED
        reset_frame_times()
        clear_perf_metrics()
        yield
        reset_frame_times()
        clear_perf_metrics()
        set_frame_profiling_enabled(was_enabled)

    def test_empty_stats_no_crash(self) -> None:
        """空缓冲时 frame_time_stats 返回零值而不崩溃。"""
        set_frame_profiling_enabled(True)
        stats = frame_time_stats()
        assert stats == {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "count": 0}

    def test_percentile_known_dataset(self) -> None:
        """已知样本集 1..10 的 p50/p95/p99 与事件分位同口径。"""
        set_frame_profiling_enabled(True)
        for value in range(1, 11):
            record_frame_sample(float(value))
        stats = frame_time_stats()
        assert stats["count"] == 10
        assert stats["p50_ms"] == pytest.approx(6.0)
        assert stats["p95_ms"] == pytest.approx(10.0)
        assert stats["p99_ms"] == pytest.approx(10.0)

    def test_ring_buffer_bound(self) -> None:
        """写入超量后环形缓冲只保留 FRAME_RING_MAXLEN 条。"""
        set_frame_profiling_enabled(True)
        for value in range(FRAME_RING_MAXLEN + 500):
            record_frame_sample(float(value % 100))
        stats = frame_time_stats()
        assert stats["count"] == FRAME_RING_MAXLEN
        assert len(perf_metrics._frame_times) == FRAME_RING_MAXLEN

    def test_begin_end_frame_roundtrip(self) -> None:
        """begin/end_frame 配对记录一次样本；None token 为无操作。"""
        set_frame_profiling_enabled(True)
        token = begin_frame()
        assert token is not None
        end_frame(token)
        end_frame(None)
        assert frame_time_stats()["count"] == 1

    def test_disabled_records_nothing(self) -> None:
        """关闭时 begin 返回 None 且一切写入为无操作。"""
        set_frame_profiling_enabled(False)
        assert begin_frame() is None
        record_frame_sample(5.0)
        with frame_sample():
            pass
        assert frame_time_stats()["count"] == 0

    def test_frame_sample_context_manager(self) -> None:
        """frame_sample 上下文记录一次样本。"""
        set_frame_profiling_enabled(True)
        with frame_sample():
            pass
        assert frame_time_stats()["count"] == 1

    def test_snapshot_contains_frame_percentiles(self, tmp_path) -> None:
        """快照/导出 JSON 必含帧 p50/p95/p99（缺字段即失败）。"""
        set_frame_profiling_enabled(True)
        for value in range(1, 11):
            record_frame_sample(float(value))

        snap = get_perf_snapshot()
        assert {"p50_ms", "p95_ms", "p99_ms", "count"} <= set(snap["frame_times"])
        assert snap["frame_times"]["p50_ms"] == pytest.approx(6.0)

        out = tmp_path / "frame_snap.json"
        export_perf_metrics(str(out))
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert {"p50_ms", "p95_ms", "p99_ms", "count"} <= set(loaded["frame_times"])
        assert loaded["frame_times"]["count"] == 10

    def test_snapshot_empty_frames_still_has_keys(self) -> None:
        """空帧缓冲的快照仍含帧键（零值），不断言缺失。"""
        snap = get_perf_snapshot()
        assert {"p50_ms", "p95_ms", "p99_ms", "count"} <= set(snap["frame_times"])
        assert snap["frame_times"]["count"] == 0

    def test_paint_hook_overhead_within_5_percent(self) -> None:
        """关闭门控时 paint 钩子开销 ≤ 无钩子均值 +5%（≥200 样本，预热后）。

        用真实 paint 量级（~0.5ms 忙循环， delegate 实际绘制为百微秒~
        毫秒级）的确定性体量模拟一次 paint，对比无钩子与
        门控关闭钩子的均值；同时记录启用路径数值作证据（不断言）。
        """
        set_frame_profiling_enabled(False)

        def _paint_body() -> float:
            acc = 0.0
            for i in range(15000):
                acc += (float(i) * 1.7) % 5.0
            return acc

        def _paint_unhooked() -> float:
            return _paint_body()

        def _paint_hooked() -> float:
            token = begin_frame()
            try:
                return _paint_body()
            finally:
                end_frame(token)

        sample_count = 300
        for _ in range(50):
            _paint_unhooked()
            _paint_hooked()

        # 交错采样：同一循环内交替测无钩子/门控关闭，抵消机器漂移。
        plain_total = 0.0
        gated_off_total = 0.0
        for _ in range(sample_count):
            started = time.perf_counter()
            _paint_unhooked()
            plain_total += time.perf_counter() - started
            started = time.perf_counter()
            _paint_hooked()
            gated_off_total += time.perf_counter() - started
        plain_us = plain_total / sample_count * 1e6
        gated_off_us = gated_off_total / sample_count * 1e6

        set_frame_profiling_enabled(True)
        reset_frame_times()
        started = time.perf_counter()
        for _ in range(sample_count):
            _paint_hooked()
        gated_on_us = (time.perf_counter() - started) / sample_count * 1e6
        on_count = frame_time_stats()["count"]
        set_frame_profiling_enabled(False)

        print(
            f"\npaint 钩子开销探针（{sample_count} 样本，交错采样）: "
            f"unhooked={plain_us:.3f}us "
            f"gated_off={gated_off_us:.3f}us "
            f"gated_on={gated_on_us:.3f}us "
            f"on_count={on_count}"
        )
        assert gated_off_us <= plain_us * 1.05, (
            f"门控关闭钩子开销超标: {gated_off_us:.3f}us > {plain_us:.3f}us * 1.05"
        )