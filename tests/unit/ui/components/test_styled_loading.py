# -*- coding: utf-8 -*-
"""StyledLoading 加载动画组件单元测试。

覆盖范围：
- 构造契约：尺寸 / 变体 / 遮罩样式的合法值与非法值回落、只读属性
- 遮罩底色：dim（半透明黑色压暗）与 opaque（主题表面色实色）的离屏像素取值
- 非遮罩模式回归：固定正方形、不填背景

验证命令：
    python -m pytest tests/unit/ui/components/test_styled_loading.py -q
"""

# targets: ui.components.styled_loading

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

# 组件模块内部使用短路径导入（from theme import tm），要求
# freeassetfilter/ui 位于 sys.path；与 test_styled_basic.py 的 bootstrap 一致。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from theme import tm  # noqa: E402

from freeassetfilter.ui.components.styled_loading import StyledLoading  # noqa: E402

pytestmark = pytest.mark.unit

#: 离屏渲染用的正方形画布边长（远大于 lg 档 32px 圆环，四角必然在遮罩区内）
_CANVAS = 120
#: 取样点：靠近左上角，距圆心约 82px，避开圆环与端帽抗锯齿区
_SAMPLE = (2, 2)


def _render(overlay: StyledLoading) -> QImage:
    """把从属控件离屏渲染到透明底图上。

    顶层控件需 ``WA_TranslucentBackground`` + ``WA_NoSystemBackground``：
    否则 ``render()`` 会把调色板底色填进图像，alpha 恒为 255（实测）。

    Args:
        overlay: 已 ``resize`` 好的被测控件。

    Returns:
        QImage: ARGB32 预乘格式的渲染结果。
    """
    overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    overlay.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    image = QImage(overlay.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    overlay.render(image)
    return image


class TestStyledLoadingContract:
    """构造契约：尺寸 / 变体 / 遮罩样式与只读属性。"""

    def test_defaults(self, qapp: QApplication) -> None:
        """默认构造：default 尺寸、default 变体、非遮罩、dim 遮罩样式。"""
        loading = StyledLoading()
        assert loading.size_variant == "default"
        assert loading.variant == "default"
        assert loading.overlay is False
        assert loading.backdrop == "dim"
        assert loading.sizeHint() == QSize(24, 24)
        loading.deleteLater()

    def test_invalid_enum_values_fall_back(self, qapp: QApplication) -> None:
        """尺寸 / 变体 / 遮罩样式的非法值分别回落默认档。"""
        loading = StyledLoading(size="huge", variant="purple", overlay=True, backdrop="blur")
        assert loading.size_variant == "default"
        assert loading.variant == "default"
        assert loading.backdrop == "dim"
        loading.deleteLater()

    def test_backdrop_opaque_accepted(self, qapp: QApplication) -> None:
        """非法值回落之外，合法值 opaque 原样生效。"""
        loading = StyledLoading(overlay=True, backdrop="opaque")
        assert loading.backdrop == "opaque"
        loading.deleteLater()

    def test_inline_mode_fixed_square(self, qapp: QApplication) -> None:
        """非遮罩模式按尺寸档固定为正方形（lg = 32px）。"""
        loading = StyledLoading(size="lg")
        assert loading.width() == 32
        assert loading.height() == 32
        assert loading.sizeHint() == QSize(32, 32)
        loading.deleteLater()


class TestStyledLoadingBackdrop:
    """遮罩底色：dim 半透明压暗 / opaque 主题表面色实色。"""

    def test_opaque_backdrop_paints_surface_color(self, qapp: QApplication) -> None:
        """opaque：遮罩区被主题表面色不透明铺满。"""
        loading = StyledLoading(size="lg", overlay=True, backdrop="opaque")
        loading.resize(_CANVAS, _CANVAS)
        pixel = _render(loading).pixelColor(*_SAMPLE)

        expected = tm.surface
        assert pixel.alpha() == 255
        assert (pixel.red(), pixel.green(), pixel.blue()) == (
            expected.red(),
            expected.green(),
            expected.blue(),
        )
        loading.deleteLater()

    def test_dim_backdrop_paints_half_transparent_black(self, qapp: QApplication) -> None:
        """dim：遮罩区为 OVERLAY_ALPHA 强度的半透明黑色（默认行为不变）。"""
        loading = StyledLoading(size="lg", overlay=True)
        loading.resize(_CANVAS, _CANVAS)
        pixel = _render(loading).pixelColor(*_SAMPLE)

        assert pixel.alpha() == StyledLoading.OVERLAY_ALPHA
        assert (pixel.red(), pixel.green(), pixel.blue()) == (0, 0, 0)
        loading.deleteLater()

    def test_opaque_backdrop_follows_theme(self, qapp: QApplication) -> None:
        """opaque 底色在绘制期现取：改调色板后同一控件渲染出新的表面色。"""
        loading = StyledLoading(size="lg", overlay=True, backdrop="opaque")
        loading.resize(_CANVAS, _CANVAS)
        before = _render(loading).pixelColor(*_SAMPLE)

        # tm.surface 现取自 gray.g1（深色）/ gray_light.g1（浅色）下的当前主题键
        palette_key = "gray" if tm.is_dark_theme() else "gray_light"
        original = tm._colors[palette_key]["g1"]
        try:
            tm._colors[palette_key]["g1"] = "#123456"
            after = _render(loading).pixelColor(*_SAMPLE)
        finally:
            tm._colors[palette_key]["g1"] = original

        assert (before.red(), before.green(), before.blue()) != (0x12, 0x34, 0x56)
        assert (after.red(), after.green(), after.blue()) == (0x12, 0x34, 0x56)
        loading.deleteLater()


class TestStyledLoadingInlineRegression:
    """非遮罩模式：paintEvent 不填背景，只画圆环。"""

    def test_inline_paints_no_backdrop(self, qapp: QApplication) -> None:
        """角点像素保持全透明（未被任何底色填充）。"""
        loading = StyledLoading(size="sm")
        loading.resize(_CANVAS, _CANVAS)
        pixel = _render(loading).pixelColor(*_SAMPLE)

        assert pixel.alpha() == 0
        loading.deleteLater()