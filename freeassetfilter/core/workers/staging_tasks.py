#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

存储池后台任务（QRunnable 计算类）
从 file_staging_pool.py 提取的工作线程任务，保持一致的 API 和信号定义。
"""

import hashlib
import weakref
from typing import Callable, Optional

from PySide6.QtCore import QRunnable

from freeassetfilter.core.heartbeat_manager import HeartbeatManager
from freeassetfilter.utils.app_logger import warning


class _MD5CalculationTask(QRunnable):
    """在后台线程计算文件MD5，完成后在主线程通过HeartbeatManager调用回调。"""

    def __init__(
        self, file_path: str, callback: Callable[[Optional[str]], None]
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._callback = callback

    def run(self) -> None:
        try:
            hash_md5 = hashlib.md5()
            with open(self._file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            result: Optional[str] = hash_md5.hexdigest()
        except FileNotFoundError:
            result = None
        except (IOError, OSError, PermissionError) as e:
            warning(f"计算MD5失败: {e}")
            result = None

        # 在主线程调用回调
        try:
            hm = HeartbeatManager()
            weak_self = weakref.ref(self)
            hm.request_main_thread(lambda: (s := weak_self()) and s._callback(result))
        except Exception:
            pass


# 公开别名，与 file_staging_pool 中的私有名保持兼容
MD5CalculationTask = _MD5CalculationTask
