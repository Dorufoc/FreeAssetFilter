# -*- coding: utf-8 -*-
"""``lut_preview_native`` 加载缓存 / 重试策略单测（审查 3.1#18）。

不加载真实 .pyd：monkeypatch ``_candidates`` 控制候选集合，验证：

* 候选为空时不置位 ``_attempted``（候选后续补齐仍可恢复重试）；
* 候选存在但加载失败后粘滞（避免每次调用重复导入与告警）；
* ``reset()`` 清空缓存，允许 QA 在扩展补齐后重新探测。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest

from freeassetfilter.core.native.bridges import lut_preview_native as lpn

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_module_state() -> Iterator[None]:
    """用例前后清空模块加载缓存，避免跨用例粘滞。"""
    lpn.reset()
    yield
    lpn.reset()


def _missing_pyd() -> Path:
    """返回一个必然不存在的 .pyd 候选路径。"""
    return Path("__definitely_missing_lut_preview_cpp__.pyd")


def test_no_candidates_does_not_latch_attempted(monkeypatch: Any) -> None:
    """候选为空 → 不粘滞；补齐候选后发生真实尝试并失败粘滞。"""
    monkeypatch.setattr(lpn, "_candidates", lambda: [])
    assert lpn.is_cpp_available() is False
    assert lpn._attempted is False  # noqa: SLF001

    monkeypatch.setattr(lpn, "_candidates", lambda: [_missing_pyd()])
    assert lpn.is_cpp_available() is False
    assert lpn._attempted is True  # noqa: SLF001

    # 已真实失败：再次调用直接返回 None（不重复尝试）
    monkeypatch.setattr(lpn, "_candidates", lambda: [_missing_pyd(), _missing_pyd()])
    assert lpn.is_cpp_available() is False


def test_reset_allows_retry(monkeypatch: Any) -> None:
    """reset() 清空粘滞状态，允许扩展补齐后重新探测。"""
    monkeypatch.setattr(lpn, "_candidates", lambda: [_missing_pyd()])
    assert lpn.is_cpp_available() is False
    assert lpn._attempted is True  # noqa: SLF001

    lpn.reset()
    assert lpn._attempted is False  # noqa: SLF001
    assert lpn._module is None  # noqa: SLF001
