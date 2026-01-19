#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

FileBlockCard 文件卡片组件测试
"""

import os
import sys

from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QScrollArea, QLabel, QHBoxLayout, QPushButton
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.widgets.file_block_card import FileBlockCard


def create_file_info(name, is_dir=False, size=1024, created="2025-01-15T10:30:00"):
    """创建测试用的文件信息字典"""
    suffix = "" if is_dir else os.path.splitext(name)[1].lower()
    return {
        "name": name,
        "path": os.path.join("C:\\test", name),
        "is_dir": is_dir,
        "size": size,
        "created": created,
        "suffix": suffix
    }


class TestMainWindow(QMainWindow):
    """测试主窗口"""
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("FileBlockCard 测试")
        self.setGeometry(100, 100, 500, 700)
        
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        
        app.setStyleSheet("""
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", Arial;
            }
        """)
        
        self.cards = []
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        main_layout.addWidget(scroll_area)
        
        scroll_content = QWidget()
        scroll_area.setWidget(scroll_content)
        
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setSpacing(10)
        
        self.test_file_types(content_layout)
        self.test_hover_state(content_layout)
        self.test_selection_state(content_layout)
        self.test_interactions(content_layout)
        self.create_control_buttons(content_layout)
    
    def test_file_types(self, layout):
        """测试不同文件类型的卡片"""
        title = self.create_title("1. 不同文件类型")
        layout.addWidget(title)
        
        test_files = [
            ("视频文件", create_file_info("test_video.mp4", False, 1024 * 1024 * 50)),
            ("图片文件", create_file_info("test_image.jpg", False, 2048)),
            ("PDF文档", create_file_info("document.pdf", False, 5120)),
            ("Excel表格", create_file_info("data.xlsx", False, 1024)),
            ("PPT演示", create_file_info("presentation.pptx", False, 2048)),
            ("Word文档", create_file_info("document.docx", False, 1024)),
            ("音频文件", create_file_info("music.mp3", False, 1024 * 1024 * 5)),
            ("压缩文件", create_file_info("archive.zip", False, 1024 * 1024 * 10)),
            ("文件夹", create_file_info("my_folder", True, 0)),
            ("未知类型", create_file_info("unknown.xyz", False, 256)),
        ]
        
        for label_text, file_info in test_files:
            label = QLabel(f"- {label_text}")
            label.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(label)
            
            card = FileBlockCard(file_info, dpi_scale=1.0)
            card.clicked.connect(lambda f, name=label_text: print(f"[点击] {name}"))
            card.right_clicked.connect(lambda f, name=label_text: print(f"[右键] {name}"))
            card.double_clicked.connect(lambda f, name=label_text: print(f"[双击] {name}"))
            
            layout.addWidget(card)
            self.cards.append(card)
    
    def test_hover_state(self, layout):
        """测试Hover状态"""
        title = self.create_title("2. Hover状态测试")
        layout.addWidget(title)
        
        info = create_file_info("hover_test.txt", False, 1024)
        card = FileBlockCard(info, dpi_scale=1.0)
        card.clicked.connect(lambda f: print(f"[点击] {f['name']}"))
        layout.addWidget(card)
        self.cards.append(card)
        
        hint = QLabel("提示：将鼠标悬停在上面的卡片上，观察边框颜色变化")
        hint.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(hint)
    
    def test_selection_state(self, layout):
        """测试选中状态"""
        title = self.create_title("3. 选中状态测试")
        layout.addWidget(title)
        
        test_cases = [
            ("未选中", False),
            ("已选中", True),
        ]
        
        for label_text, selected in test_cases:
            label = QLabel(f"- {label_text}")
            label.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(label)
            
            info = create_file_info(f"select_{label_text}.txt", False, 512)
            card = FileBlockCard(info, dpi_scale=1.0)
            card.set_selected(selected)
            layout.addWidget(card)
            self.cards.append(card)
    
    def test_interactions(self, layout):
        """测试交互信号"""
        title = self.create_title("4. 交互测试")
        layout.addWidget(title)
        
        info = create_file_info("interaction_test.mp4", False, 1024 * 1024)
        card = FileBlockCard(info, dpi_scale=1.0)
        
        def on_click(f):
            print(f"[信号] clicked - {f['name']}")
            self.status_label.setText(f"状态: 点击 {f['name']}")
        
        def on_right_click(f):
            print(f"[信号] right_clicked - {f['name']}")
            self.status_label.setText(f"状态: 右键 {f['name']}")
        
        def on_double_click(f):
            print(f"[信号] double_clicked - {f['name']}")
            self.status_label.setText(f"状态: 双击 {f['name']}")
        
        card.clicked.connect(on_click)
        card.right_clicked.connect(on_right_click)
        card.double_clicked.connect(on_double_click)
        
        layout.addWidget(card)
        self.cards.append(card)
        
        hint = QLabel("提示：左键点击、右键点击、左键双击卡片，观察控制台输出")
        hint.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(hint)
    
    def create_control_buttons(self, layout):
        """创建控制按钮"""
        title = self.create_title("5. 控制按钮")
        layout.addWidget(title)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self.on_select_all)
        button_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("取消全选")
        deselect_all_btn.clicked.connect(self.on_deselect_all)
        button_layout.addWidget(deselect_all_btn)
        
        toggle_btn = QPushButton("切换选中")
        toggle_btn.clicked.connect(self.on_toggle)
        button_layout.addWidget(toggle_btn)
        
        layout.addLayout(button_layout)
        
        self.status_label = QLabel("状态: 等待操作")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #4a7abc; padding: 8px; background: #f0f8ff; border-radius: 4px;")
        layout.addWidget(self.status_label)
    
    def on_select_all(self):
        """全选"""
        for card in self.cards:
            card.set_selected(True)
        self.status_label.setText("状态: 已全选")
    
    def on_deselect_all(self):
        """取消全选"""
        for card in self.cards:
            card.set_selected(False)
        self.status_label.setText("状态: 已取消全选")
    
    def on_toggle(self):
        """切换选中"""
        for card in self.cards:
            card.set_selected(not card.is_selected())
        self.status_label.setText("状态: 已切换选中状态")
    
    def create_title(self, text):
        """创建标题标签"""
        label = QLabel(text)
        font = QFont()
        font.setBold(True)
        font.setPointSize(12)
        label.setFont(font)
        return label


def main():
    """主函数"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    window = TestMainWindow()
    window.show()
    
    print("=" * 50)
    print("FileBlockCard 测试")
    print("=" * 50)
    print("功能测试:")
    print("  1. 不同文件类型显示（图标、名称、大小、时间）")
    print("  2. Hover状态效果（边框和背景变化）")
    print("  3. 选中状态切换")
    print("  4. 交互信号测试（点击、右键、双击）")
    print("=" * 50)
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
