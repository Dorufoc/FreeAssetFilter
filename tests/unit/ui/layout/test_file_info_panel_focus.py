# -*- coding: utf-8 -*-
"""文件信息面板焦点归属回归。

背景（用户实测反馈）：空的信息面板不应该能获得键盘焦点。此前画布与
``QScrollArea`` 都是 ``StrongFocus``，点击空白区会把焦点落在空面板上，
键盘切区也会停在这里。

本文件锁定以下契约：

* 空面板：画布/滚动区均 NoFocus，子树内没有可见可聚焦控件，
  ``focus_canvas()`` 返回 False；
* 有文件：画布/滚动区恢复 StrongFocus，``focus_canvas()`` 聚焦画布；
* 焦点在画布时清空文件：取消焦点并发出 ``focus_exhausted``，由宿主导回
  文件选择器。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_file_info_panel_focus.py -v
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from sopeek.ui.layout.preview.file_info_panel import FileInfoPanel

pytestmark = [pytest.mark.unit, pytest.mark.widgets]


@pytest.fixture
def panel(qapp: Any) -> Iterator[FileInfoPanel]:
    """已显示的空信息面板（无文件）。"""
    widget = FileInfoPanel()
    widget.resize(600, 400)
    widget.show()
    QTest.qWait(50)
    qapp.processEvents()
    try:
        yield widget
    finally:
        widget.stop()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _visible_focusable_children(root: QWidget) -> list:
    """返回子树内「可见且可聚焦」的控件（空面板必须为空列表）。"""
    return [
        child
        for child in root.findChildren(QWidget)
        if child.isVisible() and child.focusPolicy() != Qt.FocusPolicy.NoFocus
    ]


def _file_info(tmp_path: Any) -> dict:
    """构造一个真实存在的文本文件信息（走同步 light 行采集）。"""
    path = tmp_path / "sample.txt"
    path.write_text("hello", encoding="utf-8")
    return {"path": str(path), "name": "sample.txt", "suffix": "txt"}


def test_empty_panel_is_not_focusable(panel: FileInfoPanel) -> None:
    """空面板：画布与滚动区都不可聚焦，也没有可聚焦子控件。"""
    assert panel.has_file() is False
    assert panel._canvas.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert panel._scroll_area.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert _visible_focusable_children(panel) == []
    assert panel.focus_canvas() is False


def test_panel_becomes_focusable_with_file(
    panel: FileInfoPanel, tmp_path: Any
) -> None:
    """有文件后画布恢复可聚焦，``focus_canvas`` 能真正拿到焦点。"""
    panel.set_file(_file_info(tmp_path))
    QApplication.processEvents()

    assert panel.has_file() is True
    assert panel._canvas.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert panel._scroll_area.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert panel.focus_canvas() is True
    QApplication.processEvents()
    assert QApplication.focusWidget() is panel._canvas


def test_clear_while_focused_emits_focus_exhausted(
    panel: FileInfoPanel, tmp_path: Any
) -> None:
    """焦点在画布时清空文件：取消焦点并发出回退信号。"""
    panel.set_file(_file_info(tmp_path))
    QApplication.processEvents()
    assert panel.focus_canvas() is True
    QApplication.processEvents()
    assert panel._canvas.hasFocus()

    emitted: list = []
    panel.focus_exhausted.connect(lambda: emitted.append(True))

    panel.clear()
    QApplication.processEvents()

    assert panel.has_file() is False
    assert panel._canvas.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert panel._scroll_area.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert panel._canvas.hasFocus() is False
    assert emitted == [True]
