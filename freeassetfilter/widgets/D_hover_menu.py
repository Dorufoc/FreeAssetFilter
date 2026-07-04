#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 自定义悬浮菜单组件
提供可自定义内容和位置的悬浮卡片菜单
特点：
- 与HoverTooltip一致的圆角卡片样式
- 支持自定义内部布局和内容
- 支持多种弹出位置
- 支持DPI缩放和主题颜色
- 支持超时自动隐藏（带渐变动画）
- 支持点击切换显示/隐藏
- 支持目标控件移动时自动隐藏
"""

from typing import Set

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication
from PySide6.QtCore import Qt, QPoint, QRect, Signal, QPropertyAnimation, QEasingCurve, Property, QEvent
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPainterPath, QCursor

import time
from freeassetfilter.core.heartbeat_manager import HeartbeatManager
from freeassetfilter.utils.global_mouse_monitor import GlobalMouseMonitor
from freeassetfilter.utils.app_logger import debug


class D_HoverMenu(QWidget):
    """
    自定义悬浮菜单组件
    特点：
    - 与HoverTooltip一致的白色圆角卡片样式
    - 支持自定义内部布局和内容
    - 支持多种弹出位置（上、下、左、右及组合位置）
    - 支持DPI缩放，适配不同屏幕分辨率
    - 支持主题颜色
    - 支持超时自动隐藏（带渐变动画）
    - 支持点击切换显示/隐藏
    - 支持目标控件移动时自动隐藏
    """

    keyPressed = Signal(object)  # 键盘按下信号，用于传递键盘事件给父窗口
    controlBarShown = Signal()  # 控制栏显示信号
    controlBarHidden = Signal()  # 控制栏隐藏信号

    Position_Top = "top"
    Position_Bottom = "bottom"
    Position_Left = "left"
    Position_Right = "right"
    Position_TopLeft = "top_left"
    Position_TopRight = "top_right"
    Position_BottomLeft = "bottom_left"
    Position_BottomRight = "bottom_right"

    closed = Signal()

    def __init__(self, parent=None, position="bottom", stay_on_top=True, hide_on_window_move=True, use_sub_widget_mode=False, fill_width=False, margin=0, border_radius=None, background_alpha=1.0, enable_vertical_animation=False, content_padding: tuple = (0, 0, 0, 0), no_focus=False):
        """
        初始化悬浮菜单

        Args:
            parent: 父窗口部件
            position: 初始弹出位置，可选值：top, bottom, left, right, top_left, top_right, bottom_left, bottom_right
            stay_on_top: 是否保持在顶层
            hide_on_window_move: 是否在窗口移动时隐藏
            use_sub_widget_mode: 是否使用子控件模式（作为父窗口的子控件，而不是独立窗口）
            fill_width: 是否横向填充整个父窗口宽度
            margin: 外边距（像素）
            border_radius: 圆角半径（像素），默认为None表示使用默认值4像素
            background_alpha: 背景透明度，范围 0.0-1.0，默认 1.0（不透明）
            enable_vertical_animation: 是否启用垂直位移动画，默认 False（仅透明度动画）
            content_padding: 内容内边距 (左, 上, 右, 下) 像素，默认 (0, 0, 0, 0)
            no_focus: 是否不接受焦点（WindowDoesNotAcceptFocus），避免后续 setWindowFlags 重建窗口
        """
        super().__init__(parent)

        self._stay_on_top = stay_on_top
        self._hide_on_window_move = hide_on_window_move
        self._use_sub_widget_mode = use_sub_widget_mode
        self._fill_width = fill_width
        self._margin = margin
        self._border_radius = border_radius if border_radius is not None else 8
        self._background_alpha = max(0.0, min(1.0, background_alpha))
        self._enable_vertical_animation = enable_vertical_animation
        self._content_padding = content_padding
        
        if use_sub_widget_mode:
            # 子控件模式：作为父窗口的子控件
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_NoSystemBackground, True)
        else:
            # 独立窗口模式：使用 Tool 标志而不是 ToolTip，作为父窗口的子窗口
            window_flags = Qt.Tool | Qt.FramelessWindowHint
            if stay_on_top:
                window_flags |= Qt.WindowStaysOnTopHint
            if no_focus:
                window_flags |= Qt.WindowDoesNotAcceptFocus
            self.setWindowFlags(window_flags)
            self.setAttribute(Qt.WA_TranslucentBackground)
            # 显示时不激活窗口，不获取焦点，确保键盘事件传递给父窗口
            self.setAttribute(Qt.WA_ShowWithoutActivating)

        # 禁用焦点，确保键盘事件传递给父窗口
        self.setFocusPolicy(Qt.NoFocus)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        self._position = position
        self._target_widget = None
        self._target_rect = None  # 直接设置目标矩形区域（优先于_target_widget）
        self._custom_position_callback = None
        self._offset_x = 0
        self._offset_y = int(5 * self.dpi_scale)

        self._is_visible = False
        self._is_animating = False
        self._timeout_enabled = True
        self._timeout_duration = 5000
        self._mouse_outside_timeout = 3000   # 鼠标在控制栏区域外 → 3 秒
        self._mouse_inside_timeout = 6000    # 鼠标在控制栏区域内 → 6 秒
        self._fade_duration = 300

        self._fade_animation = None
        self._opacity_value = 1.0

        self._hidden_vertical_offset = int(20 * self.dpi_scale) if self._enable_vertical_animation else 0
        self._vertical_offset = self._hidden_vertical_offset
        self._vertical_animation = None
        self._vertical_animation_duration = 300
        self._base_position = QPoint(0, 0)

        self._debounce_hide_on_move = False
        self._auto_hide_enabled = False

        # Timestamp-based timer management (replacing 3 QTimers)
        self._timeout_deadline: float = 0.0       # 0 = no pending timeout
        self._bar_idle_deadline: float = 0.0      # 0 = no pending idle
        self._debounce_deadline: float = 0.0      # 0 = no pending debounce
        self._mouse_activity_monitor = GlobalMouseMonitor(self, timeout=5000)
        self._mouse_activity_monitor.mouse_moved.connect(self._show_control_bar)
        self._mouse_activity_monitor.timeout_reached.connect(self._hide_control_bar)
        self._mouse_monitor_active = False

        self._popup_menu_visible = False      # 弹出菜单（速度/音量等）是否可见
        self._popup_widgets: Set[QWidget] = set()  # 关联的弹出窗口，用于光标区域检测
        
        self._target_widget_clicked = False

        self._init_ui()
        self._setup_animation()

        # 安装事件过滤器到所有子控件，捕获键盘事件
        # 注意：必须在 _init_ui 之后调用，因为子控件在此时才被创建
        self._install_event_filter_to_children()

        # 启用鼠标跟踪，用于控制栏空闲检测
        self._start_mouse_tracking()

        # Register heartbeat callback for deadline checks
        self._deadline_check_id = f"D_hover_menu_{id(self)}_deadlines"
        HeartbeatManager().register_tick_callback(
            self._deadline_check_id,
            self._check_deadlines,
            priority=4,
            every_n_ticks=1,
            owner=self
        )

    def _clear_debounce(self):
        """清除隐藏防抖标记"""
        if self._debounce_deadline == 0:
            return  # cancelled or not yet due
        self._debounce_deadline = 0
        self._debounce_hide_on_move = False

    def _check_deadlines(self):
        """Check all timestamp-based deadlines and fire callbacks as needed."""
        now = time.monotonic()
        if self._timeout_deadline and now >= self._timeout_deadline:
            self._timeout_deadline = 0
            self._on_timeout()
        if self._bar_idle_deadline and now >= self._bar_idle_deadline:
            self._bar_idle_deadline = 0
            self._on_bar_idle_timeout()
        if self._debounce_deadline and now >= self._debounce_deadline:
            self._debounce_deadline = 0
            self._clear_debounce()

    def _install_event_filter_to_children(self):
        """为所有子控件安装事件过滤器，捕获键盘事件并传递给父窗口"""
        for child in self.findChildren(QWidget):
            child.installEventFilter(self)
            # 递归为子控件的子控件也安装事件过滤器
            self._install_event_filter_recursive(child)

    def _install_event_filter_recursive(self, parent_widget):
        """递归为所有子控件安装事件过滤器"""
        for child in parent_widget.findChildren(QWidget):
            if child not in [self]:
                child.installEventFilter(self)
                self._install_event_filter_recursive(child)


    def _is_menu_widget(self, obj):
        """判断对象是否属于当前悬浮菜单自身或其子控件"""
        return obj is self or (isinstance(obj, QWidget) and self.isAncestorOf(obj))

    def keyPressEvent(self, event):
        """
        键盘按下事件处理
        将键盘事件传递给父窗口处理
        """
        # 发射信号通知父窗口有键盘事件
        self.keyPressed.emit(event)
        # 阻止事件继续传递，避免重复处理
        # 注意：eventFilter已经处理了子控件的键盘事件
        # keyPressEvent只处理D_HoverMenu本身接收到的键盘事件
        event.accept()

    def mouseMoveEvent(self, event):
        """鼠标在控制栏自身范围移动时重置区域内空闲定时器"""
        super().mouseMoveEvent(event)
        if self._auto_hide_enabled and self._is_visible:
            if self._popup_menu_visible:
                self._bar_idle_deadline = 0.0
            else:
                self._bar_idle_deadline = 0.0
                self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)

    def _init_ui(self):
        """初始化UI组件"""
        self._content_widget = None

        self._content_layout = QVBoxLayout(self)
        left, top, right, bottom = self._content_padding
        self._content_layout.setContentsMargins(left, top, right, bottom)
        self._content_layout.setSpacing(0)

        self.hide()
        self._opacity_value = 1.0

    def _get_opacity(self):
        """获取透明度"""
        return self._opacity_value

    def _set_opacity(self, opacity):
        """设置透明度"""
        self._opacity_value = max(0.0, min(1.0, opacity))
        self.setWindowOpacity(self._opacity_value)
        self._update_mouse_transparency()

    _menu_opacity = Property(float, _get_opacity, _set_opacity)

    def _get_vertical_offset(self):
        """获取垂直偏移量"""
        return self._vertical_offset

    def _set_vertical_offset(self, offset):
        """设置垂直偏移量并更新位置"""
        self._vertical_offset = offset
        self._update_position_with_offset()

    _menu_vertical_offset = Property(float, _get_vertical_offset, _set_vertical_offset)

    def _update_mouse_transparency(self):
        """根据透明度更新鼠标事件穿透"""
        if self._opacity_value <= 0.01:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    def _setup_animation(self):
        """设置渐变动画"""
        self._fade_animation = QPropertyAnimation(self, b"_menu_opacity")
        self._fade_animation.setDuration(self._fade_duration)
        self._fade_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_animation.finished.connect(self._on_animation_finished)

        self._vertical_animation = QPropertyAnimation(self, b"_menu_vertical_offset")
        self._vertical_animation.setDuration(self._vertical_animation_duration)
        self._vertical_animation.setEasingCurve(QEasingCurve.OutCubic)

    def set_timeout_enabled(self, enabled):
        """
        设置是否启用超时自动隐藏

        Args:
            enabled: 是否启用超时
        """
        self._timeout_enabled = enabled
        if enabled and self._is_visible:
            self._start_timeout_timer()

    def set_timeout_duration(self, duration):
        """
        设置超时时间

        Args:
            duration: 超时时间（毫秒），默认5000ms
        """
        self._timeout_duration = max(1000, duration)
        self._mouse_outside_timeout = max(1000, duration)
        self._mouse_inside_timeout = self._mouse_outside_timeout * 2
        if self._is_visible:
            self._start_timeout_timer()

    def set_fade_duration(self, duration):
        """
        设置渐变动画持续时间

        Args:
            duration: 动画持续时间（毫秒），默认200ms
        """
        self._fade_duration = max(50, duration)
        self._fade_animation.setDuration(self._fade_duration)

    def set_mouse_move_detection(self, enabled: bool):
        """
        设置是否启用鼠标移动检测显示控制栏

        Args:
            enabled: True 启用鼠标移动检测（经典模式），False 禁用（单击模式）
        """
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] set_mouse_move_detection called: enabled={enabled}")
        if enabled:
            if not self._mouse_monitor_active:
                self._mouse_activity_monitor.start()
                self._mouse_monitor_active = True
                debug(f"[D_HoverMenu] GlobalMouseMonitor started")
        else:
            if self._mouse_monitor_active:
                self._mouse_activity_monitor.stop()
                self._mouse_monitor_active = False
                debug(f"[D_HoverMenu] GlobalMouseMonitor stopped")

    def register_popup_widget(self, widget):
        """
        注册关联的弹出窗口，用于光标区域检测。
        当光标在已注册的弹出窗口上时，视为在控制栏区域内。

        Args:
            widget: 弹出窗口 QWidget
        """
        if widget is not None:
            self._popup_widgets.add(widget)

    def unregister_popup_widget(self, widget):
        """取消注册弹出窗口"""
        self._popup_widgets.discard(widget)

    def set_popup_menu_visible(self, visible: bool):
        """
        设置弹出菜单可见状态。
        当速度/音量等弹出菜单打开时，不应自动隐藏控制栏。

        Args:
            visible: 是否有弹出菜单可见
        """
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] set_popup_menu_visible: visible={visible}, _mouse_monitor_active={self._mouse_monitor_active}, _is_visible={self._is_visible}")
        self._popup_menu_visible = visible
        if not visible:
            self._update_hide_timer_after_show()
        else:
            self._stop_timeout_timer()
            if self._mouse_monitor_active:
                self._mouse_activity_monitor.pause_hide_timer()
            self._bar_idle_deadline = 0.0

    def is_popup_menu_visible(self) -> bool:
        """检查是否有弹出菜单可见"""
        return self._popup_menu_visible

    def _start_timeout_timer(self):
        """启动超时定时器（使用区域外超时时间）"""
        if self._timeout_enabled and self._is_visible:
            self._timeout_deadline = time.monotonic() + (self._mouse_outside_timeout / 1000.0)

    def _stop_timeout_timer(self):
        """停止超时定时器"""
        self._timeout_deadline = 0.0

    def reset_auto_hide_timer(self):
        """
        重置自动隐藏计时器（喂狗）
        用于在非经典模式下，每次用户操作后调用以延迟隐藏
        根据鼠标是否在控制栏区域内使用不同的超时时间
        """
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] reset_auto_hide_timer called: _timeout_enabled={self._timeout_enabled}, _is_visible={self._is_visible}")
        if self._timeout_enabled and self._is_visible:
            if self._is_cursor_in_control_bar_area():
                self._bar_idle_deadline = 0.0
                self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)
                debug(f"[D_HoverMenu] Inside bar area, using inside timeout: {self._mouse_inside_timeout}ms")
            else:
                self._timeout_deadline = 0.0
                self._timeout_deadline = time.monotonic() + (self._mouse_outside_timeout / 1000.0)
                debug(f"[D_HoverMenu] Outside bar area, using outside timeout: {self._mouse_outside_timeout}ms")
        else:
            debug(f"[D_HoverMenu] Timer NOT started due to condition check failed")

    def _on_timeout(self):
        """超时处理（区域外定时器 _timeout_timer 触发）"""
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] _on_timeout called: _is_visible={self._is_visible}, _is_animating={self._is_animating}, _popup_menu_visible={self._popup_menu_visible}")
        # 确保定时器确实已到期，防止重入
        if self._timeout_deadline:
            return  # deadline was reset between heartbeat tick and now
        # 控制栏已隐藏，忽略
        if not self._is_visible:
            return
        # 如果有弹出菜单可见，不隐藏控制栏，重新计时
        if self._popup_menu_visible:
            debug(f"[D_HoverMenu] Popup menu visible, restarting timer")
            self._start_timeout_timer()
            return
        if not self._is_animating:
            debug(f"[D_HoverMenu] Calling _hide_control_bar()")
            self._hide_control_bar()
        else:
            debug(f"[D_HoverMenu] Animation in progress, restarting timer")
            self._start_timeout_timer()

    def _on_bar_idle_timeout(self):
        """控制栏空闲超时：鼠标在控制栏区域静止超过 _mouse_inside_timeout 后隐藏"""
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] _on_bar_idle_timeout: _is_visible={self._is_visible}, _popup_menu_visible={self._popup_menu_visible}")
        # 确保定时器确实已到期，防止重入
        if self._bar_idle_deadline:
            return  # deadline was reset between heartbeat tick and now
        # 控制栏已隐藏，忽略
        if not self._is_visible:
            return
        # 如果有弹出菜单可见，不隐藏控制栏，统一使用 _update_hide_timer_after_show 重新评估
        if self._popup_menu_visible:
            debug(f"[D_HoverMenu] Popup menu visible, re-evaluating via _update_hide_timer_after_show")
            self._update_hide_timer_after_show()
            return
        if not self._is_animating:
            self._hide_control_bar()
        else:
            self._bar_idle_deadline = 0.0
            self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)

    def _start_mouse_tracking(self):
        """递归启用鼠标跟踪，用于检测控制栏上的鼠标移动"""
        self.setMouseTracking(True)
        for child in self.findChildren(QWidget):
            try:
                child.setMouseTracking(True)
            except RuntimeError:
                pass

    def _is_mouse_over_descendant(self) -> bool:
        """检查鼠标当前是否在本控件或任一子控件（含弹出窗口）上"""
        w = QApplication.widgetAt(QCursor.pos())

        # 检查是否在本控件或其子控件上
        while w is not None:
            if w is self:
                return True
            try:
                w = w.parentWidget()
            except RuntimeError:
                break

        # 检查是否在已注册的弹出窗口上
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None:
            if w in self._popup_widgets:
                return True
            try:
                w = w.parentWidget()
            except RuntimeError:
                break

        return False

    def _is_cursor_in_control_bar_area(self) -> bool:
        """
        检查鼠标光标是否在控制栏区域内。
        控制栏区域包括：
        - D_HoverMenu 自身（控制栏容器）
        - 所有已注册的弹出菜单（音量弹窗、倍速弹窗等）

        Returns:
            bool: 光标是否在控制栏区域内
        """
        cursor_pos = QCursor.pos()

        # 检查控制栏自身
        global_tl = self.mapToGlobal(self.rect().topLeft())
        if QRect(global_tl, self.size()).contains(cursor_pos):
            return True

        # 检查所有注册的弹出窗口
        for popup in self._popup_widgets:
            try:
                if popup and popup.isVisible():
                    popup_rect = popup.frameGeometry()
                    if popup_rect.contains(cursor_pos):
                        return True
            except RuntimeError:
                continue

        return False

    def _update_hide_timer_after_show(self):
        """
        控制栏显示后或鼠标活动后，根据鼠标位置和弹窗状态决定定时器策略：
        - 弹出菜单可见 → 暂停所有隐藏计时
        - 光标在控制栏区域内 → 使用 _mouse_inside_timeout（6s）
        - 光标在控制栏区域外 → 使用 _mouse_outside_timeout（3s）
        """
        if not self._auto_hide_enabled or not self._is_visible:
            return

        # 弹出菜单可见时不自动隐藏
        if self._popup_menu_visible:
            self._stop_timeout_timer()
            if self._mouse_monitor_active:
                self._mouse_activity_monitor.pause_hide_timer()
            self._bar_idle_deadline = 0.0
            return

        if self._is_cursor_in_control_bar_area():
            self._stop_timeout_timer()
            if self._mouse_monitor_active:
                self._mouse_activity_monitor.pause_hide_timer()
            self._bar_idle_deadline = 0.0
            self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)
        elif self._mouse_monitor_active:
            self._mouse_activity_monitor.timeout = self._mouse_outside_timeout
            self._mouse_activity_monitor.resume_hide_timer()
        else:
            self._timeout_deadline = 0.0
            self._timeout_deadline = time.monotonic() + (self._mouse_outside_timeout / 1000.0)

    def _on_animation_finished(self):
        """动画结束处理"""
        was_hidden = self._opacity_value <= 0.01
        if was_hidden:
            super().hide()
            self._opacity_value = 1.0
            self._is_visible = False
        else:
            self._is_visible = True
            self._update_hide_timer_after_show()
        self._is_animating = False
        # 如果是隐藏动画完成，发射控制栏隐藏信号
        if was_hidden:
            self.controlBarHidden.emit()

    def _prepare_geometry_for_show(self):
        """在显示前计算并应用基础位置"""
        if self._custom_position_callback and (self._target_widget or self._target_rect):
            if self._target_rect:
                target_rect = self._target_rect
            else:
                target_rect = self._target_widget.rect()

                if self._use_sub_widget_mode:
                    target_local = self._target_widget.mapTo(self.parent(), QPoint(0, 0))
                    target_rect.moveTo(target_local)
                else:
                    target_global = self._target_widget.mapToGlobal(QPoint(0, 0))
                    target_rect.moveTo(target_global)

            pos = self._custom_position_callback(target_rect, self.size())

            if not self._use_sub_widget_mode:
                self._adjust_to_screen(pos)

            self._base_position = pos
            self._update_position_with_offset()
        elif self._target_widget or self._target_rect:
            self._calculate_position()
        else:
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry() if screen else self.screen().geometry()
            screen_center = screen_geometry.center()
            pos = QPoint(screen_center.x() - self.width() // 2, screen_center.y() - self.height() // 2)

            if not self._use_sub_widget_mode:
                self._adjust_to_screen(pos)

            self._base_position = pos
            self._update_position_with_offset()

    def _animate_show(self):
        """执行向上显示 + 淡入的非线性动画"""
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu._animate_show] 调用 - self={id(self)}, parent={id(self.parent())}, _is_visible={self._is_visible}, isVisible={self.isVisible()}")
        
        if self._is_visible and not self._is_animating and self._get_opacity() >= 0.99 and self._vertical_offset == 0:
            return

        self._is_animating = True
        self._stop_timeout_timer()

        self._prepare_geometry_for_show()

        start_opacity = self._get_opacity()
        start_offset = self._vertical_offset

        if not self.isVisible():
            start_opacity = 0.0
            if start_offset == 0:
                start_offset = self._hidden_vertical_offset
            self._opacity_value = start_opacity
            self._vertical_offset = start_offset
            self._update_mouse_transparency()
            self._update_position_with_offset()
            debug(f"[D_HoverMenu._animate_show] 调用 super().show() - 首次显示")
            super().show()
            debug(f"[D_HoverMenu._animate_show] super().show() 完成，isVisible={self.isVisible()}")
        elif start_offset == 0 and start_opacity <= 0.01:
            start_offset = self._hidden_vertical_offset
            self._vertical_offset = start_offset
            self._update_position_with_offset()

        if self._enable_vertical_animation:
            self._vertical_animation.stop()
            self._vertical_animation.setStartValue(start_offset)
            self._vertical_animation.setEndValue(0)
            self._vertical_animation.start()
        else:
            self._vertical_animation.stop()
            self._vertical_offset = 0
            self._update_position_with_offset()

        self._fade_animation.stop()
        self._fade_animation.setStartValue(start_opacity)
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

        self._is_visible = True

        # 防抖：设置 300ms 内不响应 hide_on_window_move 的 Move 事件
        self._debounce_hide_on_move = True
        self._debounce_deadline = time.monotonic() + 0.3

    def _fade_in(self):
        """兼容旧接口：统一走显示动画"""
        self._animate_show()

    def _animate_hide(self):
        """执行向下隐藏 + 淡出的非线性动画"""
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] _animate_hide called: _is_visible={self._is_visible}, _is_animating={self._is_animating}")
        if not self._is_visible:
            debug(f"[D_HoverMenu] _animate_hide returned early")
            return

        self._is_animating = True
        self._stop_timeout_timer()
        self._bar_idle_deadline = 0.0

        if self._enable_vertical_animation:
            self._vertical_animation.stop()
            self._vertical_animation.setStartValue(self._vertical_offset)
            self._vertical_animation.setEndValue(self._hidden_vertical_offset)
            self._vertical_animation.start()
        else:
            self._vertical_animation.stop()
            self._vertical_offset = self._hidden_vertical_offset
            self._update_position_with_offset()

        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._get_opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

    def _fade_out(self):
        """兼容旧接口：统一走隐藏动画"""
        self._animate_hide()

    def set_content(self, widget):
        """
        设置菜单内容

        Args:
            widget: 要显示的内容部件
        """
        if self._content_widget:
            self._content_widget.setParent(None)

        self._content_widget = widget
        if widget:
            widget.setParent(self)
            self._content_layout.addWidget(widget)
            self._update_size()
            self._install_event_filter_to_children()
            self._start_mouse_tracking()

    def add_widget(self, widget):
        """
        添加单个部件到菜单内容区域

        Args:
            widget: 要添加的部件
        """
        if widget:
            self._content_layout.addWidget(widget)
            self._update_size()
            self._install_event_filter_to_children()
            self._start_mouse_tracking()

    def add_layout(self, layout):
        """
        添加布局到菜单内容区域

        Args:
            layout: 要添加的布局
        """
        if layout:
            self._content_layout.addLayout(layout)
            self._update_size()

    def clear_content(self):
        """清空菜单内容"""
        for i in reversed(range(self._content_layout.count())):
            item = self._content_layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        """递归清空布局"""
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item.widget():
                item.widget().setParent(None)
            elif item.layout():
                self._clear_layout(item.layout())

    def _update_size(self):
        """更新菜单大小"""
        if self._content_widget:
            self._content_widget.adjustSize() if hasattr(self._content_widget, 'adjustSize') else None

            content_size = self._content_widget.sizeHint()
            content_width = content_size.width()
            content_height = content_size.height()

            if hasattr(self._content_widget, '_list_widget'):
                list_widget = self._content_widget._list_widget
                # 使用实际宽度而不是 sizeHint
                actual_width = list_widget.width() if list_widget.width() > 0 else list_widget.minimumWidth()
                if actual_width > 0:
                    content_width = actual_width

            self.setFixedWidth(content_width)
            self.setFixedHeight(content_height)

    def set_target_widget(self, widget):
        """
        设置目标控件，菜单将显示在该控件附近

        Args:
            widget: 目标控件
        """
        if self._target_widget:
            self._target_widget.removeEventFilter(self)
            top_window = self._target_widget.window()
            if top_window:
                top_window.removeEventFilter(self)
        
        self._target_widget = widget
        self._target_rect = None  # 清除直接设置的矩形区域
        
        if widget:
            widget.installEventFilter(self)
            top_window = widget.window()
            if top_window:
                top_window.installEventFilter(self)
    
    def set_target_rect(self, rect):
        """
        直接设置目标矩形区域，用于不依赖控件的情况
        优先于 set_target_widget
        
        Args:
            rect: QRect 矩形区域（全局坐标）
        """
        self._target_rect = rect
        # 清除控件引用，因为直接设置的矩形优先
        if self._target_widget:
            self._target_widget.removeEventFilter(self)
            top_window = self._target_widget.window()
            if top_window:
                top_window.removeEventFilter(self)
            self._target_widget = None

    def eventFilter(self, obj, event):
        """事件过滤器 - 键盘转发、鼠标移动跟踪、窗口移动隐藏"""
        if event.type() == QEvent.KeyPress and self._is_menu_widget(obj):
            self.keyPressed.emit(event)
            return True

        # 鼠标在控制栏子控件上移动、点击、释放时重置区域内空闲定时器
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease) and self._auto_hide_enabled and self._is_visible:
            if self._is_menu_widget(obj) and obj is not self:
                if self._popup_menu_visible:
                    self._bar_idle_deadline = 0.0
                else:
                    self._bar_idle_deadline = 0.0
                    self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)

        if event.type() == QEvent.Move and self._hide_on_window_move:
            # 防抖：菜单刚显示后的 300ms 内不响应 Move 事件，
            # 防止 _restore_parent_focus 等操作触发 raise_() 产生的错误 Move 事件导致菜单立即隐藏
            if self._debounce_hide_on_move:
                return super().eventFilter(obj, event)
            if obj == self._target_widget:
                if self._is_visible:
                    self._animate_hide()
            elif self._target_widget and obj == self._target_widget.window():
                if self._is_visible:
                    self._animate_hide()

        return super().eventFilter(obj, event)

    def set_position(self, position):
        """
        设置弹出位置

        Args:
            position: 位置字符串，可选值：top, bottom, left, right, top_left, top_right, bottom_left, bottom_right
        """
        if position in [self.Position_Top, self.Position_Bottom, self.Position_Left,
                        self.Position_Right, self.Position_TopLeft, self.Position_TopRight,
                        self.Position_BottomLeft, self.Position_BottomRight]:
            self._position = position

    def set_offset(self, offset_x, offset_y):
        """
        设置菜单位置偏移量

        Args:
            offset_x: 水平偏移量
            offset_y: 垂直偏移量
        """
        self._offset_x = offset_x
        self._offset_y = offset_y

    def set_custom_position_callback(self, callback):
        """
        设置自定义位置计算回调函数

        Args:
            callback: 回调函数，接收(target_rect, menu_size)返回(QPoint)位置
        """
        self._custom_position_callback = callback

    def show_at(self, x, y):
        """
        在指定位置显示菜单

        Args:
            x: x坐标
            y: y坐标
        """
        pos = QPoint(x, y)
        self._adjust_to_screen(pos)
        self._base_position = QPoint(pos)
        self._vertical_offset = self._hidden_vertical_offset
        self._update_position_with_offset()
        self._animate_show()

    def show(self):
        """显示菜单（带向上显示 + 淡入动画）"""
        self._animate_show()

    def hide(self):
        """隐藏菜单（带向下隐藏 + 淡出动画）"""
        if self._is_visible:
            self._animate_hide()
        elif not self._is_animating:
            super().hide()
    
    def hide_immediately(self):
        """立即隐藏菜单（无动画）"""
        self._is_visible = False
        self._is_animating = False
        self._stop_timeout_timer()
        self._bar_idle_deadline = 0.0
        self._fade_animation.stop()
        self._vertical_animation.stop()
        self._opacity_value = 0.0
        self._vertical_offset = self._hidden_vertical_offset
        self._update_mouse_transparency()
        super().hide()
    
    def show_immediately(self):
        """立即显示菜单（无动画）"""
        self._is_visible = True
        self._is_animating = False
        self._stop_timeout_timer()
        self._fade_animation.stop()
        self._vertical_animation.stop()
        self._opacity_value = 1.0
        self._vertical_offset = 0
        self.setWindowOpacity(1.0)
        self._prepare_geometry_for_show()
        self._update_mouse_transparency()
        super().show()

        if self._auto_hide_enabled:
            self._update_hide_timer_after_show()

    def toggle(self):
        """切换显示/隐藏状态"""
        if self._is_visible:
            self.hide()
        else:
            self.show()

    def is_visible(self):
        """检查菜单是否正在显示"""
        return self._is_visible

    def enterEvent(self, event):
        """鼠标进入事件：停止所有隐藏定时器，启动区域内空闲定时器（_mouse_inside_timeout = 6s）"""
        super().enterEvent(event)
        if self._popup_menu_visible:
            return
        self._stop_timeout_timer()
        if self._mouse_monitor_active:
            self._mouse_activity_monitor.pause_hide_timer()
        self._bar_idle_deadline = 0.0
        self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)

    def leaveEvent(self, event):
        """
        鼠标离开事件：
        1. 停止区域内空闲定时器
        2. 如果光标仍在控制栏区域（含弹出菜单），仅在无弹窗时启动区域内定时器
        3. 否则恢复区域外隐藏定时器（_mouse_outside_timeout = 3s）
        """
        super().leaveEvent(event)
        self._bar_idle_deadline = 0.0
        # 如果鼠标移到弹出菜单上，不启动隐藏定时器
        if self._is_cursor_in_control_bar_area() or self._is_mouse_over_descendant():
            if self._popup_menu_visible:
                return
            self._bar_idle_deadline = time.monotonic() + (self._mouse_inside_timeout / 1000.0)
            return
        if self._popup_menu_visible:
            return
        if self._mouse_monitor_active:
            # 以区域外超时恢复全局监控器的隐藏计时
            self._mouse_activity_monitor.timeout = self._mouse_outside_timeout
            self._mouse_activity_monitor.resume_hide_timer()
        else:
            self._timeout_deadline = 0.0
            self._timeout_deadline = time.monotonic() + (self._mouse_outside_timeout / 1000.0)

    def _calculate_position(self):
        """计算菜单显示位置"""
        # 优先使用直接设置的矩形区域
        if self._target_rect is not None:
            target_rect = self._target_rect
        elif self._target_widget:
            target_rect = self._target_widget.rect()
            
            if self._use_sub_widget_mode:
                # 子控件模式：使用相对于父窗口的坐标
                target_local = self._target_widget.mapTo(self.parent(), QPoint(0, 0))
                target_rect.moveTo(target_local)
            else:
                # 独立窗口模式：使用全局坐标
                target_global = self._target_widget.mapToGlobal(QPoint(0, 0))
                target_rect.moveTo(target_global)
        else:
            return

        pos = QPoint()
        menu_width = self.width()
        menu_height = self.height()

        # 如果需要横向填充，设置菜单宽度与目标控件宽度一致（减去外边距）
        if self._fill_width:
            menu_width = target_rect.width() - 2 * self._margin
            self.setFixedWidth(menu_width)

        if self._position == self.Position_Top:
            pos.setX(target_rect.center().x() - menu_width // 2 + self._offset_x)
            pos.setY(target_rect.top() - menu_height - self._offset_y)
        elif self._position == self.Position_Bottom:
            pos.setX(target_rect.center().x() - menu_width // 2 + self._offset_x)
            # 控制栏底部对齐到目标区域底部减去边距
            pos.setY(target_rect.bottom() - menu_height - self._margin)
        elif self._position == self.Position_Left:
            pos.setX(target_rect.left() - menu_width - self._offset_x)
            pos.setY(target_rect.center().y() - menu_height // 2 + self._offset_y)
        elif self._position == self.Position_Right:
            pos.setX(target_rect.right() + self._offset_x)
            pos.setY(target_rect.center().y() - menu_height // 2 + self._offset_y)
        elif self._position == self.Position_TopLeft:
            pos.setX(target_rect.left() - menu_width + self._offset_x)
            pos.setY(target_rect.top() - menu_height + self._offset_y)
        elif self._position == self.Position_TopRight:
            pos.setX(target_rect.right() + self._offset_x)
            pos.setY(target_rect.top() - menu_height + self._offset_y)
        elif self._position == self.Position_BottomLeft:
            pos.setX(target_rect.left() - menu_width + self._offset_x)
            pos.setY(target_rect.bottom() + self._offset_y)
        elif self._position == self.Position_BottomRight:
            pos.setX(target_rect.right() + self._offset_x)
            pos.setY(target_rect.bottom() + self._offset_y)

        # 调整位置以适应外边距
        if self._fill_width:
            if self._position == self.Position_Bottom:
                # 底部位置，调整x坐标以考虑外边距
                pos.setX(target_rect.left() + self._margin)

        if not self._use_sub_widget_mode:
            self._adjust_to_screen(pos)
        
        self._base_position = pos
        self._update_position_with_offset()

    def _adjust_to_screen(self, pos):
        """
        调整位置确保菜单在屏幕内

        Args:
            pos: 位置引用
        """
        # Qt6中使用primaryScreen替代desktop
        screen = QApplication.primaryScreen()
        screen_rect = screen.geometry() if screen else self.screen().geometry()
        margin = int(2 * self.dpi_scale)

        if pos.x() < margin:
            pos.setX(margin)
        elif pos.x() + self.width() > screen_rect.width() - margin:
            pos.setX(screen_rect.width() - self.width() - margin)

        if pos.y() < margin:
            pos.setY(margin)
        elif pos.y() + self.height() > screen_rect.height() - margin:
            pos.setY(screen_rect.height() - self.height() - margin)

    def paintEvent(self, event):
        """绘制圆角卡片 - 与HoverTooltip样式完全一致"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()

        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()

        current_colors = settings_manager.get_setting("appearance.colors", {})
        base_color = current_colors.get("base_color", "#ffffff")
        normal_color = current_colors.get("normal_color", "#333333")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        border_pen = QPen(QColor(normal_color))
        border_pen.setWidth(1)
        painter.setPen(border_pen)

        base_qcolor = QColor(base_color)
        base_qcolor.setAlphaF(self._background_alpha)
        brush = QBrush(base_qcolor)
        painter.setBrush(brush)

        rect = QRect(0, 0, self.width() - 1, self.height() - 1)
        radius = self._border_radius
        painter.drawRoundedRect(rect, radius, radius)

    def content_layout(self):
        """
        获取内容布局

        Returns:
            QBoxLayout: 内容布局对象
        """
        return self._content_layout

    def _update_position_with_offset(self):
        """根据垂直偏移更新菜单位置"""
        final_pos = QPoint(self._base_position)
        final_pos.setY(final_pos.y() + self._vertical_offset)

        if not self._use_sub_widget_mode:
            self._adjust_to_screen(final_pos)

        self.move(final_pos)

    def set_vertical_offset(self, offset, animate=False):
        """
        设置垂直偏移量

        Args:
            offset: 垂直偏移量（像素）
            animate: 是否使用动画过渡，默认为 False
        """
        if animate:
            self.animate_to_vertical_offset(offset)
        else:
            self._vertical_animation.stop()
            self._vertical_offset = offset
            self._update_position_with_offset()

    def animate_to_vertical_offset(self, target_offset):
        """
        动画过渡到指定的垂直偏移量

        Args:
            target_offset: 目标垂直偏移量（像素）
        """
        self._vertical_animation.stop()
        self._vertical_animation.setStartValue(self._vertical_offset)
        self._vertical_animation.setEndValue(target_offset)
        self._vertical_animation.start()

    def stop_vertical_animation(self):
        """停止垂直位置动画"""
        if self._vertical_animation:
            self._vertical_animation.stop()

    def reset_vertical_animation(self):
        """重置垂直位置动画（停止并重置偏移量为0）"""
        self._vertical_animation.stop()
        self._vertical_offset = 0
        self._update_position_with_offset()

    def set_vertical_animation_duration(self, duration):
        """
        设置垂直位置动画的持续时间

        Args:
            duration: 动画持续时间（毫秒）
        """
        self._vertical_animation_duration = max(50, duration)
        if self._vertical_animation:
            self._vertical_animation.setDuration(self._vertical_animation_duration)

    def _show_control_bar(self):
        """
        显示控制栏：将垂直偏移量设置为0，同时淡入
        """
        if not self._auto_hide_enabled:
            return

        # 使用节流机制，避免过于频繁的动画触发
        import time
        current_time = time.time() * 1000
        if hasattr(self, '_last_show_time') and (current_time - self._last_show_time) < 100:
            return
        self._last_show_time = current_time

        # 如果已经在显示状态且透明度接近1，跳过
        if self.isVisible() and self._get_opacity() > 0.9 and self._vertical_offset == 0:
            return

        self._animate_show()
        # 发射控制栏显示信号
        self.controlBarShown.emit()
        # 根据鼠标位置决定定时器策略
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] _show_control_bar finished: _mouse_monitor_active={self._mouse_monitor_active}, _is_visible={self._is_visible}")
        self._update_hide_timer_after_show()

    def show_control_bar(self):
        """
        公共方法：显示控制栏
        可以被外部调用，例如当检测到鼠标点击时
        """
        self._show_control_bar()
        self._update_hide_timer_after_show()
        # 显示后确保焦点回到父窗口，不抢占键盘事件
        if self.parent():
            self.parent().activateWindow()
            self.parent().setFocus()

    def _hide_control_bar(self):
        """
        隐藏控制栏：将垂直偏移量设置为20像素，同时淡出
        如果弹出菜单可见则不隐藏，重新启动正确的计时器
        """
        if not self._auto_hide_enabled:
            return

        # 如果有弹出菜单可见，不隐藏控制栏，重新评估计时器策略
        if self._popup_menu_visible:
            from freeassetfilter.utils.app_logger import debug
            debug(f"[D_HoverMenu] _hide_control_bar: popup visible, re-evaluating timer")
            self._update_hide_timer_after_show()
            return

        # 使用节流机制，避免过于频繁的动画触发
        import time
        current_time = time.time() * 1000
        if hasattr(self, '_last_hide_time') and (current_time - self._last_hide_time) < 100:
            return
        self._last_hide_time = current_time

        # 如果已经在隐藏状态，跳过
        if not self.isVisible() or self._get_opacity() < 0.1:
            return

        self._animate_hide()

    def set_auto_hide_enabled(self, enabled):
        """
        启用或禁用自动隐藏功能

        Args:
            enabled: 是否启用自动隐藏
        """
        from freeassetfilter.utils.app_logger import debug
        debug(f"[D_HoverMenu] set_auto_hide_enabled called: enabled={enabled}, _mouse_monitor_active={self._mouse_monitor_active}")
        self._auto_hide_enabled = enabled
        if enabled:
            self._show_control_bar()
            self._update_hide_timer_after_show()
        else:
            self._bar_idle_deadline = 0.0
            if self._mouse_monitor_active:
                self._mouse_activity_monitor.stop()
                self._mouse_monitor_active = False
            self._show_control_bar()

    def is_auto_hide_enabled(self):
        """
        检查自动隐藏功能是否启用

        Returns:
            bool: 是否启用自动隐藏
        """
        return self._auto_hide_enabled

    def set_background_alpha(self, alpha):
        """
        设置背景透明度

        Args:
            alpha: 背景透明度，范围 0.0-1.0
        """
        self._background_alpha = max(0.0, min(1.0, alpha))
        self.update()  # 触发重绘

    def get_background_alpha(self):
        """
        获取当前背景透明度

        Returns:
            float: 背景透明度，范围 0.0-1.0
        """
        return self._background_alpha

    def set_vertical_animation_enabled(self, enabled):
        """
        设置是否启用垂直位移动画

        Args:
            enabled: True 启用垂直位移动画，False 仅保留透明度动画
        """
        self._enable_vertical_animation = bool(enabled)
        self._hidden_vertical_offset = int(20 * self.dpi_scale) if self._enable_vertical_animation else 0
        if not self._enable_vertical_animation and self._vertical_offset != 0:
            self._vertical_animation.stop()
            self._vertical_offset = 0
            self._update_position_with_offset()

    def is_vertical_animation_enabled(self):
        """
        获取当前是否启用垂直位移动画

        Returns:
            bool: 是否启用垂直位移动画
        """
        return self._enable_vertical_animation

    def set_border_radius(self, radius):
        """
        设置圆角半径

        Args:
            radius: 圆角半径（像素），必须 >= 0
        """
        self._border_radius = max(0, radius)
        self.update()  # 触发重绘

    def get_border_radius(self):
        """
        获取当前圆角半径

        Returns:
            int: 圆角半径（像素）
        """
        return self._border_radius

    def set_content_padding(self, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0):
        """
        设置内容内边距

        Args:
            left: 左内边距（像素）
            top: 上内边距（像素）
            right: 右内边距（像素）
            bottom: 下内边距（像素）
        """
        self._content_padding = (left, top, right, bottom)
        if hasattr(self, '_content_layout'):
            self._content_layout.setContentsMargins(left, top, right, bottom)

    def get_content_padding(self) -> tuple:
        """
        获取当前内容内边距

        Returns:
            tuple: (左, 上, 右, 下) 像素值
        """
        return self._content_padding

    def closeEvent(self, event):
        """
        重写closeEvent，确保停止监控

        Args:
            event: 关闭事件
        """
        if self._mouse_monitor_active:
            self._mouse_activity_monitor.stop()
            self._mouse_monitor_active = False
        self._popup_widgets.clear()
        super().closeEvent(event)

    def __del__(self):
        """
        析构函数，确保停止监控
        """
        try:
            if hasattr(self, '_mouse_activity_monitor') and self._mouse_activity_monitor:
                self._mouse_activity_monitor.stop()
        except (OSError, IOError, PermissionError, FileNotFoundError) as e:
            debug(f"D_HoverMenu 析构时停止监控失败 - 文件操作错误: {e}")
        except (ValueError, TypeError) as e:
            debug(f"D_HoverMenu 析构时停止监控失败 - 数据转换错误: {e}")
        except RuntimeError as e:
            debug(f"D_HoverMenu 析构时停止监控失败 - Qt运行时错误: {e}")
