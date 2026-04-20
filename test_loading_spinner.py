#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LoadingSpinner 动画效果测试窗口
用于展示加载状态转圈动画的各种功能
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QGridLayout
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from freeassetfilter.widgets import LoadingSpinner
from freeassetfilter.utils.app_logger import info, debug, warning, error


class LoadingSpinnerDemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LoadingSpinner 动画效果演示")
        self.setMinimumSize(600, 500)
        
        self._init_ui()
        self._setup_timers()
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(30, 30, 30, 30)
        
        title = QLabel("LoadingSpinner 动画效果演示")
        title.setFont(QFont("Microsoft YaHei UI", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        basic_group = QGroupBox("基本功能")
        basic_layout = QVBoxLayout()
        
        self.spinner_basic = LoadingSpinner(icon_size=64, dpi_scale=1.0)
        self.btn_start_basic = QPushButton("开始动画")
        self.btn_stop_basic = QPushButton("停止动画")
        
        btn_layout_basic = QHBoxLayout()
        btn_layout_basic.addWidget(self.btn_start_basic)
        btn_layout_basic.addWidget(self.btn_stop_basic)
        
        basic_layout.addWidget(self.spinner_basic, 0, Qt.AlignCenter)
        basic_layout.addLayout(btn_layout_basic)
        basic_group.setLayout(basic_layout)
        main_layout.addWidget(basic_group)
        
        size_group = QGroupBox("不同尺寸")
        size_layout = QHBoxLayout()
        
        self.spinner_small = LoadingSpinner(icon_size=32, dpi_scale=1.0)
        self.spinner_medium = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        self.spinner_large = LoadingSpinner(icon_size=80, dpi_scale=1.0)
        
        size_layout.addWidget(self.spinner_small)
        size_layout.addWidget(self.spinner_medium)
        size_layout.addWidget(self.spinner_large)
        size_layout.addStretch()
        
        size_group.setLayout(size_layout)
        main_layout.addWidget(size_group)
        
        multi_group = QGroupBox("多个动画同步")
        multi_layout = QHBoxLayout()
        
        self.spinner1 = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        self.spinner2 = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        self.spinner3 = LoadingSpinner(icon_size=48, dpi_scale=1.0)
        
        multi_layout.addWidget(self.spinner1)
        multi_layout.addWidget(self.spinner2)
        multi_layout.addWidget(self.spinner3)
        multi_layout.addStretch()
        
        multi_group.setLayout(multi_layout)
        main_layout.addWidget(multi_group)
        
        control_group = QGroupBox("统一控制")
        control_layout = QHBoxLayout()
        
        self.btn_start_all = QPushButton("全部开始")
        self.btn_stop_all = QPushButton("全部停止")
        
        control_layout.addWidget(self.btn_start_all)
        control_layout.addWidget(self.btn_stop_all)
        control_layout.addStretch()
        
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        main_layout.addStretch()
        
        self.btn_start_basic.clicked.connect(self.spinner_basic.start)
        self.btn_stop_basic.clicked.connect(self.spinner_basic.stop)
        self.btn_start_all.clicked.connect(self._start_all)
        self.btn_stop_all.clicked.connect(self._stop_all)
    
    def _setup_timers(self):
        self._rotation_check_timer = QTimer(self)
        self._rotation_check_timer.timeout.connect(self._update_rotation_display)
        self._rotation_check_timer.start(100)
    
    def _update_rotation_display(self):
        if hasattr(self, 'spinner_basic') and self.spinner_basic._is_running:
            rotation = self.spinner_basic._rotation_value
            scale = self.spinner_basic._scale_value
    
    def _start_all(self):
        self.spinner_basic.start()
        self.spinner_small.start()
        self.spinner_medium.start()
        self.spinner_large.start()
        self.spinner1.start()
        self.spinner2.start()
        self.spinner3.start()
    
    def _stop_all(self):
        self.spinner_basic.stop()
        self.spinner_small.stop()
        self.spinner_medium.stop()
        self.spinner_large.stop()
        self.spinner1.stop()
        self.spinner2.stop()
        self.spinner3.stop()
    
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(100, self._start_all)
    
    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    
    demo = LoadingSpinnerDemo()
    demo.show()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
