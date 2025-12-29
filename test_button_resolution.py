#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义按钮在不同分辨率下的显示问题
"""

import sys
import os
import warnings

# 忽略sipPyTypeDict相关的弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyQt5")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*sipPyTypeDict.*")

# 添加父目录到Python路径，确保包能被正确导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 导入自定义控件
from freeassetfilter.widgets.custom_widgets import CustomWindow, CustomButton


def test_custom_button_resolution():
    """
    测试自定义按钮在不同分辨率下的显示
    """
    app = QApplication(sys.argv)
    
    # 设置不同的DPI缩放因子进行测试
    test_scales = [1.0, 1.5, 2.0]
    
    for scale in test_scales:
        # 创建应用实例并设置DPI缩放因子
        app_instance = QApplication.instance()
        app_instance.dpi_scale_factor = scale
        app_instance.global_font = QFont("Microsoft YaHei", 10)
        app_instance.default_font_size = 14
        
        # 创建自定义窗口
        window = CustomWindow(f"Custom Button Resolution Test - DPI Scale: {scale}")
        window.setGeometry(100, 100, 600, 400)
        
        # 创建布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 添加标题
        title_label = QLabel(f"DPI Scale Factor: {scale}")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        main_layout.addWidget(title_label)
        
        # 创建不同类型的按钮进行测试
        button_layout = QVBoxLayout()
        button_layout.setSpacing(10)
        
        # 主要按钮
        primary_button = CustomButton("Primary Button", button_type="primary")
        button_layout.addWidget(primary_button)
        
        # 次要按钮
        secondary_button = CustomButton("Secondary Button", button_type="secondary")
        button_layout.addWidget(secondary_button)
        
        # 普通按钮
        normal_button = CustomButton("Normal Button", button_type="normal")
        button_layout.addWidget(normal_button)
        
        # 警告按钮
        warning_button = CustomButton("Warning Button", button_type="warning")
        button_layout.addWidget(warning_button)
        
        # 添加按钮布局到主布局
        main_layout.addLayout(button_layout)
        
        # 创建一个容器小部件
        container = QWidget()
        container.setLayout(main_layout)
        
        # 添加到自定义窗口
        window.add_widget(container)
        
        # 显示窗口
        window.show()
    
    # 运行应用
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_custom_button_resolution()
