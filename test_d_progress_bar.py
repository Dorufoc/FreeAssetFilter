#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D_ProgressBar 控件测试脚本
测试 D_ProgressBar 自定义进度条控件的所有功能
"""

import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QSpinBox, QCheckBox,
    QFrame, QScrollArea, QGridLayout
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from freeassetfilter.widgets import D_ProgressBar


class D_ProgressBarTestWindow(QMainWindow):
    """D_ProgressBar 测试窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("D_ProgressBar 控件测试")
        self.setMinimumSize(800, 600)
        self._setup_ui()
        self._setup_connections()
        self._start_auto_test()

    def _setup_ui(self):
        """设置UI界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel("D_ProgressBar 功能测试")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        main_layout.addWidget(scroll_area)

        content_widget = QWidget()
        scroll_area.setWidget(content_widget)
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(20)

        content_layout.addWidget(self._create_basic_demo())
        content_layout.addWidget(self._create_orientation_demo())
        content_layout.addWidget(self._create_interactive_demo())
        content_layout.addWidget(self._create_color_demo())
        content_layout.addWidget(self._create_signal_demo())

        content_layout.addStretch()

    def _create_basic_demo(self):
        """创建基础演示区域"""
        group = QGroupBox("D_ProgressBar - 基础功能")
        layout = QVBoxLayout()
        layout.setSpacing(15)

        layout.addWidget(QLabel("横向可交互进度条（支持点击跳转和拖拽）："))

        self.d_progress_bar_1 = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.d_progress_bar_1.setRange(0, 1000)
        self.d_progress_bar_1.setValue(500)
        layout.addWidget(self.d_progress_bar_1)

        self.basic_value_label = QLabel("当前值: 500")
        self.basic_value_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.basic_value_label)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("设置值:"))
        self.basic_spinner = QSpinBox()
        self.basic_spinner.setRange(0, 1000)
        self.basic_spinner.setValue(500)
        control_layout.addWidget(self.basic_spinner)
        control_layout.addStretch()
        layout.addLayout(control_layout)

        group.setLayout(layout)
        return group

    def _create_orientation_demo(self):
        """创建方向演示区域"""
        group = QGroupBox("方向对比演示")
        layout = QGridLayout()
        layout.setSpacing(15)

        layout.addWidget(QLabel("横向进度条:"), 0, 0)
        self.horizontal_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.horizontal_bar.setRange(0, 100)
        self.horizontal_bar.setValue(40)
        layout.addWidget(self.horizontal_bar, 0, 1)

        layout.addWidget(QLabel("纵向进度条:"), 1, 0)
        self.vertical_bar = D_ProgressBar(orientation=D_ProgressBar.Vertical, is_interactive=True)
        self.vertical_bar.setRange(0, 100)
        self.vertical_bar.setValue(60)
        layout.addWidget(self.vertical_bar, 1, 1)

        group.setLayout(layout)
        return group

    def _create_interactive_demo(self):
        """创建交互模式演示区域"""
        group = QGroupBox("交互模式演示")
        layout = QVBoxLayout()
        layout.setSpacing(15)

        layout.addWidget(QLabel("可交互进度条（可点击和拖拽）："))

        self.interactive_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.interactive_bar.setRange(0, 100)
        self.interactive_bar.setValue(70)
        layout.addWidget(self.interactive_bar)

        self.interactive_label = QLabel("当前值: 70")
        self.interactive_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.interactive_label)

        layout.addWidget(QLabel("不可交互进度条（只显示进度）："))

        self.non_interactive_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=False)
        self.non_interactive_bar.setRange(0, 100)
        self.non_interactive_bar.setValue(30)
        layout.addWidget(self.non_interactive_bar)

        self.non_interactive_label = QLabel("当前值: 30")
        self.non_interactive_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.non_interactive_label)

        self.interactive_checkbox = QCheckBox("启用交互模式")
        self.interactive_checkbox.setChecked(True)
        layout.addWidget(self.interactive_checkbox)

        group.setLayout(layout)
        return group

    def _create_color_demo(self):
        """创建颜色自定义演示区域"""
        group = QGroupBox("颜色自定义演示")
        layout = QVBoxLayout()
        layout.setSpacing(15)

        layout.addWidget(QLabel("自定义颜色进度条："))

        self.color_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.color_bar.setRange(0, 100)
        self.color_bar.setValue(50)
        layout.addWidget(self.color_bar)

        color_control_layout = QHBoxLayout()
        color_control_layout.addWidget(QLabel("轨道底板色:"))
        self.track_color_button = QPushButton("设置轨道色")
        self.track_color_button.clicked.connect(self._on_track_color_clicked)
        color_control_layout.addWidget(self.track_color_button)

        color_control_layout.addWidget(QLabel("进度色:"))
        self.progress_color_button = QPushButton("设置进度色")
        self.progress_color_button.clicked.connect(self._on_progress_color_clicked)
        color_control_layout.addWidget(self.progress_color_button)

        color_control_layout.addStretch()
        layout.addLayout(color_control_layout)

        layout.addWidget(QLabel("轨道背景渐变："))

        self.bg_gradient_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.bg_gradient_bar.setRange(0, 100)
        self.bg_gradient_bar.setValue(60)
        self.bg_gradient_bar.set_track_color(QColor("#2d2d2d"))
        self.bg_gradient_bar.set_gradient_mode(True)
        self.bg_gradient_bar.set_bg_gradient_colors([
            QColor("#FF6B6B"),
            QColor("#4ECDC4"),
            QColor("#45B7D1")
        ])
        layout.addWidget(self.bg_gradient_bar)

        layout.addWidget(QLabel("进度条渐变："))

        self.progress_gradient_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.progress_gradient_bar.setRange(0, 100)
        self.progress_gradient_bar.setValue(70)
        self.progress_gradient_bar.set_progress_gradient_mode(True)
        self.progress_gradient_bar.set_progress_gradient_colors([
            QColor("#FF9A9E"),
            QColor("#FECFEF"),
            QColor("#F6416C")
        ])
        layout.addWidget(self.progress_gradient_bar)

        layout.addWidget(QLabel("双向渐变（深色轨道 + 渐变进度）："))

        self.dual_gradient_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.dual_gradient_bar.setRange(0, 100)
        self.dual_gradient_bar.setValue(80)
        self.dual_gradient_bar.set_track_color(QColor("#1a1a2e"))
        self.dual_gradient_bar.set_gradient_mode(True)
        self.dual_gradient_bar.set_bg_gradient_colors([
            QColor("#16213e"),
            QColor("#0f3460")
        ])
        self.dual_gradient_bar.set_progress_gradient_mode(True)
        self.dual_gradient_bar.set_progress_gradient_colors([
            QColor("#667eea"),
            QColor("#764ba2")
        ])
        layout.addWidget(self.dual_gradient_bar)

        layout.addWidget(QLabel("滑块边框颜色演示："))

        self.border_color_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.border_color_bar.setRange(0, 100)
        self.border_color_bar.setValue(65)
        self.border_color_bar.set_track_color(QColor("#1a1a2e"))
        self.border_color_bar.set_progress_color(QColor("#e94560"))
        self.border_color_bar.set_handle_border_color(QColor("#FFFFFF"))
        layout.addWidget(self.border_color_bar)

        border_control_layout = QHBoxLayout()
        border_control_layout.addWidget(QLabel("边框颜色:"))
        self.border_color_button = QPushButton("设置边框色")
        self.border_color_button.clicked.connect(self._on_border_color_clicked)
        border_control_layout.addWidget(self.border_color_button)

        border_control_layout.addWidget(QLabel("边框宽度:"))
        self.border_width_spinner = QSpinBox()
        self.border_width_spinner.setRange(1, 10)
        self.border_width_spinner.setValue(2)
        self.border_width_spinner.valueChanged.connect(self._on_border_width_changed)
        border_control_layout.addWidget(self.border_width_spinner)

        border_control_layout.addStretch()
        layout.addLayout(border_control_layout)

        layout.addWidget(QLabel("金色滑块 + 黑色边框："))

        self.gold_handle_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.gold_handle_bar.setRange(0, 100)
        self.gold_handle_bar.setValue(85)
        self.gold_handle_bar.set_track_color(QColor("#2d2d2d"))
        self.gold_handle_bar.set_progress_color(QColor("#FFD700"))
        self.gold_handle_bar.set_handle_colors(
            QColor("#FFD700"),
            QColor("#FFEC8B"),
            QColor("#DAA520")
        )
        self.gold_handle_bar.set_handle_border_color(QColor("#000000"))
        self.gold_handle_bar.set_handle_border_width(3)
        layout.addWidget(self.gold_handle_bar)

        group.setLayout(layout)
        return group

    def _create_signal_demo(self):
        """创建信号机制演示区域"""
        group = QGroupBox("信号机制演示")
        layout = QVBoxLayout()
        layout.setSpacing(15)

        layout.addWidget(QLabel("观察信号触发情况："))

        self.signal_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal, is_interactive=True)
        self.signal_bar.setRange(0, 100)
        self.signal_bar.setValue(25)
        layout.addWidget(self.signal_bar)

        self.signal_log = QLabel("信号日志: 等待交互...")
        self.signal_log.setAlignment(Qt.AlignCenter)
        self.signal_log.setStyleSheet("background-color: #f0f0f0; padding: 10px; border: 1px solid #ccc;")
        layout.addWidget(self.signal_log)

        group.setLayout(layout)
        return group

    def _setup_connections(self):
        """连接信号和槽"""
        self.basic_spinner.valueChanged.connect(self._on_basic_value_changed)
        self.d_progress_bar_1.valueChanged.connect(self._on_basic_progress_changed)

        self.horizontal_bar.valueChanged.connect(lambda v: print(f"横向进度条值: {v}"))
        self.vertical_bar.valueChanged.connect(lambda v: print(f"纵向进度条值: {v}"))

        self.interactive_bar.valueChanged.connect(self._on_interactive_changed)
        self.non_interactive_bar.valueChanged.connect(self._on_non_interactive_changed)
        self.interactive_checkbox.stateChanged.connect(self._on_interactive_mode_changed)

        self.signal_bar.valueChanged.connect(self._on_signal_value_changed)
        self.signal_bar.userInteracting.connect(self._on_signal_interacting)
        self.signal_bar.userInteractionEnded.connect(self._on_signal_interaction_ended)

    def _start_auto_test(self):
        """启动自动测试"""
        self.test_counter = 0
        self.test_timer = QTimer()
        self.test_timer.timeout.connect(self._run_auto_test)
        self.test_timer.start(2000)

    def _run_auto_test(self):
        """运行自动测试"""
        self.test_counter += 1

        if self.test_counter == 1:
            self.basic_spinner.setValue(700)
        elif self.test_counter == 2:
            self.horizontal_bar.setValue(80)
        elif self.test_counter == 3:
            self.vertical_bar.setValue(90)
        elif self.test_counter == 4:
            self.interactive_bar.setValue(45)
        elif self.test_counter == 5:
            self.signal_bar.setValue(60)
        else:
            self.test_counter = 0

    def _on_basic_value_changed(self, value):
        """基础值变化处理"""
        self.d_progress_bar_1.setValue(value)

    def _on_basic_progress_changed(self, value):
        """基础进度条值变化处理"""
        self.basic_value_label.setText(f"当前值: {value}")

    def _on_interactive_changed(self, value):
        """可交互进度条值变化处理"""
        self.interactive_label.setText(f"当前值: {value}")

    def _on_non_interactive_changed(self, value):
        """不可交互进度条值变化处理"""
        self.non_interactive_label.setText(f"当前值: {value}")

    def _on_interactive_mode_changed(self, state):
        """交互模式切换处理"""
        is_interactive = state == Qt.Checked
        self.interactive_bar.setInteractive(is_interactive)
        self.signal_bar.setInteractive(is_interactive)

    def _on_track_color_clicked(self):
        """轨道色按钮点击处理"""
        from PyQt5.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor("#f1f3f5"), self, "选择轨道底板色")
        if color.isValid():
            self.color_bar.set_track_color(color)

    def _on_progress_color_clicked(self):
        """进度色按钮点击处理"""
        from PyQt5.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor("#4ECDC4"), self, "选择进度色")
        if color.isValid():
            self.color_bar.set_progress_color(color)

    def _on_border_color_clicked(self):
        """边框色按钮点击处理"""
        from PyQt5.QtWidgets import QColorDialog
        color = QColorDialog.getColor(QColor("#FFFFFF"), self, "选择边框色")
        if color.isValid():
            self.border_color_bar.set_handle_border_color(color)
            self.gold_handle_bar.set_handle_border_color(color)

    def _on_border_width_changed(self, width):
        """边框宽度变化处理"""
        self.border_color_bar.set_handle_border_width(width)
        self.gold_handle_bar.set_handle_border_width(width)

    def _on_signal_value_changed(self, value):
        """信号值变化处理"""
        self.signal_log.setText(f"信号日志: valueChanged({value})")

    def _on_signal_interacting(self):
        """信号交互开始处理"""
        self.signal_log.setText("信号日志: userInteracting()")

    def _on_signal_interaction_ended(self):
        """信号交互结束处理"""
        current_value = self.signal_bar.value()
        self.signal_log.setText(f"信号日志: userInteractionEnded() - 最终值: {current_value}")


def main():
    """主函数"""
    app = QApplication(sys.argv)

    window = D_ProgressBarTestWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
