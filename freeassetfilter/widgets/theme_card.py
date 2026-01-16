#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ThemeCard 控件
现代主题编辑器的主题卡片组件，可用于单独显示主题选项
"""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPen, QBrush, QPainter, QFont


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
        
        # 增加卡片尺寸，为4px的选中边框留出足够空间
        self.setFixedSize(250, 170)
        self.setCursor(Qt.PointingHandCursor)
        
        # 主布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)
        
        self.setup_ui()
    
    def setup_ui(self):
        """设置UI界面"""
        if self.is_add_card:
            # 添加新设计的卡片
            self.add_layout = QHBoxLayout()
            self.add_label = QLabel("添加一个新设计..", self)
            self.add_label.setAlignment(Qt.AlignCenter)
            self.add_label.setFont(QFont("Noto Sans SC", 16))
            self.add_layout.addWidget(self.add_label)
            self.main_layout.addLayout(self.add_layout)
        else:
            # 确保颜色列表有足够的元素
            while len(self.colors) < 4:
                self.colors.append("#D9D9D9")
            
            # 色彩行
            self.color_layout = QHBoxLayout()
            self.color_layout.setSpacing(10)
            
            # 主题色
            self.theme_color = QLabel(self)
            self.theme_color.setFixedSize(66, 30)
            self.theme_color.setStyleSheet(f"background-color: {self.colors[0]}; border-radius: 10px;")
            self.color_layout.addWidget(self.theme_color)
            
            # 其他颜色
            for i, color in enumerate(self.colors[1:4]):
                color_label = QLabel(self)
                color_label.setFixedSize(30, 30)
                color_label.setStyleSheet(f"background-color: {color}; border-radius: 10px;")
                self.color_layout.addWidget(color_label)
            
            self.main_layout.addLayout(self.color_layout)
            
            # 文字行
            self.text_label = QLabel(self.theme_name, self)
            self.text_label.setAlignment(Qt.AlignCenter)
            self.text_label.setFont(QFont("Noto Sans SC", 16))
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
        # 确保颜色列表有足够的元素
        while len(self.colors) < 4:
            self.colors.append("#D9D9D9")
        
        if not self.is_add_card:
            # 更新主题色
            self.theme_color.setStyleSheet(f"background-color: {self.colors[0]}; border-radius: 10px;")
            
            # 更新其他颜色
            color_widgets = [widget for widget in self.color_layout.findChildren(QLabel) if widget != self.theme_color]
            for i, widget in enumerate(color_widgets[:3]):
                if i < len(self.colors[1:4]):
                    widget.setStyleSheet(f"background-color: {self.colors[i+1]}; border-radius: 10px;")
    
    def set_selected(self, is_selected):
        """设置选中状态
        
        Args:
            is_selected (bool): 是否选中
        """
        self.is_selected = is_selected
        self.update()
    
    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
    
    def paintEvent(self, event):
        """绘制事件，处理选中状态的边框"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制卡片背景（2px边框）
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        border_width = 2
        x = border_width // 2
        y = border_width // 2
        width = self.width() - border_width
        height = self.height() - border_width
        painter.setPen(QPen(QColor("#000000"), border_width))
        painter.drawRoundedRect(x, y, width, height, 20, 20)
        
        # 如果是选中状态，绘制加粗边框（4px边框）
        if self.is_selected and not self.is_add_card and self.colors:
            border_width = 4
            x = border_width // 2
            y = border_width // 2
            width = self.width() - border_width
            height = self.height() - border_width
            painter.setPen(QPen(QColor(self.colors[0]), border_width))
            painter.drawRoundedRect(x, y, width, height, 20, 20)
        
        # 如果是添加卡片，绘制虚线边框（2px边框）
        if self.is_add_card:
            border_width = 2
            x = border_width // 2
            y = border_width // 2
            width = self.width() - border_width
            height = self.height() - border_width
            pen = QPen(QColor("#000000"), border_width, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(x, y, width, height, 20, 20)
    
    def get_theme_info(self):
        """获取主题信息
        
        Returns:
            dict: 主题信息字典 {"name": str, "colors": list}
        """
        return {
            "name": self.theme_name,
            "colors": self.colors.copy()
        }
