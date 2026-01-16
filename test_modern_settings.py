#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 现代化设置窗口测试脚本
用于测试现代化设置窗口的功能和交互
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from freeassetfilter.widgets.modern_settings_window import ModernSettingsWindow
from freeassetfilter.core.settings_manager import SettingsManager

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建设置管理器实例
    settings_manager = SettingsManager()
    
    # 设置全局字体
    from PyQt5.QtGui import QFont
    app.global_font = QFont("Microsoft YaHei", 10)
    app.dpi_scale_factor = 1.0
    app.settings_manager = settings_manager
    app.default_font_size = 10
    
    # 创建现代化设置窗口
    settings_window = ModernSettingsWindow()
    
    # 显示窗口
    settings_window.show()
    
    # 运行应用
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
