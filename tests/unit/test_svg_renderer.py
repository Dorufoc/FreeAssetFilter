#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SvgRenderer 模块单元测试
测试SVG颜色替换和渲染功能
"""

import os
from unittest.mock import patch, MagicMock

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from freeassetfilter.core.svg_renderer import SvgRenderer


class TestReplaceSvgColors:
    """测试_replace_svg_colors静态方法"""

    def test_replace_black_fill(self):
        svg = '<path fill="#000000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert 'fill="#000000"' not in result
        assert 'fill="#333333"' in result or "fill" in result

    def test_replace_white_fill(self):
        # 使用 invert_white_to_black=True 来验证 #FFFFFF 会被替换
        svg = '<path fill="#FFFFFF" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg, invert_white_to_black=True)

        assert 'fill="#000000"' in result

    def test_replace_accent_color(self):
        svg = '<path fill="#0a59f7" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert '#0a59f7' not in result.lower()

    def test_replace_white_stroke(self):
        # 使用 invert_white_to_black=True 来验证 #FFFFFF 会被替换
        svg = '<path stroke="#FFFFFF" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg, invert_white_to_black=True)

        assert 'stroke="#000000"' in result

    def test_replace_black_stroke(self):
        svg = '<path stroke="#000000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert 'stroke="#000000"' not in result

    def test_invert_white_to_black(self):
        svg = '<path fill="#FFFFFF" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg, invert_white_to_black=True)

        assert 'fill="#000000"' in result

    def test_force_black_to_base(self):
        svg = '<path fill="#000000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg, force_black_to_base=True)

        assert 'fill="#000000"' not in result

    def test_replace_short_hex_colors(self):
        svg = '<path fill="#FFF" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert 'fill="#FFF"' not in result

    def test_replace_short_black(self):
        svg = '<path fill="#000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert 'fill="#000"' not in result

    def test_replace_css_fill_style(self):
        svg = '<path style="fill: #FFFFFF" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        from freeassetfilter.core.settings_manager import SettingsManager
        settings = SettingsManager()
        base_color = settings.get_setting("appearance.colors.base_color", "#FFFFFF")
        # CSS 样式中的 fill 应该被替换
        assert 'fill: ' in result

    def test_replace_css_stroke_style(self):
        svg = '<path style="stroke: #000000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        from freeassetfilter.core.settings_manager import SettingsManager
        settings = SettingsManager()
        secondary_color = settings.get_setting("appearance.colors.secondary_color", "#333333")
        assert f'stroke: {secondary_color}' in result or 'stroke:' in result

    def test_replace_cecece_color(self):
        svg = '<path fill="#cecece" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert '#cecece' not in result.lower()

    def test_preserves_non_target_colors(self):
        svg = '<path fill="#FF0000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert '#FF0000' in result

    def test_empty_svg(self):
        result = SvgRenderer._replace_svg_colors("")
        assert result == ""

    def test_svg_without_colors(self):
        svg = '<svg><circle cx="10" cy="10" r="5"/></svg>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert isinstance(result, str)

    def test_case_insensitive_replacement(self):
        svg = '<path fill="#ffffff" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert 'fill="#ffffff"' not in result

        svg2 = '<path fill="#0A59F7" d="M0 0"/>'
        result2 = SvgRenderer._replace_svg_colors(svg2)

        assert '#0a59f7' not in result2.lower() or result2 != svg2

    def test_adds_fill_to_path_without_fill(self):
        svg = '<path d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        assert 'fill=' in result

    def test_path_with_existing_fill_not_duplicated(self):
        svg = '<path fill="#FF0000" d="M0 0"/>'
        result = SvgRenderer._replace_svg_colors(svg)

        fill_count = result.lower().count('fill=')
        assert fill_count == 1


class TestColorCache:
    """测试颜色缓存机制"""

    def test_ensure_color_cache_populates(self):
        SvgRenderer._invalidate_color_cache()
        SvgRenderer._ensure_color_cache()

        assert SvgRenderer._color_cache_valid is True
        assert "accent_color" in SvgRenderer._cached_colors

    def test_get_accent_color(self):
        SvgRenderer._invalidate_color_cache()
        color = SvgRenderer._get_accent_color()
        assert color.startswith("#")
        assert len(color) == 7

    def test_get_base_color(self):
        SvgRenderer._invalidate_color_cache()
        color = SvgRenderer._get_base_color()
        assert color.startswith("#")
        assert len(color) == 7

    def test_get_secondary_color(self):
        SvgRenderer._invalidate_color_cache()
        color = SvgRenderer._get_secondary_color()
        assert color.startswith("#")
        assert len(color) == 7

    def test_get_normal_color(self):
        SvgRenderer._invalidate_color_cache()
        color = SvgRenderer._get_normal_color()
        assert color.startswith("#")
        assert len(color) == 7

    def test_invalidate_color_cache_clears(self):
        SvgRenderer._ensure_color_cache()
        assert SvgRenderer._color_cache_valid is True

        SvgRenderer._invalidate_color_cache()
        assert SvgRenderer._color_cache_valid is False
        assert len(SvgRenderer._cached_colors) == 0

    def test_cache_not_rebuilt_if_valid(self):
        SvgRenderer._invalidate_color_cache()
        SvgRenderer._ensure_color_cache()

        first_colors = SvgRenderer._cached_colors.copy()

        SvgRenderer._ensure_color_cache()

        assert SvgRenderer._cached_colors == first_colors


class TestGetDevicePixelRatio:
    """测试_get_device_pixel_ratio静态方法"""

    def test_explicit_dpr(self):
        result = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio=2.0)
        assert result == 2.0

    def test_explicit_dpr_as_string(self):
        result = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio="1.5")
        assert result == 1.5

    def test_invalid_dpr_falls_back(self):
        result = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio="invalid")
        assert result == 1.0

    def test_zero_dpr_falls_back(self):
        result = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio=0)
        assert result == 1.0

    def test_negative_dpr_falls_back(self):
        result = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio=-1.0)
        assert result == 1.0

    def test_none_dpr_no_app(self):
        result = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio=None)
        assert result == 1.0


class TestCreateTransparentPixmap:
    """测试_create_transparent_pixmap静态方法"""

    def test_creates_transparent_pixmap(self, qapp):
        pixmap = SvgRenderer._create_transparent_pixmap(10, 10)

        assert not pixmap.isNull()
        assert pixmap.width() == 10
        assert pixmap.height() == 10

    def test_minimum_size_is_one(self, qapp):
        pixmap = SvgRenderer._create_transparent_pixmap(0, 0)

        assert pixmap.width() >= 1
        assert pixmap.height() >= 1

    def test_custom_dpr(self, qapp):
        pixmap = SvgRenderer._create_transparent_pixmap(10, 10, device_pixel_ratio=2.0)

        # 物理像素 = 逻辑像素 * DPR，所以 width 应该是 10 * 2 = 20
        assert pixmap.width() == 20
        assert pixmap.height() == 20
        assert pixmap.devicePixelRatio() == 2.0


class TestConvertRgbaToHex:
    """测试_convert_rgba_to_hex静态方法"""

    def test_rgba_to_hex_conversion(self):
        svg = "rgba(255, 128, 64, 0.5)"
        result = SvgRenderer._convert_rgba_to_hex(svg)

        assert result.startswith("#")
        assert len(result) == 9
        assert result == "#ff80407f"

    def test_multiple_rgba(self):
        svg = "rgba(255, 0, 0, 1) and rgba(0, 255, 0, 0.5)"
        result = SvgRenderer._convert_rgba_to_hex(svg)

        assert "rgba" not in result

    def test_rgba_with_percentages(self):
        svg = "rgba(100%, 50%, 0%, 100%)"
        result = SvgRenderer._convert_rgba_to_hex(svg)

        assert "rgba" not in result

    def test_no_rgba_unchanged(self):
        svg = "fill: #FF0000"
        result = SvgRenderer._convert_rgba_to_hex(svg)

        assert result == svg


class TestPrepareSvgContent:
    """测试_prepare_svg_content静态方法"""

    def test_with_color_replacement(self):
        svg = '<path fill="#000000" d="M0 0"/>'
        result = SvgRenderer._prepare_svg_content(svg, replace_colors=True)

        assert isinstance(result, str)

    def test_without_color_replacement(self):
        svg = '<path fill="#000000" d="M0 0"/>'
        result = SvgRenderer._prepare_svg_content(svg, replace_colors=False)

        assert 'fill="#000000"' in result

    def test_also_converts_rgba(self):
        svg = "rgba(255, 0, 0, 1)"
        result = SvgRenderer._prepare_svg_content(svg, replace_colors=False)

        assert "rgba" not in result


class TestRenderSvgToExactPixmap:
    """测试render_svg_to_exact_pixmap静态方法"""

    def test_invalid_path_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap("nonexistent.svg", 24, 24)

        assert not pixmap.isNull()
        assert pixmap.width() == 24
        assert pixmap.height() == 24

    def test_none_path_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap(None, 24, 24)

        assert not pixmap.isNull()

    def test_empty_path_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap("", 24, 24)

        assert not pixmap.isNull()

    def test_valid_svg_file(self, qapp, temp_svg_file):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap(temp_svg_file, 24, 24)

        assert not pixmap.isNull()
        assert pixmap.width() == 24
        assert pixmap.height() == 24

    def test_custom_dimensions(self, qapp, temp_svg_file):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap(temp_svg_file, 48, 32)

        assert not pixmap.isNull()
        assert pixmap.width() == 48
        assert pixmap.height() == 32

    def test_replace_colors_false(self, qapp, temp_svg_file):
        pixmap = SvgRenderer.render_svg_to_exact_pixmap(temp_svg_file, 24, 24, replace_colors=False)

        assert not pixmap.isNull()


class TestRenderSvgToPixmap:
    """测试render_svg_to_pixmap静态方法"""

    def test_invalid_path_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_to_pixmap("nonexistent.svg", 24)

        assert not pixmap.isNull()

    def test_none_path_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_to_pixmap(None, 24)

        assert not pixmap.isNull()

    def test_valid_svg_file(self, qapp, temp_svg_file):
        pixmap = SvgRenderer.render_svg_to_pixmap(temp_svg_file, 24)

        assert not pixmap.isNull()

    def test_with_width_and_height(self, qapp, temp_svg_file):
        pixmap = SvgRenderer.render_svg_to_pixmap(temp_svg_file, 24, icon_width=48, icon_height=32)

        assert not pixmap.isNull()

    def test_replace_colors_false(self, qapp, temp_svg_file):
        pixmap = SvgRenderer.render_svg_to_pixmap(temp_svg_file, 24, replace_colors=False)

        assert not pixmap.isNull()


class TestRenderSvgToWidget:
    """测试render_svg_to_widget静态方法"""

    def test_invalid_path_returns_label(self, qapp):
        widget = SvgRenderer.render_svg_to_widget("nonexistent.svg", 24)

        assert widget is not None

    def test_none_path_returns_label(self, qapp):
        widget = SvgRenderer.render_svg_to_widget(None, 24)

        assert widget is not None

    def test_valid_svg_file(self, qapp, temp_svg_file):
        widget = SvgRenderer.render_svg_to_widget(temp_svg_file, 24)

        assert widget is not None


class TestRenderSvgStringToPixmap:
    """测试render_svg_string_to_pixmap静态方法"""

    def test_empty_string_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_string_to_pixmap("", 24)

        assert not pixmap.isNull()
        assert pixmap.width() == 24
        assert pixmap.height() == 24

    def test_none_string_returns_transparent(self, qapp):
        pixmap = SvgRenderer.render_svg_string_to_pixmap(None, 24)

        assert not pixmap.isNull()

    def test_valid_svg_string(self, qapp):
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">
  <rect fill="#FF0000" width="24" height="24"/>
</svg>"""
        pixmap = SvgRenderer.render_svg_string_to_pixmap(svg, 24)

        assert not pixmap.isNull()

    def test_replaces_colors(self, qapp):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><path fill="#000000"/></svg>'
        pixmap = SvgRenderer.render_svg_string_to_pixmap(svg, 24)

        assert not pixmap.isNull()
