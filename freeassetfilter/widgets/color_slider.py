#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
颜色滑条控件
用于选择色相(Hue)、饱和度(Saturation)和亮度(Lightness)
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QSize, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import QApplication

from freeassetfilter.widgets.progress_widgets import CustomValueBar


class ColorSliderWidget(QWidget):
    """
    颜色滑条控件
    控制色相、饱和度和亮度
    
    信号:
        color_changed: 颜色变化时发出，传递RGB颜色字符串
    """
    
    color_changed = Signal(str)
    
    def __init__(self, parent=None):
        """
        初始化颜色滑条控件
        
        Args:
            parent (QWidget): 父控件
        """
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.settings_manager = getattr(app, 'settings_manager', None)
        self.global_font_size = getattr(app, 'default_font_size', 8)
        
        font_size = int(self.global_font_size * self.dpi_scale)
        
        self._hue = 0
        self._saturation = 100
        self._lightness = 50
        
        self._init_ui(font_size)
        self._connect_signals()
        self._update_colors()
    
    def _init_ui(self, font_size):
        """初始化UI"""
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(int(4 * self.dpi_scale))
        self.layout.addStretch(0)
        
        self.hue_label = QLabel("色相", self)
        self.hue_label.setFont(QFont("Noto Sans SC", font_size))
        self.hue_label.setFixedHeight(int(10 * self.dpi_scale))
        self.layout.addWidget(self.hue_label)
        
        self.hue_slider = HueSlider(self.dpi_scale)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(0)
        self.hue_slider.setFixedHeight(int(12 * self.dpi_scale))
        self.hue_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.layout.addWidget(self.hue_slider, 1)
        
        self.saturation_label = QLabel("饱和度", self)
        self.saturation_label.setFont(QFont("Noto Sans SC", font_size))
        self.saturation_label.setFixedHeight(int(10 * self.dpi_scale))
        self.layout.addWidget(self.saturation_label)
        
        self.saturation_slider = CustomValueBar(orientation=CustomValueBar.Horizontal, interactive=True)
        self.saturation_slider.setRange(0, 100)
        self.saturation_slider.setValue(100)
        self.saturation_slider.setFixedHeight(int(12 * self.dpi_scale))
        self.saturation_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.layout.addWidget(self.saturation_slider, 1)
        self._update_saturation_slider_colors()
        
        self.lightness_label = QLabel("亮度", self)
        self.lightness_label.setFont(QFont("Noto Sans SC", font_size))
        self.lightness_label.setFixedHeight(int(10 * self.dpi_scale))
        self.layout.addWidget(self.lightness_label)
        
        self.lightness_slider = CustomValueBar(orientation=CustomValueBar.Horizontal, interactive=True)
        self.lightness_slider.setRange(0, 100)
        self.lightness_slider.setValue(50)
        self.lightness_slider.setFixedHeight(int(12 * self.dpi_scale))
        self.lightness_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.layout.addWidget(self.lightness_slider, 1)
        self._update_lightness_slider_color()
        
        self.color_preview = QLabel(self)
        self.color_preview.setFixedHeight(int(12 * self.dpi_scale))
        self.color_preview.setAlignment(Qt.AlignCenter)
        self.color_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.layout.addWidget(self.color_preview)
    
    def _connect_signals(self):
        """连接信号"""
        self.hue_slider.valueChanged.connect(self._on_hue_changed)
        self.saturation_slider.valueChanged.connect(self._on_saturation_changed)
        self.lightness_slider.valueChanged.connect(self._on_lightness_changed)
    
    def _on_hue_changed(self, value):
        """色相值变化"""
        self._hue = value
        self._update_colors()
    
    def _on_saturation_changed(self, value):
        """饱和度值变化"""
        self._saturation = value
        self._update_colors()
    
    def _on_lightness_changed(self, value):
        """亮度值变化"""
        self._lightness = value
        self._update_colors()
    
    def _update_colors(self):
        """更新滑条颜色和预览"""
        self._update_saturation_slider_colors()
        self._update_lightness_slider_color()
        self._update_preview()
        
        rgb_color = self._hsl_to_rgb(self._hue, self._saturation, self._lightness)
        self.color_changed.emit(rgb_color)
    
    def _update_saturation_slider_colors(self):
        """更新饱和度滑条颜色"""
        saturation_color = QColor.fromHsl(self._hue, 255, 128)
        saturation_gradient = QColor.fromHsl(self._hue, 0, 128)
        self.saturation_slider.set_progress_color(saturation_color)
        self.saturation_slider.set_bg_color(saturation_gradient)
        self.saturation_slider.set_gradient_mode(True)
        self.saturation_slider.set_gradient_colors([saturation_gradient, saturation_color])
        self.saturation_slider.set_dynamic_handle_color(True, lambda v: QColor.fromHsl(self._hue, v * 255 // 100, 128))
    
    def _update_lightness_slider_color(self):
        """更新亮度滑条颜色"""
        lightness_progress = QColor.fromHsl(self._hue, self._saturation * 255 // 100, 128)
        lightness_bg_start = QColor.fromHsl(self._hue, self._saturation * 255 // 100, 255)
        lightness_bg_end = QColor.fromHsl(self._hue, self._saturation * 255 // 100, 0)
        self.lightness_slider.set_progress_color(lightness_progress)
        self.lightness_slider.set_bg_color(lightness_bg_start)
        self.lightness_slider.set_gradient_mode(True)
        self.lightness_slider.set_gradient_colors([lightness_bg_start, lightness_bg_end])
        self.lightness_slider.set_dynamic_handle_color(True, lambda v: QColor.fromHsl(self._hue, self._saturation * 255 // 100, v))
    
    def _update_preview(self):
        """更新颜色预览"""
        rgb_color = self._hsl_to_rgb(self._hue, self._saturation, self._lightness)
        self.color_preview.setStyleSheet(f"background-color: {rgb_color}; border: 1px solid {rgb_color}; border-radius: {int(3 * self.dpi_scale)}px;")
    
    def _hsl_to_rgb(self, h, s, l):
        """
        HSL转RGB
        
        Args:
            h (int): 色相 (0-360)
            s (int): 饱和度 (0-100)
            l (int): 亮度 (0-100)
        
        Returns:
            str: RGB颜色字符串 (#RRGGBB)
        """
        h_normalized = h / 360.0
        s_normalized = s / 100.0
        l_normalized = l / 100.0
        
        if s_normalized == 0:
            gray = int(l_normalized * 255)
            return f"#{gray:02X}{gray:02X}{gray:02X}"
        
        def hue_to_rgb(p, q, t):
            if t < 0:
                t += 1
            if t > 1:
                t -= 1
            if t < 1/6:
                return p + (q - p) * 6 * t
            if t < 1/2:
                return q
            if t < 2/3:
                return p + (q - p) * (2/3 - t) * 6
            return p
        
        q = l_normalized * (1 + s_normalized) if l_normalized < 0.5 else l_normalized + s_normalized - l_normalized * s_normalized
        p = 2 * l_normalized - q
        
        r = int(hue_to_rgb(p, q, h_normalized + 1/3) * 255)
        g = int(hue_to_rgb(p, q, h_normalized) * 255)
        b = int(hue_to_rgb(p, q, h_normalized - 1/3) * 255)
        
        return f"#{r:02X}{g:02X}{b:02X}"
    
    def get_color(self):
        """
        获取当前颜色
        
        Returns:
            str: RGB颜色字符串 (#RRGGBB)
        """
        return self._hsl_to_rgb(self._hue, self._saturation, self._lightness)
    
    def set_color(self, rgb_color):
        """
        设置颜色
        
        Args:
            rgb_color (str): RGB颜色字符串 (#RRGGBB)
        """
        color = QColor(rgb_color)
        if color.isValid():
            h, s, l = color.hue(), color.saturation(), color.lightness()
            if h < 0:
                h = 0
            self._hue = h
            self._saturation = int(s * 100 / 255)
            self._lightness = int(l * 100 / 255)
            
            self.hue_slider.setValue(self._hue)
            self.saturation_slider.setValue(self._saturation)
            self.lightness_slider.setValue(self._lightness)
            
            self._update_colors()
    
    def sizeHint(self):
        """返回建议的大小"""
        return QSize(int(150 * self.dpi_scale), int(80 * self.dpi_scale))


class HueSlider(QWidget):
    """
    色相滑条控件
    背景显示完整的色相渐变范围
    """
    
    valueChanged = Signal(int)
    
    def __init__(self, dpi_scale=1.0, parent=None):
        super().__init__(parent)
        self.dpi_scale = dpi_scale
        
        self._minimum = 0
        self._maximum = 360
        self._value = 0
        self._is_pressed = False
        
        self._bar_size = int(3 * self.dpi_scale)
        self._handle_radius = self._bar_size
        self._bar_radius = self._bar_size // 2
        self._handle_border_width = int(1 * self.dpi_scale)
        
        self.setMinimumHeight(self._bar_size + self._handle_radius * 2)
        self.setMaximumHeight(self._bar_size + self._handle_radius * 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self.setAttribute(Qt.WA_Hover, True)
        self._is_hovered = False
    
    def setRange(self, minimum, maximum):
        """设置范围"""
        self._minimum = minimum
        self._maximum = maximum
        self.update()
    
    def setValue(self, value):
        """设置值"""
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)
    
    def value(self):
        """获取当前值"""
        return self._value
    
    def enterEvent(self, event):
        """鼠标进入"""
        self._is_hovered = True
        self.update()
    
    def leaveEvent(self, event):
        """鼠标离开"""
        self._is_hovered = False
        self.update()
    
    def mousePressEvent(self, event):
        """鼠标按下"""
        if event.button() == Qt.LeftButton:
            self._is_pressed = True
            self._update_value_from_pos(event.pos().x())
    
    def mouseMoveEvent(self, event):
        """鼠标移动"""
        if self._is_pressed:
            self._update_value_from_pos(event.pos().x())
    
    def mouseReleaseEvent(self, event):
        """鼠标释放"""
        self._is_pressed = False
    
    def _update_value_from_pos(self, pos):
        """根据位置更新值"""
        bar_length = self.width() - 2 * self._handle_radius
        relative_pos = pos - self._handle_radius
        if relative_pos < 0:
            relative_pos = 0
        elif relative_pos > bar_length:
            relative_pos = bar_length
        
        if bar_length > 0:
            ratio = relative_pos / bar_length
        else:
            ratio = 0
        
        value = int(self._minimum + ratio * (self._maximum - self._minimum))
        self.setValue(value)
    
    def paintEvent(self, event):
        """绘制"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        bar_y = (rect.height() - self._bar_size) // 2
        bar_length = rect.width() - 2 * self._handle_radius
        
        gradient = QLinearGradient(self._handle_radius, 0, self.width() - self._handle_radius, 0)
        hue_colors = [
            QColor.fromHsl(0, 255, 128),
            QColor.fromHsl(60, 255, 128),
            QColor.fromHsl(120, 255, 128),
            QColor.fromHsl(180, 255, 128),
            QColor.fromHsl(240, 255, 128),
            QColor.fromHsl(300, 255, 128),
            QColor.fromHsl(360, 255, 128),
        ]
        for i, color in enumerate(hue_colors):
            gradient.setColorAt(i / 6, color)
        
        bg_rect = QRect(self._handle_radius, bar_y, bar_length, self._bar_size)
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
        
        if (self._maximum - self._minimum) > 0:
            progress_ratio = (self._value - self._minimum) / (self._maximum - self._minimum)
        else:
            progress_ratio = 0
        
        progress_length = int(bar_length * progress_ratio)
        
        offset_y = (self._bar_size - self._handle_radius * 2) // 2
        handle_y = bar_y + offset_y
        handle_x = self._handle_radius + progress_length
        handle_x = min(handle_x, self.width() - self._handle_radius * 2)
        
        handle_color = QColor.fromHsl(self._value, 255, 128)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(handle_color, self._handle_border_width))
        painter.drawEllipse(handle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
        
        inner_radius = self._handle_radius - self._handle_border_width
        inner_x = handle_x + self._handle_border_width
        inner_y = handle_y + self._handle_border_width
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(inner_x, inner_y, inner_radius * 2, inner_radius * 2)
