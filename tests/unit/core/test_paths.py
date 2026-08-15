# -*- coding: utf-8 -*-
"""``freeassetfilter.core._paths`` 单元测试。

重点覆盖 T2 新增的 ``soffice_paths()`` 探测函数：
- 返回值必须是 ``list[Path]``；
- 候选必须去重；
- 每个候选必须是**目录**（而非二进制文件路径）；
- 指向不存在路径的候选会被过滤掉；
- 本机无 LibreOffice 时返回空列表且不抛异常。
"""

from pathlib import Path

from freeassetfilter.core import _paths
from freeassetfilter.core._paths import soffice_paths


def test_soffice_paths_returns_list_of_paths():
    """返回类型必须是 list[Path]，且不允许 None 元素。"""
    result = soffice_paths()
    assert isinstance(result, list)
    assert all(isinstance(p, Path) for p in result)


def test_soffice_paths_never_raises():
    """探测必须永不抛异常（无 LO 机器返回空列表）。"""
    result = soffice_paths()  # noqa: F841 - 断言的是调用本身不抛异常
    assert True


def test_soffice_paths_candidates_are_directories():
    """契约：每个返回路径必须是目录（fixture 会检查目录内的 soffice 二进制）。"""
    for p in soffice_paths():
        assert p.is_dir(), f"{p} 不是目录"


def test_soffice_paths_are_deduplicated():
    """候选必须去重（Program Files 命中与 PATH 命中可能指向同一目录）。"""
    result = soffice_paths()
    assert len(result) == len(set(result))


def test_soffice_paths_filters_non_existent_program_files(monkeypatch, tmp_path):
    """指向不存在路径的固定候选必须被过滤掉。"""
    fake_pf = tmp_path / "nonexistent-pf"
    fake_pf_x86 = tmp_path / "nonexistent-pf-x86"

    monkeypatch.setenv("ProgramFiles", str(fake_pf))
    monkeypatch.setenv("ProgramFiles(x86)", str(fake_pf_x86))
    # 阻断 PATH 探测与 native_bin_dir，隔离固定候选路径的过滤逻辑。
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)

    result = soffice_paths()
    assert all(p != fake_pf for p in result)
    assert all(p != fake_pf_x86 for p in result)


def test_soffice_paths_program_files_requires_soffice_binary(monkeypatch, tmp_path):
    """Program Files 候选必须存在且内含 soffice.exe/soffice.com 才返回。"""
    lo_dir = tmp_path / "LibreOffice" / "program"
    lo_dir.mkdir(parents=True)

    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf-x86-missing"))
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")

    # 目录存在但无 soffice 二进制 -> 不返回。
    assert soffice_paths() == []

    (lo_dir / "soffice.exe").write_bytes(b"")
    assert soffice_paths() == [lo_dir]


def test_soffice_paths_which_parent_is_added(monkeypatch, tmp_path):
    """PATH 命中的 soffice 取其父目录加入候选。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf-missing"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86-missing"))
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: tmp_path / "bin-missing")
    monkeypatch.setattr(
        _paths.shutil, "which", lambda name: str(bin_dir / "soffice.com")
    )

    result = soffice_paths()
    assert bin_dir in result
    assert all(p.is_dir() for p in result)


def test_soffice_paths_in_all():
    """soffice_paths 必须出现在模块显式 __all__ 导出清单中。"""
    assert "soffice_paths" in _paths.__all__


def test_soffice_paths_native_bin_dir_forward_compat(monkeypatch, tmp_path):
    """native_bin_dir 是前向兼容候选：仅要求目录存在（可暂无 soffice）。"""
    existing = tmp_path / "native-bin"
    existing.mkdir()

    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf-missing"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86-missing"))
    monkeypatch.setattr(_paths.shutil, "which", lambda name: None)
    monkeypatch.setattr(_paths, "native_bin_dir", lambda: existing)

    assert existing in soffice_paths()
