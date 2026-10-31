# -*- coding: utf-8 -*-
"""StyledMusicInfoPanel 等比自适应单元测试。

覆盖：封面按参考区域**固定面积占比**缩放、字号/边距随封面等比变化、
父控件 resize 通过事件过滤器驱动重算、真实封面按新尺寸重采样。

验证命令：
    python -m pytest tests/unit/ui/components/test_music_info_panel_scaling.py -q
"""

# targets: ui.components.styled_music_info_panel

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPixmap, QResizeEvent
from PySide6.QtWidgets import QApplication, QWidget

_UI_ROOT: str = str(Path(__file__).resolve().parents[3] / "sopeek" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from sopeek.ui.components.styled_music_info_panel import (  # noqa: E402
    StyledMusicInfoPanel,
)

pytestmark = pytest.mark.unit


def _make_panel(parent: QWidget | None = None) -> StyledMusicInfoPanel:
    """构造面板并注入长短适中的标题，避免空文本影响字体度量。"""
    panel = StyledMusicInfoPanel(parent)
    panel.set_title("残響散歌")
    panel.set_artist("Aimer")
    return panel


def test_cover_scales_with_fixed_area_ratio(qapp: QApplication) -> None:
    """参考区域放大 4 倍面积时，封面边长约放大 2 倍（面积占比恒定）。"""
    panel = _make_panel()
    try:
        panel._apply_reference_size(640, 360)  # noqa: SLF001
        small = panel._cover_px  # noqa: SLF001
        small_ratio = small * small / (640 * 360)

        panel._apply_reference_size(1280, 720)  # noqa: SLF001
        large = panel._cover_px  # noqa: SLF001
        large_ratio = large * large / (1280 * 720)

        assert large > small
        assert abs(large_ratio - small_ratio) < 0.002
        assert abs(large / small - 2.0) < 0.08
    finally:
        panel.deleteLater()
        qapp.processEvents()


def test_fonts_and_margins_scale_with_cover(qapp: QApplication) -> None:
    """字号、封面控件尺寸、面板尺寸全部随封面等比放大。"""
    panel = _make_panel()
    try:
        panel._apply_reference_size(640, 360)  # noqa: SLF001
        small_cover = panel._cover_label.width()  # noqa: SLF001
        small_title = panel._title_label.font().pixelSize()  # noqa: SLF001
        small_artist = panel._artist_label.font().pixelSize()  # noqa: SLF001
        small_panel = panel.width()

        panel._apply_reference_size(1600, 900)  # noqa: SLF001
        large_cover = panel._cover_label.width()  # noqa: SLF001
        large_title = panel._title_label.font().pixelSize()  # noqa: SLF001
        large_artist = panel._artist_label.font().pixelSize()  # noqa: SLF001
        large_panel = panel.width()

        assert large_cover > small_cover
        assert large_title > small_title
        assert large_artist > small_artist
        assert large_panel > small_panel
        # 字号与封面保持固定比值（首尾取整误差 ≤ 1px）
        assert abs(large_title / large_cover - small_title / small_cover) < 0.01
        assert abs(large_artist / large_cover - small_artist / small_cover) < 0.01
    finally:
        panel.deleteLater()
        qapp.processEvents()


def test_parent_resize_triggers_rescale(qapp: QApplication) -> None:
    """父控件（音频区域）resize 时面板自动重算，无需外部手动调用。"""
    parent = QWidget()
    parent.resize(640, 360)
    panel = _make_panel(parent)
    try:
        first = panel._cover_px  # noqa: SLF001
        # 未显示的控件 resize() 不会派发 QResizeEvent；这里显式发送，
        # 模拟真实运行中布局完成后的尺寸变化。
        parent.resize(1280, 720)
        QApplication.sendEvent(
            parent, QResizeEvent(QSize(1280, 720), QSize(640, 360))
        )
        qapp.processEvents()
        second = panel._cover_px  # noqa: SLF001
        assert second > first
    finally:
        panel.deleteLater()
        parent.deleteLater()
        qapp.processEvents()


def test_cover_pixmap_resampled_on_scale(qapp: QApplication) -> None:
    """真实封面在缩放后按新边长重采样（不是被 QLabel 拉伸）。"""
    panel = _make_panel()
    try:
        source = QPixmap(64, 64)
        source.fill(QColor("#cc3355"))
        panel.set_cover_pixmap(source)

        panel._apply_reference_size(640, 360)  # noqa: SLF001
        qapp.processEvents()
        small = panel._cover_label.pixmap()  # noqa: SLF001

        panel._apply_reference_size(1600, 900)  # noqa: SLF001
        qapp.processEvents()
        large = panel._cover_label.pixmap()  # noqa: SLF001

        assert not small.isNull() and not large.isNull()
        assert large.width() > small.width()
    finally:
        panel.deleteLater()
        qapp.processEvents()
