#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FileBlockCard 测试 - 卡片矩阵展示"""

import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QGridLayout,
                             QLabel, QFrame, QScrollArea)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from freeassetfilter.widgets.file_block_card import FileBlockCard


def create_file_info(name, is_folder=False, size=0, created=None):
    """创建测试文件信息"""
    if created is None:
        from datetime import datetime
        created = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "name": name,
        "is_folder": is_folder,
        "size": size,
        "created": created,
    }


class CardMatrixTest(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FileBlockCard 矩阵测试")
        self.resize(800, 600)
        self._setup_ui()
        self._create_card_matrix()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        self.grid_layout = QGridLayout(container)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)

        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)

        self.status_label = QLabel("右键点击卡片切换选中状态")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("Microsoft YaHei", 10))
        main_layout.addWidget(self.status_label)

    def _create_card_matrix(self):
        test_files = [
            create_file_info("视频文件", False, 1024 * 1024 * 50),
            create_file_info("图片文件", False, 2048),
            create_file_info("PDF文档", False, 5120),
            create_file_info("Excel表格", False, 1024),
            create_file_info("PPT演示", False, 2048),
            create_file_info("Word文档", False, 1024),
            create_file_info("音乐", False, 1024 * 1024 * 5),
            create_file_info("压缩包", False, 1024 * 1024 * 10),
            create_file_info("我的文件夹", True, 0),
            create_file_info("项目资料", True, 0),
            create_file_info("文档.docx", False, 2560),
            create_file_info("数据.xlsx", False, 1024),
            create_file_info("报告.pdf", False, 3072),
            create_file_info("备份.zip", False, 1024 * 1024 * 20),
            create_file_info("照片集", True, 0),
            create_file_info("工作文档", True, 0),
        ]

        row, col = 0, 0
        max_cols = 4
        for file_info in test_files:
            card = FileBlockCard(file_info, dpi_scale=1.0)
            card.clicked.connect(lambda f, name=file_info["name"]: self._update_status(f"左键点击: {name}"))
            card.right_clicked.connect(lambda f, name=file_info["name"]: self._update_status(f"选中状态切换: {name}"))
            card.double_clicked.connect(lambda f, name=file_info["name"]: self._update_status(f"双击: {name}"))

            self.grid_layout.addWidget(card, row, col)

            col += 1
            if col >= max_cols:
                col = 0
                row += 1

    def _update_status(self, text):
        self.status_label.setText(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CardMatrixTest()
    window.show()
    sys.exit(app.exec_())
