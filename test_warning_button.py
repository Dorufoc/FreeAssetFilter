#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试警告按钮功能
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from freeassetfilter.widgets.custom_widgets import CustomButton

class TestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
    
    def initUI(self):
        self.setWindowTitle('警告按钮测试')
        self.setGeometry(100, 100, 400, 300)
        
        layout = QVBoxLayout()
        
        # 创建标题标签
        title = QLabel('警告按钮样式测试')
        layout.addWidget(title)
        
        # 创建不同类型的按钮
        primary_btn = CustomButton('主要按钮', button_type='primary')
        layout.addWidget(primary_btn)
        
        secondary_btn = CustomButton('次要按钮', button_type='secondary')
        layout.addWidget(secondary_btn)
        
        normal_btn = CustomButton('普通按钮', button_type='normal')
        layout.addWidget(normal_btn)
        
        # 测试新增的警告按钮
        warning_btn = CustomButton('警告按钮', button_type='warning')
        layout.addWidget(warning_btn)
        
        self.setLayout(layout)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
