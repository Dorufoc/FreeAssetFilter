# -*- coding: utf-8 -*-
"""取消预览后的焦点与光标回落（真实主窗口端到端）。

背景（用户实测反馈）：在预览器里点「清除预览」后，焦点被 Qt 甩给选择器
路径框，方向键全被输入框吃掉；即使焦点还在文件列表，光标仍指向被取消的
那张卡，首次按方向键会跳到它的下一张。

本文件锁定以下契约：

* 点预览器顶栏「清除预览」→ 焦点回到文件列表（region == ``selector``）；
* 同时清空预览态与键盘光标（无任何卡片带光标）；
* 此后按任意方向键 → 光标落到第一个非文件夹条目；
* 焦点已在储存池时取消预览不抢焦点；
* 焦点在信息面板时取消预览 → 信息面板已空，焦点回退文件列表并高亮选择器。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/integration/test_preview_cancel_focus.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from sopeek.core.shortcuts import reset_dispatcher_for_tests

pytestmark = pytest.mark.integration

#: 仓库自带素材目录（3 张 png，无子目录，排序稳定）。
_ASSETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets",
)


@pytest.fixture
def window(qapp: Any) -> Iterator[Any]:
    """构造主窗口并导航到 ``assets/``（等异步加载稳定）。"""
    from sopeek.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    QTest.qWait(600)
    qapp.processEvents()
    win._file_selector._navigate_to(_ASSETS)
    QTest.qWait(900)
    qapp.processEvents()
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()
        reset_dispatcher_for_tests()


def _preview_card(window: Any, row: int) -> None:
    """点击第 ``row`` 张卡片加载预览（走真实鼠标事件）。"""
    selector = window._file_selector
    rect = selector._file_list.visualRect(selector._file_model.index(row, 0))
    QTest.mouseClick(
        selector._file_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )
    QTest.qWait(400)
    QApplication.processEvents()


def _click_previewer_close(window: Any) -> None:
    """把焦点送进预览器后点顶栏「清除预览」按钮（真实鼠标事件）。"""
    current = window._previewer._current_preview_widget
    assert current is not None
    view = getattr(current, "_image_view", None)
    if view is not None:
        view.viewport().setFocus()
    QApplication.processEvents()
    QTest.mouseClick(window._previewer._top_buttons[-1], Qt.MouseButton.LeftButton)
    QTest.qWait(300)
    QApplication.processEvents()


def test_cancel_returns_focus_to_file_list(window: Any) -> None:
    """点预览器「清除预览」后焦点必须回到文件列表（而非路径框）。"""
    _preview_card(window, 2)
    assert window._previewer.current_file_info() is not None

    _click_previewer_close(window)

    focused = QApplication.focusWidget()
    selector = window._file_selector
    assert focused is selector._file_list
    assert window._shortcuts.region() == "selector"
    assert window._previewer.current_file_info() is None


def test_cancel_clears_cursor_and_preview_state(window: Any) -> None:
    """取消后选择器无光标、无预览高亮。"""
    selector = window._file_selector
    _preview_card(window, 2)
    assert selector._nav_cursor_row == 2
    assert selector._previewing_file_path

    window._on_preview_cancelled()
    QTest.qWait(200)
    QApplication.processEvents()

    assert selector._nav_cursor_row == -1
    assert selector._nav_cursor_path == ""
    assert selector._previewing_file_path == ""


@pytest.mark.parametrize(
    "key", [Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right]
)
def test_arrow_after_cancel_lands_on_first_entry(window: Any, key: Any) -> None:
    """取消后按任意方向键：光标落到第一个非文件夹条目。"""
    selector = window._file_selector
    _preview_card(window, 2)
    _click_previewer_close(window)

    expected_row = selector._first_entry_row()
    assert expected_row >= 0
    expected_path = selector._row_path(expected_row)

    QTest.keyClick(selector._file_list, key)
    QTest.qWait(200)
    QApplication.processEvents()

    assert selector._nav_cursor_row == expected_row
    assert selector._nav_cursor_path == expected_path
    assert selector._previewing_file_path == expected_path


def test_cancel_from_pool_keeps_pool_focus(window: Any) -> None:
    """焦点在储存池时取消预览：不把焦点抢回文件列表。"""
    selector = window._file_selector
    _preview_card(window, 2)
    info = selector._build_file_info_for_path(selector._nav_cursor_path)
    assert info is not None
    window._on_add_files_to_pool_requested([info])
    QTest.qWait(300)
    QApplication.processEvents()

    pool = window._file_pool
    assert pool.focus_first_card() is True
    QApplication.processEvents()
    assert window._shortcuts.region() == "pool"

    window._on_preview_cancelled()
    QTest.qWait(200)
    QApplication.processEvents()

    assert window._shortcuts.region() == "pool"
    assert not selector._file_list.hasFocus()


def test_cancel_from_info_panel_falls_back_to_selector(window: Any) -> None:
    """焦点在信息面板时取消预览：空信息面板不是焦点区，回退并高亮选择器。"""
    _preview_card(window, 2)
    info_panel = window._info_panel
    assert info_panel is not None
    assert info_panel.has_file()
    assert info_panel.focus_canvas() is True
    QApplication.processEvents()
    assert window._shortcuts.region() == "info"

    window._on_preview_cancelled()
    QTest.qWait(200)
    QApplication.processEvents()

    assert info_panel.has_file() is False
    assert window._shortcuts.region() == "selector"
    assert window._file_selector._file_list.hasFocus()
    assert window._last_flash_zone == "selector"
