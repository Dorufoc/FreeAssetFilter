# -*- coding: utf-8 -*-
"""``TrayController`` 单元测试。

覆盖两条契约：

* 系统托盘不可用时安全降级：不抛异常，``is_available`` 为 False，
  ``show`` / ``hide`` / ``dispose`` 全部无操作；
* 系统托盘可用时：右键菜单含「打开主界面」「彻底退出」两项且分别发出对应
  信号，双击托盘图标发出 ``open_requested``，单击不误触。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/test_tray_controller.py -v
"""

from __future__ import annotations

from typing import List

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

from sopeek.ui.tray_controller import TrayController

pytestmark = pytest.mark.unit


@pytest.fixture()
def _tray_available(monkeypatch):
    """强制系统托盘可用（离屏环境默认不可用）。"""
    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True)
    )


@pytest.fixture()
def _tray_unavailable(monkeypatch):
    """强制系统托盘不可用。"""
    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False)
    )


def _record(signal) -> List[int]:
    """收集信号触发次数的最小替身（避免依赖 QSignalSpy）。"""
    received: List[int] = []
    signal.connect(lambda: received.append(1))
    return received


def test_unavailable_degrades_safely(qapp, _tray_unavailable) -> None:
    """托盘不可用：不抛异常、无菜单、show/hide/dispose 均为空操作。"""
    controller = TrayController()
    try:
        assert controller.is_available is False
        assert controller.menu is None

        controller.show()
        controller.hide()
        controller.dispose()

        assert controller.is_available is False
    finally:
        controller.dispose()


def test_available_builds_menu_and_emits_signals(qapp, _tray_available) -> None:
    """托盘可用：菜单动作与双击/菜单触发都映射到对应信号。"""
    controller = TrayController()
    opened = _record(controller.open_requested)
    quit_ = _record(controller.quit_requested)
    try:
        assert controller.is_available is True

        menu = controller.menu
        assert menu is not None
        labels = [action.text() for action in menu.actions()]
        assert "打开主界面" in labels
        assert "彻底退出" in labels

        open_action = next(a for a in menu.actions() if a.text() == "打开主界面")
        quit_action = next(a for a in menu.actions() if a.text() == "彻底退出")

        open_action.trigger()
        assert opened == [1]

        quit_action.trigger()
        assert quit_ == [1]

        tray = controller._tray
        assert tray is not None

        # 双击托盘图标 → 打开主界面。
        tray.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert opened == [1, 1]

        # 单击（Trigger）不得误触打开。
        tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        assert opened == [1, 1]
    finally:
        controller.dispose()
        # dispose 幂等：重复调用仍不抛异常。
        controller.dispose()
        assert controller.is_available is False
        assert controller.menu is None
