"""``sopeek.core.memory_budget``：三档预算与单例语义。"""

from __future__ import annotations

import pytest

from sopeek.core.memory_budget import TIERS, BudgetTier, MemoryBudget


pytestmark = pytest.mark.unit


def test_tiers_cover_three_named_profiles() -> None:
    assert set(TIERS) == {"low", "balanced", "high"}
    for name, tier in TIERS.items():
        assert isinstance(tier, BudgetTier)
        assert tier.name == name


def test_tier_budgets_grow_with_tier() -> None:
    """低档预算必须严格小于高档——否则分档没有意义。"""
    low, balanced, high = TIERS["low"], TIERS["balanced"], TIERS["high"]
    for field in (
        "pixmap_cache_kb",
        "rust_thumb_cache_bytes",
        "frame_cache_bytes",
        "icon_cache_entries",
        "file_info_entries",
    ):
        assert getattr(low, field) < getattr(balanced, field) <= getattr(high, field), field


def test_budget_tier_is_frozen() -> None:
    """档位是常量表：不可在运行期被就地改写。"""
    with pytest.raises(Exception):
        TIERS["low"].pixmap_cache_kb = 1  # type: ignore[misc]


def test_memory_budget_is_a_singleton() -> None:
    assert MemoryBudget() is MemoryBudget()


def test_set_tier_switches_and_rejects_unknown() -> None:
    budget = MemoryBudget()
    original = budget.tier.name
    try:
        budget.set_tier("high")
        assert budget.tier is TIERS["high"]
        with pytest.raises(ValueError):
            budget.set_tier("ultra")
    finally:
        budget.set_tier(original)


def test_detect_tier_name_honours_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = MemoryBudget()
    monkeypatch.setenv("SPK_MEMORY_TIER", "low")
    assert budget.detect_tier_name() == "low"
    monkeypatch.setenv("SPK_MEMORY_TIER", "nonsense")
    assert budget.detect_tier_name() in TIERS
