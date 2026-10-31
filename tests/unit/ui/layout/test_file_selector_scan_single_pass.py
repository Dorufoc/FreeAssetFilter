# -*- coding: utf-8 -*-
"""文件选择器单遍扫描测试（P1.3）。

P0 实测：默认配置（隐藏/系统文件均过滤）下原实现要**枚举两次目录**——
``_hidden_system_attrs_map`` 一次 + ``_iter_directory_batches`` 一次。
单遍改造把属性位随条目扫描一并采集（``follow_symlinks=False`` 口径），
实测 5k 省 12.5% / 10k 省 14.1%。

本模块锁定四条契约：

1. ``_iter_directory_batches(attrs_out=...)`` 为每个条目写入属性位；
2. 旁路表与 ``_hidden_system_attrs_map`` oracle 逐键一致（符号链接口径相同）；
3. 传入旁路表时 ``_apply_hidden_system_filter`` **不再**调用 ``os.scandir``；
4. 7 键条目契约不变（不得因旁路表新增字段）。

验证命令：
    python -m pytest tests/unit/ui/layout/test_file_selector_scan_single_pass.py -v
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import sopeek.ui.layout.file_selector_layout as fsl_mod  # noqa: E402
from sopeek.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402

pytestmark = pytest.mark.unit

_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4
_FILE_ATTRIBUTE_NORMAL = 0x80
_ENTRY_KEYS = {"name", "path", "is_dir", "size", "modified", "created", "suffix"}


def _set_attrs(path: Path, attrs: int) -> None:
    """设置文件属性位（Windows）。

    Args:
        path: 目标文件。
        attrs: ``FILE_ATTRIBUTE_*`` 位组合。
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.SetFileAttributesW(str(path), attrs)


@pytest.fixture()
def mixed_dir(tmp_path: Path) -> Dict[str, int]:
    """构造普通/隐藏/系统/双重位四类文件。

    Returns:
        ``name -> 期望属性位`` 映射。
    """
    expected: Dict[str, int] = {}
    specs = [
        ("plain.txt", _FILE_ATTRIBUTE_NORMAL),
        ("hidden.txt", _FILE_ATTRIBUTE_HIDDEN),
        ("system.txt", _FILE_ATTRIBUTE_SYSTEM),
        ("both.txt", _FILE_ATTRIBUTE_HIDDEN | _FILE_ATTRIBUTE_SYSTEM),
    ]
    for name, attrs in specs:
        target = tmp_path / name
        target.write_text("x", encoding="utf-8")
        try:
            _set_attrs(target, attrs)
        except OSError:  # pragma: no cover - 非 Windows/权限受限
            pytest.skip("无法设置文件属性位，跳过")
        expected[name] = attrs
    (tmp_path / "subdir").mkdir()
    return expected


def test_iter_batches_fills_attrs(mixed_dir: Dict[str, int], tmp_path: Path) -> None:
    """生成器必须为每个条目写入属性位，且发生在 yield 之前。"""
    attrs: Dict[str, int] = {}
    entries: List[Dict[str, Any]] = []
    for batch, _is_final in FileSelectorLayout._iter_directory_batches(
        str(tmp_path), False, lambda: False, attrs_out=attrs
    ):
        for entry in batch:
            assert entry["name"] in attrs, "yield 时属性位必须已写入"
        entries.extend(batch)

    names = {entry["name"] for entry in entries}
    for expected_name in mixed_dir:
        assert expected_name in names, f"缺少条目 {expected_name}"
    assert set(attrs) == names, "属性旁路表必须与条目名称集合一一对应"
    for name, expected in mixed_dir.items():
        assert attrs[name] & expected == expected, f"{name} 属性位不匹配"


def test_attrs_parity_with_two_pass_oracle(
    mixed_dir: Dict[str, int], tmp_path: Path
) -> None:
    """单遍采集的属性位必须与 ``_hidden_system_attrs_map`` 逐键一致。"""
    attrs: Dict[str, int] = {}
    for _batch, is_final in FileSelectorLayout._iter_directory_batches(
        str(tmp_path), False, lambda: False, attrs_out=attrs
    ):
        if is_final:
            break

    oracle = FileSelectorLayout._hidden_system_attrs_map(str(tmp_path), False, False)
    assert oracle is not None
    for name in oracle:
        assert attrs.get(name) == oracle[name], f"{name} 属性位与 oracle 不一致"


def test_filter_without_extra_scandir(
    mixed_dir: Dict[str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """传入旁路表时过滤不得再调用 ``os.scandir``。"""
    attrs: Dict[str, int] = {}
    entries: List[Dict[str, Any]] = []
    for batch, _is_final in FileSelectorLayout._iter_directory_batches(
        str(tmp_path), False, lambda: False, attrs_out=attrs
    ):
        entries.extend(batch)

    calls: List[str] = []
    original_scandir = os.scandir

    def counting_scandir(path: Any) -> Any:
        calls.append(str(path))
        return original_scandir(path)

    monkeypatch.setattr(fsl_mod.os, "scandir", counting_scandir)

    filtered = FileSelectorLayout._apply_hidden_system_filter(
        entries, str(tmp_path), False, False, attrs_by_name=attrs
    )
    assert calls == [], "旁路表存在时不应重复枚举目录"

    names = {entry["name"] for entry in filtered}
    assert "hidden.txt" not in names, "隐藏文件应被过滤"
    assert "both.txt" not in names, "隐藏+系统双重位应被过滤"
    assert "plain.txt" in names
    assert "system.txt" in names, "仅系统位恒可见"


def test_filter_fallback_still_enumerates(
    mixed_dir: Dict[str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未传旁路表时保留原行为（自行 scandir）。"""
    entries = FileSelectorLayout._collect_directory_entries_python(str(tmp_path))
    assert entries is not None

    calls: List[str] = []
    original_scandir = os.scandir

    def counting_scandir(path: Any) -> Any:
        calls.append(str(path))
        return original_scandir(path)

    monkeypatch.setattr(fsl_mod.os, "scandir", counting_scandir)

    FileSelectorLayout._apply_hidden_system_filter(
        entries, str(tmp_path), False, False
    )
    assert len(calls) == 1, "缺旁路表时回退为一次 scandir"


def test_collect_python_single_pass_and_contract(
    mixed_dir: Dict[str, int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Python 回退收集：整条路径只枚举一次，且条目仍为 7 键。"""
    monkeypatch.setattr(fsl_mod, "_native_scan_directory", lambda path: None)

    calls: List[str] = []
    original_scandir = os.scandir

    def counting_scandir(path: Any) -> Any:
        calls.append(str(path))
        return original_scandir(path)

    monkeypatch.setattr(fsl_mod.os, "scandir", counting_scandir)

    entries = FileSelectorLayout._collect_directory_entries(
        str(tmp_path), show_hidden=False, show_system=False
    )
    assert entries is not None
    assert len(calls) == 1, f"单遍扫描应只枚举一次，实际 {len(calls)} 次"
    for entry in entries:
        assert set(entry.keys()) == _ENTRY_KEYS, "7 键契约不得被旁路表破坏"


def test_attrs_out_none_keeps_legacy_path(
    mixed_dir: Dict[str, int], tmp_path: Path
) -> None:
    """不传 ``attrs_out`` 时行为与旧实现一致（不采集、不报错）。"""
    entries = FileSelectorLayout._collect_directory_entries_python(str(tmp_path))
    assert entries is not None
    assert all(set(entry.keys()) == _ENTRY_KEYS for entry in entries)
