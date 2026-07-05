# -*- coding: utf-8 -*-
"""
FreeAssetFilter 平滑滚动组件
提供平滑滚轮滚动和边界弹性回弹效果
"""

import weakref

from PySide6.QtCore import (
    Qt,
    QObject,
    QPropertyAnimation,
    Property,
    QEasingCurve,
    QEvent,
    QPoint,
)
from PySide6.QtWidgets import (
    QScrollArea,
    QAbstractItemView,
    QScroller,
    QScrollerProperties,
    QApplication,
    QGraphicsEffect,
    QScrollBar,
)
from PySide6.QtGui import QWheelEvent, QColor
from freeassetfilter.utils.animation_settings import is_animation_enabled
import time


def _calculate_damped_elastic_offset(current_offset, previous_target_offset, direction, strength, minimum_strength, limit):
    direction = -1.0 if direction < 0 else 1.0
    current_abs = abs(float(current_offset)) if current_offset * direction > 0 else 0.0
    previous_target_abs = abs(float(previous_target_offset)) if previous_target_offset * direction > 0 else 0.0
    base_abs = min(float(limit), max(current_abs, previous_target_abs))
    if base_abs >= limit:
        return direction * float(limit)

    raw_strength = max(float(minimum_strength), float(strength))
    remaining_ratio = max(0.0, (float(limit) - base_abs) / float(limit))
    elastic_factor = max(0.08, remaining_ratio * remaining_ratio)
    target_abs = min(float(limit), base_abs + raw_strength * elastic_factor)
    return direction * target_abs


def _get_target_widget(widget):
    """
    获取需要抓取手势和监听滚轮的目标控件
    """
    if isinstance(widget, QScrollArea):
        return widget.viewport()
    if hasattr(widget, "viewport"):
        return widget.viewport()
    return widget


class _ContentOverscrollEffect(QGraphicsEffect):
    """
    只在边界回弹期间临时平移目标控件的绘制结果，不改变真实滚动值或布局。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = QPoint(0, 0)

    def set_offset(self, x=0.0, y=0.0):
        new_offset = QPoint(int(round(x)), int(round(y)))
        if new_offset == self._offset:
            return
        self._offset = new_offset
        self.update()

    @staticmethod
    def _split_source_pixmap_result(source_pixmap_result):
        if isinstance(source_pixmap_result, tuple):
            return source_pixmap_result
        return source_pixmap_result, QPoint(0, 0)

    def draw(self, painter):
        pixmap, source_offset = self._split_source_pixmap_result(
            self.sourcePixmap(Qt.LogicalCoordinates)
        )
        if pixmap.isNull():
            return
        painter.drawPixmap(source_offset + self._offset, pixmap)


class _ElasticContentOverscrollController(QObject):
    """
    管理滚动内容本身的边界弹性位移。
    """

    def __init__(self, target_widget, duration=380, dpi_scale=None):
        super().__init__(target_widget)
        self._target_widget = target_widget
        self._dpi_scale = 1.0
        self._offset_value = 0.0
        self._target_offset_value = 0.0
        self._orientation = Qt.Vertical
        self._effect = None

        if dpi_scale is not None:
            self._dpi_scale = dpi_scale
        else:
            app = QApplication.instance()
            if app:
                self._dpi_scale = getattr(app, "dpi_scale_factor", 1.0)

        self._animation = QPropertyAnimation(self, b"_offset")
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.finished.connect(self._release_effect_if_idle)

    def _get_offset(self):
        return self._offset_value

    def _set_offset(self, offset):
        new_offset = float(offset)
        if abs(new_offset) < 0.01:
            new_offset = 0.0
        if new_offset != 0.0 and abs(new_offset - self._offset_value) < 0.25:
            return

        self._offset_value = new_offset
        if self._ensure_effect():
            if self._orientation == Qt.Vertical:
                self._effect.set_offset(0.0, self._offset_value)
            else:
                self._effect.set_offset(self._offset_value, 0.0)

    _offset = Property(float, fget=_get_offset, fset=_set_offset)

    def _ensure_effect(self):
        if self._target_widget is None:
            return False

        current_effect = self._target_widget.graphicsEffect()
        if current_effect is not None and current_effect is not self._effect:
            return False

        if self._effect is None:
            self._effect = _ContentOverscrollEffect(self._target_widget)

        if current_effect is None:
            self._target_widget.setGraphicsEffect(self._effect)

        return True

    def _release_effect_if_idle(self):
        if abs(self._offset_value) >= 0.01:
            return
        self._target_offset_value = 0.0
        if self._target_widget and self._target_widget.graphicsEffect() is self._effect:
            self._target_widget.setGraphicsEffect(None)
        self._effect = None

    def _get_overscroll_limit(self, orientation):
        if self._target_widget is None:
            return 0.0

        rect = self._target_widget.rect()
        if rect.isEmpty():
            return 0.0

        available_length = rect.height() if orientation == Qt.Vertical else rect.width()
        if available_length <= 0:
            return 0.0

        return max(6.0 * self._dpi_scale, min(34.0 * self._dpi_scale, available_length * 0.10))

    def reset(self):
        self._animation.stop()
        self._target_offset_value = 0.0
        self._offset_value = 0.0
        if self._effect is not None:
            self._effect.set_offset(0.0, 0.0)
        if self._target_widget and self._target_widget.graphicsEffect() is self._effect:
            self._target_widget.setGraphicsEffect(None)
        self._effect = None

    def trigger(self, orientation, boundary_direction, strength=1.0):
        """
        boundary_direction: -1 表示顶端/左端，1 表示底端/右端。
        内容需要朝相反方向位移，形成被拉出边界后的回弹感。
        """
        if not is_animation_enabled("smooth_scrolling", default=True):
            self.reset()
            return False

        limit = self._get_overscroll_limit(orientation)
        if limit <= 0:
            return False

        self._orientation = orientation
        direction = -1.0 if boundary_direction < 0 else 1.0
        target_offset = _calculate_damped_elastic_offset(
            self._offset_value,
            self._target_offset_value,
            -direction,
            strength,
            6.0 * self._dpi_scale,
            limit,
        )
        self._target_offset_value = target_offset

        if not self._ensure_effect():
            return False

        self._animation.stop()
        self._animation.setStartValue(self._offset_value)
        self._animation.setKeyValueAt(0.36, target_offset)
        self._animation.setEndValue(0.0)
        self._animation.start()
        return True


class _WheelSmoothScrollFilter(QObject):
    """
    统一处理鼠标滚轮 / 触控板滚轮平滑动画。
    使用 Qt 属性动画驱动 scrollbar.value，避免 Python 16ms 定时循环。
    """

    def __init__(self, host_widget, target_widget, duration=140):
        super().__init__(target_widget)
        self._host_widget = host_widget
        self._target_widget = target_widget
        self._duration = duration
        self._vertical_animation = None
        self._horizontal_animation = None
        self._pending_vertical_target = None
        self._pending_horizontal_target = None
        self._last_wheel_time = 0.0
        self._wheel_boost = 1.0
        self._max_wheel_boost = 2.5
        self._content_overscroll = _ElasticContentOverscrollController(target_widget)

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel:
            return super().eventFilter(obj, event)

        wheel_event = event if isinstance(event, QWheelEvent) else None
        if wheel_event is None:
            return super().eventFilter(obj, event)

        if wheel_event.modifiers() & Qt.ControlModifier:
            return False

        if self._handle_wheel_event(wheel_event):
            event.accept()
            return True

        return False

    def _handle_wheel_event(self, event):
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()

        has_pixel_delta = not pixel_delta.isNull()

        if has_pixel_delta:
            delta_x = pixel_delta.x()
            delta_y = pixel_delta.y()
        else:
            # angleDelta 以 1/8 度为单位；保留原始数值用于传统滚轮判定
            delta_x = angle_delta.x()
            delta_y = angle_delta.y()

        if abs(delta_y) >= abs(delta_x):
            scrollbar = self._resolve_scrollbar(Qt.Vertical)
            delta = delta_y
        else:
            scrollbar = self._resolve_scrollbar(Qt.Horizontal)
            delta = delta_x

        if scrollbar is None:
            return False

        if delta == 0:
            return False

        current_value = scrollbar.value()
        step = self._normalize_delta(delta, has_pixel_delta)
        target_value = self._calculate_target_value(scrollbar, current_value, step)

        if target_value == current_value:
            if self._trigger_content_overscroll(scrollbar, current_value, step):
                return True
            return False

        if not is_animation_enabled("smooth_scrolling", default=True):
            scrollbar.setValue(int(target_value))
            setattr(
                self,
                "_pending_vertical_target" if scrollbar.orientation() == Qt.Vertical else "_pending_horizontal_target",
                None,
            )
            return True

        self._animate_scrollbar(scrollbar, target_value)
        return True

    def _trigger_content_overscroll(self, scrollbar, current_value, step):
        if not is_animation_enabled("smooth_scrolling", default=True):
            return False

        at_minimum = current_value <= scrollbar.minimum()
        at_maximum = current_value >= scrollbar.maximum()
        scrolling_past_minimum = step > 0 and at_minimum
        scrolling_past_maximum = step < 0 and at_maximum
        if not scrolling_past_minimum and not scrolling_past_maximum:
            return False

        direction = -1 if scrolling_past_minimum else 1
        self._content_overscroll.trigger(scrollbar.orientation(), direction, strength=abs(step) * 0.55)
        return True

    def _normalize_delta(self, delta, is_pixel_delta):
        current_time = time.time()
        time_diff = current_time - self._last_wheel_time
        if time_diff < 0.10:
            self._wheel_boost = min(self._wheel_boost + 0.18, self._max_wheel_boost)
        else:
            self._wheel_boost = 1.0
        self._last_wheel_time = current_time

        if is_pixel_delta:
            # Chrome 风格更接近触控板原始位移，尽量少做额外放大
            scaled = int(delta * 1.05 * self._wheel_boost)
            if scaled == 0:
                scaled = 1 if delta > 0 else -1
            return scaled

        # 传统滚轮 angleDelta 典型单格为 ±120，直接按单格放大，
        # 这样修改基础步进系数时才会真实生效。
        scaled = int((delta / 120.0) * 4.0 * 120 * self._wheel_boost / 8.0)
        if scaled == 0:
            scaled = 1 if delta > 0 else -1
        return scaled

    def _calculate_target_value(self, scrollbar, current_value, step):
        orientation = scrollbar.orientation()
        animation_attr = "_vertical_animation" if orientation == Qt.Vertical else "_horizontal_animation"
        pending_attr = "_pending_vertical_target" if orientation == Qt.Vertical else "_pending_horizontal_target"
        animation = getattr(self, animation_attr, None)
        pending_target = getattr(self, pending_attr, None)
        minimum = scrollbar.minimum()
        maximum = scrollbar.maximum()

        if pending_target is not None:
            base_value = max(minimum, min(maximum, int(pending_target)))
        elif animation is not None and animation.state() == QPropertyAnimation.Running:
            end_value = animation.endValue()
            base_value = int(end_value) if end_value is not None else current_value
            base_value = max(minimum, min(maximum, base_value))
        else:
            base_value = current_value

        target_value = max(minimum, min(maximum, base_value - step))
        setattr(self, pending_attr, target_value)
        return target_value

    def _resolve_scrollbar(self, orientation):
        widget = self._host_widget

        if isinstance(widget, QScrollArea):
            scrollbar = (
                widget.verticalScrollBar()
                if orientation == Qt.Vertical
                else widget.horizontalScrollBar()
            )
            if scrollbar and scrollbar.maximum() > scrollbar.minimum():
                return scrollbar
            return None

        vertical_bar = getattr(widget, "verticalScrollBar", None)
        horizontal_bar = getattr(widget, "horizontalScrollBar", None)

        if orientation == Qt.Vertical and callable(vertical_bar):
            scrollbar = vertical_bar()
            if scrollbar and scrollbar.maximum() > scrollbar.minimum():
                return scrollbar

        if orientation == Qt.Horizontal and callable(horizontal_bar):
            scrollbar = horizontal_bar()
            if scrollbar and scrollbar.maximum() > scrollbar.minimum():
                return scrollbar

        return None

    def _animate_scrollbar(self, scrollbar, target_value):
        weak_self = weakref.ref(self)
        orientation = scrollbar.orientation()
        animation_attr = "_vertical_animation" if orientation == Qt.Vertical else "_horizontal_animation"
        pending_attr = "_pending_vertical_target" if orientation == Qt.Vertical else "_pending_horizontal_target"
        animation = getattr(self, animation_attr, None)

        start_value = scrollbar.value()
        if animation is not None and animation.state() == QPropertyAnimation.Running:
            start_value = animation.currentValue() if animation.currentValue() is not None else scrollbar.value()
            animation.stop()

        animation = QPropertyAnimation(scrollbar, b"value", self)
        animation.setDuration(self._duration)
        animation.setEasingCurve(QEasingCurve.OutQuad)
        animation.setStartValue(int(start_value))
        animation.setEndValue(int(target_value))
        animation.finished.connect(lambda p=pending_attr: (s := weak_self()) and setattr(s, p, None))
        setattr(self, animation_attr, animation)
        animation.start()


class SmoothScroller:
    """
    平滑滚动管理器
    为控件添加触摸惯性滚动效果
    """

    DEFAULT_PROFILE = {
        "drag_velocity_smoothing": 0.82,
        "deceleration": 0.12,
        "maximum_velocity": 0.60,
        "accelerating_flick_maximum_time": 0.22,
        "accelerating_flick_speedup_factor": 1.08,
        "overshoot_drag_resistance": 1.0,
        "overshoot_drag_distance": 0.0,
        "overshoot_scroll_distance": 0.0,
        "overshoot_scroll_time": 0.0,
        "frame_rate": QScrollerProperties.Fps60,
    }

    IOS_LIKE_PROFILE = {
        "drag_velocity_smoothing": 0.90,
        "deceleration": 0.08,
        "maximum_velocity": 0.70,
        "accelerating_flick_maximum_time": 0.25,
        "accelerating_flick_speedup_factor": 1.12,
        "overshoot_drag_resistance": 1.0,
        "overshoot_drag_distance": 0.0,
        "overshoot_scroll_distance": 0.0,
        "overshoot_scroll_time": 0.0,
        "frame_rate": QScrollerProperties.Fps60,
    }

    QUICK_PROFILE = {
        "drag_velocity_smoothing": 0.65,
        "deceleration": 0.18,
        "maximum_velocity": 0.80,
        "accelerating_flick_maximum_time": 0.18,
        "accelerating_flick_speedup_factor": 1.18,
        "overshoot_drag_resistance": 1.0,
        "overshoot_drag_distance": 0.0,
        "overshoot_scroll_distance": 0.0,
        "overshoot_scroll_time": 0.0,
        "frame_rate": QScrollerProperties.Fps60,
    }

    @staticmethod
    def apply(widget, gesture_type=QScroller.TouchGesture, enable_mouse_drag=False, profile=None):
        """
        为控件应用触摸惯性滚动和统一滚轮平滑滚动
        """
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)

        if not is_animation_enabled("smooth_scrolling", default=True):
            try:
                QScroller.ungrabGesture(target)
            except RuntimeError:
                pass

            wheel_filter = getattr(target, "_smooth_wheel_filter", None)
            if wheel_filter is not None:
                content_overscroll = getattr(wheel_filter, "_content_overscroll", None)
                if content_overscroll is not None:
                    content_overscroll.reset()
                try:
                    target.removeEventFilter(wheel_filter)
                except RuntimeError:
                    pass
                target._smooth_wheel_filter = None
            return scroller

        QScroller.grabGesture(target, gesture_type)
        if enable_mouse_drag:
            QScroller.grabGesture(target, QScroller.LeftMouseButtonGesture)

        SmoothScroller._apply_scroller_profile(scroller, profile or SmoothScroller.DEFAULT_PROFILE)
        SmoothScroller._install_wheel_filter(widget, target)

        return scroller

    @staticmethod
    def apply_to_scroll_area(
        scroll_area,
        gesture_type=QScroller.TouchGesture,
        enable_mouse_drag=False,
        profile=None,
    ):
        if not isinstance(scroll_area, QScrollArea):
            return None

        SmoothScroller._configure_scroll_area(scroll_area)
        SmoothScroller.apply(scroll_area, gesture_type, enable_mouse_drag, profile=profile)
        return scroll_area

    @staticmethod
    def _install_wheel_filter(widget, target):
        if hasattr(target, "_smooth_wheel_filter") and target._smooth_wheel_filter:
            return

        target._smooth_wheel_filter = _WheelSmoothScrollFilter(widget, target)
        target.installEventFilter(target._smooth_wheel_filter)

    @staticmethod
    def _apply_scroller_profile(scroller, profile):
        properties = scroller.scrollerProperties()

        properties.setScrollMetric(
            QScrollerProperties.DragVelocitySmoothingFactor,
            profile.get("drag_velocity_smoothing", SmoothScroller.DEFAULT_PROFILE["drag_velocity_smoothing"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.DecelerationFactor,
            profile.get("deceleration", SmoothScroller.DEFAULT_PROFILE["deceleration"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.MaximumVelocity,
            profile.get("maximum_velocity", SmoothScroller.DEFAULT_PROFILE["maximum_velocity"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.AcceleratingFlickMaximumTime,
            profile.get(
                "accelerating_flick_maximum_time",
                SmoothScroller.DEFAULT_PROFILE["accelerating_flick_maximum_time"],
            ),
        )
        properties.setScrollMetric(
            QScrollerProperties.AcceleratingFlickSpeedupFactor,
            profile.get(
                "accelerating_flick_speedup_factor",
                SmoothScroller.DEFAULT_PROFILE["accelerating_flick_speedup_factor"],
            ),
        )
        properties.setScrollMetric(
            QScrollerProperties.OvershootDragResistanceFactor,
            profile.get("overshoot_drag_resistance", SmoothScroller.DEFAULT_PROFILE["overshoot_drag_resistance"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.OvershootDragDistanceFactor,
            profile.get("overshoot_drag_distance", SmoothScroller.DEFAULT_PROFILE["overshoot_drag_distance"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.OvershootScrollDistanceFactor,
            profile.get("overshoot_scroll_distance", SmoothScroller.DEFAULT_PROFILE["overshoot_scroll_distance"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.OvershootScrollTime,
            profile.get("overshoot_scroll_time", SmoothScroller.DEFAULT_PROFILE["overshoot_scroll_time"]),
        )
        properties.setScrollMetric(
            QScrollerProperties.FrameRate,
            profile.get("frame_rate", SmoothScroller.DEFAULT_PROFILE["frame_rate"]),
        )

        scroller.setScrollerProperties(properties)

    @staticmethod
    def _configure_scroll_area(scroll_area):
        if isinstance(scroll_area, QAbstractItemView):
            scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)


class D_ScrollBar(QScrollBar):
    """
    自定义滚动条组件
    支持设置主题颜色的平滑滚动条
    """

    def __init__(self, parent=None, orientation=Qt.Vertical):
        super().__init__(orientation, parent)
        self._normal_color = QColor("#e0e0e0")
        self._secondary_color = QColor("#333333")
        self._accent_color = QColor("#007AFF")
        self._auxiliary_color = QColor("#f1f3f5")
        self._update_style()

    def set_colors(self, normal_color, secondary_color, accent_color, auxiliary_color):
        """
        设置滚动条颜色

        Args:
            normal_color: 正常状态颜色
            secondary_color: 次要颜色
            accent_color: 强调颜色
            auxiliary_color: 辅助颜色
        """
        self._normal_color = QColor(normal_color) if isinstance(normal_color, str) else normal_color
        self._secondary_color = QColor(secondary_color) if isinstance(secondary_color, str) else secondary_color
        self._accent_color = QColor(accent_color) if isinstance(accent_color, str) else accent_color
        self._auxiliary_color = QColor(auxiliary_color) if isinstance(auxiliary_color, str) else auxiliary_color
        self._update_style()

    def _update_style(self):
        """更新滚动条样式"""
        handle_color = self._secondary_color.name()
        bg_color = self._auxiliary_color.name()
        self.setStyleSheet(f"""
            QScrollBar {{
                background-color: {bg_color};
                border: none;
                border-radius: 4px;
            }}
            QScrollBar::handle {{
                background-color: {handle_color};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:hover {{
                background-color: {self._accent_color.name()};
            }}
            QScrollBar::add-line, QScrollBar::sub-line {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page, QScrollBar::sub-page {{
                background: none;
            }}
        """)
