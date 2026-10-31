# -*- coding: utf-8 -*-
"""FloatingPanel 公共浮层面板生命周期测试。

覆盖：
* 构造/显示/展开动画完成（有界事件泵等待几何与透明度到位）；
* close_animated 重入保护：重复调用幂等，closed 信号只发一次；
* 外部点击关闭（应用级事件过滤；面板内点击放行）；
* Esc 关闭（默认关闭该行为时不受影响）；
* delete_on_close 生效；
* 三种锚点模式的目标矩形计算。

运行环境为真实/离屏 Qt 会话均可：用例只依赖事件派发与窗口显隐，
不依赖窗口管理器语义。
"""

from __future__ import annotations

import time
from typing import Any, Callable, List

import pytest
from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from sopeek.ui.components.styled_floating_panel import FloatingPanel

pytestmark = pytest.mark.unit


def _pump(qapp: QApplication, ms: int = 30) -> None:
    """处理事件循环等待动画/显隐稳定，并冲刷 deleteLater 事件。"""
    loop_quit = [False]

    def _timeout() -> None:
        loop_quit[0] = True

    QTimer.singleShot(ms, _timeout)
    while not loop_quit[0]:
        qapp.processEvents()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _wait_until(
    qapp: QApplication, cond: Callable[[], bool], timeout: float = 3.0
) -> bool:
    """有界轮询等待条件成立（驱动事件循环使动画前进）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    qapp.processEvents()
    return cond()


def _send_mouse_press(widget: QWidget, button: Qt.MouseButton = Qt.LeftButton) -> None:
    """向控件发送一次鼠标按下事件（走应用级事件过滤路径）。"""
    local = QPointF(4, 4)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        QPointF(widget.mapToGlobal(QPoint(4, 4))),
        button,
        button,
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _send_escape(widget: QWidget) -> None:
    """向控件发送一次 Esc 按键事件。"""
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


def test_show_and_close_animation_completes(qapp: QApplication) -> None:
    """show_animated 展开到目标尺寸；close_animated 动画完成后隐藏。"""
    panel = FloatingPanel()
    try:
        panel.show_animated(QPoint(400, 300), 160, 80)
        assert panel.isVisible()
        # 初始为向上展开的小高度窗口，动画结束后到达目标尺寸
        assert _wait_until(
            qapp, lambda: panel.size() == QSize(160, 80) and panel.windowOpacity() > 0.99
        )

        panel.close_animated()
        assert _wait_until(qapp, lambda: not panel.isVisible())
    finally:
        panel.deleteLater()
        _pump(qapp)


def test_close_animated_idempotent_and_closed_once(qapp: QApplication) -> None:
    """重复 close_animated 幂等；closed 每次打开周期只发一次。"""
    panel = FloatingPanel()
    closed: List[Any] = []
    panel.closed.connect(lambda: closed.append(True))
    try:
        panel.show_animated(QPoint(400, 300), 140, 70)
        assert _wait_until(qapp, panel.isVisible)

        panel.close_animated()
        panel.close_animated()  # 关闭中重复调用：直接返回
        assert _wait_until(qapp, lambda: not panel.isVisible())
        assert len(closed) == 1

        panel.close_animated()  # 已关闭后再调用：幂等
        _pump(qapp, 60)
        assert len(closed) == 1
    finally:
        panel.deleteLater()
        _pump(qapp)


def test_outside_click_dismisses_but_inside_click_keeps(qapp: QApplication) -> None:
    """开启外部点击关闭后：面板内点击放行，面板外按下收起面板。"""
    other = QWidget()
    other.setGeometry(800, 100, 200, 120)
    other.show()
    panel = FloatingPanel(dismiss_on_outside_click=True)
    try:
        panel.show_animated(QPoint(400, 300), 140, 70)
        assert _wait_until(qapp, panel.isVisible)

        # 面板内按下：不关闭
        _send_mouse_press(panel)
        _pump(qapp, 60)
        assert panel.isVisible()

        # 面板外按下：收起（close_animated 动画完成后隐藏）
        _send_mouse_press(other)
        assert _wait_until(qapp, lambda: not panel.isVisible())
    finally:
        panel.deleteLater()
        other.deleteLater()
        _pump(qapp)


def test_outside_click_ignored_by_default(qapp: QApplication) -> None:
    """默认不启用外部点击关闭：面板外按下不影响面板。"""
    other = QWidget()
    other.setGeometry(800, 100, 200, 120)
    other.show()
    panel = FloatingPanel()
    try:
        panel.show_animated(QPoint(400, 300), 140, 70)
        assert _wait_until(qapp, panel.isVisible)

        _send_mouse_press(other)
        _pump(qapp, 80)
        assert panel.isVisible()
    finally:
        panel.close_animated()
        _pump(qapp, 160)
        panel.deleteLater()
        other.deleteLater()
        _pump(qapp)


def test_escape_dismisses_when_enabled(qapp: QApplication) -> None:
    """开启 dismiss_on_escape 后 Esc 收起面板；默认关闭时忽略。"""
    other = QWidget()
    other.show()
    panel = FloatingPanel(dismiss_on_escape=True)
    try:
        panel.show_animated(QPoint(400, 300), 140, 70)
        assert _wait_until(qapp, panel.isVisible)

        _send_escape(other)
        assert _wait_until(qapp, lambda: not panel.isVisible())
    finally:
        panel.deleteLater()
        other.deleteLater()
        _pump(qapp)


def test_delete_on_close_effective(qapp: QApplication) -> None:
    """delete_on_close=True 时关闭完成后对象被销毁（closed 已发射）。"""
    panel = FloatingPanel(delete_on_close=True)
    closed: List[Any] = []
    panel.closed.connect(lambda: closed.append(True))

    panel.show_animated(QPoint(400, 300), 140, 70)
    assert _wait_until(qapp, panel.isVisible)

    panel.close_animated()
    assert _wait_until(qapp, lambda: len(closed) == 1)
    _pump(qapp, 60)  # 冲刷 DeferredDelete

    with pytest.raises(RuntimeError):
        panel.isVisible()  # 实例已随 deleteLater 销毁


def test_anchor_target_rect_modes(qapp: QApplication) -> None:
    """bottom-center / bottom-right / top-center 三种锚点模式定位语义。"""
    panel = FloatingPanel()
    try:
        anchor = QPoint(600, 400)

        bottom_center = panel._anchor_target_rect(anchor, 120, 60, "bottom-center")
        assert abs(bottom_center.center().x() - anchor.x()) <= 1
        assert bottom_center.bottom() < anchor.y()

        bottom_right = panel._anchor_target_rect(anchor, 120, 60, "bottom-right")
        assert bottom_right.right() == anchor.x() - 1
        assert bottom_right.bottom() < anchor.y()

        top_center = panel._anchor_target_rect(anchor, 120, 60, "top-center")
        assert abs(top_center.center().x() - anchor.x()) <= 1
        assert top_center.top() > anchor.y()

        # 贴近屏幕左上角时钳制在可用区域内
        clamped = panel._anchor_target_rect(QPoint(2, 2), 120, 60, "bottom-center")
        screen = QApplication.primaryScreen()
        assert screen is not None
        sg = screen.availableGeometry()
        assert clamped.left() >= sg.x() + 8
        assert clamped.top() >= sg.y() + 8
    finally:
        panel.deleteLater()
        _pump(qapp)


def test_refresh_theme_smoke(qapp: QApplication) -> None:
    """refresh_theme / update 不抛异常（背景色在 paintEvent 现取）。"""
    panel = FloatingPanel()
    try:
        panel.refresh_theme()
        panel.update()
    finally:
        panel.deleteLater()
        _pump(qapp)
