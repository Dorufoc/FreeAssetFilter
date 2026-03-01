#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 轮盘选色组件
提供圆形色彩选择器，支持从色相环中选择颜色
特点：
- DPI缩放支持，适配不同屏幕分辨率
- 透明背景
- 基本尺寸管理
- 完整的颜色值输出接口
- 支持亮度和饱和度调节
- 颜色预览区域
"""

from PySide6.QtWidgets import QWidget, QApplication, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QPushButton
from PySide6.QtCore import Qt, Signal, QSize, QPoint, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QConicalGradient, QLinearGradient
import math

from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.D_hover_menu import D_HoverMenu
from freeassetfilter.utils.app_logger import info, debug, warning, error


class ColorWheelPicker(QWidget):
    """
    色相轮盘选择器
    特点：
    - DPI缩放支持
    - 透明背景
    - 仅负责色相选择，不处理饱和度和亮度
    - 可交互选择颜色
    - 支持信号机制
    """
    
    hueChanged = Signal(int)
    huePreviewChanged = Signal(int)
    hueSelected = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self._hue = 0
        
        self._is_pressed = False
        self._handle_radius = int(5 * self.dpi_scale)
        self._wheel_margin = int(4 * self.dpi_scale)
        self._wheel_width = int(12 * self.dpi_scale)
        
        self._setup_size()
        
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")
        
        self._is_hovered = False
        self.setAttribute(Qt.WA_Hover, True)
    
    def _setup_size(self):
        """设置尺寸参数，应用DPI缩放"""
        min_size = int(100 * self.dpi_scale)
        self.setMinimumSize(min_size, min_size)
    
    def set_hue(self, hue, emit_signal=True, is_preview=False):
        """
        设置色相
        
        Args:
            hue (int): 色相值 (0-360)
            emit_signal (bool): 是否发出信号
            is_preview (bool): 是否为预览更新（拖动过程中）
        """
        new_hue = hue % 360
        if new_hue < 0:
            new_hue += 360
        if self._hue != new_hue:
            self._hue = new_hue
            self.update()
            if emit_signal:
                if is_preview:
                    self.huePreviewChanged.emit(self._hue)
                else:
                    self.hueChanged.emit(self._hue)
    
    def get_hue(self):
        """
        获取当前色相
        
        Returns:
            int: 当前色相值
        """
        return self._hue
    
    def enterEvent(self, event):
        """鼠标进入事件"""
        self._is_hovered = True
        self.update()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self._is_hovered = False
        self.update()
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self._is_pressed = True
            self._update_hue_from_pos(event.pos(), emit_signal=True, is_preview=True)
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self._is_pressed:
            self._update_hue_from_pos(event.pos(), emit_signal=True, is_preview=True)
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton and self._is_pressed:
            self._is_pressed = False
            self.set_hue(self._hue, emit_signal=True, is_preview=False)
            self.hueSelected.emit(self._hue)
    
    def _update_hue_from_pos(self, pos, emit_signal=True, is_preview=False):
        """根据鼠标位置更新色相
        
        Args:
            pos: 鼠标位置
            emit_signal: 是否发出信号
            is_preview: 是否为预览更新（拖动过程中）
        """
        center_x = self.width() / 2
        center_y = self.height() / 2
        
        dx = pos.x() - center_x
        dy = pos.y() - center_y
        
        angle = math.atan2(dy, dx)
        hue = int(math.degrees(angle))
        
        self.set_hue(hue, emit_signal=emit_signal, is_preview=is_preview)
    
    def paintEvent(self, event):
        """绘制色相环选择器"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(center_x, center_y) - self._wheel_margin
        
        self._draw_color_ring(painter, center_x, center_y, radius)
        self._draw_selector(painter, center_x, center_y, radius)
    
    def _draw_color_ring(self, painter, center_x, center_y, radius):
        """绘制色相环"""
        outer_radius = radius
        inner_radius = radius - self._wheel_width
        
        hue_gradient = QConicalGradient(center_x, center_y, -90)
        for i in range(0, 360, 30):
            hue_gradient.setColorAt(i / 360.0, QColor.fromHsl(i, 255, 128))
        hue_gradient.setColorAt(1.0, QColor.fromHsl(0, 255, 128))
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(hue_gradient))
        painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(outer_radius), int(outer_radius))
        
        app = QApplication.instance()
        bg_color = QColor(255, 255, 255)
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            base_color_str = settings_manager.get_setting("appearance.colors.base_color", "#ffffff")
            bg_color = QColor(base_color_str)
        
        hue_for_color = self._hue % 360
        if hue_for_color < 0:
            hue_for_color += 360
        current_color = QColor.fromHsl(hue_for_color, 255, 128)
        
        border_width = int(3 * self.dpi_scale)
        
        painter.setPen(QPen(bg_color, border_width))
        painter.setBrush(QBrush(current_color))
        painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(inner_radius), int(inner_radius))
    
    def _draw_selector(self, painter, center_x, center_y, radius):
        """绘制选择指示器"""
        ring_radius = radius - self._wheel_width / 2
        angle = math.radians(self._hue)
        
        handle_x = center_x + math.cos(angle) * ring_radius
        handle_y = center_y + math.sin(angle) * ring_radius
        
        hue_for_color = self._hue % 360
        if hue_for_color < 0:
            hue_for_color += 360
        current_color = QColor.fromHsl(hue_for_color, 255, 128)
        
        border_width = int(2 * self.dpi_scale)
        if self._is_hovered or self._is_pressed:
            border_width = int(3 * self.dpi_scale)
        
        painter.setPen(QPen(QColor(255, 255, 255), border_width))
        painter.setBrush(QBrush(current_color))
        painter.drawEllipse(QPoint(int(handle_x), int(handle_y)), self._handle_radius, self._handle_radius)
        
        inner_radius = self._handle_radius - border_width
        if inner_radius > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 100)))
            painter.drawEllipse(QPoint(int(handle_x), int(handle_y)), inner_radius, inner_radius)
    
    def sizeHint(self):
        """返回建议的大小"""
        return QSize(int(100 * self.dpi_scale), int(100 * self.dpi_scale))


class ColorPreview(QWidget):
    """
    颜色预览组件
    显示当前选择的颜色
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self._color = QColor(0, 0, 0)
        self._setup_size()
        
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")
    
    def _setup_size(self):
        """设置尺寸参数"""
        min_size = int(40 * self.dpi_scale)
        self.setMinimumSize(min_size, min_size)
        self.setMaximumSize(min_size, min_size)
    
    def set_color(self, color):
        """
        设置预览颜色
        
        Args:
            color (QColor): 要显示的颜色
        """
        if self._color != color:
            self._color = color
            self.update()
    
    def get_color(self):
        """
        获取当前预览颜色
        
        Returns:
            QColor: 当前预览的颜色
        """
        return self._color
    
    def paintEvent(self, event):
        """绘制颜色预览"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(center_x, center_y) - int(2 * self.dpi_scale)
        
        app = QApplication.instance()
        bg_color = QColor(255, 255, 255)
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            base_color_str = settings_manager.get_setting("appearance.colors.base_color", "#ffffff")
            bg_color = QColor(base_color_str)
        
        border_width = int(3 * self.dpi_scale)
        painter.setPen(QPen(bg_color, border_width))
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QPoint(int(center_x), int(center_y)), int(radius), int(radius))


class ColorWheelPickerWidget(QWidget):
    """
    完整的颜色选择器组件
    包含色相选择、饱和度调节、亮度调节和颜色预览
    """
    
    colorChanged = Signal(QColor)
    colorSelected = Signal(QColor)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self._hue = 0
        self._saturation = 255
        self._lightness = 128
        
        self._initial_hue = self._hue
        self._initial_saturation = self._saturation
        self._initial_lightness = self._lightness
        
        self._init_ui()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化UI组件 - 横向布局"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(int(8 * self.dpi_scale), int(8 * self.dpi_scale), 
                                  int(8 * self.dpi_scale), int(8 * self.dpi_scale))
        layout.setSpacing(int(12 * self.dpi_scale))
        
        wheel_layout = QVBoxLayout()
        wheel_layout.setAlignment(Qt.AlignCenter)
        
        self._color_wheel = ColorWheelPicker()
        wheel_layout.addWidget(self._color_wheel)
        
        layout.addLayout(wheel_layout)
        
        preview_layout = QVBoxLayout()
        preview_layout.setAlignment(Qt.AlignCenter)
        preview_layout.setSpacing(int(8 * self.dpi_scale))
        
        self._color_preview = ColorPreview()
        preview_layout.addWidget(self._color_preview)
        
        layout.addLayout(preview_layout)
        
        right_layout = QVBoxLayout()
        right_layout.setSpacing(int(6 * self.dpi_scale))
        
        saturation_layout = QVBoxLayout()
        saturation_layout.setSpacing(int(2 * self.dpi_scale))
        
        saturation_label = QLabel("饱和度")
        saturation_label.setAlignment(Qt.AlignLeft)
        saturation_layout.addWidget(saturation_label)
        
        self._saturation_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal)
        self._saturation_bar.setRange(0, 255)
        self._saturation_bar.setValue(255)
        saturation_layout.addWidget(self._saturation_bar)
        
        right_layout.addLayout(saturation_layout)
        
        lightness_layout = QVBoxLayout()
        lightness_layout.setSpacing(int(2 * self.dpi_scale))
        
        lightness_label = QLabel("亮度")
        lightness_label.setAlignment(Qt.AlignLeft)
        lightness_layout.addWidget(lightness_label)
        
        self._lightness_bar = D_ProgressBar(orientation=D_ProgressBar.Horizontal)
        self._lightness_bar.setRange(0, 255)
        self._lightness_bar.setValue(128)
        lightness_layout.addWidget(self._lightness_bar)
        
        right_layout.addLayout(lightness_layout)
        
        bottom_row_layout = QHBoxLayout()
        bottom_row_layout.setSpacing(int(8 * self.dpi_scale))
        
        self._color_label = QLabel("#000000")
        self._color_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        bottom_row_layout.addWidget(self._color_label)
        
        bottom_row_layout.addStretch()
        
        self._cancel_button = QPushButton("取消")
        self._cancel_button.setMinimumWidth(int(60 * self.dpi_scale))
        bottom_row_layout.addWidget(self._cancel_button)
        
        self._apply_button = QPushButton("应用")
        self._apply_button.setMinimumWidth(int(60 * self.dpi_scale))
        bottom_row_layout.addWidget(self._apply_button)
        
        right_layout.addLayout(bottom_row_layout)
        
        layout.addLayout(right_layout)
        
        self._update_gradient_colors()
    
    def _connect_signals(self):
        """连接信号"""
        self._color_wheel.hueChanged.connect(self._on_hue_changed)
        self._color_wheel.huePreviewChanged.connect(self._on_hue_preview_changed)
        self._color_wheel.hueSelected.connect(self._on_hue_selected)
        self._saturation_bar.valueChanged.connect(self._on_saturation_changed)
        self._lightness_bar.valueChanged.connect(self._on_lightness_changed)
        
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        self._apply_button.clicked.connect(self._on_apply_clicked)
    
    def _on_hue_preview_changed(self, hue):
        """色相预览变化处理 - 拖动过程中仅更新UI预览，不发送colorChanged信号"""
        self._hue = hue
        self._update_gradient_colors()
        self._update_color_preview()
    
    def _on_hue_changed(self, hue):
        """色相最终变化处理 - 发送colorChanged信号"""
        self._hue = hue
        self._update_gradient_colors()
        self._update_color_preview()
        self.colorChanged.emit(self.get_color())
    
    def _on_hue_selected(self, hue):
        """色相选择完成处理"""
        self._hue = hue
        self._update_gradient_colors()
        self._update_color_preview()
        self.colorChanged.emit(self.get_color())
        self.colorSelected.emit(self.get_color())
    
    def _on_saturation_changed(self, value):
        """饱和度变化处理"""
        self._saturation = value
        self._update_color_preview()
        self.colorChanged.emit(self.get_color())
    
    def _on_lightness_changed(self, value):
        """亮度变化处理"""
        self._lightness = value
        self._update_color_preview()
        self.colorChanged.emit(self.get_color())
    
    def _update_gradient_colors(self):
        """更新进度条的渐变色"""
        hue_for_color = self._hue % 360
        if hue_for_color < 0:
            hue_for_color += 360
        current_hue_color = QColor.fromHsl(hue_for_color, 255, 128)
        gray_color = QColor.fromHsl(hue_for_color, 0, 128)
        transparent_color = QColor(0, 0, 0, 0)
        
        self._saturation_bar.set_gradient_mode(True)
        self._saturation_bar.set_bg_gradient_colors([transparent_color, current_hue_color])
        
        black_color = QColor(0, 0, 0)
        white_color = QColor(255, 255, 255)
        self._lightness_bar.set_gradient_mode(True)
        self._lightness_bar.set_bg_gradient_colors([transparent_color, current_hue_color, white_color])
    
    def _update_color_preview(self):
        """更新颜色预览"""
        color = self.get_color()
        self._color_preview.set_color(color)
        self._color_label.setText(self.get_hex())
    
    def set_color(self, color):
        """
        设置当前颜色
        
        Args:
            color (QColor): 要设置的颜色
        """
        if color.isValid():
            h = color.hue()
            s = color.saturation()
            l = color.lightness()
            if h < 0:
                h = 0
            self._hue = h
            self._saturation = s
            self._lightness = l
            
            self._initial_hue = h
            self._initial_saturation = s
            self._initial_lightness = l
            
            self._color_wheel.set_hue(h)
            self._saturation_bar.setValue(s)
            self._lightness_bar.setValue(l)
            
            self._update_gradient_colors()
            self._update_color_preview()
            self.colorChanged.emit(self.get_color())
    
    def _on_cancel_clicked(self):
        """取消按钮点击处理 - 恢复到初始颜色"""
        self._hue = self._initial_hue
        self._saturation = self._initial_saturation
        self._lightness = self._initial_lightness
        
        self._color_wheel.set_hue(self._initial_hue)
        self._saturation_bar.setValue(self._initial_saturation)
        self._lightness_bar.setValue(self._initial_lightness)
        
        self._update_gradient_colors()
        self._update_color_preview()
        self.colorChanged.emit(self.get_color())
    
    def _on_apply_clicked(self):
        """应用按钮点击处理 - 确认当前选择并更新初始值"""
        self._initial_hue = self._hue
        self._initial_saturation = self._saturation
        self._initial_lightness = self._lightness
        
        self.colorSelected.emit(self.get_color())
    
    def get_color(self):
        """
        获取当前颜色
        
        Returns:
            QColor: 当前选择的颜色
        """
        return QColor.fromHsl(self._hue, self._saturation, self._lightness)
    
    def get_rgb(self):
        """
        获取RGB颜色值
        
        Returns:
            tuple: (r, g, b)
        """
        color = self.get_color()
        return (color.red(), color.green(), color.blue())
    
    def get_hsv(self):
        """
        获取HSV颜色值
        
        Returns:
            tuple: (h, s, v)
        """
        color = self.get_color()
        h, s, v, _ = color.getHsv()
        return (h, s, v)
    
    def get_hsl(self):
        """
        获取HSL颜色值
        
        Returns:
            tuple: (h, s, l)
        """
        return (self._hue, self._saturation, self._lightness)
    
    def get_hex(self):
        """
        获取十六进制颜色值
        
        Returns:
            str: 十六进制颜色字符串，例如 "#RRGGBB"
        """
        return self.get_color().name()
    
    def set_hue(self, hue):
        """
        设置色相
        
        Args:
            hue (int): 色相值 (0-360)
        """
        self._color_wheel.set_hue(hue)
    
    def set_saturation(self, saturation):
        """
        设置饱和度
        
        Args:
            saturation (int): 饱和度值 (0-255)
        """
        self._saturation_bar.setValue(saturation)
    
    def set_lightness(self, lightness):
        """
        设置亮度
        
        Args:
            lightness (int): 亮度值 (0-255)
        """
        self._lightness_bar.setValue(lightness)
    
    def get_hue(self):
        """
        获取当前色相
        
        Returns:
            int: 色相值
        """
        return self._hue
    
    def get_saturation(self):
        """
        获取当前饱和度
        
        Returns:
            int: 饱和度值
        """
        return self._saturation
    
    def get_lightness(self):
        """
        获取当前亮度
        
        Returns:
            int: 亮度值
        """
        return self._lightness


class D_ColorWheelPickerMenu(D_HoverMenu):
    """
    使用 D_HoverMenu 包装的颜色选择器菜单
    直接继承自 D_HoverMenu，避免包装层问题
    """
    
    colorChanged = Signal(QColor)
    colorSelected = Signal(QColor)
    
    def __init__(self, parent=None, position="bottom", stay_on_top=True):
        """
        初始化颜色选择器菜单
        
        Args:
            parent: 父窗口部件
            position: 初始弹出位置
            stay_on_top: 是否保持在顶层
        """
        super().__init__(parent, position=position, stay_on_top=stay_on_top)
        
        self._color_picker = ColorWheelPickerWidget()
        self.set_content(self._color_picker)
        self.set_timeout_enabled(False)
        
        self._connect_signals()
    
    def _connect_signals(self):
        """连接信号"""
        self._color_picker.colorChanged.connect(self.colorChanged.emit)
        self._color_picker.colorSelected.connect(self.colorSelected.emit)
    
    def set_color(self, color):
        """
        设置当前颜色
        
        Args:
            color (QColor): 要设置的颜色
        """
        self._color_picker.set_color(color)
    
    def get_color(self):
        """
        获取当前颜色
        
        Returns:
            QColor: 当前选择的颜色
        """
        return self._color_picker.get_color()
    
    def get_rgb(self):
        """
        获取RGB颜色值
        
        Returns:
            tuple: (r, g, b)
        """
        return self._color_picker.get_rgb()
    
    def get_hsv(self):
        """
        获取HSV颜色值
        
        Returns:
            tuple: (h, s, v)
        """
        return self._color_picker.get_hsv()
    
    def get_hsl(self):
        """
        获取HSL颜色值
        
        Returns:
            tuple: (h, s, l)
        """
        return self._color_picker.get_hsl()
    
    def get_hex(self):
        """
        获取十六进制颜色值
        
        Returns:
            str: 十六进制颜色字符串
        """
        return self._color_picker.get_hex()
    
    def get_color_picker(self):
        """
        获取内部的颜色选择器实例
        
        Returns:
            ColorWheelPickerWidget: 颜色选择器实例
        """
        return self._color_picker
