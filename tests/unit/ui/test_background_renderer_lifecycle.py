# -*- coding: utf-8 -*-
"""主窗口背景渲染器生命周期单元测试（P7.4 挂起/恢复）。

覆盖 ``MainWindow.changeEvent`` 的激活分支：失焦宽限期到期执行过
``_suspend_background_renderers`` 后，回到前台必须调用
``_resume_background_renderers``。否则流体背景的 ``_renderer`` 仍是
``gpu`` 而 GPU 控件已被销毁，``paintEvent`` 不绘制任何内容，音频页会
残留一块与四周割裂的区域。

验证命令：
    python -m pytest tests/unit/ui/test_background_renderer_lifecycle.py -q
"""

# targets: ui.main_window

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from sopeek.ui.main_window import MainWindow  # noqa: E402

pytestmark = pytest.mark.unit


def _dispatch_activation(window: MainWindow, active: bool) -> None:
    """向窗口派发一次激活状态变化（直接驱动 changeEvent 分支）。"""
    window.changeEvent(QEvent(QEvent.Type.ActivationChange))


def test_activation_resumes_suspended_background(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重新激活时必须恢复流体背景（挂起后回到前台不再空白/残留）。"""
    window = MainWindow()
    try:
        calls: list[str] = []
        monkeypatch.setattr(
            window, "_resume_background_renderers", lambda: calls.append("resume")
        )
        monkeypatch.setattr(
            window, "_cancel_idle_texture_release", lambda: calls.append("cancel")
        )
        monkeypatch.setattr(window, "isActiveWindow", lambda: True)
        monkeypatch.setattr(window, "isMinimized", lambda: False)

        _dispatch_activation(window, True)

        assert "cancel" in calls
        assert "resume" in calls, "激活后未恢复流体背景"
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_deactivation_schedules_idle_release(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失焦时只调度宽限期释放，不立即挂起（快速切窗不闪帧）。"""
    window = MainWindow()
    try:
        calls: list[str] = []
        monkeypatch.setattr(
            window,
            "_schedule_idle_texture_release",
            lambda: calls.append("schedule"),
        )
        monkeypatch.setattr(
            window, "_resume_background_renderers", lambda: calls.append("resume")
        )
        monkeypatch.setattr(window, "isActiveWindow", lambda: False)
        monkeypatch.setattr(window, "isMinimized", lambda: False)
        # 抑制 changeEvent 顶部的文件选择器分支（未构建时自带 None 守卫）
        window._file_selector = None  # noqa: SLF001

        _dispatch_activation(window, False)

        assert calls == ["schedule"]
    finally:
        window.deleteLater()
        qapp.processEvents()
