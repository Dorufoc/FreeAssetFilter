#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0 — 设置管理器 V2

全新的设置分类树（v2），专注于核心配置项目的持久化存储与管理。
与 v1 SettingsManager 完全独立，使用独立的 JSON 文件和分类结构。

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional


# ── V2 分类树默认值 ──────────────────────────────────────────────
# "分类树 v2" — 全新的扁平化配置参数结构，按功能域分组。
DEFAULT_SETTINGS_V2: Dict[str, Any] = {
    "version": 2,
    "appearance": {
        "theme": "dark",           # "light" | "dark"
        "accent_color": "#007AFF",
        # 完整颜色树 — 与 colors.json 结构一致，统一配置源头
        "colors": {
            "accent": {
                "primary": "#3A9DCB",
                "danger": "#ef4444",
                "warning": "#f59e0b",
                "info": "#3b82f6",
                "purple": "#8b5cf6",
            },
            "gray": {
                "g1": "#1a1a1a",
                "g2": "#3e3e3e",
                "g3": "#888888",
                "g4": "#ffffff",
                "black": "#000000",
            },
            "gray_light": {
                "g1": "#f5f5f5",
                "g2": "#e0e0e0",
                "g3": "#888888",
                "g4": "#1a1a1a",
                "black": "#000000",
            },
        },
    },
}


def _project_root() -> str:
    """返回项目根目录的绝对路径。"""
    return str(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
        )
    )


def _default_settings_path() -> str:
    """返回默认的 V2 设置文件路径 ``data/settings_v2.json``。"""
    return os.path.join(_project_root(), "data", "settings_v2.json")


class SettingsManagerV2:
    """全新的设置管理器 V2。

    管理独立的 V2 分类树配置，与旧版 SettingsManager 完全解耦。
    支持点号分隔的 key 路径读写（如 ``appearance.theme``）。
    线程安全：内部使用 ``threading.Lock()`` 保护所有读写操作。

    存储位置：``data/settings_v2.json``
    """

    def __init__(self, file_path: Optional[str] = None) -> None:
        """初始化 V2 设置管理器。

        Args:
            file_path: JSON 文件路径。为 ``None`` 时使用
                ``data/settings_v2.json``。
        """
        self._lock = threading.Lock()
        self._file_path: str = file_path if file_path is not None else _default_settings_path()
        self._settings: Dict[str, Any] = {}
        self._loaded = False

    # ── 属性 ─────────────────────────────────────────────────────

    @property
    def file_path(self) -> str:
        """当前 V2 设置文件路径。"""
        return self._file_path

    # ── 加载 / 保存 ───────────────────────────────────────────────

    def load(self) -> Dict[str, Any]:
        """从磁盘加载 V2 设置。

        若文件不存在或损坏，返回默认 V2 分类树并写盘。
        多次调用安全——首次加载后返回缓存。

        Returns:
            Dict[str, Any]: V2 设置字典。
        """
        with self._lock:
            if self._loaded:
                return self._settings

            if not os.path.exists(self._file_path):
                self._settings = self._copy_defaults()
                self._loaded = True
                self._write()
                return self._settings

            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("invalid root type")
                self._settings = self._merge_with_defaults(data)
            except (json.JSONDecodeError, OSError, ValueError):
                self._settings = self._copy_defaults()
                self._write()

            self._loaded = True
            return self._settings

    def save(self) -> None:
        """将当前内存中的 V2 设置写入磁盘。"""
        with self._lock:
            self._write()

    def get_all(self) -> Dict[str, Any]:
        """获取完整的 V2 设置字典副本。"""
        with self._lock:
            if not self._loaded:
                self.load()
            return dict(self._settings)  # shallow copy

    def reset_to_defaults(self) -> None:
        """将 V2 设置重置为默认值并立即写盘。"""
        with self._lock:
            self._settings = self._copy_defaults()
            self._write()

    # ── 点号路径读写 ──────────────────────────────────────────────

    def get(self, key_path: str, default: Any = None) -> Any:
        """通过点号路径读取 V2 设置值。

        Args:
            key_path: 点号路径，如 ``"appearance.theme"``。
            default: 路径不存在时的默认值。

        Returns:
            Any: 设置值，路径不存在时返回 *default*。
        """
        with self._lock:
            if not self._loaded:
                self.load()

            keys = key_path.split(".")
            value = self._settings
            try:
                for key in keys:
                    value = value[key]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, key_path: str, value: Any) -> bool:
        """通过点号路径设置 V2 设置值（仅更新内存）。

        调用 :meth:`save` 将变更写盘。

        Args:
            key_path: 点号路径，如 ``"appearance.theme"``。
            value: 要设置的值。

        Returns:
            bool: 值有变更返回 ``True``，无变化返回 ``False``。
        """
        with self._lock:
            if not self._loaded:
                self.load()

            keys = key_path.split(".")
            target = self._settings
            for key in keys[:-1]:
                if key not in target or not isinstance(target[key], dict):
                    target[key] = {}
                target = target[key]

            if keys[-1] in target and target[keys[-1]] == value:
                return False

            target[keys[-1]] = value
            return True

    # ── 内部方法 ──────────────────────────────────────────────────

    def _write(self) -> None:
        """将 ``self._settings`` 写入 JSON 文件（已处于锁内）。"""
        settings_dir = os.path.dirname(self._file_path)
        if settings_dir:
            os.makedirs(settings_dir, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, ensure_ascii=False, indent=4)

    def _copy_defaults(self) -> Dict[str, Any]:
        """深拷贝默认 V2 设置。"""
        return json.loads(json.dumps(DEFAULT_SETTINGS_V2))

    def _merge_with_defaults(self, loaded: Dict[str, Any]) -> Dict[str, Any]:
        """将加载的设置与默认值合并，确保所有键存在。"""
        merged = self._copy_defaults()

        if not isinstance(loaded, dict):
            return merged

        # 合并 version
        if "version" in loaded and isinstance(loaded["version"], int):
            merged["version"] = loaded["version"]

        # 逐域合并（嵌套 dict 整体替换，不含逐叶合并）
        if "appearance" in loaded and isinstance(loaded["appearance"], dict):
            app_loaded = loaded["appearance"]
            for key in merged["appearance"]:
                if key in app_loaded:
                    merged["appearance"][key] = app_loaded[key]

        return merged
