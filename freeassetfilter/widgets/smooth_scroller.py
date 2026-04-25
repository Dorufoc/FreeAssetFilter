# -*- coding: utf-8 -*-
"""
FreeAssetFilter 滚动条组件
带悬停动画效果、平滑滚动和动态宽度控制的滚动条
"""

from PySide6.QtCore import (
    Qt,
    Signal,
    QObject,
    QPropertyAnimation,
    Property,
    QEasingCurve,
    QEvent,
    QRectF,
)
from PySide6.QtWidgets import (
    QScrollArea,
    QAbstractSlider,
    QAbstractItemView,
    QScroller,
    QScrollerProperties,
    QApplication,
    QScrollBar,
)
from PySide6.QtGui import QColor, QWheelEvent, QPainter
from freeassetfilter.utils.app_logger import debug
import time


def _coerce_scrollbar_args(arg1, arg2):
    """
    兼容旧版 D_ScrollBar(parent, orientation) 与新版 D_ScrollBar(orientation, parent) 两种写法
    """
    orientation_values = (Qt.Vertical, Qt.Horizontal)

    if arg1 in orientation_values or arg1 is None:
        orientation = arg1 if arg1 in orientation_values else Qt.Vertical
        parent = arg2
        return orientation, parent

    if arg2 in orientation_values or arg2 is None:
        orientation = arg2 if arg2 in orientation_values else Qt.Vertical
        parent = arg1
        return orientation, parent

    return Qt.Vertical, arg1


class D_ScrollBar(QScrollBar):
    """
    带悬停动画效果、平滑滚动和动态宽度控制的滚动条

    特点：
    - 滑块悬停时平滑变色
    - 支持强调色和次选色方案
    - 支持垂直和水平方向
    - 支持非线性动画过渡效果
    - 支持 QScroller 触摸/拖拽惯性滚动
    - 支持动态宽度控制（内容无需滚动时自动隐藏）
    """

    scroll_finished = Signal()

    def __init__(self, arg1=Qt.Vertical, arg2=None):
        """
        初始化动画滚动条

        兼容两种历史调用方式：
            D_ScrollBar(Qt.Vertical, parent)
            D_ScrollBar(parent, Qt.Vertical)
        """
        orientation, parent = _coerce_scrollbar_args(arg1, arg2)
        super().__init__(orientation, parent)

        self._dpi_scale = 1.0
        self._is_hovering = False
        self._is_pressed = False

        app = QApplication.instance()
        if app:
            self._dpi_scale = getattr(app, "dpi_scale_factor", 1.0)

        self._normal_color = QColor("#e0e0e0")
        self._hover_color = QColor("#333333")
        self._pressed_color = QColor("#007AFF")
        self._auxiliary_color = QColor("#f1f3f3")

        self._anim_handle_color_value = QColor(self._normal_color)
        self._visual_handle_ratio_value = 1.0
        self._visual_position_ratio_value = 0.0
        self._updating_style = False
        self._last_style = ""
        self._suppress_jump_animation_until = 0.0

        # 动态宽度控制相关属性
        self._default_width = 4
        self._current_width = 0
        self._scroll_area = None

        # QScroller 手势状态管理
        self._scroller_target = None
        self._scroller_was_touch_active = False
        self._scroller_was_mouse_active = False

        self._init_animations()
        self._sync_visual_handle_ratio(immediate=True)
        self._sync_visual_position_ratio(immediate=True)
        self._update_style()

        self.setAttribute(Qt.WA_Hover, True)
        self.rangeChanged.connect(self._on_range_changed)
        self.valueChanged.connect(lambda _: self.update())
        self.actionTriggered.connect(self._on_action_triggered)

    def set_scroll_area(self, scroll_area):
        """
        设置关联的滚动区域，用于检测内容是否需要滚动
        """
        self._scroll_area = scroll_area
        self._check_and_update_width()

    def _on_range_changed(self, min_val=0, max_val=0):
        """滚动范围变化时触发宽度检查"""
        self._check_and_update_width()
        self._sync_visual_handle_ratio()

    def _check_and_update_width(self):
        """
        检查内容是否需要滚动，并更新滚动条宽度
        """
        needs_scroll = self._needs_scroll()
        target_width = self._default_width if needs_scroll else 0

        if self._current_width == target_width:
            return

        self._current_width = target_width
        self._update_style()

    def _needs_scroll(self):
        """
        检测内容是否需要滚动
        """
        if self.maximum() > self.minimum():
            return True

        if self._scroll_area and self._scroll_area.widget():
            viewport = self._scroll_area.viewport()
            content = self._scroll_area.widget()

            if viewport and content:
                if self.orientation() == Qt.Vertical:
                    return content.height() > viewport.height() + 5
                return content.width() > viewport.width() + 5

        return False

    def set_default_width(self, width):
        """
        设置滚动条默认宽度
        """
        self._default_width = max(0, width)
        self._check_and_update_width()

    def update_width_immediately(self):
        """立即更新滚动条宽度（无动画）"""
        self._current_width = self._default_width if self._needs_scroll() else 0
        self._update_style()

    def set_periodic_check_interval(self, interval_ms):
        """
        保留兼容接口；当前实现不再启用周期巡检。
        """
        return

    def enable_periodic_check(self, enabled=True):
        """
        保留兼容接口；当前实现不再启用周期巡检。
        """
        return

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

        self._handle_ratio_anim = QPropertyAnimation(self, b"_visual_handle_ratio")
        self._handle_ratio_anim.setDuration(260)
        self._handle_ratio_anim.setEasingCurve(QEasingCurve.OutBack)

        self._handle_position_anim = QPropertyAnimation(self, b"_visual_position_ratio")
        self._handle_position_anim.setDuration(220)
        self._handle_position_anim.setEasingCurve(QEasingCurve.OutCubic)

    def _get_actual_handle_ratio(self):
        page_step = max(0, self.pageStep())
        total_span = max(0, self.maximum() - self.minimum()) + page_step
        if total_span <= 0:
            return 1.0
        return max(0.0, min(1.0, page_step / float(total_span)))

    def _get_actual_position_ratio(self):
        scroll_span = self.maximum() - self.minimum()
        if scroll_span <= 0:
            return 0.0
        return max(0.0, min(1.0, (self.value() - self.minimum()) / float(scroll_span)))

    def _sync_visual_handle_ratio(self, immediate=False):
        target_ratio = self._get_actual_handle_ratio()

        if immediate:
            self._handle_ratio_anim.stop()
            self._set_visual_handle_ratio(target_ratio)
            return

        current_ratio = self._visual_handle_ratio_value
        if abs(current_ratio - target_ratio) < 0.002:
            self._handle_ratio_anim.stop()
            self._set_visual_handle_ratio(target_ratio)
            return

        self._handle_ratio_anim.stop()
        self._handle_ratio_anim.setStartValue(current_ratio)
        self._handle_ratio_anim.setEndValue(target_ratio)
        self._handle_ratio_anim.start()

    def _sync_visual_position_ratio(self, immediate=False, animate_if_jump=False):
        target_ratio = self._get_actual_position_ratio()

        if immediate:
            self._handle_position_anim.stop()
            self._set_visual_position_ratio(target_ratio)
            return

        current_ratio = self._visual_position_ratio_value
        if not animate_if_jump or self._is_pressed or self._is_jump_animation_suppressed():
            self._handle_position_anim.stop()
            self._set_visual_position_ratio(target_ratio)
            return

        if not self._is_position_jump(current_ratio, target_ratio):
            self._handle_position_anim.stop()
            self._set_visual_position_ratio(target_ratio)
            return

        self._handle_position_anim.stop()
        self._handle_position_anim.setStartValue(current_ratio)
        self._handle_position_anim.setEndValue(target_ratio)
        self._handle_position_anim.start()

    def _suppress_jump_animation(self, duration_seconds=0.25):
        self._suppress_jump_animation_until = max(
            self._suppress_jump_animation_until,
            time.time() + max(0.0, float(duration_seconds)),
        )

    def _is_jump_animation_suppressed(self):
        return time.time() < self._suppress_jump_animation_until

    def _is_position_jump(self, current_ratio, target_ratio):
        groove_rect = QRectF(self.rect())
        if groove_rect.isEmpty():
            return False

        is_vertical = self.orientation() == Qt.Vertical
        available_length = groove_rect.height() if is_vertical else groove_rect.width()
        if available_length <= 0:
            return False

        min_size = max(1.0, 15.0 * self._dpi_scale)
        handle_length = min(available_length, max(min_size, available_length * self._visual_handle_ratio_value))
        travel = max(0.0, available_length - handle_length)
        jump_pixels = abs(target_ratio - current_ratio) * travel
        jump_threshold = max(28.0 * self._dpi_scale, min_size * 1.35)
        return jump_pixels >= jump_threshold

    def _on_action_triggered(self, action):
        self._suppress_jump_animation(0.22)
        self._sync_visual_position_ratio(immediate=True)

    def set_colors(self, normal_color, hover_color, pressed_color, auxiliary_color=None):
        """
        设置滚动条颜色
        """
        self._normal_color = QColor(normal_color) if isinstance(normal_color, str) else QColor(*normal_color)
        self._hover_color = QColor(hover_color) if isinstance(hover_color, str) else QColor(*hover_color)
        self._pressed_color = QColor(pressed_color) if isinstance(pressed_color, str) else QColor(*pressed_color)

        if auxiliary_color:
            self._auxiliary_color = (
                QColor(auxiliary_color) if isinstance(auxiliary_color, str) else QColor(*auxiliary_color)
            )

        if not self._is_hovering and not self._is_pressed:
            self._anim_handle_color_value = QColor(self._normal_color)

        self._update_style()

    def apply_theme_from_settings(self, settings_manager=None, prefix="appearance.colors."):
        """
        从设置管理器应用主题颜色
        """
        app = QApplication.instance()
        if settings_manager is None:
            if hasattr(app, "settings_manager"):
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
        width = int(self._current_width * self._dpi_scale)
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

        bg = self._auxiliary_color
        bg_color = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, 255)"

        style = f"""
            QScrollBar:{("vertical" if is_vertical else "horizontal")} {{
                {other_size}: {width}px;
                background-color: {bg_color};
                border: 0px solid transparent;
                border-radius: 0px;
            }}
            QScrollBar::{"handle:" + ("vertical" if is_vertical else "horizontal")} {{
                background-color: transparent;
                {min_dim}: {min_size}px;
                border-radius: {radius}px;
                border: none;
            }}
            QScrollBar::add-line:{("vertical" if is_vertical else "horizontal")},
            QScrollBar::sub-line:{("vertical" if is_vertical else "horizontal")} {{
                {size_dim}: 0px;
                border: none;
            }}
            QScrollBar::add-page:{("vertical" if is_vertical else "horizontal")},
            QScrollBar::sub-page:{("vertical" if is_vertical else "horizontal")} {{
                background: none;
                border: none;
            }}
        """

        if style != self._last_style:
            self.setStyleSheet(style)
            self._last_style = style

        self._updating_style = False

    def _get_anim_handle_color(self):
        return self._anim_handle_color_value

    def _set_anim_handle_color(self, color):
        new_color = QColor(color)
        if new_color == self._anim_handle_color_value:
            return
        self._anim_handle_color_value = new_color
        self._update_style()
        self.update()

    _anim_handle_color = Property(QColor, fget=_get_anim_handle_color, fset=_set_anim_handle_color)

    def _get_visual_handle_ratio(self):
        return self._visual_handle_ratio_value

    def _set_visual_handle_ratio(self, ratio):
        clamped_ratio = max(0.0, min(1.0, float(ratio)))
        if abs(clamped_ratio - self._visual_handle_ratio_value) < 0.0005:
            return
        self._visual_handle_ratio_value = clamped_ratio
        self.update()

    _visual_handle_ratio = Property(float, fget=_get_visual_handle_ratio, fset=_set_visual_handle_ratio)

    def _get_visual_position_ratio(self):
        return self._visual_position_ratio_value

    def _set_visual_position_ratio(self, ratio):
        clamped_ratio = max(0.0, min(1.0, float(ratio)))
        if abs(clamped_ratio - self._visual_position_ratio_value) < 0.0005:
            return
        self._visual_position_ratio_value = clamped_ratio
        self.update()

    _visual_position_ratio = Property(float, fget=_get_visual_position_ratio, fset=_set_visual_position_ratio)

    def sliderChange(self, change):
        super().sliderChange(change)
        if change in (
            QAbstractSlider.SliderRangeChange,
            QAbstractSlider.SliderStepsChange,
            QAbstractSlider.SliderValueChange,
        ):
            if change == QAbstractSlider.SliderValueChange:
                self._sync_visual_position_ratio(animate_if_jump=True)
            else:
                self._sync_visual_handle_ratio()
                self._sync_visual_position_ratio(animate_if_jump=True)

    def _build_handle_rect(self):
        full_rect = QRectF(self.rect())
        if full_rect.isEmpty():
            return QRectF()

        is_vertical = self.orientation() == Qt.Vertical
        available_length = full_rect.height() if is_vertical else full_rect.width()
        if available_length <= 0:
            return QRectF()

        min_size = max(1.0, 15.0 * self._dpi_scale)
        handle_length = min(available_length, max(min_size, available_length * self._visual_handle_ratio_value))

        scroll_span = max(1, self.maximum() - self.minimum())
        travel = max(0.0, available_length - handle_length)
        handle_offset = travel * self._visual_position_ratio_value

        if is_vertical:
            return QRectF(full_rect.left(), full_rect.top() + handle_offset, full_rect.width(), handle_length)
        return QRectF(full_rect.left() + handle_offset, full_rect.top(), handle_length, full_rect.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        groove_rect = QRectF(self.rect())
        if groove_rect.isEmpty():
            return

        bg = self._auxiliary_color
        handle = self._anim_handle_color_value
        radius = min(groove_rect.width(), groove_rect.height()) / 2.0

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(groove_rect, radius, radius)

        if self._current_width > 0:
            handle_rect = self._build_handle_rect()
            if not handle_rect.isEmpty():
                painter.setBrush(handle)
                painter.drawRoundedRect(handle_rect, radius, radius)

    def sizeHint(self):
        hint = super().sizeHint()
        thickness = max(0, int(round(self._current_width * self._dpi_scale)))
        if self.orientation() == Qt.Vertical:
            hint.setWidth(thickness)
        else:
            hint.setHeight(thickness)
        return hint

    def enterEvent(self, event):
        """鼠标进入事件"""
        self._is_hovering = True
        target_color = self._pressed_color if self._is_pressed else self._hover_color

        self._leave_anim.stop()
        self._hover_anim.setStartValue(QColor(self._anim_handle_color_value))
        self._hover_anim.setEndValue(QColor(target_color))
        self._hover_anim.start()

        super().enterEvent(event)

    def leaveEvent(self, event):
        """鼠标离开事件"""
        self._is_hovering = False

        if not self._is_pressed:
            self._hover_anim.stop()
            self._leave_anim.setStartValue(QColor(self._anim_handle_color_value))
            self._leave_anim.setEndValue(QColor(self._normal_color))
            self._leave_anim.start()

        super().leaveEvent(event)

    def _get_scroller_target(self):
        """
        获取关联的 QScroller 目标控件
        """
        parent = self.parent()
        if isinstance(parent, QScrollArea):
            return parent.viewport()
        if hasattr(parent, "viewport"):
            return parent.viewport()
        return parent

    def _disable_scroller_gesture(self):
        """
        临时禁用 QScroller 手势，避免滚动条拖动被劫持
        """
        if self._scroller_target is None:
            self._scroller_target = self._get_scroller_target()

        if self._scroller_target:
            scroller = QScroller.scroller(self._scroller_target)
            if scroller.state() != QScroller.Inactive:
                scroller.stop()

            try:
                QScroller.ungrabGesture(self._scroller_target)
            except RuntimeError as e:
                debug(f"取消手势抓取时出错: {e}")

            self._scroller_was_touch_active = True
            self._scroller_was_mouse_active = True

    def _restore_scroller_gesture(self):
        """
        恢复 QScroller 手势
        """
        if self._scroller_target:
            try:
                if self._scroller_was_touch_active:
                    QScroller.grabGesture(self._scroller_target, QScroller.TouchGesture)
                if self._scroller_was_mouse_active:
                    QScroller.grabGesture(self._scroller_target, QScroller.LeftMouseButtonGesture)
            except RuntimeError as e:
                debug(f"恢复手势抓取时出错: {e}")

        self._scroller_was_touch_active = False
        self._scroller_was_mouse_active = False

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        self._is_pressed = True
        self._disable_scroller_gesture()
        self._suppress_jump_animation(0.30)
        self._sync_visual_position_ratio(immediate=True)

        self._hover_anim.stop()
        self._press_anim.setStartValue(QColor(self._anim_handle_color_value))
        self._press_anim.setEndValue(QColor(self._pressed_color))
        self._press_anim.start()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self._is_pressed:
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        self._is_pressed = False
        self._restore_scroller_gesture()
        self._suppress_jump_animation(0.12)

        self._press_anim.stop()
        self._release_anim.setStartValue(QColor(self._anim_handle_color_value))
        self._release_anim.setEndValue(QColor(self._hover_color if self._is_hovering else self._normal_color))
        self._release_anim.start()
        self._sync_visual_position_ratio(immediate=True)

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """
        保留默认滚轮行为。
        平滑滚动由安装在视口/目标控件上的 wheel filter 统一处理。
        """
        super().wheelEvent(event)

    def set_friction(self, friction):
        """
        保留兼容接口；当前滚轮动画由 Qt 属性动画驱动，不再使用摩擦定时器。
        """
        return


def _get_target_widget(widget):
    """
    获取需要抓取手势和监听滚轮的目标控件
    """
    if isinstance(widget, QScrollArea):
        return widget.viewport()
    if hasattr(widget, "viewport"):
        return widget.viewport()
    return widget


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
        target_value = max(scrollbar.minimum(), min(scrollbar.maximum(), target_value))

        if target_value == current_value:
            return False

        self._animate_scrollbar(scrollbar, target_value)
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

        if pending_target is not None:
            base_value = int(pending_target)
        elif animation is not None and animation.state() == QPropertyAnimation.Running:
            end_value = animation.endValue()
            base_value = int(end_value) if end_value is not None else current_value
        else:
            base_value = current_value

        target_value = base_value - step
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
        orientation = scrollbar.orientation()
        animation_attr = "_vertical_animation" if orientation == Qt.Vertical else "_horizontal_animation"
        pending_attr = "_pending_vertical_target" if orientation == Qt.Vertical else "_pending_horizontal_target"
        animation = getattr(self, animation_attr, None)

        if isinstance(scrollbar, D_ScrollBar):
            scrollbar._suppress_jump_animation(max(0.18, self._duration / 1000.0 + 0.05))

        start_value = scrollbar.value()
        if animation is not None and animation.state() == QPropertyAnimation.Running:
            start_value = animation.currentValue() if animation.currentValue() is not None else scrollbar.value()
            animation.stop()

        animation = QPropertyAnimation(scrollbar, b"value", self)
        animation.setDuration(self._duration)
        animation.setEasingCurve(QEasingCurve.OutQuad)
        animation.setStartValue(int(start_value))
        animation.setEndValue(int(target_value))
        animation.finished.connect(lambda: setattr(self, pending_attr, None))
        animation.finished.connect(self._emit_scroll_finished_if_needed)
        setattr(self, animation_attr, animation)
        animation.start()

    def _emit_scroll_finished_if_needed(self):
        for orientation in (Qt.Vertical, Qt.Horizontal):
            scrollbar = self._resolve_scrollbar(orientation)
            if isinstance(scrollbar, D_ScrollBar):
                scrollbar.scroll_finished.emit()


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
        enable_smart_width=True,
        profile=None,
    ):
        """
        为 QScrollArea 应用平滑滚动
        """
        if not isinstance(scroll_area, QScrollArea):
            return None

        SmoothScroller._configure_scroll_area(scroll_area)
        SmoothScroller.apply(scroll_area, gesture_type, enable_mouse_drag, profile=profile)

        if enable_smart_width:
            SmoothScroller._enable_smart_width(scroll_area)

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
    def _enable_smart_width(scroll_area):
        """
        为滚动区域启用智能宽度控制
        """
        if not isinstance(scroll_area, QScrollArea):
            return

        v_scrollbar = scroll_area.verticalScrollBar()
        h_scrollbar = scroll_area.horizontalScrollBar()

        if isinstance(v_scrollbar, D_ScrollBar):
            v_scrollbar.set_scroll_area(scroll_area)

        if isinstance(h_scrollbar, D_ScrollBar):
            h_scrollbar.set_scroll_area(scroll_area)

        class ResizeEventFilter(QObject):
            def __init__(self, callback, parent=None):
                super().__init__(parent)
                self.callback = callback

            def eventFilter(self, obj, event):
                if event.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                    self.callback()
                return super().eventFilter(obj, event)

        def do_check():
            if isinstance(v_scrollbar, D_ScrollBar):
                v_scrollbar._check_and_update_width()
            if isinstance(h_scrollbar, D_ScrollBar):
                h_scrollbar._check_and_update_width()

        if not hasattr(scroll_area, "_smart_width_filter"):
            scroll_area._smart_width_filter = ResizeEventFilter(do_check, scroll_area)
            scroll_area.installEventFilter(scroll_area._smart_width_filter)
            scroll_area.viewport().installEventFilter(scroll_area._smart_width_filter)
            if scroll_area.widget():
                scroll_area.widget().installEventFilter(scroll_area._smart_width_filter)

        do_check()

    @staticmethod
    def _configure_scroll_area(scroll_area):
        """配置像素级滚动模式"""
        if isinstance(scroll_area, QAbstractItemView):
            scroll_area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            scroll_area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    @staticmethod
    def apply_ios_style(widget, gesture_type=QScroller.TouchGesture, enable_mouse_drag=False):
        """应用 iOS 风格滚动"""
        return SmoothScroller.apply(
            widget,
            gesture_type=gesture_type,
            enable_mouse_drag=enable_mouse_drag,
            profile=SmoothScroller.IOS_LIKE_PROFILE,
        )

    @staticmethod
    def apply_quick_style(widget, gesture_type=QScroller.TouchGesture, enable_mouse_drag=False):
        """应用快速响应风格滚动"""
        return SmoothScroller.apply(
            widget,
            gesture_type=gesture_type,
            enable_mouse_drag=enable_mouse_drag,
            profile=SmoothScroller.QUICK_PROFILE,
        )

    @staticmethod
    def enable_vertical_only(widget):
        """只启用垂直滚动"""
        if isinstance(widget, QScrollArea):
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            widget.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
