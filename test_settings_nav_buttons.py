#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试设置窗口导航按钮状态切换修复
验证：选中第一个按钮，再选中第二个按钮，hover第一个按钮不会闪烁
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy
from PyQt5.QtCore import Qt
from freeassetfilter.widgets.button_widgets import CustomButton
from freeassetfilter.core.settings_manager import SettingsManager

class TestSettingsNavWindow(QWidget):
    """模拟设置窗口导航栏测试"""
    def __init__(self):
        super().__init__()
        self.navigation_buttons = []
        self.init_ui()

    def init_ui(self):
        """初始化UI - 模拟设置窗口左侧导航栏"""
        self.setWindowTitle("设置窗口导航按钮测试 - 修复闪烁问题")
        self.setGeometry(100, 100, 400, 400)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)

        # 说明标签
        desc_label = QLabel(
            "测试步骤：\n"
            "1. 点击'通用'按钮（变为primary样式）\n"
            "2. 点击'文件选择器'按钮（变为primary样式，通用变为normal）\n"
            "3. 将鼠标hover到'通用'按钮上\n"
            "4. 观察是否有闪烁（闪现强调样式后光速变回普通样式）\n\n"
            "修复前：会有明显闪烁\n"
            "修复后：平滑过渡到hover状态，无闪烁"
        )
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)

        # 导航栏容器（模拟设置窗口左侧导航）
        nav_container = QWidget()
        nav_container.setStyleSheet("background-color: #f5f5f5; border-radius: 8px;")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(10, 15, 10, 10)
        nav_layout.setSpacing(8)

        # 标题
        title_label = QLabel("设置")
        title_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #333;")
        nav_layout.addWidget(title_label)

        # 导航按钮
        nav_items = ["通用", "文件选择器", "文件暂存池", "播放器", "开发者设置"]

        for i, item_text in enumerate(nav_items):
            # 第一个按钮默认使用primary样式
            if i == 0:
                button = CustomButton(item_text, button_type="primary", display_mode="text", height=20)
            else:
                button = CustomButton(item_text, button_type="normal", display_mode="text", height=20)

            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda checked, idx=i: self._on_navigation_clicked(idx))
            self.navigation_buttons.append(button)
            nav_layout.addWidget(button)

        nav_layout.addStretch()
        main_layout.addWidget(nav_container)

        # 状态显示
        self.status_label = QLabel("当前选中: 通用")
        self.status_label.setStyleSheet("color: #666; padding: 10px;")
        main_layout.addWidget(self.status_label)

        main_layout.addStretch()

        print("测试窗口初始化完成")
        print("请按照界面上的测试步骤操作")

    def _on_navigation_clicked(self, index):
        """
        导航选项点击事件处理 - 模拟settings_window.py中的逻辑
        """
        nav_items = ["通用", "文件选择器", "文件暂存池", "播放器", "开发者设置"]

        print(f"点击了导航按钮: {nav_items[index]}")

        for i, button in enumerate(self.navigation_buttons):
            if i == index:
                button.button_type = "primary"
                button.update_style()
            else:
                button.button_type = "normal"
                button.update_style()

        self.status_label.setText(f"当前选中: {nav_items[index]}")

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 设置一些基础属性（模拟主应用）
    app.dpi_scale_factor = 1.0
    app.default_font_size = 18

    # 初始化settings_manager
    app.settings_manager = SettingsManager()

    window = TestSettingsNavWindow()
    window.show()
    sys.exit(app.exec_())
