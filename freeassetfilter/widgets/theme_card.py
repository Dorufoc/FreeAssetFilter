#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ThemeCard 控件
现代主题编辑器的主题卡片组件，可用于单独显示主题选项
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QPen, QBrush, QPainter, QFont

from freeassetfilter.widgets.color_slider import ColorSliderWidget


class ThemeCard(QWidget):
    """
    主题卡片组件
    可独立使用的主题选项控件，用于显示和选择主题
    
    参数:
        theme_name (str): 主题名称
        colors (list): 颜色列表 [主题色, 文本颜色, 次选颜色, 不可用颜色]
        is_selected (bool): 是否被选中
        is_add_card (bool): 是否为添加新设计的卡片
        parent (QWidget): 父控件
    
    信号:
        clicked: 卡片点击时发出，传递主题信息对象
    """
    
    clicked = pyqtSignal(object)  # 点击信号，传递主题信息
    color_changed = pyqtSignal(str)  # 颜色变化信号，传递RGB颜色字符串
    
    def __init__(self, theme_name="", colors=None, is_selected=False, is_add_card=False, parent=None):
        """
        初始化主题卡片
        
        Args:
            theme_name (str): 主题名称
            colors (list): 颜色列表 [主题色, 文本颜色, 次选颜色, 不可用颜色]
            is_selected (bool): 是否被选中
            is_add_card (bool): 是否为添加新设计的卡片
            parent (QWidget): 父控件
        """
        super().__init__(parent)
        self.theme_name = theme_name
        self.colors = colors if colors is not None else []
        self.is_selected = is_selected
        self.is_add_card = is_add_card
        self._flexible_width = None
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.settings_manager = getattr(app, 'settings_manager', None)
        self.global_font_size = getattr(app, 'default_font_size', 8)
        
        font_size = int(self.global_font_size * self.dpi_scale)
        
        auxiliary_color = "#f1f3f5"
        base_color = "#FFFFFF"
        secondary_color = "#333333"
        accent_color = "#007AFF"
        if self.settings_manager:
            auxiliary_color = self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
            base_color = self.settings_manager.get_setting("appearance.colors.base_color", "#FFFFFF")
            secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
            accent_color = self.settings_manager.get_setting("appearance.colors.accent_color", "#007AFF")
        
        self._accent_color = accent_color
        self._base_color = base_color
        self._auxiliary_color = auxiliary_color
        self._secondary_color = secondary_color
        self._is_hovered = False
        self.setAttribute(Qt.WA_Hover, True)
        
        self.setStyleSheet(f"background-color: {base_color}; border: 1px solid {auxiliary_color}; border-radius: {int(6 * self.dpi_scale)}px;")
        
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        self.main_layout.setSpacing(int(6 * self.dpi_scale))
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addStretch(1)
        
        self.setup_ui(font_size)
    
    def setup_ui(self, font_size):
        """设置UI界面"""
        auxiliary_color = "#f1f3f5"
        secondary_color = "#333333"
        if self.settings_manager:
            auxiliary_color = self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
            secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        if self.is_add_card:
            self.color_slider = ColorSliderWidget(self)
            self.color_slider.setContentsMargins(0, 0, 0, 0)
            self.color_slider.color_changed.connect(self._on_color_slider_changed)
            self.main_layout.insertWidget(0, self.color_slider, 1)
            self.main_layout.removeItem(self.main_layout.takeAt(self.main_layout.count() - 1))
        else:
            while len(self.colors) < 4:
                self.colors.append("#D9D9D9")
            
            self.color_layout = QHBoxLayout()
            self.color_layout.setSpacing(int(3 * self.dpi_scale))
            self.color_layout.setContentsMargins(0, int(5 * self.dpi_scale), 0, int(5 * self.dpi_scale))
            
            self.theme_color = QLabel(self)
            self.theme_color.setFixedSize(int(20 * self.dpi_scale), int(9 * self.dpi_scale))
            self.theme_color.setStyleSheet(f"background-color: {self.colors[0]}; border: 1px solid {auxiliary_color}; border-radius: {int(3 * self.dpi_scale)}px;")
            self.color_layout.addWidget(self.theme_color)
            
            for i, color in enumerate(self.colors[1:4]):
                color_label = QLabel(self)
                color_label.setFixedSize(int(9 * self.dpi_scale), int(9 * self.dpi_scale))
                color_label.setStyleSheet(f"background-color: {color}; border: 1px solid {auxiliary_color}; border-radius: {int(3 * self.dpi_scale)}px;")
                self.color_layout.addWidget(color_label)
            
            self.main_layout.addLayout(self.color_layout)
            
            self.text_label = QLabel(self.theme_name, self)
            self.text_label.setAlignment(Qt.AlignCenter)
            self.text_label.setStyleSheet(f"color: {secondary_color}; background-color: transparent; border: none;")
            font = QFont("Noto Sans SC", font_size)
            self.text_label.setFont(font)
            self.main_layout.addWidget(self.text_label)
    
    def set_theme_name(self, name):
        """设置主题名称
        
        Args:
            name (str): 新的主题名称
        """
        self.theme_name = name
        if not self.is_add_card:
            self.text_label.setText(name)
    
    def set_colors(self, colors):
        """设置主题颜色
        
        Args:
            colors (list): 颜色列表 [主题色, 文本颜色, 次选颜色, 不可用颜色]
        """
        self.colors = colors.copy()
        while len(self.colors) < 4:
            self.colors.append("#D9D9D9")
        
        auxiliary_color = "#f1f3f5"
        secondary_color = "#333333"
        if self.settings_manager:
            auxiliary_color = self.settings_manager.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
            secondary_color = self.settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
        
        if not self.is_add_card:
            self.theme_color.setStyleSheet(f"background-color: {self.colors[0]}; border: 1px solid {auxiliary_color}; border-radius: {int(3 * self.dpi_scale)}px;")
            
            color_widgets = [widget for widget in self.color_layout.findChildren(QLabel) if widget != self.theme_color]
            for i, widget in enumerate(color_widgets[:3]):
                if i < len(self.colors[1:4]):
                    widget.setStyleSheet(f"background-color: {self.colors[i+1]}; border: 1px solid {auxiliary_color}; border-radius: {int(3 * self.dpi_scale)}px;")
            
            if hasattr(self, 'text_label') and self.text_label:
                self.text_label.setStyleSheet(f"color: {secondary_color}; background-color: transparent; border: none;")
        self.update()
    
    def set_selected(self, is_selected):
        """设置选中状态
        
        Args:
            is_selected (bool): 是否选中
        """
        self.is_selected = is_selected
        self.update()
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton and not self.is_add_card:
            self.clicked.emit(self)
    
    def _on_color_slider_changed(self, color):
        """颜色滑条颜色变化"""
        self.color_changed.emit(color)
    
    def enterEvent(self, event):
        """鼠标进入事件"""
        self._is_hovered = True
        self.update()
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self._is_hovered = False
        self.update()
    
    def paintEvent(self, event):
        """绘制事件，处理选中状态和hover状态的边框和背景"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        border_width = 1
        x = border_width // 2
        y = border_width // 2
        width = self.width() - border_width
        height = self.height() - border_width
        
        if self.is_selected and not self.is_add_card and self.colors:
            card_accent = QColor(self.colors[0])
            card_accent.setAlpha(102)
            border_color = QColor(self.colors[0])
            
            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(QBrush(card_accent))
            painter.drawRoundedRect(x, y, width, height, int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        elif self._is_hovered and not self.is_add_card:
            border_color = QColor(self._auxiliary_color)
            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(QBrush(QColor(self._auxiliary_color)))
            painter.drawRoundedRect(x, y, width, height, int(6 * self.dpi_scale), int(6 * self.dpi_scale))
        else:
            border_color = QColor(self._auxiliary_color)
            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(QBrush(QColor(self._base_color)))
            painter.drawRoundedRect(x, y, width, height, int(6 * self.dpi_scale), int(6 * self.dpi_scale))
    
    def get_theme_info(self):
        """获取主题信息
        
        Returns:
            dict: 主题信息字典 {"name": str, "colors": list}
        """
        return {
            "name": self.theme_name,
            "colors": self.colors.copy()
        }
    
    def sizeHint(self):
        """返回建议的大小"""
        if self._flexible_width is not None:
            base_width = self._flexible_width
        else:
            base_width = int(75 * self.dpi_scale)
        return QSize(base_width, int(51 * self.dpi_scale))
    
    def set_flexible_width(self, width):
        """
        设置卡片动态宽度
        
        Args:
            width (int): 可用宽度（像素）
        """
        self._flexible_width = width
        if self.is_add_card:
            self.setMinimumWidth(int(100 * self.dpi_scale))
            self.setMaximumWidth(int(16777215))  # QWIDGETSIZE_MAX
        else:
            min_width = int(50 * self.dpi_scale)
            max_width = int(200 * self.dpi_scale)
            constrained_width = max(min_width, min(width, max_width))
            self.setFixedWidth(constrained_width)
        self.updateGeometry()
