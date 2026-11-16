#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek 收藏夹服务模块

提供文件收藏夹的 CRUD 操作，支持持久化到 JSON 文件。
"""

import os
from typing import List, Optional

from sopeek._paths import favorites_file as _favorites_file
from sopeek.services.base import BaseService
from sopeek.utils.app_logger import warning


class FavoritesService(BaseService):
    """文件收藏夹服务。

    管理收藏文件路径的增删查改，数据持久化到 JSON 文件。
    非单例模式 —— 每个调用方持有自己的实例。

    Attributes:
        favorites_file: 持久化 JSON 文件路径。
    """

    def __init__(self, favorites_file: Optional[str] = None) -> None:
        """初始化 FavoritesService。

        Args:
            favorites_file: 收藏夹 JSON 文件路径。
                           默认为 ``<data>/config/favorites.json``。
        """
        super().__init__()
        if favorites_file is not None:
            self.favorites_file: str = favorites_file
        else:
            from sopeek.storage_layout import ensure_layout

            ensure_layout()
            self.favorites_file = str(_favorites_file())
        self._favorites: List[str] = []
        self._loaded: bool = False

    def _do_initialize(self) -> None:
        """确保收藏夹文件的父目录存在。"""
        parent = os.path.dirname(self.favorites_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _do_dispose(self) -> None:
        """清空内存缓存。"""
        self._favorites.clear()
        self._loaded = False

    def load(self) -> List[str]:
        """从 JSON 文件加载收藏路径列表。

        首次调用时从磁盘读取；之后返回内存缓存。
        若文件损坏或不存在，返回空列表。

        Returns:
            List[str]: 收藏的文件路径列表。
        """
        if self._loaded:
            return self._favorites

        if not os.path.exists(self.favorites_file):
            self._loaded = True
            return self._favorites

        try:
            from sopeek.utils.atomic_json import read_json

            data = read_json(
                self.favorites_file,
                default=None,
                use_backup=True,
                quarantine=True,
            )
            if isinstance(data, list):
                self._favorites = data
            elif data is not None:
                warning(
                    f"FavoritesService: 收藏夹文件顶层非列表，已按空列表处理："
                    f"{self.favorites_file}"
                )
                self._favorites = []
        except (OSError, ValueError, TypeError) as exc:
            # 文件损坏/不可读：按空列表继续，但必须留痕（含文件路径），
            # 便于用户发现收藏数据异常。
            warning(
                f"FavoritesService: 收藏夹文件读取失败，已按空列表处理："
                f"{self.favorites_file}（{type(exc).__name__}: {exc}）"
            )
            self._favorites = []

        self._loaded = True
        return self._favorites

    def save(self, favorites: List[str]) -> bool:
        """将收藏路径列表原子持久化到 JSON 文件。

        Args:
            favorites: 要保存的路径列表。

        Returns:
            bool: 写入成功返回 True；权限/磁盘错误返回 False 并记录日志。
        """
        from sopeek.utils.atomic_json import write_json_atomic

        try:
            write_json_atomic(
                self.favorites_file,
                list(favorites),
                indent=2,
                backup=True,
            )
        except OSError as exc:
            warning(
                f"FavoritesService: 收藏夹写入失败："
                f"{self.favorites_file}（{type(exc).__name__}: {exc}）"
            )
            return False

        self._favorites = list(favorites)
        self._loaded = True
        return True

    def add(self, path: str) -> bool:
        """添加路径到收藏夹。

        如果路径已存在则不重复添加。

        Args:
            path: 要收藏的文件路径。

        Returns:
            bool: 成功添加返回 True，路径已存在（重复）返回 False。
        """
        self.load()
        if path in self._favorites:
            return False
        self._favorites.append(path)
        return True

    def remove(self, path: str) -> bool:
        """从收藏夹移除路径。

        Args:
            path: 要移除的文件路径。

        Returns:
            bool: 成功移除返回 True，路径不存在返回 False。
        """
        self.load()
        if path not in self._favorites:
            return False
        self._favorites.remove(path)
        return True

    def contains(self, path: str) -> bool:
        """检查路径是否已收藏。

        Args:
            path: 要检查的文件路径。

        Returns:
            bool: 已收藏返回 True，否则返回 False。
        """
        self.load()
        return path in self._favorites
