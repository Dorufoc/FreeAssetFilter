# -*- coding: utf-8 -*-
"""test_perf_metrics: perf_metrics.py 覆盖测试（todo-10, unit/utils 批 1）。

覆盖：PerfEventStats.add_sample/to_dict/_percentile、线程安全并发、
FAF_PERF_METRICS_ENABLED 禁用、export/clear/snapshot/summary_lines、
模块级便捷函数。
"""

from __future__ import annotations

import json
import threading

import pytest

from freeassetfilter.utils import perf_metrics
from freeassetfilter.utils.perf_metrics import (
    PerfEventStats,
    PerfMetricsRegistry,
    _truthy_env,
    clear_perf_metrics,
    export_perf_metrics,
    get_perf_registry,
    get_perf_snapshot,
    increment_perf_counter,
    record_perf_duration,
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
    """snapshot 顶层字段齐全。"""
    registry = PerfMetricsRegistry()
    snap: dict[str, object] = registry.snapshot()
    assert set(snap.keys()) == {"enabled", "global_counters", "events"}
    assert isinstance(registry.enabled, bool)