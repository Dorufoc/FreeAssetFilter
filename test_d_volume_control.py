#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DVolumeControl 组件测试脚本
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt
from freeassetfilter.widgets.D_volume_control import DVolumeControl


class DVolumeControlTest(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DVolumeControl 测试")
        self.resize(400, 300)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)

        title_label = QLabel("DVolumeControl 组件测试")
        title_label.setFont(self.global_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        test_button = QPushButton("测试按钮 - 点击显示音量控制")
        test_button.setFont(self.global_font)
        test_button.clicked.connect(self._toggle_volume_control)
        layout.addWidget(test_button)

        layout.addStretch(1)

        self.volume_control = DVolumeControl(self)
        self.volume_control.set_volume(50)

        self.volume_control.valueChanged.connect(self._on_volume_changed)
        self.volume_control.mutedChanged.connect(self._on_muted_changed)

        self.status_label = QLabel("当前音量: 50%")
        self.status_label.setFont(self.global_font)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

    def _toggle_volume_control(self):
        self.volume_control._toggle_volume_menu()

    def _on_volume_changed(self, volume):
        self.status_label.setText(f"当前音量: {volume}%")

    def _on_muted_changed(self, muted):
        status = "已静音" if muted else "未静音"
        current_text = self.status_label.text()
        self.status_label.setText(f"{current_text} ({status})")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    test_window = DVolumeControlTest()
    test_window.show()

    sys.exit(app.exec_())
