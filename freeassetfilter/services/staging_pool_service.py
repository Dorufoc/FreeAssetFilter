#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件临时存储池数据服务
提供对文件暂存池的纯数据操作，不含任何 UI 逻辑。
"""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple


from freeassetfilter.services.base import BaseService
from freeassetfilter.utils.app_logger import debug, warning


class StagingPoolService(BaseService):
    """文件临时存储池数据服务。

    管理文件暂存池中的项目列表，提供添加、移除、查询、清空
    以及磁盘空间查询和文件夹大小计算等纯数据操作。

    该服务不包含任何 UI 逻辑（信号、槽、QWidget 等），
    设计为被 FileStagingPool 组件或其它需要操作暂存池的模块调用。

    用法::

        service = StagingPoolService()
        if service.add_item({"path": "/foo/bar.jpg", "name": "bar.jpg", ...}):
            items = service.get_items()
            service.remove_item("/foo/bar.jpg")
    """

    _BACKUP_STRING_FIELDS: Tuple[str, ...] = (
        "name",
        "display_name",
        "original_name",
        "modified",
        "created",
        "suffix",
        "info_text",
    )
    _BACKUP_BOOL_FIELDS: Tuple[str, ...] = (
        "is_dir",
        "is_selected",
        "is_missing",
        "size_calculating",
    )

    def __init__(self) -> None:
        super().__init__()
        self._items: List[Dict[str, Any]] = []
        self._lock: threading.Lock = threading.Lock()
        self._size_calculator_executor: Optional[ThreadPoolExecutor] = None
        self._active_size_calculators: Dict[str, Future] = {}
        self._size_calculator_cancel_events: Dict[str, threading.Event] = {}

    # ── BaseService lifecycle ────────────────────────────────────────────

    def _do_initialize(self) -> None:
        """初始化服务内部状态。"""
        self._items = []
        max_workers = min(4, os.cpu_count() or 2)
        self._size_calculator_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="FolderSizeCalculator",
        )
        debug("StagingPoolService 初始化完成")

    def _do_dispose(self) -> None:
        """释放服务资源，停止所有后台计算任务。"""
        self._cancel_all_size_calculations()

        if self._size_calculator_executor is not None:
            self._size_calculator_executor.shutdown(wait=False, cancel_futures=True)
            self._size_calculator_executor = None

        self._items.clear()
        debug("StagingPoolService 已释放")

    # ── Item management ──────────────────────────────────────────────────

    def add_item(self, file_info: Dict[str, Any]) -> bool:
        """添加一个文件/文件夹信息到暂存池。

        如果 ``path`` 已存在则跳过（重复检测）。

        Args:
            file_info: 文件信息字典，至少包含 ``path`` 和 ``name`` 键。

        Returns:
            添加成功返回 True，项目已存在或输入无效返回 False。
        """
        file_path = file_info.get("path")
        if not file_path:
            return False

        normalized = os.path.normpath(file_path)

        with self._lock:
            # 重复检测
            if self._has_path_locked(normalized):
                return False

            item = dict(file_info)
            item.setdefault("display_name", item.get("name", os.path.basename(normalized)))
            item.setdefault("original_name", item.get("name", os.path.basename(normalized)))
            if item.get("is_dir") and "size_calculating" not in item:
                item["size_calculating"] = True

            self._items.append(item)

        debug(f"StagingPoolService 添加项目: {item.get('name', 'unknown')}")
        return True

    def remove_item(self, path: str) -> Optional[Dict[str, Any]]:
        """按路径从暂存池中移除项目。

        Args:
            path: 要移除的文件或文件夹路径。

        Returns:
            被移除的项目字典，未找到则返回 None。
        """
        normalized = os.path.normpath(path)

        with self._lock:
            for i, item in enumerate(self._items):
                item_path = item.get("path", "")
                if item_path and os.path.normpath(item_path) == normalized:
                    removed = self._items.pop(i)
                    return removed

        return None

    def get_items(self) -> List[Dict[str, Any]]:
        """获取暂存池中所有项目的快照。

        Returns:
            项目字典列表（每个为独立副本）。
        """
        with self._lock:
            return [item.copy() for item in self._items]

    def clear(self) -> None:
        """清空暂存池中的所有项目。"""
        with self._lock:
            self._items.clear()
        debug("StagingPoolService 已清空所有项目")

    def get_item_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        """按路径查找项目。

        Args:
            path: 文件或文件夹路径。

        Returns:
            匹配的项目字典，未找到返回 None。
        """
        normalized = os.path.normpath(path)

        with self._lock:
            for item in self._items:
                item_path = item.get("path", "")
                if item_path and os.path.normpath(item_path) == normalized:
                    return item.copy()

        return None

    def has_path(self, path: str) -> bool:
        """检查指定路径是否已在暂存池中。

        Args:
            path: 要检查的文件或文件夹路径。

        Returns:
            路径已存在返回 True，否则返回 False。
        """
        normalized = os.path.normpath(path)

        with self._lock:
            return self._has_path_locked(normalized)

    def _has_path_locked(self, normalized_path: str) -> bool:
        """已持有锁时检查路径是否存在（内部辅助）。"""
        for item in self._items:
            item_path = item.get("path", "")
            if item_path and os.path.normpath(item_path) == normalized_path:
                return True
        return False

    # ── Disk space ───────────────────────────────────────────────────────

    def get_directory_space(self, directory: str) -> Tuple[Optional[int], Optional[int]]:
        """获取目录所在磁盘的总容量和可用空间。

        Args:
            directory: 目录路径。

        Returns:
            ``(总容量字节数, 可用空间字节数)`` 的二元组；
            获取失败返回 ``(None, None)``。
        """
        try:
            if sys.platform == "win32":
                import ctypes

                if not os.path.exists(directory):
                    return None, None

                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(directory),
                    None,
                    ctypes.byref(total_bytes),
                    ctypes.byref(free_bytes),
                )
                return total_bytes.value, free_bytes.value
            else:
                statvfs = os.statvfs(directory)
                total_bytes = statvfs.f_frsize * statvfs.f_blocks
                free_bytes = statvfs.f_frsize * statvfs.f_bavail
                return total_bytes, free_bytes
        except (OSError, PermissionError, FileNotFoundError) as e:
            warning(f"获取目录空间失败: {e}")
            return None, None

    # ── Folder size ──────────────────────────────────────────────────────

    def calculate_folder_size(
        self,
        folder_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> Optional[int]:
        """递归计算文件夹中所有文件的总大小。

        这是纯同步计算；若需要在后台线程中执行，请自行通过
        :meth:`calculate_folder_size_async` 提交。

        Args:
            folder_path: 要计算大小的文件夹路径。
            cancel_event: 可选取消标记，设置后可中断正在进行的计算。

        Returns:
            文件夹总大小（字节数），计算被取消或出错返回 None。
        """
        if cancel_event is not None and cancel_event.is_set():
            return None

        if not os.path.isdir(folder_path):
            return None

        return self._sum_folder_file_sizes(folder_path, cancel_event)

    def calculate_folder_size_async(
        self,
        folder_path: str,
        callback: Optional[callable] = None,
    ) -> Optional[Future]:
        """异步提交文件夹大小计算任务。

        通过内部线程池执行 :meth:`calculate_folder_size`，避免阻塞调用方。
        如果相同路径的计算任务已存在且未完成，则不会重复提交。

        Args:
            folder_path: 要计算大小的文件夹路径。
            callback: 计算完成后的回调函数，签名 ``callback(result: Optional[int])``。
                      如果为 None，调用方需自行通过返回的 Future 获取结果。

        Returns:
            代表计算任务的 :class:`~concurrent.futures.Future` 对象；
            如果任务已存在且未完成，返回该任务已有的 Future；
            如果传入的路径不是目录，返回 None。
        """
        if not os.path.isdir(folder_path):
            return None

        normalized = os.path.normpath(folder_path)

        # 检查是否已有进行中的计算
        existing = self._active_size_calculators.get(normalized)
        if existing is not None and not existing.done():
            return existing

        if self._size_calculator_executor is None:
            return None

        cancel_event = threading.Event()
        self._size_calculator_cancel_events[normalized] = cancel_event

        future = self._size_calculator_executor.submit(
            self._calculate_folder_size_worker,
            normalized,
            cancel_event,
        )
        self._active_size_calculators[normalized] = future

        def _on_done(completed_future: Future) -> None:
            try:
                if completed_future.cancelled():
                    return
                result = completed_future.result()
                if callback is not None:
                    callback(result)
            except Exception as e:
                warning(f"文件夹大小计算失败: {normalized}, 错误: {e}")
            finally:
                self._active_size_calculators.pop(normalized, None)
                self._size_calculator_cancel_events.pop(normalized, None)

        future.add_done_callback(_on_done)
        return future

    def cancel_folder_size_calculation(self, folder_path: str) -> None:
        """取消指定文件夹的大小计算任务。

        Args:
            folder_path: 文件夹路径。
        """
        normalized = os.path.normpath(folder_path)

        cancel_event = self._size_calculator_cancel_events.pop(normalized, None)
        if cancel_event is not None:
            cancel_event.set()

        future = self._active_size_calculators.pop(normalized, None)
        if future is not None and not future.done():
            future.cancel()

    # ── Internals ────────────────────────────────────────────────────────

    def _calculate_folder_size_worker(
        self,
        folder_path: str,
        cancel_event: threading.Event,
    ) -> Optional[int]:
        """在线程池中执行的文件夹大小计算工作线程。"""
        return self.calculate_folder_size(folder_path, cancel_event)

    @staticmethod
    def _iter_file_entries(
        folder_path: str,
        cancel_event: Optional[threading.Event] = None,
    ):
        """递归遍历目录中的文件项。

        Args:
            folder_path: 文件夹路径。
            cancel_event: 可选取消标记。

        Yields:
            os.DirEntry: 文件项（仅文件，不含子目录）。
        """
        if cancel_event is not None and cancel_event.is_set():
            return

        try:
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if cancel_event is not None and cancel_event.is_set():
                        return

                    try:
                        if entry.is_dir(follow_symlinks=False):
                            yield from StagingPoolService._iter_file_entries(
                                entry.path, cancel_event,
                            )
                        elif entry.is_file():
                            yield entry
                    except (OSError, PermissionError, FileNotFoundError):
                        continue
        except (OSError, PermissionError, FileNotFoundError):
            return

    @staticmethod
    def _sum_folder_file_sizes(
        folder_path: str,
        cancel_event: Optional[threading.Event] = None,
    ) -> Optional[int]:
        """递归累加文件夹中的文件大小。

        Args:
            folder_path: 文件夹路径。
            cancel_event: 可选取消标记。

        Returns:
            总大小（字节数），计算被取消则返回 None。
        """
        total_size = 0

        for entry in StagingPoolService._iter_file_entries(folder_path, cancel_event):
            if cancel_event is not None and cancel_event.is_set():
                return None

            try:
                total_size += entry.stat().st_size
            except (OSError, PermissionError, FileNotFoundError):
                continue

        if cancel_event is not None and cancel_event.is_set():
            return None

        return total_size

    # ── File size formatting ────────────────────────────────────────────

    @staticmethod
    def format_file_size(size_bytes) -> str:
        """将字节数格式化为可读的文件大小字符串。

        Args:
            size_bytes: 文件大小（字节），可为 int、float 或 None。

        Returns:
            格式化后的大小字符串，如 ``"1.50 MB"``；输入无效时返回空字符串。
        """
        if size_bytes is None:
            return ""
        try:
            size_value = float(size_bytes)
        except (TypeError, ValueError):
            return ""
        if size_value < 0:
            size_value = 0.0
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while size_value >= 1024 and unit_index < len(units) - 1:
            size_value /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{int(size_value)} {units[unit_index]}"
        return f"{size_value:.2f} {units[unit_index]}"

    # ── Serialization helpers ────────────────────────────────────────────

    @classmethod
    def serialize_backup_item(cls, file_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将运行时文件信息压缩为可安全写入 JSON 的备份结构。

        Args:
            file_info: 运行时文件信息字典。

        Returns:
            序列化后的字典，若输入无效返回 None。
        """
        if not isinstance(file_info, dict):
            return None

        raw_path = file_info.get("path")
        if raw_path is None:
            return None

        path = os.path.normpath(str(raw_path).strip())
        if not path:
            return None

        serialized: Dict[str, Any] = {"path": path}

        size = file_info.get("size")
        if isinstance(size, (int, float)) and not isinstance(size, bool):
            serialized["size"] = int(size)
        else:
            serialized["size"] = None

        for field in cls._BACKUP_STRING_FIELDS:
            value = file_info.get(field)
            serialized[field] = "" if value is None else str(value)

        for field in cls._BACKUP_BOOL_FIELDS:
            serialized[field] = bool(file_info.get(field, False))

        return serialized

    @staticmethod
    def build_file_info(
        file_path: str,
        stat_result: Optional[os.stat_result] = None,
        is_dir: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """构建标准化的文件/文件夹信息字典。

        Args:
            file_path: 文件或文件夹路径。
            stat_result: 可选的 os.stat 结果，复用可避免额外系统调用。
            is_dir: 可选的目录标识，为 None 时会自动检测。

        Returns:
            信息字典，读取失败返回 None。
        """
        from datetime import datetime

        try:
            file_stat = stat_result or os.stat(file_path)
            file_name = os.path.basename(file_path)
            if is_dir is None:
                is_dir = os.path.isdir(file_path)

            suffix = ""
            if not is_dir:
                ext = os.path.splitext(file_name)[1].lower()
                suffix = ext[1:] if ext.startswith(".") else ext

            file_info = {
                "name": file_name,
                "path": file_path,
                "is_dir": is_dir,
                "size": None if is_dir else file_stat.st_size,
                "size_calculating": True if is_dir else False,
                "modified": datetime.fromtimestamp(
                    file_stat.st_mtime,
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "created": datetime.fromtimestamp(
                    file_stat.st_ctime,
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "suffix": suffix,
                "display_name": file_name,
                "original_name": file_name,
            }

            return file_info
        except (OSError, PermissionError, FileNotFoundError) as e:
            warning(f"获取文件/文件夹信息失败: {e}")
            return None

    # ── Internal helpers ─────────────────────────────────────────────────

    def _cancel_all_size_calculations(self) -> None:
        """取消所有正在进行的文件夹大小计算。"""
        for cancel_event in self._size_calculator_cancel_events.values():
            cancel_event.set()

        for future in self._active_size_calculators.values():
            future.cancel()

        self._active_size_calculators.clear()
        self._size_calculator_cancel_events.clear()
