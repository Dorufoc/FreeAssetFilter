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

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QApplication
from PySide6.QtCore import Qt, QPoint, QRect, Signal, QTimer, QPropertyAnimation, QEasingCurve, Property, QEvent
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPainterPath

from freeassetfilter.utils.mouse_activity_monitor import MouseActivityMonitor
from freeassetfilter.utils.app_logger import info, debug, warning, error


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

    Position_Top = "top"
    Position_Bottom = "bottom"
    Position_Left = "left"
    Position_Right = "right"
    Position_TopLeft = "top_left"
    Position_TopRight = "top_right"
    Position_BottomLeft = "bottom_left"
    Position_BottomRight = "bottom_right"

    closed = Signal()

    def __init__(self, parent=None, position="bottom", stay_on_top=True, hide_on_window_move=True, use_sub_widget_mode=False, fill_width=False, margin=0, border_radius=None):
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
        """
        super().__init__(parent)
        
        self._stay_on_top = stay_on_top
        self._hide_on_window_move = hide_on_window_move
        self._use_sub_widget_mode = use_sub_widget_mode
        self._fill_width = fill_width
        self._margin = margin
        self._border_radius = border_radius if border_radius is not None else 8
        
        if use_sub_widget_mode:
            # 子控件模式：作为父窗口的子控件
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_NoSystemBackground, True)
        else:
            # 独立窗口模式：使用 Tool 标志而不是 ToolTip，作为父窗口的子窗口
            window_flags = Qt.Tool | Qt.FramelessWindowHint
            if stay_on_top:
                window_flags |= Qt.WindowStaysOnTopHint
            self.setWindowFlags(window_flags)
            self.setAttribute(Qt.WA_TranslucentBackground)

        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)

        self._position = position
        self._target_widget = None
        self._custom_position_callback = None
        self._offset_x = 0
        self._offset_y = int(5 * self.dpi_scale)

        self._is_visible = False
        self._is_animating = False
        self._timeout_enabled = True
        self._timeout_duration = 5000
        self._fade_duration = 300

        self._fade_animation = None
        self._opacity_value = 1.0

        self._vertical_offset = 0
        self._vertical_animation = None
        self._vertical_animation_duration = 300
        self._base_position = QPoint(0, 0)

        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

        self._auto_hide_enabled = False
        self._mouse_activity_monitor = MouseActivityMonitor(self, timeout=5000)
        self._mouse_activity_monitor.mouse_moved.connect(self._show_control_bar)
        self._mouse_activity_monitor.timeout_reached.connect(self._hide_control_bar)
        self._mouse_monitor_active = False
        
        self._target_widget_clicked = False

        self._init_ui()
        self._setup_animation()

    def _init_ui(self):
        """初始化UI组件"""
        self._content_widget = None

        self._content_layout = QVBoxLayout(self)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
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

    def _start_timeout_timer(self):
        """启动超时定时器"""
        if self._timeout_enabled and self._is_visible and not self._is_animating:
            self._timeout_timer.stop()
            self._timeout_timer.start(self._timeout_duration)

    def _stop_timeout_timer(self):
        """停止超时定时器"""
        self._timeout_timer.stop()

    def _on_timeout(self):
        """超时处理"""
        if self._is_visible and not self._is_animating:
            self._fade_out()

    def _on_animation_finished(self):
        """动画结束处理"""
        if self._opacity_value <= 0.01:
            super().hide()
            self._opacity_value = 1.0
            self._is_visible = False
        else:
            self._is_visible = True
            self._start_timeout_timer()
        self._is_animating = False

    def _fade_in(self):
        """淡入显示"""
        if self._is_visible and not self._is_animating:
            return

        self._is_animating = True
        self._stop_timeout_timer()

        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._get_opacity())
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

        super().show()
        self._is_visible = True

    def _fade_out(self):
        """淡出隐藏"""
        if not self._is_visible or self._is_animating:
            return

        self._is_animating = True
        self._stop_timeout_timer()

        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._get_opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

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

    def add_widget(self, widget):
        """
        添加单个部件到菜单内容区域

        Args:
            widget: 要添加的部件
        """
        if widget:
            self._content_layout.addWidget(widget)
            self._update_size()

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
        
        if widget:
            widget.installEventFilter(self)
            top_window = widget.window()
            if top_window:
                top_window.installEventFilter(self)

    def eventFilter(self, obj, event):
        """事件过滤器 - 监听目标控件及其顶层窗口的移动事件"""
        if event.type() == QEvent.Move and self._hide_on_window_move:
            if obj == self._target_widget:
                if self._is_visible and not self._is_animating:
                    self._fade_out()
            elif self._target_widget and obj == self._target_widget.window():
                if self._is_visible and not self._is_animating:
                    self._fade_out()
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
        self.move(pos)
        self._fade_in()

    def show(self):
        """显示菜单（带淡入动画）"""
        if self._custom_position_callback and self._target_widget:
            target_rect = self._target_widget.rect()
            
            if self._use_sub_widget_mode:
                # 子控件模式：使用相对于父窗口的坐标
                target_local = self._target_widget.mapTo(self.parent(), QPoint(0, 0))
                target_rect.moveTo(target_local)
            else:
                # 独立窗口模式：使用全局坐标
                target_global = self._target_widget.mapToGlobal(QPoint(0, 0))
                target_rect.moveTo(target_global)
            
            pos = self._custom_position_callback(target_rect, self.size())
            
            if not self._use_sub_widget_mode:
                self._adjust_to_screen(pos)
            
            self.move(pos)
        elif self._target_widget:
            self._calculate_position()
        else:
            # Qt6中使用primaryScreen替代desktop
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry() if screen else self.screen().geometry()
            screen_center = screen_geometry.center()
            pos = QPoint(screen_center.x() - self.width() // 2, screen_center.y() - self.height() // 2)
            
            if not self._use_sub_widget_mode:
                self._adjust_to_screen(pos)
            
            self.move(pos)

        self._fade_in()

    def hide(self):
        """隐藏菜单（带淡出动画）"""
        if self._is_visible and not self._is_animating:
            self._fade_out()
        elif not self._is_animating:
            super().hide()
    
    def hide_immediately(self):
        """立即隐藏菜单（无动画）"""
        self._is_visible = False
        self._stop_timeout_timer()
        super().hide()
    
    def show_immediately(self):
        """立即显示菜单（无动画）"""
        self._is_visible = True
        self._stop_timeout_timer()
        self.setWindowOpacity(1.0)
        self._update_mouse_transparency()
        
        if self._custom_position_callback and self._target_widget:
            target_rect = self._target_widget.rect()
            
            if self._use_sub_widget_mode:
                # 子控件模式：使用相对于父窗口的坐标
                target_local = self._target_widget.mapTo(self.parent(), QPoint(0, 0))
                target_rect.moveTo(target_local)
            else:
                # 独立窗口模式：使用全局坐标
                target_global = self._target_widget.mapToGlobal(QPoint(0, 0))
                target_rect.moveTo(target_global)
            
            pos = self._custom_position_callback(target_rect, self.size())
            
            if not self._use_sub_widget_mode:
                self._adjust_to_screen(pos)
            
            self.move(pos)
        elif self._target_widget:
            self._calculate_position()
        else:
            # Qt6中使用primaryScreen替代desktop
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry() if screen else self.screen().geometry()
            screen_center = screen_geometry.center()
            pos = QPoint(screen_center.x() - self.width() // 2, screen_center.y() - self.height() // 2)
            
            if not self._use_sub_widget_mode:
                self._adjust_to_screen(pos)
            
            self.move(pos)
        
        super().show()

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
        """鼠标进入事件"""
        super().enterEvent(event)
        self._stop_timeout_timer()

    def leaveEvent(self, event):
        """鼠标离开事件"""
        super().leaveEvent(event)
        self._start_timeout_timer()

    def _calculate_position(self):
        """计算菜单显示位置"""
        if not self._target_widget:
            return

        target_rect = self._target_widget.rect()
        
        if self._use_sub_widget_mode:
            # 子控件模式：使用相对于父窗口的坐标
            target_local = self._target_widget.mapTo(self.parent(), QPoint(0, 0))
            target_rect.moveTo(target_local)
        else:
            # 独立窗口模式：使用全局坐标
            target_global = self._target_widget.mapToGlobal(QPoint(0, 0))
            target_rect.moveTo(target_global)

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
            pos.setY(target_rect.bottom() + self._offset_y - self._margin)
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

        brush = QBrush(QColor(base_color))
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
        if not self._target_widget:
            return

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
        # 同时执行垂直位置动画和透明度淡入
        self.animate_to_vertical_offset(0)
        # 确保窗口可见
        if not self.isVisible():
            super().show()
        # 淡入动画
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._get_opacity())
        self._fade_animation.setEndValue(1.0)
        self._fade_animation.start()

    def show_control_bar(self):
        """
        公共方法：显示控制栏
        可以被外部调用，例如当检测到鼠标点击时
        """
        self._show_control_bar()
        if self._mouse_monitor_active:
            self._mouse_activity_monitor.reset_timer()

    def _hide_control_bar(self):
        """
        隐藏控制栏：将垂直偏移量设置为20像素，同时淡出
        """
        if not self._auto_hide_enabled:
            return
        # 只移动20像素
        self.animate_to_vertical_offset(20)
        # 淡出动画
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._get_opacity())
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()

    def set_auto_hide_enabled(self, enabled):
        """
        启用或禁用自动隐藏功能

        Args:
            enabled: 是否启用自动隐藏
        """
        self._auto_hide_enabled = enabled
        if enabled:
            if not self._mouse_monitor_active:
                self._mouse_activity_monitor.start()
                self._mouse_monitor_active = True
            self._show_control_bar()
        else:
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

    def closeEvent(self, event):
        """
        重写closeEvent，确保停止监控

        Args:
            event: 关闭事件
        """
        if self._mouse_monitor_active:
            self._mouse_activity_monitor.stop()
            self._mouse_monitor_active = False
        super().closeEvent(event)

    def __del__(self):
        """
        析构函数，确保停止监控
        """
        try:
            if hasattr(self, '_mouse_activity_monitor') and self._mouse_activity_monitor:
                self._mouse_activity_monitor.stop()
        except:
            pass
