#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试现代化设置窗口
"""

import sys
import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入现代化设置窗口
from freeassetfilter.widgets.modern_settings_window import ModernSettingsWindow

# 设置DPI支持
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

if __name__ == "__main__":
    # 创建应用实例
    app = QApplication(sys.argv)
    
    # 设置DPI缩放因子
    app.dpi_scale_factor = app.primaryScreen().logicalDotsPerInch() / 96.0
    
    # 测试现代化设置窗口
    settings_window = ModernSettingsWindow()
    settings_window.show()
    
    # 启动应用事件循环
    sys.exit(app.exec_())