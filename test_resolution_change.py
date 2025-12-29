#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试分辨率变化时按钮的显示情况
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 导入自定义控件
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.widgets.window_widgets import CustomWindow
from freeassetfilter.app.main import calculate_dpi_scale_factor


def test_resolution_change():
    """
    测试分辨率变化时按钮的显示情况
    """
    app = QApplication(sys.argv)
    
    # 设置全局字体
    global_font = QFont()
    global_font.setPointSize(14)
    app.global_font = global_font
    app.default_font_size = 14
    
    # 初始分辨率：2560x1600（DPI缩放因子为1.0）
    app.dpi_scale_factor = 1.0
    print(f"初始DPI缩放因子: {app.dpi_scale_factor}")
    
    # 创建自定义窗口
    window = CustomWindow("分辨率变化测试")
    
    # 创建按钮布局
    button_layout = QVBoxLayout()
    
    # 创建不同类型的按钮
    primary_btn = CustomButton("主要按钮", button_type="primary")
    secondary_btn = CustomButton("次要按钮", button_type="secondary")
    normal_btn = CustomButton("普通按钮", button_type="normal")
    warning_btn = CustomButton("警告按钮", button_type="warning")
    
    # 添加按钮到布局
    button_layout.addWidget(primary_btn)
    button_layout.addWidget(secondary_btn)
    button_layout.addWidget(normal_btn)
    button_layout.addWidget(warning_btn)
    
    # 将布局添加到窗口
    window.content_widget.setLayout(button_layout)
    
    # 显示窗口
    window.show()
    
    # 等待用户确认后切换分辨率
    input("按回车键切换到1920x1080分辨率...")
    
    # 切换到1920x1080分辨率（DPI缩放因子约为0.675）
    app.dpi_scale_factor = 0.675
    print(f"切换后DPI缩放因子: {app.dpi_scale_factor}")
    
    # 更新窗口和按钮的样式
    window.dpi_scale = app.dpi_scale_factor
    window.init_ui()
    
    # 重新设置按钮布局
    window.content_widget.setLayout(button_layout)
    
    # 显示窗口
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_resolution_change()
