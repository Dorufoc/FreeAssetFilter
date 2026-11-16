"""``sopeek.core.native.api``：原生能力门面必须“永不抛异常”。

DLL 缺失、导出缺失、FFI 报错都只能表现为 ``False`` / ``None``，由调用方
回退到 Python 实现——这是本项目原生层的核心契约。
"""

from __future__ import annotations

import os

import pytest

from sopeek.core.native import api as native_api


pytestmark = pytest.mark.integration


def test_known_capabilities_are_boolean() -> None:
    for capability in ("scan", "sort", "highlight", "hash", "exif", "copy"):
        assert isinstance(native_api.supports(capability), bool)


def test_unknown_capability_is_false() -> None:
    assert native_api.supports("definitely-not-a-capability") is False
    assert native_api.supports("") is False


def test_bundled_spk_core_offers_core_capabilities() -> None:
    """随包 ``spk_core.dll`` 应至少提供扫描/排序/高亮（缺失说明资源坏了）。"""
    # The shipped spk_core is a Windows DLL. Other hosts use Python for both.
    assert native_api.supports("scan") is (os.name == "nt")
    assert native_api.supports("sort") is (os.name == "nt")


def test_scan_directory_of_real_folder_returns_entries(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    entries = native_api.scan_directory(str(tmp_path))
    if entries is None:  # 原生不可用 → 契约允许返回 None
        pytest.skip("native scan 不可用")
    names = {entry.get("name") for entry in entries}
    assert {"a.txt", "sub"} <= names


def test_scan_missing_directory_does_not_raise(tmp_path) -> None:
    result = native_api.scan_directory(str(tmp_path / "nope"))
    assert result is None or result == []
