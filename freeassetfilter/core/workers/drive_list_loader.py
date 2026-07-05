#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

后台驱动器加载与盘符可用性检查线程
"""

import ctypes
import os
import sys
import traceback
from ctypes import wintypes

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from freeassetfilter.utils.app_logger import debug, error, warning


class _DriveAvailabilitySignals(QObject):
    """盘符可用性检查完成信号桥接器，用于 QRunnable。"""
    finished = Signal(str, bool)  # drive_path, available


class _DriveAvailabilityCheckRunnable(QRunnable):
    """后台盘符可用性检查，使用 os.scandir()。"""

    def __init__(self, drive_path: str, signals: _DriveAvailabilitySignals):
        super().__init__()
        self._drive_path = drive_path
        self._signals = signals

    def run(self):
        available = False
        try:
            drive_path = self._drive_path
            if not drive_path.endswith(('\\', '/')):
                drive_path = drive_path + '\\'
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
        self._signals.finished.emit(self._drive_path, available)


class DriveListLoaderThread(QThread):
    loaded = Signal(list, list)

    def run(self):
        try:
            local_drives = []
            network_locations = []

            if sys.platform == 'win32':
                try:
                    kernel32 = ctypes.windll.kernel32
                    drives_bitmask = kernel32.GetLogicalDrives()
                    for drive in range(26):
                        if drives_bitmask & (1 << drive):
                            local_drives.append(chr(65 + drive) + ':')
                except Exception as e:
                    warning(f"获取本地盘符失败: {e}")

                try:
                    mpr = ctypes.WinDLL('mpr')

                    class NETRESOURCE(ctypes.Structure):
                        _fields_ = [
                            ('dwScope', wintypes.DWORD),
                            ('dwType', wintypes.DWORD),
                            ('dwDisplayType', wintypes.DWORD),
                            ('dwUsage', wintypes.DWORD),
                            ('lpLocalName', wintypes.LPWSTR),
                            ('lpRemoteName', wintypes.LPWSTR),
                            ('lpComment', wintypes.LPWSTR),
                            ('lpProvider', wintypes.LPWSTR)
                        ]

                    resource_connected = 1
                    resource_type_any = 0
                    h_enum = wintypes.HANDLE()

                    if mpr.WNetOpenEnumW(resource_connected, resource_type_any, 0, None, ctypes.byref(h_enum)) == 0:
                        try:
                            while True:
                                buf_size = wintypes.DWORD(16384)
                                count = wintypes.DWORD(0xFFFFFFFF)
                                buf = ctypes.create_string_buffer(buf_size.value)
                                result = mpr.WNetEnumResourceW(h_enum, ctypes.byref(count), buf, ctypes.byref(buf_size))
                                if result != 0:
                                    break

                                ptr = ctypes.cast(buf, ctypes.POINTER(NETRESOURCE))
                                for i in range(count.value):
                                    res = ptr[i]
                                    if res.lpLocalName:
                                        local_name = ctypes.wstring_at(res.lpLocalName)
                                        if local_name and local_name not in local_drives:
                                            local_drives.append(local_name)
                                    if res.lpRemoteName:
                                        remote_name = ctypes.wstring_at(res.lpRemoteName)
                                        if remote_name and remote_name not in network_locations:
                                            network_locations.append(remote_name)
                        finally:
                            mpr.WNetCloseEnum(h_enum)
                except Exception as e:
                    debug(f"获取网络位置失败，保留本地盘符列表: {e}")
            else:
                local_drives = ['/']

            local_drives = sorted(set(local_drives))
            network_locations = sorted(set(network_locations))
            self.loaded.emit(local_drives, network_locations)
        except Exception:
            error(f"DriveListLoaderThread.run() 异常: {traceback.format_exc()}")
