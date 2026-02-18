#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 设置管理模块
用于加载、保存和管理用户设置
"""

import os
import json
import copy
import threading
from functools import lru_cache


class SettingsManager:
    """
    设置管理类
    用于加载、保存和管理用户设置
    """
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, settings_file=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, settings_file=None):
        with self._lock:
            if SettingsManager._initialized:
                return

            SettingsManager._initialized = True
            self._settings_lock = threading.RLock()
            self.settings = None
            self._settings_file = settings_file
            self._initialize_settings()
    def _initialize_settings(self):
        if self._settings_file is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            data_dir = os.path.join(project_root, "data")
            with self._settings_lock:
                os.makedirs(data_dir, exist_ok=True)
            self._settings_file = os.path.join(data_dir, "settings.json")
        else:
            self._settings_file = self._settings_file

        self.default_settings = {
            "font": {
                "size": 10,
                "style": "Microsoft YaHei"
            },
            "appearance": {
                "theme": "default",
                "colors": {
                    "accent_color": "#0A59F7",
                    "secondary_color": "#333333",
                    "normal_color": "#e0e0e0",
                    "auxiliary_color": "#f1f3f5",
                    "base_color": "#FFFFFF",
                    "custom_design_color": "#27BE24"
                }
            },
            "file_selector": {
                "auto_clear_thumbnail_cache": True,
                "restore_last_path": True,
                "default_layout": "card",
                "cache_cleanup_period": 7,
                "cache_cleanup_threshold": 500,
                "return_shortcut": "middle_click"
            },
            "file_staging": {
                "auto_restore_records": True,
                "default_export_data_path": "",
                "default_export_file_path": "",
                "delete_original_after_export": False
            },
            "player": {
                "speed": 1.0,
                "volume": 100,
                "fluid_gradient_theme": "sunset",
                "audio_background_style": "流体动画",
                "use_default_volume": False,
                "default_volume": 100,
                "use_default_speed": True,
                "default_speed": 1.0,
                "last_volume": 100,
                "last_speed": 1.0,
                "enable_fullscreen": False
            },
            "developer": {
                "debug_mode": False,
                "log_level": "info"
            },
            "text_preview": {
                "word_wrap": True,
                "use_global_font": True,
                "custom_font_family": "Microsoft YaHei",
                "use_global_font_size": True,
                "custom_font_size": 12,
                "markdown_word_wrap": True,
                "markdown_use_global_font": True,
                "markdown_custom_font_family": "Microsoft YaHei",
                "markdown_use_global_font_size": True,
                "markdown_custom_font_size": 12
            },
            "video": {
                "lut_files": [],
                "active_lut_id": None
            }
        }
        self.settings = self.load_settings()
    
    def load_settings(self):
        try:
            with self._settings_lock:
                if os.path.exists(self._settings_file):
                    with open(self._settings_file, "r", encoding="utf-8") as f:
                        loaded_settings = json.load(f)
                        merged_settings = self._merge_settings(self.default_settings, loaded_settings)
                        self.settings = merged_settings
                        if merged_settings != loaded_settings:
                            self.save_settings()
                        return merged_settings
                else:
                    default_settings = self._create_default_settings_copy()
                    self.settings = default_settings
                    self.save_settings()
                    return default_settings
        except Exception as e:
            print(f"加载设置失败: {e}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            self.save_settings()
            return default_settings

    def _create_default_settings_copy(self):
        return {
            "font": self.default_settings["font"].copy(),
            "appearance": {
                "theme": self.default_settings["appearance"]["theme"],
                "colors": self.default_settings["appearance"]["colors"].copy()
            },
            "file_selector": self.default_settings["file_selector"].copy(),
            "file_staging": self.default_settings["file_staging"].copy(),
            "player": self.default_settings["player"].copy(),
            "developer": self.default_settings["developer"].copy(),
            "text_preview": self.default_settings["text_preview"].copy(),
            "video": {
                "lut_files": [],
                "active_lut_id": None
            }
        }

    def get_player_volume(self):
        """
        获取播放器音量
        如果使用默认音量则返回设置的默认音量，否则返回上次保存的音量

        Returns:
            int: 音量值 (0-100)
        """
        use_default = self.get_setting("player.use_default_volume", False)
        if use_default:
            return self.get_setting("player.default_volume", 100)
        else:
            return self.get_setting("player.last_volume", 100)

    def get_player_speed(self):
        """
        获取播放器倍速
        如果使用默认倍速则返回设置的默认倍速，否则返回上次保存的倍速

        Returns:
            float: 倍速值
        """
        use_default = self.get_setting("player.use_default_speed", True)
        if use_default:
            return self.get_setting("player.default_speed", 1.0)
        else:
            return self.get_setting("player.last_speed", 1.0)

    def save_player_volume(self, volume):
        """
        保存播放器音量到 last_volume

        Args:
            volume (int): 音量值 (0-100)
        """
        self.set_setting("player.last_volume", volume)
        self.save_settings()

    def save_player_speed(self, speed):
        """
        保存播放器倍速到 last_speed

        Args:
            speed (float): 倍速值
        """
        self.set_setting("player.last_speed", speed)
        self.save_settings()
    
    def save_settings(self):
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [SettingsManager.save_settings] {msg}")

        with self._settings_lock:
            debug("开始保存设置")
            debug(f"设置文件路径: {self._settings_file}")

            if "appearance" in self.settings and "colors" in self.settings["appearance"]:
                base_color_keys = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color", "custom_design_color"]
                filtered_colors = {}
                for color_key in base_color_keys:
                    if color_key in self.settings["appearance"]["colors"]:
                        filtered_colors[color_key] = self.settings["appearance"]["colors"][color_key]
                self.settings["appearance"]["colors"] = filtered_colors

            if "appearance" in self.settings and "colors" in self.settings["appearance"]:
                debug("当前主题颜色设置:")
                for color_key, color_value in self.settings["appearance"]["colors"].items():
                    debug(f"  {color_key}: {color_value}")

            try:
                with open(self._settings_file, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, ensure_ascii=False, indent=4)
                debug(f"设置保存成功: {self._settings_file}")
                print(f"设置已保存到: {self._settings_file}")
            except Exception as e:
                debug(f"设置保存失败: {e}")
                print(f"保存设置失败: {e}")
    
    def get_setting(self, key_path, default=None):
        if self.settings is None:
            return default

        with self._settings_lock:
            keys = key_path.split(".")
            value = self.settings

            try:
                for key in keys:
                    value = value[key]
                return value
            except (KeyError, TypeError):
                if default is not None:
                    self.set_setting(key_path, default)
                    self.save_settings()
                return default
    
    def set_setting(self, key_path, value):
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [SettingsManager.set_setting] {msg}")

        with self._settings_lock:
            if "appearance.colors" in key_path:
                debug(f"设置键路径: {key_path} = {value}")

            keys = key_path.split(".")
            settings = self.settings

            for key in keys[:-1]:
                if key not in settings:
                    settings[key] = {}
                settings = settings[key]

            settings[keys[-1]] = value

            if "appearance.colors" in key_path:
                debug(f"设置完成: {key_path} = {value}")
                self.save_settings()
    
    def _merge_settings(self, default, loaded):
        base_color_keys = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color", "custom_design_color"]

        merged = {
            "font": default["font"].copy(),
            "appearance": {
                "theme": default["appearance"]["theme"],
                "colors": default["appearance"]["colors"].copy()
            },
            "file_selector": default["file_selector"].copy(),
            "file_staging": default["file_staging"].copy(),
            "player": default["player"].copy(),
            "developer": default["developer"].copy(),
            "text_preview": default["text_preview"].copy()
        }

        for key, value in loaded.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                if key == "appearance":
                    if "theme" in value:
                        merged[key]["theme"] = value["theme"]
                    if "colors" in value:
                        for color_key in base_color_keys:
                            if color_key in value["colors"]:
                                merged[key]["colors"][color_key] = value["colors"][color_key]
                elif key == "colors":
                    for color_key in base_color_keys:
                        if color_key in value:
                            merged["appearance"]["colors"][color_key] = value[color_key]
                elif key in ("font", "file_selector", "file_staging", "player", "developer", "text_preview"):
                    merged[key] = value.copy()
                else:
                    merged[key] = value
            else:
                merged[key] = value

        return merged

    def reset_to_defaults(self):
        with self._settings_lock:
            self.settings = self._create_default_settings_copy()