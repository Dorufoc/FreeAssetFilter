#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义按钮在不同分辨率下的可见性问题
"""

import sys
import os
import warnings

# 忽略弃用警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="PyQt5")

# 添加父目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 导入自定义控件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.window_widgets import CustomWindow

def test_button_visibility():
    """
    测试自定义按钮在不同分辨率下的可见性
    """
    app = QApplication(sys.argv)
    
    # 测试不同的DPI缩放因子
    test_scales = [1.0, 1.25, 1.5, 2.0]
    
    for scale in test_scales:
        # 设置DPI缩放因子
        app_instance = QApplication.instance()
        app_instance.dpi_scale_factor = scale
        app_instance.global_font = QFont("Microsoft YaHei", 10)
        app_instance.default_font_size = 14
        
        # 创建自定义窗口
        window = CustomWindow(f"Button Visibility Test - DPI Scale: {scale}")
        window.setGeometry(100 + int(scale * 100), 100 + int(scale * 100), 500, 400)
        
        # 创建布局
        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 添加标题
        title_label = QLabel(f"DPI Scale: {scale}")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        main_layout.addWidget(title_label)
        
        # 创建不同类型的按钮
        buttons = [
            ("Primary", "primary"),
            ("Secondary", "secondary"),
            ("Normal", "normal"),
            ("Warning", "warning")
        ]
        
        for button_text, button_type in buttons:
            button = CustomButton(button_text, button_type=button_type)
            # 添加点击事件处理，用于验证按钮是否可交互
            button.clicked.connect(lambda text=button_text: print(f"Clicked: {text}"))
            main_layout.addWidget(button)
        
        # 添加一个容器小部件
        container = QWidget()
        container.setLayout(main_layout)
        
        # 添加到自定义窗口
        window.add_widget(container)
        
        # 显示窗口
        window.show()
    
    # 运行应用
    sys.exit(app.exec_())

if __name__ == "__main__":
    test_button_visibility()