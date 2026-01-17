#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试CustomFileHorizontalCard的单行文本格式功能
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.widgets.file_horizontal_card import CustomFileHorizontalCard

class TestWindow(QWidget):
    """测试窗口，用于测试CustomFileHorizontalCard的单行文本格式功能"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle('CustomFileHorizontalCard测试')
        self.setGeometry(100, 100, 600, 400)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        
        # 创建测试控件的容器
        self.test_container = QVBoxLayout()
        
        # 创建测试按钮
        button_layout = QHBoxLayout()
        
        # 普通模式按钮
        self.normal_btn = QPushButton('普通模式')
        self.normal_btn.clicked.connect(self.test_normal_mode)
        button_layout.addWidget(self.normal_btn)
        
        # 单行模式按钮
        self.single_line_btn = QPushButton('单行模式')
        self.single_line_btn.clicked.connect(self.test_single_line_mode)
        button_layout.addWidget(self.single_line_btn)
        
        # 切换模式按钮
        self.toggle_btn = QPushButton('切换模式')
        self.toggle_btn.clicked.connect(self.toggle_mode)
        button_layout.addWidget(self.toggle_btn)
        
        # 添加按钮布局到主布局
        main_layout.addLayout(button_layout)
        
        # 添加测试控件容器到主布局
        main_layout.addLayout(self.test_container)
        
        # 初始化测试卡片
        self.test_card = None
        self.is_single_line = False
        
        # 默认显示普通模式
        self.test_normal_mode()
    
    def test_normal_mode(self):
        """测试普通模式"""
        self._create_test_card(False)
        self.is_single_line = False
    
    def test_single_line_mode(self):
        """测试单行模式"""
        self._create_test_card(True)
        self.is_single_line = True
    
    def toggle_mode(self):
        """切换显示模式"""
        if self.is_single_line:
            self.test_normal_mode()
        else:
            self.test_single_line_mode()
    
    def _create_test_card(self, single_line_mode):
        """创建测试卡片
        
        参数：
            single_line_mode (bool): 是否使用单行文本格式
        """
        # 移除之前的测试卡片
        if self.test_card:
            self.test_card.deleteLater()
            self.test_card = None
        
        # 创建新的测试卡片
        self.test_card = CustomFileHorizontalCard(
            file_path=__file__,  # 使用当前文件作为测试文件
            single_line_mode=single_line_mode
        )
        
        # 添加测试卡片到容器
        self.test_container.addWidget(self.test_card)
        
        # 设置卡片样式以增强可读性
        self.test_card.setStyleSheet("""
            QWidget {
                margin: 10px;
            }
        """)
        
        # 连接信号用于调试
        self.test_card.clicked.connect(lambda path: print(f'点击了文件: {path}'))
        self.test_card.doubleClicked.connect(lambda path: print(f'双击了文件: {path}'))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    
    # 设置全局DPI缩放因子（如果需要）
    if hasattr(app, 'setAttribute'):
        app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
