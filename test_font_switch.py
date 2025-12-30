#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QFileDialog
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.text_previewer import TextPreviewWidget


class TestWindow(QMainWindow):
    """
    测试窗口，用于验证字体切换功能
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("字体切换测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 创建文本预览器
        self.text_previewer = TextPreviewWidget()
        main_layout.addWidget(self.text_previewer)
        
        # 创建打开文件按钮
        self.open_button = QPushButton("打开测试文件")
        self.open_button.clicked.connect(self.open_test_file)
        main_layout.addWidget(self.open_button)
        
        # 加载一个默认的测试文件（如果存在）
        self.load_default_test_file()
    
    def load_default_test_file(self):
        """
        加载默认的测试文件
        """
        test_file = os.path.join(os.path.dirname(__file__), "test_sample.txt")
        if os.path.exists(test_file):
            self.text_previewer.set_file(test_file)
        else:
            # 创建一个简单的测试文件
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("这是一个测试文件，用于测试字体切换功能。\n\n")
                f.write("Hello World! This is a test file for font switching.\n\n")
                f.write("中文和英文混合文本，测试不同字体的显示效果。\n")
                f.write("1234567890 数字测试。\n")
                f.write("Special characters: !@#$%^&*()_+{}[]|;:,.<>?\n")
            self.text_previewer.set_file(test_file)
    
    def open_test_file(self):
        """
        打开用户选择的测试文件
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开测试文件", "", 
            "文本文件 (*.txt *.md *.markdown *.mdown *.mkd *.py *.js *.html *.css *.json)")
        
        if file_path:
            self.text_previewer.set_file(file_path)


if __name__ == "__main__":
    # 设置DPI缩放，必须在创建QApplication之前设置
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    app = QApplication(sys.argv)
    
    # 设置全局字体
    font = app.font()
    font.setPointSize(12)
    app.setFont(font)
    
    window = TestWindow()
    window.show()
    
    sys.exit(app.exec_())
