#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义选择列表组件
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入自定义选择列表组件
from freeassetfilter.widgets.custom_widgets import CustomSelectList

class TestWindow(QMainWindow):
    """
    测试窗口类
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自定义选择列表测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 创建主部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 创建测试标题
        title_label = QLabel("自定义选择列表组件测试")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        main_layout.addWidget(title_label)
        
        # 创建单选模式测试区域
        self.create_single_selection_test(main_layout)
        
        # 创建多选模式测试区域
        self.create_multiple_selection_test(main_layout)
        
        # 创建带图标测试区域
        self.create_with_icons_test(main_layout)
        
        # 显示窗口
        self.show()
    
    def create_single_selection_test(self, parent_layout):
        """
        创建单选模式测试区域
        """
        # 创建测试标题
        test_label = QLabel("1. 单选模式测试")
        test_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        parent_layout.addWidget(test_label)
        
        # 创建单选列表
        self.single_list = CustomSelectList(
            default_width=300, 
            default_height=200, 
            selection_mode="single"
        )
        
        # 添加测试数据
        test_items = ["选项1", "选项2", "选项3", "选项4", "选项5", "选项6", "选项7", "选项8"]
        self.single_list.add_items(test_items)
        
        # 连接信号
        self.single_list.itemClicked.connect(self.on_single_item_clicked)
        self.single_list.itemDoubleClicked.connect(self.on_single_item_double_clicked)
        self.single_list.selectionChanged.connect(self.on_single_selection_changed)
        
        parent_layout.addWidget(self.single_list)
        
        # 创建结果显示
        self.single_result_label = QLabel("点击选项查看结果")
        parent_layout.addWidget(self.single_result_label)
    
    def create_multiple_selection_test(self, parent_layout):
        """
        创建多选模式测试区域
        """
        # 创建测试标题
        test_label = QLabel("2. 多选模式测试")
        test_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        parent_layout.addWidget(test_label)
        
        # 创建多选列表
        self.multiple_list = CustomSelectList(
            default_width=300, 
            default_height=200, 
            selection_mode="multiple"
        )
        
        # 添加测试数据
        test_items = ["选项A", "选项B", "选项C", "选项D", "选项E", "选项F", "选项G", "选项H"]
        self.multiple_list.add_items(test_items)
        
        # 连接信号
        self.multiple_list.itemClicked.connect(self.on_multiple_item_clicked)
        self.multiple_list.itemDoubleClicked.connect(self.on_multiple_item_double_clicked)
        self.multiple_list.selectionChanged.connect(self.on_multiple_selection_changed)
        
        parent_layout.addWidget(self.multiple_list)
        
        # 创建结果显示
        self.multiple_result_label = QLabel("点击选项查看结果")
        parent_layout.addWidget(self.multiple_result_label)
        
        # 创建控制按钮
        button_layout = QVBoxLayout()
        button_layout.setSpacing(10)
        
        # 全选按钮
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self.on_select_all)
        button_layout.addWidget(select_all_btn)
        
        # 取消全选按钮
        clear_btn = QPushButton("取消全选")
        clear_btn.clicked.connect(self.on_clear_all)
        button_layout.addWidget(clear_btn)
        
        parent_layout.addLayout(button_layout)
    
    def create_with_icons_test(self, parent_layout):
        """
        创建带图标测试区域
        """
        # 创建测试标题
        test_label = QLabel("3. 带图标测试")
        test_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        parent_layout.addWidget(test_label)
        
        # 创建带图标列表
        self.icons_list = CustomSelectList(
            default_width=400, 
            default_height=200, 
            selection_mode="single"
        )
        
        # 测试数据：注意这里使用了不存在的图标路径，实际使用时需要替换为真实存在的图标路径
        test_items = [
            {"text": "无图标选项", "icon_path": ""},
            {"text": "PNG图标选项", "icon_path": "test_icon.png"},  # 请替换为真实存在的PNG图标路径
            {"text": "SVG图标选项", "icon_path": "test_icon.svg"},  # 请替换为真实存在的SVG图标路径
            {"text": "ICO图标选项", "icon_path": "test_icon.ico"},  # 请替换为真实存在的ICO图标路径
            {"text": "选项5", "icon_path": ""},
            {"text": "选项6", "icon_path": ""},
            {"text": "选项7", "icon_path": ""},
            {"text": "选项8", "icon_path": ""}
        ]
        
        self.icons_list.add_items(test_items)
        
        # 连接信号
        self.icons_list.itemClicked.connect(self.on_icons_item_clicked)
        
        parent_layout.addWidget(self.icons_list)
        
        # 创建结果显示
        self.icons_result_label = QLabel("点击选项查看结果")
        parent_layout.addWidget(self.icons_result_label)
    
    def on_single_item_clicked(self, index):
        """
        单选列表项点击事件处理
        """
        self.single_result_label.setText(f"单选列表项点击：索引 {index}")
    
    def on_single_item_double_clicked(self, index):
        """
        单选列表项双击事件处理
        """
        self.single_result_label.setText(f"单选列表项双击：索引 {index}")
    
    def on_single_selection_changed(self, indices):
        """
        单选列表选择变化事件处理
        """
        self.single_result_label.setText(f"单选列表选择变化：选中索引 {indices}")
    
    def on_multiple_item_clicked(self, index):
        """
        多选列表项点击事件处理
        """
        self.multiple_result_label.setText(f"多选列表项点击：索引 {index}")
    
    def on_multiple_item_double_clicked(self, index):
        """
        多选列表项双击事件处理
        """
        self.multiple_result_label.setText(f"多选列表项双击：索引 {index}")
    
    def on_multiple_selection_changed(self, indices):
        """
        多选列表选择变化事件处理
        """
        self.multiple_result_label.setText(f"多选列表选择变化：选中索引 {indices}")
    
    def on_icons_item_clicked(self, index):
        """
        带图标列表项点击事件处理
        """
        self.icons_result_label.setText(f"带图标列表项点击：索引 {index}")
    
    def on_select_all(self):
        """
        全选按钮点击事件处理
        """
        all_indices = list(range(len(self.multiple_list.items)))
        self.multiple_list.set_selected_indices(all_indices)
    
    def on_clear_all(self):
        """
        取消全选按钮点击事件处理
        """
        self.multiple_list.clear_selection()

if __name__ == "__main__":
    # 创建应用实例
    app = QApplication(sys.argv)
    
    # 创建测试窗口
    window = TestWindow()
    
    # 运行应用
    sys.exit(app.exec_())
