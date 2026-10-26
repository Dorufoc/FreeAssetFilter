# -*- coding: utf-8 -*-
"""P0.4 线程与内存基线：为 P6/P7 的预算器提供真实起点。

只读采集，不修改任何产品状态：

* **线程数**：``CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD)`` 按本进程 PID 统计；
  零第三方依赖，生产侧 ``core/pools.py`` 将复用同一实现。
* **内存**：``psapi.GetProcessMemoryInfo(PROCESS_MEMORY_COUNTERS_EX)`` 取
  RSS / PrivateUsage / PeakWorkingSet。
* **缓存声明值**：``QPixmapCache.cacheLimit()`` 与 ``ThumbnailManager`` 的
  硬编码常量（这些是 P7.2 三档预算要接管的对象）。
* **探针开销**：连续采样 100 次，确认探针本身不成为瓶颈（目标 < 50µs/次）。

产物：``build/bench/p04-thread-memory-baseline-<ts>.json``。

已知边界（写入报告，避免误读）：

* pytest 进程的线程数**不代表**产品进程（没有 MPV / 缩略图批 / 流体）；
  真实四态采样（空闲 / 200 图目录 / 批量视频 / 导出复制）在 P7 接真实应用后补。
* 显存（``IDXGIAdapter3::QueryVideoMemoryInfo``）在本仓库**零先例**，且核显 /
  RDP / 沙箱降级路径未验证——P0 阶段**不采集、不门控**，留到 P7.1。
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(120)]

#: 产物路径（P0.2 隔离：默认 build/bench/）。
_OUTPUT_ENV: str = os.environ.get("FAF_BENCH_OUTPUT", "").strip()
if _OUTPUT_ENV:
    _candidate: Path = Path(_OUTPUT_ENV)
    OUTPUT_PATH: Path = (
        _candidate / "p04-thread-memory-baseline.json"
        if (_candidate.is_dir() or not _candidate.suffix)
        else _candidate
    )
else:
    OUTPUT_PATH = (
        Path(__file__).resolve().parents[2]
        / "build"
        / "bench"
        / f"p04-thread-memory-baseline-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

#: ``CreateToolhelp32Snapshot`` 的线程快照标志。
TH32CS_SNAPTHREAD: int = 0x00000004
#: ``INVALID_HANDLE_VALUE``（64 位下为全 1）。
_INVALID_HANDLE: int = ctypes.c_void_p(-1).value or 0
#: 线程计数缓存 TTL（秒）。Toolhelp32 需枚举全系统线程（实测约 90ms/次），
#: 因此生产侧**不得**做周期性调用；缓存命中开销必须接近零。
_THREAD_CACHE_TTL_S: float = 5.0
_THREAD_CACHE: Dict[str, Any] = {"timestamp": 0.0, "value": None}


class _THREADENTRY32(ctypes.Structure):
    """Win32 ``THREADENTRY32`` 结构体（仅字段布局，语义见 MSDN）。"""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    """``PROCESS_MEMORY_COUNTERS_EX``（psapi）。"""

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
_PSAPI = ctypes.WinDLL("psapi", use_last_error=True)  # type: ignore[attr-defined]


def _bind_win32() -> None:
    """绑定一次函数签名（避免每次调用重设 argtypes）。"""
    _KERNEL32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    _KERNEL32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _KERNEL32.Thread32First.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_THREADENTRY32),
    ]
    _KERNEL32.Thread32First.restype = wintypes.BOOL
    _KERNEL32.Thread32Next.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_THREADENTRY32),
    ]
    _KERNEL32.Thread32Next.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetCurrentProcess.restype = ctypes.c_void_p
    _PSAPI.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    _PSAPI.GetProcessMemoryInfo.restype = wintypes.BOOL


_bind_win32()


def _count_process_threads_uncached() -> Optional[int]:
    """按本进程 PID 统计线程数（无缓存，实测约 90ms/次）。

    Returns:
        Optional[int]: 线程数；快照失败返回 ``None``（不抛异常）。
    """
    snapshot: Optional[int] = _KERNEL32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == _INVALID_HANDLE:
        return None
    entry = _THREADENTRY32()
    entry.dwSize = ctypes.sizeof(_THREADENTRY32)
    pid: int = os.getpid()
    count: int = 0
    try:
        if not _KERNEL32.Thread32First(snapshot, ctypes.byref(entry)):
            return None
        while True:
            if entry.th32OwnerProcessID == pid:
                count += 1
            if not _KERNEL32.Thread32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        _KERNEL32.CloseHandle(snapshot)
    return count


def count_process_threads(use_cache: bool = True) -> Optional[int]:
    """统计本进程线程数（默认带 5s TTL 缓存）。

    Toolhelp32 需要枚举全系统所有进程的线程，实测约 90ms/次；因此
    ``core/pools.py`` 只能在**显式诊断**（如 ``snapshot()``）时调用，
    绝不进入周期性心跳。

    Args:
        use_cache: 是否使用 TTL 缓存（探针开销自检时传 ``False``）。

    Returns:
        Optional[int]: 线程数；快照失败返回 ``None``。
    """
    now: float = time.monotonic()
    if use_cache and (now - float(_THREAD_CACHE["timestamp"])) < _THREAD_CACHE_TTL_S:
        return _THREAD_CACHE["value"]
    value: Optional[int] = _count_process_threads_uncached()
    _THREAD_CACHE["timestamp"] = now
    _THREAD_CACHE["value"] = value
    return value


def read_process_memory() -> Dict[str, Optional[int]]:
    """读取本进程内存计数。

    Returns:
        dict: ``rss_bytes`` / ``private_bytes`` / ``peak_rss_bytes`` /
            ``pagefile_bytes``；失败时各字段为 ``None``。
    """
    result: Dict[str, Optional[int]] = {
        "rss_bytes": None,
        "private_bytes": None,
        "peak_rss_bytes": None,
        "pagefile_bytes": None,
    }
    counters = _PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
    ok = _PSAPI.GetProcessMemoryInfo(
        _KERNEL32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    )
    if not ok:
        return result
    result["rss_bytes"] = int(counters.WorkingSetSize)
    result["private_bytes"] = int(counters.PrivateUsage)
    result["peak_rss_bytes"] = int(counters.PeakWorkingSetSize)
    result["pagefile_bytes"] = int(counters.PagefileUsage)
    return result


def _cache_declarations() -> Dict[str, Any]:
    """读取各缓存池的硬编码声明值（P7.2 预算器要接管的对象）。"""
    declarations: Dict[str, Any] = {}
    try:
        from PySide6.QtGui import QPixmapCache

        declarations["qpixmap_cache_kb"] = int(QPixmapCache.cacheLimit())
    except Exception as exc:  # noqa: BLE001 - 无 Qt 环境时降级
        declarations["qpixmap_cache_kb"] = f"unavailable: {exc}"

    try:
        from freeassetfilter.core.managers.thumbnail_manager import ThumbnailManager

        declarations.update(
            {
                "thumb_disk_cache_bytes": int(ThumbnailManager.MAX_THUMB_CACHE_SIZE),
                "thumb_disk_cache_files": int(ThumbnailManager.MAX_THUMB_CACHE_FILES),
                "frame_cache_groups": int(ThumbnailManager.MAX_FRAME_CACHE_GROUPS),
                "frame_cache_bytes": int(ThumbnailManager.MAX_FRAME_CACHE_BYTES),
                "frame_cache_bytes_per_group": int(
                    ThumbnailManager.MAX_FRAME_CACHE_BYTES_PER_GROUP
                ),
                "svg_cache_entries": int(ThumbnailManager.MAX_SVG_CACHE_ENTRIES),
                "path_exists_cache_entries": int(
                    ThumbnailManager.PATH_EXISTS_CACHE_MAX_ENTRIES
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001 - 依赖缺失时降级
        declarations["thumbnail_manager"] = f"unavailable: {exc}"

    try:
        from freeassetfilter.services.file_icon_manager import FileIconManager

        declarations["icon_cache_entries"] = int(FileIconManager._ICON_CACHE_MAX_ENTRIES)
        declarations["system_icon_cache_entries"] = int(
            FileIconManager._SYSTEM_ICON_CACHE_MAX_ENTRIES
        )
    except Exception as exc:  # noqa: BLE001
        declarations["file_icon_manager"] = f"unavailable: {exc}"

    try:
        from freeassetfilter.ui.components.file_card_delegate import (
            _ICON_SCALE_CACHE_CAP,
        )

        declarations["icon_scale_cache_entries"] = int(_ICON_SCALE_CACHE_CAP)
    except Exception as exc:  # noqa: BLE001
        declarations["file_card_delegate"] = f"unavailable: {exc}"

    return declarations


def _machine_summary() -> Dict[str, Any]:
    """机器指纹。"""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
    }


def _probe_overhead_ms(iterations: int = 100) -> Dict[str, float]:
    """测量探针自身开销（冷路径 vs 缓存命中 vs 内存读取）。"""
    cold_start: float = time.perf_counter()
    _count_process_threads_uncached()
    cold_ms: float = (time.perf_counter() - cold_start) * 1000.0

    # 先填充缓存，再测命中路径。
    count_process_threads(use_cache=True)
    cached_start: float = time.perf_counter()
    for _ in range(iterations):
        count_process_threads(use_cache=True)
    cached_us: float = (time.perf_counter() - cached_start) / iterations * 1_000_000.0

    memory_start: float = time.perf_counter()
    for _ in range(iterations):
        read_process_memory()
    memory_us: float = (time.perf_counter() - memory_start) / iterations * 1_000_000.0

    return {
        "thread_cold_ms": round(cold_ms, 3),
        "thread_cached_us": round(cached_us, 3),
        "memory_read_us": round(memory_us, 3),
    }


def test_p04_thread_memory_baseline(qapp: Any) -> None:
    """采集线程/内存/缓存声明值基线并落盘。"""
    del qapp  # 仅用于确保 QApplication 已创建（QPixmapCache 可用）

    # 稳定期：让导入期的瞬时线程退出后再采样。
    time.sleep(0.2)

    samples: List[Dict[str, Optional[int]]] = []
    thread_samples: List[Optional[int]] = []
    for _ in range(5):
        samples.append(read_process_memory())
        thread_samples.append(count_process_threads(use_cache=False))
        time.sleep(0.02)

    rss_values: List[int] = [s["rss_bytes"] for s in samples if s["rss_bytes"]]
    thread_values: List[int] = [t for t in thread_samples if t is not None]

    baseline: Dict[str, Any] = {
        "schema": "faf-thread-memory-baseline/v1",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": _machine_summary(),
        "process_threads": {
            "samples": thread_samples,
            "min": min(thread_values) if thread_values else None,
            "max": max(thread_values) if thread_values else None,
            "note": "pytest 进程，不含 MPV/缩略图批/流体；真实四态在 P7 补",
        },
        "process_memory": {
            "samples": samples,
            "rss_min_bytes": min(rss_values) if rss_values else None,
            "rss_max_bytes": max(rss_values) if rss_values else None,
        },
        "cache_declarations": _cache_declarations(),
        "probe_overhead": _probe_overhead_ms(),
        "probe_policy": {
            "thread_count": "仅显式诊断（pools.snapshot）时采样；90ms/次，不得进入周期心跳",
            "memory_read": "可直接周期采样（µs 级）",
            "cache_ttl_s": _THREAD_CACHE_TTL_S,
        },
        "qt_version": _qt_version(),
        "known_gaps": [
            "显存（IDXGIAdapter3::QueryVideoMemoryInfo）未采集：仓库零先例，核显/RDP 降级未验证",
            "真实四态线程（空闲/200 图目录/批量视频/导出复制）需接真实应用后在 P7 补",
            "QPixmapCache 不暴露实际占用，只能记录声明上限",
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"\n[P0.4] threads={thread_values} rss={rss_values} "
        f"probe={baseline['probe_overhead']}",
        flush=True,
    )
    print(f"[P0.4] 结果已写入 {OUTPUT_PATH}", flush=True)

    # 硬约束：缓存命中必须足够便宜（周期采样不成立，只能按需）；
    # 冷路径写入报告供 P6.2 决定采样频次。
    assert baseline["probe_overhead"]["thread_cached_us"] < 50.0
    assert baseline["probe_overhead"]["memory_read_us"] < 50.0
    assert baseline["probe_overhead"]["thread_cold_ms"] < 300.0
    assert thread_values, "线程计数探针失效（返回 None）"
    assert rss_values, "内存探针失效（返回 None）"


def _qt_version() -> str:
    """返回 PySide6 / Qt 版本字符串（失败返回 unknown）。"""
    try:
        import PySide6

        return f"PySide6 {PySide6.__version__} / Qt {PySide6.QtCore.qVersion()}"
    except Exception as exc:  # noqa: BLE001
        return f"unknown: {exc}"
