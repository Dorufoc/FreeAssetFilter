#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试时间轴可见性修复
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from freeassetfilter.components.auto_timeline import AutoTimeline


class TestWindow(QMainWindow):
    """测试窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("时间轴可见性测试")
        self.setGeometry(100, 100, 1000, 600)
        
        # 创建主部件和布局
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        
        # 添加时间轴组件
        self.timeline = AutoTimeline()
        layout.addWidget(self.timeline)
        
        self.setCentralWidget(central_widget)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
