#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修改后的自定义输入框的自适应宽度功能
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from freeassetfilter.widgets.custom_widgets import CustomInputBox

class TestWindow(QMainWindow):
    """
    测试窗口，用于验证自定义输入框的自适应宽度功能
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自定义输入框自适应宽度测试")
        self.setGeometry(100, 100, 600, 400)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建垂直布局
        main_layout = QVBoxLayout(central_widget)
        
        # 测试1：水平布局中的自适应宽度
        test1_label = QLabel("测试1：水平布局中的自适应宽度")
        main_layout.addWidget(test1_label)
        
        h_layout = QHBoxLayout()
        h_layout.setSpacing(10)
        
        # 创建自适应宽度的自定义输入框
        self.input1 = CustomInputBox(
            placeholder_text="自适应宽度的输入框",
            height=40
        )
        h_layout.addWidget(self.input1, 1)  # 添加伸展因子，使其自适应宽度
        
        # 添加一个按钮，与输入框并排
        btn1 = QPushButton("确定")
        h_layout.addWidget(btn1)
        
        main_layout.addLayout(h_layout)
        
        # 测试2：默认宽度的自定义输入框
        test2_label = QLabel("测试2：默认宽度的自定义输入框")
        main_layout.addWidget(test2_label)
        
        self.input2 = CustomInputBox(
            placeholder_text="默认宽度的输入框",
            height=40
        )
        main_layout.addWidget(self.input2)
        
        # 测试3：固定宽度的自定义输入框
        test3_label = QLabel("测试3：固定宽度的自定义输入框")
        main_layout.addWidget(test3_label)
        
        self.input3 = CustomInputBox(
            placeholder_text="固定宽度的输入框",
            width=300,
            height=40
        )
        main_layout.addWidget(self.input3)
        
        # 测试4：多行布局中的自适应宽度
        test4_label = QLabel("测试4：多行布局中的自适应宽度")
        main_layout.addWidget(test4_label)
        
        for i in range(3):
            h_layout2 = QHBoxLayout()
            input_box = CustomInputBox(
                placeholder_text=f"自适应宽度输入框 {i+1}",
                height=35
            )
            h_layout2.addWidget(input_box, 1)
            btn = QPushButton(f"按钮 {i+1}")
            h_layout2.addWidget(btn)
            main_layout.addLayout(h_layout2)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
