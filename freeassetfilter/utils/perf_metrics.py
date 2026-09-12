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
- 可选帧时间剖析（默认关闭，零开销）

帧时间剖析（frame-time profiling）：
    帧时间通道用于度量 paint()/paintEvent 等主线程绘制耗时。
    开关由环境变量 ``FAF_FRAME_PROFILING`` 控制，``FAF_FRAME_PROFILING=1``
    启用，其余值（或未设置）关闭。默认关闭；关闭时埋点钩子仅做一次
    模块级标志检查后立即返回，对绘制路径近乎零开销。

    典型用法（绘制入口/出口各一次标志检查）::

        token = begin_frame()
        try:
            ...  # 绘制
        finally:
            end_frame(token)

    或上下文管理器形式::

        with frame_sample():
            ...  # 绘制

    合同：环形缓冲只允许主线程写入（无锁）；读取时先拷贝。
    查询统计：:func:`frame_time_stats`；导出：快照 ``frame_times`` 段。
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

from freeassetfilter.utils.app_logger import debug, info, warning
from freeassetfilter.utils.path_utils import get_app_data_path


def _truthy_env(name: str, default: str = "1") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() not in {"0", "false", "off", "no", ""}


def _percentile_of(samples: Iterable[float], ratio: float) -> float:
    """按既有分位公式计算分位数（与 PerfEventStats._percentile 同口径）。

    Args:
        samples: 样本序列（内部拷贝后排序，不修改入参）。
        ratio: 分位比（0.0~1.0）。

    Returns:
        float: 分位值；无样本时返回 0.0。
    """
    ordered = sorted(samples)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    index = min(len(ordered) - 1, max(0, int(math.ceil((len(ordered) - 1) * ratio))))
    return float(ordered[index])


#: 帧时间环形缓冲上限（主线程写入，读时拷贝）。
FRAME_RING_MAXLEN: int = 2048

#: 帧剖析总开关（模块级标志，每帧只读一次，开销可忽略）。
#: 由环境变量 FAF_FRAME_PROFILING 控制，默认关闭。
FRAME_PROFILING_ENABLED: bool = _truthy_env("FAF_FRAME_PROFILING", "0")

#: 帧耗时环形缓冲（毫秒）。只允许主线程写入，无锁；读取前先拷贝。
_frame_times: Deque[float] = deque(maxlen=FRAME_RING_MAXLEN)


def is_frame_profiling_enabled() -> bool:
    """返回帧时间剖析是否启用。

    Returns:
        bool: 启用返回 True，否则返回 False。
    """
    return FRAME_PROFILING_ENABLED


def set_frame_profiling_enabled(enabled: bool) -> None:
    """运行时切换帧时间剖析开关（主要供测试与手动 QA 使用）。

    Args:
        enabled: True 启用，False 关闭。
    """
    global FRAME_PROFILING_ENABLED
    FRAME_PROFILING_ENABLED = bool(enabled)


def refresh_frame_profiling_from_env() -> bool:
    """从环境变量 FAF_FRAME_PROFILING 重新读取开关。

    Returns:
        bool: 读取后的开关状态。
    """
    set_frame_profiling_enabled(_truthy_env("FAF_FRAME_PROFILING", "0"))
    return FRAME_PROFILING_ENABLED


def reset_frame_times() -> None:
    """清空帧时间环形缓冲（测试隔离用，主线程调用）。"""
    _frame_times.clear()


def record_frame_sample(elapsed_ms: float) -> None:
    """记录一次帧耗时样本（毫秒）；关闭时为无操作。

    只允许主线程调用（无锁写入环形缓冲）。

    Args:
        elapsed_ms: 帧耗时（毫秒），负值钳制为 0.0。
    """
    if not FRAME_PROFILING_ENABLED:
        return
    _frame_times.append(max(0.0, float(elapsed_ms)))


def begin_frame() -> Optional[float]:
    """帧开始打点，返回 perf_counter 时间戳；关闭时返回 None。

    关闭路径仅做一次模块级标志检查，开销可忽略。

    Returns:
        Optional[float]: 启用时为起始时间戳，关闭时为 None。
    """
    if not FRAME_PROFILING_ENABLED:
        return None
    return time.perf_counter()


def end_frame(token: Optional[float]) -> None:
    """帧结束打点，将耗时记入环形缓冲；token 为 None 时无操作。

    Args:
        token: :func:`begin_frame` 返回的时间戳。
    """
    if token is None or not FRAME_PROFILING_ENABLED:
        return
    record_frame_sample((time.perf_counter() - token) * 1000.0)


@contextmanager
def frame_sample():
    """帧耗时上下文管理器（关闭时仅一次标志检查，近乎零开销）。

    Yields:
        None: 无返回值。
    """
    token = begin_frame()
    try:
        yield
    finally:
        end_frame(token)


def frame_time_stats() -> Dict[str, Any]:
    """计算帧时间分位统计（读时拷贝，与事件分位同口径）。

    Returns:
        Dict[str, Any]: ``{"p50_ms", "p95_ms", "p99_ms", "count"}``；
            无样本时分位为 0.0 且 ``count`` 为 0，不抛异常。
    """
    samples = list(_frame_times)
    return {
        "p50_ms": round(_percentile_of(samples, 0.50), 3),
        "p95_ms": round(_percentile_of(samples, 0.95), 3),
        "p99_ms": round(_percentile_of(samples, 0.99), 3),
        "count": len(samples),
    }


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
        return _percentile_of(self.recent_samples_ms, ratio)

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
        debug(f"PerfMetricsRegistry initialized, enabled={self._enabled}, sample_limit={self._sample_limit}")

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
        old_val = self._enabled
        self._enabled = bool(enabled)
        if old_val != self._enabled:
            info(f"PerfMetrics enabled changed: {old_val} -> {self._enabled}")

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
            event_count = len(self._events)
            counter_count = len(self._global_counters)
            self._events.clear()
            self._global_counters.clear()
            reset_frame_times()
            debug(f"PerfMetrics cleared: {event_count} events, {counter_count} counters")

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            events = {
                name: stats.to_dict()
                for name, stats in sorted(self._events.items(), key=lambda item: item[0])
            }
            # W10 句柄预算（加法式扩展：既有键保持不变）。
            # 延迟导入避免 core/native 与 utils 之间的导入环；
            # 采样失败时降级为计数字段全 None 的字典，不抛异常。
            try:
                from freeassetfilter.core.native.platform_monitor import (
                    sample_gui_resources,
                )

                gui_resources = sample_gui_resources()
            except Exception:
                gui_resources = {
                    "user_objects": None,
                    "gdi_objects": None,
                    "user_warn": False,
                    "gdi_warn": False,
                    "user_over_cap": False,
                    "gdi_over_cap": False,
                    "platform": "unknown",
                }
            return {
                "enabled": self._enabled,
                "global_counters": dict(sorted(self._global_counters.items())),
                "events": events,
                "frame_times": frame_time_stats(),
                "gui_resources": gui_resources,
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

            debug(f"性能快照已导出: {output_path}")
            return output_path
        except Exception as e:
            warning(f"导出性能快照失败: {e}")
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
