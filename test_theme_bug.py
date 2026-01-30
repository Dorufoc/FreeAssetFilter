#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：重现主题设置窗口空白问题
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QDialog, QVBoxLayout, QPushButton

# 在创建QApplication之前设置Qt属性
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

# 创建应用程序实例
app = QApplication(sys.argv)

# 设置全局属性
app.dpi_scale_factor = 1.0
app.default_font_size = 9

# 导入设置管理器
from freeassetfilter.core.settings_manager import SettingsManager
settings_manager = SettingsManager()
app.settings_manager = settings_manager

# 导入主题编辑器
from freeassetfilter.components.theme_editor import ThemeEditor
from freeassetfilter.components.settings_window import ModernSettingsWindow

# 创建设置窗口
print("创建设置窗口...")
settings_window = ModernSettingsWindow(parent=None)
settings_window.show()

# 模拟点击"自定义主题颜色"按钮
print("点击自定义主题颜色按钮...")

# 获取外观设置中的主题颜色按钮
appearance_tab = settings_window.content_area
print(f"内容区域类型: {type(appearance_tab)}")

# 直接调用打开主题颜色设置的方法
settings_window._open_theme_color_settings()

# 保持事件循环运行一段时间以便观察
import time
print("等待5秒观察主题设置窗口...")
time.sleep(5)

print("测试完成")
