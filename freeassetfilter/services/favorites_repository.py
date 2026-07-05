#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 收藏夹数据访问层

提供 FavoritesRepository 类，处理收藏夹 JSON 文件的读写操作。
纯数据访问 —— 不包含业务逻辑。
"""

import json
import os
from typing import List, Optional


class FavoritesRepository:
    """收藏夹 JSON 数据访问层。

    负责收藏夹数据的持久化，将 List[str] 序列化为 JSON 文件，
    或从 JSON 文件反序列化为 List[str]。
    不包含去重、验证等业务逻辑 —— 仅处理文件 I/O 和类型安全。

    Attributes:
        filepath: 收藏夹 JSON 文件路径。
    """

    def __init__(self, filepath: Optional[str] = None) -> None:
        """初始化 FavoritesRepository。

        Args:
            filepath: 收藏夹 JSON 文件路径。
                      默认为项目 data/ 目录下的 favorites.json。
        """
        if filepath is not None:
            self.filepath: str = filepath
        else:
            self.filepath = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data",
                "favorites.json",
            )

    def load(self) -> List[str]:
        """从 JSON 文件加载收藏路径列表。

        若文件不存在、内容损坏或数据类型错误，返回空列表。
        不抛出异常 —— 所有错误均静默处理。

        Returns:
            List[str]: 收藏的文件路径列表。失败时返回 []。
        """
        if not os.path.exists(self.filepath):
            return []

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError, ValueError):
            return []

    def save(self, favorites: List[str]) -> None:
        """将收藏路径列表持久化到 JSON 文件。

        若父目录不存在则自动创建。
        以 pretty-print 格式写入。

        Args:
            favorites: 要保存的路径列表。
        """
        parent = os.path.dirname(self.filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
