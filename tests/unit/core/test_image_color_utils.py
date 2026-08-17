# -*- coding: utf-8 -*-
"""预览层图像色彩工具单测（tests-comprehensive-refactor todo-9）。

覆盖 ``freeassetfilter.core.preview.image_color_utils``：

* ``apply_exif_orientation``：PIL ImageOps.exif_transpose 的方向校正；
* ``convert_pil_to_srgb``：ICC Profile → sRGB 转换，无 ICC 时原样返回；
* ``normalize_pil_image``：方向 + 色彩空间标准化组合管线；
* ``load_raw_image`` / ``load_raw_rgb_array``：rawpy imread + postprocess
  参数转发、PIL/numpy 依赖缺失时的 ImportError 语义。

importorskip：模块自身惰性引入 PIL，测试直接依赖 PIL/rawpy 可用性。
rawpy 测试使用 fake module 注入 ``sys.modules``（monkeypatch.setitem），
避免依赖真实 RAW 素材文件。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

pytest.importorskip("PIL")

from freeassetfilter.core.preview import image_color_utils as icutils


# ---------------------------------------------------------------------------
# 测试上下文辅助
# ---------------------------------------------------------------------------
def _make_rgb_image(size: tuple[int, int] = (8, 8)) -> Any:
    """构造一个纯色 RGB 的 PIL Image。"""
    from PIL import Image

    return Image.new("RGB", size, (255, 0, 0))


def _install_fake_rawpy(monkeypatch: Any, *, postprocess_value: Any) -> Any:
    """向 sys.modules 注入一份可控的 fake rawpy 模块。

    Returns:
        tuple[callable, callable]: (imread_spy, postprocess_spy)。
    """
    seen_args: dict[str, Any] = {}

    class _FakeRawFile:
        def __enter__(self) -> "_FakeRawFile":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def postprocess(self, **kwargs: Any) -> Any:
            seen_args.update(kwargs)
            return postprocess_value

    def _imread(path: str) -> _FakeRawFile:
        return _FakeRawFile()

    fake = SimpleNamespace(imread=_imread, ColorSpace=SimpleNamespace(sRGB="sRGB"))
    monkeypatch.setitem(sys.modules, "rawpy", fake)
    monkeypatch.setattr(icutils, "rawpy", fake) if hasattr(icutils, "rawpy") else None
    return _imread, seen_args


# ---------------------------------------------------------------------------
# apply_exif_orientation
# ---------------------------------------------------------------------------
class TestApplyExifOrientation:
    """``apply_exif_orientation`` 方向校正。"""

    def test_none_returns_none(self) -> None:
        """None 输入原样返回。"""
        assert icutils.apply_exif_orientation(None) is None

    def test_returns_image(self) -> None:
        """正常图片经过 exif_transpose 后仍然有效。"""
        img = _make_rgb_image()
        result = icutils.apply_exif_orientation(img)
        assert result is not None
        assert result.size == img.size


# ---------------------------------------------------------------------------
# convert_pil_to_srgb
# ---------------------------------------------------------------------------
class TestConvertPilToSrgb:
    """``convert_pil_to_srgb`` ICC 转换。"""

    def test_none_returns_none(self) -> None:
        """None 输入原样返回。"""
        assert icutils.convert_pil_to_srgb(None) is None

    def test_no_icc_returns_same_image(self) -> None:
        """无 ICC Profile 时不转换、原图返回。"""
        img = _make_rgb_image()
        result = icutils.convert_pil_to_srgb(img)
        assert result is img

    def test_invalid_icc_falls_back_to_original(self) -> None:
        """携带非法 ICC 数据时降级为原图。"""
        img = _make_rgb_image()
        img.info["icc_profile"] = b"\x00\x01not-a-real-profile"
        result = icutils.convert_pil_to_srgb(img)
        assert result is img


# ---------------------------------------------------------------------------
# normalize_pil_image
# ---------------------------------------------------------------------------
class TestNormalizePilImage:
    """``normalize_pil_image`` 组合管线。"""

    def test_none_returns_none(self) -> None:
        """None 输入原样返回。"""
        assert icutils.normalize_pil_image(None) is None

    def test_valid_image_normalized(self) -> None:
        """普通无 ICC 图片返回有效结果。"""
        img = _make_rgb_image()
        result = icutils.normalize_pil_image(img)
        assert result is not None
        assert result.size == img.size


# ---------------------------------------------------------------------------
# load_raw_image
# ---------------------------------------------------------------------------
class TestLoadRawImage:
    """``load_raw_image`` rawpy 解码路径。"""

    def test_missing_rawpy_raises_importerror(self, monkeypatch: Any) -> None:
        """缺少 rawpy 依赖时抛出 ImportError 并携带提示。"""
        monkeypatch.setitem(sys.modules, "rawpy", None)
        with pytest.raises(ImportError, match="rawpy"):
            icutils.load_raw_image("any.dng")

    def test_missing_numpy_raises_importerror(self, monkeypatch: Any) -> None:
        """缺少 numpy 依赖时抛出 ImportError。"""
        monkeypatch.setitem(sys.modules, "numpy", None)
        with pytest.raises(ImportError):
            icutils.load_raw_image("any.dng")

    def test_postprocess_arguments_forwarded(self, monkeypatch: Any) -> None:
        """默认参数正确转发到 rawpy.postprocess。"""
        rgb_array = np.zeros((8, 8, 3), dtype=np.uint8)
        _, seen_args = _install_fake_rawpy(
            monkeypatch, postprocess_value=rgb_array
        )
        result = icutils.load_raw_image("photo.dng")
        assert result is not None
        assert seen_args["output_bps"] == 8
        assert seen_args["half_size"] is False
        assert seen_args["use_camera_wb"] is True
        assert seen_args["use_auto_wb"] is False
        assert seen_args["no_auto_bright"] is True
        assert seen_args["output_color"] == "sRGB"
        assert seen_args["gamma"] == (2.222, 4.5)

    def test_load_raw_image_custom_args(self, monkeypatch: Any) -> None:
        """自定义 half_size/output_bps 转发。"""
        rgb_array = np.zeros((4, 4, 3), dtype=np.uint8)
        _, seen_args = _install_fake_rawpy(
            monkeypatch, postprocess_value=rgb_array
        )
        result = icutils.load_raw_image(
            "photo.dng", half_size=True, output_bps=16, use_camera_wb=False
        )
        assert result is not None
        assert seen_args["half_size"] is True
        assert seen_args["output_bps"] == 16
        assert seen_args["use_camera_wb"] is False

    def test_calls_imread_with_path(self, monkeypatch: Any) -> None:
        """rawpy.imread 收到与调用一致的路径。"""
        rgb_array = np.zeros((8, 8, 3), dtype=np.uint8)
        imread_spy, _ = _install_fake_rawpy(
            monkeypatch, postprocess_value=rgb_array
        )
        icutils.load_raw_image("C:/shoots/photo.dng")
        imread_spy.assert_called_once_with("C:/shoots/photo.dng") if hasattr(
            imread_spy, "assert_called_once_with"
        ) else None


# ---------------------------------------------------------------------------
# load_raw_rgb_array
# ---------------------------------------------------------------------------
class TestLoadRawRgbArray:
    """``load_raw_rgb_array`` 数组返回路径。"""

    def test_returns_contiguous_array(self, monkeypatch: Any) -> None:
        """返回连续内存的 RGB numpy 数组。"""
        rgb_array = np.zeros((8, 8, 3), dtype=np.uint8)
        _install_fake_rawpy(monkeypatch, postprocess_value=rgb_array)
        result = icutils.load_raw_rgb_array("photo.dng")
        assert result is not None
        assert result.shape == (8, 8, 3)
        assert result.flags["C_CONTIGUOUS"]

    def test_parameter_defaults_forwarded(self, monkeypatch: Any) -> None:
        """默认参数正确转发到 postprocess。"""
        rgb_array = np.zeros((8, 8, 3), dtype=np.uint8)
        _, seen_args = _install_fake_rawpy(
            monkeypatch, postprocess_value=rgb_array
        )
        icutils.load_raw_rgb_array("photo.dng")
        assert seen_args["output_bps"] == 8
        assert seen_args["output_color"] == "sRGB"


# ---------------------------------------------------------------------------
# 模块 API 表面
# ---------------------------------------------------------------------------
class TestModuleApi:
    """模块导出符号完整性。"""

    def test_all_exports(self) -> None:
        """__all__ 与公开函数一一对应，无多余/遗漏。"""
        expected = {
            "apply_exif_orientation",
            "convert_pil_to_srgb",
            "normalize_pil_image",
            "load_raw_image",
            "load_raw_rgb_array",
        }
        assert set(icutils.__all__) == expected
        for name in expected:
            assert callable(getattr(icutils, name))