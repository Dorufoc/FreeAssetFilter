# -*- coding: utf-8 -*-
"""全屏宿主键盘转发回归测试。

历史缺陷：宿主把按键 ``sendEvent`` 给内容控件；内容不处理时事件沿父链
冒泡回宿主，再次进入 ``keyPressEvent`` → 无限递归 → 原生栈溢出崩溃。
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

pytestmark = pytest.mark.unit


def test_fullscreen_host_key_forward_does_not_recurse(qapp: Any) -> None:
    """内容控件不消费按键时，宿主转发一次后必须正常返回。"""
    from sopeek.ui.layout.preview.fullscreen_host import PreviewFullscreenHost

    host = PreviewFullscreenHost()
    content = QWidget()
    content.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    assert host.attach(content) is True
    host.show()
    qapp.processEvents()
    try:
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Backslash,
            Qt.KeyboardModifier.ControlModifier,
        )
        # 直接投递到宿主：修复前这里会栈溢出崩溃
        QApplication.sendEvent(host, event)
        assert host.content is content
    finally:
        host.exit_fullscreen()
        host.close()
        content.deleteLater()
        host.deleteLater()
        qapp.processEvents()
