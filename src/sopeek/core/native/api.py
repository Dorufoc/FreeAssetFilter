#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""native 能力门面（P1.4）。

本模块是所有业务代码访问 ``spk_core`` 原生能力的**唯一入口**。目标：

* 调用方不再 ``getattr(bridge, "_supports_*")`` 读私有能力位——那会把
  桥的内部布局泄漏到 UI 层，且新增导出时每处都要跟着改；
* 能力探测与调用错误收敛到一处（FFI 边界防御只写一次）；
* 为 P2/P3 的契约收敛（POD / 句柄 / 回退计数）留出单一改造点。

设计约束（与 ``spk_core_bridge`` 的既有范式一致）：

* DLL 缺失 / 能力缺失 / native 抛异常 → 一律返回 ``None`` 或 ``False``，
  **绝不向上抛**，调用方据此回退 Python 实现；
* 惰性单例经桥模块的 ``get_spk_core_bridge`` 获取，本模块不重复缓存；
* 只暴露**动词**，不转发桥的全部内部状态（``spk_free_message`` 等仍在桥内）。

用法::

    from sopeek.core.native import api as native_api

    if native_api.supports("scan"):
        entries = native_api.scan_directory(path)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from sopeek.core.native.bridges.spk_core_bridge import (
    SpkCoreBridge,
    get_spk_core_bridge,
)

#: X6：GUI 线程单次 FFI 预算（ms）。超过即计一次 ``ui.main_thread_block``。
#: 默认开启（测量开销仅两次 ``perf_counter``），``SPK_MAIN_THREAD_GUARD=0`` 可关。
MAIN_THREAD_FFI_BUDGET_MS: float = 5.0
_MAIN_THREAD_GUARD_ENV: str = os.environ.get("SPK_MAIN_THREAD_GUARD", "1").strip()
_MAIN_THREAD_GUARD: bool = _MAIN_THREAD_GUARD_ENV not in {"0", "false", "off", "no"}

#: 能力名 → 桥上的私有能力位（本模块是唯一允许读这些位的地方）。
_CAPABILITY_FLAGS: Dict[str, str] = {
    "scan": "_supports_scan",
    "sort": "_supports_sort",
    "highlight": "_supports_highlight",
    "markdown": "_supports_render_markdown",
    "font": "_supports_parse_font",
    "hash": "_supports_hash",
    "encoding": "_supports_detect_encoding",
    "copy": "_supports_copy",
    "sizesum": "_supports_sizesum",
    "exif": "_supports_parse_exif",
    "svg": "_supports_replace_svg_colors",
    "7z": "_supports_parse_7z_list",
    "pdf": "_supports_pdf_select_words",
    "dirhandle": "_supports_dir_handle",
    "scanstream": "_supports_scan_stream",
    "abi": "_supports_abi_version",
}


def bridge() -> Optional[SpkCoreBridge]:
    """获取原生桥单例（DLL 缺失时返回降级实例，不抛异常）。

    Returns:
        Optional[SpkCoreBridge]: 桥实例；构造失败返回 ``None``。
    """
    try:
        return get_spk_core_bridge()
    except Exception:  # noqa: BLE001  # FFI 边界防御
        return None


def supports(capability: str) -> bool:
    """判断某个原生能力是否可用。

    Args:
        capability: 能力名，取值见 :data:`_CAPABILITY_FLAGS`。

    Returns:
        bool: DLL 可用且导出存在时为 ``True``；未知能力名返回 ``False``。
    """
    flag = _CAPABILITY_FLAGS.get(capability)
    if flag is None:
        return False
    inst = bridge()
    if inst is None or not inst.available:
        return False
    try:
        return bool(getattr(inst, flag, False))
    except Exception:  # noqa: BLE001  # FFI 边界防御
        return False


def _note_fallback(capability: str) -> None:
    """记录一次原生回退（P2.3：让回退可观测，而不是静默变慢）。"""
    try:
        from sopeek.utils import perf_metrics as pm

        pm.increment_global(f"native.fallback.{capability}")
    except Exception:  # noqa: BLE001 - 埋点不得影响业务
        pass


def _call(
    capability: str, method: str, *args: Any, **kwargs: Any
) -> Any:
    """能力探测 + 调用 + 异常收敛（所有包装函数的唯一实现）。

    X6：非主线程直接返回；在主线程且单次耗时超
    :data:`MAIN_THREAD_FFI_BUDGET_MS` 时记一条 ``ui.main_thread_block``
    （P99 验收用），并记一次 ``native.main_thread.slow.<capability>``。

    Args:
        capability: 能力名（用于 ``supports``）。
        method: 桥上的方法名。
        *args: 位置参数。
        **kwargs: 关键字参数。

    Returns:
        Any: native 返回值；能力缺失或调用失败返回 ``None``。
    """
    if not supports(capability):
        _note_fallback(capability)
        return None
    inst = bridge()
    if inst is None:
        _note_fallback(capability)
        return None
    started = time.perf_counter() if _MAIN_THREAD_GUARD else 0.0
    try:
        return getattr(inst, method)(*args, **kwargs)
    except Exception:  # noqa: BLE001  # FFI 边界防御
        _note_fallback(capability)
        return None
    finally:
        if _MAIN_THREAD_GUARD:
            _note_main_thread_cost(capability, time.perf_counter() - started)


def _note_main_thread_cost(capability: str, elapsed_s: float) -> None:
    """记录主线程上的长 FFI（X6 度量；非主线程/未超预算直接返回）。"""
    elapsed_ms = elapsed_s * 1000.0
    if elapsed_ms <= MAIN_THREAD_FFI_BUDGET_MS:
        return
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        from sopeek.utils import perf_metrics as pm

        pm.record_duration("ui.main_thread_block", elapsed_ms)
        pm.increment_global(f"native.main_thread.slow.{capability}")
    except Exception:  # noqa: BLE001 - 埋点不得影响业务
        pass


def scan_directory(path: str) -> Optional[List[Dict[str, Any]]]:
    """经原生扫描目录（7 键条目列表）。"""
    return _call("scan", "scan_directory", path)


def scan_begin(path: str) -> int:
    """打开流式扫描游标（P3.4）；失败返回 0。"""
    return int(_call("scanstream", "scan_begin", path) or 0)


def scan_next(handle: int, max_count: int) -> Optional[List[Dict[str, Any]]]:
    """读下一批（8 键：7 键 + ``attrs``）；非法句柄/失败返回 ``None``。"""
    return _call("scanstream", "scan_next", handle, max_count)


def scan_free(handle: int) -> bool:
    """关闭流式游标（幂等）。"""
    return bool(_call("scanstream", "scan_free", handle))


def sort_entries(
    entries: List[Dict[str, Any]], mode: int
) -> Optional[List[Dict[str, Any]]]:
    """经原生排序条目（8 种模式）。"""
    return _call("sort", "sort_entries", entries, mode)


def highlight_text(language: str, text: str) -> Optional[List[dict]]:
    """经原生做语法高亮（span-only，字符偏移）。"""
    return _call("highlight", "highlight_text", language, text)


def render_markdown(text: str) -> Optional[Dict[str, Any]]:
    """经原生渲染 Markdown（返回 ``{"html": ...}`` body 片段）。"""
    return _call("markdown", "render_markdown", text)


def parse_font(path: str) -> Optional[Dict[str, Any]]:
    """经原生解析字体文件（ttf-parser）。"""
    return _call("font", "parse_font", path)


def hash_file_streaming(
    path: str,
    progress: Optional[Callable[[int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Optional[Dict[str, str]]:
    """经原生流式计算三哈希（MD5/SHA1/SHA256）。"""
    return _call(
        "hash",
        "hash_file_streaming",
        path,
        progress=progress,
        should_stop=should_stop,
    )


def detect_encoding(data: bytes) -> Optional[Dict[str, Any]]:
    """经原生探测文本编码（chardetng）。"""
    return _call("encoding", "detect_encoding", data)


def copy_files(sources: List[str], dest_dir: str) -> Optional[Dict[str, Any]]:
    """经原生批量复制文件/目录到目标目录。"""
    return _call("copy", "copy_files", sources, dest_dir)


def sum_directory_sizes(paths: List[str]) -> Optional[Dict[str, Any]]:
    """经原生单遍递归聚合目录大小。"""
    return _call("sizesum", "sum_directory_sizes", paths)


def parse_exif(path: str) -> Optional[Dict[str, Any]]:
    """经原生解析图片 EXIF（kamadak-exif）。"""
    return _call("exif", "parse_exif", path)


def replace_svg_colors(
    svg_text: str,
    invert_white_to_black: bool,
    force_black_to_base: bool,
) -> Optional[str]:
    """经原生替换 SVG 图标颜色（返回裸 SVG 文本）。"""
    return _call(
        "svg",
        "replace_svg_colors",
        svg_text,
        invert_white_to_black,
        force_black_to_base,
    )


def parse_7z_list(
    output: str, current_path: str, archive_path: str
) -> Optional[List[Dict[str, Any]]]:
    """经原生解析 7z ``-slt`` 输出。"""
    return _call("7z", "parse_7z_list", output, current_path, archive_path)


def pdf_select_words(
    words_json: str, selection_json: str
) -> Optional[List[Dict[str, Any]]]:
    """经原生过滤 PDF 选区逐词。"""
    return _call("pdf", "pdf_select_words", words_json, selection_json)


def abi_version() -> Optional[Dict[str, Any]]:
    """查询 DLL 的 ABI 信息（P3.1 闸门）。"""
    if not supports("abi"):
        return None
    inst = bridge()
    return inst.abi_version() if inst is not None else None


def dir_open(path: str) -> int:
    """打开目录句柄（P3.2）；失败返回 0。"""
    if not supports("dirhandle"):
        return 0
    inst = bridge()
    return inst.dir_open(path) if inst is not None else 0


def dir_count(handle: int) -> int:
    """句柄条目数；非法句柄返回 -1。"""
    if not supports("dirhandle"):
        return -1
    inst = bridge()
    return inst.dir_count(handle) if inst is not None else -1


def dir_rows(handle: int, first: int, count: int) -> Optional[List[Dict[str, Any]]]:
    """取窗口行（P3.2）。"""
    if not supports("dirhandle"):
        return None
    inst = bridge()
    return inst.dir_rows(handle, first, count) if inst is not None else None


def dir_sort(handle: int, mode: int) -> int:
    """在句柄上原地排序。"""
    if not supports("dirhandle"):
        return -1
    inst = bridge()
    return inst.dir_sort(handle, mode) if inst is not None else -1


def dir_close(handle: int) -> bool:
    """关闭句柄（幂等）。"""
    if not supports("dirhandle"):
        return False
    inst = bridge()
    return inst.dir_close(handle) if inst is not None else False


def dir_next(handle: int, max_count: int) -> Optional[List[Dict[str, Any]]]:
    """流式游标取下一块（P3.4）。"""
    if not supports("dirhandle"):
        return None
    inst = bridge()
    return inst.dir_next(handle, max_count) if inst is not None else None


def dir_cancel(handle: int) -> bool:
    """取消句柄（P3.7）。"""
    if not supports("dirhandle"):
        return False
    inst = bridge()
    return inst.dir_cancel(handle) if inst is not None else False


def dir_rows_pod(handle: int, first: int, count: int) -> Optional[List[Dict[str, Any]]]:
    """POD 行通道（P3.3）：无 JSON 往返的窗口取行。"""
    if not supports("dirhandle"):
        return None
    inst = bridge()
    return inst.dir_rows_pod(handle, first, count) if inst is not None else None


def dir_sort_window(
    handle: int,
    mode: int,
    first: int,
    count: int,
    *,
    presort_name: bool = True,
) -> Optional[List[Dict[str, Any]]]:
    """句柄内排序 + 只取窗口行（P3.6，排序结果不回传）。"""
    if not supports("dirhandle"):
        return None
    inst = bridge()
    if inst is None:
        return None
    return inst.dir_sort_window(
        handle, mode, first, count, presort_name=presort_name
    )
