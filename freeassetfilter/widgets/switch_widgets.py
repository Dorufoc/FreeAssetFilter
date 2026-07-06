#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 开关类自定义控件
包含独立的开关控件实现
"""

from PySide6.QtWidgets import QWidget, QPushButton, QApplication, QVBoxLayout
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap

# 用于SVG渲染
from freeassetfilter.core.preview.svg_renderer import SvgRenderer
import os


class CustomSwitch(QWidget):
    """
    独立的自定义开关控件
    特点：
    - 显示等比例的SVG贴图
    - 上下高度与普通自定义按钮一致
    - 支持点击切换开关状态
    - 支持DPI缩放
    - 无需容器布局
    """
    
    # 信号定义
    toggled = Signal(bool)  # 开关状态变化信号
    
    def __init__(self, parent=None, initial_value=False, height=20, dpi_scale=None):
        """
        初始化开关控件
        
        Args:
            parent: 父控件
            initial_value: 初始状态，默认为False（关闭）
            height: 开关高度，默认为40px，与CustomButton保持一致
            dpi_scale: DPI缩放因子，None时从QApplication自动获取
        """
        super().__init__(parent)
        
        if dpi_scale is not None:
            self.dpi_scale = dpi_scale
        else:
            self.dpi_scale = getattr(QApplication.instance(), 'dpi_scale_factor', 1.0)
        self._height = int(height * self.dpi_scale)
        self._is_checked = initial_value
        self.icon_ratio = 462 / 256  # 图标宽高比约为1.8:1
        self._width = int(self._height * self.icon_ratio)
        self.setFixedSize(self._width, self._height)
        
        self.click_button = QPushButton(self)
        self.click_button.setCheckable(True)
        self.click_button.setChecked(initial_value)
        self.click_button.setFixedSize(self._width, self._height)
        self.click_button.move(0, 0)
        self.click_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 0;
                margin: 0;
                border-radius: %dpx;
            }
            QPushButton:hover {
                background-color: transparent;
            }
            QPushButton:pressed {
                background-color: transparent;
            }
        """ % (self._height // 2))
        
        from PySide6.QtSvgWidgets import QSvgWidget
        self.svg_widget = QSvgWidget(self)
        self.svg_widget.setStyleSheet("background: transparent;")
        
        self.click_button.toggled.connect(self._on_switch_toggled)
        self.click_button.toggled.connect(self._update_switch_icon)
        
        # 延迟渲染图标，确保按钮尺寸已确定
        QTimer.singleShot(0, self._update_switch_icon)
    
    def _update_switch_icon(self):
        """
        更新开关图标
        先使用SvgRenderer类的颜色替换功能处理SVG内容，然后再加载到QSvgWidget中
        """
        is_checked = self.click_button.isChecked()
        
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        if is_checked:
            icon_path = os.path.join(icon_dir, '开.svg')
        else:
            icon_path = os.path.join(icon_dir, '关.svg')
        
        with open(icon_path, 'r', encoding='utf-8') as f:
            svg_content = f.read()
        
        processed_svg = SvgRenderer._replace_svg_colors(svg_content)
        self.svg_widget.load(processed_svg.encode('utf-8'))
        
        icon_height = int(self.height() * 0.9)
        icon_width = int(icon_height * self.icon_ratio)
        self.svg_widget.setFixedSize(icon_width, icon_height)
        
        x = (self.width() - icon_width) // 2
        y = (self.height() - icon_height) // 2
        self.svg_widget.move(x, y)
        
        # 确保点击按钮在最上层
        self.click_button.raise_()
    
    def _on_switch_toggled(self, checked):
        """
        开关状态变化处理
        """
        self._is_checked = checked
        self.toggled.emit(checked)
    
    def isChecked(self):
        """
        获取开关状态
        """
        return self._is_checked
    
    def setChecked(self, checked):
        """
        设置开关状态
        """
        self.click_button.setChecked(checked)
    
    def resizeEvent(self, event):
        """
        大小变化事件，重新渲染图标
        """
        super().resizeEvent(event)
        self.click_button.setFixedSize(self.width(), self.height())
        self.click_button.move(0, 0)
        self._update_switch_icon()
    
    def update_style(self):
        """
        更新开关样式，用于主题更新
        """
        self._update_switch_icon()
    
    def paintEvent(self, event):
        """
        绘制开关
        """
        super().paintEvent(event)
