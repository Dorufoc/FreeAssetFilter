# -*- coding: utf-8 -*-
"""文件夹 / 压缩包预览器「首次方向键落位」回归。

背景（用户实测反馈）：进入文件夹预览器或压缩包预览器后，列表里没有任何
条目带光标；此时第一次按任意方向键应先把光标落到**第一条**，而不是直接
跳到第二条。

根因：模型重建后 Qt 会在列表 show / 获得焦点时把 ``currentIndex`` 自动置为
第 0 行（不带选中态，视觉上没有光标），原生方向键会从第 0 行再走一格。
两个列表视图因此覆写 ``keyPressEvent``：无选中项时先落位并消费该键。

本文件锁定以下契约：

* 进入文件夹预览器后首次任意方向键 → 第 0 行被选中；
* 第二次按键才正常移动一格；
* 进入子目录后同样先落位（Qt 自动 current 不应导致跳过首行）；
* 压缩包预览器同样先落位，且自动跳过不可选的警示行；
* 列表为空时按键不崩（交给 Qt 原生处理）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_previewer_list_landing.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from sopeek.ui.layout.preview.archive_previewer_layout import (
    ArchivePreviewerLayout,
)
from sopeek.ui.layout.preview.folder_previewer_layout import FolderPreviewerLayout

pytestmark = [pytest.mark.unit, pytest.mark.widgets]

_ARROWS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)


@pytest.fixture
def folder_root(tmp_path: Any) -> str:
    """根目录：``sub/`` + 4 个文件（子目录排在最前，模拟真实排序）。"""
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    for index in range(4):
        (root / f"f{index}.txt").write_text("x", encoding="utf-8")
    for index in range(3):
        (root / "sub" / f"g{index}.txt").write_text("x", encoding="utf-8")
    return str(root)


@pytest.fixture
def folder_previewer(qapp: Any, folder_root: str) -> Iterator[FolderPreviewerLayout]:
    """已加载 ``folder_root`` 的文件夹预览器（列表页可见）。"""
    host = QWidget()
    layout = QVBoxLayout(host)
    widget = FolderPreviewerLayout()
    layout.addWidget(widget)
    host.show()
    widget.set_file(folder_root)
    QTest.qWait(500)
    qapp.processEvents()
    try:
        yield widget
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


@pytest.fixture
def archive_previewer(qapp: Any) -> Iterator[ArchivePreviewerLayout]:
    """已灌入条目的压缩包预览器（列表页可见）。"""
    host = QWidget()
    layout = QVBoxLayout(host)
    widget = ArchivePreviewerLayout()
    layout.addWidget(widget)
    host.show()
    qapp.processEvents()
    try:
        yield widget
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()


def _selected_rows(view: Any) -> list:
    return [index.row() for index in view.selectionModel().selectedIndexes()]


def _install_archive_entries(widget: ArchivePreviewerLayout, entries: list) -> None:
    """把条目灌进压缩包预览器并切到列表页（模拟一次读取完成）。"""
    widget._dir_entries_cache = [dict(entry) for entry in entries]
    widget._model.set_entries(entries)
    widget._view.scrollToTop()
    widget._view.clearSelection()
    widget._show_list()
    QTest.qWait(20)


@pytest.mark.parametrize("key", _ARROWS)
def test_folder_first_arrow_lands_on_first_row(
    folder_previewer: FolderPreviewerLayout, qapp: Any, key: Any
) -> None:
    """文件夹预览器：无选中项时首次任意方向键落到第 0 行。"""
    view = folder_previewer._view
    view.setFocus()
    qapp.processEvents()
    assert _selected_rows(view) == []

    QTest.keyClick(view, key)
    qapp.processEvents()

    assert view.currentIndex().row() == 0
    assert _selected_rows(view) == [0]


def test_folder_second_arrow_moves_one_row(
    folder_previewer: FolderPreviewerLayout, qapp: Any
) -> None:
    """落位后第二次按 ↓ 才正常前进一行。"""
    view = folder_previewer._view
    view.setFocus()
    qapp.processEvents()

    QTest.keyClick(view, Qt.Key.Key_Down)
    qapp.processEvents()
    assert view.currentIndex().row() == 0

    QTest.keyClick(view, Qt.Key.Key_Down)
    qapp.processEvents()
    assert view.currentIndex().row() == 1


def test_folder_first_arrow_after_entering_subdir(
    folder_previewer: FolderPreviewerLayout, qapp: Any
) -> None:
    """进入子目录后（模型重建）首次方向键仍落到第一行。"""
    view = folder_previewer._view
    view.setFocus()
    qapp.processEvents()

    folder_previewer._enter_dir("sub")
    QTest.qWait(400)
    qapp.processEvents()
    assert _selected_rows(view) == []

    QTest.keyClick(view, Qt.Key.Key_Down)
    qapp.processEvents()
    assert view.currentIndex().row() == 0


@pytest.mark.parametrize("key", _ARROWS)
def test_archive_first_arrow_lands_on_first_row(
    archive_previewer: ArchivePreviewerLayout, qapp: Any, key: Any
) -> None:
    """压缩包预览器：无选中项时首次任意方向键落到第 0 行。"""
    _install_archive_entries(
        archive_previewer,
        [
            {"name": "d1/", "is_dir": True, "size": 0, "modified": "", "suffix": ""},
            {"name": "a.txt", "is_dir": False, "size": 1, "modified": "", "suffix": "txt"},
            {"name": "b.txt", "is_dir": False, "size": 1, "modified": "", "suffix": "txt"},
        ],
    )
    view = archive_previewer._view
    view.setFocus()
    qapp.processEvents()
    assert _selected_rows(view) == []

    QTest.keyClick(view, key)
    qapp.processEvents()

    assert view.currentIndex().row() == 0
    assert _selected_rows(view) == [0]


def test_archive_second_arrow_moves_one_row(
    archive_previewer: ArchivePreviewerLayout, qapp: Any
) -> None:
    """落位后第二次按 ↓ 才正常前进一行。"""
    _install_archive_entries(
        archive_previewer,
        [
            {"name": "a.txt", "is_dir": False, "size": 1, "modified": "", "suffix": "txt"},
            {"name": "b.txt", "is_dir": False, "size": 1, "modified": "", "suffix": "txt"},
        ],
    )
    view = archive_previewer._view
    view.setFocus()
    qapp.processEvents()

    QTest.keyClick(view, Qt.Key.Key_Down)
    qapp.processEvents()
    assert view.currentIndex().row() == 0

    QTest.keyClick(view, Qt.Key.Key_Down)
    qapp.processEvents()
    assert view.currentIndex().row() == 1


def test_archive_first_arrow_skips_warning_row(
    archive_previewer: ArchivePreviewerLayout, qapp: Any
) -> None:
    """首行是警示行（不可选）时，落位跳到第一条可选条目。"""
    _install_archive_entries(
        archive_previewer,
        [
            {"name": "bad\ufffdname", "is_dir": False, "size": 1, "modified": "", "suffix": ""},
            {"name": "c.txt", "is_dir": False, "size": 1, "modified": "", "suffix": "txt"},
        ],
    )
    view = archive_previewer._view
    assert archive_previewer._model.kind_at(0) == "warning"
    view.setFocus()
    qapp.processEvents()

    QTest.keyClick(view, Qt.Key.Key_Down)
    qapp.processEvents()

    assert view.currentIndex().row() == 1
    assert archive_previewer._model.kind_at(view.currentIndex().row()) == "file"


def test_folder_empty_list_ignores_arrow(
    qapp: Any, tmp_path: Any
) -> None:
    """空文件夹：方向键不崩（交给 Qt 原生处理，无选中项）。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    host = QWidget()
    layout = QVBoxLayout(host)
    widget = FolderPreviewerLayout()
    layout.addWidget(widget)
    host.show()
    widget.set_file(str(empty))
    QTest.qWait(400)
    qapp.processEvents()
    try:
        view = widget._view
        view.setFocus()
        qapp.processEvents()
        QTest.keyClick(view, Qt.Key.Key_Down)
        qapp.processEvents()
        assert _selected_rows(view) == []
    finally:
        host.close()
        host.deleteLater()
        qapp.processEvents()
