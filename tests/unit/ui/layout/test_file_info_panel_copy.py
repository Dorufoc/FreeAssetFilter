# -*- coding: utf-8 -*-
"""文件信息面板复制交互测试。

覆盖：

* 左键单击条目 → 复制该条目值，底部提示「已复制」并显示前置对勾图标；
* 左键单击路径行 → 复制完整路径（不省略）；
* 左键双击条目 → 与单击一致（双击无特殊语义，防回归）；
* 右键单击信息区 → 复制全部信息且不弹右键菜单；
* 右键空白区 → 同样复制全部信息；
* Ctrl+左键点击路径 → 资源管理器定位，剪贴板不变；
* 空状态右键 → 剪贴板不变（``_copy_all`` 的空文件守卫）。

验证命令：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/layout/test_file_info_panel_copy.py -v
"""

from __future__ import annotations

from typing import Any, Iterator, Tuple

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

import sopeek.ui.layout.preview.file_info_panel as fip_mod
from sopeek.ui.layout.preview.file_info_panel import FileInfoPanel

pytestmark = pytest.mark.unit


def _release(canvas: Any, pos: QPointF, modifiers: Qt.KeyboardModifier = Qt.NoModifier) -> None:
    """向画布投递一次左键释放事件（绕过平台事件队列，直接走命中逻辑）。"""
    event = QMouseEvent(
        QEvent.MouseButtonRelease,
        pos,
        canvas.mapToGlobal(pos.toPoint()).toPointF(),
        Qt.LeftButton,
        Qt.LeftButton,
        modifiers,
    )
    canvas.mouseReleaseEvent(event)


def _context_menu(canvas: Any, pos: QPoint = QPoint(4, 4)) -> None:
    """向画布投递一次右键菜单事件。"""
    event = QContextMenuEvent(
        QContextMenuEvent.Mouse, pos, canvas.mapToGlobal(pos)
    )
    canvas.contextMenuEvent(event)


@pytest.fixture
def panel(qapp: Any, tmp_path: Any) -> Iterator[Tuple[FileInfoPanel, str]]:
    """带一个真实文本文件的信息面板（已 show + 布局落地）。"""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")
    widget = FileInfoPanel()
    widget.show()
    widget.set_file({"path": str(file_path), "name": "sample.txt", "suffix": "txt"})
    widget.resize(600, 400)
    qapp.processEvents()
    try:
        yield widget, str(file_path)
    finally:
        widget.stop()
        widget.close()
        widget.deleteLater()
        qapp.processEvents()


def _row(panel: FileInfoPanel, kind: str = "grid") -> Any:
    """取首个指定类型的画布条目（标题/路径/属性行）。"""
    for item in panel._canvas._items:
        if item.kind == kind:
            return item
    raise AssertionError(f"画布中没有 kind={kind} 的条目")


def test_single_click_copies_value_with_check_toast(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """左键单击属性行：复制该值，提示带对勾图标。"""
    widget, _path = panel
    row = _row(widget)
    QApplication.clipboard().setText("")

    _release(widget._canvas, QPointF(row.rect.center()))
    qapp.processEvents()

    assert QApplication.clipboard().text() == row.value
    assert widget._toast_label.text() == "已复制"
    assert not widget._toast.isHidden()
    assert not widget._toast_icon.isHidden()
    assert not widget._toast_icon.pixmap().isNull()


def test_single_click_on_path_copies_full_path(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """左键单击路径行：剪贴板是未省略的完整路径。"""
    widget, path = panel
    row = _row(widget, "path")
    QApplication.clipboard().setText("")

    _release(widget._canvas, QPointF(row.rect.center()))
    qapp.processEvents()

    assert QApplication.clipboard().text() == path


def test_double_click_behaves_like_single_click(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """左键双击无特殊语义：仍是复制该条目（不复制全部）。"""
    widget, _path = panel
    row = _row(widget)
    QApplication.clipboard().setText("")

    canvas = widget._canvas
    pos = QPointF(row.rect.center())
    _release(canvas, pos)
    dbl = QMouseEvent(
        QEvent.MouseButtonDblClick,
        pos,
        canvas.mapToGlobal(pos.toPoint()).toPointF(),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    canvas.mouseDoubleClickEvent(dbl)
    _release(canvas, pos)
    qapp.processEvents()

    assert QApplication.clipboard().text() == row.value
    assert widget._toast_label.text() == "已复制"


def test_right_click_copies_all_without_menu(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """右键单击信息区：复制全部信息，且不弹任何菜单。"""
    widget, path = panel
    QApplication.clipboard().setText("")

    _context_menu(widget._canvas)
    qapp.processEvents()

    text = QApplication.clipboard().text()
    assert text.startswith("文件信息")
    assert f"文件路径: {path}" in text
    assert "类别: " in text
    assert widget._toast_label.text() == "已复制全部信息"
    assert QApplication.activePopupWidget() is None


def test_right_click_on_empty_area_copies_all(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """右键画布空白区：同样复制全部信息（不因未命中行而静默）。"""
    widget, _path = panel
    QApplication.clipboard().setText("")

    _context_menu(widget._canvas, QPoint(4, widget._canvas.height() - 2))
    qapp.processEvents()

    assert QApplication.clipboard().text().startswith("文件信息")


def test_ctrl_click_path_opens_explorer_without_copying(
    qapp: Any, panel: Tuple[FileInfoPanel, str], monkeypatch: Any
) -> None:
    """Ctrl+左键路径：定位资源管理器，剪贴板不变。"""
    widget, path = panel
    row = _row(widget, "path")
    opened: list = []
    monkeypatch.setattr(
        fip_mod.FileInfoPanel, "_open_in_explorer", staticmethod(opened.append)
    )
    QApplication.clipboard().setText("sentinel")

    _release(widget._canvas, QPointF(row.rect.center()), Qt.ControlModifier)
    qapp.processEvents()

    assert opened == [path]
    assert QApplication.clipboard().text() == "sentinel"


def test_right_click_without_file_keeps_clipboard(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """空状态右键：``_copy_all`` 直接返回，剪贴板与提示都不变。"""
    widget, _path = panel
    widget.set_file(None)
    qapp.processEvents()
    QApplication.clipboard().setText("sentinel")

    _context_menu(widget._canvas)
    qapp.processEvents()

    assert QApplication.clipboard().text() == "sentinel"
    assert widget._toast.isHidden()


def test_toast_fades_in_and_out(
    qapp: Any, panel: Tuple[FileInfoPanel, str]
) -> None:
    """提示淡入到完全不透明，超时后淡出并隐藏（动画开关默认开启）。"""
    widget, _path = panel
    row = _row(widget)

    _release(widget._canvas, QPointF(row.rect.center()))
    qapp.processEvents()

    assert not widget._toast.isHidden()
    assert widget._toast_fade is not None
    widget._toast_fade.setCurrentTime(widget._toast_fade.duration())
    qapp.processEvents()
    assert widget._toast_effect.opacity() == pytest.approx(1.0)

    widget._toast_timer.stop()
    widget._hide_copy_toast()
    qapp.processEvents()
    fade = widget._toast_fade
    assert fade is not None
    fade.setCurrentTime(fade.duration())
    qapp.processEvents()

    assert widget._toast.isHidden()
    assert widget._toast_effect.opacity() == pytest.approx(0.0)
    assert widget._toast_fade is None


def test_toast_animation_disabled_hides_instantly(
    qapp: Any, panel: Tuple[FileInfoPanel, str], monkeypatch: Any
) -> None:
    """全局动画关闭：提示立即显示为完全不透明，隐藏时也不建动画。"""
    widget, _path = panel
    monkeypatch.setattr(
        fip_mod, "is_animation_enabled", lambda *args, **kwargs: False
    )
    row = _row(widget)

    _release(widget._canvas, QPointF(row.rect.center()))
    qapp.processEvents()

    assert not widget._toast.isHidden()
    assert widget._toast_fade is None
    assert widget._toast_effect.opacity() == pytest.approx(1.0)

    widget._hide_copy_toast()
    qapp.processEvents()

    assert widget._toast.isHidden()
    assert widget._toast_fade is None
    assert widget._toast_effect.opacity() == pytest.approx(0.0)
