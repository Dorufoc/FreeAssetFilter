#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 设置管理模块
用于加载、保存和管理用户设置
"""

import os
import json


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
            "dpi": {
                "global_scale_factor": 1.0
            },
            "font": {
                "size": 20,
                "style": "Microsoft YaHei"
            },
            "appearance": {
                "theme": "default",
                "colors": {
                    # 窗口颜色
                    "window_background": "#1E1E1E",
                    "window_border": "#3C3C3C",
                    
                    # 按钮颜色 - 通用（向后兼容）
                    "button_normal": "#2D2D2D",
                    "button_hover": "#3C3C3C",
                    "button_pressed": "#4C4C4C",
                    "button_text": "#FFFFFF",
                    "button_border": "#5C5C5C",
                    
                    # 按钮颜色 - 强调样式（primary）
                    "button_primary_normal": "#2D2D2D",
                    "button_primary_hover": "#3C3C3C",
                    "button_primary_pressed": "#4C4C4C",
                    "button_primary_text": "#FFFFFF",
                    "button_primary_border": "#5C5C5C",
                    
                    # 按钮颜色 - 普通样式（normal）
                    "button_normal_normal": "#1E1E1E",
                    "button_normal_hover": "#3C3C3C",
                    "button_normal_pressed": "#4ECDC4",
                    "button_normal_text": "#FFFFFF",
                    "button_normal_border": "#3C3C3C",
                    
                    # 按钮颜色 - 次选样式（secondary）
                    "button_secondary_normal": "#1E1E1E",
                    "button_secondary_hover": "#3C3C3C",
                    "button_secondary_pressed": "#4ECDC4",
                    "button_secondary_text": "#4ECDC4",
                    "button_secondary_border": "#4ECDC4",
                    
                    # 文字颜色
                    "text_normal": "#FFFFFF",
                    "text_disabled": "#888888",
                    "text_highlight": "#4ECDC4",
                    "text_placeholder": "#666666",
                    
                    # 输入框颜色
                    "input_background": "#2D2D2D",
                    "input_border": "#3C3C3C",
                    "input_focus_border": "#4ECDC4",
                    "input_text": "#FFFFFF",
                    
                    # 列表和表格颜色
                    "list_background": "#1E1E1E",
                    "list_item_normal": "#2D2D2D",
                    "list_item_hover": "#3C3C3C",
                    "list_item_selected": "#4ECDC4",
                    "list_item_text": "#FFFFFF",
                    
                    # 滑块颜色
                    "slider_track": "#3C3C3C",
                    "slider_handle": "#4ECDC4",
                    "slider_handle_hover": "#5EE0D8",
                    
                    # 进度条颜色
                    "progress_bar_bg": "#3C3C3C",
                    "progress_bar_fg": "#4ECDC4",
                    
                    # 分隔线颜色
                    "separator": "#3C3C3C",
                    
                    # 通知颜色
                    "notification_info": "#4ECDC4",
                    "notification_success": "#4CAF50",
                    "notification_warning": "#FFC107",
                    "notification_error": "#F44336",
                    "notification_text": "#FFFFFF",
                    
                    # 标签页颜色
                    "tab_normal": "#2D2D2D",
                    "tab_selected": "#4ECDC4",
                    "tab_text_normal": "#AAAAAA",
                    "tab_text_selected": "#FFFFFF",
                    "tab_border": "#3C3C3C"
                }
            },
            "file_selector": {
                "auto_clear_thumbnail_cache": True,
                "restore_last_path": True,
                "default_layout": "card"
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
                default_settings = self.default_settings.copy()
                # 先将默认设置赋值给self.settings，再保存
                self.settings = default_settings
                self.save_settings()
                return default_settings
        except Exception as e:
            print(f"加载设置失败: {e}")
            # 加载失败，返回默认设置并保存到文件
            default_settings = self.default_settings.copy()
            # 先将默认设置赋值给self.settings，再保存
            self.settings = default_settings
            self.save_settings()
            return default_settings
    
    def save_settings(self):
        """
        将当前设置保存到JSON文件
        """
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            print(f"设置已保存到: {self.settings_file}")
        except Exception as e:
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
        keys = key_path.split(".")
        settings = self.settings
        
        # 遍历除最后一个键外的所有键，确保路径存在
        for key in keys[:-1]:
            if key not in settings:
                settings[key] = {}
            settings = settings[key]
        
        # 设置最后一个键的值
        settings[keys[-1]] = value
    
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
        merged = default.copy()
        
        for key, value in loaded.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                # 如果是嵌套字典，递归合并
                merged[key] = self._merge_settings(merged[key], value)
            else:
                # 否则，使用加载的设置值
                merged[key] = value
        
        return merged