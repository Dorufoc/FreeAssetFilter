#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动画设置读取辅助工具（SettingsManagerV2 通路）。

自新版架构起，动画开关统一从 ``SettingsManagerV2`` 读取（键路径
``appearance.animations.<key>``）；未配置时回退调用方给定的默认值，
与旧版 SettingsManager 的行为对齐但不复用它。
"""

from __future__ import annotations

import os
from typing import Any, Optional

#: 复用的设置管理器实例。
#:
#: ``SettingsManagerV2`` 不是单例，而 ``load()`` 首次调用要整份读盘（实测
#: 3~4ms）。滚动/悬停这类热路径每次重建实例就等于每次读一次设置文件——实测
#: 滚动时主线程被拖住 100ms/次，正是"交互卡顿"的主因之一。这里复用一个实例，
#: 并用设置文件的 mtime 判断是否需要刷新，既不读盘也不会吃到过期值。
_cached_manager: Optional[Any] = None
_cached_mtime_ns: int = -1


def _shared_settings_manager():
    """取进程内复用的 V2 设置管理器（文件变更时自动重载）。"""
    global _cached_manager, _cached_mtime_ns

    from sopeek.core.managers.settings_manager_v2 import SettingsManagerV2

    if _cached_manager is None:
        _cached_manager = SettingsManagerV2()

    try:
        mtime_ns = os.stat(_cached_manager.file_path).st_mtime_ns
    except OSError:
        mtime_ns = -1
    if mtime_ns != _cached_mtime_ns:
        _cached_mtime_ns = mtime_ns
        try:
            _cached_manager.load(force=True)
        except Exception:  # noqa: BLE001 - 读盘失败就退回缓存
            pass
    return _cached_manager


def resolve_settings_manager(settings_manager: Any = None):
    """
    获取当前可用的设置管理器实例。

    优先使用调用方注入的管理器（兼容旧参数传递方式）；否则返回
    ``SettingsManagerV2`` 实例。
    """
    if settings_manager is not None:
        return settings_manager

    try:
        return _shared_settings_manager()
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