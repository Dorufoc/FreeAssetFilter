#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字体调整功能测试脚本
用于验证文本预览器的字体选择和字体大小调整功能
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath('.'))

from freeassetfilter.components.text_previewer import TextPreviewWidget


class TestFontAdjustment(QMainWindow):
    """
    字体调整功能测试窗口
    """
    def __init__(self):
        super().__init__()
        
        # 设置窗口属性
        self.setWindowTitle("字体调整功能测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 创建主布局
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        
        # 创建文本预览器组件
        self.text_previewer = TextPreviewWidget()
        
        # 添加到布局
        main_layout.addWidget(self.text_previewer)
        
        # 设置中心组件
        self.setCentralWidget(main_widget)
        
        # 加载测试文件
        self.load_test_file()
    
    def load_test_file(self):
        """
        加载测试文本文件
        """
        # 创建一个简单的测试文本文件
        test_content = """这是一个测试文件
用于验证字体调整功能是否正常工作。

Markdown格式测试：
- 列表项1
- 列表项2

**粗体文本** 和 *斜体文本*
"""
        
        # 保存到临时文件
        test_file_path = os.path.abspath("test_font_adjustment.txt")
        with open(test_file_path, "w", encoding="utf-8") as f:
            f.write(test_content)
        
        # 加载到预览器
        self.text_previewer.set_file(test_file_path)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 设置全局DPI缩放因子
    app.setAttribute(Qt.AA_EnableHighDpiScaling)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    # 设置全局字体
    font = app.font()
    app.global_font = font
    app.dpi_scale_factor = app.primaryScreen().logicalDotsPerInch() / 96.0
    app.default_font_size = 18
    
    window = TestFontAdjustment()
    window.show()
    
    sys.exit(app.exec_())
