# -*- coding: utf-8 -*-
"""Mica 应用级激活状态回归。

背景：设置窗、收藏夹/筛选等 ``Qt.Dialog``、菜单与 ``Qt.Tool`` 浮层都是
本应用的独立顶层窗口。它们获得焦点时主窗口本身收不到 ``WindowActivate``；
旧实现只用 ``QApplication.activeWindow()`` 做一次 60ms 防抖，会把主窗口
材质永久锁死在失焦暂停态（局部区域退化成 G1）。

本文件锁定以下契约：

* 应用仍在前台 → 任一应用窗口获得焦点都应恢复 Mica；
* 整个应用切后台 → 防抖后淡出；
* 构造时应用已失活 → 初始状态即为隐藏；
* 失焦白名单按 weakref 解引用比较；
* 30s idle 释放只在应用失活 / 最小化时发生。

验证：
    $env:QT_QPA_PLATFORM='offscreen'
    python -m pytest tests/unit/ui/mica/test_activation.py -v
"""

from __future__ import annotations

from typing import Any, Iterator, Tuple

import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QWidget

import sopeek.ui.mica.material as material_mod
from sopeek.ui.mica.material import MicaMaterial

pytestmark = pytest.mark.unit


@pytest.fixture()
def material(qapp) -> Iterator[Tuple[QWidget, MicaMaterial]]:
    """创建一个惰性材质（不烘焙），测试结束显式释放信号连接。"""
    widget = QWidget()
    widget.resize(320, 200)
    mica = MicaMaterial(widget, surface_color="#000000", lazy=True)
    try:
        yield widget, mica
    finally:
        mica.dispose()
        widget.deleteLater()


def test_application_deactivate_check_uses_app_state(
    material: Tuple[QWidget, MicaMaterial],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """失焦复查只看应用状态，不再受 activeWindow 瞬态 None 影响。"""
    _widget, mica = material
    calls: list[bool] = []
    monkeypatch.setattr(mica, "set_active", calls.append)

    monkeypatch.setattr(material_mod, "_application_is_active", lambda: False)
    mica._on_deactivate_check()
    assert calls == [False]

    monkeypatch.setattr(material_mod, "_application_is_active", lambda: True)
    mica._on_deactivate_check()
    assert calls == [False, True]


def test_application_state_signal_binding(
    material: Tuple[QWidget, MicaMaterial],
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """材质必须真正连上 applicationStateChanged，而不是只在方法内判断状态。"""
    _widget, mica = material
    calls: list[bool] = []
    monkeypatch.setattr(mica, "set_active", calls.append)
    mica._deactivate_timer.stop()

    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    assert mica._deactivate_timer.isActive()

    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    assert calls == [True]
    assert not mica._deactivate_timer.isActive()


def test_focus_window_signal_binding(
    material: Tuple[QWidget, MicaMaterial],
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """材质必须真正连上 focusWindowChanged（应用内窗口抢焦点恢复）。"""
    _widget, mica = material
    calls: list[bool] = []
    monkeypatch.setattr(mica, "set_active", calls.append)
    mica._deactivate_timer.start()

    qapp.focusWindowChanged.emit(QWindow())

    assert calls == [True]
    assert not mica._deactivate_timer.isActive()


def test_focus_window_restores_material(
    material: Tuple[QWidget, MicaMaterial],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """焦点落在应用内任意窗口（含弹窗/菜单）即恢复，不等主窗口激活。"""
    _widget, mica = material
    calls: list[bool] = []
    monkeypatch.setattr(mica, "set_active", calls.append)
    mica._deactivate_timer.start()

    mica._on_focus_window_changed(object())  # 任意非 None 应用窗口

    assert calls == [True]
    assert not mica._deactivate_timer.isActive()


def test_focus_window_none_starts_debounce(
    material: Tuple[QWidget, MicaMaterial],
) -> None:
    """焦点窗口变空（菜单关闭/窗口切换瞬态）先防抖，不立即淡出。"""
    _widget, mica = material
    mica._deactivate_timer.stop()

    mica._on_focus_window_changed(None)

    assert mica._deactivate_timer.isActive()
    mica._deactivate_timer.stop()


def test_application_active_signal_restores_paused_material(
    material: Tuple[QWidget, MicaMaterial],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应用回到前台：已暂停的材质立即恢复活动态并开始淡入。"""
    _widget, mica = material
    mica._active = False
    mica._paused = True
    mica._fade_alpha = 0.0
    mica._reveal_pending = False
    monkeypatch.setattr(mica, "ensure_layer", lambda: None)

    mica._on_application_state_changed(
        Qt.ApplicationState.ApplicationActive
    )

    assert mica._active is True
    assert mica._paused is False
    assert mica._fade_anim.state() == QAbstractAnimation.State.Running
    mica._fade_anim.stop()


def test_initial_state_follows_inactive_application(
    qapp,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """材质在应用已失活时构造：初始即隐藏，避免先闪一帧 Mica。"""
    monkeypatch.setattr(material_mod, "_application_is_active", lambda: False)
    widget = QWidget()
    mica = MicaMaterial(widget, surface_color="#000000", lazy=True)
    try:
        assert mica._active is False
        assert mica._paused is True
        assert mica._reveal_pending is True
    finally:
        mica.dispose()
        widget.deleteLater()


def test_focus_whitelist_weakref_membership(
    material: Tuple[QWidget, MicaMaterial],
) -> None:
    """白名单存 weakref，查询时必须解引用比较（历史实现恒为 False）。"""
    widget, mica = material
    standalone = QWidget()  # 无 parent：只能通过白名单命中
    try:
        mica.add_focus_whitelist(standalone)
        assert mica._is_in_focus_whitelist(standalone) is True

        mica.remove_focus_whitelist(standalone)
        assert mica._is_in_focus_whitelist(standalone) is False

        # 材质宿主窗口自身及其子控件同样视为“应用内窗口”。
        assert mica._is_in_focus_whitelist(widget) is True
        child = QWidget(widget)
        assert mica._is_in_focus_whitelist(child) is True
        child.deleteLater()
    finally:
        standalone.deleteLater()


class _IdleHost:
    """``MainWindow._on_idle_texture_timeout`` 的最小宿主替身。"""

    _idle_texture_timer: Any = object()

    def __init__(self, app_active: bool) -> None:
        self._app_active = app_active
        self.suspended = False

    def isMinimized(self) -> bool:
        return False

    def _application_is_active(self) -> bool:
        return self._app_active

    def _suspend_background_renderers(self) -> None:
        self.suspended = True


def test_idle_release_only_when_application_inactive(qapp) -> None:
    """应用仍在前台（哪怕焦点在设置窗）时绝不释放 Mica 视口层。"""
    from sopeek.ui.main_window import MainWindow

    active_host = _IdleHost(app_active=True)
    MainWindow._on_idle_texture_timeout(active_host)
    assert active_host.suspended is False

    inactive_host = _IdleHost(app_active=False)
    MainWindow._on_idle_texture_timeout(inactive_host)
    assert inactive_host.suspended is True
