#!/usr/bin/env python3
"""faf_core 统一原生核心桥接层（ctypes）。

本模块是 ``faf_core.dll``（Rust cdylib，见
``freeassetfilter/core/native/src/faf_core/``）的 Python 桥。遵循
``rust_thumbnail_bridge.py`` 的加载范式与 ``mica_render.py`` 的路径范式：

* 候选路径以 :func:`freeassetfilter.core._paths.native_bin_dir` 解析的
  ``core/native/bin/faf_core.dll`` 优先，开发期回退
  ``src/faf_core/target/release|debug`` 下的 cargo 产物；
* ``os.add_dll_directory`` 预置运行时目录后 ``ctypes.CDLL`` 加载（释放 GIL）；
* JSON 返回统一 ``c_void_p`` + ``ctypes.string_at`` 拷贝 +
  ``finally: faf_free_message`` 释放；
* 可选导出经 ``try/except`` 能力探测 ``_supports_*``；
* DLL 缺失时安全降级（``available is False``，调用返回 ``None`` 不抛异常）。

已绑定业务导出：``faf_version`` / ``faf_free_message`` /
``faf_scan_directory``（目录扫描，7 键 JSON）/ ``faf_sort_entries``
（条目排序，8 种模式）/ ``faf_highlight_text``（代码语法高亮，span-only
JSON ``[{start,len,token_type}]``，字符偏移）/ ``faf_render_markdown``
（Markdown 渲染，body 片段 JSON ``{"html": ...}``，无 CSS/颜色，主题由
调用方注入。见 ``freeassetfilter/utils/markdown_renderer.py`` todo-17
接线）/ ``faf_parse_font``（字体解析，JSON
``{"name1".."name6","format","glyph_count","ascent","descent","line_gap"}``，
name 缺失键为 null；WOFF/WOFF2 与损坏字体返回 null 由调用方回退
fontTools。见 ``file_info_service.py`` todo-26 接线）/ ``faf_hash_init/
update/final/free``（流式三哈希 MD5/SHA1/SHA256，句柄式注册表；Rust 侧
不做文件 I/O——I/O 循环在 Python 侧 :meth:`FafCoreBridge.hash_file_streaming`
持行，逐块喂入，每块前可取消）/ ``faf_detect_encoding``（文本编码探测，
只吃调用方提供的原始字节样本 ``(ptr, len)``，JSON
``{"encoding","confidence"}``，置信度 <0.5 返回空 JSON ``{}``。见
``file_info_service.py`` todo-25 三处收敛接线）/ ``faf_copy_files``（批量
复制，≤32 源/批 rayon 并行，JSON ``{"copied","failed"}``，目标名=源文件名。
见 ``file_pool_layout.py`` todo-29 导出接线）/ ``faf_sum_directory_sizes``
（单遍递归目录大小聚合，JSON ``{"results"}``、``follow_symlinks=False``。
见 ``staging_pool_service.py`` todo-29 接线）。公开入口经
:func:`get_faf_core_bridge` 模块级惰性单例获取（避免每次调用重建 ctypes
绑定）。

新增导出（rust-hot-path-native-migration todo 3 接线）：``faf_parse_exif``
（图片 EXIF，JSON ``{"common","rest"}``，见 ``file_info_service.py``
todo-7 接线）/ ``faf_composite_psd``（PSD 合成，spike 裁决 DROP——恒返回
null，Python 保持 psd-tools）/ ``faf_replace_svg_colors``（SVG 图标换色，
返回**裸 SVG 文本**非 JSON，见 ``svg_renderer.py`` todo-12 接线）/
``faf_render_fluid_frame``（流体 CPU 帧，spike 裁决 DROP——恒返回 null，
返回 **RGBA 像素缓冲**非 JSON，``QPixmap`` 构造留 GUI 线程）/
``faf_parse_7z_list``（7z ``-slt`` 输出解析，JSON 数组，见 ``py7z_core.py``
todo-17 接线；7z.exe 子进程保留在 Python）/ ``faf_pdf_select_words``
（PDF 选区逐词过滤，JSON 数组，见 ``pdf_document_view.py`` todo-19 接线；
PyMuPDF 取词保留在 Python）。JSON 导出统一走
:meth:`_call_json_list_export` / :meth:`_call_json_object_export` 骨架
（先 ``string_at`` 拷贝后 ``finally: faf_free_message`` 释放）。
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
from collections.abc import Callable
from ctypes import POINTER, c_char_p, c_double, c_int, c_size_t, c_uint64, c_void_p
from pathlib import Path
from typing import Optional

from freeassetfilter.utils.app_logger import debug, info, warning

LIBRARY_NAME: str = "faf_core.dll"

# JSON 载荷上限（与 Rust 侧 ``lib.rs::MAX_JSON_BYTES`` 同值）。
# 超限时 native 返回 null / 跳过，Python 侧回退自身实现。
MAX_JSON_BYTES: int = 8 * 1024 * 1024

# 流式哈希 I/O 参数（语义对齐 ``file_info_service.compute_hashes``：
# 256KiB 块读取、每累计 1MiB 触发一次进度回调）。
HASH_CHUNK_SIZE: int = 256 * 1024
HASH_PROGRESS_GRANULARITY: int = 1024 * 1024

# 模块级惰性单例（``threading.Lock`` 保证并发首次构造安全）。
_instance_lock: threading.Lock = threading.Lock()
_instance: Optional["FafCoreBridge"] = None


def get_faf_core_bridge() -> Optional["FafCoreBridge"]:
    """获取 faf_core 桥的模块级惰性单例（线程安全）。

    DLL 缺失时返回 ``available is False`` 的降级实例；调用方经
    ``available`` / ``_supports_*`` 探测后决定是否走 native 路径。惰性
    构造避免启动期在 DLL 缺失环境产生不必要的 I/O。

    Returns:
        Optional[FafCoreBridge]: 桥实例（模块首次调用时构造）。
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FafCoreBridge()
    return _instance


class FafCoreBridge:
    """faf_core 原生核心桥接。"""

    def __init__(self) -> None:
        self._dll = None
        self._available = False
        self._supports_version = False
        self._supports_scan = False
        self._supports_sort = False
        self._supports_highlight = False
        self._supports_render_markdown = False
        self._supports_parse_font = False
        self._supports_hash = False
        self._supports_detect_encoding = False
        self._supports_copy = False
        self._supports_sizesum = False
        self._supports_parse_exif = False
        self._supports_composite_psd = False
        self._supports_replace_svg_colors = False
        self._supports_render_fluid_frame = False
        self._supports_parse_7z_list = False
        self._supports_pdf_select_words = False
        self._dll_directory_handle = None
        self._load()

    @property
    def available(self) -> bool:
        """DLL 是否已成功加载。"""
        return self._available and self._dll is not None

    def _native_runtime_dir(self) -> Path:
        """返回原生运行时目录（``os.add_dll_directory`` 目标）。

        优先 :func:`freeassetfilter.core._paths.native_bin_dir`（mica_render
        范式）；``_paths`` 不可用时退回相对定位。

        Returns:
            Path: ``core/native/bin/`` 目录。
        """
        try:
            from freeassetfilter.core._paths import native_bin_dir

            return native_bin_dir()
        except Exception:  # pragma: no cover - _paths 不可用时退回相对定位
            return Path(__file__).resolve().parent.parent / "bin"

    def _is_frozen_app(self) -> bool:
        """是否运行于打包产物中。"""
        return bool(getattr(sys, "frozen", False))

    def _candidate_paths(self) -> list[Path]:
        """返回 DLL 候选路径（按优先级，未过滤存在性）。

        打包后只允许 ``core/native/bin/faf_core.dll``；开发期额外允许
        ``src/faf_core/target/release|debug`` 下的 cargo 产物，便于编译后
        立即验证而无需先拷贝（todo 4 之前 DLL 尚未拷贝进 ``bin/``）。

        Returns:
            list[Path]: 候选路径列表。
        """
        native_dir = Path(__file__).resolve().parent.parent
        bundled_dll = self._native_runtime_dir() / LIBRARY_NAME
        dev_release_dll = native_dir / "src" / "faf_core" / "target" / "release" / LIBRARY_NAME
        dev_debug_dll = native_dir / "src" / "faf_core" / "target" / "debug" / LIBRARY_NAME

        if self._is_frozen_app():
            return [bundled_dll]

        return [bundled_dll, dev_release_dll, dev_debug_dll]

    def _prepare_local_runtime(self) -> None:
        """显式准备项目内自带的原生运行时目录。"""
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

    def _load(self) -> None:
        """按候选路径顺序加载第一个可用的 DLL。"""
        debug("开始加载 faf_core 原生核心")
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
                info(f"已加载 faf_core 原生核心: {path}")
                return
            except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
                warning(f"加载失败 {path}: {e}")
        self._available = False
        self._dll = None
        warning("未找到可用的 faf_core.dll，将回退 Python 实现")

    def _bind(self, dll) -> None:
        """为 DLL 导出绑定 ctypes 签名（try/except 能力探测）。

        业务导出按 ``try/except`` 能力探测形态逐个追加：某个导出缺失
        （旧版 DLL）仅影响对应能力标志（``_supports_*`` = False），调用方
        据此回退 Python 实现。

        Args:
            dll: 已加载的 DLL 句柄。
        """
        self._supports_version = False
        self._supports_scan = False
        self._supports_sort = False
        self._supports_highlight = False
        self._supports_render_markdown = False
        self._supports_parse_font = False
        self._supports_hash = False
        self._supports_detect_encoding = False
        self._supports_copy = False
        self._supports_sizesum = False
        self._supports_parse_exif = False
        self._supports_composite_psd = False
        self._supports_replace_svg_colors = False
        self._supports_render_fluid_frame = False
        self._supports_parse_7z_list = False
        self._supports_pdf_select_words = False

        self._native_free_message = dll.faf_free_message
        self._native_free_message.argtypes = [c_void_p]
        self._native_free_message.restype = None

        try:
            dll.faf_version.argtypes = []
            dll.faf_version.restype = c_void_p
            self._supports_version = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_version = False

        try:
            dll.faf_scan_directory.argtypes = [c_char_p]
            dll.faf_scan_directory.restype = c_void_p
            self._native_scan_directory = dll.faf_scan_directory
            self._supports_scan = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_scan = False

        try:
            dll.faf_sort_entries.argtypes = [c_char_p, c_int]
            dll.faf_sort_entries.restype = c_void_p
            self._native_sort_entries = dll.faf_sort_entries
            self._supports_sort = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_sort = False

        try:
            dll.faf_highlight_text.argtypes = [c_char_p, c_char_p]
            dll.faf_highlight_text.restype = c_void_p
            self._native_highlight_text = dll.faf_highlight_text
            self._supports_highlight = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_highlight = False

        try:
            dll.faf_render_markdown.argtypes = [c_char_p]
            dll.faf_render_markdown.restype = c_void_p
            self._native_render_markdown = dll.faf_render_markdown
            self._supports_render_markdown = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_render_markdown = False

        try:
            # 流式三哈希：faf_hash_init() -> u64 句柄 / update(handle, chunk, len)
            # -> int / final(handle) -> JSON 指针（成功即销毁句柄）/ free(handle)
            # -> int（幂等）。句柄 0 为失败保留值，null/非法句柄不崩溃。
            dll.faf_hash_init.argtypes = []
            dll.faf_hash_init.restype = c_uint64
            dll.faf_hash_update.argtypes = [c_uint64, c_char_p, c_int]
            dll.faf_hash_update.restype = c_int
            dll.faf_hash_final.argtypes = [c_uint64]
            dll.faf_hash_final.restype = c_void_p
            dll.faf_hash_free.argtypes = [c_uint64]
            dll.faf_hash_free.restype = c_int
            self._native_hash_init = dll.faf_hash_init
            self._native_hash_update = dll.faf_hash_update
            self._native_hash_final = dll.faf_hash_final
            self._native_hash_free = dll.faf_hash_free
            self._supports_hash = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_hash = False

        try:
            # 文本编码探测：faf_detect_encoding(sample_ptr, len) -> JSON 指针。
            # 入参为调用方提供的原始字节样本（指针 + 长度，样本可含 NUL）。
            # 置信度 <0.5 时返回空 JSON "{}"；null 指针/负 len/空样本返回 null。
            dll.faf_detect_encoding.argtypes = [c_void_p, c_int]
            dll.faf_detect_encoding.restype = c_void_p
            self._native_detect_encoding = dll.faf_detect_encoding
            self._supports_detect_encoding = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_detect_encoding = False

        try:
            dll.faf_parse_font.argtypes = [c_char_p]
            dll.faf_parse_font.restype = c_void_p
            self._native_parse_font = dll.faf_parse_font
            self._supports_parse_font = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_parse_font = False

        try:
            dll.faf_copy_files.argtypes = [c_char_p, c_char_p, c_char_p]
            dll.faf_copy_files.restype = c_void_p
            self._native_copy_files = dll.faf_copy_files
            self._supports_copy = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_copy = False

        try:
            dll.faf_sum_directory_sizes.argtypes = [c_char_p]
            dll.faf_sum_directory_sizes.restype = c_void_p
            self._native_sum_directory_sizes = dll.faf_sum_directory_sizes
            self._supports_sizesum = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_sizesum = False

        try:
            dll.faf_parse_exif.argtypes = [c_char_p]
            dll.faf_parse_exif.restype = c_void_p
            self._native_parse_exif = dll.faf_parse_exif
            self._supports_parse_exif = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_parse_exif = False

        try:
            dll.faf_composite_psd.argtypes = [c_char_p]
            dll.faf_composite_psd.restype = c_void_p
            self._native_composite_psd = dll.faf_composite_psd
            self._supports_composite_psd = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_composite_psd = False

        try:
            dll.faf_replace_svg_colors.argtypes = [c_char_p, c_int, c_int]
            dll.faf_replace_svg_colors.restype = c_void_p
            self._native_replace_svg_colors = dll.faf_replace_svg_colors
            self._supports_replace_svg_colors = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_replace_svg_colors = False

        try:
            dll.faf_render_fluid_frame.argtypes = [
                c_int,
                c_int,
                c_char_p,
                c_int,
                c_double,
                c_char_p,
                POINTER(c_size_t),
            ]
            dll.faf_render_fluid_frame.restype = c_void_p
            self._native_render_fluid_frame = dll.faf_render_fluid_frame
            self._supports_render_fluid_frame = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_render_fluid_frame = False

        try:
            dll.faf_parse_7z_list.argtypes = [c_char_p, c_char_p, c_char_p]
            dll.faf_parse_7z_list.restype = c_void_p
            self._native_parse_7z_list = dll.faf_parse_7z_list
            self._supports_parse_7z_list = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_parse_7z_list = False

        try:
            dll.faf_pdf_select_words.argtypes = [c_char_p, c_char_p]
            dll.faf_pdf_select_words.restype = c_void_p
            self._native_pdf_select_words = dll.faf_pdf_select_words
            self._supports_pdf_select_words = True
        except Exception:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            self._supports_pdf_select_words = False

    def free_message(self, raw) -> None:
        """释放 Rust 侧堆分配的 JSON 字符串指针（null 安全）。

        Args:
            raw: ``faf_version``（及后续 JSON 导出）返回的原始指针；
                ``None`` / null 时直接返回。
        """
        try:
            if raw is None:
                return
            self._native_free_message(raw)
        except Exception:  # noqa: BLE001, S110  # broad catch intentional at ctypes FFI boundary; ignore intentional (ctypes FFI boundary)
            pass

    def version(self) -> Optional[dict]:
        """查询 faf_core 版本信息。

        Returns:
            Optional[dict]: 解析后的 ``{"version": ...}`` 字典；DLL 不可用、
                绑定缺失、返回空指针或内容非法时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_version:
            return None
        raw = None
        try:
            raw = self._dll.faf_version()
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            text = payload.decode("utf-8", errors="replace")
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                return None
            debug(f"faf_core 版本: {parsed}")
            return parsed
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"version 失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def _call_json_list_export(self, invoke) -> Optional[list]:
        """JSON 数组导出统一调用骨架：string_at 拷贝 → json 解析 → finally free。

        Args:
            invoke: 无参可调用对象，执行 native 调用并返回 ``c_void_p`` 指针
                （null 时 ctypes 返回 ``None``）。

        Returns:
            Optional[list]: 解析后的列表；失败/非法内容返回 ``None``
                （不抛异常）。
        """
        raw = None
        try:
            raw = invoke()
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            text = payload.decode("utf-8", errors="replace")
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                return None
            return parsed
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"faf_core JSON 数组导出失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def _call_json_object_export(self, invoke) -> Optional[dict]:
        """JSON 对象导出统一调用骨架：string_at 拷贝 → json 解析 → finally free。

        Args:
            invoke: 无参可调用对象，执行 native 调用并返回 ``c_void_p`` 指针
                （null 时 ctypes 返回 ``None``）。

        Returns:
            Optional[dict]: 解析后的字典；失败/非法内容返回 ``None``
                （不抛异常）。
        """
        raw = None
        try:
            raw = invoke()
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            text = payload.decode("utf-8", errors="replace")
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"faf_core JSON 对象导出失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def scan_directory(self, path: str) -> Optional[list]:
        """经 faf_core 扫描目录，返回 7 键条目字典列表（原始未排序）。

        Args:
            path: 待扫描目录绝对路径。

        Returns:
            Optional[list]: 条目字典列表；DLL 不可用、绑定缺失、native 失败
                或输出超 ``MAX_JSON_BYTES`` 时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_scan:
            return None
        encoded: bytes = path.encode("utf-8", errors="replace")
        return self._call_json_list_export(lambda: self._native_scan_directory(encoded))

    def sort_entries(self, entries: list, mode: int) -> Optional[list]:
        """经 faf_core 排序目录条目（8 种模式，与 Python ``_apply_sort`` 一致）。

        Args:
            entries: 7 键条目字典列表（原始未排序）。
            mode: 排序模式 0-7（``SORT_MODE_NAMES`` 语义）。

        Returns:
            Optional[list]: 排序后的条目字典列表；DLL 不可用、绑定缺失、
                序列化超限或 native 失败时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_sort:
            return None
        try:
            payload: str = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
            if len(payload.encode("utf-8", errors="replace")) > MAX_JSON_BYTES:
                return None
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"sort_entries 序列化失败: {e}")
            return None
        encoded: bytes = payload.encode("utf-8", errors="replace")
        return self._call_json_list_export(lambda: self._native_sort_entries(encoded, int(mode)))

    def highlight_text(self, language: str, text: str) -> Optional[list]:
        """经 faf_core 高亮代码文本，返回 span 列表 ``[{start,len,token_type}]``。

        ``start``/``len`` 为**字符偏移**（非 byte），``token_type`` 索引
        1-16 与 Python ``TokenType`` 枚举顺序精确对齐（见
        ``freeassetfilter/utils/syntax_highlighter.py:76-93``）。颜色/主题
        不跨 FFI——调用方自行用 token_type 索引映射配色。

        Args:
            language: 应用语言名（如 ``'python'``/``'json'``）。
            text: 待高亮代码文本（含换行，整块高亮跨行状态保持）。

        Returns:
            Optional[list]: span 字典列表；DLL 不可用、绑定缺失、native
                失败/返回 null（含逐语言回退 -6）、序列化超限或非法 span
                形状时返回 ``None``（不抛异常，调用方回退 Python 引擎）。
        """
        if not self.available or not self._supports_highlight:
            return None
        if not isinstance(language, str) or not isinstance(text, str):
            return None
        lang_b: bytes = language.encode("utf-8", errors="replace")
        text_b: bytes = text.encode("utf-8", errors="replace")
        raw = self._call_json_list_export(
            lambda: self._native_highlight_text(lang_b, text_b)
        )
        if raw is None:
            return None
        # span 形状校验：任一 item 缺键/非 int → 整单丢弃（malformed 输入回退）。
        for item in raw:
            if not isinstance(item, dict):
                return None
            if not all(isinstance(item.get(key), int) for key in ("start", "len", "token_type")):
                return None
        return raw

    def render_markdown(self, text: str) -> Optional[dict]:
        """经 faf_core 渲染 Markdown 文本，返回 ``{"html": "<body 片段>"}``。

        native 产物是 **body 片段**（不含 ``<html>/<head>/<style>``，无任何
        颜色/CSS——主题 CSS 由调用方 ``_build_css`` 注入）。支持
        tables/footnotes/tasklists/strikethrough/fenced_code（内嵌 syntect
        高亮）；admonition/def_list/abbr/toc 语法按普通段落降级；损坏输入
        不 panic 仍返回可渲染 body。``html`` 字段为空串合法（空文本输入）。

        Args:
            text: Markdown 源文本。

        Returns:
            Optional[dict]: ``{"html": ...}``（body 片段）；DLL 不可用、
                绑定缺失、native 失败/返回 null/非法载荷（非 ``{"html": str}``
                形状）时返回 ``None``（不抛异常，调用方回退 python-markdown）。
        """
        if not self.available or not self._supports_render_markdown:
            return None
        if not isinstance(text, str):
            return None
        raw = None
        try:
            raw = self._native_render_markdown(text.encode("utf-8", errors="replace"))
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if not isinstance(parsed, dict):
                return None
            if not isinstance(parsed.get("html"), str):
                return None
            return parsed
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"render_markdown 失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def copy_files(self, sources: list, dest_dir: str) -> Optional[dict]:
        """经 faf_core 批量复制文件/目录到目标目录（todo 27/29 接线）。

        native 语义与 Python ``FilePoolLayout.copy_files`` 对齐：文件
        ``shutil.copy2``（内容 + mtime/权限）、目录 ``shutil.copytree(
        dirs_exist_ok=True)``（递归、跟随符号链接）；≤32 源/批内部 rayon
        并行；单源失败记入 ``failed`` 不中断整批。**目标名 = 源文件名**
        （冲突改名保持在调用方 Python 侧 dispatch 前完成）。

        Args:
            sources: 源路径字符串列表（目录/文件均可）。
            dest_dir: 目标目录绝对路径。

        Returns:
            Optional[dict]: ``{"copied": [{"src","dst","size"}], "failed":
            [{"src","error"}]}``；DLL 不可用、绑定缺失、native 失败/返回
            null、序列化超限或非法载荷（非上述形状）时返回 ``None``
            （不抛异常，调用方回退 Python 复制路径）。
        """
        if not self.available or not self._supports_copy:
            return None
        if not isinstance(sources, list) or not isinstance(dest_dir, str):
            return None
        try:
            payload: str = json.dumps(
                [str(s) for s in sources], ensure_ascii=False, separators=(",", ":")
            )
            if len(payload.encode("utf-8", errors="replace")) > MAX_JSON_BYTES:
                return None
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"copy_files 序列化失败: {e}")
            return None
        sources_b: bytes = payload.encode("utf-8", errors="replace")
        dest_b: bytes = dest_dir.encode("utf-8", errors="replace")
        opts_b: bytes = b"{}"
        parsed = self._call_json_object_export(
            lambda: self._native_copy_files(sources_b, dest_b, opts_b)
        )
        if parsed is None:
            return None
        # 形状校验：copied/failed 必须为列表（malformed 输入回退）。
        if not isinstance(parsed.get("copied"), list) or not isinstance(
            parsed.get("failed"), list
        ):
            return None
        return parsed

    def sum_directory_sizes(self, paths: list) -> Optional[dict]:
        """经 faf_core 单遍递归聚合目录大小（todo 27/29 接线）。

        native 语义与 Python ``staging_pool_service._iter_file_entries``
        对齐：单遍 walk、**``follow_symlinks=False``**、rayon 顶层并行；
        缺失/不可读/非目录路径记入对应 ``error`` 字段，不中断其它路径。

        Args:
            paths: 目录绝对路径字符串列表。

        Returns:
            Optional[dict]: ``{"results": [{"path","size","error"}]}``
            （成功 ``error`` 为 ``None``）；DLL 不可用、绑定缺失、native
            失败/返回 null、序列化超限或非法载荷（非上述形状）时返回
            ``None``（不抛异常，调用方回退 Python ``os.scandir`` walk）。
        """
        if not self.available or not self._supports_sizesum:
            return None
        if not isinstance(paths, list):
            return None
        try:
            payload: str = json.dumps(
                [str(p) for p in paths], ensure_ascii=False, separators=(",", ":")
            )
            if len(payload.encode("utf-8", errors="replace")) > MAX_JSON_BYTES:
                return None
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"sum_directory_sizes 序列化失败: {e}")
            return None
        paths_b: bytes = payload.encode("utf-8", errors="replace")
        parsed = self._call_json_object_export(
            lambda: self._native_sum_directory_sizes(paths_b)
        )
        if parsed is None:
            return None
        # 形状校验：results 必须为列表（malformed 输入回退）。
        if not isinstance(parsed.get("results"), list):
            return None
        return parsed

    def parse_font(self, path: str) -> Optional[dict]:
        """经 faf_core 解析字体文件（ttf-parser），返回字段字典。

        JSON 契约（与 ``font.rs::parse_font_impl`` 对齐）：
        ``{"name1".."name6","format","glyph_count","ascent","descent","line_gap"}``
        ——name 表 1/2/3/4/5/6（镜像 Python ``_font_name_rows`` 的逐记录
        UTF-8→latin-1 解码链 + 首记录优先 + seen 去重，缺失键为 ``None``），
        ``format`` 为 ``"TrueType"``/``"OpenType/CFF"``，
        ``glyph_count``/``ascent``/``descent``/``line_gap`` 为 **raw 原值**
        （ttf-parser 读 hhea/maxp 表，与 fontTools ``font["hhea"]``/``maxp``
        原值逐字节一致，非统一缩放值）。

        WOFF/WOFF2（todo 1 裁决：ttf-parser 不支持，回退 fontTools）、
        损坏字体、空文件、缺失文件、超限文件 → native 返回 null → 本方法
        返回 ``None``（不抛异常，调用方回退 fontTools 路径）。

        Args:
            path: 字体文件绝对路径。

        Returns:
            Optional[dict]: 上述字段字典；DLL 不可用、绑定缺失、native
                失败/返回 null 或非法载荷（非 dict）时返回 ``None``。
        """
        if not self.available or not self._supports_parse_font:
            return None
        if not isinstance(path, str):
            return None
        raw = None
        try:
            raw = self._native_parse_font(path.encode("utf-8", errors="replace"))
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if not isinstance(parsed, dict):
                return None
            return parsed
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"parse_font 失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def hash_file_streaming(
        self,
        path: str,
        progress: Optional[Callable[[int], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> Optional[dict]:
        """经 faf_core 流式计算文件三哈希（MD5/SHA1/SHA256）。

        **Python 侧持 I/O 循环**（语义对齐
        ``freeassetfilter.services.file_info_service.compute_hashes``）：
        256KiB ``f.read`` 分块 → 逐块 ``faf_hash_update``；每累计 1MiB 触发
        一次 ``progress``（0-100 整数）；**每块读取前**探测 ``should_stop``，
        取消时**返回已读部分的结果**（不补发 100% 进度）；正常完成时补发
        ``progress(100)``。文件句柄与 Rust 注册表句柄均在 ``finally`` 中
        清理（含异常路径）。

        Args:
            path: 目标文件绝对路径。
            progress: 可选进度回调（工作线程执行）。
            should_stop: 可选取消回调（每块前探测；True → 提前终结并返回
                部分结果，调用方据此丢弃缓存写入）。

        Returns:
            Optional[dict]: ``{"MD5": .., "SHA1": .., "SHA256": ..}``；DLL
                不可用、绑定缺失、文件缺失/OSError、native 失败或非法载荷
                时返回 ``None``（不抛异常，调用方回退 ``compute_hashes``）。
        """
        if not self.available or not self._supports_hash:
            return None
        handle: Optional[int] = None
        try:
            total = os.path.getsize(path)
            handle = self._native_hash_init()
            if not handle:
                return None
            read_bytes = 0
            with open(path, "rb") as f:
                while True:
                    if should_stop is not None and should_stop():
                        break
                    chunk = f.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    if self._native_hash_update(handle, chunk, len(chunk)) != 0:
                        return None
                    read_bytes += len(chunk)
                    if (
                        progress is not None
                        and total > 0
                        and read_bytes % HASH_PROGRESS_GRANULARITY == 0
                    ):
                        progress(int(read_bytes * 100 / total))
            raw = self._native_hash_final(handle)
            handle = None  # final 成功即销毁句柄（注册表移除）
            if not raw:
                return None
            try:
                payload = ctypes.string_at(raw)
                if not payload:
                    return None
                parsed = json.loads(payload.decode("utf-8", errors="replace"))
                if not isinstance(parsed, dict):
                    return None
                if not all(
                    isinstance(parsed.get(k), str) for k in ("MD5", "SHA1", "SHA256")
                ):
                    return None
                # 正常完成补发 100%；取消（should_stop 已为 True）不发，让进度停在取消点。
                if progress is not None and (should_stop is None or not should_stop()):
                    progress(100)
                return parsed
            finally:
                self.free_message(raw)
        except OSError:
            return None
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"hash_file_streaming 失败: {e}")
            return None
        finally:
            if handle is not None:
                try:
                    self._native_hash_free(handle)
                except Exception:  # noqa: BLE001, S110  # ignore intentional (cleanup best-effort)
                    pass

    def detect_encoding(self, data: bytes) -> Optional[dict]:
        """经 faf_core 探测文本编码（chardetng），返回探测结果字典。

        native 只吃调用方提供的原始字节样本——不做文件 I/O、不读磁盘，
        I/O 由调用方（``file_info_service`` / 文本预览器）按各自采样窗口
        （1KB/4KB/全文件）负责。返回值语义：

        * ``{"encoding": "gbk", "confidence": 0.98}``：置信度 ≥0.5 的探测
          结果（``encoding`` 为 encoding_rs 小写名称，``bytes.decode`` 可直用）；
        * ``{}``：native 置信度 <0.5（含 chardetng 否决信号）——调用方
          据此走 ``utf-8 → latin-1`` 回退链（计划 C6 / todo 25 明文）；
        * ``None``：DLL 不可用、绑定缺失、非 ``bytes``/空样本入参、
          native 返回 null（空样本/守卫失败/panic）、返回内容非法或解析
          失败——调用方回退 chardet 现状（不抛异常）。

        Args:
            data: 待探测的原始字节样本。

        Returns:
            Optional[dict]: ``{"encoding","confidence"}`` 或 ``{}``；失败为
                ``None``。
        """
        if not self.available or not self._supports_detect_encoding:
            return None
        if not isinstance(data, bytes) or not data:
            return None
        raw = None
        try:
            # create_string_buffer 按字节逐字拷贝（含内嵌 NUL），c_void_p 取
            # 起始地址直传；argtypes [c_void_p, c_int] 保证不截断样本。
            buf = ctypes.create_string_buffer(data)
            raw = self._native_detect_encoding(ctypes.cast(buf, c_void_p), len(data))
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            parsed = json.loads(payload.decode("utf-8", errors="replace"))
            if not isinstance(parsed, dict):
                return None
            # 形状校验：非空 dict 必须含 encoding(str) + confidence(数)。
            # malformed 输入（缺键/错型）→ None 回退。
            if parsed:
                if not isinstance(parsed.get("encoding"), str):
                    return None
                confidence = parsed.get("confidence")
                if not isinstance(confidence, (int, float)):
                    return None
            return parsed
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"detect_encoding 失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def parse_exif(self, path: str) -> Optional[dict]:
        """经 faf_core 解析图片 EXIF 元数据（rust-hot-path-native-migration）。

        JSON 契约（与 Rust ``exif::parse_exif_impl`` 对齐，todo 6 已核验）：
        ``{"common": ["label: value",...], "rest": ["label: value",...]}``——
        每行为已连接的 ``"label: value"`` 单串（exifread 键无冒号 → 标签即
        完整键、common 恒空）。对应 Python oracle ``_collect_exif`` 的
        ``(common, rest)`` 两组行（常用子集 + 文件内顺序平铺），接线侧经
        ``_split_exif_native_row`` 切回二元组。

        todo 2 占位期 native 返回 null（``STATUS_UNSUPPORTED``）→ 本方法返回
        ``None``，调用方（todo 7 接线）回退 exifread 路径。

        Args:
            path: 图片文件绝对路径。

        Returns:
            Optional[dict]: ``{"common","rest"}`` 两组行；DLL 不可用、绑定
                缺失、native 失败/返回 null 或非法载荷（非 dict 或缺列表键）
                时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_parse_exif:
            return None
        if not isinstance(path, str):
            return None
        parsed = self._call_json_object_export(
            lambda: self._native_parse_exif(path.encode("utf-8", errors="replace"))
        )
        if parsed is None:
            return None
        # 形状校验：common/rest 必须为列表（malformed 载荷回退）。
        if not isinstance(parsed.get("common"), list) or not isinstance(
            parsed.get("rest"), list
        ):
            return None
        return parsed

    def composite_psd(self, path: str) -> Optional[dict]:
        """经 faf_core 合成 PSD 图层（rust-hot-path-native-migration）。

        **spike 裁决 DROP**（task-1-decisions.md §3）：Rust ``psd`` crate 无法
        等价 ``psd-tools .composite()``（混合模式/蒙版不应用），Rust 侧恒返回
        ``STATUS_UNSUPPORTED`` → null → 本方法恒返回 ``None``，Python 保持
        ``_decode_psd``（``image_decoder_service.py:324-``）路径。本方法仅供
        能力探测与 todo 9 接线预留，禁止降级为错误的合成结果。

        Args:
            path: PSD 文件绝对路径。

        Returns:
            Optional[dict]: 合成结果 JSON；DLL 不可用、绑定缺失、native
                失败/返回 null 时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_composite_psd:
            return None
        if not isinstance(path, str):
            return None
        return self._call_json_object_export(
            lambda: self._native_composite_psd(path.encode("utf-8", errors="replace"))
        )

    def replace_svg_colors(
        self,
        svg_text: str,
        invert_white_to_black: bool,
        force_black_to_base: bool,
    ) -> Optional[str]:
        """经 faf_core 替换 SVG 图标颜色（rust-hot-path-native-migration）。

        **返回裸 SVG 文本（非 JSON）**——契约与 ``svg_renderer._replace_svg_colors``
        （``freeassetfilter/core/preview/svg_renderer.py:68-137``）对齐：18 条
        正则替换顺序 + ``_convert_rgba_to_hex``/``rgba_to_hex`` 语义（todo 11
        填实现）。返回指针经 ``faf_free_message`` 释放（与 JSON 导出同分配
        契约——Rust 侧 ``alloc_json_message`` 分配）。

        todo 2 占位期 native 返回 null（``STATUS_UNSUPPORTED``）→ 本方法返回
        ``None``，调用方（todo 12 接线）回退 Python 换色。

        Args:
            svg_text: 待替换颜色的 SVG 源文本。
            invert_white_to_black: 白转黑开关。
            force_black_to_base: 黑强制转基础色开关。

        Returns:
            Optional[str]: 替换后的完整 SVG 文本；DLL 不可用、绑定缺失、
                native 失败/返回 null、非 str 入参时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_replace_svg_colors:
            return None
        if not isinstance(svg_text, str):
            return None
        raw = None
        try:
            raw = self._native_replace_svg_colors(
                svg_text.encode("utf-8", errors="replace"),
                int(bool(invert_white_to_black)),
                int(bool(force_black_to_base)),
            )
            if not raw:
                return None
            # 先 string_at 拷贝出字节，再在 finally 中释放 Rust 堆内存。
            payload = ctypes.string_at(raw)
            if not payload:
                return None
            return payload.decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"replace_svg_colors 失败: {e}")
            return None
        finally:
            if raw is not None:
                self.free_message(raw)

    def render_fluid_frame(
        self,
        width: int,
        height: int,
        palette_json: str,
        noise_seed: int,
        time: float,
        overlay_json: str,
    ) -> Optional[bytes]:
        """经 faf_core 渲染流体背景 CPU 帧（rust-hot-path-native-migration）。

        **返回 RGBA 像素缓冲（非 JSON）**——Rust 分配 ``c_void_p`` +
        ``*out_len``，本方法 ``string_at(raw, out_len)`` 拷贝为 ``bytes``。
        ``QPixmap``/``QImage`` 构造留在调用方（GUI 线程）。

        **spike 裁决 DROP**（task-1-decisions.md §6）：float ULP（``math.hypot``
        vs ``f64::hypot`` 差 1 ULP）令逐像素 parity 不可达，Rust 侧恒返回
        ``STATUS_UNSUPPORTED`` → null → 本方法恒返回 ``None``，Python 保持
        ``_styled_fluid_cpu.render_static_frame`` 路径。**无配套 free 导出**——
        占位期 Rust 永不分配缓冲，故本方法不释放 raw（``faf_free_message``
        只对 ``CString`` 分配有效，禁止用于裸缓冲）。

        Args:
            width: 帧宽（像素）。
            height: 帧高（像素）。
            palette_json: 调色板 JSON 串。
            noise_seed: 噪声种子（int）。
            time: 帧时间（float）。
            overlay_json: 叠加参数 JSON 串。

        Returns:
            Optional[bytes]: RGBA 像素缓冲（``width * height * 4`` 字节）；DLL
                不可用、绑定缺失、native 失败/返回 null、负/零尺寸或非法入参
                时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_render_fluid_frame:
            return None
        raw = None
        try:
            if width <= 0 or height <= 0:
                return None
            if not isinstance(palette_json, str) or not isinstance(overlay_json, str):
                return None
            out_len = ctypes.c_size_t(0)
            raw = self._native_render_fluid_frame(
                int(width),
                int(height),
                palette_json.encode("utf-8", errors="replace"),
                int(noise_seed),
                float(time),
                overlay_json.encode("utf-8", errors="replace"),
                ctypes.byref(out_len),
            )
            if not raw:
                return None
            size = int(out_len.value)
            if size <= 0:
                return None
            # RGBA 缓冲按 out_len 拷贝（含内嵌 NUL 字节）；占位期不可达。
            return ctypes.string_at(raw, size)
        except Exception as e:  # noqa: BLE001  # broad catch intentional at ctypes FFI boundary
            warning(f"render_fluid_frame 失败: {e}")
            return None

    def parse_7z_list(
        self, output: str, current_path: str, archive_path: str
    ) -> Optional[list]:
        """经 faf_core 解析 7z ``-slt`` 列表输出（rust-hot-path-native-migration）。

        JSON 契约（与 Rust ``archive::parse_7z_list_impl`` 对齐，todo 16 填
        实现）：条目 JSON 数组——对应 Python oracle ``py7z_core._parse_list_output``
        （``freeassetfilter/core/native/bridges/py7z_core.py:333-``）的 7 键
        条目（``name/path/is_dir/size/modified/suffix`` 等）。**7z.exe 子进程
        与编码重试保留在 Python**，本方法只吃 stdout 文本。

        todo 2 占位期 native 返回 null（``STATUS_UNSUPPORTED``）→ 本方法返回
        ``None``，调用方（todo 17 接线）回退 ``_parse_list_output``。

        Args:
            output: 7z 命令的 ``-slt`` 输出文本。
            current_path: 当前浏览路径（目录过滤基准）。
            archive_path: 压缩包路径（排除压缩包自身）。

        Returns:
            Optional[list]: 条目字典列表；DLL 不可用、绑定缺失、native
                失败/返回 null、非 str 入参或非法载荷（非列表/含非 dict 项）
                时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_parse_7z_list:
            return None
        if (
            not isinstance(output, str)
            or not isinstance(current_path, str)
            or not isinstance(archive_path, str)
        ):
            return None
        raw = self._call_json_list_export(
            lambda: self._native_parse_7z_list(
                output.encode("utf-8", errors="replace"),
                current_path.encode("utf-8", errors="replace"),
                archive_path.encode("utf-8", errors="replace"),
            )
        )
        if raw is None:
            return None
        # 形状校验：条目必须为字典（malformed 载荷回退）。
        for item in raw:
            if not isinstance(item, dict):
                return None
        return raw

    def pdf_select_words(
        self, words_json: str, selection_json: str
    ) -> Optional[list]:
        """经 faf_core 过滤 PDF 选区逐词（rust-hot-path-native-migration）。

        JSON 契约（与 Rust ``pdfsel::select_words_impl`` 对齐，todo 18 填
        实现）：选中词条目 JSON 数组——对应 Python oracle
        ``pdf_document_view.get_text_selection``（``pdf_document_view.py:616-745``）
        的 smart x-bound 过滤 + ``sort((page,block,line,word_no))``。**PyMuPDF
        ``get_text_words`` 取词保留在 Python**，Rust 只吃词表 + 选区参数。

        todo 2 占位期 native 返回 null（``STATUS_UNSUPPORTED``）→ 本方法返回
        ``None``，调用方（todo 19 接线）回退 Python 选区过滤。

        Args:
            words_json: 词表 JSON（PyMuPDF ``get_text_words`` 产物序列化）。
            selection_json: 选区参数 JSON（归一化矩形/拖拽方向等）。

        Returns:
            Optional[list]: 选中词条目列表；DLL 不可用、绑定缺失、native
                失败/返回 null、非 str 入参或非法载荷（非列表/含非 dict 项）
                时返回 ``None``（不抛异常）。
        """
        if not self.available or not self._supports_pdf_select_words:
            return None
        if not isinstance(words_json, str) or not isinstance(selection_json, str):
            return None
        raw = self._call_json_list_export(
            lambda: self._native_pdf_select_words(
                words_json.encode("utf-8", errors="replace"),
                selection_json.encode("utf-8", errors="replace"),
            )
        )
        if raw is None:
            return None
        # 形状校验：条目必须为字典（malformed 载荷回退）。
        for item in raw:
            if not isinstance(item, dict):
                return None
        return raw
