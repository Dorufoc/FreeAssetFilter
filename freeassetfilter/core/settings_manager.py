#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 设置管理模块
用于加载、保存和管理用户设置
"""

import os
import json
import copy


class SettingsManager:
    """
    设置管理类
    用于加载、保存和管理用户设置
    """
    
    def __init__(self, settings_file=None):
        """
        初始化设置管理器
        
        Args:
            settings_file (str, optional): 设置文件路径. 默认值为 None，将使用默认路径
        """
        # 设置默认设置文件路径
        if settings_file is None:
            # 获取项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            # 创建data目录（如果不存在）
            data_dir = os.path.join(project_root, "data")
            os.makedirs(data_dir, exist_ok=True)
            # 设置文件路径
            self.settings_file = os.path.join(data_dir, "settings.json")
        else:
            self.settings_file = settings_file
        
        # 默认设置
        self.default_settings = {
            "font": {
                "size": 8,
                "style": "Microsoft YaHei"
            },
            "appearance": {
                "theme": "default",
                "colors": {
                    # 基础颜色配置
                    "accent_color": "#B036EE",      # 强调色
                    "secondary_color": "#333333",   # 次选色
                    "normal_color": "#e0e0e0",      # 普通色
                    "auxiliary_color": "#f1f3f5",    # 辅助色
                    "base_color": "#FFFFFF"        # 底层色
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
                "volume": 100
            }
        }
        
        # 加载设置
        self.settings = self.load_settings()
    
    def load_settings(self):
        """
        从JSON文件加载设置
        
        Returns:
            dict: 加载的设置，如果文件不存在或加载失败则返回默认设置
        """
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                    # 合并默认设置和加载的设置，确保所有必要的设置项都存在
                    merged_settings = self._merge_settings(self.default_settings, loaded_settings)
                    # 先将合并后的设置赋值给self.settings，再保存
                    self.settings = merged_settings
                    # 如果合并后的设置与加载的设置不同，说明有缺失项，保存更新后的设置
                    if merged_settings != loaded_settings:
                        self.save_settings()
                    return merged_settings
            else:
                # 文件不存在，返回默认设置并保存到文件
                default_settings = copy.deepcopy(self.default_settings)
                # 先将默认设置赋值给self.settings，再保存
                self.settings = default_settings
                self.save_settings()
                return default_settings
        except Exception as e:
            print(f"加载设置失败: {e}")
            # 加载失败，返回默认设置并保存到文件
            default_settings = copy.deepcopy(self.default_settings)
            # 先将默认设置赋值给self.settings，再保存
            self.settings = default_settings
            self.save_settings()
            return default_settings
    
    def save_settings(self):
        """
        将当前设置保存到JSON文件
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [SettingsManager.save_settings] {msg}")
        
        debug("开始保存设置")
        debug(f"设置文件路径: {self.settings_file}")
        
        # 保存前过滤颜色设置，只保留基础颜色
        if "appearance" in self.settings and "colors" in self.settings["appearance"]:
            # 定义需要保留的基础颜色键
            base_color_keys = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color"]
            # 创建新的颜色字典，只保留基础颜色
            filtered_colors = {}
            for color_key in base_color_keys:
                if color_key in self.settings["appearance"]["colors"]:
                    filtered_colors[color_key] = self.settings["appearance"]["colors"][color_key]
            # 替换原有的颜色字典
            self.settings["appearance"]["colors"] = filtered_colors
        
        # 显示主题颜色设置
        if "appearance" in self.settings and "colors" in self.settings["appearance"]:
            debug("当前主题颜色设置:")
            for color_key, color_value in self.settings["appearance"]["colors"].items():
                debug(f"  {color_key}: {color_value}")
        
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            debug(f"设置保存成功: {self.settings_file}")
            print(f"设置已保存到: {self.settings_file}")
        except Exception as e:
            debug(f"设置保存失败: {e}")
            print(f"保存设置失败: {e}")
    
    def get_setting(self, key_path, default=None):
        """
        获取指定路径的设置值
        
        Args:
            key_path (str): 设置键路径，使用点分隔，如 "dpi.global_scale_factor"
            default: 默认值，如果路径不存在则返回并添加到设置中
        
        Returns:
            对应路径的设置值，如果路径不存在则返回默认值
        """
        keys = key_path.split(".")
        value = self.settings
        
        try:
            # 尝试获取设置值
            for key in keys:
                value = value[key]
            return value
        except KeyError:
            # 设置项不存在，使用默认值
            if default is not None:
                # 将默认值添加到设置中
                self.set_setting(key_path, default)
                # 保存更新后的设置
                self.save_settings()
            return default
    
    def set_setting(self, key_path, value):
        """
        设置指定路径的设置值
        
        Args:
            key_path (str): 设置键路径，使用点分隔，如 "dpi.global_scale_factor"
            value: 要设置的值
        """
        import datetime
        def debug(msg):
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] [SettingsManager.set_setting] {msg}")
        
        # 移除对颜色设置的限制，允许保存所有颜色设置
        
        # 仅当设置与主题颜色相关时才输出详细debug信息
        if "appearance.colors" in key_path:
            debug(f"设置键路径: {key_path} = {value}")
        
        keys = key_path.split(".")
        settings = self.settings
        
        # 遍历除最后一个键外的所有键，确保路径存在
        for key in keys[:-1]:
            if key not in settings:
                settings[key] = {}
            settings = settings[key]
        
        # 设置最后一个键的值
        settings[keys[-1]] = value
        
        if "appearance.colors" in key_path:
            debug(f"设置完成: {key_path} = {value}")
    
    def _merge_settings(self, default, loaded):
        """
        合并默认设置和加载的设置
        递归合并字典，确保所有必要的设置项都存在
        
        Args:
            default (dict): 默认设置
            loaded (dict): 加载的设置
        
        Returns:
            dict: 合并后的设置
        """
        merged = copy.deepcopy(default)
        
        for key, value in loaded.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # 如果是颜色字典，只保留基础颜色设置
                if key == "colors" and "appearance" in merged:
                    # 定义需要保留的基础颜色键
                    base_color_keys = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color"]
                    # 创建新的颜色字典，只保留基础颜色
                    merged_colors = {}
                    # 首先复制默认的基础颜色
                    for color_key in base_color_keys:
                        if color_key in merged[key]:
                            merged_colors[color_key] = merged[key][color_key]
                    # 然后用加载的设置中的基础颜色覆盖默认值
                    for color_key in base_color_keys:
                        if color_key in value:
                            merged_colors[color_key] = value[color_key]
                    merged[key] = merged_colors
                else:
                    # 其他嵌套字典，递归合并
                    merged[key] = self._merge_settings(merged[key], value)
            else:
                # 否则，使用加载的设置值
                merged[key] = value
        
        return merged
    
    def reset_to_defaults(self):
        """
        重置所有设置为默认值
        """
        self.settings = copy.deepcopy(self.default_settings)