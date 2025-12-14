#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义输入框控件
"""

import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from freeassetfilter.widgets.custom_widgets import CustomInputBox


class TestWindow(QMainWindow):
    """
    测试窗口，用于展示和测试自定义输入框控件
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自定义输入框测试")
        self.setGeometry(100, 100, 400, 300)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 创建标签用于显示输入内容
        self.result_label = QLabel("输入内容: ")
        layout.addWidget(self.result_label)
        
        # 创建默认样式的自定义输入框
        self.input1 = CustomInputBox(
            placeholder_text="请输入文本...",
            width=350,
            height=40
        )
        self.input1.textChanged.connect(self.on_text_changed)
        self.input1.editingFinished.connect(self.on_editing_finished)
        layout.addWidget(self.input1)
        
        # 创建带有初始文本的自定义输入框
        self.input2 = CustomInputBox(
            placeholder_text="带有初始文本的输入框",
            initial_text="初始文本",
            width=350,
            height=40
        )
        self.input2.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.input2)
        
        # 创建自定义样式的输入框
        self.input3 = CustomInputBox(
            placeholder_text="自定义样式输入框",
            width=350,
            height=50,
            border_radius=15,
            border_color="#ff6b6b",
            background_color="#f8f9fa",
            text_color="#333333",
            placeholder_color="#6c757d",
            active_border_color="#ff5252",
            active_background_color="#ffffff"
        )
        self.input3.textChanged.connect(self.on_text_changed)
        layout.addWidget(self.input3)
        
        # 创建状态标签
        self.status_label = QLabel("状态: 等待输入")
        layout.addWidget(self.status_label)
    
    def on_text_changed(self, text):
        """
        文本变化事件处理
        """
        sender = self.sender()
        if sender == self.input1:
            self.result_label.setText(f"输入内容1: {text}")
        elif sender == self.input2:
            self.result_label.setText(f"输入内容2: {text}")
        elif sender == self.input3:
            self.result_label.setText(f"输入内容3: {text}")
    
    def on_editing_finished(self, text):
        """
        编辑完成事件处理
        """
        self.status_label.setText(f"状态: 编辑完成 - 最终内容: {text}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
