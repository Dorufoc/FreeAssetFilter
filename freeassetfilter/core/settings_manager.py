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
            "font": {
                "size": 18,
                "style": "Microsoft YaHei"
            },
            "appearance": {
                "theme": "default",
                "colors": {
                    # 窗口颜色
                    "window_background": "#f1f3f5",
                    "window_border": "#e0e0e0",
                    
                    # 按钮颜色 - 通用（向后兼容）
                    "button_normal": "#ffffff",
                    "button_hover": "#e0e0e0",
                    "button_pressed": "#d0d0d0",
                    "button_text": "#333333",
                    "button_border": "#e0e0e0",
                    
                    # 按钮颜色 - 强调样式（primary）
                    "button_primary_normal": "#007AFF",
                    "button_primary_hover": "#0A84FF",
                    "button_primary_pressed": "#0056CC",
                    "button_primary_text": "#FFFFFF",
                    "button_primary_border": "#007AFF",
                    
                    # 按钮颜色 - 普通样式（normal）
                    "button_normal_normal": "#ffffff",
                    "button_normal_hover": "#e0e0e0",
                    "button_normal_pressed": "#d0d0d0",
                    "button_normal_text": "#333333",
                    "button_normal_border": "#e0e0e0",
                    
                    # 按钮颜色 - 次选样式（secondary）
                    "button_secondary_normal": "#ffffff",
                    "button_secondary_hover": "#e0e0e0",
                    "button_secondary_pressed": "#d0d0d0",
                    "button_secondary_text": "#007AFF",
                    "button_secondary_border": "#007AFF",
                    
                    # 按钮颜色 - 警告样式（warning）
                    "button_warning_normal": "#F44336",
                    "button_warning_hover": "#E63946",
                    "button_warning_pressed": "#D62828",
                    "button_warning_text": "#FFFFFF",
                    "button_warning_border": "#F44336",
                    
                    # 文字颜色
                    "text_normal": "#333333",
                    "text_disabled": "#999999",
                    "text_highlight": "#007AFF",
                    "text_placeholder": "#999999",
                    
                    # 输入框颜色
                    "input_background": "#ffffff",
                    "input_border": "#e0e0e0",
                    "input_focus_border": "#007AFF",
                    "input_text": "#333333",
                    
                    # 列表和表格颜色
                    "list_background": "#f1f3f5",
                    "list_item_normal": "#ffffff",
                    "list_item_hover": "#e0e0e0",
                    "list_item_selected": "#007AFF",
                    "list_item_text": "#333333",
                    
                    # 滑块颜色
                    "slider_track": "#e0e0e0",
                    "slider_handle": "#007AFF",
                    "slider_handle_hover": "#0A84FF",
                    
                    # 进度条颜色
                    "progress_bar_bg": "#e0e0e0",
                    "progress_bar_fg": "#007AFF",
                    
                    # 分隔线颜色
                    "separator": "#e0e0e0",
                    
                    # 通知颜色
                    "notification_info": "#007AFF",
                    "notification_success": "#4CAF50",
                    "notification_warning": "#FFC107",
                    "notification_error": "#F44336",
                    "notification_text": "#FFFFFF",
                    
                    # 标签页颜色
                    "tab_normal": "#ffffff",
                    "tab_selected": "#007AFF",
                    "tab_text_normal": "#666666",
                    "tab_text_selected": "#FFFFFF",
                    "tab_border": "#e0e0e0"
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