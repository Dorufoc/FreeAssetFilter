# -*- coding: utf-8 -*-
"""心跳有序化与 tick 预算测试（P6.4）。

锁定四条契约：

1. 有序缓存**复用**：注册表未变更时 tick 不重建、不复制、不排序；
2. 注销标记：``unregister`` 置 ``dead`` 并把缓存置脏；
3. tick 预算降级：持续超预算的回调 ``every_n_ticks`` 翻倍（上限 4）；
4. 跨线程队列：heapq 保证「优先级 + 同优先级 FIFO」。

验证命令：
    python -m pytest tests/unit/core/test_heartbeat_p64.py -v
"""

from __future__ import annotations

import time
from typing import Any, List

import pytest

from sopeek.core.managers.heartbeat_manager import HeartbeatManager

pytestmark = pytest.mark.unit


@pytest.fixture()
def heartbeat(heartbeat_manager: HeartbeatManager) -> HeartbeatManager:
    """复用 conftest 的已启动心跳实例。"""
    return heartbeat_manager


def test_ordered_cache_reused_across_ticks(heartbeat: HeartbeatManager) -> None:
    """未变更时 tick 复用同一有序列表（无每 tick 复制/排序）。"""
    calls: List[int] = []
    heartbeat.register_tick_callback("p64_a", lambda: calls.append(1), priority=2)
    heartbeat.register_tick_callback("p64_b", lambda: calls.append(2), priority=1)

    heartbeat._process_normal_tick()  # noqa: SLF001
    first = heartbeat._ordered_normal  # noqa: SLF001
    assert heartbeat._ordered_dirty is False  # noqa: SLF001

    heartbeat._process_normal_tick()  # noqa: SLF001
    assert heartbeat._ordered_normal is first  # noqa: SLF001
    assert len(calls) >= 2
    # 优先级 1 在优先级 2 之前
    assert [e.priority for e in heartbeat._ordered_normal] == [1, 2]  # noqa: SLF001


def test_unregister_marks_dead_and_dirties(heartbeat: HeartbeatManager) -> None:
    """注销后条目不再被迭代，缓存置脏。"""
    calls: List[int] = []
    heartbeat.register_tick_callback("p64_x", lambda: calls.append(1))
    heartbeat._process_normal_tick()  # noqa: SLF001
    baseline = len(calls)

    assert heartbeat.unregister_tick_callback("p64_x") is True
    assert heartbeat._ordered_dirty is True  # noqa: SLF001
    heartbeat._process_normal_tick()  # noqa: SLF001
    assert len(calls) == baseline, "注销后的回调不得再执行"


def test_slow_callback_degrades_every_n_ticks(heartbeat: HeartbeatManager) -> None:
    """持续超预算的回调按倍数降频（上限 4）。"""

    def slow() -> None:
        time.sleep(0.02)

    heartbeat.register_tick_callback("p64_slow", slow, priority=3)
    for _ in range(6):
        heartbeat._process_normal_tick()  # noqa: SLF001

    entry = heartbeat._callbacks["p64_slow"]  # noqa: SLF001
    assert entry.every_n_ticks >= 2
    assert entry.every_n_ticks <= 4
    assert entry.base_every_n == 1


def test_pending_queue_priority_and_fifo(heartbeat: HeartbeatManager) -> None:
    """heapq 队列：优先级升序，同优先级保持 FIFO。"""
    order: List[str] = []
    f_low = heartbeat.request_main_thread(lambda: order.append("low"), priority=5)
    f_high1 = heartbeat.request_main_thread(lambda: order.append("high1"), priority=0)
    f_high2 = heartbeat.request_main_thread(lambda: order.append("high2"), priority=0)

    heartbeat._drain_pending_queue()  # noqa: SLF001

    assert order == ["high1", "high2", "low"]
    assert f_low.done() and f_high1.done() and f_high2.done()


def test_tick_metrics_recorded(heartbeat: HeartbeatManager) -> None:
    """tick 耗时写入 perf_metrics（provider 可读）。"""
    from sopeek.utils import perf_metrics as pm

    pm.clear_perf_metrics()
    heartbeat.register_tick_callback("p64_metric", lambda: None)
    heartbeat._process_normal_tick()  # noqa: SLF001

    snapshot = pm.get_perf_snapshot()
    assert "heartbeat.tick" in snapshot["events"]
