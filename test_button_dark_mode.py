#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义按钮在深色模式下的颜色处理
验证深色模式下颜色是否正确变亮而不是变暗
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.core.settings_manager import SettingsManager


class TestApp(QMainWindow):
    """测试应用程序"""
    
    def __init__(self):
        super().__init__()
        
        # 设置窗口标题和大小
        self.setWindowTitle("按钮深色模式颜色测试")
        self.resize(600, 400)
        
        # 创建设置管理器
        self.settings_manager = SettingsManager()
        
        # 创建UI
        self.init_ui()
        
        # 显示当前主题信息
        self.display_theme_info()
    
    def init_ui(self):
        """初始化UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # 添加信息标签
        self.info_label = QLabel()
        self.info_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_label)
        
        # 创建各种类型的按钮
        self.primary_button = CustomButton("主要按钮", self, button_type="primary")
        self.secondary_button = CustomButton("次要按钮", self, button_type="secondary")
        self.normal_button = CustomButton("普通按钮", self, button_type="normal")
        
        layout.addWidget(self.primary_button)
        layout.addWidget(self.secondary_button)
        layout.addWidget(self.normal_button)
        
        # 添加切换主题按钮
        self.toggle_button = CustomButton("切换主题", self, button_type="primary")
        self.toggle_button.clicked.connect(self.toggle_theme)
        layout.addWidget(self.toggle_button)
    
    def display_theme_info(self):
        """显示当前主题信息"""
        current_theme = self.settings_manager.get_setting("appearance.theme", "default")
        base_color = self.settings_manager.get_setting("appearance.colors.base_color", "#ffffff")
        accent_color = self.settings_manager.get_setting("appearance.colors.accent_color", "#007AFF")
        
        is_dark = (current_theme == "dark")
        
        info_text = f"""
        <h2>当前主题信息</h2>
        <p>主题模式: <b>{'深色模式' if is_dark else '浅色模式'}</b></p>
        <p>底层色 (base_color): {base_color}</p>
        <p>强调色 (accent_color): {accent_color}</p>
        <p>悬停颜色应该: <b>{'变亮' if is_dark else '变暗'}</b></p>
        """
        self.info_label.setText(info_text)
    
    def toggle_theme(self):
        """切换主题"""
        current_theme = self.settings_manager.get_setting("appearance.theme", "default")
        new_theme = "dark" if current_theme != "dark" else "default"
        
        # 更新主题设置
        self.settings_manager.set_setting("appearance.theme", new_theme)
        
        # 更新颜色配置
        if new_theme == "dark":
            self.settings_manager.set_setting("appearance.colors", {
                "accent_color": "#0A84FF",
                "secondary_color": "#FFFFFF",
                "normal_color": "#3A3A3C",
                "auxiliary_color": "#1C1C1E",
                "base_color": "#000000"
            })
        else:
            self.settings_manager.set_setting("appearance.colors", {
                "accent_color": "#007AFF",
                "secondary_color": "#333333",
                "normal_color": "#e0e0e0",
                "auxiliary_color": "#f1f3f5",
                "base_color": "#ffffff"
            })
        
        # 更新按钮样式
        self.primary_button.update_style()
        self.secondary_button.update_style()
        self.normal_button.update_style()
        
        # 更新信息显示
        self.display_theme_info()


def test_darken_color_function():
    """测试 darken_color 函数的逻辑"""
    print("=" * 60)
    print("测试 darken_color 函数逻辑")
    print("=" * 60)
    
    # 模拟 darken_color_qcolor 函数
    def darken_color_qcolor(color_hex, percentage, is_dark_mode):
        color = QColor(color_hex)
        
        if is_dark_mode:
            # 深色模式下变浅
            r = min(255, int(color.red() * (1 + percentage)))
            g = min(255, int(color.green() * (1 + percentage)))
            b = min(255, int(color.blue() * (1 + percentage)))
        else:
            # 浅色模式下加深
            r = max(0, int(color.red() * (1 - percentage)))
            g = max(0, int(color.green() * (1 - percentage)))
            b = max(0, int(color.blue() * (1 - percentage)))
        return QColor(r, g, b)
    
    # 测试颜色
    test_colors = ["#007AFF", "#333333", "#ffffff", "#000000"]
    percentage = 0.1
    
    for color in test_colors:
        light_result = darken_color_qcolor(color, percentage, False)
        dark_result = darken_color_qcolor(color, percentage, True)
        
        print(f"\n原始颜色: {color}")
        print(f"  浅色模式 (变暗): {light_result.name()}")
        print(f"  深色模式 (变亮): {dark_result.name()}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    # 先运行函数测试
    test_darken_color_function()
    
    # 然后运行GUI测试
    app = QApplication(sys.argv)
    
    # 设置全局字体
    from PyQt5.QtGui import QFont
    app.global_font = QFont("Microsoft YaHei", 10)
    app.default_font_size = 10
    app.dpi_scale_factor = 1.0
    
    # 创建设置管理器并附加到应用
    app.settings_manager = SettingsManager()
    
    window = TestApp()
    window.show()
    
    sys.exit(app.exec_())
