#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 盘符检测服务模块
提供系统盘符枚举与可用性检查功能，从 file_selector.py 的 DriveListLoaderThread
与 _DriveAvailabilityCheckRunnable 中提取的纯业务逻辑。
"""

import ctypes
import os
import sys
import threading
from typing import List

from freeassetfilter.services.base import BaseService


class DriveService(BaseService):
    """系统盘符枚举与可用性检查服务。

    线程安全的单例服务，封装了 Windows 盘符检测逻辑：
      - list_drives(): 枚举当前系统所有可用盘符
      - check_availability(): 检测指定盘符是否可访问

    使用示例：

        service = DriveService()
        service.initialize()
        drives = service.list_drives()          # ["C:", "D:", "E:"]
        ok = service.check_availability("C:")   # True
    """

    _instance: "DriveService | None" = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._initialized = True
            super().__init__()

    # ------------------------------------------------------------------
    # BaseService 抽象方法实现
    # ------------------------------------------------------------------

    def _do_initialize(self) -> None:
        """DriveService 无需额外的初始化资源，此方法仅占位。"""
        pass

    def _do_dispose(self) -> None:
        """DriveService 无需清理的资源，此方法仅占位。"""
        pass

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def list_drives(self) -> List[str]:
        """枚举当前系统存在的所有盘符。

        在 Windows 上通过 ``GetLogicalDrives()`` 获取可用盘符；
        在其他平台（Linux/macOS）返回 ``["/"]``。

        Returns:
            List[str]: 排序后的盘符列表，例如 ``["C:", "D:", "E:"]``。
        """
        local_drives: List[str] = []
        network_locations: List[str] = []

        if sys.platform == "win32":
            local_drives = self._list_windows_drives()
            network_locations = self._list_windows_network_locations()
        else:
            local_drives = ["/"]

        # 合并本地盘符与网络位置，去重并排序
        all_drives = list(set(local_drives + network_locations))
        all_drives.sort()
        return all_drives

    def check_availability(self, drive: str) -> bool:
        """检查指定盘符是否可访问。

        规范化路径后使用 ``os.path.exists()`` 配合 ``os.scandir()``
        验证盘符是否可读。空目录视为可用。

        Args:
            drive: 盘符路径，例如 ``"C:"`` 或 ``"D:\\"``。

        Returns:
            bool: 盘符可访问返回 True，否则返回 False。
        """
        drive_path = drive
        if not drive_path.endswith(("\\", "/")):
            drive_path = drive_path + "\\"

        available = False
        try:
            if os.path.exists(drive_path):
                with os.scandir(drive_path) as it:
                    next(it, None)
                available = True
        except StopIteration:
            # 空目录——仍然可用
            available = True
        except (OSError, PermissionError):
            available = False
        except Exception:
            available = False
        return available

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    @staticmethod
    def _list_windows_drives() -> List[str]:
        """通过 Win32 API ``GetLogicalDrives()`` 获取本地逻辑盘符。"""
        drives: List[str] = []
        try:
            kernel32 = ctypes.windll.kernel32
            drives_bitmask = kernel32.GetLogicalDrives()
            for drive in range(26):
                if drives_bitmask & (1 << drive):
                    drives.append(chr(65 + drive) + ":")
        except Exception:
            # 静默失败，返回空列表
            pass
        return drives

    @staticmethod
    def _list_windows_network_locations() -> List[str]:
        """通过 Win32 API ``WNetOpenEnumW`` / ``WNetEnumResourceW`` 枚举网络位置。

        Returns:
            List[str]: 网络位置列表（包括映射为盘符的网络驱动器和 UNC 路径）。
        """
        locations: List[str] = []
        try:
            from ctypes import wintypes

            mpr = ctypes.WinDLL("mpr")

            class NETRESOURCE(ctypes.Structure):
                _fields_ = [
                    ("dwScope", wintypes.DWORD),
                    ("dwType", wintypes.DWORD),
                    ("dwDisplayType", wintypes.DWORD),
                    ("dwUsage", wintypes.DWORD),
                    ("lpLocalName", wintypes.LPWSTR),
                    ("lpRemoteName", wintypes.LPWSTR),
                    ("lpComment", wintypes.LPWSTR),
                    ("lpProvider", wintypes.LPWSTR),
                ]

            resource_connected = 1
            resource_type_any = 0
            h_enum = wintypes.HANDLE()

            if (
                mpr.WNetOpenEnumW(
                    resource_connected,
                    resource_type_any,
                    0,
                    None,
                    ctypes.byref(h_enum),
                )
                == 0
            ):
                try:
                    while True:
                        buf_size = wintypes.DWORD(16384)
                        count = wintypes.DWORD(0xFFFFFFFF)
                        buf = ctypes.create_string_buffer(buf_size.value)
                        result = mpr.WNetEnumResourceW(
                            h_enum,
                            ctypes.byref(count),
                            buf,
                            ctypes.byref(buf_size),
                        )
                        if result != 0:
                            break

                        ptr = ctypes.cast(buf, ctypes.POINTER(NETRESOURCE))
                        for i in range(count.value):
                            res = ptr[i]
                            if res.lpLocalName:
                                local_name = ctypes.wstring_at(res.lpLocalName)
                                if local_name and local_name not in locations:
                                    locations.append(local_name)
                            if res.lpRemoteName:
                                remote_name = ctypes.wstring_at(res.lpRemoteName)
                                if remote_name and remote_name not in locations:
                                    locations.append(remote_name)
                finally:
                    mpr.WNetCloseEnum(h_enum)
        except Exception:
            # 静默失败——保留已收集到的结果
            pass
        return locations
