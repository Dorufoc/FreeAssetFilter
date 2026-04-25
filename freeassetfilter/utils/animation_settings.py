#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动画设置读取辅助工具。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QApplication


def resolve_settings_manager(settings_manager: Any = None):
    """
    获取当前可用的设置管理器实例。
    """
    if settings_manager is not None:
        return settings_manager

    app = QApplication.instance()
    if app is not None and hasattr(app, "settings_manager"):
        return app.settings_manager

    try:
        from freeassetfilter.core.settings_manager import SettingsManager
        return SettingsManager()
    except Exception:
        return None


def is_animation_enabled(animation_key: str, default: bool = True, settings_manager: Any = None) -> bool:
    """
    读取全局动画开关。
    """
    manager = resolve_settings_manager(settings_manager)
    if manager is None:
        return bool(default)

    key_path = animation_key
    if not key_path.startswith("appearance.animations."):
        key_path = f"appearance.animations.{animation_key}"

    try:
        return bool(manager.get_setting(key_path, default))
    except Exception:
        return bool(default)
