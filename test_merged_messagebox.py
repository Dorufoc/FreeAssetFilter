#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试合并后的 CustomMessageBox 功能
"""

import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.append('.')

from freeassetfilter.widgets.custom_widgets import CustomMessageBox

class TestWindow(QMainWindow):
    """
    测试窗口类
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CustomMessageBox 测试")
        self.setGeometry(100, 100, 800, 600)
        
        # 创建主部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)
        
        # 创建测试按钮
        test_button = QPushButton("测试带列表的提示窗", self)
        test_button.clicked.connect(self.test_message_box_with_list)
        main_layout.addWidget(test_button)
        
        # 显示窗口
        self.show()
    
    def test_message_box_with_list(self):
        """
        测试带列表的提示窗
        """
        # 创建自定义提示窗
        msg_box = CustomMessageBox(self)
        msg_box.set_title("选择列表测试")
        msg_box.set_text("请从以下选项中选择一个：")
        
        # 添加列表项
        list_items = [
            "选项 1",
            "选项 2", 
            "选项 3",
            "选项 4",
            "选项 5"
        ]
        msg_box.set_list(list_items, selection_mode="single")
        
        # 添加按钮
        msg_box.set_buttons(["确定", "取消"], Qt.Horizontal, ["primary", "normal"])
        
        # 连接按钮点击信号
        msg_box.buttonClicked.connect(lambda idx: self._on_button_clicked(idx, msg_box))
        
        # 显示提示窗
        msg_box.exec_()
    
    def _on_button_clicked(self, button_index, msg_box):
        """
        按钮点击事件处理
        """
        if button_index == 0:  # 确定按钮
            selected_indices = msg_box.get_selected_list_items()
            print(f"选中的索引: {selected_indices}")
            for idx in selected_indices:
                print(f"选中的选项: {msg_box._list_items[idx]}")
        msg_box.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_window = TestWindow()
    sys.exit(app.exec_())