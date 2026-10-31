# -*- coding: utf-8 -*-
"""内存/显存预算器测试（P7.2）。

锁定五条契约：

1. 档位可由 ``SPK_MEMORY_TIER`` 强制覆盖；
2. ``apply()`` 把 QPixmapCache 上限设为档位值（幂等）；
3. ``snapshot()`` 形状稳定（含档位、阈值、进程/系统/显存段、账本）；
4. 压力分级按 RSS 阈值判定并派发回调（回调异常被隔离）；
5. 账本 ``register_cache`` / ``note`` 正确累计。

验证命令：
    python -m pytest tests/unit/core/test_memory_budget.py -v
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from PySide6.QtGui import QPixmapCache

from sopeek.core import memory_budget as mb

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_budget() -> Any:
    """每个用例前后重置单例。"""
    mb.reset_for_tests()
    yield
    mb.reset_for_tests()


def test_tier_override_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量可强制档位。"""
    monkeypatch.setenv("SPK_MEMORY_TIER", "low")
    budget = mb.get_memory_budget()
    assert budget.detect_tier_name() == "low"

    monkeypatch.setenv("SPK_MEMORY_TIER", "high")
    assert budget.detect_tier_name() == "high"


def test_default_tier_is_balanced_for_midrange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """12–32GB 机器自动落在 balanced（与改造前上限一致）。"""
    monkeypatch.delenv("SPK_MEMORY_TIER", raising=False)
    budget = mb.get_memory_budget()
    monkeypatch.setattr(
        mb.memory_probe,
        "read_system_memory",
        lambda: {"total_phys_bytes": 24 * 1024 * 1024 * 1024},
    )
    assert budget.detect_tier_name() == "balanced"
    assert budget.tier.rust_thumb_cache_bytes == 200 * 1024 * 1024


def test_apply_sets_pixmap_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """apply() 把 QPixmapCache 设为档位值且幂等。"""
    monkeypatch.setenv("SPK_MEMORY_TIER", "low")
    budget = mb.get_memory_budget()
    budget.set_tier("low")
    result = budget.apply()
    assert "qpixmap_cache" in result["applied"]
    assert QPixmapCache.cacheLimit() == mb.TIERS["low"].pixmap_cache_kb

    budget.apply()
    assert QPixmapCache.cacheLimit() == mb.TIERS["low"].pixmap_cache_kb


def test_snapshot_shape() -> None:
    """snapshot 包含档位、阈值与三段采样。"""
    budget = mb.get_memory_budget()
    snapshot = budget.snapshot()
    assert snapshot["tier"] in {"low", "balanced", "high"}
    assert "tier_values" in snapshot
    assert snapshot["process"]["rss_bytes"] > 0
    assert snapshot["system"]["total_phys_bytes"] > 0
    assert snapshot["gpu"]["available"] is False
    assert isinstance(snapshot["ledger"], dict)


def test_pressure_detection_and_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """RSS 超 hard 阈值触发 rss_hard 并派发回调；回调异常被隔离。"""
    budget = mb.get_memory_budget()
    hard = budget.tier.rss_hard_bytes
    monkeypatch.setattr(
        mb.memory_probe,
        "snapshot",
        lambda: {
            "process": {"rss_bytes": hard + 1},
            "system": {"total_phys_bytes": 1},
            "gpu": {"available": False},
        },
    )
    levels: List[str] = []

    def good(level: str, _sample: Dict[str, Any]) -> None:
        levels.append(level)

    def bad(_level: str, _sample: Dict[str, Any]) -> None:
        raise RuntimeError("boom")

    budget.on_pressure(good)
    budget.on_pressure(bad)
    result = budget.sample()

    assert result["pressure"] == "rss_hard"
    assert levels == ["rss_hard"]


def test_ledger_accumulates() -> None:
    """账本按 put/evict/entries_delta 累计。"""
    budget = mb.get_memory_budget()
    budget.register_cache("demo", cap_bytes=1000, cap_entries=10)
    budget.note("demo", put_bytes=300, entries_delta=3)
    budget.note("demo", evict_bytes=100, entries_delta=-1)

    entry = budget.ledger()["demo"]
    assert entry["bytes"] == 200
    assert entry["entries"] == 2
    assert entry["cap_bytes"] == 1000


def test_tier_values_are_monotonic() -> None:
    """三档的缓存上限单调递增（low < balanced < high）。"""
    low, balanced, high = mb.TIERS["low"], mb.TIERS["balanced"], mb.TIERS["high"]
    assert low.pixmap_cache_kb < balanced.pixmap_cache_kb < high.pixmap_cache_kb
    assert (
        low.rust_thumb_cache_bytes
        < balanced.rust_thumb_cache_bytes
        < high.rust_thumb_cache_bytes
    )
    assert (
        low.fluid_texture_max_px
        <= balanced.fluid_texture_max_px
        <= high.fluid_texture_max_px
    )
