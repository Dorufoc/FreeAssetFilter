# -*- coding: utf-8 -*-
"""压缩包预览器：包内列表 ↔ 包内搜索框的方向键焦点切换。

背景（用户实测反馈）：焦点在压缩包预览器的包内列表时，方向键只能在列表
内部移动，首行再按 ``↑`` 无反应，无法用键盘回到顶栏的「包内搜索框」。

本文件锁定以下契约：

* 包内列表首行按 ``↑`` → 搜索框可见并拿到焦点（原隐藏时自动展开）；
* 非首行按 ``↑`` → 保持 Qt 原生行为（光标上移一行，焦点留在列表）；
* ``Shift+↑`` 等多选组合不触发焦点切换；
* 警示行（不可选）不算首行，首个可选条目即视为「首行」；
* 搜索框按 ``↓`` → 焦点回到列表并选中首个可选条目；
* 搜索框按 ``Esc`` → 退出搜索且焦点回到列表（不停在隐藏控件上）；
* 空列表按 ``↑`` 不打开搜索框、不抛异常。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_archive_focus_nav.py -v
"""

from __future__ import annotations

import os
from typing import Any, Iterator, List

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from sopeek.ui.layout.preview.archive_previewer_layout import (
    ArchivePreviewerLayout,
    _ArchiveListView,
    _ArchiveListModel,
)

pytestmark = [pytest.mark.unit, pytest.mark.widgets]

_ARCHIVE_PATH = os.path.join("C:\\focus_nav", "demo.zip")


def _entry(name: str, *, is_dir: bool = False) -> dict:
    """构造与 py7z list_archive 产物同构的条目字典。"""
    return {
        "name": name,
        "path": name,
        "is_dir": is_dir,
        "size": 0 if is_dir else 1024,
        "modified": "2026-01-01 00:00",
        "suffix": "" if is_dir else os.path.splitext(name)[1].lstrip("."),
    }


@pytest.fixture()
def previewer(qapp: Any) -> Iterator[ArchivePreviewerLayout]:
    """已显示的压缩包预览器（销毁时注销快捷键登记）。"""
    widget = ArchivePreviewerLayout()
    widget.resize(800, 500)
    widget.show()
    QTest.qWait(50)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.cleanup()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _install_entries(
    previewer: ArchivePreviewerLayout, entries: List[dict]
) -> None:
    """把条目灌进模型并切到「列表可见、无选中」的初始态。"""
    previewer._archive_path = _ARCHIVE_PATH
    previewer._dir_entries_cache = list(entries)
    previewer._model.set_entries(entries)
    previewer._show_list()
    previewer.focus_internal_list()
    QTest.qWait(20)


def test_up_on_first_entry_opens_and_focuses_search(
    previewer: ArchivePreviewerLayout,
) -> None:
    """首行按 ↑：搜索框自动展开并聚焦（无需先记 Shift+F）。"""
    _install_entries(previewer, [_entry("a.txt"), _entry("b.txt")])
    view = previewer._view
    search = previewer._search_edit

    # 首次 ↑ 仍按既有约定落位首条（光标此前被 focus_internal_list 清空）。
    QTest.keyClick(view, Qt.Key.Key_Up)
    QTest.qWait(10)
    assert view.currentIndex().row() == 0
    assert not search.isVisible()

    # 首行再按 ↑：焦点上行到搜索框。
    QTest.keyClick(view, Qt.Key.Key_Up)
    QTest.qWait(10)
    assert search.isVisible()
    assert search.hasFocus()
    assert not previewer._path_edit.isVisible()


def test_up_on_non_first_entry_moves_selection_only(
    previewer: ArchivePreviewerLayout,
) -> None:
    """非首行按 ↑：光标上移一行，焦点不被搜索框抢走。"""
    _install_entries(
        previewer, [_entry("a.txt"), _entry("b.txt"), _entry("c.txt")]
    )
    view = previewer._view
    view.setCurrentIndex(previewer._model.index(2, 0))
    QTest.qWait(10)

    QTest.keyClick(view, Qt.Key.Key_Up)
    QTest.qWait(10)

    assert view.currentIndex().row() == 1
    assert view.hasFocus()
    assert not previewer._search_edit.isVisible()


def test_shift_up_on_first_entry_keeps_native_selection(
    previewer: ArchivePreviewerLayout,
) -> None:
    """``Shift+↑`` 属于多选语义，不触发焦点切换。"""
    _install_entries(previewer, [_entry("a.txt"), _entry("b.txt")])
    view = previewer._view
    view.setCurrentIndex(previewer._model.index(0, 0))
    QTest.qWait(10)

    QTest.keyClick(view, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    QTest.qWait(10)

    assert view.hasFocus()
    assert not previewer._search_edit.isVisible()


def test_warning_row_is_skipped_for_first_entry(
    previewer: ArchivePreviewerLayout,
) -> None:
    """警示行不可选：首个可选条目即视为首行，再按 ↑ 才进搜索框。"""
    # 名称含替换符 → 模型自动在顶部插入不可选警示行（行 0）。
    _install_entries(previewer, [_entry("bad\ufffd.txt"), _entry("a.txt")])
    view = previewer._view
    search = previewer._search_edit

    QTest.keyClick(view, Qt.Key.Key_Up)
    QTest.qWait(10)
    assert view.currentIndex().row() == 1
    assert not search.isVisible()

    QTest.keyClick(view, Qt.Key.Key_Up)
    QTest.qWait(10)
    assert search.isVisible()
    assert search.hasFocus()


def test_down_in_search_returns_to_first_entry(
    previewer: ArchivePreviewerLayout,
) -> None:
    """搜索框按 ↓：焦点回到列表并选中首个可选条目。"""
    _install_entries(previewer, [_entry("a.txt"), _entry("b.txt")])
    view = previewer._view
    search = previewer._search_edit

    previewer._toggle_search()
    QTest.qWait(10)
    assert search.hasFocus()

    QTest.keyClick(search, Qt.Key.Key_Down)
    QTest.qWait(10)

    assert view.hasFocus()
    assert view.currentIndex().row() == 0


def test_escape_from_search_restores_list_focus(
    previewer: ArchivePreviewerLayout,
) -> None:
    """搜索框按 Esc：退出搜索且焦点回到列表（不停在隐藏控件上）。"""
    _install_entries(previewer, [_entry("a.txt"), _entry("b.txt")])
    view = previewer._view
    search = previewer._search_edit

    previewer._toggle_search()
    QTest.qWait(10)
    assert search.hasFocus()

    QTest.keyClick(search, Qt.Key.Key_Escape)
    QTest.qWait(10)

    assert not search.isVisible()
    assert previewer._path_edit.isVisible()
    assert view.hasFocus()


def test_up_with_empty_model_does_not_request_search(qapp: Any) -> None:
    """空模型按 ↑：不发出 search_requested，也不崩。"""
    view = _ArchiveListView()
    view.setModel(_ArchiveListModel(view))
    view.resize(320, 200)
    view.show()
    view.setFocus()
    QTest.qWait(20)

    requests: list = []
    view.search_requested.connect(lambda: requests.append(True))

    QTest.keyClick(view, Qt.Key.Key_Up)
    QTest.qWait(10)

    assert requests == []
    view.close()
    view.deleteLater()
    qapp.processEvents()
