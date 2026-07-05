#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 收藏夹服务模块

提供文件收藏夹的 CRUD 操作，支持持久化到 JSON 文件。
"""

import json
import os
from typing import List, Optional

from freeassetfilter.services.base import BaseService


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
                           默认为项目根目录下的 data/favorites.json。
        """
        super().__init__()
        if favorites_file is not None:
            self.favorites_file: str = favorites_file
        else:
            self.favorites_file: str = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data",
                "favorites.json",
            )
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
            with open(self.favorites_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self._favorites = data
            else:
                self._favorites = []
        except (json.JSONDecodeError, OSError, ValueError):
            self._favorites = []

        self._loaded = True
        return self._favorites

    def save(self, favorites: List[str]) -> None:
        """将收藏路径列表持久化到 JSON 文件。

        Args:
            favorites: 要保存的路径列表。
        """
        parent = os.path.dirname(self.favorites_file)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(self.favorites_file, "w", encoding="utf-8") as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)

        self._favorites = list(favorites)
        self._loaded = True

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
