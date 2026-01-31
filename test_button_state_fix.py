#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试按钮点击后状态回归修复
验证点击释放后按钮状态正确回归
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt
from freeassetfilter.widgets.button_widgets import CustomButton

class TestWindow(QWidget):
    """测试窗口"""
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("按钮状态回归修复测试")
        self.setGeometry(100, 100, 500, 300)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # 说明标签
        desc_label = QLabel("测试：点击按钮后，鼠标移开，按钮状态应该回归默认\n"
                           "修复前：点击后按钮保持hover状态\n"
                           "修复后：点击后鼠标移开，按钮回归正常状态")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        
        # 主要按钮
        self.primary_btn = CustomButton("主要按钮", button_type="primary")
        self.primary_btn.clicked.connect(lambda: print("主要按钮被点击"))
        btn_layout.addWidget(self.primary_btn)
        
        # 普通按钮
        self.normal_btn = CustomButton("普通按钮", button_type="normal")
        self.normal_btn.clicked.connect(lambda: print("普通按钮被点击"))
        btn_layout.addWidget(self.normal_btn)
        
        # 次选按钮
        self.secondary_btn = CustomButton("次选按钮", button_type="secondary")
        self.secondary_btn.clicked.connect(lambda: print("次选按钮被点击"))
        btn_layout.addWidget(self.secondary_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 图标按钮测试
        icon_layout = QHBoxLayout()
        icon_label = QLabel("图标按钮:")
        icon_layout.addWidget(icon_label)
        
        # 图标按钮（使用文字模拟）
        self.icon_btn = CustomButton("图标", button_type="normal", display_mode="icon")
        self.icon_btn.clicked.connect(lambda: print("图标按钮被点击"))
        icon_layout.addWidget(self.icon_btn)
        
        icon_layout.addStretch()
        layout.addLayout(icon_layout)
        
        # 状态显示标签
        self.status_label = QLabel("操作提示：\n"
                                  "1. 鼠标悬停在按钮上观察hover状态\n"
                                  "2. 点击按钮并按住\n"
                                  "3. 释放鼠标（鼠标在按钮上）- 应保持hover状态\n"
                                  "4. 点击按钮并按住\n"
                                  "5. 移动鼠标离开按钮后释放 - 应回归正常状态")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        print("测试窗口初始化完成")
        print("请按照界面上的操作提示测试按钮状态")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
