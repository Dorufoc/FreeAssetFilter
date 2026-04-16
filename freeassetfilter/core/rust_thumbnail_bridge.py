#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rust 缩略图引擎桥接层（ctypes）
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import c_char_p, c_int, c_size_t, c_uint8, c_uint32, POINTER, Structure
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from freeassetfilter.utils.app_logger import debug, info, warning, error


class NativeThumbnailResult(Structure):
    _fields_ = [
        ("status", c_int),
        ("width", c_uint32),
        ("height", c_uint32),
        ("channels", c_uint8),
        ("len", c_size_t),
        ("data", POINTER(c_uint8)),
        ("message", c_char_p),
    ]


class NativeThumbnailBatchResult(Structure):
    _fields_ = [
        ("status", c_int),
        ("count", c_size_t),
        ("results", POINTER(NativeThumbnailResult)),
        ("message", c_char_p),
    ]


class RustThumbnailBridge:
    """Rust 原生缩略图桥接"""

    def __init__(self):
        self._dll = None
        self._available = False
        self._supports_jpg = False
        self._supports_batch_jpg = False
        self._dll_directory_handle = None
        self._preloaded_runtime_dlls = []
        self._load()

    @property
    def available(self) -> bool:
        return self._available and self._dll is not None

    def _native_runtime_dir(self) -> Path:
        return Path(__file__).resolve().parent / "native"

    def _is_frozen_app(self) -> bool:
        return bool(getattr(sys, "frozen", False))

    def _candidate_paths(self) -> List[Path]:
        core_dir = Path(__file__).resolve().parent
        bundled_dll = core_dir / "native" / "thumbnail_generator.dll"
        dev_release_dll = core_dir / "native" / "thumbnail_rust" / "target" / "release" / "thumbnail_generator.dll"
        dev_debug_dll = core_dir / "native" / "thumbnail_rust" / "target" / "debug" / "thumbnail_generator.dll"

        if self._is_frozen_app():
            return [bundled_dll]

        return [dev_release_dll, dev_debug_dll]

    def _prepare_local_runtime(self):
        """
        显式准备项目内自带的原生运行时依赖，避免回退到外部环境中的 OpenCV DLL。
        """
        runtime_dir = self._native_runtime_dir()
        if not runtime_dir.exists():
            debug(f"原生运行时目录不存在: {runtime_dir}")
            return

        if os.name == "nt" and hasattr(os, "add_dll_directory"):
            try:
                self._dll_directory_handle = os.add_dll_directory(str(runtime_dir))
                debug(f"已添加 DLL 目录: {runtime_dir}")
            except Exception as e:
                warning(f"添加 DLL 目录失败: {e}")

        # 运行时工具（如 ffmpeg/ffprobe）由 Rust 侧按路径直接调用，
        # 这里不再预加载任何 OpenCV 相关 DLL，避免误依赖外部环境。

    def _load(self):
        debug("开始加载 Rust 原生引擎")
        self._prepare_local_runtime()
        for path in self._candidate_paths():
            if not path.exists():
                debug(f"候选路径不存在: {path}")
                continue
            try:
                dll = ctypes.CDLL(str(path))
                self._bind(dll)
                self._dll = dll
                self._available = True
                info(f"已加载原生引擎: {path}")
                return
            except Exception as e:
                warning(f"加载失败 {path}: {e}")
        self._available = False
        self._dll = None
        warning("未找到可用的 thumbnail_generator.dll，将回退 Python 实现")

    def _bind(self, dll):
        self._supports_jpg = False
        self._supports_batch_jpg = False

        dll.native_generate_thumbnail.argtypes = [c_char_p, c_int, c_int]
        dll.native_generate_thumbnail.restype = NativeThumbnailResult

        dll.native_generate_thumbnail_jpeg.argtypes = [c_char_p, c_int, c_int]
        dll.native_generate_thumbnail_jpeg.restype = NativeThumbnailResult

        dll.native_generate_batch.argtypes = [POINTER(c_char_p), c_int, c_int, c_int]
        dll.native_generate_batch.restype = NativeThumbnailBatchResult

        dll.native_set_cache_limit.argtypes = [c_size_t]
        dll.native_set_cache_limit.restype = c_int

        dll.native_clear_cache.argtypes = []
        dll.native_clear_cache.restype = c_int

        dll.native_get_decode_stats_json.argtypes = []
        dll.native_get_decode_stats_json.restype = c_char_p

        dll.native_reset_decode_stats.argtypes = []
        dll.native_reset_decode_stats.restype = c_int

        dll.native_get_available_hwaccels_json.argtypes = []
        dll.native_get_available_hwaccels_json.restype = c_char_p

        dll.native_set_max_concurrent_hw_video_decodes.argtypes = [c_size_t]
        dll.native_set_max_concurrent_hw_video_decodes.restype = c_int

        dll.native_free_buffer.argtypes = [POINTER(c_uint8), c_size_t]
        dll.native_free_buffer.restype = None

        dll.native_free_batch_result.argtypes = [POINTER(NativeThumbnailBatchResult)]
        dll.native_free_batch_result.restype = None

        try:
            dll.native_generate_thumbnail_jpg.argtypes = [c_char_p, c_int, c_int]
            dll.native_generate_thumbnail_jpg.restype = NativeThumbnailResult
            self._supports_jpg = True
        except Exception:
            self._supports_jpg = False

        try:
            dll.native_generate_batch_jpg.argtypes = [POINTER(c_char_p), c_int, c_int, c_int]
            dll.native_generate_batch_jpg.restype = NativeThumbnailBatchResult
            self._supports_batch_jpg = True
        except Exception:
            self._supports_batch_jpg = False

    def set_cache_limit(self, max_bytes: int) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_set_cache_limit(max(1, int(max_bytes)))
            debug(f"设置缓存限制: {max_bytes} bytes, 结果: {code}")
            return code == 0
        except Exception as e:
            warning(f"set_cache_limit 失败: {e}")
            return False

    def clear_cache(self) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_clear_cache()
            debug(f"清除缓存, 结果: {code}")
            return code == 0
        except Exception as e:
            warning(f"clear_cache 失败: {e}")
            return False

    def get_decode_stats(self) -> Dict[str, int]:
        if not self.available:
            return {}
        try:
            raw = self._dll.native_get_decode_stats_json()
            if not raw:
                return {}
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore")
            else:
                text = raw
            result = json.loads(text) if text else {}
            debug(f"获取解码统计: {result}")
            return result
        except Exception as e:
            warning(f"get_decode_stats 失败: {e}")
            return {}

    def reset_decode_stats(self) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_reset_decode_stats()
            debug(f"重置解码统计, 结果: {code}")
            return code == 0
        except Exception as e:
            warning(f"reset_decode_stats 失败: {e}")
            return False

    def get_available_hwaccels(self) -> List[str]:
        if not self.available:
            return []
        try:
            raw = self._dll.native_get_available_hwaccels_json()
            if not raw:
                return []
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore")
            else:
                text = raw
            parsed = json.loads(text) if text else []
            if not isinstance(parsed, list):
                return []
            result = [str(item).strip().lower() for item in parsed if str(item).strip()]
            debug(f"可用硬件加速: {result}")
            return result
        except Exception as e:
            warning(f"get_available_hwaccels 失败: {e}")
            return []

    def set_max_concurrent_hw_video_decodes(self, max_slots: int) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_set_max_concurrent_hw_video_decodes(max(1, int(max_slots)))
            debug(f"设置最大并发硬件解码数: {max_slots}, 结果: {code}")
            return code == 0
        except Exception as e:
            warning(f"set_max_concurrent_hw_video_decodes 失败: {e}")
            return False

    def generate_rgba(self, file_path: str, width: int, height: int) -> Optional[Tuple[bytes, int, int, int]]:
        if not self.available:
            return None
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            result = self._dll.native_generate_thumbnail(file_path.encode("utf-8"), int(width), int(height))
            if result.status != 0 or not result.data or result.len <= 0:
                debug(f"生成 RGBA 失败: status={result.status}, data={result.data}, len={result.len}")
                return None
            raw = ctypes.string_at(result.data, result.len)
            channels = int(result.channels) if result.channels else 4
            w = int(result.width)
            h = int(result.height)
            self._dll.native_free_buffer(result.data, result.len)
            debug(f"生成 RGBA 成功: {file_path}, 尺寸 {w}x{h}, 通道 {channels}")
            return raw, w, h, channels
        except Exception as e:
            warning(f"generate_rgba 失败: {e}")
            return None

    def generate_jpeg(self, file_path: str, width: int, height: int) -> Optional[bytes]:
        """
        直接由 Rust 返回已编码 JPEG 字节。
        """
        if not self.available:
            return None
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            result = self._dll.native_generate_thumbnail_jpeg(file_path.encode("utf-8"), int(width), int(height))
            if result.status != 0 or not result.data or result.len <= 0:
                debug(f"生成 JPEG 失败: status={result.status}")
                return None
            jpeg_bytes = ctypes.string_at(result.data, result.len)
            self._dll.native_free_buffer(result.data, result.len)
            debug(f"生成 JPEG 成功: {file_path}, 大小 {len(jpeg_bytes)} bytes")
            return jpeg_bytes
        except Exception as e:
            warning(f"generate_jpeg 失败: {e}")
            return None

    def generate_jpg(self, file_path: str, width: int, height: int) -> Optional[bytes]:
        """
        直接由 Rust 返回已编码 JPG 字节。
        """
        if not self.available or not self._supports_jpg:
            return None
        if not file_path or not os.path.exists(file_path):
            return None
        try:
            result = self._dll.native_generate_thumbnail_jpg(file_path.encode("utf-8"), int(width), int(height))
            if result.status != 0 or not result.data or result.len <= 0:
                debug(f"生成 JPG 失败: status={result.status}")
                return None
            jpg_bytes = ctypes.string_at(result.data, result.len)
            self._dll.native_free_buffer(result.data, result.len)
            debug(f"生成 JPG 成功: {file_path}, 大小 {len(jpg_bytes)} bytes")
            return jpg_bytes
        except Exception as e:
            warning(f"generate_jpg 失败: {e}")
            return None

    def generate_jpg_batch(self, file_paths: List[str], width: int, height: int) -> List[Optional[bytes]]:
        """
        批量调用 Rust 原生接口生成 JPG 缩略图字节。
        返回与输入路径等长的结果列表；失败项为 None。
        """
        if not self.available or not self._supports_batch_jpg:
            return [None for _ in file_paths]
        if not file_paths:
            return []

        debug(f"批量生成 JPG: {len(file_paths)} 个文件, 尺寸 {width}x{height}")

        normalized_paths: List[str] = []
        for p in file_paths:
            if p and os.path.exists(p):
                normalized_paths.append(p)
            else:
                normalized_paths.append("")

        encoded_paths = [(p.encode("utf-8") if p else None) for p in normalized_paths]
        arr_type = c_char_p * len(encoded_paths)
        c_paths = arr_type(*encoded_paths)

        batch_result = None
        outputs: List[Optional[bytes]] = [None for _ in file_paths]

        try:
            batch_result = self._dll.native_generate_batch_jpg(
                c_paths, int(len(encoded_paths)), int(width), int(height)
            )

            if batch_result.status != 0 or not batch_result.results or batch_result.count <= 0:
                debug(f"批量生成失败: status={batch_result.status if batch_result else 'N/A'}")
                return outputs

            safe_count = min(int(batch_result.count), len(outputs))
            success_count = 0
            for i in range(safe_count):
                item = batch_result.results[i]
                if item.status == 0 and item.data and item.len > 0:
                    outputs[i] = ctypes.string_at(item.data, item.len)
                    success_count += 1
                else:
                    outputs[i] = None

            debug(f"批量生成完成: {success_count}/{len(file_paths)} 成功")
            return outputs
        except Exception as e:
            warning(f"generate_jpg_batch 失败: {e}")
            return outputs
        finally:
            if batch_result is not None:
                try:
                    self._dll.native_free_batch_result(ctypes.byref(batch_result))
                except Exception:
                    pass
