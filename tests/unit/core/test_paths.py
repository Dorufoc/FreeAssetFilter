# -*- coding: utf-8 -*-
# targets: core._paths
"""``freeassetfilter.core._paths`` 单元测试。

覆盖模块的全部 6 个公开路径解析函数：

* ``core_dir`` / ``native_bin_dir`` / ``archive_7z_dir`` / ``icons_dir``
* ``get_app_data_path``（会创建目录）
* ``soffice_paths``（环境感知的 LibreOffice 探测，永不抛异常）

契约（对齐 conftest 中 ``soffice_available`` fixture 的消费方式）：
返回的每个候选必须是**目录**而非二进制文件；指向不存在目录的固定候选
会被过滤；PATH 命中只取其父目录；``native_bin_dir`` 是前向兼容候选。

测试全部使用 ``monkeypatch``/``tmp_path`` 隔离环境变量与路径解析，
不触碰真实的 ``freeassetfilter/data/`` 或用户配置文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from freeassetfilter.core import _paths
from freeassetfilter.core._paths import (
    archive_7z_dir,
    core_dir,
    get_app_data_path,
    icons_dir,
    native_bin_dir,
    soffice_paths,
)


# =============================================================================
# 静态路径解析器（core_dir / native_bin_dir / archive_7z_dir / icons_dir）
# =============================================================================
def test_core_dir_is_absolute_directory() -> None:
    """``core_dir`` 必须返回绝对路径指向真实存在的 core 目录。"""
    result: Path = core_dir()
    assert isinstance(result, Path)
    assert result.is_absolute()
    assert result.name == "core"
    assert result.is_dir()


def test_core_dir_is_module_parent() -> None:
    """``core_dir`` 是该模块文件（_paths.py）所在目录。"""
    module_dir: Path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "freeassetfilter"
        / "core"
    )
    assert core_dir() == module_dir


def test_native_bin_dir_joins_core() -> None:
    """``native_bin_dir`` 必须为 ``core/native/bin``。"""
    expected: Path = core_dir() / "native" / "bin"
    assert native_bin_dir() == expected


def test_native_bin_dir_is_directory_when_files_exist() -> None:
    """若 bin 目录内存在文件（如 ffmpeg.exe），则其必须为目录。"""
    if any(native_bin_dir().iterdir()):
        assert native_bin_dir().is_dir()


def test_archive_7z_dir_joins_bin() -> None:
    """``archive_7z_dir`` 必须为 ``core/native/bin/7z``。"""
    assert archive_7z_dir() == native_bin_dir() / "7z"


def test_archive_7z_dir_is_directory_when_7z_exe_exists() -> None:
    """若 ``7z.exe`` 存在，则其所在目录必须为目录（AGENTS.md 已知坑点）。"""
    if (archive_7z_dir() / "7z.exe").exists():
        assert archive_7z_dir().is_dir()


def test_icons_dir_is_core_sibling() -> None:
    """``icons_dir`` 必须为 core 的兄弟目录 ``icons/``。"""
    assert icons_dir() == core_dir().parent / "icons"
    if icons_dir().is_dir():
        assert icons_dir().is_absolute()


# =============================================================================
# get_app_data_path
# =============================================================================
def test_get_app_data_path_creates_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``get_app_data_path`` 必须创建 data 目录并返回其 Path。"""
    fake_core: Path = tmp_path / "freeassetfilter" / "core"
    monkeypatch.setattr(_paths, "core_dir", lambda: fake_core)

    result: Path = get_app_data_path()
    assert result == fake_core.parent / "data"
    assert result is not None
    assert result.is_dir()


def test_get_app_data_path_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """重复调用不得抛异常（目录已存在时 ``exist_ok=True``）。"""
    fake_core: Path = tmp_path / "pkg" / "core"
    monkeypatch.setattr(_paths, "core_dir", lambda: fake_core)

    first: Path = get_app_data_path()
    second: Path = get_app_data_path()
    assert first == second
    assert first.is_dir()


# =============================================================================
# soffice_paths — 环境感知探测
# =============================================================================
def test_soffice_paths_never_raises() -> None:
    """契约：探测函数在任何机器环境上永不抛异常。"""
    soffice_paths()
    assert True


def test_soffice_paths_returns_list_of_paths() -> None:
    """返回类型必须是 ``list[Path]``，不允许 None 元素。"""
    result: List[Path] = soffice_paths()
    assert isinstance(result, list)
    assert all(isinstance(p, Path) for p in result)


def test_soffice_paths_candidates_are_directories() -> None:
    """契约：每个返回路径必须是目录（供 ``soffice_available`` fixture 检查）。"""
    for candidate in soffice_paths():
        assert candidate.is_dir(), f"{candidate} 不是目录"


def test_soffice_paths_are_deduplicated() -> None:
    """候选必须去重（Program Files 命中与 PATH 命中可能指向同一目录）。"""
    result: List[Path] = soffice_paths()
    assert len(result) == len(set(result))


def test_soffice_paths_all_exports() -> None:
    """``soffice_paths`` 必须出现在模块显式 ``__all__`` 导出清单中。"""
    assert "soffice_paths" in _paths.__all__
    assert "get_app_data_path" in _paths.__all__
    assert "core_dir" in _paths.__all__
    assert "native_bin_dir" in _paths.__all__
    assert "archive_7z_dir" in _paths.__all__
    assert "icons_dir" in _paths.__all__


def _isolate_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """将环境变量指向缺失路径并阻断 PATH / native_bin 探测。

    用于隔离固定 Program Files 候选的过滤逻辑，使结果完全可预测。
    """
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf-missing"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86-missing"))
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")


def test_soffice_paths_empty_when_nothing_detected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """无 LibreOffice / 无 PATH 命中 / 无 native_bin 时返回空列表且不抛异常。"""
    _isolate_env(monkeypatch, tmp_path)
    assert soffice_paths() == []


def test_soffice_paths_filters_non_existent_program_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """指向不存在路径的固定候选必须被过滤掉。"""
    fake_pf: Path = tmp_path / "nonexistent-pf"
    fake_pf_x86: Path = tmp_path / "nonexistent-pf-x86"
    monkeypatch.setenv("ProgramFiles", str(fake_pf))
    monkeypatch.setenv("ProgramFiles(x86)", str(fake_pf_x86))
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")

    result: List[Path] = soffice_paths()
    assert all(p != fake_pf for p in result)
    assert all(p != fake_pf_x86 for p in result)


def test_soffice_paths_program_files_requires_soffice_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Program Files 候选必须含 ``soffice.exe``/``soffice.com`` 才被返回。"""
    lo_dir: Path = tmp_path / "LibreOffice" / "program"
    lo_dir.mkdir(parents=True)

    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf-x86-missing"))
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")

    assert soffice_paths() == []

    (lo_dir / "soffice.exe").write_bytes(b"")
    assert soffice_paths() == [lo_dir]


def test_soffice_paths_which_parent_is_added(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PATH 命中的 soffice 取其父目录（目录本身的确定性存在）加入候选。"""
    bin_dir: Path = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf-missing"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86-missing"))
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")
    monkeypatch.setattr(
        _paths.shutil, "which", lambda name: str(bin_dir / "soffice.com")
    )

    result: List[Path] = soffice_paths()
    assert bin_dir in result
    assert all(p.is_dir() for p in result)


def test_soffice_paths_native_bin_dir_forward_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``native_bin_dir`` 是前向兼容候选：仅要求目录存在（可暂无 soffice）。"""
    existing: Path = tmp_path / "native-bin"
    existing.mkdir()

    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf-missing"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86-missing"))
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: existing)

    assert existing in soffice_paths()


def test_soffice_paths_dedupes_program_files_and_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Program Files 命中与 PATH 指向同一目录时必须去重。"""
    lo_dir: Path = tmp_path / "LibreOffice" / "program"
    lo_dir.mkdir(parents=True)
    (lo_dir / "soffice.exe").write_bytes(b"")

    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86-missing"))
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")
    monkeypatch.setattr(_paths.shutil, "which", lambda name: str(lo_dir / "soffice.exe"))

    result: List[Path] = soffice_paths()
    assert result.count(lo_dir) == 1