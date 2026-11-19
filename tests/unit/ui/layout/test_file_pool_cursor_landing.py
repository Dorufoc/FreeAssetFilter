# -*- coding: utf-8 -*-
"""文件储存池「无光标时首次方向键落位」回归。

背景（用户实测反馈）：进入储存池后没有任何卡片带键盘光标，此时第一次按
任意方向键应先把光标**落位**到第一张卡片，而不是直接跳到第二张（网格按
整行跳时尤其明显），也不应毫无反应（列表模式上下键曾经完全不动）。

本文件锁定以下契约：

* 无光标时首次按任意方向键 → 光标落在视觉顺序第一张卡片，且不额外步进；
* 落位后第二次按键才正常移动一格（网格按整行、列表按 ±1）；
* 列表模式（单列）四个方向都能移动，不再出现「上下键不动」；
* 鼠标点击卡片后方向键从被点的那张继续（点击同步键盘光标）；
* 光标所在卡片被移除后光标清空，下一次方向键重新落位到第一张；
* 池为空时按键不消费（返回 False，不崩）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_file_pool_cursor_landing.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator, List

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from sopeek.ui.layout.file_pool_layout import FilePoolLayout

pytestmark = [pytest.mark.unit, pytest.mark.widgets]

_ARROWS = (
    (-1, "row", "Up"),
    (+1, "row", "Down"),
    (-1, "col", "Left"),
    (+1, "col", "Right"),
)


@pytest.fixture
def pool(qapp: Any, tmp_path: Any) -> Iterator[FilePoolLayout]:
    """空储存池（卡片由用例按需加入）。"""
    widget = FilePoolLayout()
    widget.resize(700, 500)
    widget.show()
    QTest.qWait(50)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _add_files(pool: FilePoolLayout, tmp_path: Any, count: int) -> List[str]:
    """向池中加入 ``count`` 个真实文件（顺序即视觉顺序），返回路径列表。"""
    paths: List[str] = []
    for index in range(count):
        path = os.path.join(str(tmp_path), f"p{index:02d}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("x")
        paths.append(os.path.normpath(path))
        pool.add_file({"path": path, "name": os.path.basename(path), "size": 1})
    QTest.qWait(120)
    return paths


def _clear_cursor(pool: FilePoolLayout) -> None:
    """把池置为「无光标」初始态。"""
    pool._cursor_path = ""


@pytest.mark.parametrize("step,axis,label", _ARROWS)
def test_first_arrow_lands_on_first_card(
    pool: FilePoolLayout, tmp_path: Any, step: int, axis: str, label: str
) -> None:
    """无光标时任意方向键都只落位到第一张卡片（不额外步进）。"""
    paths = _add_files(pool, tmp_path, 4)
    _clear_cursor(pool)

    assert pool.advance_cursor(step, axis=axis) is True, label
    assert pool._cursor_path == paths[0], label


def test_second_arrow_moves_after_landing(pool: FilePoolLayout, tmp_path: Any) -> None:
    """列表模式：落位后第二次按键按顺序移动一格。"""
    paths = _add_files(pool, tmp_path, 4)
    pool.set_view_mode("list")
    QTest.qWait(120)
    _clear_cursor(pool)

    pool.advance_cursor(+1, axis="row")
    assert pool._cursor_path == paths[0]

    pool.advance_cursor(+1, axis="row")
    assert pool._cursor_path == paths[1]


@pytest.mark.parametrize("axis", ["row", "col"])
def test_list_mode_moves_in_both_axes(
    pool: FilePoolLayout, tmp_path: Any, axis: str
) -> None:
    """列表模式（单列）上下与左右都能移动（曾经上下键原地不动）。"""
    paths = _add_files(pool, tmp_path, 4)
    pool.set_view_mode("list")
    QTest.qWait(120)
    _clear_cursor(pool)

    pool.advance_cursor(+1, axis=axis)
    assert pool._cursor_path == paths[0]

    assert pool.advance_cursor(+1, axis=axis) is True
    assert pool._cursor_path == paths[1]


def test_grid_row_step_keeps_column(pool: FilePoolLayout, tmp_path: Any) -> None:
    """网格模式：落位后第二次按 ↓ 前进整整一行（保持列对齐）。"""
    paths = _add_files(pool, tmp_path, 12)
    pool.set_view_mode("grid")
    QTest.qWait(200)
    cols = pool._grid_columns()
    if cols < 2:
        pytest.skip(f"当前视口单列布局（cols={cols}），无相邻列")

    _clear_cursor(pool)
    pool.advance_cursor(+1, axis="row")
    assert pool._cursor_path == paths[0]

    pool.advance_cursor(+1, axis="row")
    assert pool._cursor_path == paths[min(cols, len(paths) - 1)]


def test_clicked_card_becomes_cursor(pool: FilePoolLayout, tmp_path: Any) -> None:
    """鼠标点击卡片后，方向键从被点的那张继续（点击同步键盘光标）。"""
    paths = _add_files(pool, tmp_path, 5)
    _clear_cursor(pool)

    card = pool._card_widgets[paths[3]]
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
    QTest.qWait(50)

    assert pool._cursor_path == paths[3]

    pool.advance_cursor(+1, axis="col")
    assert pool._cursor_path == paths[4]


def test_removed_cursor_card_resets_cursor(
    pool: FilePoolLayout, tmp_path: Any
) -> None:
    """光标卡片被移除后光标清空，下一次方向键重新落位到第一张。"""
    paths = _add_files(pool, tmp_path, 4)
    _clear_cursor(pool)
    pool.advance_cursor(+1, axis="row")
    assert pool._cursor_path == paths[0]

    pool.remove_file(paths[0])
    QTest.qWait(400)

    assert pool._cursor_path == ""

    pool.advance_cursor(+1, axis="row")
    assert pool._cursor_path == paths[1]


def test_empty_pool_ignores_arrow(pool: FilePoolLayout) -> None:
    """空池：按键不消费（返回 False），光标保持为空。"""
    _clear_cursor(pool)

    assert pool.advance_cursor(+1, axis="row") is False
    assert pool._cursor_path == ""


# ── 空池不是焦点区 ──────────────────────────────────────────────────────


def _visible_focusable_children(widget: Any) -> list:
    """返回控件子树内「可见且可聚焦」的子控件（空区域必须为空列表）。"""
    from PySide6.QtWidgets import QWidget

    return [
        child
        for child in widget.findChildren(QWidget)
        if child.isVisible() and child.focusPolicy() != Qt.FocusPolicy.NoFocus
    ]


def test_empty_pool_has_no_focusable_children(pool: FilePoolLayout) -> None:
    """空池：滚动区与提示都不可聚焦，点击空白不会让空池获得焦点。"""
    assert pool.has_items() is False
    assert pool._scroll_area.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert _visible_focusable_children(pool) == []
    assert pool.focus_first_card() is False


def test_pool_becomes_focusable_after_adding_item(
    pool: FilePoolLayout, tmp_path: Any
) -> None:
    """有卡片后恢复滚动区聚焦能力，``focus_first_card`` 可聚焦首卡。"""
    from PySide6.QtWidgets import QApplication

    paths = _add_files(pool, tmp_path, 1)

    assert pool.has_items() is True
    assert pool._scroll_area.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert pool.focus_first_card() is True
    QApplication.processEvents()
    assert QApplication.focusWidget() is pool._card_widgets[paths[0]]


def test_empty_pool_after_removing_last_card_emits_focus_exhausted(
    pool: FilePoolLayout, tmp_path: Any
) -> None:
    """最后一张卡片被移除且焦点在池内：发出回退信号，池回到不可聚焦。"""
    paths = _add_files(pool, tmp_path, 1)
    assert pool.focus_first_card() is True

    emitted: list = []
    pool.focus_exhausted.connect(lambda: emitted.append(True))

    pool.remove_file(paths[0])
    QTest.qWait(500)

    assert pool.has_items() is False
    assert pool._scroll_area.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert emitted == [True]
