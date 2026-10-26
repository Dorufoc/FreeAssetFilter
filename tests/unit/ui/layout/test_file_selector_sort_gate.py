# -*- coding: utf-8 -*-
"""文件选择器排序门控测试（P1.2）。

P0 实测结论：native ``faf_sort_entries`` 的 JSON 往返成本高于 Python
``sort`` 本身（2000 条 ≥3.1ms vs 0.32ms），且 30k 条会先撞 8MB 上限再
整体回退（白烧 115.2ms）。因此 ``NATIVE_SORT_ENABLED`` 默认关闭。

本模块锁定三条契约：

1. 默认配置下 ``_sort_entries`` **不调用** native；
2. 8 种排序模式的结果与「预排序 + ``_apply_sort``」oracle 逐项一致
   （含 mode 2–7 的 equal-key 平局）；
3. 显式打开 ``FAF_NATIVE_SORT`` 且超过门槛时，native 路径才会被调用。

验证命令：
    python -m pytest tests/unit/ui/layout/test_file_selector_sort_gate.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

import freeassetfilter.ui.layout.file_selector_layout as fsl_mod  # noqa: E402
from freeassetfilter.ui.layout.file_selector_layout import FileSelectorLayout  # noqa: E402

pytestmark = pytest.mark.unit


def _make_entries(count: int, same_mtime: bool = False) -> List[Dict[str, Any]]:
    """构造混合条目（含目录、大小写歧义、可选相同 mtime）。

    Args:
        count: 条目数。
        same_mtime: True 时所有文件 mtime 相同（制造 mode 2/3 平局）。

    Returns:
        7 键条目列表。
    """
    entries: List[Dict[str, Any]] = []
    for i in range(count):
        is_dir = i % 11 == 0
        name = f"{'Dir' if is_dir else 'file'}_{i:05d}.TXT"
        entries.append(
            {
                "name": name,
                "path": f"C:/x/{name}",
                "is_dir": is_dir,
                "size": i,
                "modified": (
                    "2026-01-01 00:00"
                    if same_mtime
                    else f"2026-01-{i % 28 + 1:02d} 00:00"
                ),
                "created": (
                    "2026-01-01 00:00"
                    if same_mtime
                    else f"2026-02-{i % 28 + 1:02d} 00:00"
                ),
                "suffix": "" if is_dir else "txt",
            }
        )
    # 制造大小写歧义（mode 0/1 的 equal-key）
    if count > 2:
        entries[1]["name"] = entries[0]["name"].lower()
        entries[1]["path"] = "C:/x/" + entries[1]["name"]
    return entries


def _oracle(entries: List[Dict[str, Any]], mode: int) -> List[str]:
    """「预排序 + _apply_sort」参照实现（mode 2–7 必带预排序）。"""
    ordered = list(entries)
    if mode >= 2:
        ordered.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    if mode == 0:
        ordered.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    elif mode == 1:
        ordered.sort(key=lambda x: (not x["is_dir"], x["name"].lower()), reverse=True)
    elif mode == 2:
        ordered.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")), reverse=True)
    elif mode == 3:
        ordered.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")))
    elif mode == 4:
        ordered.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)), reverse=True)
    elif mode == 5:
        ordered.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)))
    elif mode == 6:
        ordered.sort(key=lambda x: (not x["is_dir"], x.get("created", "")), reverse=True)
    elif mode == 7:
        ordered.sort(key=lambda x: (not x["is_dir"], x.get("created", "")))
    return [entry["path"] for entry in ordered]


@pytest.fixture()
def layout(qapp: Any) -> Any:
    """构造 FileSelectorLayout（offscreen，不 show → 不触发首屏导航）。"""
    widget = FileSelectorLayout()
    yield widget
    widget.deleteLater()


def test_small_dir_skips_native(
    layout: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认配置（2000 条）下不得调用 native 排序。"""
    called: List[int] = []

    def fake_native(entries: List[Dict[str, Any]], mode: int) -> None:
        called.append(mode)
        return None

    monkeypatch.setattr(fsl_mod, "_native_sort_entries", fake_native)
    monkeypatch.setattr(fsl_mod, "NATIVE_SORT_ENABLED", False)

    entries = _make_entries(2000)
    for mode in range(8):
        layout._sort_mode = mode
        result = layout._sort_entries(entries)
        assert len(result) == 2000
    assert called == [], "默认配置下 native 排序必须被门控跳过"


def test_sort_order_matches_oracle_for_all_modes(layout: Any) -> None:
    """8 种模式（含平局）与 oracle 逐项一致。"""
    monkeypatch_enabled = getattr(fsl_mod, "NATIVE_SORT_ENABLED", False)
    assert monkeypatch_enabled is False, "默认应为关闭"

    for same_mtime in (False, True):
        entries = _make_entries(300, same_mtime=same_mtime)
        for mode in range(8):
            layout._sort_mode = mode
            actual = [e["path"] for e in layout._sort_entries(entries)]
            expected = _oracle(entries, mode)
            assert actual == expected, (
                f"mode={mode} same_mtime={same_mtime} 排序结果与 oracle 不一致"
            )


def test_mode_2_presort_is_required_for_ties(layout: Any) -> None:
    """mode 2 全平局时，顺序必须等于「按名预排序」后的输入序。

    这条锁定「预排序不可删」：Rust 与 Python 的稳定排序都保持输入序，
    而输入序来自 read_dir（非确定），预排序是平局确定性的唯一来源。
    """
    entries = _make_entries(120, same_mtime=True)
    layout._sort_mode = 2
    actual = [e["path"] for e in layout._sort_entries(entries)]

    expected = list(entries)
    expected.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    expected.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")), reverse=True)
    assert actual == [e["path"] for e in expected]


def test_native_path_used_only_when_explicitly_enabled(
    layout: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式开启 + 超过门槛时才走 native；返回 None 时回退 Python。"""
    called: List[int] = []

    def fake_native(entries: List[Dict[str, Any]], mode: int) -> List[Dict[str, Any]]:
        called.append(mode)
        return list(reversed(entries))

    monkeypatch.setattr(fsl_mod, "NATIVE_SORT_ENABLED", True)
    monkeypatch.setattr(fsl_mod, "NATIVE_SORT_MIN_ENTRIES", 10)
    monkeypatch.setattr(fsl_mod, "_native_sort_entries", fake_native)

    layout._sort_mode = 1
    entries = _make_entries(50)
    result = layout._sort_entries(entries)
    assert called == [1], "开启且超门槛时应调用 native"
    assert [e["path"] for e in result] == list(reversed([e["path"] for e in entries]))

    # 低于门槛 → 不调用
    called.clear()
    layout._sort_entries(_make_entries(5))
    assert called == []
