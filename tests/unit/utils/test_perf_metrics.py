#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PerfMetrics 模块单元测试

测试 PerfEventStats、PerfMetricsRegistry 及模块级便捷函数的正确性。
"""

import json
import os
import math
from typing import Any, Dict
from unittest.mock import patch

import pytest

from freeassetfilter.utils.perf_metrics import (
    PerfEventStats,
    PerfMetricsRegistry,
    track_perf,
    record_perf_duration,
    increment_perf_counter,
    set_perf_metadata,
    clear_perf_metrics,
    get_perf_snapshot,
    get_perf_registry,
    export_perf_metrics,
)


# ---------------------------------------------------------------------------
# 模块级夹具 —— 每个测试前重置全局单例
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """自动在每条测试前清空全局 _registry，保证测试隔离。"""
    clear_perf_metrics()


# ---------------------------------------------------------------------------
# PerfEventStats
# ---------------------------------------------------------------------------


class TestPerfEventStats:
    """PerfEventStats 数据类的单元测试"""

    def test_add_sample_basic(self) -> None:
        """add_sample() 基本调用后 calls / total_ms / min_ms / max_ms 正确。"""
        stats = PerfEventStats(name="test_event")
        stats.add_sample(10.5)
        stats.add_sample(20.3)

        assert stats.calls == 2
        assert stats.total_ms == pytest.approx(30.8)
        assert stats.min_ms == pytest.approx(10.5)
        assert stats.max_ms == pytest.approx(20.3)

    def test_add_sample_success_false(self) -> None:
        """add_sample(success=False) 使 failures 计数增加。"""
        stats = PerfEventStats(name="fail_event")
        stats.add_sample(5.0, success=False)
        stats.add_sample(3.0, success=True)

        assert stats.failures == 1

    def test_add_sample_clamps_negative(self) -> None:
        """add_sample() 将负值钳位到 0.0。"""
        stats = PerfEventStats(name="neg_event")
        stats.add_sample(-1.0)
        assert stats.total_ms == pytest.approx(0.0)
        assert stats.min_ms == pytest.approx(0.0)

    def test_increment(self) -> None:
        """increment() 累加计数器。"""
        stats = PerfEventStats(name="counter_event")
        stats.increment("cache_hit")
        stats.increment("cache_hit", 2)
        stats.increment("cache_miss")

        assert stats.counters["cache_hit"] == 3
        assert stats.counters["cache_miss"] == 1

    def test_set_metadata(self) -> None:
        """set_metadata() 存储键值元数据。"""
        stats = PerfEventStats(name="meta_event")
        stats.set_metadata("source", "test")
        stats.set_metadata("version", 2)

        assert stats.metadata == {"source": "test", "version": 2}

    def test_to_dict_fields(self) -> None:
        """to_dict() 返回包含所有预期字段的字典。"""
        stats = PerfEventStats(name="dict_event")
        stats.add_sample(100.0)
        stats.add_sample(200.0)
        stats.increment("cache_hit", 3)
        stats.set_metadata("key", "val")

        d = stats.to_dict()

        expected_keys = {
            "name", "calls", "total_ms", "avg_ms", "min_ms", "max_ms",
            "p50_ms", "p95_ms", "p99_ms", "failures", "failure_rate",
            "cache_hit", "cache_miss", "cache_hit_rate",
            "counters", "metadata", "sample_count",
        }
        assert set(d.keys()) == expected_keys
        assert d["name"] == "dict_event"
        assert d["calls"] == 2
        assert d["total_ms"] == 300.0
        assert d["avg_ms"] == 150.0
        assert d["min_ms"] == 100.0
        assert d["max_ms"] == 200.0
        assert d["cache_hit"] == 3
        assert d["metadata"] == {"key": "val"}

    def test_to_dict_zero_calls(self) -> None:
        """to_dict() 在零调用时 avg_ms / failure_rate 为 0.0，cache_hit_rate 为 None。"""
        stats = PerfEventStats(name="empty_event")
        d = stats.to_dict()

        assert d["calls"] == 0
        assert d["avg_ms"] == 0.0
        assert d["failure_rate"] == 0.0
        assert d["cache_hit_rate"] is None

    def test_percentile_single_sample(self) -> None:
        """_percentile() 单样本返回该值。"""
        stats = PerfEventStats(name="p_single")
        stats.add_sample(42.0)
        assert stats._percentile(0.50) == 42.0
        assert stats._percentile(0.99) == 42.0

    def test_percentile_empty(self) -> None:
        """_percentile() 空样本返回 0.0。"""
        stats = PerfEventStats(name="p_empty")
        assert stats._percentile(0.50) == 0.0

    def test_percentile_p50_p95_p99(self) -> None:
        """_percentile() 对多样本计算 P50 / P95 / P99 近似值。

        算法: index = min(N-1, max(0, ceil((N-1) * ratio)))
        对 [0..99] 共 100 个样本:
          P50: ceil(99*0.50)=50 → samples[50]=50
          P95: ceil(99*0.95)=95 → samples[95]=95  (实际 95→94，因为 ceil(94.05)=95)
          P99: ceil(99*0.99)=99 → samples[99]=99
        """
        stats = PerfEventStats(name="p_multi")
        for i in range(100):
            stats.add_sample(float(i))

        assert stats._percentile(0.50) == pytest.approx(50.0)
        assert stats._percentile(0.95) == pytest.approx(95.0)
        assert stats._percentile(0.99) == pytest.approx(99.0)

    def test_min_ms_none_when_no_samples(self) -> None:
        """未调用 add_sample 时 min_ms 为 None。"""
        stats = PerfEventStats(name="no_samples")
        assert stats.min_ms is None

    def test_counters_sorted_in_dict(self) -> None:
        """to_dict() 的 counters 按键排序。"""
        stats = PerfEventStats(name="sort_test")
        stats.increment("z_counter")
        stats.increment("a_counter")
        stats.increment("m_counter")
        d = stats.to_dict()
        keys = list(d["counters"].keys())
        assert keys == ["a_counter", "m_counter", "z_counter"]


# ---------------------------------------------------------------------------
# PerfMetricsRegistry
# ---------------------------------------------------------------------------


class TestPerfMetricsRegistry:
    """PerfMetricsRegistry 的单元测试"""

    def test_constructed_enabled(self) -> None:
        """构造后 enabled 属性为 True（默认环境变量）。"""
        registry = PerfMetricsRegistry()
        assert registry.enabled is True

    def test_set_enabled_false_skips_record(self) -> None:
        """set_enabled(False) 后 record_duration() 不记录任何事件。"""
        registry = PerfMetricsRegistry()
        registry.set_enabled(False)
        registry.record_duration("ev", 100.0)
        snapshot = registry.snapshot()
        assert len(snapshot["events"]) == 0

    def test_set_enabled_then_true_records(self) -> None:
        """disable 后重新 enable，record_duration() 恢复正常。"""
        registry = PerfMetricsRegistry()
        registry.set_enabled(False)
        registry.record_duration("ev", 100.0)
        registry.set_enabled(True)
        registry.record_duration("ev", 50.0)
        snapshot = registry.snapshot()
        assert "ev" in snapshot["events"]
        assert snapshot["events"]["ev"]["calls"] == 1

    def test_record_duration_basic(self) -> None:
        """record_duration() 基本调用后事件被创建并记录。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("load_file", 123.456)
        snapshot = registry.snapshot()
        ev = snapshot["events"]["load_file"]
        assert ev["calls"] == 1
        assert ev["total_ms"] == pytest.approx(123.456, rel=1e-3)

    def test_record_duration_accumulates(self) -> None:
        """多次 record_duration 累加到同一事件。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("acc", 10.0)
        registry.record_duration("acc", 20.0)
        registry.record_duration("acc", 30.0)
        ev = registry.snapshot()["events"]["acc"]
        assert ev["calls"] == 3
        assert ev["total_ms"] == pytest.approx(60.0)
        assert ev["min_ms"] == pytest.approx(10.0)
        assert ev["max_ms"] == pytest.approx(30.0)
        assert ev["avg_ms"] == pytest.approx(20.0)

    def test_record_duration_failure(self) -> None:
        """record_duration(..., success=False) 记录失败。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("fail_ev", 5.0, success=False)
        ev = registry.snapshot()["events"]["fail_ev"]
        assert ev["failures"] == 1

    def test_track_context_manager_success(self) -> None:
        """track() context manager 正常路径记录耗时。"""
        registry = PerfMetricsRegistry()
        with registry.track("ctx_ok"):
            pass
        ev = registry.snapshot()["events"]["ctx_ok"]
        assert ev["calls"] == 1
        assert ev["failures"] == 0
        # total_ms 在极快机器上可能 round 为 0.0，这可以接受
        assert ev["total_ms"] >= 0.0

    def test_track_context_manager_exception(self) -> None:
        """track() context manager 异常路径记录失败并向上抛出。"""
        registry = PerfMetricsRegistry()

        with pytest.raises(ValueError, match="boom"):
            with registry.track("ctx_fail"):
                raise ValueError("boom")

        ev = registry.snapshot()["events"]["ctx_fail"]
        assert ev["calls"] == 1
        assert ev["failures"] == 1

    def test_track_overrides_success_flag(self) -> None:
        """track(success=False) 在无异常时仍标记为失败。"""
        registry = PerfMetricsRegistry()
        with registry.track("override_fail", success=False):
            pass
        ev = registry.snapshot()["events"]["override_fail"]
        assert ev["failures"] == 1

    def test_clear_removes_all_events(self) -> None:
        """clear() 清空所有事件和全局计数器。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("a", 1.0)
        registry.record_duration("b", 2.0)
        registry.increment_global("g", 5)
        registry.clear()

        snapshot = registry.snapshot()
        assert len(snapshot["events"]) == 0
        assert snapshot["global_counters"] == {}

    def test_clear_then_record_works(self) -> None:
        """clear() 后 record_duration() 仍能正常工作。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("before", 1.0)
        registry.clear()
        registry.record_duration("after", 2.0)
        snapshot = registry.snapshot()
        assert "before" not in snapshot["events"]
        assert snapshot["events"]["after"]["calls"] == 1

    def test_snapshot_structure(self) -> None:
        """snapshot() 返回 enabled / global_counters / events 三个顶级字段。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("x", 1.0)
        registry.increment_global("total", 42)
        snap = registry.snapshot()

        assert set(snap.keys()) == {"enabled", "global_counters", "events"}
        assert snap["enabled"] is True
        assert snap["global_counters"] == {"total": 42}
        assert "x" in snap["events"]

    def test_snapshot_events_sorted(self) -> None:
        """snapshot() 中的 events 按键排序。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("z", 1.0)
        registry.record_duration("a", 1.0)
        registry.record_duration("m", 1.0)
        events = registry.snapshot()["events"]
        assert list(events.keys()) == ["a", "m", "z"]

    def test_export_snapshot_to_path(self, tmp_path: Any) -> None:
        """export_snapshot() 导出到指定路径，文件内容为合法 JSON。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("export_ev", 7.5)
        out = tmp_path / "snap.json"

        result_path = registry.export_snapshot(str(out))
        assert result_path == str(out)
        assert out.exists()

        with open(out, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "events" in data
        assert "export_ev" in data["events"]

    def test_export_snapshot_default_path(self, monkeypatch: Any) -> None:
        """export_snapshot() 无参数时自动生成路径。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("auto_ev", 3.0)

        with monkeypatch.context() as m:
            m.setattr(registry, "_snapshot_dir", str(tmp_path := pytest.importorskip("pytest").TempdirFactory))
            # Use a concrete tmp_path
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                m.setattr(registry, "_snapshot_dir", d)
                result = registry.export_snapshot()
                assert os.path.isfile(result)
                assert result.startswith(d)

    def test_increment_global(self) -> None:
        """increment_global() 增加全局计数器。"""
        registry = PerfMetricsRegistry()
        registry.increment_global("api_calls")
        registry.increment_global("api_calls", 3)
        assert registry.snapshot()["global_counters"] == {"api_calls": 4}

    def test_increment_global_disabled(self) -> None:
        """set_enabled(False) 后 increment_global() 不生效。"""
        registry = PerfMetricsRegistry()
        registry.set_enabled(False)
        registry.increment_global("should_not_count")
        assert registry.snapshot()["global_counters"] == {}

    def test_increment_counter_on_event(self) -> None:
        """increment() 在指定事件上增加计数器。"""
        registry = PerfMetricsRegistry()
        registry.increment("ev", "cache_hit", 2)
        ev = registry.snapshot()["events"]["ev"]
        assert ev["counters"]["cache_hit"] == 2

    def test_set_metadata_on_event(self) -> None:
        """set_metadata() 在指定事件上存储元数据。"""
        registry = PerfMetricsRegistry()
        registry.set_metadata("ev", "format", "PNG")
        ev = registry.snapshot()["events"]["ev"]
        assert ev["metadata"]["format"] == "PNG"

    def test_export_raises_on_bad_path(self) -> None:
        """export_snapshot() 在不可写入路径时向上抛出异常。"""
        registry = PerfMetricsRegistry()
        with pytest.raises(Exception):
            registry.export_snapshot(r"Z:\nonexistent\perf.json")

    def test_summary_lines_yields_strings(self) -> None:
        """summary_lines() 生成可读的摘要行。"""
        registry = PerfMetricsRegistry()
        registry.record_duration("summary_test", 10.0)
        registry.increment("summary_test", "cache_hit", 5)
        lines = list(registry.summary_lines())
        assert len(lines) == 1
        assert "summary_test" in lines[0]
        assert "calls=1" in lines[0]
        assert "hit_rate" in lines[0]


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    """模块级便捷函数的单元测试"""

    def test_get_perf_registry_returns_singleton(self) -> None:
        """get_perf_registry() 返回单例 _registry。"""
        reg1 = get_perf_registry()
        reg2 = get_perf_registry()
        assert reg1 is reg2

    def test_track_perf_context_manager(self) -> None:
        """track_perf() context manager 记录事件。"""
        with track_perf("module_track"):
            pass
        snapshot = get_perf_snapshot()
        assert "module_track" in snapshot["events"]

    def test_track_perf_context_manager_exception(self) -> None:
        """track_perf() 在异常时记录失败。"""
        with pytest.raises(RuntimeError):
            with track_perf("module_fail"):
                raise RuntimeError("bad")
        snapshot = get_perf_snapshot()
        ev = snapshot["events"]["module_fail"]
        assert ev["failures"] == 1

    def test_record_perf_duration(self) -> None:
        """record_perf_duration() 模块级函数记录耗时。"""
        record_perf_duration("module_dur", 55.5)
        snapshot = get_perf_snapshot()
        assert snapshot["events"]["module_dur"]["total_ms"] == pytest.approx(55.5)

    def test_record_perf_duration_failure(self) -> None:
        """record_perf_duration(success=False) 记录失败。"""
        record_perf_duration("module_fail_dur", 1.0, success=False)
        ev = get_perf_snapshot()["events"]["module_fail_dur"]
        assert ev["failures"] == 1

    def test_increment_perf_counter(self) -> None:
        """increment_perf_counter() 模块级函数增加事件计数器。"""
        increment_perf_counter("mod_counter", "cache_hit", 3)
        ev = get_perf_snapshot()["events"]["mod_counter"]
        assert ev["counters"]["cache_hit"] == 3

    def test_set_perf_metadata(self) -> None:
        """set_perf_metadata() 模块级函数设置事件元数据。"""
        set_perf_metadata("mod_meta", "key", "value")
        ev = get_perf_snapshot()["events"]["mod_meta"]
        assert ev["metadata"]["key"] == "value"

    def test_clear_perf_metrics(self) -> None:
        """clear_perf_metrics() 清空所有数据。"""
        record_perf_duration("before_clear", 1.0)
        clear_perf_metrics()
        snapshot = get_perf_snapshot()
        assert len(snapshot["events"]) == 0

    def test_get_perf_snapshot(self) -> None:
        """get_perf_snapshot() 返回当前快照字典。"""
        record_perf_duration("snap_ev", 1.0)
        snap = get_perf_snapshot()
        assert "snap_ev" in snap["events"]

    def test_export_perf_metrics(self, tmp_path: Any) -> None:
        """export_perf_metrics() 导出到指定文件。"""
        record_perf_duration("export_mod", 1.0)
        out = tmp_path / "mod_export.json"
        path = export_perf_metrics(str(out))
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "export_mod" in data["events"]


# ---------------------------------------------------------------------------
# 环境变量控制
# ---------------------------------------------------------------------------


class TestEnvDisabled:
    """FAF_PERF_METRICS_ENABLED=0 时代码行为的测试"""

    def test_disabled_by_env(self, monkeypatch: Any) -> None:
        """环境变量设 0 后新建 registry 默认 disabled。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        assert registry.enabled is False

    def test_disabled_does_not_record(self, monkeypatch: Any) -> None:
        """disabled 时 record_duration 不记录。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        registry.record_duration("silent", 99.0)
        assert "silent" not in registry.snapshot()["events"]

    def test_disabled_track_does_not_record(self, monkeypatch: Any) -> None:
        """disabled 时 track() context manager 不记录。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        with registry.track("silent_track"):
            pass
        assert "silent_track" not in registry.snapshot()["events"]

    def test_disabled_increment_does_not_record(self, monkeypatch: Any) -> None:
        """disabled 时 increment() 不记录。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        registry.increment("silent_cnt", "cache_hit")
        assert "silent_cnt" not in registry.snapshot()["events"]

    def test_disabled_set_metadata_does_not_record(self, monkeypatch: Any) -> None:
        """disabled 时 set_metadata() 不记录。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        registry.set_metadata("silent_meta", "k", "v")
        assert "silent_meta" not in registry.snapshot()["events"]

    def test_disabled_track_exception_still_propagates(self, monkeypatch: Any) -> None:
        """disabled 时 track() context manager 异常仍向上传播。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        with pytest.raises(ValueError, match="still_propagate"):
            with registry.track("no_record"):
                raise ValueError("still_propagate")

    def test_disabled_global_counter_does_not_record(self, monkeypatch: Any) -> None:
        """disabled 时 increment_global() 不记录。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        registry = PerfMetricsRegistry()
        registry.increment_global("silent_g")
        assert registry.snapshot()["global_counters"] == {}

    def test_disabled_module_functions_obey_env(self, monkeypatch: Any) -> None:
        """模块级函数在 disabled 时遵照 registry 状态不记录。"""
        monkeypatch.setenv("FAF_PERF_METRICS_ENABLED", "0")
        # 重新导入模块或重新创建 registry 以应用环境变量
        # 由于 _registry 是已创建的实例，我们需要替换它
        import freeassetfilter.utils.perf_metrics as pm
        old_registry = pm._registry
        pm._registry = PerfMetricsRegistry()
        try:
            record_perf_duration("module_disabled", 1.0)
            snap = get_perf_snapshot()
            assert "module_disabled" not in snap["events"]
        finally:
            pm._registry = old_registry
