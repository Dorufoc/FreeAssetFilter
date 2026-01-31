#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 SVG 图标按钮的透明文本颜色
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.core.settings_manager import SettingsManager


class TestApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("图标按钮透明文本测试")
        self.resize(400, 300)
        
        self.settings_manager = SettingsManager()
        self.init_ui()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # 创建各种类型的图标按钮
        # 注意：这里使用 text 参数作为 SVG 路径，但实际测试时可能没有有效路径
        # 按钮会尝试加载 SVG，如果失败则显示文本
        
        primary_icon_btn = CustomButton(
            "icon/path.svg", 
            self, 
            button_type="primary", 
            display_mode="icon",
            tooltip_text="主要按钮"
        )
        
        normal_icon_btn = CustomButton(
            "icon/path.svg", 
            self, 
            button_type="normal", 
            display_mode="icon",
            tooltip_text="普通按钮"
        )
        
        secondary_icon_btn = CustomButton(
            "icon/path.svg", 
            self, 
            button_type="secondary", 
            display_mode="icon",
            tooltip_text="次要按钮"
        )
        
        warning_icon_btn = CustomButton(
            "icon/path.svg", 
            self, 
            button_type="warning", 
            display_mode="icon",
            tooltip_text="警告按钮"
        )
        
        layout.addWidget(primary_icon_btn)
        layout.addWidget(normal_icon_btn)
        layout.addWidget(secondary_icon_btn)
        layout.addWidget(warning_icon_btn)
        
        # 打印文本颜色信息
        print("\n按钮文本颜色信息:")
        print("=" * 60)
        for btn in [primary_icon_btn, normal_icon_btn, secondary_icon_btn, warning_icon_btn]:
            if hasattr(btn, '_style_colors'):
                text_color = btn._style_colors.get('normal_text')
                print(f"{btn.button_type}: {text_color.name(QColor.HexArgb) if text_color else 'N/A'}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    from PyQt5.QtGui import QFont
    app.global_font = QFont("Microsoft YaHei", 10)
    app.default_font_size = 10
    app.dpi_scale_factor = 1.0
    app.settings_manager = SettingsManager()
    
    window = TestApp()
    window.show()
    
    sys.exit(app.exec_())
