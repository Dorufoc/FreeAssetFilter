#!/usr/bin/env python3
"""
Rust 缩略图引擎桥接层（ctypes）
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import (
    POINTER,
    Structure,
    c_char_p,
    c_int,
    c_size_t,
    c_uint8,
    c_uint32,
    c_void_p,
)
from pathlib import Path

from freeassetfilter.utils.app_logger import debug, info, warning

# 原生引擎状态码（与 Rust lib.rs 的 pub(crate) STATUS_* 常量同值；
# -4 为 Python 桥专用降级语义：DLL 缺失/可选接口未导出等非解码类失败）
STATUS_OK: int = 0
STATUS_INVALID_ARG: int = -1
STATUS_DECODE_FAILED: int = -2
STATUS_OOM: int = -3
STATUS_BRIDGE_UNAVAILABLE: int = -4
STATUS_INTERNAL: int = -5
STATUS_UNSUPPORTED: int = -6
STATUS_TOO_LARGE: int = -7


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
        # todo 25 新导出能力标记（errorlog 查询/清空、格式表、ffmpeg 能力表）
        self._supports_errorlog = False
        self._supports_formats = False
        self._supports_caps = False
        self._dll_directory_handle = None
        self._preloaded_runtime_dlls = []
        self._load()

    @property
    def available(self) -> bool:
        return self._available and self._dll is not None

    def _native_runtime_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "bin"

    def _is_frozen_app(self) -> bool:
        return bool(getattr(sys, "frozen", False))

    def _candidate_paths(self) -> list[Path]:
        native_dir = Path(__file__).resolve().parent.parent
        bundled_dll = native_dir / "bin" / "thumbnail_generator.dll"
        dev_release_dll = native_dir / "src" / "thumbnail_rust" / "target" / "release" / "thumbnail_generator.dll"
        dev_debug_dll = native_dir / "src" / "thumbnail_rust" / "target" / "debug" / "thumbnail_generator.dll"

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
            except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
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
            except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
                warning(f"加载失败 {path}: {e}")
        self._available = False
        self._dll = None
        warning("未找到可用的 thumbnail_generator.dll，将回退 Python 实现")

    def _bind(self, dll):
        self._supports_jpg = False
        self._supports_batch_jpg = False
        self._supports_errorlog = False
        self._supports_formats = False
        self._supports_caps = False

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
        dll.native_get_decode_stats_json.restype = c_void_p

        dll.native_reset_decode_stats.argtypes = []
        dll.native_reset_decode_stats.restype = c_int

        dll.native_get_available_hwaccels_json.argtypes = []
        dll.native_get_available_hwaccels_json.restype = c_void_p

        dll.native_set_max_concurrent_hw_video_decodes.argtypes = [c_size_t]
        dll.native_set_max_concurrent_hw_video_decodes.restype = c_int

        dll.native_free_buffer.argtypes = [POINTER(c_uint8), c_size_t]
        dll.native_free_buffer.restype = None

        dll.native_free_batch_result.argtypes = [POINTER(NativeThumbnailBatchResult)]
        dll.native_free_batch_result.restype = None

        self._native_free_message = dll.native_free_message
        self._native_free_message.argtypes = [c_void_p]
        self._native_free_message.restype = None

        try:
            dll.native_generate_thumbnail_jpg.argtypes = [c_char_p, c_int, c_int]
            dll.native_generate_thumbnail_jpg.restype = NativeThumbnailResult
            self._supports_jpg = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_jpg = False

        try:
            dll.native_generate_batch_jpg.argtypes = [POINTER(c_char_p), c_int, c_int, c_int]
            dll.native_generate_batch_jpg.restype = NativeThumbnailBatchResult
            self._supports_batch_jpg = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_batch_jpg = False

        # todo 25 新导出：错误日志查询/清空（Rust 导出自 todo 5 起存在）
        try:
            dll.native_get_error_log_json.argtypes = []
            dll.native_get_error_log_json.restype = c_void_p
            dll.native_clear_error_log.argtypes = []
            dll.native_clear_error_log.restype = c_int
            self._supports_errorlog = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_errorlog = False

        # todo 25 新导出：支持格式注册表查询（Rust 导出自 todo 7 起存在）
        try:
            dll.native_get_supported_formats_json.argtypes = []
            dll.native_get_supported_formats_json.restype = c_void_p
            self._supports_formats = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_formats = False

        # todo 23/25 新导出：ffmpeg 能力表查询（Rust 导出自 todo 23 起存在）
        try:
            dll.native_get_ffmpeg_capabilities_json.argtypes = []
            dll.native_get_ffmpeg_capabilities_json.restype = c_void_p
            self._supports_caps = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_caps = False

    def set_cache_limit(self, max_bytes: int) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_set_cache_limit(max(1, int(max_bytes)))
            debug(f"设置缓存限制: {max_bytes} bytes, 结果: {code}")
            return code == 0
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"set_cache_limit 失败: {e}")
            return False

    def clear_cache(self) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_clear_cache()
            debug(f"清除缓存, 结果: {code}")
            return code == 0
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"clear_cache 失败: {e}")
            return False

    def get_decode_stats(self) -> dict[str, int]:
        if not self.available:
            return {}
        raw = self._dll.native_get_decode_stats_json()
        try:
            if not raw:
                return {}
            result = json.loads(ctypes.cast(raw, c_char_p).value)
            debug(f"获取解码统计: {result}")
            return result
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"get_decode_stats 失败: {e}")
            return {}
        finally:
            self._native_free_message(raw)

    def reset_decode_stats(self) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_reset_decode_stats()
            debug(f"重置解码统计, 结果: {code}")
            return code == 0
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"reset_decode_stats 失败: {e}")
            return False

    def get_available_hwaccels(self) -> list[str]:
        if not self.available:
            return []
        raw = self._dll.native_get_available_hwaccels_json()
        try:
            if not raw:
                return []
            parsed = json.loads(ctypes.cast(raw, c_char_p).value)
            if not isinstance(parsed, list):
                return []
            result = [str(item).strip().lower() for item in parsed if str(item).strip()]
            debug(f"可用硬件加速: {result}")
            return result
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"get_available_hwaccels 失败: {e}")
            return []
        finally:
            self._native_free_message(raw)

    def set_max_concurrent_hw_video_decodes(self, max_slots: int) -> bool:
        if not self.available:
            return False
        try:
            code = self._dll.native_set_max_concurrent_hw_video_decodes(max(1, int(max_slots)))
            debug(f"设置最大并发硬件解码数: {max_slots}, 结果: {code}")
            return code == 0
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"set_max_concurrent_hw_video_decodes 失败: {e}")
            return False

    def get_error_log(self) -> str:
        """获取原生错误日志环形缓冲的 JSON 字符串。

        每条记录含 ``path`` / ``format`` / ``status`` / ``message`` /
        ``timestamp`` 字段；环形上限 512 条，溢出丢弃最旧。写入侧由 Rust
        T3 跳过路径与解码失败统一补录（thumbnail-rust-refactor todo 25）填充。

        Returns:
            JSON 数组字符串；DLL 不可用、绑定缺失、返回空指针或内容非法时
            返回安全降级值 ``"[]"``（不抛异常）。
        """
        if not self.available or not self._supports_errorlog:
            return "[]"
        raw = None
        try:
            raw = self._dll.native_get_error_log_json()
            if not raw:
                return "[]"
            payload = ctypes.cast(raw, c_char_p).value
            if not payload:
                return "[]"
            text = payload.decode("utf-8", errors="replace")
            json.loads(text)  # 非法 JSON 一律降级，保证返回值恒可解析
            return text
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"get_error_log 失败: {e}")
            return "[]"
        finally:
            if raw is not None:
                self._native_free_message(raw)

    def clear_error_log(self) -> bool:
        """清空原生错误日志环形缓冲。

        Returns:
            清空成功返回 ``True``；DLL 不可用、绑定缺失或调用失败返回
            ``False``（不抛异常）。
        """
        if not self.available or not self._supports_errorlog:
            return False
        try:
            code = self._dll.native_clear_error_log()
            debug(f"清空错误日志, 结果: {code}")
            return code == 0
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"clear_error_log 失败: {e}")
            return False

    def get_supported_formats(self) -> str:
        """获取原生支持格式注册表的 JSON 字符串。

        形状：``{"formats": [{"id": str, "extensions": [str, ...]}, ...]}``，
        覆盖魔数注册表全部格式组（顺序稳定）。

        Returns:
            JSON 对象字符串；DLL 不可用、绑定缺失或调用失败时返回安全降级值
            ``"{}"``（与 Rust 查询型导出的 panic 降级口径一致，不抛异常）。
        """
        if not self.available or not self._supports_formats:
            return "{}"
        raw = None
        try:
            raw = self._dll.native_get_supported_formats_json()
            if not raw:
                return "{}"
            payload = ctypes.cast(raw, c_char_p).value
            if not payload:
                return "{}"
            text = payload.decode("utf-8", errors="replace")
            if not isinstance(json.loads(text), dict):
                return "{}"
            return text
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"get_supported_formats 失败: {e}")
            return "{}"
        finally:
            if raw is not None:
                self._native_free_message(raw)

    def get_ffmpeg_capabilities(self) -> str:
        """获取 ffmpeg/ffprobe 实测能力表的 JSON 字符串。

        形状：``{"version": str, "formats": [...], "demuxer": [...],
        "muxer": [...], "codecs": [...], "hwaccels": [...]}``
        （thumbnail-rust-refactor todo 23 契约；OnceLock 缓存）。

        Returns:
            JSON 对象字符串；DLL 不可用、绑定缺失或调用失败时返回安全降级值
            ``"{}"``（与 Rust 查询型导出的 panic 降级口径一致，不抛异常）。
        """
        if not self.available or not self._supports_caps:
            return "{}"
        raw = None
        try:
            raw = self._dll.native_get_ffmpeg_capabilities_json()
            if not raw:
                return "{}"
            payload = ctypes.cast(raw, c_char_p).value
            if not payload:
                return "{}"
            text = payload.decode("utf-8", errors="replace")
            if not isinstance(json.loads(text), dict):
                return "{}"
            return text
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"get_ffmpeg_capabilities 失败: {e}")
            return "{}"
        finally:
            if raw is not None:
                self._native_free_message(raw)

    def generate_rgba(self, file_path: str, width: int, height: int) -> tuple[bytes, int, int, int] | None:
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
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"generate_rgba 失败: {e}")
            return None

    def _jpeg_like_with_status(
        self,
        dll_func_name: str,
        file_path: str,
        width: int,
        height: int,
        log_label: str,
        capability_attr: str | None = None,
    ) -> tuple[bytes | None, int]:
        """内部通用：调用单个 native_generate_thumbnail(_jpg) 导出并透传结构体 status。

        状态码直读 ``NativeThumbnailResult.status`` 字段（方案 A，结构体已在
        ctypes 绑定中含该字段，零 Rust 改动），不回读 errorlog。

        Args:
            dll_func_name: DLL 导出函数名。
            file_path: 文件路径。
            width: 目标宽度。
            height: 目标高度。
            log_label: 日志前缀标签。
            capability_attr: 可选能力标记属性名（如 ``"_supports_jpg"``）；
                非 None 时该标记为 False 直接降级，不触碰 DLL。

        Returns:
            Tuple[Optional[bytes], int]: 成功 ``(图像字节, STATUS_OK)``；
            失败 ``(None, 状态码)``——DLL 不可用或可选接口缺失返回
            ``STATUS_BRIDGE_UNAVAILABLE(-4)``，路径无效返回
            ``STATUS_INVALID_ARG(-1)``，FFI 异常返回 ``STATUS_INTERNAL(-5)``，
            其余为 Rust 解码管线的原生状态码。不抛异常。
        """
        if not self.available:
            return None, STATUS_BRIDGE_UNAVAILABLE
        if capability_attr is not None and not getattr(self, capability_attr, False):
            return None, STATUS_BRIDGE_UNAVAILABLE
        if not file_path or not os.path.exists(file_path):
            return None, STATUS_INVALID_ARG
        try:
            func = getattr(self._dll, dll_func_name)
            result = func(file_path.encode("utf-8"), int(width), int(height))
            status = int(result.status)
            if status != STATUS_OK or not result.data or result.len <= 0:
                debug(f"{log_label}失败: status={status}")
                return None, status
            payload = ctypes.string_at(result.data, result.len)
            self._dll.native_free_buffer(result.data, result.len)
            debug(f"{log_label}成功: {file_path}, 大小 {len(payload)} bytes")
            return payload, STATUS_OK
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"{log_label}异常: {e}")
            return None, STATUS_INTERNAL

    def generate_jpg_with_status(self, file_path: str, width: int, height: int) -> tuple[bytes | None, int]:
        """生成 JPG 缩略图并透传原生状态码（todo 33 状态通道入口）。

        与 :meth:`generate_jpg` 的区别在于失败时不再吞掉状态码：直接读取
        ctypes 结构体的 ``status`` 字段返回给调用方，供 ThumbnailManager 按
        ``-7 TOO_LARGE / -6 UNSUPPORTED / -3 OOM / -2 DECODE_FAILED`` 路由
        回退链。

        Returns:
            Tuple[Optional[bytes], int]: 成功 ``(jpg_bytes, 0)``；失败
            ``(None, status_code)``（降级语义见 :meth:`_jpeg_like_with_status`）。
        """
        return self._jpeg_like_with_status(
            "native_generate_thumbnail_jpg", file_path, width, height,
            log_label="生成 JPG(带状态)", capability_attr="_supports_jpg",
        )

    def generate_jpeg_with_status(self, file_path: str, width: int, height: int) -> tuple[bytes | None, int]:
        """生成 JPEG 缩略图并透传原生状态码（兼容别名接口的状态通道版）。"""
        return self._jpeg_like_with_status(
            "native_generate_thumbnail_jpeg", file_path, width, height,
            log_label="生成 JPEG(带状态)",
        )

    def generate_rgba_with_status(
        self, file_path: str, width: int, height: int
    ) -> tuple[tuple[bytes, int, int, int] | None, int]:
        """生成 RGBA 像素并透传原生状态码（manager RGBA 回退路径专用）。

        Returns:
            Tuple[Optional[Tuple[bytes, int, int, int]], int]: 成功
            ``((raw, w, h, channels), 0)``；失败 ``(None, status_code)``，
            降级语义与 :meth:`_jpeg_like_with_status` 一致。不抛异常。
        """
        if not self.available:
            return None, STATUS_BRIDGE_UNAVAILABLE
        if not file_path or not os.path.exists(file_path):
            return None, STATUS_INVALID_ARG
        try:
            result = self._dll.native_generate_thumbnail(file_path.encode("utf-8"), int(width), int(height))
            status = int(result.status)
            if status != STATUS_OK or not result.data or result.len <= 0:
                debug(f"生成 RGBA(带状态) 失败: status={status}")
                return None, status
            raw = ctypes.string_at(result.data, result.len)
            channels = int(result.channels) if result.channels else 4
            w = int(result.width)
            h = int(result.height)
            self._dll.native_free_buffer(result.data, result.len)
            debug(f"生成 RGBA(带状态) 成功: {file_path}, 尺寸 {w}x{h}, 通道 {channels}")
            return (raw, w, h, channels), STATUS_OK
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"generate_rgba_with_status 失败: {e}")
            return None, STATUS_INTERNAL

    def generate_jpeg(self, file_path: str, width: int, height: int) -> bytes | None:
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
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"generate_jpeg 失败: {e}")
            return None

    def generate_jpg(self, file_path: str, width: int, height: int) -> bytes | None:
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
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"generate_jpg 失败: {e}")
            return None

    def generate_jpg_batch(self, file_paths: list[str], width: int, height: int) -> list[bytes | None]:
        """
        批量调用 Rust 原生接口生成 JPG 缩略图字节。
        返回与输入路径等长的结果列表；失败项为 None。
        """
        if not self.available or not self._supports_batch_jpg:
            return [None for _ in file_paths]
        if not file_paths:
            return []

        debug(f"批量生成 JPG: {len(file_paths)} 个文件, 尺寸 {width}x{height}")

        normalized_paths: list[str] = []
        for p in file_paths:
            if p and os.path.exists(p):
                normalized_paths.append(p)
            else:
                normalized_paths.append("")

        encoded_paths = [(p.encode("utf-8") if p else None) for p in normalized_paths]
        arr_type = c_char_p * len(encoded_paths)
        c_paths = arr_type(*encoded_paths)

        batch_result = None
        outputs: list[bytes | None] = [None for _ in file_paths]

        try:
            batch_result = self._dll.native_generate_batch_jpg(
                c_paths, len(encoded_paths), int(width), int(height)
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
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"generate_jpg_batch 失败: {e}")
            return outputs
        finally:
            if batch_result is not None:
                try:
                    self._dll.native_free_batch_result(ctypes.byref(batch_result))
                except Exception:  # noqa: BLE001, S110  # broad catch intentional at ctypes FFI boundary; ignore intentional (ctypes FFI boundary)
                    pass
