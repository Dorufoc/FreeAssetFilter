# -*- coding: utf-8 -*-
"""windowed 冻结态下 ``version_info`` 的资源路径解析。

冻结进程没有 CLI 入口，因此用 ``sys.frozen`` + ``sys._MEIPASS`` 模拟
PyInstaller onedir 布局，断言版本号从 ``_MEIPASS`` 读取。
"""

from __future__ import annotations

import sys

import pytest

from sopeek.utils import version_info


def test_reads_version_from_meipass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """sys.frozen=True 时从 _MEIPASS/SPKVERSION 读取。"""
    (tmp_path / "SPKVERSION").write_text(
        "v9.8.7\n2026-10-25\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert version_info.get_local_version() == "9.8.7"
    assert version_info.get_local_build_date() == "2026-10-25"


def test_frozen_internal_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """_MEIPASS 根缺失时回退到 _MEIPASS/_internal（PyInstaller 6 布局）。"""
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "SPKVERSION").write_text(
        "v1.0.0-alpha.5\n2026-05-22\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert version_info.get_local_version() == "1.0.0-alpha.5"
    assert version_info.get_local_build_date() == "2026-05-22"
