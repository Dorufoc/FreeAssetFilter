#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程/系统内存探针（P7.1）。

纯 ``ctypes``，**不 import Qt**，与 :mod:`platform_monitor` 同风格：

* 失败时返回字段全 ``None`` 的降级字典，**绝不抛异常**；
* 采样成本实测：``GetProcessMemoryInfo`` 约 1–2µs，可周期调用；
* 显存查询**故意不实现**：``IDXGIAdapter3::QueryVideoMemoryInfo`` 需要手工
  维护 COM vtable 索引，索引一变就是进程级崩溃（native access violation），
  而本仓库对此**零先例**且核显/RDP/沙箱降级路径未验证。按计划「显存只报告
  不门控」的口径，这里返回 ``available=False`` 并给出原因；显存压力改由
  :mod:`memory_budget` 的纹理硬上限控制。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Dict, Optional


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


class _MEMORYSTATUSEX(ctypes.Structure):
    """``MEMORYSTATUSEX``（kernel32）。"""

    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
_psapi = ctypes.WinDLL("psapi", use_last_error=True)  # type: ignore[attr-defined]
_bound = False


def _bind() -> None:
    """绑定 Win32 函数签名（幂等）。"""
    global _bound
    if _bound:
        return
    _kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    _kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    _kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    _psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    _bound = True


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
    try:
        _bind()
        counters = _PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS_EX)
        ok = _psapi.GetProcessMemoryInfo(
            _kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        if not ok:
            return result
        result["rss_bytes"] = int(counters.WorkingSetSize)
        result["private_bytes"] = int(counters.PrivateUsage)
        result["peak_rss_bytes"] = int(counters.PeakWorkingSetSize)
        result["pagefile_bytes"] = int(counters.PagefileUsage)
    except Exception:  # noqa: BLE001 - 探针失败不得影响业务
        return result
    return result


def read_system_memory() -> Dict[str, Optional[int]]:
    """读取系统物理内存。

    Returns:
        dict: ``total_phys_bytes`` / ``avail_phys_bytes`` / ``load_percent``；
            失败时全 ``None``。
    """
    result: Dict[str, Optional[int]] = {
        "total_phys_bytes": None,
        "avail_phys_bytes": None,
        "load_percent": None,
    }
    try:
        _bind()
        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return result
        result["total_phys_bytes"] = int(status.ullTotalPhys)
        result["avail_phys_bytes"] = int(status.ullAvailPhys)
        result["load_percent"] = int(status.dwMemoryLoad)
    except Exception:  # noqa: BLE001
        return result
    return result


def read_gpu_memory(adapter_index: int = 0) -> Dict[str, Any]:
    """显存查询（**当前为安全降级实现**）。

    不调用 ``IDXGIAdapter3::QueryVideoMemoryInfo``：手工 vtable 索引在
    Windows 版本/驱动差异下可能偏移，一旦偏移就是进程级崩溃，而本仓库
    对 DXGI COM 零先例。按计划口径「显存只报告不门控」，返回不可用。
    显存占用的真正约束由 :mod:`memory_budget` 的纹理硬上限承担。

    Args:
        adapter_index: 适配器序号（当前未使用，保留签名）。

    Returns:
        dict: ``{"available": False, "reason": ...}``。
    """
    del adapter_index
    return {
        "available": False,
        "reason": "DXGI QueryVideoMemoryInfo disabled (crash-safe fallback)",
        "dedicated_bytes": None,
        "shared_bytes": None,
        "usage_bytes": None,
    }


def snapshot() -> Dict[str, Any]:
    """一次采样进程 + 系统 + 显存（显存为降级字典）。

    Returns:
        dict: ``{"process": ..., "system": ..., "gpu": ...}``。
    """
    return {
        "process": read_process_memory(),
        "system": read_system_memory(),
        "gpu": read_gpu_memory(),
    }
