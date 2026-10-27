# -*- coding: utf-8 -*-
"""RHI 合成预热时机单元测试。

覆盖 ``ui.components.styled_fluid_background.prewarm_top_level_rhi`` 与
``MainWindow`` 的调用时机：顶层窗口只在 QWindow 创建**之前**其层级内已存在
QRhiWidget 时才会选择 RHI 合成后端；晚于建窗再预热，流体背景只能回退 CPU
静态帧（实测控制台仅打印 ``QRhiWidget: No QRhi``）。

验证命令：
    python -m pytest tests/unit/ui/test_rhi_prewarm.py -q
"""

# targets: ui.main_window, ui.components.styled_fluid_background

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget

_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from components import styled_fluid_background as fluid_bg  # noqa: E402
from freeassetfilter.ui import main_window as mw  # noqa: E402

pytestmark = pytest.mark.unit


def test_prewarm_creates_marker_before_window_creation() -> None:
    """未建窗的顶层控件应得到预热标记控件（QRhiWidget 可用时）。"""
    if fluid_bg._FluidGPUShaderWidget is None:  # pragma: no cover - 环境降级
        pytest.skip("QRhiWidget 不可用")

    window = QWidget()
    try:
        assert window.internalWinId() == 0
        warmup = fluid_bg.prewarm_top_level_rhi(window)
        assert warmup is not None
        assert warmup.parent() is window
        assert warmup.isHidden()
    finally:
        window.deleteLater()


def test_prewarm_rejects_already_created_window(qapp: QApplication) -> None:
    """已建窗的顶层控件必须拒绝预热（此时预热无效，只留诊断日志）。"""
    window = QWidget()
    window.show()
    qapp.processEvents()
    try:
        assert window.internalWinId() != 0
        assert fluid_bg.prewarm_top_level_rhi(window) is None
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_main_window_prewarms_before_show(monkeypatch: pytest.MonkeyPatch) -> None:
    """MainWindow 构造期预热时顶层 HWND 必须尚未创建（defer 路径同样如此）。"""
    seen: dict[str, int] = {}

    def _spy(window: QWidget) -> None:
        seen["win_id"] = int(window.internalWinId())
        return None

    monkeypatch.setattr(mw, "prewarm_top_level_rhi", _spy)

    window = mw.MainWindow(defer_heavy_init=True)
    try:
        assert seen.get("win_id") == 0, "RHI 预热发生在建窗之后，流体背景会回退 CPU"
        assert window.internalWinId() == 0
    finally:
        window.deleteLater()


def test_deferred_content_does_not_repeat_prewarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首帧后的完整内容构建不得再次预热（此时窗口已 show，预热必然无效）。"""
    calls: list[int] = []

    def _spy(window: QWidget) -> None:
        calls.append(int(window.internalWinId()))
        return None

    monkeypatch.setattr(mw, "prewarm_top_level_rhi", _spy)

    window = mw.MainWindow(defer_heavy_init=True)
    try:
        assert len(calls) == 1
        window.initialize_deferred_content()
        assert len(calls) == 1, "initialize_deferred_content 不应重复预热"
    finally:
        window.deleteLater()
