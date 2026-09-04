# -*- coding: utf-8 -*-
"""缩放/字重弹窗（_ZoomPopup / _WeightPopup）生命周期与随动行为测试。

覆盖四个新 UI 预览器的弹窗修复：
* 弹窗以预览器布局为真实 Qt 父级（owned tool 窗口）——层级在主窗口之上；
* 预览器销毁时弹窗随之销毁（无残留悬浮窗口 / 无多实例累积）；
* 主窗口移动时弹窗跟随锚点移动（拖拽窗口不会把弹窗“按消失”）；
* 弹窗外普通点击（未拖动窗口）在释放时收起弹窗；
* cleanup() 收起并销毁弹窗实例。

运行平台为真实 Windows 会话（与既有 widget 测试一致），使用顶部宿主窗口
承载预览器以获得合法的 mapToGlobal 锚点。
"""

from __future__ import annotations

from typing import Any, List

import pytest
from PySide6.QtCore import (
    Qt,
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QTimer,
)
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from freeassetfilter.ui.layout.preview.font_previewer_layout import (
    FontPreviewerLayout,
    _ZoomPopup as FontZoomPopup,
    _WeightPopup as FontWeightPopup,
)
from freeassetfilter.ui.layout.preview.image_previewer_layout import (
    ImagePreviewerLayout,
)
from freeassetfilter.ui.layout.preview.pdf_previewer_layout import (
    PdfPreviewerLayout,
)
from freeassetfilter.ui.layout.preview.text_previewer_layout import (
    TextPreviewerLayout,
)

_ZOOM_CLASSES: List[Any] = [
    ImagePreviewerLayout,
    PdfPreviewerLayout,
    TextPreviewerLayout,
    FontPreviewerLayout,
]


def _pump(ms: int = 30) -> None:
    """处理事件循环等待弹窗显隐/动画稳定，并冲刷 deleteLater 事件。"""
    loop_quit = [False]

    def _timeout() -> None:
        loop_quit[0] = True

    QTimer.singleShot(ms, _timeout)
    while not loop_quit[0]:
        QApplication.processEvents()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _make_host(previewer: QWidget) -> QWidget:
    """构建并显示一个承载预览器的宿主窗口，返回宿主。"""
    host = QWidget()
    host.setWindowTitle(type(previewer).__name__)
    host.setGeometry(140, 140, 900, 560)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(previewer)
    host.show()
    _pump(60)
    return host


def _shutdown_host(host: QWidget, previewer: Any = None) -> None:
    """关闭并销毁宿主（幂等，已销毁的 C++ 对象直接忽略）。"""
    if previewer is not None:
        try:
            previewer.cleanup()
        except RuntimeError:
            pass
    try:
        host.close()
        host.deleteLater()
    except RuntimeError:
        pass
    _pump(30)


def _open_zoom(previewer: Any) -> None:
    """点击预览器缩放按钮并等待弹窗展开。"""
    previewer._on_zoom_clicked()
    _pump(40)


def _outside_global(previewer: Any, popup: QWidget) -> QPoint:
    """返回一个位于弹窗之外、宿主窗口内的屏幕坐标点（左上角区域）。"""
    host = previewer.window()
    assert host.isVisible()
    return QPoint(host.x() + 12, host.y() + 12)


def _send_mouse_click(previewer: Any, etype: QEvent.Type, global_pos: QPoint) -> None:
    """向预览器根控件发送一次鼠标事件（走应用级事件过滤路径）。"""
    local = QPointF(
        global_pos.x() - previewer.window().x(),
        global_pos.y() - previewer.window().y(),
    )
    event = QMouseEvent(
        etype,
        local,
        QPointF(global_pos),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(previewer, event)


@pytest.mark.parametrize("previewer_cls", _ZOOM_CLASSES)
def test_zoom_popup_owned_by_previewer(
    qapp: QApplication, previewer_cls: Any
) -> None:
    """缩放弹窗以预览器布局为真实 Qt 父级（owned tool 窗口）。"""
    previewer = previewer_cls()
    host = _make_host(previewer)
    try:
        _open_zoom(previewer)
        popup = previewer._zoom_popup
        assert popup is not None
        assert popup.isVisible()
        assert popup.parentWidget() is previewer
        # 弹窗是独立的顶层 tool 窗口（非内嵌子控件）
        assert popup.window() is popup
    finally:
        _shutdown_host(host, previewer)


@pytest.mark.parametrize("previewer_cls", _ZOOM_CLASSES)
def test_zoom_popup_follows_host_window_move(
    qapp: QApplication, previewer_cls: Any
) -> None:
    """主窗口移动时缩放弹窗跟随锚点移动（不被遮挡/滞留原位）。"""
    previewer = previewer_cls()
    host = _make_host(previewer)
    try:
        _open_zoom(previewer)
        popup = previewer._zoom_popup
        assert popup is not None and popup.isVisible()

        before = popup.pos()
        dx, dy = 90, 60
        host.move(host.x() + dx, host.y() + dy)
        _pump(60)

        after = popup.pos()
        assert abs((after.x() - before.x()) - dx) <= 1
        assert abs((after.y() - before.y()) - dy) <= 1
    finally:
        _shutdown_host(host, previewer)


@pytest.mark.parametrize("previewer_cls", _ZOOM_CLASSES)
def test_zoom_popup_closed_and_discarded_by_cleanup(
    qapp: QApplication, previewer_cls: Any
) -> None:
    """cleanup() 收起缩放弹窗并销毁实例（引用清空、窗口不残留）。"""
    previewer = previewer_cls()
    host = _make_host(previewer)
    try:
        _open_zoom(previewer)
        popup = previewer._zoom_popup
        assert popup is not None and popup.isVisible()

        previewer.cleanup()
        _pump(40)

        assert previewer._zoom_popup is None
        with pytest.raises(RuntimeError):
            popup.isVisible()  # 实例已随 discard 销毁
    finally:
        _shutdown_host(host)


@pytest.mark.parametrize("previewer_cls", _ZOOM_CLASSES)
def test_zoom_popup_destroyed_with_previewer(
    qapp: QApplication, previewer_cls: Any
) -> None:
    """预览器销毁时弹窗随 Qt 父级一起销毁（不残留悬浮窗口）。"""
    previewer = previewer_cls()
    host = _make_host(previewer)
    try:
        _open_zoom(previewer)
        popup = previewer._zoom_popup
        assert popup is not None and popup.isVisible()

        # 模拟 unified previewer 的拆除流程：脱离宿主后 deleteLater
        previewer.setParent(None)
        previewer.deleteLater()
        _pump(80)

        with pytest.raises(RuntimeError):
            popup.isVisible()  # C++ 对象已随预览器销毁
    finally:
        _shutdown_host(host)


def test_font_popups_mutually_exclusive(qapp: QApplication) -> None:
    """字体预览器：打开缩放会收起字重弹窗，反之亦然（不叠显）。"""
    previewer = FontPreviewerLayout()
    host = _make_host(previewer)
    try:
        previewer.current_font_family = "Arial"
        assert previewer._weight_btn is not None

        # 打开字重弹窗
        previewer._on_weight_clicked()
        _pump(40)
        weight_popup = previewer._weight_popup
        assert isinstance(weight_popup, FontWeightPopup)
        assert weight_popup.isVisible()

        # 打开缩放弹窗 → 字重弹窗应被收起（动画约 120ms，等待其真正隐藏）
        _open_zoom(previewer)
        _pump(250)
        zoom_popup = previewer._zoom_popup
        assert isinstance(zoom_popup, FontZoomPopup)
        assert zoom_popup.isVisible()
        assert not weight_popup.isVisible()

        # 再开字重 → 缩放弹窗应被收起
        previewer._on_weight_clicked()
        _pump(250)
        assert weight_popup.isVisible()
        assert not zoom_popup.isVisible()

        # 两处引用各自单一实例（重复开关不创建新实例）
        same_weight = weight_popup
        previewer._on_weight_clicked()  # 收起
        _pump(250)
        previewer._on_weight_clicked()  # 再展开
        _pump(40)
        assert previewer._weight_popup is same_weight
    finally:
        _shutdown_host(host, previewer)


@pytest.mark.parametrize("previewer_cls", _ZOOM_CLASSES)
def test_zoom_popup_survives_window_drag_gesture(
    qapp: QApplication, previewer_cls: Any
) -> None:
    """弹窗外按下 → 拖动窗口 → 释放：弹窗不消失，跟随窗口一起移动。

    模拟真实场景：标题栏按下（startSystemMove 起点）是弹窗外 MouseButtonPress，
    期间窗口发生 Move；释放时不应把弹窗当普通外部点击收起。
    """
    previewer = previewer_cls()
    host = _make_host(previewer)
    try:
        _open_zoom(previewer)
        popup = previewer._zoom_popup
        assert popup is not None and popup.isVisible()

        press_global = _outside_global(previewer, popup)
        popup_rect = QRect(popup.pos(), popup.size())
        assert not popup_rect.contains(press_global)

        _send_mouse_click(previewer, QEvent.MouseButtonPress, press_global)
        before = popup.pos()

        dx, dy = 90, 60
        host.move(host.x() + dx, host.y() + dy)
        _pump(60)

        _send_mouse_click(previewer, QEvent.MouseButtonRelease, press_global)
        _pump(250)  # 若错误关闭，此时弹窗已随关闭动画隐藏

        assert popup.isVisible(), "拖拽窗口后弹窗不应被关闭"
        after = popup.pos()
        assert abs((after.x() - before.x()) - dx) <= 1
        assert abs((after.y() - before.y()) - dy) <= 1
    finally:
        _shutdown_host(host, previewer)


@pytest.mark.parametrize("previewer_cls", _ZOOM_CLASSES)
def test_zoom_popup_dismissed_by_plain_outside_click(
    qapp: QApplication, previewer_cls: Any
) -> None:
    """弹窗外普通点击（未拖动窗口）：释放时收起缩放弹窗。"""
    previewer = previewer_cls()
    host = _make_host(previewer)
    try:
        _open_zoom(previewer)
        popup = previewer._zoom_popup
        assert popup is not None and popup.isVisible()

        press_global = _outside_global(previewer, popup)
        popup_rect = QRect(popup.pos(), popup.size())
        assert not popup_rect.contains(press_global)

        _send_mouse_click(previewer, QEvent.MouseButtonPress, press_global)
        _send_mouse_click(previewer, QEvent.MouseButtonRelease, press_global)
        _pump(250)  # 等待关闭动画完成

        assert not popup.isVisible()
    finally:
        _shutdown_host(host, previewer)
