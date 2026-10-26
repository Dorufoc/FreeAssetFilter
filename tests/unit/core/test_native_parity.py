# -*- coding: utf-8 -*-
"""X1/X2：原生导出与 Python oracle 的逐导出 parity 套件。

背景（计划「跨阶段：防漂移」）：

* X1：Python oracle 不进生产分支，只在测试里做对照；
* X2：每个导出都要有一条 parity 用例，而不是只靠人工核对。

本模块对**有明确 Python oracle 的导出**逐项对拍：

====================== ==================================================
导出                    Python oracle
====================== ==================================================
``scan_directory``     ``FileSelectorLayout._collect_directory_entries_python``
``sort_entries``       ``FileSelectorLayout._apply_sort``（8 模式）
``copy_files``         ``shutil.copy2``
``sum_directory_sizes`` ``os.walk`` 递归求和（``follow_symlinks=False``）
``replace_svg_colors`` 纯 Python 字符串替换（同一颜色映射）
====================== ==================================================

DLL 缺失时整体 skip（不阻塞无 native 环境）。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from freeassetfilter.core.native import api as native_api

#: 布局模块用短路径导入（``from theme import tm``），需 ``freeassetfilter/ui`` 在 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

pytestmark = pytest.mark.unit


def _require(capability: str) -> None:
    """能力不可用时跳过（旧 DLL / 无 DLL 环境）。"""
    if not native_api.supports(capability):
        pytest.skip(f"native 能力 {capability} 不可用")


@pytest.fixture()
def sample_tree(tmp_path: Path) -> Path:
    """构造带子目录、空文件、带内容文件的样例树。"""
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    (root / "B.TXT").write_text("x" * 100, encoding="utf-8")
    (root / "empty.bin").write_bytes(b"")
    sub = root / "sub dir"
    sub.mkdir()
    (sub / "inner.dat").write_bytes(b"1234567890")
    nested = sub / "deeper"
    nested.mkdir()
    (nested / "leaf.log").write_text("leaf", encoding="utf-8")
    return root


def test_scan_directory_parity(sample_tree: Path) -> None:
    """``scan_directory`` 与 Python 收集器逐字段相等（7 键 + 时间字符串）。"""
    _require("scan")
    from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout

    native_rows = native_api.scan_directory(str(sample_tree))
    assert native_rows is not None
    python_rows = FileSelectorLayout._collect_directory_entries_python(
        str(sample_tree)
    )
    assert python_rows is not None

    def _key(row: Dict[str, Any]) -> tuple:
        return (row["name"], row["path"], row["is_dir"], row["size"])

    native_sorted = sorted(native_rows, key=_key)
    python_sorted = sorted(python_rows, key=_key)
    assert len(native_sorted) == len(python_sorted)
    for native_row, python_row in zip(native_sorted, python_sorted):
        assert set(native_row) == {
            "name",
            "path",
            "is_dir",
            "size",
            "modified",
            "created",
            "suffix",
        }
        # 时间按同一 ``strftime("%Y-%m-%d %H:%M")`` 口径比较；目录的 ctime
        # 在两次调用之间可能差 1 分钟边界，故只对文件做严格比较。
        for field in ("name", "path", "is_dir", "size", "suffix"):
            assert native_row[field] == python_row[field], field
        if not python_row["is_dir"]:
            assert native_row["modified"] == python_row["modified"]
            assert native_row["created"] == python_row["created"]


class _SortShim:
    """调用生产 ``_apply_sort`` 的最小替身（该方法只读 ``_sort_mode``）。"""

    def __init__(self, mode: int) -> None:
        self._sort_mode = mode


def _sort_oracle(rows: List[Dict[str, Any]], mode: int) -> List[Dict[str, Any]]:
    """用生产 ``_apply_sort`` 作为排序 oracle（就地排序后返回）。"""
    from freeassetfilter.ui.layout import file_selector_layout as fsl_mod

    copies = [dict(row) for row in rows]
    fsl_mod.FileSelectorLayout._apply_sort(_SortShim(mode), copies)
    return copies


@pytest.mark.parametrize("mode", list(range(8)))
def test_sort_entries_parity(sample_tree: Path, mode: int) -> None:
    """``sort_entries`` 8 模式与生产 ``_apply_sort`` 逐条相等。"""
    _require("sort")
    rows = native_api.scan_directory(str(sample_tree))
    assert rows is not None
    # 稳定排序的 equal-key 输入序必须是确定的，否则两条路径无法对拍；
    # 生产路径（``_sort_entries``）同样先按名称预排序。
    preset = sorted(rows, key=lambda x: (not x["is_dir"], x["name"].lower()))
    native_sorted = native_api.sort_entries([dict(r) for r in preset], mode)
    assert native_sorted is not None
    assert native_sorted == _sort_oracle(preset, mode)


def test_copy_files_parity(sample_tree: Path, tmp_path: Path) -> None:
    """``copy_files`` 与 ``shutil.copy2`` 内容一致、名字一致。"""
    _require("copy")
    native_dest = tmp_path / "native_out"
    native_dest.mkdir()
    python_dest = tmp_path / "python_out"
    python_dest.mkdir()

    sources = [str(sample_tree / "a.txt"), str(sample_tree / "B.TXT")]
    result = native_api.copy_files(sources, str(native_dest))
    assert result is not None
    for source in sources:
        shutil.copy2(source, python_dest)

    native_names = sorted(p.name for p in native_dest.iterdir())
    python_names = sorted(p.name for p in python_dest.iterdir())
    assert native_names == python_names
    for name in python_names:
        assert (native_dest / name).read_bytes() == (python_dest / name).read_bytes()


def test_sum_directory_sizes_parity(sample_tree: Path) -> None:
    """``sum_directory_sizes`` 与 ``os.walk`` 递归求和相等。"""
    _require("sizesum")
    expected = 0
    for dirpath, _dirnames, filenames in os.walk(sample_tree, followlinks=False):
        for name in filenames:
            expected += os.path.getsize(os.path.join(dirpath, name))

    result = native_api.sum_directory_sizes([str(sample_tree)])
    assert result is not None
    # 导出返回 ``{"results": [{"path", "size", "error"}]}``（路径已规范化）。
    entries = result.get("results") or []
    assert len(entries) == 1
    entry = entries[0]
    assert entry.get("error") is None
    assert os.path.normcase(entry["path"]) == os.path.normcase(str(sample_tree))
    assert int(entry["size"]) == expected


_SVG_TEXT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<path d="M0 0h10v10H0z" fill="#FFFFFF"/>'
    '<circle cx="5" cy="5" r="2" fill="#000000"/>'
    "</svg>"
)


def test_replace_svg_colors_parity() -> None:
    """``replace_svg_colors`` 的白色→黑色变换与 Python 等价替换一致。"""
    _require("svg")
    native_out = native_api.replace_svg_colors(_SVG_TEXT, True, False)
    assert native_out is not None
    expected = _SVG_TEXT.replace("#FFFFFF", "#000000")
    assert native_out.replace('"', '"') == expected
    # 结构不变、只换颜色：节点数量一致
    assert native_out.count("<path") == expected.count("<path")
    assert native_out.count("<circle") == expected.count("<circle")


def test_abi_parity_across_bridge_and_api() -> None:
    """``abi_version`` 在桥与门面两侧一致（X4 打包一致性）。"""
    _require("abi")
    inst = native_api.bridge()
    assert inst is not None
    direct = inst.abi_version()
    through_api = native_api.abi_version()
    assert direct is not None and through_api is not None
    assert direct.get("abi") == through_api.get("abi") == 1
    assert direct.get("handles") is True
