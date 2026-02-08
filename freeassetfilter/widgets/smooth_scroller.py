# -*- coding: utf-8 -*-
"""
FreeAssetFilter 滚动条组件
带悬停动画效果和平滑滚动的滚动条
"""

from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QObject, QPropertyAnimation, pyqtProperty, QEasingCurve
from PyQt5.QtWidgets import QScrollArea, QAbstractItemView, QScroller, QScrollerProperties, QApplication, QScrollBar
from PyQt5.QtGui import QColor, QWheelEvent
import time


class D_ScrollBar(QScrollBar):
    """
    带悬停动画效果和平滑滚动的滚动条
    
    特点：
    - 滑块悬停时平滑变色
    - 支持强调色和次选色方案
    - 支持垂直和水平方向
    - 支持非线性动画过渡效果
    - 支持触摸惯性滚动
    - 支持滚轮平滑滚动
    """
    
    scroll_finished = pyqtSignal()
    
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
        self._init_smooth_scroll()
        
        self.setAttribute(Qt.WA_Hover, True)
    
    def _init_animations(self):
        """初始化颜色动画"""
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
    
    def _init_smooth_scroll(self):
        """初始化平滑滚动"""
        self._velocity = 0
        self._friction = 0.88
        self._min_velocity = 0.5
        self._is_scrolling = False
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._on_scroll_animation_tick)
        self._last_wheel_time = 0
        self._wheel_speed_boost = 1.0
        self._max_boost = 3.0
    
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
            }}
            QScrollBar::{"handle:" + ("vertical" if is_vertical else "horizontal")}:pressed {{
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
    
    def _get_anim_handle_color(self):
        return self._anim_handle_color_value
    
    def _set_anim_handle_color(self, color):
        self._anim_handle_color_value = QColor(color)
        self._update_style()
    
    _anim_handle_color = pyqtProperty(QColor, fget=_get_anim_handle_color, fset=_set_anim_handle_color)
    
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
    
    def wheelEvent(self, event):
        """滚轮事件 - 平滑滚动，Ctrl+滚轮时交给父控件处理缩放"""
        # 当按下Ctrl时，不处理滚轮事件，让事件向上传播以支持缩放
        if event.modifiers() == Qt.ControlModifier:
            super().wheelEvent(event)
            return

        angle_delta = event.angleDelta().y()

        if angle_delta != 0:
            current_time = time.time()
            time_diff = current_time - self._last_wheel_time

            if time_diff < 0.1:
                self._wheel_speed_boost = min(self._wheel_speed_boost + 0.3, self._max_boost)
            else:
                self._wheel_speed_boost = 1.0

            self._last_wheel_time = current_time

            pixel_delta = -angle_delta // 9 * self._wheel_speed_boost

            if self._animation_timer.isActive():
                self._velocity = pixel_delta
            else:
                self._velocity = pixel_delta
                self._start_scroll_animation()

            event.accept()
        else:
            super().wheelEvent(event)
    
    def _start_scroll_animation(self):
        """开始惯性滚动动画"""
        self._is_scrolling = True
        self._wheel_speed_boost = 1.0
        self._animation_timer.start()
    
    def _on_scroll_animation_tick(self):
        """滚动动画每帧更新"""
        if not self._is_scrolling:
            return
        
        self._velocity *= self._friction
        
        if abs(self._velocity) < self._min_velocity:
            self._animation_timer.stop()
            self._is_scrolling = False
            self.scroll_finished.emit()
            return
        
        new_value = self.value() + self._velocity
        
        max_val = self.maximum()
        min_val = self.minimum()
        
        new_value = max(min_val, min(max_val, new_value))
        
        self.setValue(int(new_value))
    
    def set_friction(self, friction):
        """
        设置摩擦力系数
        
        Args:
            friction: 摩擦力 (0.0-1.0)，越大停止越慢
        """
        self._friction = max(0.0, min(1.0, friction))


def _get_target_widget(widget):
    """
    获取需要抓取手势的目标控件
    """
    if isinstance(widget, QScrollArea):
        return widget.viewport()
    return widget


class SmoothScroller:
    """
    平滑滚动管理器
    为控件添加触摸惯性滚动效果
    """
    
    @staticmethod
    def apply(widget, gesture_type=QScroller.TouchGesture):
        """
        为控件应用触摸惯性滚动
        
        Args:
            widget: 要应用平滑滚动的控件
            gesture_type: 手势类型
        """
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)
        
        properties = scroller.scrollerProperties()
        
        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 1.0)
        properties.setScrollMetric(QScrollerProperties.OvershootDragDistanceFactor, 0.0)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 0)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.8)
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.6)
        
        scroller.setScrollerProperties(properties)
        
        return scroller
    
    @staticmethod
    def apply_to_scroll_area(scroll_area, gesture_type=QScroller.TouchGesture):
        """
        为 QScrollArea 应用平滑滚动
        
        Args:
            scroll_area: QScrollArea 实例
            gesture_type: 手势类型
        """
        if not isinstance(scroll_area, QScrollArea):
            return None
        
        SmoothScroller._configure_scroll_area(scroll_area)
        SmoothScroller.apply(scroll_area, gesture_type)
        
        return scroll_area
    
    @staticmethod
    def _configure_scroll_area(scroll_area):
        """配置像素级滚动模式"""
        if isinstance(scroll_area, QAbstractItemView):
            scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    
    @staticmethod
    def apply_ios_style(widget, gesture_type=QScroller.TouchGesture):
        """应用 iOS 风格滚动"""
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)
        
        properties = scroller.scrollerProperties()
        
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.9)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.5)
        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 1.0)
        properties.setScrollMetric(QScrollerProperties.OvershootDragDistanceFactor, 0.0)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 0)
        
        scroller.setScrollerProperties(properties)
        
        return scroller
    
    @staticmethod
    def apply_quick_style(widget, gesture_type=QScroller.TouchGesture):
        """应用快速响应风格滚动"""
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)
        
        properties = scroller.scrollerProperties()
        
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.4)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.9)
        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 1.0)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 0)
        
        scroller.setScrollerProperties(properties)
        
        return scroller
    
    @staticmethod
    def enable_vertical_only(widget):
        """只启用垂直滚动"""
        if isinstance(widget, QScrollArea):
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
