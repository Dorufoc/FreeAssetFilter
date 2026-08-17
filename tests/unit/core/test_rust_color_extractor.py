# -*- coding: utf-8 -*-
"""Rust 颜色提取 DLL ctypes 桥接层单测（tests-comprehensive-refactor todo-9）。

覆盖 ``freeassetfilter.core.native.bridges.rust_color_extractor``：

* 缺失 DLL 时的双模式防护：模块级 importorskip（DLL 不存在则整文件跳过）；
* 三条导入路径（bridges 子模块 / native 包 / bridges 包）解析到同一实例；
* 真实 DLL API 契约：``extract_colors`` / ``extract_colors_from_numpy`` /
  ``rgb_to_lab`` / ``lab_to_rgb`` / ``ciede2000`` / ``get_version``；
* 纯 Python 错误路径：空数据 ValueError、非 numpy 数组 ValueError。

importorskip 语义：模块 import 阶段即检查 ``_BRIDGE.available``，DLL 缺失
时抛 ImportError——本文件顶层 ``pytest.importorskip`` 保证 DLL 缺失环境
下整文件安全跳过且 reason 在线程输出（``-rs``）中可见。
"""

from __future__ import annotations

import importlib
import struct
from typing import Any, List, Tuple

import numpy as np
import pytest
from PySide6.QtCore import QObject

rust_colors = pytest.importorskip(
    "freeassetfilter.core.native.bridges.rust_color_extractor"
)


def _solid_image_data(width: int = 4, height: int = 4, color: Tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """构造 Rust 期望的 8 字节头（宽高）+ RGBA 像素数据。"""
    header: bytes = struct.pack("ii", width, height)
    r, g, b = color
    pixels: bytes = bytes([r, g, b, 255]) * (width * height)
    return header + pixels


# ---------------------------------------------------------------------------
# 导入路径一致性
# ---------------------------------------------------------------------------
class TestImportPaths:
    """三条导入路径解析到同一模块实例。"""

    def test_three_import_paths_align(self) -> None:
        """bridges 子模块 / native 包 / bridges 包为同一对象。"""
        direct = importlib.import_module(
            "freeassetfilter.core.native.bridges.rust_color_extractor"
        )
        native_pkg = importlib.import_module("freeassetfilter.core.native")
        bridges_pkg = importlib.import_module("freeassetfilter.core.native.bridges")
        assert direct is native_pkg.rust_color_extractor
        assert direct is bridges_pkg.rust_color_extractor

    def test_module_has_bridge_singleton(self) -> None:
        """模块级桥接实例可用。"""
        assert rust_colors._BRIDGE is not None
        assert isinstance(rust_colors._BRIDGE.available, bool)
        assert rust_colors._BRIDGE.available is True


# ---------------------------------------------------------------------------
# 版本与可用性
# ---------------------------------------------------------------------------
class TestVersion:
    """``__version__`` / ``_BRIDGE.get_version``。"""

    def test_version_is_non_empty_string(self) -> None:
        """模块版本为非空字符串。"""
        assert isinstance(rust_colors.__version__, str)
        assert len(rust_colors.__version__) > 0

    def test_get_version_matches(self) -> None:
        """桥接版本与模块导出版本一致。"""
        assert rust_colors._BRIDGE.get_version() == rust_colors.__version__


# ---------------------------------------------------------------------------
# extract_colors
# ---------------------------------------------------------------------------
class TestExtractColors:
    """``extract_colors`` 真实 DLL 路径与错误路径。"""

    def test_empty_data_raises_valueerror(self) -> None:
        """空字节抛 ValueError。"""
        with pytest.raises(ValueError):
            rust_colors.extract_colors(b"")

    def test_solid_red_image_extracts_dominant_red(self) -> None:
        """纯红图返回含红色的三元组列表。"""
        colors: List[Tuple[int, int, int]] = rust_colors.extract_colors(
            _solid_image_data(),
            num_colors=5,
            min_distance=75.0,
            max_image_size=150,
        )
        assert len(colors) >= 1
        r, g, b = colors[0]
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
        # 主色应明显偏红（DLL 内部可能做轻微量化）
        assert r >= g and r >= b

    def test_all_entries_are_three_int_tuples(self) -> None:
        """返回结构中每个颜色都是 3 整数元组。"""
        colors = rust_colors.extract_colors(_solid_image_data())
        for item in colors:
            assert isinstance(item, (list, tuple))
            assert len(item) == 3

    def test_larger_num_colors_allowed(self) -> None:
        """请求更多颜色不抛异常。"""
        colors = rust_colors.extract_colors(_solid_image_data(), num_colors=8)
        assert isinstance(colors, list)


# ---------------------------------------------------------------------------
# extract_colors_from_numpy
# ---------------------------------------------------------------------------
class TestExtractColorsFromNumpy:
    """``extract_colors_from_numpy`` numpy 数组入口。"""

    def test_rgb_array_extracts(self) -> None:
        """RGB (H,W,3) 数组可提取颜色。"""
        arr = np.zeros((4, 4, 3), dtype=np.uint8)
        arr[:, :, 0] = 255  # 纯红
        colors = rust_colors.extract_colors_from_numpy(arr, num_colors=5)
        assert isinstance(colors, list)
        assert len(colors) >= 1

    def test_rgba_array_extracts(self) -> None:
        """RGBA (H,W,4) 数组同样可提取。"""
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[:, :, 0] = 255
        arr[:, :, 3] = 255
        colors = rust_colors.extract_colors_from_numpy(arr)
        assert isinstance(colors, list)

    def test_2d_array_raises_valueerror(self) -> None:
        """2 维数组抛 ValueError。"""
        arr = np.zeros((4, 4), dtype=np.uint8)
        with pytest.raises(ValueError):
            rust_colors.extract_colors_from_numpy(arr)

    def test_two_channel_array_raises_valueerror(self) -> None:
        """通道数不为 3/4 抛 ValueError。"""
        arr = np.zeros((4, 4, 2), dtype=np.uint8)
        with pytest.raises(ValueError):
            rust_colors.extract_colors_from_numpy(arr)

    def test_non_numpy_input_raises_valueerror(self) -> None:
        """非 numpy 对象抛 ValueError（AttributeError 转换）。"""
        with pytest.raises(ValueError):
            rust_colors.extract_colors_from_numpy([1, 2, 3])


# ---------------------------------------------------------------------------
# Lab 空间换算
# ---------------------------------------------------------------------------
class TestLabConversions:
    """``rgb_to_lab`` / ``lab_to_rgb`` 色彩空间换算。"""

    def test_rgb_to_lab_returns_three_floats(self) -> None:
        """返回 L,a,b 三个浮点。"""
        l, a, b = rust_colors.rgb_to_lab(255, 0, 0)
        assert isinstance(l, float) and isinstance(a, float) and isinstance(b, float)
        assert 0.0 <= l <= 100.0

    def test_lab_to_rgb_returns_bytes(self) -> None:
        """返回 0-255 整数三元组。"""
        r, g, b = rust_colors.lab_to_rgb(50.0, 0.0, 0.0)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_round_trip_approx(self) -> None:
        """RGB → Lab → RGB 近似还原（允许量化误差）。"""
        r2, g2, b2 = rust_colors.lab_to_rgb(*rust_colors.rgb_to_lab(128, 96, 64))
        assert abs(r2 - 128) <= 3
        assert abs(g2 - 96) <= 3
        assert abs(b2 - 64) <= 3


# ---------------------------------------------------------------------------
# CIEDE2000
# ---------------------------------------------------------------------------
class TestCiede2000:
    """``ciede2000`` 色差计算。"""

    def test_same_color_zero(self) -> None:
        """相同 Lab 值的色差近似为 0。"""
        delta = rust_colors.ciede2000(50.0, 0.0, 0.0, 50.0, 0.0, 0.0)
        assert abs(delta) < 1e-3

    def test_different_color_positive(self) -> None:
        """不同颜色色差为正。"""
        delta = rust_colors.ciede2000(50.0, 10.0, 20.0, 20.0, -10.0, 30.0)
        assert delta > 0


# ---------------------------------------------------------------------------
# 模块 API 表面
# ---------------------------------------------------------------------------
class TestModuleApi:
    """导出符号完整性。"""

    def test_public_functions_exist(self) -> None:
        """关键公开函数均可调用。"""
        for name in (
            "extract_colors",
            "extract_colors_from_numpy",
            "rgb_to_lab",
            "lab_to_rgb",
            "ciede2000",
        ):
            assert callable(getattr(rust_colors, name)), f"{name} missing"


# ---------------------------------------------------------------------------
# ctypes 结构体与桥接器实例
# ---------------------------------------------------------------------------
class TestCtypesStructures:
    """``LabResult`` / ``RgbResult`` 字段布局与 ``RustColorExtractorBridge``。"""

    def test_lab_result_fields(self) -> None:
        """Lab 结构体为三个 c_float 字段。"""
        from ctypes import c_float

        assert [f[0] for f in rust_colors.LabResult._fields_] == ["l", "a", "b"]
        assert [f[1] for f in rust_colors.LabResult._fields_] == [c_float, c_float, c_float]
        lab = rust_colors.LabResult()
        assert lab.l == 0.0 and lab.a == 0.0 and lab.b == 0.0
        lab.l, lab.a, lab.b = 50.0, -10.0, 20.0
        assert (lab.l, lab.a, lab.b) == (50.0, -10.0, 20.0)

    def test_rgb_result_fields(self) -> None:
        """RGB 结构体为三个 c_uint8 字段。"""
        from ctypes import c_uint8

        assert [f[0] for f in rust_colors.RgbResult._fields_] == ["r", "g", "b"]
        assert [f[1] for f in rust_colors.RgbResult._fields_] == [c_uint8, c_uint8, c_uint8]
        rgb = rust_colors.RgbResult()
        assert rgb.r == 0 and rgb.g == 0 and rgb.b == 0
        rgb.r, rgb.g, rgb.b = 255, 128, 0
        assert (rgb.r, rgb.g, rgb.b) == (255, 128, 0)

    def test_bridge_available_property(self) -> None:
        """桥接器可用性为布尔属性（DLL 已由 importorskip 保证）。"""
        bridge = rust_colors.RustColorExtractorBridge()
        assert isinstance(bridge.available, bool)
        assert bridge.available is True
        assert bridge._dll is not None

    def test_bridge_is_instance_methods(self) -> None:
        """桥接器暴露私有加载相关方法供内部使用。"""
        bridge = rust_colors.RustColorExtractorBridge()
        assert callable(bridge._load)
        assert callable(bridge._bind)
        assert callable(bridge._candidate_paths)
        for path in bridge._candidate_paths():
            assert str(path).endswith(".dll")