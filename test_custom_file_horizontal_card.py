#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自定义文件横向卡片组件
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QScrollArea, QCheckBox
)
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.widgets import CustomFileHorizontalCard

class TestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.selected_cards = set()
    
    def init_ui(self):
        self.setWindowTitle('自定义文件横向卡片测试')
        self.setGeometry(100, 100, 800, 600)
        
        # 设置应用的DPI缩放因子
        app = QApplication.instance()
        app.dpi_scale_factor = 1.0
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        
        # 添加标题
        title_label = QLabel('自定义文件横向卡片组件测试')
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet('font-size: 18px; font-weight: bold; margin: 10px;')
        main_layout.addWidget(title_label)
        
        # 添加说明
        desc_label = QLabel('测试点击、双击和选中状态功能：')
        desc_label.setStyleSheet('margin: 10px;')
        main_layout.addWidget(desc_label)
        
        # 添加多选功能控制
        control_layout = QHBoxLayout()
        
        self.multiselect_checkbox = QCheckBox('开启多选功能')
        self.multiselect_checkbox.setChecked(True)
        self.multiselect_checkbox.stateChanged.connect(self.on_multiselect_toggled)
        control_layout.addWidget(self.multiselect_checkbox)
        
        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # 创建卡片容器
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(10)
        self.cards_layout.setContentsMargins(10, 10, 10, 10)
        
        # 添加测试卡片
        self.cards = []
        self.add_test_cards()
        
        scroll_area.setWidget(self.cards_container)
        main_layout.addWidget(scroll_area, 1)
        
        # 添加控制按钮
        control_layout = QHBoxLayout()
        
        select_all_btn = QPushButton('全选')
        select_all_btn.clicked.connect(self.select_all_cards)
        control_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton('取消全选')
        deselect_all_btn.clicked.connect(self.deselect_all_cards)
        control_layout.addWidget(deselect_all_btn)
        
        main_layout.addLayout(control_layout)
        
        # 添加状态标签
        self.status_label = QLabel('选中的文件：')
        self.status_label.setStyleSheet('margin: 10px;')
        main_layout.addWidget(self.status_label)
    
    def add_test_cards(self):
        # 获取当前脚本所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 获取一些测试文件
        test_files = []
        
        # 添加测试脚本本身
        test_files.append(__file__)
        
        # 添加其他测试文件（如果存在）
        for file_name in ['README.md', 'setup.py', 'requirements.txt']:
            file_path = os.path.join(current_dir, file_name)
            if os.path.exists(file_path):
                test_files.append(file_path)
        
        # 添加文件夹
        test_files.append(current_dir)
        
        # 创建卡片
        for file_path in test_files:
            # 创建卡片时传递enable_multiselect参数
            card = CustomFileHorizontalCard(
                file_path, 
                enable_multiselect=self.multiselect_checkbox.isChecked()
            )
            
            # 连接信号
            card.clicked.connect(self.on_card_clicked)
            card.doubleClicked.connect(self.on_card_double_clicked)
            card.selectionChanged.connect(self.on_card_selection_changed)
            
            self.cards_layout.addWidget(card)
            self.cards.append(card)
    
    def on_multiselect_toggled(self, state):
        """处理多选功能开关的状态变化"""
        enable_multiselect = state == Qt.Checked
        # 更新所有卡片的多选功能状态
        for card in self.cards:
            card.set_enable_multiselect(enable_multiselect)
        # 清空选中状态
        self.selected_cards.clear()
        self.update_status_label()
    
    def on_card_clicked(self, file_path):
        print(f"卡片被点击: {file_path}")
        # 点击切换选中状态
        for i in range(self.cards_layout.count()):
            card = self.cards_layout.itemAt(i).widget()
            if card.file_path == file_path:
                card.set_selected(not card.is_selected)
                break
    
    def on_card_double_clicked(self, file_path):
        print(f"卡片被双击: {file_path}")
        self.status_label.setText(f"双击了文件: {file_path}")
    
    def on_card_selection_changed(self, selected, file_path):
        if selected:
            self.selected_cards.add(file_path)
        else:
            self.selected_cards.discard(file_path)
        
        # 更新状态标签
        self.update_status_label()
    
    def update_status_label(self):
        if self.selected_cards:
            self.status_label.setText(f"选中的文件：{', '.join([os.path.basename(f) for f in self.selected_cards])}")
        else:
            self.status_label.setText("选中的文件：")
    
    def select_all_cards(self):
        for i in range(self.cards_layout.count()):
            card = self.cards_layout.itemAt(i).widget()
            card.set_selected(True)
    
    def deselect_all_cards(self):
        for i in range(self.cards_layout.count()):
            card = self.cards_layout.itemAt(i).widget()
            card.set_selected(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
