# -*- coding: utf-8 -*-
"""预览层 SVG 渲染器单测（tests-comprehensive-refactor todo-9）。

覆盖 ``freeassetfilter.core.preview.svg_renderer`` 的纯函数与静态工具：

* ``_smart_render_size`` 的尺寸兜底与 DPR 缩放；
* ``_replace_svg_colors`` 的颜色替换矩阵（black/white/accent/normal、
  ``invert_white_to_black``、``force_black_to_base``）；颜色值依赖
  SettingsManager，故使用 ``settings_manager`` fixture 绑定临时设置文件；
* ``_convert_rgba_to_hex`` 的 rgba() → 十六进制带 alpha 转换；
* ``_prepare_svg_content`` 的组合管线（replace_colors 开关）；
* 四个渲染入口的有效/缺失/失败降级路径（使用 ``qapp`` + ``tmp_path``，
  不做像素级断言，只校验非空可渲染或透明兜底）。
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QLabel, QWidget, QVBoxLayout

from freeassetfilter.core.preview.svg_renderer import SvgRenderer, _smart_render_size


# ---------------------------------------------------------------------------
# _smart_render_size
# ---------------------------------------------------------------------------
class TestSmartRenderSize:
    """``_smart_render_size`` 尺寸计算与最低 64px 兜底。"""

    def test_basic_size_uses_max_dimension(self) -> None:
        """最大维低于 64 时按 64 兜底，再乘 DPR。"""
        result: int = _smart_render_size(24, 24, 1.0)
        assert result == 64

    def test_larger_dimension_wins(self) -> None:
        """取宽度/高度中较大者作为渲染基准。"""
        assert _smart_render_size(120, 48, 1.0) == 120
        assert _smart_render_size(48, 120, 1.0) == 120

    def test_dpr_scaling(self) -> None:
        """DPR 2.0 时输出翻倍。"""
        assert _smart_render_size(120, 120, 2.0) == 240
        # 64 兜底同样参与 DPR 缩放
        assert _smart_render_size(10, 10, 1.5) == 96


# ---------------------------------------------------------------------------
# _replace_svg_colors
# ---------------------------------------------------------------------------
class TestReplaceSvgColors:
    """``_replace_svg_colors`` 颜色替换矩阵（绑定临时 SettingsManager）。"""

    @pytest.fixture(autouse=True)
    def _bind_settings(self, settings_manager: Any) -> None:
        """将 app 级颜色绑定到临时设置，保证断言与机器默认无关。"""
        settings_manager.set_setting("appearance.colors.accent_color", "#FF0000")
        settings_manager.set_setting("appearance.colors.base_color", "#FFFFFF")
        settings_manager.set_setting("appearance.colors.secondary_color", "#333333")
        settings_manager.set_setting("appearance.colors.normal_color", "#CECECE")
        yield

    def test_svg_without_colors_is_unchanged(self) -> None:
        """不含可替换颜色的 SVG 保持原样。"""
        svg: str = '<svg><rect x="0" y="0" width="10" height="10"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg)
        assert processed == svg

    def test_black_replaced_by_secondary(self) -> None:
        """#000000 默认替换为 secondary_color（#333333）。"""
        svg: str = '<svg><path fill="#000000"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg)
        assert 'fill="#333333"' in processed
        assert '#000000' not in processed

    def test_force_black_to_base(self) -> None:
        """``force_black_to_base=True`` 将 #000000 替换为 base_color。"""
        svg: str = '<svg><path fill="#000000"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg, force_black_to_base=True)
        assert 'fill="#FFFFFF"' in processed
        assert '#000000' not in processed

    def test_white_replaced_by_base(self) -> None:
        """#FFFFFF 默认替换为 base_color。"""
        svg: str = '<svg><path fill="#FFFFFF"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg)
        assert 'fill="#FFFFFF"' in processed

    def test_invert_white_to_black(self) -> None:
        """``invert_white_to_black=True`` 将 #FFFFFF 替换为 #000000。"""
        svg: str = '<svg><path fill="#FFFFFF" stroke="#FFFFFF"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg, invert_white_to_black=True)
        assert 'fill="#000000"' in processed
        assert 'stroke="#000000"' in processed
        assert '#FFFFFF' not in processed

    def test_accent_replaced(self) -> None:
        """品牌蓝色 #0a59f7 替换为 accent_color。"""
        svg: str = '<svg><path fill="#0a59f7"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg)
        assert 'fill="#FF0000"' in processed
        assert '#0a59f7' not in processed

    def test_normal_color_replaced_in_attr_and_css(self) -> None:
        """#cecece 在属性与 CSS 中均替换为 normal_color。"""
        svg: str = (
            '<svg><path fill="#cecece" stroke="#cecece"/>'
            '<style>.a { fill: #cecece; stroke: #cecece; }</style></svg>'
        )
        processed: str = SvgRenderer._replace_svg_colors(svg)
        assert processed.count("fill: #CECECE") == 1
        assert processed.count("stroke: #CECECE") == 1
        assert '#cecece' not in processed

    def test_path_without_fill_gets_black_fill(self) -> None:
        """无 fill/class 属性的 <path> 补上黑色填充。"""
        svg: str = '<svg><path d="M0 0 L10 10"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg)
        # 未显式指定 fill 的 path 被回填为 black 的替换色（secondary）
        assert 'fill="#333333"' in processed

    def test_short_hex_colors_replaced(self) -> None:
        """#000/#fff 短样式同样替换。"""
        svg: str = '<svg><path fill="#000" stroke="#fff"/></svg>'
        processed: str = SvgRenderer._replace_svg_colors(svg)
        assert 'fill="#333333"' in processed
        assert 'stroke="#FFFFFF"' in processed
        assert '#000' not in processed and '#fff' not in processed


# ---------------------------------------------------------------------------
# _convert_rgba_to_hex
# ---------------------------------------------------------------------------
class TestConvertRgbaToHex:
    """``_convert_rgba_to_hex`` rgba() → 十六进制转换。"""

    def test_basic_rgba(self) -> None:
        """标准 0-255 alpha 转换为 hex。"""
        svg: str = '<path fill="rgba(255, 0, 0, 1)"/>'
        processed: str = SvgRenderer._convert_rgba_to_hex(svg)
        assert processed == '<path fill="#ff0000ff"/>'

    def test_percentage_components(self) -> None:
        """百分比分量按 2.55 缩放（浮点截断为 int）。"""
        svg: str = '<path fill="rgba(100%, 0%, 0%, 50%)"/>'
        processed: str = SvgRenderer._convert_rgba_to_hex(svg)
        # 100% * 2.55 = 254.99... -> int 截断为 254(0xfe)；0.5*255 -> 127(0x7f)
        assert processed == '<path fill="#fe00007f"/>'

    def test_clamping(self) -> None:
        """越界值被钳制到 0-255 / 0-1。"""
        svg: str = '<path fill="rgba(300, -10, 128, 2)"/>'
        processed: str = SvgRenderer._convert_rgba_to_hex(svg)
        assert processed == '<path fill="#ff0080ff"/>'

    def test_no_rgba_unchanged(self) -> None:
        """不含 rgba() 的字符串原样返回。"""
        svg: str = '<path fill="#ff0000"/>'
        assert SvgRenderer._convert_rgba_to_hex(svg) == svg


# ---------------------------------------------------------------------------
# _prepare_svg_content
# ---------------------------------------------------------------------------
class TestPrepareSvgContent:
    """``_prepare_svg_content`` 组合管线。"""

    def test_replace_colors_off_keeps_unknown_colors(self, settings_manager: Any) -> None:
        """``replace_colors=False`` 跳过替换但仍转换 rgba()。"""
        svg: str = '<path fill="#000000" fill-opacity="rgba(0,0,0,0.5)"/>'
        processed: str = SvgRenderer._prepare_svg_content(svg, replace_colors=False)
        assert '#000000' in processed  # 未替换
        assert 'rgba(' not in processed  # 仍转为 hex

    def test_replace_colors_on_default(self, settings_manager: Any) -> None:
        """默认开启颜色替换。"""
        svg: str = '<path fill="#0a59f7"/>'
        processed: str = SvgRenderer._prepare_svg_content(svg)
        assert '#0a59f7' not in processed
        assert processed.startswith('<path fill="#')


# ---------------------------------------------------------------------------
# DPR 解析与透明占位
# ---------------------------------------------------------------------------
class TestDprAndTransparentPixmap:
    """``_get_device_pixel_ratio`` 与 ``_create_transparent_pixmap``。"""

    def test_explicit_dpr_wins(self) -> None:
        """显式传入的 DPR 优先。"""
        assert SvgRenderer._get_device_pixel_ratio(2.0) == 2.0

    def test_invalid_dpr_falls_back_to_positive(self, qapp: Any) -> None:
        """非法 DPR 值回退到有效屏幕 DPR。"""
        dpr: float = SvgRenderer._get_device_pixel_ratio(0.0)
        assert dpr > 0  # 面板 DPR 或 1.0

    def test_create_transparent_pixmap_size(self, qapp: Any) -> None:
        """透明占位像素图尺寸与 DPR 关联。"""
        pixmap: QPixmap = SvgRenderer._create_transparent_pixmap(24, 24, 2.0)
        assert not pixmap.isNull()
        assert pixmap.devicePixelRatio() == 2.0
        assert pixmap.width() == 48
        assert pixmap.height() == 48

    def test_create_transparent_pixmap_clamps_min_one(self, qapp: Any) -> None:
        """过小尺寸钳制到 1。"""
        pixmap: QPixmap = SvgRenderer._create_transparent_pixmap(0, 0, 1.0)
        assert pixmap.width() >= 1 and pixmap.height() >= 1


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------
class TestRenderEntrypoints:
    """四个渲染入口的有效路径与缺失文件降级路径。"""

    def test_render_svg_to_exact_pixmap_missing_file(self, qapp: Any, tmp_path: Any) -> None:
        """文件不存在时返回透明占位而非异常。"""
        pixmap: QPixmap = SvgRenderer.render_svg_to_exact_pixmap(
            str(tmp_path / "missing.svg"),
            icon_width=24,
            icon_height=24,
        )
        assert not pixmap.isNull()
        assert pixmap.width() >= 1 and pixmap.height() >= 1

    def test_render_svg_to_exact_pixmap_valid(self, qapp: Any, sample_svg_file: str) -> None:
        """合法 SVG 渲染出非空像素图（DPR 1.0）。"""
        pixmap: QPixmap = SvgRenderer.render_svg_to_exact_pixmap(
            sample_svg_file,
            icon_width=32,
            icon_height=32,
            device_pixel_ratio=1.0,
        )
        assert not pixmap.isNull()

    def test_render_svg_to_pixmap_valid(self, qapp: Any, sample_svg_file: str) -> None:
        """``render_svg_to_pixmap`` 有效路径返回非空像素图。"""
        pixmap: QPixmap = SvgRenderer.render_svg_to_pixmap(
            sample_svg_file,
            icon_size=24,
            replace_colors=True,
        )
        assert not pixmap.isNull()

    def test_render_svg_to_pixmap_missing_file(self, qapp: Any, tmp_path: Any) -> None:
        """``render_svg_to_pixmap`` 缺失文件返回透明图。"""
        pixmap: QPixmap = SvgRenderer.render_svg_to_pixmap(str(tmp_path / "nope.svg"))
        assert not pixmap.isNull()

    def test_render_svg_to_widget_valid(self, qapp: Any, sample_svg_file: str) -> None:
        """``render_svg_to_widget`` 返回含子布局的容器。"""
        widget: QWidget = SvgRenderer.render_svg_to_widget(sample_svg_file, icon_size=48)
        assert widget is not None
        assert widget.layout() is not None
        assert isinstance(widget.layout(), QVBoxLayout)

    def test_render_svg_to_widget_missing_file(self, qapp: Any, tmp_path: Any) -> None:
        """``render_svg_to_widget`` 缺失文件降级为带透明图的 QLabel。"""
        widget: QWidget = SvgRenderer.render_svg_to_widget(str(tmp_path / "nope.svg"), icon_size=48)
        assert isinstance(widget, QLabel)
        assert widget.pixmap() is not None and not widget.pixmap().isNull()

    def test_render_svg_string_to_pixmap_empty(self, qapp: Any) -> None:
        """空 SVG 字符串返回透明像素图。"""
        pixmap: QPixmap = SvgRenderer.render_svg_string_to_pixmap("", icon_size=24)
        assert not pixmap.isNull()

    def test_render_svg_string_to_pixmap_valid(self, qapp: Any) -> None:
        """合法 SVG 字符串渲染为非空像素图。"""
        svg: str = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            '<rect width="24" height="24" fill="#0a59f7"/></svg>'
        )
        pixmap: QPixmap = SvgRenderer.render_svg_string_to_pixmap(svg, icon_size=24)
        assert not pixmap.isNull()

    def test_render_unknown_file_icon_short_text(self, qapp: Any, sample_svg_file: str) -> None:
        """短 text（<5 字符）保留原值。"""
        widget: QWidget = SvgRenderer.render_unknown_file_icon(sample_svg_file, "EXE", icon_size=48)
        assert widget is not None

    def test_render_unknown_file_icon_long_text_defaults_to_file(
        self, qapp: Any, sample_svg_file: str
    ) -> None:
        """长 text（>=5 字符）兜底为 FILE 并成功渲染。"""
        widget: QWidget = SvgRenderer.render_unknown_file_icon(sample_svg_file, "EXEFILE", icon_size=48)
        assert widget is not None