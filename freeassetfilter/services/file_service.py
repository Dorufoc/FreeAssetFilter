#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件扫描、筛选、排序服务
提供纯文件系统操作，无 UI 依赖。
"""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional

from freeassetfilter.services.base import BaseService


class FileService(BaseService):
    """文件扫描、筛选、排序服务。

    纯文件系统操作，不依赖 Qt 或 UI 组件。
    生成的 file_dict 格式与 file_selector 组件 100% 兼容：:

        {
            "name": str,       # 文件/目录名
            "path": str,       # 完整路径
            "is_dir": bool,    # 是否为目录
            "size": int,       # 文件大小（字节），目录为 0
            "modified": str,   # ISO 格式修改时间（秒精度）
            "created": str,    # ISO 格式创建时间（秒精度）
            "suffix": str,     # 扩展名（无点，小写），目录为空字符串
        }

    单例模式，继承 BaseService 的线程安全生命周期管理。
    """

    _instance: Optional["FileService"] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    # ── Singleton ─────────────────────────────────────────────────────

    def __new__(cls, *args, **kwargs) -> "FileService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        with self._lock:
            if self._initialized:
                return
            super().__init__()
            self._initialized = True

    # ── BaseService lifecycle (no-op, nothing to init/dispose) ────────

    def _do_initialize(self) -> None:
        """FileService 无需额外初始化资源。"""
        pass

    def _do_dispose(self) -> None:
        """FileService 无需额外销毁逻辑。"""
        pass

    # ── Public API ─────────────────────────────────────────────────────

    @staticmethod
    def normalize_path(file_path: str) -> str:
        """标准化文件路径。

        Parameters
        ----------
        file_path : str
            要标准化的文件路径。

        Returns
        -------
        str
            标准化后的路径，输入为空时返回空字符串。
        """
        return os.path.normpath(file_path) if file_path else ""

    def scan_directory(self, path: str) -> List[Dict]:
        """扫描目录并返回文件信息字典列表。

        跳过隐藏文件（以 ``.`` 开头）和符号链接。
        跳过无法访问的文件项。

        Parameters
        ----------
        path : str
            要扫描的目录路径。

        Returns
        -------
        List[Dict]
            文件信息字典列表。当路径不存在或无法访问时返回空列表。
        """
        try:
            return self._scan_normal_directory(path)
        except (OSError, PermissionError, TypeError, ValueError):
            return []

    def filter_files(self, files: List[Dict], pattern: str = "*") -> List[Dict]:
        """根据通配符模式筛选文件列表。

        Parameters
        ----------
        files : List[Dict]
            文件信息字典列表。
        pattern : str
            通配符筛选模式。支持 ``*``（匹配任意字符）和 ``?``（匹配单个字符）。
            默认为 ``"*"``（全部匹配）。空字符串视为 ``"*"``。

        Returns
        -------
        List[Dict]
            匹配模式的文件列表。无效模式返回空列表。
        """
        if not pattern or pattern == "*":
            return list(files)

        # 将通配符转换为正则表达式
        regex_pattern = re.escape(pattern)
        regex_pattern = regex_pattern.replace(r"\*", ".*")
        regex_pattern = regex_pattern.replace(r"\?", ".")
        regex_pattern = f"^{regex_pattern}$"

        try:
            regex = re.compile(regex_pattern, re.IGNORECASE)
        except re.error:
            return []

        return [f for f in files if regex.match(f.get("name", ""))]

    def sort_files(
        self,
        files: List[Dict],
        key: str = "name",
        reverse: bool = False,
    ) -> List[Dict]:
        """对文件列表进行排序。目录始终排在文件之前。

        Parameters
        ----------
        files : List[Dict]
            文件信息字典列表。
        key : str
            排序键。可选值：``"name"``（默认，按名称不区分大小写）、
            ``"size"``（按大小）、``"modified"``（按修改时间）、
            ``"created"``（按创建时间）。未知键回退为 ``"name"``。
        reverse : bool
            是否逆序排序（默认 False）。

        Returns
        -------
        List[Dict]
            排序后的新列表（不影响原始列表）。
        """
        if key not in ("name", "size", "modified", "created"):
            key = "name"

        _key_fns = {
            "name": lambda x: x.get("name", "").lower(),
            "size": lambda x: x.get("size", 0),
            "modified": lambda x: x.get("modified", ""),
            "created": lambda x: x.get("created", ""),
        }

        sort_key_fn = _key_fns[key]
        sorted_files = sorted(
            files,
            key=lambda x: (not x.get("is_dir", False), sort_key_fn(x)),
        )

        if reverse:
            sorted_files.reverse()

        return sorted_files

    # ── Internals ──────────────────────────────────────────────────────

    def _scan_all_drives(self) -> List[Dict]:
        """扫描所有可用盘符（Windows）或根目录（Unix）。

        与 file_selector.py 中 FileListLoaderThread 对 "All" 的处理逻辑一致。
        """
        files: List[Dict] = []

        if os.name == "nt":
            # Windows: 通过 GetLogicalDrives 枚举盘符
            import ctypes

            kernel32 = ctypes.windll.kernel32
            drives_bitmask = kernel32.GetLogicalDrives()
            for drive in range(26):
                if drives_bitmask & (1 << drive):
                    drive_name = chr(65 + drive) + ":"
                    drive_path = drive_name + "\\"
                    try:
                        stat = os.stat(drive_path)
                        modified = datetime.fromtimestamp(
                            int(stat.st_mtime)
                        ).isoformat()
                        created = datetime.fromtimestamp(
                            int(stat.st_ctime)
                        ).isoformat()
                    except OSError:
                        modified = ""
                        created = ""

                    files.append(
                        {
                            "name": drive_name,
                            "path": drive_path,
                            "is_dir": True,
                            "size": 0,
                            "modified": modified,
                            "created": created,
                            "suffix": "",
                        }
                    )
        else:
            # Unix: 显示根目录
            root_path = "/"
            try:
                stat = os.stat(root_path)
                modified = datetime.fromtimestamp(
                    int(stat.st_mtime)
                ).isoformat()
                created = datetime.fromtimestamp(
                    int(stat.st_ctime)
                ).isoformat()
            except OSError:
                modified = ""
                created = ""

            files.append(
                {
                    "name": root_path,
                    "path": root_path,
                    "is_dir": True,
                    "size": 0,
                    "modified": modified,
                    "created": created,
                    "suffix": "",
                }
            )

        return files

    def _scan_normal_directory(self, path: str) -> List[Dict]:
        """使用 os.scandir 扫描普通目录。

        跳过隐藏文件（以 ``.`` 开头）和符号链接。
        跳过无法访问的文件项。与 file_selector.py 中
        FileListLoaderThread.run() 的正常目录扫描逻辑一致。
        """
        files: List[Dict] = []

        with os.scandir(path) as entries:
            for entry in entries:
                # 跳过隐藏文件
                if entry.name.startswith("."):
                    continue

                try:
                    if entry.is_symlink():
                        continue

                    stat = entry.stat(follow_symlinks=False)
                    files.append(
                        {
                            "name": entry.name,
                            "path": entry.path,
                            "is_dir": entry.is_dir(follow_symlinks=False),
                            "size": stat.st_size,
                            "modified": datetime.fromtimestamp(
                                int(stat.st_mtime)
                            ).isoformat(),
                            "created": datetime.fromtimestamp(
                                int(stat.st_ctime)
                            ).isoformat(),
                            "suffix": os.path.splitext(entry.name)[1]
                            .lower()
                            .lstrip("."),
                        }
                    )
                except (OSError, PermissionError):
                    continue

        return files
