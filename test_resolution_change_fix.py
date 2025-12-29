#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义窗口控件中自定义按钮在分辨率变化时的可见性修复
"""

import sys
import os
# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QVBoxLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 导入自定义控件
from freeassetfilter.widgets.window_widgets import CustomWindow
from freeassetfilter.widgets.button_widgets import CustomButton


def test_resolution_change():
    """
    测试分辨率变化时按钮的显示情况
    """
    app = QApplication(sys.argv)
    
    # 设置全局字体和初始DPI缩放因子（模拟2560x1600分辨率）
    global_font = QFont()
    global_font.setPointSize(14)
    app.global_font = global_font
    app.default_font_size = 14
    app.dpi_scale_factor = 1.0  # 初始缩放因子（2560x1600）
    
    print(f"初始DPI缩放因子: {app.dpi_scale_factor}")
    
    # 创建自定义窗口
    window = CustomWindow("分辨率变化测试")
    
    # 创建按钮布局
    button_layout = QVBoxLayout()
    
    # 创建不同类型的按钮
    primary_button = CustomButton("主要按钮", button_type="primary")
    secondary_button = CustomButton("次要按钮", button_type="secondary")
    normal_button = CustomButton("普通按钮", button_type="normal")
    warning_button = CustomButton("警告按钮", button_type="warning")
    
    # 添加按钮到布局
    button_layout.addWidget(primary_button)
    button_layout.addWidget(secondary_button)
    button_layout.addWidget(normal_button)
    button_layout.addWidget(warning_button)
    
    # 设置窗口内容布局
    window.content_widget.setLayout(button_layout)
    
    # 显示窗口
    window.show()
    
    # 等待用户输入后切换分辨率（模拟1920x1080）
    input("按回车键切换到1920x1080分辨率...")
    
    # 模拟分辨率变化
    app.dpi_scale_factor = 0.675  # 1920x1080对应的高度缩放因子（1080/1600=0.675）
    
    print(f"切换后DPI缩放因子: {app.dpi_scale_factor}")
    
    # 测试修复：手动触发窗口的resizeEvent以更新UI
    # 首先获取当前窗口大小
    current_size = window.size()
    # 触发resizeEvent
    from PyQt5.QtGui import QResizeEvent
    resize_event = QResizeEvent(current_size, current_size)  # 大小不变，但仍会触发事件
    QApplication.sendEvent(window, resize_event)
    
    # 也可以尝试直接调整窗口大小来触发事件
    # window.resize(current_size.width() + 1, current_size.height() + 1)
    # window.resize(current_size)
    
    print("已触发窗口resizeEvent以更新UI")
    
    # 等待用户输入后结束测试
    input("按回车键结束测试...")
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    test_resolution_change()