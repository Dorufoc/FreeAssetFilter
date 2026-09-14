"""parity helper 单测（todo 5 验收）：相等 PASS / 不等 FAIL / 清单豁免。"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from tests.support.parity import ParityMismatchError, assert_parity


def _python_impl() -> Dict[str, Any]:
    """模拟 python-impl 输出（dict/list 嵌套）。"""
    return {
        "name": "alpha",
        "size": 12,
        "tags": ["x", "y"],
        "meta": {"created": "2026-01-01", "count": 3},
    }


def _native_impl_same() -> Dict[str, Any]:
    """模拟与 python-impl 一致的 native-impl 输出。"""
    return {
        "name": "alpha",
        "size": 12,
        "tags": ["x", "y"],
        "meta": {"created": "2026-01-01", "count": 3},
    }


def _native_impl_different() -> Dict[str, Any]:
    """模拟与 python-impl 不一致的 native-impl 输出（两处分歧）。"""
    return {
        "name": "alpha",
        "size": 13,
        "tags": ["x", "z"],
        "meta": {"created": "2026-01-01", "count": 3},
    }


def test_equal_pass_and_unequal_fail() -> None:
    """相等实现断言通过；不等实现断言失败且输出差异明细。"""
    assert assert_parity(_python_impl(), _native_impl_same()) == []

    with pytest.raises(ParityMismatchError) as excinfo:
        assert_parity(_python_impl(), _native_impl_different())
    message: str = str(excinfo.value)
    assert "$.size" in message
    assert "$.tags[1]" in message
    assert len(excinfo.value.diffs) == 2


def test_accepted_diffs_injection_hit_passes() -> None:
    """accepted-diffs 命中全部差异路径时豁免通过。"""
    diffs = assert_parity(
        _python_impl(),
        _native_impl_different(),
        accepted_diffs=["$.size", "$.tags[1]"],
    )
    assert len(diffs) == 2


def test_accepted_diffs_miss_still_fails() -> None:
    """清单未覆盖的差异仍 FAIL（只豁免命中的那条）。"""
    with pytest.raises(ParityMismatchError) as excinfo:
        assert_parity(
            _python_impl(),
            _native_impl_different(),
            accepted_diffs=["$.size"],
        )
    assert len(excinfo.value.diffs) == 1
    assert excinfo.value.diffs[0].startswith("$.tags[1]")
    assert len(excinfo.value.accepted) == 1
