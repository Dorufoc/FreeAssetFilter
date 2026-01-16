#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试主题编辑器组件
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# 直接导入theme_editor模块
theme_editor_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'freeassetfilter', 'components', 'theme_editor.py'))

# 使用importlib导入模块
import importlib.util
spec = importlib.util.spec_from_file_location("theme_editor", theme_editor_path)
theme_editor = importlib.util.module_from_spec(spec)
sys.modules["theme_editor"] = theme_editor
spec.loader.exec_module(theme_editor)
ThemeEditor = theme_editor.ThemeEditor

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 创建原生窗口
    window = QMainWindow()
    window.setWindowTitle("主题编辑器测试")
    window.setGeometry(100, 100, 900, 700)
    
    # 创建主题编辑器
    theme_editor = ThemeEditor()
    
    # 设置主题编辑器为窗口的主控件
    window.setCentralWidget(theme_editor)
    
    window.show()
    sys.exit(app.exec_())