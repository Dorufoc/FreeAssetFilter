#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 设置管理模块
用于加载、保存和管理用户设置
"""

import os
import json
import threading
import tempfile

from freeassetfilter.utils.app_logger import info, debug, warning, error


def _load_json_file(file_path):
    """从文件加载 JSON，附带基础文件大小保护。"""
    MAX_SIZE = 10 * 1024 * 1024
    file_size = os.path.getsize(file_path)
    if file_size > MAX_SIZE:
        raise ValueError(f"JSON 文件大小 ({file_size} 字节) 超过最大限制 ({MAX_SIZE} 字节)")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _apply_private_file_permissions(file_path):
    """尽量限制设置文件权限，降低本机其他账户读取敏感路径信息的风险。"""
    try:
        os.chmod(file_path, 0o600)
    except (OSError, PermissionError, FileNotFoundError, ValueError, TypeError):
        pass


class SettingsManager:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    BASE_COLOR_KEYS = [
        "accent_color", "secondary_color", "normal_color",
        "auxiliary_color", "base_color", "custom_design_color", "panel_background",
    ]

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
            self._color_cache: dict[str, str] = {}
            self._color_cache_lock = threading.Lock()
            self._save_timer = None
            self._save_delay_seconds = 0.35
            self._save_pending = False
            self._dirty_keys = set()
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
                "icon_style": 0,
                "preset_theme": "活力蓝",
                "animations": {
                    "directory_transition": True,
                    "file_record_changes": True,
                    "smooth_scrolling": True,
                    "file_card_state": True,
                    "progress_bar_smoothing": True,
                    "button_smoothing": True
                },
                "colors": {
                    "accent_color": "#007AFF",
                    "secondary_color": "#333333",
                    "normal_color": "#e0e0e0",
                    "auxiliary_color": "#f1f3f5",
                    "base_color": "#FFFFFF",
                    "custom_design_color": "#27BE24",
                    "panel_background": "#f1f3f5"
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
                "enable_fullscreen": False,
                "control_bar_show_fullscreen": True,
                "control_bar_show_lut": False,
                "control_bar_show_subtitle": False,
                "control_bar_show_audio": True,
                "control_bar_show_volume": True,
                "control_bar_show_speed": True,
                "fullscreen_classic_control_bar": True,
                "control_bar_timeout": 3
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
            },
            "photo_viewer": {
                "style": {
                    "bg_color_key": "base_color",
                    "remember_bg_color": True
                }
            }
        }
        self.settings = self.load_settings()
    
    def load_settings(self):
        with self._settings_lock:
            if not os.path.exists(self._settings_file):
                defaults = self._create_default_settings_copy()
                self.settings = defaults
                self.save_settings()
                return defaults
            try:
                loaded = _load_json_file(self._settings_file)
                merged = self._merge_settings(self.default_settings, loaded)
                self.settings = merged
                return merged
            except (FileNotFoundError, json.JSONDecodeError, PermissionError, UnicodeDecodeError, ValueError) as e:
                warning(f"读取设置文件失败 ({type(e).__name__}: {e})，使用默认设置")
                defaults = self._create_default_settings_copy()
                self.settings = defaults
                self.save_settings()
                return defaults

    def _create_default_settings_copy(self):
        return {
            "font": self.default_settings["font"].copy(),
            "appearance": {
                "theme": self.default_settings["appearance"]["theme"],
                "icon_style": self.default_settings["appearance"]["icon_style"],
                "preset_theme": self.default_settings["appearance"].get("preset_theme", ""),
                "animations": self.default_settings["appearance"]["animations"].copy(),
                "colors": self.default_settings["appearance"]["colors"].copy(),
            },
            "file_selector": self.default_settings["file_selector"].copy(),
            "file_staging": self.default_settings["file_staging"].copy(),
            "player": self.default_settings["player"].copy(),
            "developer": self.default_settings["developer"].copy(),
            "text_preview": self.default_settings["text_preview"].copy(),
            "video": {
                "lut_files": list(self.default_settings["video"]["lut_files"]),
                "active_lut_id": self.default_settings["video"]["active_lut_id"],
            },
            "photo_viewer": {
                "style": dict(self.default_settings["photo_viewer"]["style"]),
            },
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
        self.schedule_save()

    def save_player_speed(self, speed):
        """
        保存播放器倍速到 last_speed

        Args:
            speed (float): 倍速值
        """
        self.set_setting("player.last_speed", speed)
        self.schedule_save()

    def schedule_save(self, delay=None):
        """
        延迟调度设置写盘，将高频设置变更合并为一次磁盘写入。

        Args:
            delay: 延迟秒数，None 时使用默认延迟
        """
        with self._settings_lock:
            if delay is None:
                delay = self._save_delay_seconds

            self._save_pending = True
            # 重置时也清除颜色缓存
            with self._color_cache_lock:
                self._color_cache.clear()

            if self._save_timer is not None:
                self._save_timer.cancel()

            self._save_timer = threading.Timer(delay, self._flush_scheduled_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _flush_scheduled_save(self):
        """执行已调度的设置写盘"""
        with self._settings_lock:
            self._save_timer = None
            if not self._save_pending:
                return

        self.save_settings()

    def save_settings(self):
        with self._settings_lock:
            dirty_keys = sorted(self._dirty_keys)
            if dirty_keys:
                debug(f"保存设置，变更项: {', '.join(dirty_keys)}")

            self._save_pending = False
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None

            try:
                settings_dir = os.path.dirname(self._settings_file) or "."
                os.makedirs(settings_dir, exist_ok=True)

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=settings_dir,
                    delete=False,
                    suffix=".tmp"
                ) as tmp_file:
                    json.dump(self.settings, tmp_file, ensure_ascii=False, indent=4)
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                    temp_path = tmp_file.name

                os.replace(temp_path, self._settings_file)
                _apply_private_file_permissions(self._settings_file)

                self._dirty_keys.clear()
                info(f"设置已保存: {self._settings_file}")
            except PermissionError as e:
                error(f"保存设置失败，权限不足: {e}")
            except FileNotFoundError as e:
                error(f"保存设置失败，目录不存在: {e}")
            except TypeError as e:
                error(f"保存设置失败，数据类型错误: {e}")
            except IOError as e:
                error(f"保存设置失败，IO错误: {e}")
            finally:
                temp_path = locals().get("temp_path")
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
    
    def get_setting(self, key_path, default=None):
        """
        获取设置值

        Args:
            key_path: 设置键路径，如 "appearance.colors.accent_color"
            default: 默认值

        Returns:
            设置值
        """
        # 颜色快速路径：使用内存缓存，避免字典遍历
        if key_path.startswith("appearance.colors."):
            color_key = key_path.split(".")[-1]
            with self._color_cache_lock:
                if color_key in self._color_cache:
                    return self._color_cache[color_key]

            # 缓存未命中，从内存设置中读取
            with self._settings_lock:
                if self.settings is None:
                    return default
                color_value = self.settings.get("appearance", {}).get("colors", {}).get(color_key, default)

                with self._color_cache_lock:
                    self._color_cache[color_key] = color_value
            return color_value

        with self._settings_lock:
            if self.settings is None:
                return default

            keys = key_path.split(".")
            value = self.settings

            try:
                for key in keys:
                    value = value[key]
                return value
            except (KeyError, TypeError):
                if default is not None:
                    # 使用auto_save=True确保默认值被持久化
                    self.set_setting(key_path, default, auto_save=True)
                return default
    def set_setting(self, key_path, value, auto_save=False):
        """
        设置配置值

        Args:
            key_path: 配置键路径，如 "appearance.colors.accent_color"
            value: 配置值
            auto_save: 是否自动保存到文件，默认为False
                      设置为True时立即写入JSON，否则只在内存中更新
        """
        with self._settings_lock:
            keys = key_path.split(".")
            settings = self.settings

            for key in keys[:-1]:
                if key not in settings or not isinstance(settings[key], dict):
                    settings[key] = {}
                settings = settings[key]

            old_value = settings.get(keys[-1])
            if old_value == value:
                return False

            settings[keys[-1]] = value
            self._dirty_keys.add(key_path)

            # 颜色变更时清除缓存
            if key_path.startswith("appearance.colors."):
                with self._color_cache_lock:
                    self._color_cache.clear()

            if key_path == "appearance.theme" or key_path == "appearance.preset_theme":
                debug(f"主题变更: {key_path}={value}")
            elif key_path.startswith("appearance.colors."):
                debug(f"颜色变更: {key_path}={value}")

            # 只有显式要求时才自动保存，但使用延迟合并写盘避免高频 I/O
            if auto_save:
                self.schedule_save()

            return True
    
    def _merge_settings(self, default, loaded):
        merged = self._create_default_settings_copy()

        for key, value in loaded.items():
            if key not in merged:
                merged[key] = value
                continue
            if not isinstance(merged[key], dict) or not isinstance(value, dict):
                merged[key] = value
                continue

            if key == "appearance":
                for sub_key in ("theme", "icon_style", "preset_theme"):
                    if sub_key in value:
                        merged["appearance"][sub_key] = value[sub_key]
                if "animations" in value and isinstance(value["animations"], dict):
                    for ak, av in value["animations"].items():
                        if ak in merged["appearance"]["animations"]:
                            merged["appearance"]["animations"][ak] = av
                if "colors" in value:
                    for ck in self.BASE_COLOR_KEYS:
                        if ck in value["colors"]:
                            merged["appearance"]["colors"][ck] = value["colors"][ck]
            elif key in ("font", "file_selector", "file_staging", "player", "developer", "text_preview"):
                for sub_key, sub_val in value.items():
                    if sub_key in merged[key]:
                        merged[key][sub_key] = sub_val
            else:
                merged[key] = value

        return merged

    def reset_to_defaults(self):
        with self._settings_lock:
            self.settings = self._create_default_settings_copy()
            self._dirty_keys.add("__reset_to_defaults__")
            self._save_pending = True

    def get_colors_dict(self):
        """
        从内存中读取所有颜色值

        Returns:
            dict: 颜色字典，包含所有颜色键值对
        """
        with self._settings_lock:
            if self.settings is None:
                return self.default_settings["appearance"]["colors"].copy()
            return self.settings.get("appearance", {}).get("colors", self.default_settings["appearance"]["colors"]).copy()



