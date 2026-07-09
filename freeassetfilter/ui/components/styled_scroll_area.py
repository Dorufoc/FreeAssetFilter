"""Styled Scroll Area component - custom scrollbar with smooth scrolling and edge bounce."""

from __future__ import annotations

import weakref
import time

from PySide6.QtCore import (
    Qt,
    QObject,
    QPropertyAnimation,
    Property,
    QEasingCurve,
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Signal,
)
from PySide6.QtWidgets import (
    QScrollArea,
    QAbstractItemView,
    QScroller,
    QScrollerProperties,
    QApplication,
    QGraphicsEffect,
    QScrollBar,
    QWidget,
)
from PySide6.QtGui import QWheelEvent, QPainter, QPaintEvent, QColor

from theme import tm
from freeassetfilter.utils.animation_settings import is_animation_enabled


__all__ = ["StyledScrollBar", "StyledScrollArea"]


# ported from widgets/smooth_scroller.py
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


# ported from widgets/smooth_scroller.py
def _get_target_widget(widget):
    """
    获取需要抓取手势和监听滚轮的目标控件
    """
    if isinstance(widget, QScrollArea):
        return widget.viewport()
    if hasattr(widget, "viewport"):
        return widget.viewport()
    return widget


class StyledScrollBar(QScrollBar):
    """Custom themed scrollbar with self-drawn paint and hover expansion.

    Paint-only (no QSS). Colors from ``tm`` (ThemeManager).
    Handle expands from ``_bar_width`` to ``_hover_width`` on mouse hover.
    """

    def __init__(self, parent: QWidget | None = None, orientation: Qt.Orientation = Qt.Vertical) -> None:
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._hovered: bool = False
        self._pressed: bool = False
        self._dragging: bool = False
        self._drag_offset: float = 0.0

        app = QApplication.instance()
        self._dpi_scale: float = getattr(app, 'dpi_scale_factor', 1.0) if app else 1.0

        self._bar_width: int = 4       # handle thickness in normal state
        self._hover_width: int = 6     # handle thickness on hover / press
        self._padding: int = 2         # right / bottom edge inset

        # ── 非线性缓动动画 ──
        self._anim_thickness: float = float(self._bar_width)
        self._thickness_anim = QPropertyAnimation(self, b"anim_thickness")
        self._thickness_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._thickness_anim.setDuration(120)

        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)  # 可靠悬停追踪，跨同级组件

    # ------------------------------------------------------------------
    # Animated thickness property (QPropertyAnimation target)
    # ------------------------------------------------------------------

    def _get_anim_thickness(self) -> float:
        return self._anim_thickness

    def _set_anim_thickness(self, val: float) -> None:
        self._anim_thickness = val
        self.update()

    anim_thickness = Property(float, _get_anim_thickness, _set_anim_thickness)

    def _animate_thickness_to(self, target: int) -> None:
        """Smoothly animate handle thickness to *target* with OutCubic easing."""
        self._thickness_anim.stop()
        self._thickness_anim.setStartValue(self._anim_thickness)
        self._thickness_anim.setEndValue(float(target))
        self._thickness_anim.start()

    # ------------------------------------------------------------------
    # Public configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        normal_width: int = 4,
        hover_width: int = 6,
        padding: int = 2,
    ) -> None:
        """Adjust visual metrics at runtime."""
        self._bar_width = max(1, normal_width)
        self._hover_width = max(1, hover_width)
        self._padding = max(0, padding)
        self.update()

    # ------------------------------------------------------------------
    # Size hint — reserve 10 px for the hover hit-target
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(8, 100)

    # ------------------------------------------------------------------
    # Handle geometry helpers
    # ------------------------------------------------------------------

    def _get_handle_rect(self) -> QRectF:
        """Return the visual handle rectangle in widget coordinates (uses animated thickness)."""
        if self.maximum() > 0:
            total = self.maximum() + self.pageStep()
            ratio = self.pageStep() / total
            min_handle = 30
            thickness = self._anim_thickness

            if self.orientation() == Qt.Vertical:
                track_size = self.height()
                handle_size = max(min_handle, int(track_size * ratio))
                handle_range = track_size - handle_size
                pos = int(handle_range * self.sliderPosition() / max(1, self.maximum()))
                x = self.width() - thickness - self._padding
                return QRectF(float(x), float(pos), float(thickness), float(handle_size))
            else:
                track_size = self.width()
                handle_size = max(min_handle, int(track_size * ratio))
                handle_range = track_size - handle_size
                pos = int(handle_range * self.sliderPosition() / max(1, self.maximum()))
                y = self.height() - thickness - self._padding
                return QRectF(float(pos), float(y), float(handle_size), float(thickness))
        else:
            if self.orientation() == Qt.Vertical:
                return QRectF(0.0, 0.0, float(self.width()), float(self.height()))
            else:
                return QRectF(0.0, 0.0, float(self.width()), float(self.height()))

    def _value_from_pos(self, pos: float) -> int:
        """Map a mouse coordinate along the scroll axis to a slider value."""
        if self.maximum() <= 0:
            return 0

        total = self.maximum() + self.pageStep()
        ratio = self.pageStep() / total
        min_handle = 30

        if self.orientation() == Qt.Vertical:
            track_size = self.height()
        else:
            track_size = self.width()

        handle_size = max(min_handle, int(track_size * ratio))
        pixel_range = track_size - handle_size
        if pixel_range <= 0:
            return 0

        norm = (pos - handle_size / 2.0) / pixel_range
        return max(0, min(int(norm * self.maximum()), self.maximum()))

    # ------------------------------------------------------------------
    # Paint — self-drawn rounded pill, no QSS
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        handle_rect = self._get_handle_rect()
        thickness = self._anim_thickness

        if self._pressed:
            color = tm.alpha_of(tm.mid, 100)
        elif self._hovered:
            color = tm.alpha_of(tm.mid, 80)
        else:
            color = tm.alpha_of(tm.mid, 40)

        painter.setBrush(color)
        radius = thickness / 2.0
        painter.drawRoundedRect(handle_rect, radius, radius)
        painter.end()

    # ------------------------------------------------------------------
    # Hover tracking (WA_Hover + HoverEnter/HoverLeave — 可靠跨同级组件)
    # ------------------------------------------------------------------

    def event(self, event) -> bool:
        if event.type() == QEvent.HoverEnter:
            self._hovered = True
            self._animate_thickness_to(self._hover_width)
        elif event.type() == QEvent.HoverLeave:
            self._hovered = False
            if not self._pressed:
                self._animate_thickness_to(self._bar_width)
        return super().event(event)

    # ------------------------------------------------------------------
    # Mouse interaction — drag handle or click-track-to-jump
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            handle_rect = self._get_handle_rect()
            if handle_rect.contains(event.pos()):
                if self.orientation() == Qt.Vertical:
                    self._drag_offset = event.pos().y() - handle_rect.y()
                else:
                    self._drag_offset = event.pos().x() - handle_rect.x()
                self._dragging = True
                self._pressed = True
                self._animate_thickness_to(self._hover_width)
            else:
                if self.orientation() == Qt.Vertical:
                    new_value = self._value_from_pos(float(event.pos().y()))
                else:
                    new_value = self._value_from_pos(float(event.pos().x()))
                self.setSliderPosition(new_value)
                self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self._pressed = False
            self._animate_thickness_to(self._hover_width if self._hovered else self._bar_width)
            self.update()
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and self.maximum() > 0:
            total = self.maximum() + self.pageStep()
            ratio = self.pageStep() / total
            min_handle = 30

            if self.orientation() == Qt.Vertical:
                track_size = self.height()
                mouse_pos = event.pos().y() - self._drag_offset
            else:
                track_size = self.width()
                mouse_pos = event.pos().x() - self._drag_offset

            handle_size = max(min_handle, int(track_size * ratio))
            pixel_range = track_size - handle_size
            if pixel_range > 0:
                new_value = (mouse_pos / pixel_range) * self.maximum()
                self.setSliderPosition(max(0, min(int(new_value), self.maximum())))
                self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)


class StyledScrollArea(QScrollArea):
    """Scroll area integrating StyledScrollBar, smooth wheel scrolling, edge bounce, and touch gestures."""

    # ------------------------------------------------------------------
    # Profile constants (ported from widgets/smooth_scroller.py)
    # ------------------------------------------------------------------
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Install StyledScrollBar for both orientations
        self.setVerticalScrollBar(StyledScrollBar(self))
        self.setHorizontalScrollBar(StyledScrollBar(self, orientation=Qt.Horizontal))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Smooth scrolling via fine-grained step (QScrollArea does not inherit QAbstractItemView)
        self.verticalScrollBar().setSingleStep(1)
        self.horizontalScrollBar().setSingleStep(1)
        self._scroller_initialized = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._scroller_initialized:
            self._scroller_initialized = True
            target = _get_target_widget(self)
            QScroller.grabGesture(target, QScroller.TouchGesture)
            # Apply DEFAULT_PROFILE settings
            scroller = QScroller.scroller(target)
            props = scroller.scrollerProperties()
            props.setScrollMetric(
                QScrollerProperties.DragVelocitySmoothingFactor,
                self.DEFAULT_PROFILE["drag_velocity_smoothing"],
            )
            props.setScrollMetric(
                QScrollerProperties.DecelerationFactor,
                self.DEFAULT_PROFILE["deceleration"],
            )
            props.setScrollMetric(
                QScrollerProperties.MaximumVelocity,
                self.DEFAULT_PROFILE["maximum_velocity"],
            )
            props.setScrollMetric(
                QScrollerProperties.AcceleratingFlickMaximumTime,
                self.DEFAULT_PROFILE["accelerating_flick_maximum_time"],
            )
            props.setScrollMetric(
                QScrollerProperties.AcceleratingFlickSpeedupFactor,
                self.DEFAULT_PROFILE["accelerating_flick_speedup_factor"],
            )
            props.setScrollMetric(
                QScrollerProperties.OvershootDragResistanceFactor,
                self.DEFAULT_PROFILE["overshoot_drag_resistance"],
            )
            props.setScrollMetric(
                QScrollerProperties.OvershootDragDistanceFactor,
                self.DEFAULT_PROFILE["overshoot_drag_distance"],
            )
            props.setScrollMetric(
                QScrollerProperties.OvershootScrollDistanceFactor,
                self.DEFAULT_PROFILE["overshoot_scroll_distance"],
            )
            props.setScrollMetric(
                QScrollerProperties.OvershootScrollTime,
                self.DEFAULT_PROFILE["overshoot_scroll_time"],
            )
            props.setScrollMetric(
                QScrollerProperties.FrameRate,
                self.DEFAULT_PROFILE["frame_rate"],
            )
            scroller.setScrollerProperties(props)
            # Install wheel smooth filter
            self._install_wheel_filter(target)

    @staticmethod
    def apply_to(
        widget: QWidget,
        enable_mouse_drag: bool = False,
        profile: dict | None = None,
    ) -> QScroller | None:
        """Apply smooth scrolling and touch gestures to any widget.

        Ported from ``SmoothScroller.apply()`` in widgets/smooth_scroller.py.
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

        QScroller.grabGesture(target, QScroller.TouchGesture)
        if enable_mouse_drag:
            QScroller.grabGesture(target, QScroller.LeftMouseButtonGesture)

        StyledScrollArea._apply_scroller_profile(
            scroller, profile or StyledScrollArea.DEFAULT_PROFILE
        )
        StyledScrollArea._install_wheel_filter_to(target, widget)

        return scroller

    @staticmethod
    def apply_to_scroll_area(
        scroll_area: QScrollArea,
        enable_mouse_drag: bool = False,
        profile: dict | None = None,
    ) -> QScrollArea | None:
        """Apply smooth scrolling and touch gestures to an existing QScrollArea."""
        if not isinstance(scroll_area, QScrollArea):
            return None
        scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        StyledScrollArea.apply_to(scroll_area, enable_mouse_drag, profile=profile)
        return scroll_area

    # ------------------------------------------------------------------
    # Internal helpers (ported from SmoothScroller private methods)
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_scroller_profile(scroller: QScroller, profile: dict) -> None:
        """Apply scroller property profile to a QScroller."""
        default = StyledScrollArea.DEFAULT_PROFILE
        props = scroller.scrollerProperties()

        props.setScrollMetric(
            QScrollerProperties.DragVelocitySmoothingFactor,
            profile.get("drag_velocity_smoothing", default["drag_velocity_smoothing"]),
        )
        props.setScrollMetric(
            QScrollerProperties.DecelerationFactor,
            profile.get("deceleration", default["deceleration"]),
        )
        props.setScrollMetric(
            QScrollerProperties.MaximumVelocity,
            profile.get("maximum_velocity", default["maximum_velocity"]),
        )
        props.setScrollMetric(
            QScrollerProperties.AcceleratingFlickMaximumTime,
            profile.get(
                "accelerating_flick_maximum_time",
                default["accelerating_flick_maximum_time"],
            ),
        )
        props.setScrollMetric(
            QScrollerProperties.AcceleratingFlickSpeedupFactor,
            profile.get(
                "accelerating_flick_speedup_factor",
                default["accelerating_flick_speedup_factor"],
            ),
        )
        props.setScrollMetric(
            QScrollerProperties.OvershootDragResistanceFactor,
            profile.get("overshoot_drag_resistance", default["overshoot_drag_resistance"]),
        )
        props.setScrollMetric(
            QScrollerProperties.OvershootDragDistanceFactor,
            profile.get("overshoot_drag_distance", default["overshoot_drag_distance"]),
        )
        props.setScrollMetric(
            QScrollerProperties.OvershootScrollDistanceFactor,
            profile.get("overshoot_scroll_distance", default["overshoot_scroll_distance"]),
        )
        props.setScrollMetric(
            QScrollerProperties.OvershootScrollTime,
            profile.get("overshoot_scroll_time", default["overshoot_scroll_time"]),
        )
        props.setScrollMetric(
            QScrollerProperties.FrameRate,
            profile.get("frame_rate", default["frame_rate"]),
        )

        scroller.setScrollerProperties(props)

    @staticmethod
    def _install_wheel_filter_to(target: QWidget, host_widget: QWidget) -> None:
        """Install wheel smooth filter on the target widget."""
        if hasattr(target, "_smooth_wheel_filter") and target._smooth_wheel_filter:
            return
        target._smooth_wheel_filter = _WheelSmoothScrollFilter(host_widget, target)
        target.installEventFilter(target._smooth_wheel_filter)

    def _install_wheel_filter(self, target: QWidget) -> None:
        """Install wheel smooth filter using self as the host widget."""
        StyledScrollArea._install_wheel_filter_to(target, self)


# ported from widgets/smooth_scroller.py
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


# ported from widgets/smooth_scroller.py
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


# ported from widgets/smooth_scroller.py
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