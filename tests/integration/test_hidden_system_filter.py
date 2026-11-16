"""隐藏/系统文件过滤：原生流式属性位与 junction 回归测试。

重点覆盖 2026-11 修复的缺陷：原生流式扫描（``spk_scan_next``）对
junction/symlink 曾使用“跟随目标”后的 metadata 取 ``attrs``，导致链接
自身的 Hidden/System 位丢失，``C:\\Documents and Settings`` 等受保护
目录在“关闭隐藏文件”时仍然可见。

验证命令：
    python -m pytest tests/integration/test_hidden_system_filter.py -v
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Set

import pytest

from sopeek.core.native import api as native_api
from sopeek.ui.layout.file_selector_layout import FileSelectorLayout

_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4
_FILE_ATTRIBUTE_DIRECTORY = 0x10

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 有 FILE_ATTRIBUTE_*"),
]


def _set_file_attributes(path: Path, attrs: int) -> None:
    """通过 Win32 ``SetFileAttributesW`` 设置路径自身属性。

    Args:
        path: 目标文件/目录/junction。
        attrs: ``FILE_ATTRIBUTE_*`` 位组合。
    """
    set_attrs = ctypes.windll.kernel32.SetFileAttributesW
    set_attrs.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    set_attrs.restype = ctypes.c_int
    if not set_attrs(str(path), attrs):
        raise OSError(f"SetFileAttributesW 失败: {path}")


def _make_hidden_system_junction(tmp_path: Path) -> Path:
    """构造一个链接自身带 Hidden + System 的 junction。

    ``attrib +H`` 会作用到 junction 目标，故必须用 SetFileAttributesW。

    Args:
        tmp_path: pytest 每测试临时目录。

    Returns:
        Path: 指向 ``target`` 的 junction 路径。
    """
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("inside", encoding="utf-8")
    link = tmp_path / "link"
    subprocess.run(
        ["cmd", "/C", "mklink", "/J", str(link), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    _set_file_attributes(
        link, _FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM
    )
    return link


def _read_native_stream(path: Path) -> List[Dict[str, object]]:
    """读取原生流式扫描的全部条目；不可用/失败跳过测试。

    Args:
        path: 待扫描目录。

    Returns:
        8 键条目列表（7 键 + ``attrs``）。
    """
    if not native_api.supports("scanstream"):
        pytest.skip("native scanstream 不可用")
    handle = native_api.scan_begin(str(path))
    if not handle:
        pytest.skip("native scan_begin 失败")
    rows: List[Dict[str, object]] = []
    try:
        while True:
            batch = native_api.scan_next(handle, 64)
            if batch is None:
                pytest.skip("native scan_next 失败")
            if not batch:
                break
            rows.extend(batch)
    finally:
        native_api.scan_free(handle)
    return rows


def _visible_names(
    iterator: Callable[..., object],
    path: Path,
    show_hidden: bool,
    show_system: bool,
) -> Set[str]:
    """用指定扫描器 + 过滤函数计算可见文件名集合。

    Args:
        iterator: ``_iter_directory_batches`` 或 ``_iter_directory_batches_python``。
        path: 待扫描目录。
        show_hidden: 显示隐藏文件开关。
        show_system: 显示受保护系统文件开关。

    Returns:
        可见条目名集合。
    """
    attrs: Dict[str, int] = {}
    entries: List[Dict[str, object]] = []
    for batch, _is_final in iterator(
        str(path), False, lambda: False, attrs_out=attrs
    ):
        entries.extend(batch)
    return {
        str(entry["name"])
        for entry in entries
        if FileSelectorLayout._entry_visible_by_attrs(
            entry, attrs, show_hidden, show_system
        )
    }


def _expected(show_hidden: bool, show_system: bool) -> Set[str]:
    """四种开关组合下的期望可见集合（system-only 与普通目录恒可见）。"""
    names = {"plain.txt", "system.txt", "target"}
    if show_hidden:
        names.add("hidden.txt")
    if show_hidden and show_system:
        names.add("link")
    return names


@pytest.fixture()
def hidden_system_tree(tmp_path: Path) -> Path:
    """构造普通/隐藏/系统/隐藏+系统四类条目。"""
    (tmp_path / "plain.txt").write_text("p", encoding="utf-8")
    hidden = tmp_path / "hidden.txt"
    hidden.write_text("h", encoding="utf-8")
    _set_file_attributes(hidden, _FILE_ATTRIBUTE_HIDDEN)
    system = tmp_path / "system.txt"
    system.write_text("s", encoding="utf-8")
    _set_file_attributes(system, _FILE_ATTRIBUTE_SYSTEM)
    link = _make_hidden_system_junction(tmp_path)
    try:
        yield tmp_path
    finally:
        # 先删 junction 本身，避免临时目录清理跟随目标。
        if os.path.lexists(link):
            os.rmdir(link)


def test_native_stream_junction_attrs_are_link_attrs(
    hidden_system_tree: Path,
) -> None:
    """原生流式扫描的 junction attrs 必须等于 lstat，而不是目标属性。"""
    link = hidden_system_tree / "link"
    target = hidden_system_tree / "target"
    expected_attrs = os.stat(link, follow_symlinks=False).st_file_attributes
    assert expected_attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM) == (
        _FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM
    )
    target_attrs = os.stat(target, follow_symlinks=False).st_file_attributes
    assert target_attrs & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM) == 0

    rows = _read_native_stream(hidden_system_tree)
    row = next((r for r in rows if r["name"] == "link"), None)
    assert row is not None, "原生流应包含 junction"
    assert row["is_dir"] is True
    assert int(row["attrs"]) == expected_attrs
    assert int(row["attrs"]) & (_FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM) == (
        _FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM
    )


@pytest.mark.parametrize(
    ("show_hidden", "show_system"),
    [(False, False), (True, False), (True, True), (False, True)],
)
def test_stream_and_python_fallback_filter_matrix(
    hidden_system_tree: Path, show_hidden: bool, show_system: bool
) -> None:
    """原生流式与 Python 回退在四种开关组合下可见集合一致。"""
    expected = _expected(show_hidden, show_system)
    native_visible = _visible_names(
        FileSelectorLayout._iter_directory_batches,
        hidden_system_tree,
        show_hidden,
        show_system,
    )
    python_visible = _visible_names(
        FileSelectorLayout._iter_directory_batches_python,
        hidden_system_tree,
        show_hidden,
        show_system,
    )
    assert native_visible == expected
    assert python_visible == expected


@pytest.mark.parametrize(
    ("show_hidden", "show_system"),
    [(False, False), (True, False), (True, True), (False, True)],
)
def test_static_collect_filter_matches_matrix(
    hidden_system_tree: Path, show_hidden: bool, show_system: bool
) -> None:
    """静态收集路径（native scan_directory + 属性表）与流式口径一致。"""
    entries = FileSelectorLayout._collect_directory_entries(
        str(hidden_system_tree),
        show_hidden=show_hidden,
        show_system=show_system,
    )
    assert entries is not None
    assert {entry["name"] for entry in entries} == _expected(
        show_hidden, show_system
    )
