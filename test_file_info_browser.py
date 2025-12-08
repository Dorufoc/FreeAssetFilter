#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件信息浏览组件
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow
from src.core.file_info_browser import FileInfoBrowser
from datetime import datetime

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 创建主窗口
    window = QMainWindow()
    window.setWindowTitle("文件信息浏览组件测试")
    window.setGeometry(100, 100, 800, 600)
    
    # 创建文件信息浏览组件
    file_info_browser = FileInfoBrowser()
    window.setCentralWidget(file_info_browser.get_ui())
    
    # 测试文件信息
    test_file = {
        "name": "test_file_info_browser.py",
        "path": __file__,
        "is_dir": False,
        "size": os.path.getsize(__file__),
        "modified": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "suffix": "py"
    }
    
    # 设置测试文件
    file_info_browser.set_file(test_file)
    
    window.show()
    sys.exit(app.exec_())