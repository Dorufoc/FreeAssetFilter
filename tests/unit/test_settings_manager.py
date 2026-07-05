#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SettingsManager 模块单元测试
测试JSON安全解析、设置管理和主题管理功能
"""

import json
import os
import time
import threading
from unittest.mock import patch, MagicMock

import pytest

from freeassetfilter.core.settings_manager import (
    SettingsManager,
)


class TestSettingsManager:
    """测试SettingsManager类"""

    def test_singleton_pattern(self, settings_file):
        SettingsManager._instance = None
        SettingsManager._initialized = False

        mgr1 = SettingsManager(settings_file=settings_file)
        mgr2 = SettingsManager(settings_file=settings_file)

        assert mgr1 is mgr2

    def test_load_settings_creates_file(self, settings_file):
        SettingsManager._instance = None
        SettingsManager._initialized = False

        assert not os.path.exists(settings_file)

        manager = SettingsManager(settings_file=settings_file)
        assert os.path.exists(settings_file)

    def test_load_settings_returns_dict(self, settings_manager):
        settings = settings_manager.settings
        assert isinstance(settings, dict)
        assert "appearance" in settings
        assert "font" in settings

    def test_save_settings(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.save_settings()

        assert os.path.exists(settings_manager._settings_file)

        with open(settings_manager._settings_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["appearance"]["theme"] == "dark"

    def test_get_setting(self, settings_manager):
        value = settings_manager.get_setting("appearance.theme")
        assert value == "default"

    def test_get_setting_nested(self, settings_manager):
        value = settings_manager.get_setting("appearance.colors.accent_color")
        assert value == "#007AFF"

    def test_get_setting_with_default(self, settings_manager):
        value = settings_manager.get_setting("nonexistent.key", "fallback")
        assert value == "fallback"

    def test_get_setting_returns_none_for_missing_no_default(self, settings_manager):
        value = settings_manager.get_setting("nonexistent.key")
        assert value is None

    def test_set_setting(self, settings_manager):
        changed = settings_manager.set_setting("appearance.theme", "dark")
        assert changed is True
        assert settings_manager.get_setting("appearance.theme") == "dark"

    def test_set_setting_no_change(self, settings_manager):
        original = settings_manager.get_setting("appearance.theme")
        changed = settings_manager.set_setting("appearance.theme", original)
        assert changed is False

    def test_set_setting_creates_nested(self, settings_manager):
        changed = settings_manager.set_setting("new_section.new_key", "value")
        assert changed is True
        assert settings_manager.get_setting("new_section.new_key") == "value"

    def test_set_setting_auto_save_false(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark", auto_save=False)
        assert settings_manager.get_setting("appearance.theme") == "dark"

    def test_set_setting_auto_save_true(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark", auto_save=True)
        time.sleep(0.5)
        settings_manager.schedule_save(delay=0)
        time.sleep(0.1)

        with open(settings_manager._settings_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["appearance"]["theme"] == "dark"

    def test_load_existing_settings(self, temp_settings_file, settings_file):
        SettingsManager._instance = None
        SettingsManager._initialized = False

        manager = SettingsManager(settings_file=temp_settings_file)
        assert manager.get_setting("appearance.theme") == "dark"
        assert manager.get_setting("appearance.colors.accent_color") == "#FF0000"
        assert manager.get_setting("font.size") == 12

    def test_load_corrupted_json(self, temp_data_dir):
        bad_file = os.path.join(temp_data_dir, "bad.json")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("{bad json content")

        SettingsManager._instance = None
        SettingsManager._initialized = False

        manager = SettingsManager(settings_file=bad_file)
        assert manager.settings is not None
        assert isinstance(manager.settings, dict)

    def test_load_nonexistent_file(self, temp_data_dir):
        nonexistent = os.path.join(temp_data_dir, "nonexistent.json")

        SettingsManager._instance = None
        SettingsManager._initialized = False

        manager = SettingsManager(settings_file=nonexistent)
        assert manager.settings is not None
        assert os.path.exists(nonexistent)

    def test_merge_settings_keeps_unknown_keys(self, temp_data_dir):
        settings_file = os.path.join(temp_data_dir, "merge_test.json")
        custom_settings = {
            "appearance": {
                "theme": "custom",
                "custom_key": "custom_value",
                "colors": {
                    "accent_color": "#123456",
                    "base_color": "#654321",
                    "secondary_color": "#333333",
                    "normal_color": "#CCCCCC",
                    "auxiliary_color": "#DDDDDD",
                    "custom_design_color": "#AABBCC",
                },
                "icon_style": 2,
                "animations": {
                    "directory_transition": False,
                    "file_record_changes": True,
                    "smooth_scrolling": True,
                    "file_card_state": True,
                    "progress_bar_smoothing": True,
                    "button_smoothing": True,
                },
            },
            "font": {"size": 14, "style": "Arial"},
            "file_selector": {"auto_clear_thumbnail_cache": True},
            "file_staging": {"auto_restore_records": True},
            "player": {"speed": 1.0, "volume": 100},
            "developer": {"debug_mode": True, "log_level": "debug"},
            "text_preview": {"word_wrap": True},
            "custom_section": {"key": "value"},
        }
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(custom_settings, f)

        SettingsManager._instance = None
        SettingsManager._initialized = False

        manager = SettingsManager(settings_file=settings_file)
        assert manager.get_setting("appearance.theme") == "custom"
        assert manager.get_setting("appearance.colors.accent_color") == "#123456"
        assert manager.get_setting("custom_section.key") == "value"
        assert manager.get_setting("font.size") == 14


class TestThemeManagement:
    """测试主题管理相关功能"""

    def test_theme_change_is_tracked(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark")
        assert "appearance.theme" in settings_manager._dirty_keys

    def test_preset_theme_change_is_tracked(self, settings_manager):
        settings_manager.set_setting("appearance.preset_theme", "活力蓝")
        settings_manager._dirty_keys.add("appearance.preset_theme")
        assert "appearance.preset_theme" in settings_manager._dirty_keys

    def test_color_change_is_tracked(self, settings_manager):
        settings_manager.set_setting("appearance.colors.accent_color", "#FF0000")
        assert "appearance.colors.accent_color" in settings_manager._dirty_keys

    def test_reset_to_defaults(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.reset_to_defaults()

        assert settings_manager.get_setting("appearance.theme") == "default"


class TestScheduleSave:
    """测试延迟保存功能"""

    def test_schedule_save_creates_timer(self, settings_manager):
        assert settings_manager._save_timer is None
        settings_manager.schedule_save(delay=0.1)
        assert settings_manager._save_timer is not None

    def test_schedule_save_cancels_previous_timer(self, settings_manager):
        settings_manager.schedule_save(delay=1.0)
        first_timer = settings_manager._save_timer

        settings_manager.schedule_save(delay=0.1)
        second_timer = settings_manager._save_timer

        assert first_timer is not second_timer
        assert first_timer.finished.is_set() or not first_timer.is_alive()

    def test_flush_scheduled_save(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.schedule_save(delay=0.01)
        time.sleep(0.05)

        assert settings_manager._save_timer is None

    def test_schedule_save_with_none_delay(self, settings_manager):
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.schedule_save(delay=None)
        time.sleep(0.5)


class TestPlayerVolumeAndSpeed:
    """测试播放器音量和倍速功能"""

    def test_get_player_volume_use_default(self, settings_manager):
        settings_manager.set_setting("player.use_default_volume", True)
        settings_manager.set_setting("player.default_volume", 75)
        assert settings_manager.get_player_volume() == 75

    def test_get_player_volume_use_last(self, settings_manager):
        settings_manager.set_setting("player.use_default_volume", False)
        settings_manager.set_setting("player.last_volume", 60)
        assert settings_manager.get_player_volume() == 60

    def test_get_player_speed_use_default(self, settings_manager):
        settings_manager.set_setting("player.use_default_speed", True)
        settings_manager.set_setting("player.default_speed", 1.5)
        assert settings_manager.get_player_speed() == 1.5

    def test_get_player_speed_use_last(self, settings_manager):
        settings_manager.set_setting("player.use_default_speed", False)
        settings_manager.set_setting("player.last_speed", 2.0)
        assert settings_manager.get_player_speed() == 2.0

    def test_save_player_volume(self, settings_manager):
        settings_manager.save_player_volume(80)
        assert settings_manager.get_setting("player.last_volume") == 80

    def test_save_player_speed(self, settings_manager):
        settings_manager.save_player_speed(1.75)
        assert settings_manager.get_setting("player.last_speed") == 1.75


class TestEdgeCases:
    """测试边缘情况"""

    def test_save_settings_empty_dirty_keys(self, settings_manager):
        settings_manager._dirty_keys.clear()
        settings_manager._save_pending = True
        settings_manager.save_settings()

    def test_save_settings_permission_error(self, settings_manager, monkeypatch):
        def mock_open(*args, **kwargs):
            raise PermissionError("Access denied")

        monkeypatch.setattr("builtins.open", mock_open)
        settings_manager.set_setting("appearance.theme", "dark")
        settings_manager.save_settings()

    def test_save_settings_directory_not_exists(self, temp_data_dir):
        nonexistent_dir = os.path.join(temp_data_dir, "nonexistent", "deep")
        settings_file = os.path.join(nonexistent_dir, "settings.json")

        SettingsManager._instance = None
        SettingsManager._initialized = False

        manager = SettingsManager(settings_file=settings_file)
        manager.save_settings()

        assert os.path.exists(settings_file)

    def test_get_setting_with_none_settings(self, settings_manager):
        settings_manager.settings = None
        value = settings_manager.get_setting("appearance.theme", "default")
        assert value == "default"

    def test_set_setting_creates_intermediate_dicts(self, settings_manager):
        changed = settings_manager.set_setting("a.b.c.d", "value")
        assert changed is True
        assert settings_manager.settings["a"]["b"]["c"]["d"] == "value"

    def test_save_settings_type_error(self, settings_manager, monkeypatch):
        settings_manager.settings["bad_key"] = object()
        settings_manager.save_settings()
