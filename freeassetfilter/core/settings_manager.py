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
import tempfile
from functools import lru_cache

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error


class JSONDepthExceededError(Exception):
    """JSON解析深度超出限制错误"""
    pass


class JSONSizeExceededError(Exception):
    """JSON文件大小超出限制错误"""
    pass


def _check_json_depth(obj, current_depth=0, max_depth=50):
    """
    递归检查JSON对象的嵌套深度

    Args:
        obj: 要检查的对象
        current_depth: 当前深度
        max_depth: 最大允许深度

    Raises:
        JSONDepthExceededError: 如果深度超过限制
    """
    if current_depth > max_depth:
        raise JSONDepthExceededError(f"JSON嵌套深度超过最大限制 ({max_depth}层)")

    if isinstance(obj, dict):
        for value in obj.values():
            _check_json_depth(value, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            _check_json_depth(item, current_depth + 1, max_depth)


def safe_json_loads(json_str, max_depth=50):
    """
    安全地解析JSON字符串，带有深度限制

    Args:
        json_str: JSON字符串
        max_depth: 最大允许深度

    Returns:
        解析后的Python对象

    Raises:
        JSONDepthExceededError: 如果深度超过限制
        json.JSONDecodeError: 如果JSON格式错误
    """
    data = json.loads(json_str)
    _check_json_depth(data, current_depth=0, max_depth=max_depth)
    return data


def safe_json_load(file_path, max_depth=50, max_size_bytes=10*1024*1024):
    """
    安全地从文件加载JSON，带有深度和大小限制

    Args:
        file_path: JSON文件路径
        max_depth: 最大允许深度
        max_size_bytes: 最大允许文件大小（字节）

    Returns:
        解析后的Python对象

    Raises:
        JSONSizeExceededError: 如果文件大小超过限制
        JSONDepthExceededError: 如果深度超过限制
        json.JSONDecodeError: 如果JSON格式错误
    """
    # 检查文件大小
    file_size = os.path.getsize(file_path)
    if file_size > max_size_bytes:
        raise JSONSizeExceededError(
            f"JSON文件大小 ({file_size} 字节) 超过最大限制 ({max_size_bytes} 字节, {max_size_bytes//1024//1024}MB)"
        )

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        data = json.loads(content)
        _check_json_depth(data, current_depth=0, max_depth=max_depth)
        return data


class SettingsManager:
    """
    设置管理类
    用于加载、保存和管理用户设置
    """
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    # JSON解析安全限制
    MAX_JSON_DEPTH = 50          # 最大JSON解析深度
    MAX_JSON_SIZE_MB = 10        # 最大JSON文件大小（MB）
    MAX_JSON_SIZE_BYTES = MAX_JSON_SIZE_MB * 1024 * 1024  # 转换为字节

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
                "colors": {
                    "accent_color": "#007AFF",
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
        try:
            with self._settings_lock:
                if os.path.exists(self._settings_file):
                    # 使用安全的JSON加载，带有深度和大小限制
                    loaded_settings = safe_json_load(
                        self._settings_file,
                        max_depth=self.MAX_JSON_DEPTH,
                        max_size_bytes=self.MAX_JSON_SIZE_BYTES
                    )
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
        except FileNotFoundError:
            warning(f"设置文件不存在，使用默认设置: {self._settings_file}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            self.save_settings()
            return default_settings
        except JSONSizeExceededError as e:
            error(f"设置文件大小超出安全限制: {e}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            return default_settings
        except JSONDepthExceededError as e:
            error(f"设置文件嵌套深度超出安全限制: {e}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            return default_settings
        except json.JSONDecodeError as e:
            error(f"设置文件JSON格式错误: {e}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            self.save_settings()
            return default_settings
        except PermissionError as e:
            error(f"读取设置文件权限不足: {e}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            return default_settings
        except UnicodeDecodeError as e:
            error(f"设置文件编码错误: {e}")
            default_settings = self._create_default_settings_copy()
            self.settings = default_settings
            self.save_settings()
            return default_settings

    def _create_default_settings_copy(self):
        return {
            "font": self.default_settings["font"].copy(),
            "appearance": {
                "theme": self.default_settings["appearance"]["theme"],
                "icon_style": self.default_settings["appearance"]["icon_style"],
                "preset_theme": self.default_settings["appearance"].get("preset_theme", ""),
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
            pending_before_save = self._save_pending
            theme_dirty = any(
                key == "appearance.theme"
                or key == "appearance.preset_theme"
                or key.startswith("appearance.colors.")
                for key in dirty_keys
            )

            if dirty_keys:
                debug(f"保存设置，变更项: {', '.join(dirty_keys)}")
            elif pending_before_save:
                debug("保存设置")

            self._save_pending = False
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None

            if "appearance" in self.settings and "colors" in self.settings["appearance"]:
                base_color_keys = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color", "custom_design_color"]
                filtered_colors = {}
                for color_key in base_color_keys:
                    if color_key in self.settings["appearance"]["colors"]:
                        filtered_colors[color_key] = self.settings["appearance"]["colors"][color_key]
                self.settings["appearance"]["colors"] = filtered_colors

            if "appearance" in self.settings:
                preset_theme = self.settings["appearance"].get("preset_theme", "")
                if preset_theme:
                    self.settings["appearance"]["preset_theme"] = preset_theme
                else:
                    self.settings["appearance"].pop("preset_theme", None)

            if theme_dirty and "appearance" in self.settings and "colors" in self.settings["appearance"]:
                debug(f"主题颜色: {self.settings['appearance']['colors']}")

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
    
    def get_setting(self, key_path, default=None, use_file_for_colors=False):
        """
        获取设置值

        Args:
            key_path: 设置键路径，如 "appearance.colors.accent_color"
            default: 默认值
            use_file_for_colors: 如果为True，颜色设置直接从JSON文件读取，绕过内存缓存

        Returns:
            设置值
        """
        # 如果是颜色设置且要求从文件读取，直接读取文件
        if use_file_for_colors and "appearance.colors." in key_path:
            color_key = key_path.replace("appearance.colors.", "")
            return self.get_color_from_file(color_key, default)

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
                if default is not None and not key_path.startswith("appearance.colors."):
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

            if key_path == "appearance.theme" or key_path == "appearance.preset_theme":
                debug(f"主题变更: {key_path}={value}")
            elif key_path.startswith("appearance.colors."):
                debug(f"颜色变更: {key_path}={value}")

            # 只有显式要求时才自动保存，但使用延迟合并写盘避免高频 I/O
            if auto_save:
                self.schedule_save()

            return True
    
    def _merge_settings(self, default, loaded):
        base_color_keys = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color", "custom_design_color"]

        merged = {
            "font": default["font"].copy(),
            "appearance": {
                "theme": default["appearance"]["theme"],
                "icon_style": default["appearance"]["icon_style"],
                "preset_theme": default["appearance"].get("preset_theme", ""),
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
                    if "icon_style" in value:
                        merged[key]["icon_style"] = value["icon_style"]
                    if "preset_theme" in value:
                        merged[key]["preset_theme"] = value["preset_theme"]
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
            self._dirty_keys.add("__reset_to_defaults__")
            self._save_pending = True

    def get_color_from_file(self, color_key, default=None):
        """
        直接从JSON文件读取颜色值，绕过内存缓存
        用于前端获取颜色，确保获取到的是持久化的颜色值

        Args:
            color_key: 颜色键名，如 "accent_color", "secondary_color" 等
            default: 默认值，如果文件中没有该颜色则返回此值

        Returns:
            str: 颜色值（十六进制格式）
        """
        with self._settings_lock:
            try:
                if os.path.exists(self._settings_file):
                    # 使用安全的JSON加载
                    file_settings = safe_json_load(
                        self._settings_file,
                        max_depth=self.MAX_JSON_DEPTH,
                        max_size_bytes=self.MAX_JSON_SIZE_BYTES
                    )
                    colors = file_settings.get("appearance", {}).get("colors", {})
                    return colors.get(color_key, default)
                else:
                    # 文件不存在时返回默认值
                    return self.default_settings.get("appearance", {}).get("colors", {}).get(color_key, default)
            except FileNotFoundError:
                warning(f"设置文件不存在，使用默认颜色: {self._settings_file}")
                return self.default_settings.get("appearance", {}).get("colors", {}).get(color_key, default)
            except (JSONSizeExceededError, JSONDepthExceededError) as e:
                error(f"设置文件超出安全限制，无法读取颜色: {e}")
                return self.default_settings.get("appearance", {}).get("colors", {}).get(color_key, default)
            except json.JSONDecodeError as e:
                error(f"设置文件JSON格式错误，无法读取颜色: {e}")
                return self.default_settings.get("appearance", {}).get("colors", {}).get(color_key, default)
            except PermissionError as e:
                error(f"读取设置文件权限不足: {e}")
                return default
            except KeyError:
                debug(f"颜色键 '{color_key}' 不存在，使用默认值")
                return default
            except UnicodeDecodeError as e:
                error(f"设置文件编码错误: {e}")
                return self.default_settings.get("appearance", {}).get("colors", {}).get(color_key, default)

    def get_all_colors_from_file(self):
        """
        直接从JSON文件读取所有颜色值，绕过内存缓存

        Returns:
            dict: 颜色字典，包含所有颜色键值对
        """
        with self._settings_lock:
            try:
                if os.path.exists(self._settings_file):
                    # 使用安全的JSON加载
                    file_settings = safe_json_load(
                        self._settings_file,
                        max_depth=self.MAX_JSON_DEPTH,
                        max_size_bytes=self.MAX_JSON_SIZE_BYTES
                    )
                    return file_settings.get("appearance", {}).get("colors", self.default_settings["appearance"]["colors"].copy())
                else:
                    return self.default_settings["appearance"]["colors"].copy()
            except FileNotFoundError:
                warning(f"设置文件不存在，使用默认颜色: {self._settings_file}")
                return self.default_settings["appearance"]["colors"].copy()
            except (JSONSizeExceededError, JSONDepthExceededError) as e:
                error(f"设置文件超出安全限制，无法读取颜色: {e}")
                return self.default_settings["appearance"]["colors"].copy()
            except json.JSONDecodeError as e:
                error(f"设置文件JSON格式错误，无法读取颜色: {e}")
                return self.default_settings["appearance"]["colors"].copy()
            except PermissionError as e:
                error(f"读取设置文件权限不足: {e}")
                return self.default_settings["appearance"]["colors"].copy()
            except UnicodeDecodeError as e:
                error(f"设置文件编码错误: {e}")
                return self.default_settings["appearance"]["colors"].copy()
