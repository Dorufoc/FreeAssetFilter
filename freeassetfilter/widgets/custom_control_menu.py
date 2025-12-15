#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

自定义控制菜单组件
用于播放器等控件的弹出式控制菜单
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt, QRect, QSize, QPoint
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFontMetrics


class CustomControlMenu(QWidget):
    """
    自定义控制菜单组件
    用于播放器等控件的弹出式控制菜单
    特点：
    - 纯白圆角矩形外观，带有阴影效果
    - 支持DPI缩放，适配不同屏幕分辨率
    - 可在指定按钮上方水平居中显示
    - 支持自定义内容布局
    """
    
    def __init__(self, parent=None):
        """
        初始化自定义控制菜单
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        
        # 获取应用实例和DPI缩放因子
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 基础属性
        self._parent_widget = parent
        self._target_button = None
        
        # 外观属性，应用DPI缩放
        self._bg_color = QColor(255, 255, 255)  # 白色背景
        self._shadow_color = QColor(0, 0, 0, 25)  # 阴影颜色，透明度25/255
        self._shadow_radius = int(4 * self.dpi_scale)  # 阴影半径
        self._border_radius = int(8 * self.dpi_scale)  # 圆角半径
        self._padding = int(10 * self.dpi_scale)  # 内边距
        
        # 布局属性
        self._content_layout = None
        self._is_content_set = False
        
        # 初始化UI
        self.init_ui()
        
    def init_ui(self):
        """
        初始化UI组件
        """
        # 设置窗口属性
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 创建内容容器
        self.content_container = QWidget()
        self.content_container.setStyleSheet("background-color: transparent;")
        self.content_container.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        
        # 创建内容布局
        self._content_layout = QVBoxLayout(self.content_container)
        self._content_layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        self._content_layout.setSpacing(int(10 * self.dpi_scale))
        
        main_layout.addWidget(self.content_container)
    
    def set_content(self, content_widget):
        """
        设置菜单内容
        
        Args:
            content_widget: 要显示的内容部件
        """
        # 清空现有内容
        for i in reversed(range(self._content_layout.count())):
            widget = self._content_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        # 添加新内容
        if content_widget:
            self._content_layout.addWidget(content_widget)
            self._is_content_set = True
            
            # 调整菜单大小以适应内容
            self.adjustSize()
    
    def set_target_button(self, button):
        """
        设置目标按钮，菜单将显示在该按钮的正上方
        
        Args:
            button: 目标按钮部件
        """
        self._target_button = button
    
    def show(self):
        """
        显示菜单
        先定位，再显示
        """
        if not self._is_content_set:
            return
        
        # 计算菜单位置
        self._calculate_position()
        
        # 显示菜单
        super().show()
    
    def _calculate_position(self):
        """
        计算菜单在目标按钮正上方水平居中的位置
        """
        if not self._target_button:
            # 如果没有目标按钮，默认显示在屏幕中心
            screen = self.screen()
            screen_rect = screen.availableGeometry()
            x = (screen_rect.width() - self.width()) // 2
            y = (screen_rect.height() - self.height()) // 2
            self.move(x, y)
            return
        
        # 获取目标按钮的全局位置和尺寸
        button_rect = self._target_button.geometry()
        button_global_pos = self._target_button.mapToGlobal(QPoint(0, 0))
        
        # 计算菜单位置
        menu_width = self.width()
        menu_height = self.height()
        
        # 水平居中：按钮中心点与菜单中心点对齐
        x = button_global_pos.x() + (button_rect.width() - menu_width) // 2
        
        # 垂直位置：菜单底部距离按钮顶部10px
        y = button_global_pos.y() - menu_height - int(10 * self.dpi_scale)
        
        # 确保菜单在屏幕内
        screen = self.screen()
        screen_rect = screen.availableGeometry()
        
        # 水平边界检查
        if x < 0:
            x = 0
        elif x + menu_width > screen_rect.width():
            x = screen_rect.width() - menu_width
        
        # 垂直边界检查
        if y < 0:
            y = button_global_pos.y() + button_rect.height() + int(10 * self.dpi_scale)
        
        # 设置菜单位置
        self.move(x, y)
    
    def paintEvent(self, event):
        """
        绘制菜单外观，包括圆角和阴影
        """
        from PyQt5.QtCore import QRectF
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制阴影
        shadow_path = QPainterPath()
        shadow_rect = QRectF(
            self._shadow_radius,
            self._shadow_radius,
            self.width() - 2 * self._shadow_radius,
            self.height() - 2 * self._shadow_radius
        )
        shadow_path.addRoundedRect(shadow_rect, self._border_radius, self._border_radius)
        painter.fillPath(shadow_path, QBrush(self._shadow_color))
        
        # 绘制背景
        bg_path = QPainterPath()
        bg_rect = QRectF(
            self._shadow_radius,
            self._shadow_radius,
            self.width() - 2 * self._shadow_radius,
            self.height() - 2 * self._shadow_radius
        )
        bg_path.addRoundedRect(bg_rect, self._border_radius, self._border_radius)
        painter.fillPath(bg_path, QBrush(self._bg_color))
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件，处理菜单外点击关闭
        """
        # 检查点击是否在菜单内
        if not self.rect().contains(event.pos()):
            self.close()
        super().mousePressEvent(event)
    
    def closeEvent(self, event):
        """
        关闭事件
        """
        super().closeEvent(event)
    
    def adjustSize(self):
        """
        调整菜单大小以适应内容
        """
        if self._content_layout:
            self.content_container.adjustSize()
            
            # 计算总尺寸，包括阴影
            content_width = self.content_container.width()
            content_height = self.content_container.height()
            
            total_width = content_width + 2 * self._shadow_radius
            total_height = content_height + 2 * self._shadow_radius
            
            self.setFixedSize(total_width, total_height)
        super().adjustSize()
