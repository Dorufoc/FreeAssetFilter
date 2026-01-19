#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试FileBlockCard图标显示"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QGridLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.widgets.file_block_card import FileBlockCard


def create_file_info(name, is_dir=False, size=0, created="2025-01-01"):
    """创建测试用文件信息"""
    suffix = ""
    if not is_dir:
        parts = name.rsplit('.', 1)
        if len(parts) > 1:
            suffix = parts[1].lower()
    return {
        "name": name,
        "path": os.path.join("C:/test", name),
        "is_dir": is_dir,
        "size": size,
        "created": created,
        "suffix": suffix
    }


class IconTestWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileBlockCard 图标显示测试")
        self.resize(900, 600)
        self._setup_ui()
        self._create_test_cards()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        self.grid_layout = QGridLayout(container)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(15, 15, 15, 15)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

        self.status_label = QLabel("测试FileBlockCard图标显示")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        main_layout.addWidget(self.status_label)

    def _create_test_cards(self):
        test_files = [
            create_file_info("测试文件夹", True, 0, "2025-01-15"),
            create_file_info("视频文件.mp4", False, 1024 * 1024 * 50, "2025-01-10"),
            create_file_info("图片文件.jpg", False, 2048, "2025-01-12"),
            create_file_info("PDF文档.pdf", False, 5120, "2025-01-08"),
            create_file_info("表格.xlsx", False, 1024, "2025-01-05"),
            create_file_info("Word文档.docx", False, 2048, "2025-01-03"),
            create_file_info("演示文稿.pptx", False, 3072, "2025-01-01"),
            create_file_info("音乐.mp3", False, 512, "2025-01-14"),
            create_file_info("字体.ttf", False, 1024, "2025-01-13"),
            create_file_info("压缩文件.zip", False, 1024 * 10, "2025-01-11"),
            create_file_info("未知类型.xyz", False, 100, "2025-01-09"),
            create_file_info("文本文件.txt", False, 50, "2025-01-07"),
        ]

        row, col = 0, 0
        max_cols = 4
        for file_info in test_files:
            card = FileBlockCard(file_info, dpi_scale=1.0)
            card.clicked.connect(lambda f, name=file_info["name"]: self._update_status(f"左键点击: {name}"))
            card.right_clicked.connect(lambda f, name=file_info["name"]: self._update_status(f"右键点击: {name}"))
            card.double_clicked.connect(lambda f, name=file_info["name"]: self._update_status(f"双击: {name}"))

            self.grid_layout.addWidget(card, row, col)

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def _update_status(self, message):
        self.status_label.setText(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))

    window = IconTestWidget()
    window.show()

    sys.exit(app.exec_())
