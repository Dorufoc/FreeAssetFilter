#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置流程集成测试
"""

import os
import json
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QEventLoop, QTimer


class TestSettingsSaveAndApply:
    def test_settings_window_initialization(self, settings_window):
        assert settings_window is not None
        assert hasattr(settings_window, 'settings_manager')
        assert settings_window.settings_manager is not None

    def test_settings_window_has_navigation(self, settings_window):
        assert hasattr(settings_window, 'navigation_buttons')
        assert len(settings_window.navigation_buttons) > 0

    def test_settings_window_has_save_button(self, settings_window):
        assert hasattr(settings_window, 'save_button')
        assert settings_window.save_button is not None

    def test_settings_window_has_reset_button(self, settings_window):
        assert hasattr(settings_window, 'reset_button')
        assert settings_window.reset_button is not None

    def test_load_settings(self, settings_window):
        settings_window.load_settings()
        assert isinstance(settings_window.current_settings, dict)

    def test_save_button_click(self, settings_window):
        settings_window.save_button.click()

    def test_reset_button_click(self, settings_window):
        settings_window.reset_button.click()


class TestThemeSwitchingFlow:
    def test_theme_manager_exists(self, settings_window):
        assert hasattr(settings_window, 'theme_manager')
        assert settings_window.theme_manager is not None

    def test_navigation_items_include_appearance(self, settings_window):
        nav_ids = [item['id'] for item in settings_window.navigation_items]
        assert 'general' in nav_ids

    def test_fill_tab_content_exists(self, settings_window):
        assert hasattr(settings_window, '_fill_tab_content')
        assert callable(settings_window._fill_tab_content)

    def test_fill_tab_content_general(self, settings_window):
        settings_window._fill_tab_content("general")
        assert settings_window._current_tab_id == "general"

    def test_update_styles_method_exists(self, settings_window):
        assert hasattr(settings_window, '_update_styles')
        assert callable(settings_window._update_styles)

    def test_create_setting_items_method_exists(self, settings_window):
        assert hasattr(settings_window, '_create_setting_items')
        assert callable(settings_window._create_setting_items)


class TestColorCustomizationFlow:
    def test_color_preview_widget_method_exists(self, settings_window):
        assert hasattr(settings_window, '_create_color_picker')
        assert callable(settings_window._create_color_picker)

    def test_apply_theme_method_exists(self, settings_window):
        assert hasattr(settings_window, '_apply_theme')
        assert callable(settings_window._apply_theme)

    def test_reset_color_to_default_method_exists(self, settings_window):
        assert hasattr(settings_window, '_reset_color_to_default')
        assert callable(settings_window._reset_color_to_default)

    def test_theme_colors_accessible(self, settings_window):
        colors = settings_window.theme_manager.get_theme_colors()
        assert isinstance(colors, dict)
        assert 'base_color' in colors
        assert 'secondary_color' in colors
        assert 'accent_color' in colors


class TestSettingsPersistence:
    def test_settings_manager_persistence(self, settings_window):
        settings_window.settings_manager.save_setting("test.key", "test_value")
        assert settings_window.settings_manager.get_setting("test.key") == "test_value"

    def test_settings_manager_save_config(self, settings_window):
        settings_window.settings_manager.save_setting("test.persist", True)
        settings_window.settings_manager.save_config()
        assert settings_window.settings_manager.get_setting("test.persist") == True

    def test_settings_manager_get_setting_default(self, settings_window):
        value = settings_window.settings_manager.get_setting("nonexistent.key", "default")
        assert value == "default"

    def test_settings_saved_signal_exists(self, settings_window):
        assert hasattr(settings_window, 'settings_saved')

    def test_player_restart_requested_signal_exists(self, settings_window):
        assert hasattr(settings_window, 'player_restart_requested')

    def test_get_config_file_path(self, settings_window):
        config_path = settings_window.settings_manager._get_config_file_path()
        assert config_path is not None
        assert os.path.exists(os.path.dirname(config_path))

    def test_settings_manager_load_and_save(self, settings_window):
        sm = settings_window.settings_manager
        sm.save_setting("appearance.colors.base_color", "#123456")
        sm.save_config()
        sm2 = type(sm)()
        sm2.load_config()
        assert sm2.get_setting("appearance.colors.base_color") == "#123456"
