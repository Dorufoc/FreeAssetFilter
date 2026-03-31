#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust 颜色提取 DLL 的 ctypes 桥接层
"""

from __future__ import annotations

import ctypes
import json
from ctypes import c_char_p, c_float, c_int, c_size_t, c_uint8, POINTER, Structure
from pathlib import Path
from typing import List, Tuple

from freeassetfilter.utils.app_logger import debug, warning


class LabResult(Structure):
    _fields_ = [
        ("l", c_float),
        ("a", c_float),
        ("b", c_float),
    ]


class RgbResult(Structure):
    _fields_ = [
        ("r", c_uint8),
        ("g", c_uint8),
        ("b", c_uint8),
    ]


class RustColorExtractorBridge:
    def __init__(self):
        self._dll = None
        self._available = False
        self._load()

    @property
    def available(self) -> bool:
        return self._available and self._dll is not None

    def _candidate_paths(self) -> List[Path]:
        base_dir = Path(__file__).resolve().parent
        return [
            base_dir / "rust_color_extractor_native.dll",
            base_dir / "color_extractor_rust" / "target" / "release" / "rust_color_extractor_native.dll",
        ]

    def _load(self):
        for path in self._candidate_paths():
            if not path.exists():
                continue

            try:
                dll = ctypes.CDLL(str(path))
                self._bind(dll)
                self._dll = dll
                self._available = True
                debug(f"[RustColorExtractor] 已加载 Rust DLL: {path}")
                return
            except Exception as e:
                warning(f"[RustColorExtractor] 加载 DLL 失败 {path}: {e}")

        self._dll = None
        self._available = False
        warning("[RustColorExtractor] 未找到可用的 rust_color_extractor_native.dll")

    def _bind(self, dll):
        dll.color_extractor_get_version.argtypes = []
        dll.color_extractor_get_version.restype = c_char_p

        dll.color_extractor_extract_colors.argtypes = [POINTER(c_uint8), c_size_t, c_int, c_float, c_int]
        dll.color_extractor_extract_colors.restype = c_char_p

        dll.color_extractor_rgb_to_lab.argtypes = [c_uint8, c_uint8, c_uint8]
        dll.color_extractor_rgb_to_lab.restype = LabResult

        dll.color_extractor_lab_to_rgb.argtypes = [c_float, c_float, c_float]
        dll.color_extractor_lab_to_rgb.restype = RgbResult

        dll.color_extractor_ciede2000.argtypes = [c_float, c_float, c_float, c_float, c_float, c_float]
        dll.color_extractor_ciede2000.restype = c_float

    def get_version(self) -> str:
        if not self.available:
            raise RuntimeError("Rust DLL 不可用")
        raw = self._dll.color_extractor_get_version()
        if not raw:
            raise RuntimeError("无法获取版本信息")
        return ctypes.cast(raw, c_char_p).value.decode("utf-8", errors="replace")

    def extract_colors(
        self,
        image_data: bytes,
        num_colors: int = 5,
        min_distance: float = 75.0,
        max_image_size: int = 150,
    ) -> List[Tuple[int, int, int]]:
        if not self.available:
            raise RuntimeError("Rust DLL 不可用")
        if not image_data:
            raise ValueError("图像数据为空")

        buf = (c_uint8 * len(image_data)).from_buffer_copy(image_data)
        raw = self._dll.color_extractor_extract_colors(
            buf,
            len(image_data),
            int(num_colors),
            float(min_distance),
            int(max_image_size),
        )
        if not raw:
            raise RuntimeError("Rust DLL 返回空结果")

        payload = ctypes.cast(raw, c_char_p).value.decode("utf-8", errors="replace")
        data = json.loads(payload)

        if "error" in data:
            raise RuntimeError(data["error"])

        colors = data.get("colors", [])
        result = []
        for item in colors:
            if isinstance(item, list) and len(item) >= 3:
                result.append((int(item[0]), int(item[1]), int(item[2])))
        return result

    def rgb_to_lab(self, r: int, g: int, b: int) -> Tuple[float, float, float]:
        if not self.available:
            raise RuntimeError("Rust DLL 不可用")
        result = self._dll.color_extractor_rgb_to_lab(int(r), int(g), int(b))
        return (float(result.l), float(result.a), float(result.b))

    def lab_to_rgb(self, l: float, a: float, b: float) -> Tuple[int, int, int]:
        if not self.available:
            raise RuntimeError("Rust DLL 不可用")
        result = self._dll.color_extractor_lab_to_rgb(float(l), float(a), float(b))
        return (int(result.r), int(result.g), int(result.b))

    def ciede2000(
        self,
        l1: float,
        a1: float,
        b1: float,
        l2: float,
        a2: float,
        b2: float,
    ) -> float:
        if not self.available:
            raise RuntimeError("Rust DLL 不可用")
        return float(self._dll.color_extractor_ciede2000(l1, a1, b1, l2, a2, b2))


_BRIDGE = RustColorExtractorBridge()

if not _BRIDGE.available:
    raise ImportError("rust_color_extractor_native.dll 不可用")

__version__ = _BRIDGE.get_version()


def extract_colors(
    image_data: bytes,
    num_colors: int = 5,
    min_distance: float = 75.0,
    max_image_size: int = 150,
) -> List[Tuple[int, int, int]]:
    return _BRIDGE.extract_colors(image_data, num_colors, min_distance, max_image_size)


def extract_colors_from_numpy(image_array, num_colors: int = 5, min_distance: float = 75.0):
    try:
        shape = image_array.shape
        if len(shape) != 3:
            raise ValueError("图像数组必须是 3 维 (H, W, C)")
        height, width, channels = int(shape[0]), int(shape[1]), int(shape[2])
        if channels not in (3, 4):
            raise ValueError("图像必须是 RGB 或 RGBA 格式")
        raw = image_array.tobytes()
        header = int(width).to_bytes(4, "little", signed=True) + int(height).to_bytes(4, "little", signed=True)
        return extract_colors(header + raw, num_colors=num_colors, min_distance=min_distance, max_image_size=150)
    except AttributeError as e:
        raise ValueError(f"无效的 numpy 图像数组: {e}")


def rgb_to_lab(r: int, g: int, b: int) -> Tuple[float, float, float]:
    return _BRIDGE.rgb_to_lab(r, g, b)


def lab_to_rgb(l: float, a: float, b: float) -> Tuple[int, int, int]:
    return _BRIDGE.lab_to_rgb(l, a, b)


def ciede2000(l1: float, a1: float, b1: float, l2: float, a2: float, b2: float) -> float:
    return _BRIDGE.ciede2000(l1, a1, b1, l2, a2, b2)
