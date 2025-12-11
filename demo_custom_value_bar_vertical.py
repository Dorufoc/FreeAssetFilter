#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义数值控制条组件演示（支持竖向）
演示修改后的CustomValueBar组件，支持横向和竖向显示
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入自定义数值控制条组件
from src.components.video_player import CustomValueBar


class ValueBarDemo(QMainWindow):
    """
    数值控制条组件演示窗口
    """
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自定义数值控制条演示（支持竖向）")
        self.setGeometry(100, 100, 600, 400)
        
        # 创建中心窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 添加标题
        title_label = QLabel("自定义数值控制条组件演示")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 创建横向布局，用于放置横向和竖向的数值条
        orientation_layout = QHBoxLayout()
        orientation_layout.setSpacing(40)
        orientation_layout.setAlignment(Qt.AlignCenter)
        
        # 创建横向数值控制条
        self.value_bar_horizontal = CustomValueBar(orientation=CustomValueBar.Horizontal)
        self.value_bar_horizontal.setRange(0, 100)
        self.value_bar_horizontal.setValue(50)
        self.value_bar_horizontal.valueChanged.connect(self.on_horizontal_value_changed)
        
        # 横向数值条容器
        horizontal_container = QVBoxLayout()
        horizontal_container.setSpacing(10)
        horizontal_label = QLabel("横向数值条")
        horizontal_label.setAlignment(Qt.AlignCenter)
        horizontal_label.setFont(QFont("Arial", 12, QFont.Bold))
        horizontal_container.addWidget(horizontal_label)
        horizontal_container.addWidget(self.value_bar_horizontal)
        self.horizontal_value_label = QLabel("当前数值: 50")
        self.horizontal_value_label.setAlignment(Qt.AlignCenter)
        horizontal_container.addWidget(self.horizontal_value_label)
        
        # 创建竖向数值控制条
        self.value_bar_vertical = CustomValueBar(orientation=CustomValueBar.Vertical)
        self.value_bar_vertical.setRange(0, 100)
        self.value_bar_vertical.setValue(50)
        self.value_bar_vertical.valueChanged.connect(self.on_vertical_value_changed)
        
        # 竖向数值条容器
        vertical_container = QVBoxLayout()
        vertical_container.setSpacing(10)
        vertical_label = QLabel("竖向数值条")
        vertical_label.setAlignment(Qt.AlignCenter)
        vertical_label.setFont(QFont("Arial", 12, QFont.Bold))
        vertical_container.addWidget(vertical_label)
        vertical_container.addWidget(self.value_bar_vertical)
        self.vertical_value_label = QLabel("当前数值: 50")
        self.vertical_value_label.setAlignment(Qt.AlignCenter)
        vertical_container.addWidget(self.vertical_value_label)
        
        # 添加到横向布局
        orientation_layout.addLayout(horizontal_container)
        orientation_layout.addLayout(vertical_container)
        main_layout.addLayout(orientation_layout)
        
        # 创建方向切换按钮
        switch_layout = QHBoxLayout()
        switch_layout.setSpacing(20)
        switch_layout.setAlignment(Qt.AlignCenter)
        
        self.switch_horizontal_btn = QPushButton("切换为横向")
        self.switch_horizontal_btn.clicked.connect(self.switch_to_horizontal)
        switch_layout.addWidget(self.switch_horizontal_btn)
        
        self.switch_vertical_btn = QPushButton("切换为竖向")
        self.switch_vertical_btn.clicked.connect(self.switch_to_vertical)
        switch_layout.addWidget(self.switch_vertical_btn)
        
        main_layout.addLayout(switch_layout)
        
        # 创建说明文本
        desc_label = QLabel("拖动滑块或点击进度条调整数值")
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setFont(QFont("Arial", 12))
        desc_label.setStyleSheet("color: #666666;")
        main_layout.addWidget(desc_label)
    
    def on_horizontal_value_changed(self, value):
        """
        横向数值条变化回调函数
        """
        self.horizontal_value_label.setText(f"当前数值: {value}")
    
    def on_vertical_value_changed(self, value):
        """
        竖向数值条变化回调函数
        """
        self.vertical_value_label.setText(f"当前数值: {value}")
    
    def switch_to_horizontal(self):
        """
        将竖向数值条切换为横向
        """
        self.value_bar_vertical.setOrientation(CustomValueBar.Horizontal)
        self.switch_horizontal_btn.setEnabled(False)
        self.switch_vertical_btn.setEnabled(True)
    
    def switch_to_vertical(self):
        """
        将横向数值条切换为竖向
        """
        self.value_bar_vertical.setOrientation(CustomValueBar.Vertical)
        self.switch_horizontal_btn.setEnabled(True)
        self.switch_vertical_btn.setEnabled(False)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    demo = ValueBarDemo()
    demo.show()
    sys.exit(app.exec_())
