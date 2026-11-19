# -*- coding: utf-8 -*-
"""文件选择器「无光标时首次方向键落位」回归。

背景（用户实测反馈）：取消预览后焦点回到文件选择器，此时没有任何卡片带
光标；按任意方向键都应先把光标**选定到第一个卡片**，而不是从被取消的那张
继续，也不是落到第二张。

本文件锁定以下契约：

* ``clear_previewing_state`` 同时清空预览态与键盘光标；
* ``clear_nav_cursor`` 彻底清空光标（含路径，与 ``reset_nav_state`` 区分）；
* 无光标时首次按 ↑/↓/←/→ 一律落位到第一个非文件夹条目，且**不**额外步进；
* 落位后第二次按方向键才正常移动一格；
* 模型全为文件夹时落位到第 0 行（不出现「无处可落」）；
* 空模型时按键不消费事件（不崩）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_file_selector_nav_landing.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator, List, Tuple

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from sopeek.ui.layout.file_selector_layout import FileSelectorLayout

pytestmark = [pytest.mark.unit, pytest.mark.widgets]

_ARROWS: Tuple[Tuple[int, str], ...] = (
    (int(Qt.Key.Key_Up), "Up"),
    (int(Qt.Key.Key_Down), "Down"),
    (int(Qt.Key.Key_Left), "Left"),
    (int(Qt.Key.Key_Right), "Right"),
)


def _entry(name: str, *, is_dir: bool = False) -> dict:
    """构造与目录扫描产物同构的 7 键条目。"""
    return {
        "name": name,
        "path": os.path.join("C:\\nav_landing", name),
        "is_dir": is_dir,
        "size": 0 if is_dir else 1024,
        "modified": "2026-01-01 00:00",
        "created": "2026-01-01 00:00",
        "suffix": "" if is_dir else os.path.splitext(name)[1].lstrip("."),
    }


@pytest.fixture
def selector(qapp: Any) -> Iterator[FileSelectorLayout]:
    """已稳定下来的文件选择器（等异步 All 视图落地后再喂自定义模型）。"""
    widget = FileSelectorLayout()
    widget.resize(640, 480)
    widget.show()
    QTest.qWait(50)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _install_entries(
    selector: FileSelectorLayout, entries: List[dict]
) -> None:
    """把自定义条目灌进模型，并置为「无光标、无预览」的初始态。"""
    selector._current_path = "C:\\nav_landing"
    selector._file_model.set_files(entries)
    selector._update_grid_size()
    selector.clear_nav_cursor()
    selector.set_previewing_file("")
    QTest.qWait(20)


def _first_file_path(entries: List[dict]) -> str:
    """测试期望：第一个非文件夹条目（全文件夹时取首行）。"""
    for entry in entries:
        if not entry["is_dir"]:
            return os.path.normpath(entry["path"])
    return os.path.normpath(entries[0]["path"])


def test_clear_previewing_state_also_clears_nav_cursor(
    selector: FileSelectorLayout,
) -> None:
    """取消预览必须同时清掉键盘光标（否则方向键从被取消那张继续）。"""
    entries = [_entry("a.png"), _entry("b.png"), _entry("c.png")]
    _install_entries(selector, entries)
    selector.set_previewing_file(entries[1]["path"])
    selector._sync_nav_cursor(entries[1]["path"])
    assert selector._nav_cursor_row == 1

    selector.clear_previewing_state()

    assert selector._previewing_file_path == ""
    assert selector._nav_cursor_row == -1
    assert selector._nav_cursor_path == ""
    assert selector._nav_active is False


def test_clear_nav_cursor_is_stricter_than_reset_nav_state(
    selector: FileSelectorLayout,
) -> None:
    """``reset_nav_state`` 保留路径（失活后继续），``clear_nav_cursor`` 不保留。"""
    entries = [_entry("a.png"), _entry("b.png")]
    _install_entries(selector, entries)
    selector._sync_nav_cursor(entries[1]["path"])

    selector.reset_nav_state()
    assert selector._nav_cursor_row == -1
    assert selector._nav_cursor_path == entries[1]["path"]

    selector._sync_nav_cursor(entries[1]["path"])
    selector.clear_nav_cursor()
    assert selector._nav_cursor_row == -1
    assert selector._nav_cursor_path == ""
    assert selector._nav_last_key == 0
    assert selector._nav_model_key is None


@pytest.mark.parametrize("key,label", _ARROWS)
def test_first_arrow_lands_on_first_entry(
    selector: FileSelectorLayout, key: int, label: str
) -> None:
    """无光标时任意方向键都只落位到第一个非文件夹条目（不额外步进）。"""
    entries = [
        _entry("dir_a", is_dir=True),
        _entry("a.png"),
        _entry("b.png"),
        _entry("c.png"),
    ]
    _install_entries(selector, entries)

    consumed = selector.handle_nav_key_press(key)

    assert consumed is True, label
    assert selector._nav_cursor_row == 1, label
    assert selector._nav_cursor_path == os.path.normpath(entries[1]["path"])
    # 落位只移高亮，不发 file_selected；预览内容由 release 统一加载。
    assert selector._previewing_file_path == os.path.normpath(entries[1]["path"])


def test_second_arrow_moves_one_step_after_landing(
    selector: FileSelectorLayout,
) -> None:
    """落位后同一手势内继续按键才正常步进（长按连发语义不变）。"""
    entries = [_entry("a.png"), _entry("b.png"), _entry("c.png")]
    _install_entries(selector, entries)

    selector.handle_nav_key_press(int(Qt.Key.Key_Right))
    assert selector._nav_cursor_row == 0

    selector.handle_nav_key_press(int(Qt.Key.Key_Right))
    assert selector._nav_cursor_row == 1
    assert selector._nav_cursor_path == os.path.normpath(entries[1]["path"])


def test_second_arrow_moves_one_grid_row_when_multiple_rows(
    selector: FileSelectorLayout,
) -> None:
    """网格多行时，落位后第二次按 ↓ 前进整整一行（保持列对齐）。"""
    entries = [_entry(f"{index}.png") for index in range(12)]
    _install_entries(selector, entries)
    cols = selector._nav_cols()
    if cols >= len(entries):
        pytest.skip(f"当前视口单行布局（cols={cols}），垂直步进无相邻行")

    selector.handle_nav_key_press(int(Qt.Key.Key_Down))
    assert selector._nav_cursor_row == 0

    selector.handle_nav_key_press(int(Qt.Key.Key_Down))
    assert selector._nav_cursor_row == cols


def test_first_arrow_falls_back_to_first_row_when_all_dirs(
    selector: FileSelectorLayout,
) -> None:
    """全是文件夹时落位到第 0 行（文件夹也可预览/回车进入）。"""
    entries = [_entry("dir_a", is_dir=True), _entry("dir_b", is_dir=True)]
    _install_entries(selector, entries)

    assert selector.handle_nav_key_press(int(Qt.Key.Key_Down)) is True
    assert selector._nav_cursor_row == 0
    assert selector._nav_cursor_path == os.path.normpath(entries[0]["path"])


def test_first_arrow_ignores_empty_model(
    selector: FileSelectorLayout,
) -> None:
    """空模型：按键不消费（事件放行给上层），光标保持为空。"""
    _install_entries(selector, [])

    assert selector.handle_nav_key_press(int(Qt.Key.Key_Down)) is False
    assert selector._nav_cursor_row == -1
    assert selector._nav_cursor_path == ""


def test_first_entry_row_skips_leading_dirs(
    selector: FileSelectorLayout,
) -> None:
    """``_first_entry_row`` 跳过前导文件夹；全文件夹回退 0。"""
    _install_entries(
        selector,
        [_entry("d1", is_dir=True), _entry("d2", is_dir=True), _entry("x.png")],
    )
    assert selector._first_entry_row() == 2

    _install_entries(selector, [_entry("d1", is_dir=True)])
    assert selector._first_entry_row() == 0

    _install_entries(selector, [])
    assert selector._first_entry_row() == -1


def test_cancel_preview_then_arrow_lands_on_first(
    selector: FileSelectorLayout,
) -> None:
    """端到端：预览第 3 张 → 取消 → 按 ↓ → 落到第一张。"""
    entries = [_entry("a.png"), _entry("b.png"), _entry("c.png")]
    _install_entries(selector, entries)
    selector.set_previewing_file(entries[2]["path"])
    selector._sync_nav_cursor(entries[2]["path"])

    selector.clear_previewing_state()
    assert selector.handle_nav_key_press(int(Qt.Key.Key_Down)) is True

    assert selector._nav_cursor_row == 0
    assert selector._previewing_file_path == os.path.normpath(entries[0]["path"])


def test_second_arrow_moves_when_single_grid_row(
    selector: FileSelectorLayout,
) -> None:
    """单行网格（上下无相邻行）：第二次按 ↓ 退化为顺序步进而非原地不动。"""
    entries = [_entry(f"{index}.png") for index in range(4)]
    _install_entries(selector, entries)
    if selector._nav_cols() < len(entries):
        pytest.skip(f"当前视口已多行（cols={selector._nav_cols()}）")

    assert selector.handle_nav_key_press(int(Qt.Key.Key_Down)) is True
    assert selector._nav_cursor_row == 0

    assert selector.handle_nav_key_press(int(Qt.Key.Key_Down)) is True
    assert selector._nav_cursor_row == 1


def test_stale_preview_path_does_not_revive_as_anchor(
    selector: FileSelectorLayout,
) -> None:
    """旧目录残留的预览路径不得成为锚点（首次方向键仍落第一个文件）。

    复现场景：预览 a1 → 进入子目录 → 退回上级；a1 在新模型里仍存在，
    ``_resolve_anchor_row`` 若读 ``_previewing_file_path`` 就会从 a1 继续。
    """
    entries = [
        _entry("dir_a", is_dir=True),
        _entry("a0.png"),
        _entry("a1.png"),
        _entry("a2.png"),
    ]
    _install_entries(selector, entries)

    # 模拟「进入目录」后的落地状态：光标清空，但旧预览路径残留
    selector.clear_nav_cursor()
    selector._previewing_file_path = os.path.normpath(entries[2]["path"])
    assert selector._resolve_anchor_row() == 2

    # 落地收尾必须把预览态一起清掉（_finalize_stream 的 pending 分支）
    selector.clear_previewing_state()
    assert selector._resolve_anchor_row() == -1

    assert selector.handle_nav_key_press(int(Qt.Key.Key_Down)) is True
    assert selector._nav_cursor_row == 1
    assert selector._nav_cursor_path == os.path.normpath(entries[1]["path"])
