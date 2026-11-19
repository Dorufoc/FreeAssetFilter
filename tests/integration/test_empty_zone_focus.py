# -*- coding: utf-8 -*-
"""空区域焦点归属与回退（真实主窗口端到端）。

背景（用户实测反馈）：空预览区 / 空储存池 / 空信息面板不应该获得键盘
焦点；尝试点击它们时应把焦点回退到文件选择器并高亮回退目标。键盘切区
在三块全空时应先停在文件选择器并高亮，再按一次才继续到路径框。

本文件锁定以下契约：

* 三个空区域 ``_focus_zone`` 均返回 False；
* 点击空区域的空白内容面 → 焦点回到文件列表、region 为 selector、闪选择器描边；
* 焦点在储存池（有卡片）时点击空信息面板 → 同样回退到文件选择器；
* 三块全空时 Ctrl+方向键：第一次停在选择器并高亮，第二次到路径框；
* 储存池最后一张卡片移除且焦点在池内 → 回退选择器并高亮。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/integration/test_empty_zone_focus.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sopeek.core.shortcuts import reset_dispatcher_for_tests

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def window(qapp: Any) -> Iterator[Any]:
    """空池 / 空信息面板的主窗口（模块内复用，避免反复建窗）。

    每个用例开始前由 :func:`_reset_empty_state` 复位到空状态；测试会话的
    数据目录共享，启动期还会恢复前序用例留下的暂存池备份，因此在建窗后
    必须先等恢复跑完再清空。
    """
    from sopeek.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    # 等启动期「暂存池备份恢复」跑完（STARTUP_OVERLAY_FADE_MS + 400ms）。
    QTest.qWait(900)
    qapp.processEvents()
    _reset_empty_state(win)
    try:
        yield win
    finally:
        win.close()
        win.deleteLater()
        qapp.processEvents()
        reset_dispatcher_for_tests()


def _reset_empty_state(window: Any) -> None:
    """把主窗口复位为「三块全空 + 焦点在文件列表」的起点。"""
    pool = window._file_pool
    if pool.has_items():
        pool.clear_all_without_confirmation()
        QTest.qWait(300)
    window._previewer.clear_preview()
    window._info_panel.clear()
    window._file_selector.focus_file_list()
    window._shortcuts.replace_region("selector")
    window._last_flash_zone = ""
    window._empty_cycle_selector_stay = False
    QApplication.processEvents()


def _focus_path_input(window: Any) -> None:
    """把焦点放到路径框（验证点击空区会主动回退到文件列表）。"""
    window._file_selector._path_input.setFocus()
    QApplication.processEvents()


def _click_center(widget: Any) -> None:
    """向目标控件中心投递一次真实左键点击。"""
    QTest.mouseClick(
        widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        widget.rect().center(),
    )
    QApplication.processEvents()


def _add_pool_file(window: Any, tmp_path: Any) -> str:
    """向储存池加入一个真实文件并等卡片就绪，返回规范化路径。"""
    path = os.path.join(str(tmp_path), "pool_sample.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")
    window._file_pool.add_file(
        {"path": path, "name": "pool_sample.txt", "size": 1}
    )
    QTest.qWait(400)
    QApplication.processEvents()
    return os.path.normpath(path)


def _assert_selector_fallback(window: Any) -> None:
    """焦点、区域与描边都落在文件选择器上。"""
    selector = window._file_selector
    assert QApplication.focusWidget() is selector._file_list
    assert window._shortcuts.region() == "selector"
    assert window._last_flash_zone == "selector"


def test_empty_zones_are_not_focusable(window: Any) -> None:
    """空预览区 / 空池 / 空信息面板均不能成为焦点区。"""
    _reset_empty_state(window)
    assert window._previewer.has_active_preview() is False
    assert window._file_pool.has_items() is False
    assert window._info_panel.has_file() is False

    assert window._focus_zone("preview") is False
    assert window._focus_zone("pool") is False
    assert window._focus_zone("info") is False


def test_click_empty_info_falls_back_to_selector(window: Any) -> None:
    """点击空信息面板空白处 → 回退文件选择器并高亮。"""
    _reset_empty_state(window)
    _focus_path_input(window)
    window._last_flash_zone = ""

    _click_center(window._info_panel._canvas)

    _assert_selector_fallback(window)


def test_click_empty_pool_falls_back_to_selector(window: Any) -> None:
    """点击空储存池空白处 → 回退文件选择器并高亮。"""
    _reset_empty_state(window)
    _focus_path_input(window)
    window._last_flash_zone = ""

    _click_center(window._file_pool._scroll_area.viewport())

    _assert_selector_fallback(window)


def test_click_empty_preview_falls_back_to_selector(window: Any) -> None:
    """点击空预览区占位处 → 回退文件选择器并高亮。"""
    _reset_empty_state(window)
    _focus_path_input(window)
    window._last_flash_zone = ""

    _click_center(window._previewer._placeholder_label)

    _assert_selector_fallback(window)


def test_click_empty_info_while_pool_focused_falls_back(
    window: Any, tmp_path: Any
) -> None:
    """焦点在储存池时点击空信息面板：仍按要求回退文件选择器并高亮。"""
    _reset_empty_state(window)
    path = _add_pool_file(window, tmp_path)
    pool = window._file_pool
    assert pool.focus_first_card() is True
    QApplication.processEvents()
    assert QApplication.focusWidget() is pool._card_widgets[path]
    window._last_flash_zone = ""

    _click_center(window._info_panel._canvas)

    _assert_selector_fallback(window)


def test_all_empty_keyboard_stays_on_selector_then_path(window: Any) -> None:
    """三块全空：第一次停在选择器并高亮，第二次到路径框。"""
    _reset_empty_state(window)
    selector = window._file_selector
    assert not window._previewer.has_active_preview()
    assert not window._file_pool.has_items()
    assert not window._info_panel.has_file()
    selector.focus_file_list()
    QApplication.processEvents()
    window._last_flash_zone = ""
    window._empty_cycle_selector_stay = False

    assert window._focus_next_zone(+1) is True
    assert QApplication.focusWidget() is selector._file_list
    assert window._shortcuts.region() == "selector"
    assert window._last_flash_zone == "selector"

    assert window._focus_next_zone(+1) is True
    assert QApplication.focusWidget() is selector._path_input
    assert window._shortcuts.region() == "path"


def test_remove_last_pool_card_while_focused_falls_back(
    window: Any, tmp_path: Any
) -> None:
    """最后一张池卡片被移除且焦点在池内 → 回退选择器并高亮。"""
    _reset_empty_state(window)
    path = _add_pool_file(window, tmp_path)
    pool = window._file_pool
    assert pool.focus_first_card() is True
    QApplication.processEvents()
    window._last_flash_zone = ""

    pool.remove_file(path)
    QTest.qWait(600)
    QApplication.processEvents()

    assert pool.has_items() is False
    _assert_selector_fallback(window)
