#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试示例：演示CustomButton的文字模式和图标模式使用方法
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt
from freeassetfilter.widgets.custom_widgets import CustomButton
import os

class TestButtonWindow(QWidget):
    """
    测试按钮窗口，展示文字模式和图标模式的CustomButton
    """
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """
        初始化UI
        """
        # 设置窗口标题和大小
        self.setWindowTitle('CustomButton 测试示例')
        self.setGeometry(100, 100, 400, 300)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题标签
        title_label = QLabel('CustomButton 文字模式和图标模式测试')
        title_label.setStyleSheet('font-size: 18px; font-weight: bold;')
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 文字模式按钮区域
        text_mode_layout = QHBoxLayout()
        text_mode_layout.setSpacing(10)
        main_layout.addLayout(text_mode_layout)
        
        # 文字模式标签
        text_mode_label = QLabel('文字模式：')
        text_mode_layout.addWidget(text_mode_label)
        
        # 文字模式按钮 - 主要按钮
        primary_button = CustomButton('主要按钮', button_type='primary')
        text_mode_layout.addWidget(primary_button)
        
        # 文字模式按钮 - 次要按钮
        secondary_button = CustomButton('次要按钮', button_type='secondary')
        text_mode_layout.addWidget(secondary_button)
        
        # 文字模式按钮 - 普通按钮
        normal_button = CustomButton('普通按钮', button_type='normal')
        text_mode_layout.addWidget(normal_button)
        
        # 图标模式按钮区域
        icon_mode_layout = QHBoxLayout()
        icon_mode_layout.setSpacing(10)
        main_layout.addLayout(icon_mode_layout)
        
        # 图标模式标签
        icon_mode_label = QLabel('图标模式：')
        icon_mode_layout.addWidget(icon_mode_label)
        
        # 获取图标目录路径
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        
        # 图标模式按钮 - 示例1
        # 注意：请确保图标路径存在，否则将显示为文字
        # 这里使用项目中已有的SVG图标作为示例
        try:
            # 查找项目中存在的SVG图标文件
            svg_files = [f for f in os.listdir(icon_dir) if f.endswith('.svg')]
            if svg_files:
                # 使用第一个找到的SVG文件作为示例
                icon_path = os.path.join(icon_dir, svg_files[0])
                icon_button1 = CustomButton(icon_path, button_type='primary', display_mode='icon')
                icon_button1.setFixedSize(40, 40)  # 设置固定大小以更好地显示图标
                icon_mode_layout.addWidget(icon_button1)
            else:
                # 如果没有找到SVG文件，显示提示文字
                no_icon_label = QLabel('未找到SVG图标文件')
                no_icon_label.setStyleSheet('color: red;')
                icon_mode_layout.addWidget(no_icon_label)
        except Exception as e:
            error_label = QLabel(f'图标加载失败: {e}')
            error_label.setStyleSheet('color: red;')
            icon_mode_layout.addWidget(error_label)
        
        # 图标模式按钮 - 示例2：使用无效路径，测试异常处理
        invalid_icon_button = CustomButton('/invalid/path/to/icon.svg', button_type='secondary', display_mode='icon')
        invalid_icon_button.setFixedSize(40, 40)  # 设置固定大小
        icon_mode_layout.addWidget(invalid_icon_button)
        
        # 提示标签
        tip_label = QLabel('提示：图标模式下，按钮文本被视为SVG路径；无效路径时将显示为文字。')
        tip_label.setStyleSheet('font-size: 12px; color: #666666;')
        tip_label.setAlignment(Qt.AlignCenter)
        tip_label.setWordWrap(True)
        main_layout.addWidget(tip_label)

if __name__ == '__main__':
    # 创建应用程序
    app = QApplication(sys.argv)
    
    # 创建并显示测试窗口
    window = TestButtonWindow()
    window.show()
    
    # 运行应用程序
    sys.exit(app.exec_())