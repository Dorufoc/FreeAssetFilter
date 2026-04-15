#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一性能埋点与指标汇总模块

提供：
- 耗时事件记录
- 调用计数
- 命中/未命中统计
- P50/P95/P99 近似分位统计（基于保留样本）
- JSON 快照导出
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, Optional

from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.utils.path_utils import get_app_data_path


def _truthy_env(name: str, default: str = "1") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() not in {"0", "false", "off", "no", ""}


@dataclass
class PerfEventStats:
    """单个事件的性能统计信息"""

    name: str
    calls: int = 0
    total_ms: float = 0.0
    min_ms: Optional[float] = None
    max_ms: float = 0.0
    failures: int = 0
    sample_limit: int = 2048
    recent_samples_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=2048))
    counters: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_sample(self, elapsed_ms: float, *, success: bool = True) -> None:
        elapsed_ms = max(0.0, float(elapsed_ms))
        self.calls += 1
        self.total_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)
        self.min_ms = elapsed_ms if self.min_ms is None else min(self.min_ms, elapsed_ms)
        self.recent_samples_ms.append(elapsed_ms)
        if not success:
            self.failures += 1

    def increment(self, counter_name: str, delta: int = 1) -> None:
        self.counters[counter_name] += int(delta)

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def _percentile(self, ratio: float) -> float:
        samples = list(self.recent_samples_ms)
        if not samples:
            return 0.0
        samples.sort()
        if len(samples) == 1:
            return float(samples[0])
        index = min(len(samples) - 1, max(0, int(math.ceil((len(samples) - 1) * ratio))))
        return float(samples[index])

    def to_dict(self) -> Dict[str, Any]:
        hits = int(self.counters.get("cache_hit", 0))
        misses = int(self.counters.get("cache_miss", 0))
        hit_base = hits + misses
        return {
            "name": self.name,
            "calls": int(self.calls),
            "total_ms": round(self.total_ms, 3),
            "avg_ms": round((self.total_ms / self.calls), 3) if self.calls else 0.0,
            "min_ms": round(float(self.min_ms), 3) if self.min_ms is not None else None,
            "max_ms": round(self.max_ms, 3),
            "p50_ms": round(self._percentile(0.50), 3),
            "p95_ms": round(self._percentile(0.95), 3),
            "p99_ms": round(self._percentile(0.99), 3),
            "failures": int(self.failures),
            "failure_rate": round((self.failures / self.calls), 6) if self.calls else 0.0,
            "cache_hit": hits,
            "cache_miss": misses,
            "cache_hit_rate": round((hits / hit_base), 6) if hit_base > 0 else None,
            "counters": dict(sorted(self.counters.items())),
            "metadata": dict(self.metadata),
            "sample_count": len(self.recent_samples_ms),
        }


class PerfMetricsRegistry:
    """线程安全的性能指标注册表"""

    def __init__(self) -> None:
        self._enabled = _truthy_env("FAF_PERF_METRICS_ENABLED", "1")
        self._lock = threading.RLock()
        self._events: Dict[str, PerfEventStats] = {}
        self._global_counters: Dict[str, int] = defaultdict(int)
        self._snapshot_dir = os.path.join(get_app_data_path(), "performance")
        self._sample_limit = self._read_sample_limit()

    @staticmethod
    def _read_sample_limit() -> int:
        raw = os.getenv("FAF_PERF_SAMPLE_LIMIT", "2048")
        try:
            return max(64, int(raw))
        except (TypeError, ValueError):
            return 2048

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def _get_or_create(self, event_name: str) -> PerfEventStats:
        event = self._events.get(event_name)
        if event is not None:
            return event
        event = PerfEventStats(name=event_name, sample_limit=self._sample_limit)
        event.recent_samples_ms = deque(maxlen=self._sample_limit)
        self._events[event_name] = event
        return event

    def record_duration(self, event_name: str, elapsed_ms: float, *, success: bool = True) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._get_or_create(event_name).add_sample(elapsed_ms, success=success)

    def increment(self, event_name: str, counter_name: str, delta: int = 1) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._get_or_create(event_name).increment(counter_name, delta)

    def set_metadata(self, event_name: str, key: str, value: Any) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._get_or_create(event_name).set_metadata(key, value)

    def increment_global(self, counter_name: str, delta: int = 1) -> None:
        if not self._enabled:
            return
        with self._lock:
            self._global_counters[counter_name] += int(delta)

    @contextmanager
    def track(self, event_name: str, *, success: bool = True):
        started = time.perf_counter()
        ok = success
        try:
            yield
        except Exception:
            ok = False
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.record_duration(event_name, elapsed_ms, success=ok)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._global_counters.clear()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            events = {
                name: stats.to_dict()
                for name, stats in sorted(self._events.items(), key=lambda item: item[0])
            }
            return {
                "enabled": self._enabled,
                "global_counters": dict(sorted(self._global_counters.items())),
                "events": events,
            }

    def export_snapshot(self, output_path: Optional[str] = None) -> str:
        snapshot = self.snapshot()
        try:
            if output_path is None:
                os.makedirs(self._snapshot_dir, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_path = os.path.join(self._snapshot_dir, f"perf_metrics_{timestamp}.json")
            else:
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)

            debug(f"[PerfMetrics] 已导出性能快照: {output_path}")
            return output_path
        except Exception as e:
            warning(f"[PerfMetrics] 导出性能快照失败: {e}")
            raise

    def summary_lines(self) -> Iterable[str]:
        data = self.snapshot()
        events = data.get("events", {})
        for name, payload in events.items():
            yield (
                f"{name}: calls={payload.get('calls', 0)}, "
                f"avg_ms={payload.get('avg_ms', 0.0)}, "
                f"p95_ms={payload.get('p95_ms', 0.0)}, "
                f"hit_rate={payload.get('cache_hit_rate')}"
            )


_registry = PerfMetricsRegistry()


def get_perf_registry() -> PerfMetricsRegistry:
    return _registry


@contextmanager
def track_perf(event_name: str, *, success: bool = True):
    with _registry.track(event_name, success=success):
        yield


def record_perf_duration(event_name: str, elapsed_ms: float, *, success: bool = True) -> None:
    _registry.record_duration(event_name, elapsed_ms, success=success)


def increment_perf_counter(event_name: str, counter_name: str, delta: int = 1) -> None:
    _registry.increment(event_name, counter_name, delta)


def set_perf_metadata(event_name: str, key: str, value: Any) -> None:
    _registry.set_metadata(event_name, key, value)


def clear_perf_metrics() -> None:
    _registry.clear()


def export_perf_metrics(output_path: Optional[str] = None) -> str:
    return _registry.export_snapshot(output_path)


def get_perf_snapshot() -> Dict[str, Any]:
    return _registry.snapshot()
