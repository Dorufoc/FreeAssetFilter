#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件列表加载器线程
在后台线程中扫描目录，通过 Signal 将结果发送回 UI 线程
"""

import os
import sys

from PySide6.QtCore import QThread, Signal, QDateTime, Qt


class FileListLoaderThread(QThread):
    """后台线程：扫描目录并返回文件列表（通过 Signal 与 UI 通信）"""

    loaded = Signal(str, list)
    failed = Signal(str, str)

    def __init__(self, current_path, parent=None):
        super().__init__(parent)
        self.current_path = current_path

    def run(self):
        files = []

        try:
            if self.current_path == "All":
                if sys.platform == 'win32':
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    drives_bitmask = kernel32.GetLogicalDrives()
                    for drive in range(26):
                        if drives_bitmask & (1 << drive):
                            drive_name = chr(65 + drive) + ':'
                            drive_path = drive_name + '\\'
                            try:
                                stat = os.stat(drive_path)
                                modified = QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate)
                                created = QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate)
                            except OSError:
                                modified = ""
                                created = ""

                            files.append({
                                "name": drive_name,
                                "path": drive_path,
                                "is_dir": True,
                                "size": 0,
                                "modified": modified,
                                "created": created,
                                "suffix": ""
                            })
                else:
                    root_path = "/"
                    try:
                        stat = os.stat(root_path)
                        modified = QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate)
                        created = QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate)
                    except OSError:
                        modified = ""
                        created = ""

                    files.append({
                        "name": root_path,
                        "path": root_path,
                        "is_dir": True,
                        "size": 0,
                        "modified": modified,
                        "created": created,
                        "suffix": ""
                    })
            else:
                if os.path.islink(self.current_path):
                    raise OSError("拒绝扫描符号链接目录")

                with os.scandir(self.current_path) as entries:
                    for entry in entries:
                        if entry.name.startswith("."):
                            continue

                        try:
                            if entry.is_symlink():
                                continue

                            stat = entry.stat(follow_symlinks=False)
                            files.append({
                                "name": entry.name,
                                "path": entry.path,
                                "is_dir": entry.is_dir(follow_symlinks=False),
                                "size": stat.st_size,
                                "modified": QDateTime.fromSecsSinceEpoch(int(stat.st_mtime)).toString(Qt.ISODate),
                                "created": QDateTime.fromSecsSinceEpoch(int(stat.st_ctime)).toString(Qt.ISODate),
                                "suffix": os.path.splitext(entry.name)[1].lower().lstrip('.')
                            })
                        except (OSError, PermissionError):
                            continue

            self.loaded.emit(self.current_path, files)
        except Exception as e:
            self.failed.emit(self.current_path, str(e))
