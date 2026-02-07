#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 主题管理器组件
集中管理应用的主题颜色和主题切换功能
"""

from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QColor

# 导入设置管理器
from freeassetfilter.core.settings_manager import SettingsManager


class ThemeManager(QObject):
    """
    主题管理器类
    负责管理应用的主题颜色和主题切换功能
    
    信号：
        theme_changed: 主题变更时发出的信号
        colors_updated: 颜色更新时发出的信号
    """
    
    theme_changed = pyqtSignal(str)  # 主题变更信号，参数为新主题名称
    colors_updated = pyqtSignal(dict)  # 颜色更新信号，参数为新颜色字典
    
    def __init__(self, settings_manager=None):
        """
        初始化主题管理器
        
        参数：
            settings_manager: 设置管理器实例，如果不提供则创建新实例
        """
        super().__init__()  # 调用QObject的初始化函数
        self.settings_manager = settings_manager or SettingsManager()
        
        # 主题颜色字典
        self.theme_colors = {}
        
        # 辅助色加深版本
        self.auxiliary_color_darker_2 = ""
        self.auxiliary_color_darker_5 = ""
        
        # 加载当前主题颜色
        self._load_theme_colors()
    
    def _load_theme_colors(self):
        """
        加载主题颜色设置
        """
        self.theme_colors = {
            "accent_color": self.settings_manager.get_setting("appearance.colors.accent_color", "#0A59F7"),
            "secondary_color": self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333"),
            "normal_color": self.settings_manager.get_setting("appearance.colors.normal_color", "#e0e0e0"),
            "auxiliary_color": self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5"),
            "base_color": self.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
        }
        
        # 计算辅助色加深2%和5%的颜色
        self.auxiliary_color_darker_2 = self._darken_color(self.theme_colors["auxiliary_color"], 2)
        self.auxiliary_color_darker_5 = self._darken_color(self.theme_colors["auxiliary_color"], 5)
    
    def _darken_color(self, color_hex, percent):
        """
        将颜色加深指定百分比，深色模式下则变浅
        
        参数：
            color_hex (str): 十六进制颜色值
            percent (int): 加深/变浅百分比（1-100）
            
        返回：
            str: 处理后的十六进制颜色值
        """
        # 获取当前主题模式
        current_theme = self.settings_manager.get_setting("appearance.theme", "default")
        is_dark_mode = (current_theme == "dark")
        
        # 将十六进制颜色转换为RGB
        color = QColor(color_hex)
        r = color.red()
        g = color.green()
        b = color.blue()
        
        # 计算处理后的RGB值
        if is_dark_mode:
            # 深色模式下变浅，使用(1 - 绝对值百分比)
            # 由于percent是正数，这里直接使用(1 + percent / 100)实现变浅效果
            factor = 1 + percent / 100
            r = min(255, int(r * factor))
            g = min(255, int(g * factor))
            b = min(255, int(b * factor))
        else:
            # 浅色模式下加深
            factor = 1 - percent / 100
            r = max(0, int(r * factor))
            g = max(0, int(g * factor))
            b = max(0, int(b * factor))
        
        # 转换回十六进制颜色
        return "#" + "{:02x}{:02x}{:02x}".format(r, g, b)
    
    def toggle_theme(self, is_dark):
        """
        切换主题模式（深色/浅色）
        
        参数：
            is_dark (bool): True为深色主题，False为浅色主题
            
        返回：
            dict: 更新后的主题颜色字典
        """
        # 更新主题模式设置
        theme_value = "dark" if is_dark else "default"
        self.settings_manager.set_setting("appearance.theme", theme_value)
        
        # 根据主题模式更新所有相关颜色
        if is_dark:  # 深色主题
            dark_colors = {
                "base_color": "#212121",          # 深色底层色
                "secondary_color": "#FFFFFF",      # 深色模式下文字颜色为白色
                "normal_color": "#8C8C8C",        # 深色模式下普通色
                "auxiliary_color": "#515151"      # 深色模式下辅助色
            }
        else:  # 浅色主题
            dark_colors = {
                "base_color": "#FFFFFF",          # 浅色底层色
                "secondary_color": "#3F3F3F",      # 浅色模式下文字颜色为黑色
                "normal_color": "#808080",        # 浅色模式下普通色
                "auxiliary_color": "#E6E6E6"      # 浅色模式下辅助色
            }
        
        # 更新当前设置中的所有颜色
        for color_key, color_value in dark_colors.items():
            self.settings_manager.set_setting(f"appearance.colors.{color_key}", color_value)
        
        # 重新加载主题颜色
        self._load_theme_colors()
        
        # 保存设置
        self.settings_manager.save_settings()
        
        # 发出信号
        self.theme_changed.emit(theme_value)
        self.colors_updated.emit(self.theme_colors)
        
        return self.theme_colors
    
    def get_theme_colors(self):
        """
        获取当前主题颜色字典
        
        返回：
            dict: 主题颜色字典
        """
        return self.theme_colors
    
    def get_darkened_auxiliary_colors(self):
        """
        获取辅助色的加深版本
        
        返回：
            tuple: (auxiliary_color_darker_2, auxiliary_color_darker_5)
        """
        return (self.auxiliary_color_darker_2, self.auxiliary_color_darker_5)
    
    def update_color(self, color_key, color_value):
        """
        更新单个颜色值
        
        参数：
            color_key (str): 颜色键名
            color_value (str): 颜色值（十六进制格式）
        """
        if color_key in self.theme_colors:
            self.theme_colors[color_key] = color_value
            self.settings_manager.set_setting(f"appearance.colors.{color_key}", color_value)
            
            # 如果更新的是辅助色，重新计算加深版本
            if color_key == "auxiliary_color":
                self.auxiliary_color_darker_2 = self._darken_color(color_value, 2)
                self.auxiliary_color_darker_5 = self._darken_color(color_value, 5)
            
            # 保存设置
            self.settings_manager.save_settings()
            
            # 发出信号
            self.colors_updated.emit(self.theme_colors)
    
    def is_dark_theme(self):
        """
        检查当前是否为深色主题
        
        返回：
            bool: True为深色主题，False为浅色主题
        """
        return self.settings_manager.get_setting("appearance.theme", "default") == "dark"
