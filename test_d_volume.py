#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 D_Volume 控件布局
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QScreen

from freeassetfilter.widgets.D_volume import D_Volume
from freeassetfilter.core.settings_manager import SettingsManager


class TestWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("D_Volume Test")
        self.setMinimumSize(400, 300)

        app = QApplication.instance()

        if hasattr(app, 'dpi_scale_factor'):
            self.dpi_scale = app.dpi_scale_factor
        else:
            screen = QApplication.primaryScreen()
            logical_dpi = screen.logicalDotsPerInch()
            physical_dpi = screen.physicalDotsPerInch()
            system_scale = physical_dpi / logical_dpi if logical_dpi > 0 else 1.0
            self.dpi_scale = system_scale * 1.5
            app.dpi_scale_factor = self.dpi_scale

        if hasattr(app, 'global_font'):
            self.setFont(app.global_font)
            self.global_font = app.global_font
        else:
            settings_manager = SettingsManager()
            font_size = settings_manager.get_setting("font.size", 10)
            font_style = settings_manager.get_setting("font.style", "Microsoft YaHei")
            self.global_font = QFont(font_style, font_size, QFont.Normal)
            self.setFont(self.global_font)
            app.global_font = self.global_font

        if hasattr(app, 'settings_manager'):
            self.settings_manager = app.settings_manager
        else:
            self.settings_manager = SettingsManager()
            app.settings_manager = self.settings_manager

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(20 * self.dpi_scale), int(20 * self.dpi_scale), int(20 * self.dpi_scale), int(20 * self.dpi_scale))
        layout.setAlignment(Qt.AlignTop)

        self.test_button = QPushButton("Click to Show Volume Menu")
        self.test_button.setFont(self.global_font)
        self.test_button.setMinimumSize(int(150 * self.dpi_scale), int(40 * self.dpi_scale))
        layout.addWidget(self.test_button, alignment=Qt.AlignLeft)

        self.volume_control = D_Volume(self)
        self.volume_control.set_target_widget(self.test_button)

        self.test_button.clicked.connect(self._on_button_clicked)

        layout.addSpacing(int(20 * self.dpi_scale))

        volume_label = QLabel("Volume Controls Test:")
        volume_label.setFont(self.global_font)
        layout.addWidget(volume_label)

    def _on_button_clicked(self):
        self.volume_control.toggle()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    app.setStyle("Windows")

    window = TestWindow()
    window.show()

    sys.exit(app.exec_())
