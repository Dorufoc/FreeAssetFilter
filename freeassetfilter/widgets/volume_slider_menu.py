#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 独立音量条浮动菜单组件
用于提供独立的音量控制功能，可在自定义权重中使用
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QApplication
from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import QIcon, QFont

# 导入现有的自定义控件
from .custom_control_menu import CustomControlMenu
from .progress_widgets import CustomValueBar
from .button_widgets import CustomButton
from freeassetfilter.core.svg_renderer import SvgRenderer
import os


class VolumeSliderMenu(QWidget):
    """
    独立音量条浮动菜单组件
    包含音量按钮和可弹出的音量条菜单
    """
    valueChanged = pyqtSignal(int)  # 音量值变化信号
    mutedChanged = pyqtSignal(bool)  # 静音状态变化信号
    
    def __init__(self, parent=None):
        """
        初始化音量条浮动菜单
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 音量属性
        self._volume = 100  # 默认音量100%
        self._muted = False  # 默认不静音
        self._menu_visible = False  # 菜单是否可见
        
        # 图标属性
        self._icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        self._volume_icon_path = os.path.join(self._icon_dir, 'speaker.svg')
        self._mute_icon_path = os.path.join(self._icon_dir, 'speaker_slash.svg')
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """
        初始化UI组件
        """
        # 设置布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建音量按钮，使用CustomButton
        self.volume_button = CustomButton(
            text=self._volume_icon_path,
            button_type="normal",
            display_mode="icon",
            height=18
        )
        # 设置音量图标
        self.update_volume_icon()
        
        # 创建音量菜单
        self.volume_menu = CustomControlMenu(self)
        
        # 调整菜单内边距，确保内容居中且与按钮宽度匹配
        # 设置内边距为0，避免内容容器宽度超过按钮宽度
        self.volume_menu._padding = 0
        
        # 将阴影半径设置为0，消除阴影带来的偏移
        # 阴影虽然透明，但会增加菜单总宽度，导致位置计算不准确
        self.volume_menu._shadow_radius = 0
        
        # 设置菜单样式，确保没有外边框
        self.volume_menu.setStyleSheet("QWidget { border: none; background-color: transparent; }")
        
        # 创建音量条
        self.volume_slider = CustomValueBar(
            orientation=CustomValueBar.Vertical,
            interactive=True
        )
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self._volume)
        
        # 设置音量条尺寸，考虑DPI缩放
        # 音量条宽度与音量按钮宽度匹配，确保视觉居中
        # 使用与音量按钮相同的固定尺寸
        button_size = int(18 * self.dpi_scale)
        slider_width = button_size
        slider_height = int(50 * self.dpi_scale)
        self.volume_slider.setFixedSize(slider_width, slider_height)
        
        # 确保音量按钮也使用相同的尺寸
        self.volume_button.setFixedSize(button_size, button_size)
        
        # 创建包含音量条和百分比标签的容器
        from PyQt5.QtWidgets import QVBoxLayout, QLabel
        container = QWidget()
        container.setStyleSheet("QWidget { background-color: transparent; border: none; }")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(int(2.5 * self.dpi_scale))
        
        # 创建百分比显示标签
        self.volume_label = QLabel(f"{self._volume}%")
        self.volume_label.setAlignment(Qt.AlignCenter)
        self.volume_label.setFont(self.global_font)  # 使用全局字体
        
        # 设置标签样式，确保美观
        # 字体大小根据DPI缩放，颜色与应用风格一致
        font_size = int(6 * self.dpi_scale)
        self.volume_label.setStyleSheet(f"QLabel {{ font-size: {font_size}px; color: #333333; font-weight: normal; }}")
        
        # 添加标签和音量条到容器
        container_layout.addWidget(self.volume_label)
        container_layout.addWidget(self.volume_slider)
        
        # 将容器设置为菜单的内容
        self.volume_menu.set_content(container)
        
        # 强制调整菜单大小，确保尺寸计算准确
        self.volume_menu.adjustSize()
        
        # 将音量按钮添加到主布局
        main_layout.addWidget(self.volume_button)
        
        # 连接信号和槽
        self.volume_button.clicked.connect(self.toggle_menu)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        
    def update_volume_icon(self):
        """
        更新音量图标
        """
        # 获取当前图标路径：静音或音量为0时显示静音图标，否则显示正常音量图标
        icon_path = self._mute_icon_path if (self._muted or self._volume == 0) else self._volume_icon_path
        
        # 更新CustomButton的图标
        self.volume_button._icon_path = icon_path
        self.volume_button._display_mode = "icon"
        self.volume_button._render_icon()
        self.volume_button.update()
        
    def toggle_mute(self):
        """
        切换静音状态
        """
        self._muted = not self._muted
        self.update_volume_icon()
        self.mutedChanged.emit(self._muted)
        
    def set_muted(self, muted):
        """
        设置静音状态
        
        Args:
            muted (bool): 是否静音
        """
        if self._muted != muted:
            self._muted = muted
            self.update_volume_icon()
            self.mutedChanged.emit(self._muted)
        
    def muted(self):
        """
        获取当前静音状态
        
        Returns:
            bool: 是否静音
        """
        return self._muted
        
    def set_volume(self, volume):
        """
        设置音量值
        
        Args:
            volume (int): 音量值，范围0-100
        """
        if volume < 0:
            volume = 0
        elif volume > 100:
            volume = 100
            
        if self._volume != volume:
            self._volume = volume
            self.volume_slider.setValue(volume)
            self.valueChanged.emit(volume)
            
            # 更新音量百分比标签
            if hasattr(self, 'volume_label'):
                self.volume_label.setText(f"{self._volume}%")
            
            # 如果音量不为0且当前静音，则取消静音
            # 直接更新静音状态，不发出信号，避免无限递归
            if volume > 0 and self._muted:
                self._muted = False
            
            # 更新音量图标，确保音量为0时显示静音图标
            self.update_volume_icon()
        
    def volume(self):
        """
        获取当前音量值
        
        Returns:
            int: 当前音量值，范围0-100
        """
        return self._volume
        
    def toggle_menu(self):
        """
        切换音量菜单显示/隐藏状态
        """
        if self._menu_visible:
            self.hide_menu()
        else:
            self.show_menu()
            
    def show_menu(self):
        """
        显示音量菜单
        """
        if not self._menu_visible:
            # 设置目标按钮
            self.volume_menu.set_target_button(self.volume_button)
            # 显示菜单
            self.volume_menu.show()
            self._menu_visible = True
            # 连接菜单关闭信号
            self.volume_menu.closeEvent = self._on_menu_close
            # 连接点击外部区域关闭菜单信号
            self.volume_menu.mousePressEvent = self._on_menu_click
            # 连接按钮的leaveEvent
            self.volume_button.leaveEvent = self._on_button_leave
            # 启动定时器，3秒后检查是否需要关闭菜单
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(3000, self._check_leave_and_close)
            
    def hide_menu(self):
        """
        隐藏音量菜单
        """
        if self._menu_visible:
            self.volume_menu.close()
            self._menu_visible = False
            # 断开按钮的leaveEvent
            self.volume_button.leaveEvent = None
            
    def _on_menu_close(self, event):
        """
        菜单关闭事件处理
        """
        self._menu_visible = False
        # 断开按钮的leaveEvent
        self.volume_button.leaveEvent = None
        # 调用原始的closeEvent
        super(CustomControlMenu, self.volume_menu).closeEvent(event)
        
    def _on_button_leave(self, event):
        """
        鼠标离开音量按钮事件
        """
        # 启动定时器，3秒后检查是否需要关闭菜单
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(3000, self._check_leave_and_close)
        # 调用父类的leaveEvent
        from PyQt5.QtWidgets import QPushButton
        super(QPushButton, self.volume_button).leaveEvent(event)
        
    def _on_menu_click(self, event):
        """
        菜单点击事件，处理点击外部区域关闭菜单
        """
        # 如果点击的是菜单内部，不处理
        if self.volume_menu.rect().contains(event.pos()):
            return
        # 否则关闭菜单
        self.hide_menu()
        
    def _on_volume_changed(self, value):
        """
        音量值变化处理
        
        Args:
            value (int): 新的音量值
        """
        self.set_volume(value)
        
    def enterEvent(self, event):
        """
        鼠标进入组件事件
        """
        # 移除鼠标悬停显示菜单的逻辑，改为点击显示
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        """
        鼠标离开组件事件
        """
        # 移除鼠标离开时的延迟隐藏逻辑，改为点击关闭和3秒自动关闭
        super().leaveEvent(event)
        
    def _check_leave_and_close(self):
        """
        检查是否真正离开组件，并在离开3秒后关闭菜单
        """
        # 检查鼠标是否在组件或菜单上
        from PyQt5.QtCore import QPoint, QRect
        from PyQt5.QtGui import QCursor
        
        # 获取全局鼠标位置，使用兼容Qt 5所有版本的QCursor.pos()
        global_pos = QCursor.pos()
        
        # 检查鼠标是否在VolumeSliderMenu组件上
        widget_rect = self.mapToGlobal(QPoint(0, 0))
        widget_rect = QRect(widget_rect, self.size())
        if widget_rect.contains(global_pos):
            return
        
        # 检查鼠标是否在音量菜单上
        menu_rect = self.volume_menu.mapToGlobal(QPoint(0, 0))
        menu_rect = QRect(menu_rect, self.volume_menu.size())
        if menu_rect.contains(global_pos):
            return
        
        # 鼠标不在组件或菜单上，隐藏菜单
        self.hide_menu()
            
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        super().mousePressEvent(event)
        
    def resizeEvent(self, event):
        """
        窗口大小变化事件
        """
        super().resizeEvent(event)
        
    def setStyleSheet(self, styleSheet):
        """
        设置样式表
        
        Args:
            styleSheet: 样式表字符串
        """
        super().setStyleSheet(styleSheet)
        self.volume_button.setStyleSheet(styleSheet)
