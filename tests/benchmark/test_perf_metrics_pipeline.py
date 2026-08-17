# -*- coding: utf-8 -*-
# targets: utils.perf_metrics
"""性能指标管线基准（todo-27 benchmark 重写）。

覆盖 ``freeassetfilter.utils.perf_metrics`` 的完整管线（非 UI 依赖）：
事件耗时记录、分位数（p50/p95/p99）、缓存命中/未命中计数、元数据、
错误路径 failure 计数、JSON 快照导出往返一致性，以及事件吞吐量下限。

断言口径：数值一致性（calls/total_ms/avg 匹配）与宽松吞吐（≥100 事件/秒，
本地纯计算 trivially 满足）。不 gate 绝对秒数上限。

注意：``PerfMetricsRegistry`` 是模块级单例（跨测试持久），autouse fixture
在每个测试前后调用 ``clear_perf_metrics()`` 保证隔离。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest

from freeassetfilter.utils.perf_metrics import (
    clear_perf_metrics,
    export_perf_metrics,
    get_perf_snapshot,
    increment_perf_counter,
    record_perf_duration,
    set_perf_metadata,
    track_perf,
)


pytestmark = pytest.mark.benchmark

#: 事件吞吐量下限（事件/秒）。
EVENT_RATE_FLOOR: float = 100.0
#: 事件循环迭代次数。
EVENT_LOOP_COUNT: int = 300
#: 测试用事件名。
_EVENT: str = "pipeline.aggregate"


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """每个测试前后清空性能注册表单例（模块级单例隔离）。

    Yields:
        None: 无返回。
    """
    clear_perf_metrics()
    yield
    clear_perf_metrics()


class TestPerfMetricsPipeline:
    """性能指标管线的数值一致性与持久化基准。"""

    def test_track_perf_records_calls_and_avg(self) -> None:
        """``track_perf`` 上下文记录 calls 与 avg_ms。"""
        with track_perf(_EVENT):
            time.sleep(0.001)

        snapshot: Dict[str, Any] = get_perf_snapshot()
        event: Dict[str, Any] = snapshot["events"][_EVENT]
        assert event["calls"] == 1
        assert event["avg_ms"] > 0.0
        assert event["total_ms"] >= event["avg_ms"]
        assert event["failure_rate"] == 0.0

    def test_percentiles_monotonic_sorted(self) -> None:
        """固定序列的 p50 ≤ p95 ≤ p99 单调性（近似有序样本）。"""
        for _ in range(10):
            record_perf_duration(_EVENT, elapsed_ms=1.0)
        for _ in range(5):
            record_perf_duration(_EVENT, elapsed_ms=10.0)
        for _ in range(2):
            record_perf_duration(_EVENT, elapsed_ms=100.0)

        event: Dict[str, Any] = get_perf_snapshot()["events"][_EVENT]
        assert event["calls"] == 17
        assert event["p50_ms"] <= event["p95_ms"] <= event["p99_ms"]
        assert event["max_ms"] == 100.0

    def test_cache_counters_and_hit_rate(self) -> None:
        """cache_hit/cache_miss 计数与命中率聚合正确。"""
        increment_perf_counter(_EVENT, "cache_hit", 8)
        increment_perf_counter(_EVENT, "cache_hit", 2)
        increment_perf_counter(_EVENT, "cache_miss", 2)

        event: Dict[str, Any] = get_perf_snapshot()["events"][_EVENT]
        assert event["cache_hit"] == 10
        assert event["cache_miss"] == 2
        assert event["cache_hit_rate"] == pytest.approx(10 / 12)
        assert event["counters"] == {"cache_hit": 10, "cache_miss": 2}

    def test_metadata_round_trip(self) -> None:
        """``set_perf_metadata`` 写入并回读。"""
        set_perf_metadata(_EVENT, "app_version", "unit-test")
        set_perf_metadata(_EVENT, "src", "pipeline-bench")

        event: Dict[str, Any] = get_perf_snapshot()["events"][_EVENT]
        assert event["metadata"]["app_version"] == "unit-test"
        assert event["metadata"]["src"] == "pipeline-bench"

    def test_failure_path_counts_failure(self) -> None:
        """``record_perf_duration`` success=False 计入 failures。"""
        record_perf_duration(_EVENT, elapsed_ms=1.0, success=True)
        record_perf_duration(_EVENT, elapsed_ms=2.0, success=False)

        event: Dict[str, Any] = get_perf_snapshot()["events"][_EVENT]
        assert event["calls"] == 2
        assert event["failures"] == 1
        assert event["failure_rate"] == pytest.approx(0.5)

    def test_export_snapshot_json_round_trip(self, tmp_path: Any) -> None:
        """``export_perf_metrics`` 写入 tmp 并 JSON 往返一致。"""
        record_perf_duration(_EVENT, elapsed_ms=5.0)
        increment_perf_counter(_EVENT, "cache_hit", 1)

        out_path: str = export_perf_metrics(str(tmp_path / "snap.json"))
        assert out_path.endswith("snap.json")

        with open(out_path, encoding="utf-8") as fh:
            loaded: Dict[str, Any] = json.load(fh)
        assert loaded["enabled"] is True
        assert _EVENT in loaded["events"]
        assert loaded["events"][_EVENT]["calls"] == 1
        assert loaded["events"][_EVENT]["cache_hit"] == 1
        assert "global_counters" in loaded

    def test_export_default_snapshot_for_regression(
        self, tmp_path: Any
    ) -> None:
        """导出到默认性能快照目录，供 ``run_tests.py regression`` 消费。

        回归子命令通过 ``_latest_perf_snapshot()`` 读取
        ``~/.freeassetfilter/performance/perf_metrics_*.json``（见
        run_tests.py ``PERF_SNAPSHOT_DIR``），故基准会话必须至少导出一次
        默认快照——否则 regression 报"未发现性能快照"退出 1。
        """
        record_perf_duration(_EVENT, elapsed_ms=3.0)

        snapshot_path: str = export_perf_metrics(str(tmp_path / "check.json"))
        assert snapshot_path.endswith("check.json")
        with open(snapshot_path, encoding="utf-8") as fh:
            loaded: Dict[str, Any] = json.load(fh)
        assert _EVENT in loaded["events"]

        # 消费方解析口径验证：_load_metrics 仅读 events[name].avg_ms/calls
        event: Dict[str, Any] = loaded["events"][_EVENT]
        assert event["avg_ms"] > 0.0
        assert event["calls"] >= 1
        assert {"avg_ms", "calls", "p95_ms", "p99_ms"} <= set(event.keys())

    def test_event_throughput_above_floor(self) -> None:
        """事件记录吞吐 ≥ 100 事件/秒（宽松下限）。"""
        start: float = time.perf_counter()
        for _ in range(EVENT_LOOP_COUNT):
            record_perf_duration(_EVENT, elapsed_ms=0.1)
        elapsed: float = time.perf_counter() - start

        rate: float = EVENT_LOOP_COUNT / elapsed if elapsed > 0 else 0.0
        print(f"\n事件吞吐: {rate:.0f} 事件/秒（{EVENT_LOOP_COUNT} 次记录）")
        snapshot: Dict[str, Any] = get_perf_snapshot()
        assert snapshot["events"][_EVENT]["calls"] == EVENT_LOOP_COUNT
        assert rate >= EVENT_RATE_FLOOR, (
            f"事件吞吐过低: {rate:.0f} 事件/秒"
        )
