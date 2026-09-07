#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动画设置读取辅助工具（SettingsManagerV2 通路）。

自新版架构起，动画开关统一从 ``SettingsManagerV2`` 读取（键路径
``appearance.animations.<key>``）；未配置时回退调用方给定的默认值，
与旧版 SettingsManager 的行为对齐但不复用它。
"""

from __future__ import annotations

from typing import Any


def resolve_settings_manager(settings_manager: Any = None):
    """
    获取当前可用的设置管理器实例。

    优先使用调用方注入的管理器（兼容旧参数传递方式）；否则返回
    ``SettingsManagerV2`` 实例。
    """
    if settings_manager is not None:
        return settings_manager

    try:
        from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2
        return SettingsManagerV2()
    except Exception:
        return None


def is_animation_enabled(animation_key: str, default: bool = True, settings_manager: Any = None) -> bool:
    """
    读取全局动画开关。

    键路径约定：``appearance.animations.<animation_key>``。
    兼容两种管理器接口：``get(key_path, default)``（V2）与
    ``get_setting(key_path, default)``（旧式注入实例）。
    """
    manager = resolve_settings_manager(settings_manager)
    if manager is None:
        return bool(default)

    key_path = animation_key
    if not key_path.startswith("appearance.animations."):
        key_path = f"appearance.animations.{animation_key}"

    try:
        if hasattr(manager, "get"):
            value = manager.get(key_path, default)
        else:
            value = manager.get_setting(key_path, default)
        if value is None:
            return bool(default)
        return bool(value)
    except Exception:
        return bool(default)