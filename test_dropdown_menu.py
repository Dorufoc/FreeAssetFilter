#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试CustomDropdownMenu组件
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu

class TestWindow(QWidget):
    """测试窗口"""
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("CustomDropdownMenu测试")
        self.setGeometry(100, 100, 400, 200)
        
        layout = QVBoxLayout(self)
        
        # 创建CustomDropdownMenu组件
        self.dropdown = CustomDropdownMenu(self, position="bottom")
        self.dropdown.set_fixed_width(150)
        
        # 添加测试项（带前缀）
        test_items = []
        for i in range(5):
            test_items.append({"text": f"测试: 选项{i}", "data": f"option{i}"})
        
        # 设置测试项
        self.dropdown.set_items(test_items)
        
        # 设置默认选中项
        self.dropdown.set_current_item({"text": "测试: 选项2", "data": "option2"})
        
        # 连接信号
        self.dropdown.itemClicked.connect(self.on_item_clicked)
        
        layout.addWidget(self.dropdown)
        
    def on_item_clicked(self, item_data):
        """处理选项点击事件"""
        print(f"选中的项: {item_data}")
        print(f"当前按钮文本: {self.dropdown.main_button.text()}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
