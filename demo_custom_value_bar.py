#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义数值控制条组件演示
演示新创建的 CustomValueBar 组件的使用
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QHBoxLayout
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
        self.setWindowTitle("自定义数值控制条演示")
        self.setGeometry(100, 100, 600, 300)
        
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
        
        # 创建数值控制条实例
        self.value_bar = CustomValueBar()
        self.value_bar.setRange(0, 100)
        self.value_bar.setValue(50)
        # 连接值变化信号
        self.value_bar.valueChanged.connect(self.on_value_changed)
        main_layout.addWidget(self.value_bar)
        
        # 创建数值显示标签
        self.value_label = QLabel("当前数值: 50")
        self.value_label.setFont(QFont("Arial", 14))
        self.value_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.value_label)
        
        # 创建说明文本
        desc_label = QLabel("拖动滑块或点击进度条调整数值")
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setFont(QFont("Arial", 12))
        desc_label.setStyleSheet("color: #666666;")
        main_layout.addWidget(desc_label)
        
        # 创建一个带有默认样式的数值控制条实例
        self.value_bar_default = CustomValueBar()
        self.value_bar_default.setRange(0, 200)
        self.value_bar_default.setValue(100)
        self.value_bar_default.valueChanged.connect(self.on_value_changed_default)
        main_layout.addWidget(self.value_bar_default)
        
        self.value_label_default = QLabel("当前数值: 100")
        self.value_label_default.setFont(QFont("Arial", 14))
        self.value_label_default.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.value_label_default)
    
    def on_value_changed(self, value):
        """
        数值变化回调函数
        """
        self.value_label.setText(f"当前数值: {value}")
    
    def on_value_changed_default(self, value):
        """
        默认样式数值控制条的数值变化回调
        """
        self.value_label_default.setText(f"当前数值: {value}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    demo = ValueBarDemo()
    demo.show()
    sys.exit(app.exec_())
