#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试代码，用于验证ArchiveBrowser组件的修改
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton
from freeassetfilter.components.archive_browser import ArchiveBrowser

class TestWindow(QWidget):
    """测试窗口"""
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("ArchiveBrowser测试")
        self.setGeometry(100, 100, 800, 600)
        
        layout = QVBoxLayout(self)
        
        # 创建ArchiveBrowser组件
        self.browser = ArchiveBrowser()
        layout.addWidget(self.browser)
        
        # 添加测试按钮（可选）
        test_btn = QPushButton("测试")
        layout.addWidget(test_btn)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
