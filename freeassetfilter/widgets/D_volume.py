#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 音量控制悬浮菜单组件
基于 D_hover_menu 的音量控制控件，包含百分比显示和纵向进度条
特点：
- 使用 D_hover_menu 作为容器
- 上方显示音量百分比（居中）
- 下方为纵向可交互进度条
- 支持DPI缩放和主题颜色
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from .D_hover_menu import D_HoverMenu
from .progress_widgets import D_ProgressBar


class D_Volume(QWidget):
    """
    音量控制悬浮菜单组件
    基于 D_hover_menu，包含百分比显示和纵向进度条
    """

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        """
        初始化音量控制组件

        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())

        self._volume = 100

        self._init_ui()

    def _init_ui(self):
        """初始化UI组件"""
        self._menu = D_HoverMenu(self, position=D_HoverMenu.Position_Top)

        container = QWidget()
        container.setStyleSheet("QWidget { background-color: transparent; border: none; }")
        container_layout = QVBoxLayout(container)
        padding = int(6 * self.dpi_scale)
        container_layout.setContentsMargins(padding, padding, padding, padding)
        container_layout.setSpacing(int(2.5 * self.dpi_scale))
        container_layout.setAlignment(Qt.AlignCenter)

        self._percentage_label = QLabel(f"{self._volume}%")
        self._percentage_label.setAlignment(Qt.AlignCenter)
        self._percentage_label.setFont(self.global_font)

        app = QApplication.instance()
        text_color = "#333333"
        if hasattr(app, 'settings_manager'):
            text_color = app.settings_manager.get_setting(
                "appearance.colors.secondary_color", "#333333"
            )

        font_size = int(6 * self.dpi_scale)
        self._percentage_label.setStyleSheet(
            f"QLabel {{ font-size: {font_size}px; color: {text_color}; "
            f"font-weight: normal; background-color: transparent; }}"
        )

        self._progress_bar = D_ProgressBar(
            orientation=D_ProgressBar.Vertical,
            is_interactive=True
        )
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(self._volume)

        button_size = int(18 * self.dpi_scale)
        slider_width = button_size
        slider_height = int(50 * self.dpi_scale)
        self._progress_bar.setFixedSize(slider_width, slider_height)

        container_layout.addWidget(self._percentage_label)
        container_layout.addWidget(self._progress_bar)

        self._menu.set_content(container)
        self._menu.set_timeout_enabled(False)

    def enterEvent(self, event):
        """鼠标进入事件 - 禁用hover检测"""
        pass

    def leaveEvent(self, event):
        """鼠标离开事件 - 禁用hover检测"""
        pass

    def set_target_widget(self, widget):
        """
        设置目标控件，音量菜单将显示在该控件附近

        Args:
            widget: 目标控件
        """
        self._menu.set_target_widget(widget)

    def show(self):
        """显示音量菜单"""
        self._menu.show()

    def hide(self):
        """隐藏音量菜单"""
        self._menu.hide()

    def is_visible(self):
        """检查菜单是否正在显示"""
        return self._menu.is_visible()

    def set_volume(self, volume):
        """
        设置音量值

        Args:
            volume: 音量值，范围0-100
        """
        if volume < 0:
            volume = 0
        elif volume > 100:
            volume = 100

        if self._volume != volume:
            self._volume = volume
            self._progress_bar.setValue(volume)
            self._percentage_label.setText(f"{self._volume}%")

    def volume(self):
        """
        获取当前音量值

        Returns:
            int: 当前音量值，范围0-100
        """
        return self._volume

    def toggle(self):
        """切换显示/隐藏状态"""
        if self._menu.is_visible():
            self._menu.hide()
        else:
            self._menu.show()

    def update_style(self):
        """更新样式，用于主题变化时"""
        app = QApplication.instance()
        text_color = "#333333"
        if hasattr(app, 'settings_manager'):
            text_color = app.settings_manager.get_setting(
                "appearance.colors.secondary_color", "#333333"
            )

        font_size = int(6 * self.dpi_scale)
        self._percentage_label.setStyleSheet(
            f"QLabel {{ font-size: {font_size}px; color: {text_color}; "
            f"font-weight: normal; background-color: transparent; }}"
        )
