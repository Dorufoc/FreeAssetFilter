#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件列表加载任务（QRunnable）
在后台线程池中扫描目录，通过主线程持有的信号中转对象将结果发送回 UI 线程。
"""

import os
import sys

from PySide6.QtCore import QDateTime, QObject, QRunnable, Qt, QThreadPool, Signal


class _FileListSignals(QObject):
    """文件列表加载完成信号中转（主线程持有，跨线程队列投递）。"""

    loaded = Signal(str, list)
    failed = Signal(str, str)


class FileListLoaderThread(QRunnable):
    """后台任务：扫描目录并返回文件列表（通过信号中转对象与 UI 通信）。

    ``run()`` 在 ``QThreadPool.globalInstance()`` 的池线程中执行；
    ``loaded`` / ``failed`` 信号挂在主线程持有的 ``_FileListSignals``
    中转对象上（以属性方式透出），连接方式与旧 QThread 版完全一致。
    类名与构造签名保持向后兼容。
    """

    def __init__(self, current_path, parent=None):
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject。
        super().__init__()
        self.setAutoDelete(True)
        self.current_path = current_path
        self._signals = _FileListSignals()

    @property
    def loaded(self):
        """目录扫描完成信号 ``(path, files)``（经中转对象）。"""
        return self._signals.loaded

    @property
    def failed(self):
        """目录扫描失败信号 ``(path, error_message)``（经中转对象）。"""
        return self._signals.failed

    def start(self) -> None:
        """投递到全局线程池执行（替代旧 QThread.start()）。"""
        QThreadPool.globalInstance().start(self)

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

            self._signals.loaded.emit(self.current_path, files)
        except Exception as e:
            self._signals.failed.emit(self.current_path, str(e))
