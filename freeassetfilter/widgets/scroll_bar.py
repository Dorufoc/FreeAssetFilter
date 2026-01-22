#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 动画滚动条组件
带悬停动画效果的滚动条
"""

from PyQt5.QtWidgets import QScrollBar, QAbstractItemView, QScroller, QScrollerProperties
from PyQt5.QtCore import Qt, QPropertyAnimation, pyqtProperty, QEasingCurve
from PyQt5.QtGui import QColor

from freeassetfilter.widgets.smooth_scroller import SmoothScroller


class D_ScrollBar(QScrollBar):
    """
    带悬停动画效果的滚动条
    
    特点：
    - 滑块悬停时平滑变色
    - 支持强调色和次选色方案
    - 支持垂直和水平方向
    - 支持非线性动画过渡效果
    """
    
    def __init__(self, parent=None, orientation=Qt.Vertical):
        """
        初始化动画滚动条
        
        Args:
            parent: 父控件
            orientation: 滚动条方向，Qt.Vertical 或 Qt.Horizontal
        """
        super().__init__(orientation, parent)
        
        self._dpi_scale = 1.0
        self._is_hovering = False
        self._is_pressed = False
        
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            self._dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self._normal_color = QColor("#e0e0e0")
        self._hover_color = QColor("#333333")
        self._pressed_color = QColor("#007AFF")
        self._auxiliary_color = QColor("#f1f3f3")
        
        self._anim_handle_color_value = QColor(self._normal_color)
        self._updating_style = False
        
        self._init_animations()
        self._update_style()
        
        self.setAttribute(Qt.WA_Hover, True)
    
    def _init_animations(self):
        """初始化动画"""
        self._hover_anim = QPropertyAnimation(self, b"_anim_handle_color")
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self._leave_anim = QPropertyAnimation(self, b"_anim_handle_color")
        self._leave_anim.setDuration(200)
        self._leave_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._press_anim = QPropertyAnimation(self, b"_anim_handle_color")
        self._press_anim.setDuration(100)
        self._press_anim.setEasingCurve(QEasingCurve.OutQuad)
        
        self._release_anim = QPropertyAnimation(self, b"_anim_handle_color")
        self._release_anim.setDuration(150)
        self._release_anim.setEasingCurve(QEasingCurve.InOutQuad)
    
    def set_colors(self, normal_color, hover_color, pressed_color, auxiliary_color=None):
        """
        设置滚动条颜色
        
        Args:
            normal_color: 正常状态颜色
            hover_color: 悬停状态颜色
            pressed_color: 按下状态颜色
            auxiliary_color: 背景颜色（可选）
        """
        self._normal_color = QColor(normal_color) if isinstance(normal_color, str) else QColor(*normal_color)
        self._hover_color = QColor(hover_color) if isinstance(hover_color, str) else QColor(*hover_color)
        self._pressed_color = QColor(pressed_color) if isinstance(pressed_color, str) else QColor(*pressed_color)
        
        if auxiliary_color:
            self._auxiliary_color = QColor(auxiliary_color) if isinstance(auxiliary_color, str) else QColor(*auxiliary_color)
        
        if not self._is_hovering and not self._is_pressed:
            self._anim_handle_color_value = QColor(self._normal_color)
        
        self._update_style()
    
    def apply_theme_from_settings(self, settings_manager=None, prefix="appearance.colors."):
        """
        从设置管理器应用主题颜色
        
        Args:
            settings_manager: 设置管理器实例，如果为None则从应用获取
            prefix: 设置键前缀，默认 "appearance.colors."
        """
        from PyQt5.QtWidgets import QApplication
        
        app = QApplication.instance()
        if settings_manager is None:
            if hasattr(app, 'settings_manager'):
                settings_manager = app.settings_manager
            else:
                return
        
        normal_color = settings_manager.get_setting(f"{prefix}normal_color", "#e0e0e0")
        hover_color = settings_manager.get_setting(f"{prefix}secondary_color", "#333333")
        pressed_color = settings_manager.get_setting(f"{prefix}accent_color", "#007AFF")
        auxiliary_color = settings_manager.get_setting(f"{prefix}auxiliary_color", "#f1f3f3")
        
        self.set_colors(normal_color, hover_color, pressed_color, auxiliary_color)
    
    def _update_style(self):
        """更新样式表"""
        if self._updating_style:
            return
        
        self._updating_style = True
        
        is_vertical = self.orientation() == Qt.Vertical
        width = int(4 * self._dpi_scale)
        radius = int(2 * self._dpi_scale)
        min_size = int(15 * self._dpi_scale)
        
        if is_vertical:
            size_dim = "height"
            min_dim = f"min-{size_dim}"
            other_size = "width"
        else:
            size_dim = "width"
            min_dim = f"min-{size_dim}"
            other_size = "height"
        
        color = self._anim_handle_color_value
        r, g, b = color.red(), color.green(), color.blue()
        handle_color = f"rgba({r}, {g}, {b}, 255)"
        
        bg_r, bg_g, bg_b = self._auxiliary_color.red(), self._auxiliary_color.green(), self._auxiliary_color.blue()
        bg_color = f"rgba({bg_r}, {bg_g}, {bg_b}, 255)"
        
        style = f"""
            QScrollBar:{("vertical" if is_vertical else "horizontal")} {{
                {other_size}: {width}px;
                background-color: {bg_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::{"handle:" + ("vertical" if is_vertical else "horizontal")} {{
                background-color: {handle_color};
                {min_dim}: {min_size}px;
                border-radius: {radius}px;
                border: none;
            }}
            QScrollBar::{"handle:" + ("vertical" if is_vertical else "horizontal")}:hover {{
                /* 由动画控制 */
            }}
            QScrollBar::{"handle:" + ("vertical" if is_vertical else "horizontal")}:pressed {{
                /* 由动画控制 */
            }}
            QScrollBar::add-line:{("vertical" if is_vertical else "horizontal")},
            QScrollBar::sub-line:{("vertical" if is_vertical else "horizontal")} {{
                {size_dim}: 0px;
                border: none;
            }}
            QScrollBar::add-page:{("vertical" if is_vertical else "horizontal")},
            QScrollBar::sub-page:{("vertical" if is_vertical else "horizontal")} {{
                background: none;
                border: 0px solid transparent;
                border: none;
            }}
        """
        self.setStyleSheet(style)
        
        self._updating_style = False
    
    def enterEvent(self, event):
        """鼠标进入事件"""
        self._is_hovering = True
        
        if self._is_pressed:
            target_color = self._pressed_color
        else:
            target_color = self._hover_color
        
        self._leave_anim.stop()
        self._anim_handle_color_value = QColor(self._anim_handle_color_value)
        self._hover_anim.setStartValue(QColor(self._anim_handle_color_value))
        self._hover_anim.setEndValue(QColor(target_color))
        self._hover_anim.start()
        
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self._is_hovering = False
        
        if not self._is_pressed:
            self._hover_anim.stop()
            self._anim_handle_color_value = QColor(self._anim_handle_color_value)
            self._leave_anim.setStartValue(QColor(self._anim_handle_color_value))
            self._leave_anim.setEndValue(QColor(self._normal_color))
            self._leave_anim.start()
        
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        self._is_pressed = True
        
        self._hover_anim.stop()
        self._anim_handle_color_value = QColor(self._anim_handle_color_value)
        self._press_anim.setStartValue(QColor(self._anim_handle_color_value))
        self._press_anim.setEndValue(QColor(self._pressed_color))
        self._press_anim.start()
        
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self._is_pressed = False
        
        self._press_anim.stop()
        self._anim_handle_color_value = QColor(self._anim_handle_color_value)
        
        if self._is_hovering:
            self._release_anim.setStartValue(QColor(self._anim_handle_color_value))
            self._release_anim.setEndValue(QColor(self._hover_color))
        else:
            self._release_anim.setStartValue(QColor(self._anim_handle_color_value))
            self._release_anim.setEndValue(QColor(self._normal_color))
        
        self._release_anim.start()
        
        super().mouseReleaseEvent(event)
    
    def _get_anim_handle_color(self):
        return self._anim_handle_color_value
    
    def _set_anim_handle_color(self, color):
        self._anim_handle_color_value = QColor(color)
        self._update_style()
    
    _anim_handle_color = pyqtProperty(QColor, _get_anim_handle_color, _set_anim_handle_color)
