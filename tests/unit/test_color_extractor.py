#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ColorExtractor 模块单元测试
测试颜色提取、距离计算和图像处理功能
"""

import struct
import os
from unittest.mock import patch, MagicMock
from io import BytesIO

import pytest
from PIL import Image

from freeassetfilter.core.color_extractor import (
    extract_cover_colors,
    _extract_cover_colors_python,
    _prepare_image_data_for_rust,
    _is_valid_color,
    _is_color_different,
    color_distance,
    rgb_to_hex,
    hex_to_qcolor,
    sort_colors_by_brightness,
    adjust_colors_for_gradient,
    generate_colors_from_accent,
    is_rust_available,
)
from PySide6.QtGui import QColor


class TestPrepareImageDataForRust:
    """测试_prepare_image_data_for_rust函数"""

    def test_valid_png_data(self, sample_image_data):
        result = _prepare_image_data_for_rust(sample_image_data)
        width, height = struct.unpack('ii', result[:8])
        assert width == 100
        assert height == 100
        assert len(result) == 8 + (width * height * 4)

    def test_invalid_data_raises(self):
        with pytest.raises(ValueError, match="图像解码失败"):
            _prepare_image_data_for_rust(b"not an image")

    def test_corrupted_image_raises(self):
        with pytest.raises(ValueError, match="图像解码失败"):
            _prepare_image_data_for_rust(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    def test_format_conversion(self):
        img = Image.new("RGBA", (5, 5), (255, 0, 0, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        result = _prepare_image_data_for_rust(png_data)
        width, height = struct.unpack('ii', result[:8])
        assert width == 5
        assert height == 5

    def test_rgb_to_rgba_conversion(self):
        img = Image.new("RGB", (3, 3), (0, 255, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        result = _prepare_image_data_for_rust(png_data)
        assert len(result) == 8 + (3 * 3 * 4)


class TestExtractCoverColors:
    """测试extract_cover_colors函数"""

    def test_empty_data_returns_empty_list(self):
        result = extract_cover_colors(b"")
        assert result == []

    def test_none_data_returns_empty_list(self):
        result = extract_cover_colors(None)
        assert result == []

    def test_valid_image_returns_colors(self, sample_image_data):
        result = extract_cover_colors(sample_image_data, num_colors=1)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(c, QColor) for c in result)

    def test_num_colors_parameter(self, sample_image_data):
        from freeassetfilter.core.color_extractor import is_rust_available
        if is_rust_available():
            result = extract_cover_colors(sample_image_data, num_colors=5)
            assert len(result) >= 1
        else:
            result = extract_cover_colors(sample_image_data, num_colors=3)
            assert len(result) == 3

    def test_returns_qcolor_objects(self, sample_image_data):
        result = extract_cover_colors(sample_image_data, num_colors=1)
        assert isinstance(result[0], QColor)


class TestExtractCoverColorsPython:
    """测试_extract_cover_colors_python函数"""

    def test_empty_data_returns_empty_list(self):
        result = _extract_cover_colors_python(b"")
        assert result == []

    def test_invalid_data_returns_empty_list(self):
        result = _extract_cover_colors_python(b"not an image")
        assert result == []

    def test_single_color_image(self):
        img = Image.new("RGB", (10, 10), (128, 64, 32))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        result = _extract_cover_colors_python(png_data, num_colors=1)
        assert len(result) == 1
        assert result[0].red() == 128
        assert result[0].green() == 64
        assert result[0].blue() == 32

    def test_multiple_colors(self):
        img = Image.new("RGB", (100, 100))
        pixels = []
        for y in range(100):
            for x in range(100):
                if x < 33:
                    pixels.append((255, 0, 0))
                elif x < 66:
                    pixels.append((0, 255, 0))
                else:
                    pixels.append((0, 0, 255))
        img.putdata(pixels)

        buf = BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        result = _extract_cover_colors_python(png_data, num_colors=3)
        assert len(result) == 3

    def test_filters_extreme_colors(self):
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        result = _extract_cover_colors_python(png_data, num_colors=1)
        gray_count = sum(1 for c in result if c.red() == 128 and c.green() == 128 and c.blue() == 128)
        assert gray_count <= 1

    def test_fills_with_gray_when_not_enough(self):
        img = Image.new("RGB", (10, 10), (100, 100, 100))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_data = buf.getvalue()

        result = _extract_cover_colors_python(png_data, num_colors=5)
        assert len(result) == 5

        gray_count = sum(1 for c in result if c.red() == 128 and c.green() == 128 and c.blue() == 128)
        assert gray_count <= 5


class TestIsValidColor:
    """测试_is_valid_color函数"""

    def test_valid_color(self):
        color = QColor(128, 128, 128)
        assert _is_valid_color(color) is True

    def test_black_color(self):
        color = QColor(0, 0, 0)
        assert _is_valid_color(color) is False

    def test_white_color(self):
        color = QColor(255, 255, 255)
        assert _is_valid_color(color) is False

    def test_near_white(self):
        color = QColor(251, 251, 251)
        assert _is_valid_color(color) is False

    def test_near_black(self):
        color = QColor(10, 10, 10)
        assert _is_valid_color(color) is False

    def test_boundary_low(self):
        color = QColor(16, 16, 16)
        assert _is_valid_color(color) is False

    def test_boundary_high(self):
        color = QColor(230, 230, 230)
        assert _is_valid_color(color) is True

    def test_mixed_valid(self):
        color = QColor(100, 200, 50)
        assert _is_valid_color(color) is True


class TestColorDistance:
    """测试color_distance函数"""

    def test_same_color_distance_zero(self):
        c1 = QColor(100, 150, 200)
        c2 = QColor(100, 150, 200)
        assert color_distance(c1, c2) == 0.0

    def test_max_distance(self):
        black = QColor(0, 0, 0)
        white = QColor(255, 255, 255)
        expected = (255**2 + 255**2 + 255**2) ** 0.5
        assert abs(color_distance(black, white) - expected) < 0.001

    def test_primary_color_distances(self):
        red = QColor(255, 0, 0)
        green = QColor(0, 255, 0)
        blue = QColor(0, 0, 255)

        expected_rg = (255**2 + 255**2) ** 0.5
        assert abs(color_distance(red, green) - expected_rg) < 0.001
        assert abs(color_distance(red, blue) - expected_rg) < 0.001
        assert abs(color_distance(green, blue) - expected_rg) < 0.001

    def test_euclidean_formula(self):
        c1 = QColor(10, 20, 30)
        c2 = QColor(40, 50, 60)

        dr = 10 - 40
        dg = 20 - 50
        db = 30 - 60
        expected = (dr*dr + dg*dg + db*db) ** 0.5

        assert abs(color_distance(c1, c2) - expected) < 0.001


class TestIsColorDifferent:
    """测试_is_color_different函数"""

    def test_no_existing_colors(self):
        color = QColor(100, 100, 100)
        assert _is_color_different(color, [], 50.0) is True

    def test_different_enough(self):
        new_color = QColor(255, 0, 0)
        existing = [QColor(0, 0, 255)]
        assert _is_color_different(new_color, existing, 50.0) is True

    def test_too_similar(self):
        new_color = QColor(100, 100, 100)
        existing = [QColor(101, 101, 101)]
        assert _is_color_different(new_color, existing, 50.0) is False

    def test_multiple_existing_all_different(self):
        new_color = QColor(200, 200, 200)
        existing = [QColor(0, 0, 0), QColor(255, 0, 0), QColor(0, 255, 0)]
        assert _is_color_different(new_color, existing, 50.0) is True

    def test_multiple_existing_one_similar(self):
        new_color = QColor(100, 100, 100)
        existing = [QColor(0, 0, 0), QColor(101, 101, 101), QColor(255, 255, 255)]
        assert _is_color_different(new_color, existing, 50.0) is False


class TestRgbToHex:
    """测试rgb_to_hex函数"""

    def test_black(self):
        assert rgb_to_hex(QColor(0, 0, 0)) == "#000000"

    def test_white(self):
        assert rgb_to_hex(QColor(255, 255, 255)) == "#ffffff"

    def test_red(self):
        assert rgb_to_hex(QColor(255, 0, 0)) == "#ff0000"

    def test_custom_color(self):
        assert rgb_to_hex(QColor(128, 64, 32)) == "#804020"

    def test_hex_format(self):
        result = rgb_to_hex(QColor(10, 20, 30))
        assert result.startswith("#")
        assert len(result) == 7


class TestHexToQcolor:
    """测试hex_to_qcolor函数"""

    def test_valid_hex(self):
        color = hex_to_qcolor("#ff0000")
        assert color is not None
        assert color.red() == 255
        assert color.green() == 0
        assert color.blue() == 0

    def test_missing_hash(self):
        assert hex_to_qcolor("ff0000") is None

    def test_wrong_length(self):
        assert hex_to_qcolor("#ff00") is None

    def test_invalid_chars(self):
        assert hex_to_qcolor("#GGGGGG") is None

    def test_valid_hex_black(self):
        color = hex_to_qcolor("#000000")
        assert color is not None
        assert color.red() == 0

    def test_valid_hex_white(self):
        color = hex_to_qcolor("#ffffff")
        assert color is not None
        assert color.red() == 255


class TestSortColorsByBrightness:
    """测试sort_colors_by_brightness函数"""

    def test_sort_ascending(self):
        colors = [
            QColor(200, 200, 200),
            QColor(50, 50, 50),
            QColor(128, 128, 128),
        ]
        sorted_colors = sort_colors_by_brightness(colors, ascending=True)

        assert sorted_colors[0].red() == 50
        assert sorted_colors[1].red() == 128
        assert sorted_colors[2].red() == 200

    def test_sort_descending(self):
        colors = [
            QColor(50, 50, 50),
            QColor(200, 200, 200),
            QColor(128, 128, 128),
        ]
        sorted_colors = sort_colors_by_brightness(colors, ascending=False)

        assert sorted_colors[0].red() == 200
        assert sorted_colors[1].red() == 128
        assert sorted_colors[2].red() == 50

    def test_empty_list(self):
        assert sort_colors_by_brightness([]) == []

    def test_single_color(self):
        colors = [QColor(100, 100, 100)]
        assert sort_colors_by_brightness(colors) == colors

    def test_same_brightness(self):
        colors = [QColor(100, 100, 100), QColor(100, 100, 100)]
        result = sort_colors_by_brightness(colors)
        assert len(result) == 2


class TestAdjustColorsForGradient:
    """测试adjust_colors_for_gradient函数"""

    def test_less_than_five_colors(self):
        colors = [QColor(100, 100, 100), QColor(150, 150, 150)]
        result = adjust_colors_for_gradient(colors)
        assert result == colors

    def test_five_colors(self):
        colors = [
            QColor(50, 50, 50),
            QColor(100, 100, 100),
            QColor(150, 150, 150),
            QColor(200, 200, 200),
            QColor(250, 250, 250),
        ]
        result = adjust_colors_for_gradient(colors)
        assert len(result) == 5

    def test_more_than_five_colors(self):
        colors = [QColor(i * 20, i * 20, i * 20) for i in range(1, 11)]
        result = adjust_colors_for_gradient(colors)
        assert len(result) == 5


class TestGenerateColorsFromAccent:
    """测试generate_colors_from_accent函数"""

    def test_default_accent(self):
        colors = generate_colors_from_accent()
        assert len(colors) == 5
        assert all(isinstance(c, QColor) for c in colors)

    def test_custom_accent(self):
        colors = generate_colors_from_accent("#FF0000")
        assert len(colors) == 5

        first_color = colors[0]
        assert first_color.red() == 255
        assert first_color.green() == 0
        assert first_color.blue() == 0

    def test_invalid_hex_uses_default(self):
        colors = generate_colors_from_accent("not-a-color")
        assert len(colors) == 5

    def test_empty_string_uses_default(self):
        colors = generate_colors_from_accent("")
        assert len(colors) == 5

    def test_colors_have_variation(self):
        colors = generate_colors_from_accent("#B036EE")
        unique_colors = set()
        for c in colors:
            unique_colors.add((c.red(), c.green(), c.blue()))
        assert len(unique_colors) > 1


class TestIsRustAvailable:
    """测试is_rust_available函数"""

    def test_returns_bool(self):
        result = is_rust_available()
        assert isinstance(result, bool)
