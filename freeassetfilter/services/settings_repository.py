#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

Settings JSON 数据访问层
纯文件 I/O 操作，不含合并、默认值、业务逻辑。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Optional


class SettingsRepository:
    """JSON 设置文件的数据访问层。

    职责仅限于从磁盘读取和写入 JSON 设置文件，
    不包含合并策略、默认值填充、校验或任何业务逻辑。
    线程安全由调用方（SettingsManager）保证。

    文件大小保护：load() 会拒绝超过 10MB 的文件，返回空字典。

    Default path resolves to ``data/settings.json`` under the project root.
    """

    MAX_JSON_SIZE: int = 10 * 1024 * 1024
    """单个 JSON 文件的最大允许大小（字节）。"""

    def __init__(self, file_path: Optional[str] = None) -> None:
        """初始化仓库。

        Args:
            file_path: JSON 文件路径。为 ``None`` 时使用
                ``data/settings.json``（相对于项目根目录）。
        """
        self._file_path: str = (
            file_path if file_path is not None else self._default_path()
        )

    @staticmethod
    def _default_path() -> str:
        """返回默认设置文件路径 ``data/settings.json``。

        Returns:
            str: 项目根目录下的 data/settings.json 绝对路径。
        """
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return os.path.join(project_root, "data", "settings.json")

    @property
    def file_path(self) -> str:
        """当前仓库管理的 JSON 文件路径。"""
        return self._file_path

    def load(self) -> Dict[str, Any]:
        """从磁盘读取 JSON 设置文件。

        Returns:
            Dict[str, Any]: 解析后的设置字典。
                文件不存在、JSON 格式错误、权限不足、编码异常
                或文件大小超过限制时返回空字典。
        """
        if not os.path.exists(self._file_path):
            return {}

        try:
            self._validate_file_size(self._file_path)
            with open(self._file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError,
                UnicodeDecodeError, ValueError):
            return {}

    def save(self, settings: Dict[str, Any]) -> None:
        """直接将设置字典写入 JSON 文件（非原子写入）。

        写入前会确保父目录存在。
        调用方负责处理可能抛出的 :class:`PermissionError`、
        :class:`TypeError` 等 I/O 异常。

        Args:
            settings: 待写入的设置字典。

        Raises:
            PermissionError: 目标目录或文件无写入权限。
            TypeError: settings 包含无法序列化的类型。
            OSError: 父目录创建失败或写入时发生 I/O 错误。
        """
        self._ensure_dir_exists()
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)

    def atomic_save(self, settings: Dict[str, Any]) -> None:
        """通过临时文件 + 原子重写的方式安全写入设置文件。

        先将 JSON 写入同一目录下带 ``.tmp`` 后缀的临时文件，
        再通过 :func:`os.replace` 原子替换目标文件。
        无论成功或失败，临时文件均会被清理。

        调用方负责处理可能抛出的 :class:`PermissionError`、
        :class:`TypeError` 等 I/O 异常。

        Args:
            settings: 待写入的设置字典。

        Raises:
            PermissionError: 目标目录或文件无写入权限。
            TypeError: settings 包含无法序列化的类型。
            OSError: 父目录创建失败、临时文件写入或 rename 时发生 I/O 错误。
        """
        settings_dir = os.path.dirname(self._file_path) or "."
        self._ensure_dir_exists()
        tmp_file = None
        temp_path: Optional[str] = None
        try:
            tmp_file = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=settings_dir,
                delete=False,
                suffix=".tmp",
            )
            temp_path = tmp_file.name
            json.dump(settings, tmp_file, ensure_ascii=False, indent=4)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
            tmp_file.close()
            tmp_file = None

            os.replace(temp_path, self._file_path)
        finally:
            if tmp_file is not None:
                try:
                    tmp_file.close()
                except OSError:
                    pass
            if temp_path is not None and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _ensure_dir_exists(self) -> None:
        """确保目标文件的父目录存在。"""
        settings_dir = os.path.dirname(self._file_path)
        if settings_dir:
            os.makedirs(settings_dir, exist_ok=True)

    def _validate_file_size(self, file_path: str) -> None:
        """检查文件大小是否超过最大限制。

        Args:
            file_path: 要检查的文件路径。

        Raises:
            ValueError: 文件大小超过 MAX_JSON_SIZE。
        """
        file_size = os.path.getsize(file_path)
        if file_size > self.MAX_JSON_SIZE:
            raise ValueError(
                f"JSON 文件大小 ({file_size} 字节) "
                f"超过最大限制 ({self.MAX_JSON_SIZE} 字节)"
            )
