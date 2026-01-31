#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试排序下拉菜单修复
验证使用外部按钮时不显示内部按钮
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
from freeassetfilter.widgets.button_widgets import CustomButton

class TestWindow(QWidget):
    """测试窗口"""
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("排序下拉菜单修复测试")
        self.setGeometry(100, 100, 600, 300)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # 说明标签
        desc_label = QLabel("测试：排序方式下拉菜单（使用外部按钮，无内部按钮）")
        layout.addWidget(desc_label)
        
        # 第一行：模拟文件选择器中的排序按钮和下拉菜单
        row1_layout = QHBoxLayout()
        row1_layout.addWidget(QLabel("排序方式（外部按钮模式）:"))
        
        # 创建外部按钮（SVG图标按钮）
        self.sort_btn = CustomButton("排序", button_type="normal", display_mode="text")
        row1_layout.addWidget(self.sort_btn)
        
        # 创建下拉菜单（使用use_internal_button=False）
        self.sort_menu = CustomDropdownMenu(self, position="bottom", use_internal_button=False)
        self.sort_menu.set_fixed_width(100)
        
        sort_items = [
            {"text": "名称升序", "data": ("name", "asc")},
            {"text": "名称降序", "data": ("name", "desc")},
            {"text": "大小升序", "data": ("size", "asc")},
            {"text": "大小降序", "data": ("size", "desc")},
        ]
        self.sort_menu.set_items(sort_items, default_item=sort_items[0])
        self.sort_menu.set_target_button(self.sort_btn)
        self.sort_menu.itemClicked.connect(self.on_sort_item_clicked)
        
        # 连接外部按钮点击事件
        def show_sort_menu():
            self.sort_menu.set_target_button(self.sort_btn)
            self.sort_menu.show_menu()
        
        self.sort_btn.clicked.connect(show_sort_menu)
        
        row1_layout.addStretch()
        layout.addLayout(row1_layout)
        
        # 第二行：对比测试 - 使用内部按钮的模式（盘符选择器样式）
        row2_layout = QHBoxLayout()
        row2_layout.addWidget(QLabel("盘符选择（内部按钮模式）:"))
        
        # 创建带内部按钮的下拉菜单
        self.drive_menu = CustomDropdownMenu(self, position="bottom", use_internal_button=True)
        self.drive_menu.set_fixed_width(60)
        
        drive_items = [
            {"text": "C:", "data": "C:"},
            {"text": "D:", "data": "D:"},
            {"text": "E:", "data": "E:"},
        ]
        self.drive_menu.set_items(drive_items, default_item=drive_items[0])
        self.drive_menu.itemClicked.connect(self.on_drive_item_clicked)
        
        row2_layout.addWidget(self.drive_menu)
        row2_layout.addStretch()
        layout.addLayout(row2_layout)
        
        # 结果显示标签
        self.result_label = QLabel("点击下拉菜单查看结果")
        layout.addWidget(self.result_label)
        
        layout.addStretch()
        
        # 验证测试
        self.run_verification_tests()
    
    def on_sort_item_clicked(self, item_data):
        """处理排序选项点击"""
        self.result_label.setText(f"排序选择: {item_data}")
        print(f"排序选择: {item_data}")
    
    def on_drive_item_clicked(self, item_data):
        """处理盘符选项点击"""
        self.result_label.setText(f"盘符选择: {item_data}")
        print(f"盘符选择: {item_data}")
    
    def run_verification_tests(self):
        """运行验证测试"""
        print("=" * 50)
        print("开始验证测试...")
        print("=" * 50)
        
        # 测试1: 验证排序菜单没有内部按钮
        print("\n测试1: 验证排序菜单（use_internal_button=False）")
        if self.sort_menu.main_button is None:
            print("✓ 通过: 排序菜单没有内部按钮 (main_button is None)")
        else:
            print("✗ 失败: 排序菜单不应该有内部按钮")
        
        # 测试2: 验证盘符菜单有内部按钮
        print("\n测试2: 验证盘符菜单（use_internal_button=True）")
        if self.drive_menu.main_button is not None:
            print("✓ 通过: 盘符菜单有内部按钮")
        else:
            print("✗ 失败: 盘符菜单应该有内部按钮")
        
        # 测试3: 验证排序菜单的外部目标按钮设置
        print("\n测试3: 验证排序菜单的外部目标按钮")
        if self.sort_menu._external_target_button == self.sort_btn:
            print("✓ 通过: 排序菜单的外部目标按钮设置正确")
        else:
            print("✗ 失败: 排序菜单的外部目标按钮设置不正确")
        
        print("\n" + "=" * 50)
        print("验证测试完成")
        print("=" * 50)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
