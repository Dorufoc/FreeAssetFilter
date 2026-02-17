# -*- coding: utf-8 -*-
"""
FreeAssetFilter 滚动条组件
带悬停动画效果、平滑滚动和动态宽度控制的滚动条
"""

from PySide6.QtCore import Qt, QPoint, QTimer, Signal, QObject, QPropertyAnimation, Property, QEasingCurve
from PySide6.QtWidgets import QScrollArea, QAbstractItemView, QScroller, QScrollerProperties, QApplication, QScrollBar
from PySide6.QtGui import QColor, QWheelEvent
import time


class D_ScrollBar(QScrollBar):
    """
    带悬停动画效果、平滑滚动和动态宽度控制的滚动条
    
    特点：
    - 滑块悬停时平滑变色
    - 支持强调色和次选色方案
    - 支持垂直和水平方向
    - 支持非线性动画过渡效果
    - 支持触摸惯性滚动
    - 支持滚轮平滑滚动
    - 支持动态宽度控制（内容无需滚动时自动隐藏）
    """
    
    scroll_finished = Signal()
    
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
        
        # 动态宽度控制相关属性
        self._default_width = 4  # 默认滚动条宽度（像素）
        self._current_width = 0  # 当前宽度初始为0（隐藏状态）
        self._scroll_area = None  # 关联的滚动区域
        
        self._init_animations()
        self._update_style()
        self._init_smooth_scroll()
        
        self.setAttribute(Qt.WA_Hover, True)
        
        # 连接值变化信号以检测滚动需求变化
        self.rangeChanged.connect(self._on_range_changed)
    
    def set_scroll_area(self, scroll_area):
        """
        设置关联的滚动区域，用于检测内容是否需要滚动
        
        Args:
            scroll_area: QScrollArea 实例
        """
        # 如果之前有关联的滚动区域，断开连接
        if self._scroll_area and self._scroll_area != scroll_area:
            try:
                self.rangeChanged.disconnect(self._on_range_changed)
            except:
                pass
        
        self._scroll_area = scroll_area
        if scroll_area:
            # 监听D_ScrollBar自身的rangeChanged信号
            # 注意：当D_ScrollBar被设置为QScrollArea的滚动条后，
            # QScrollArea会自动更新D_ScrollBar的range，触发其rangeChanged信号
            self.rangeChanged.connect(self._on_range_changed)
            # 初始检查
            self._check_and_update_width()
        else:
            # 断开信号连接
            try:
                self.rangeChanged.disconnect(self._on_range_changed)
            except:
                pass
    
    def _on_range_changed(self, min_val=0, max_val=0):
        """滚动范围变化时触发宽度检查"""
        # 直接检查并更新宽度，不使用延迟
        self._check_and_update_width()
    
    def _check_and_update_width(self):
        """
        检查内容是否需要滚动，并更新滚动条宽度
        
        当内容无需滚动时，将滚动条宽度设为0px
        当内容需要滚动时，恢复默认宽度
        """
        try:
            if not self or not self.isVisible():
                return
            needs_scroll = self._needs_scroll()
            target_width = self._default_width if needs_scroll else 0
            
            # 如果宽度没有变化，直接返回
            if self._current_width == target_width:
                return
            
            # 直接设置宽度，不使用动画
            self._current_width = target_width
            self._update_style()
        except RuntimeError:
            pass
    
    def _needs_scroll(self):
        """
        检测内容是否需要滚动
        
        Returns:
            bool: 是否需要滚动
        """
        try:
            if not self:
                return False
            # 首先检查滚动条自身的range（最可靠的指标）
            if self.maximum() > self.minimum():
                return True
            
            # 如果range为0，但关联了滚动区域，进一步检查内容尺寸
            # 这种情况可能发生在滚动条range还未更新时
            if self._scroll_area and self._scroll_area.widget():
                viewport = self._scroll_area.viewport()
                content = self._scroll_area.widget()
                
                if viewport and content:
                    if self.orientation() == Qt.Vertical:
                        # 垂直方向：比较内容高度和视口高度
                        # 添加一个小的阈值避免边界情况
                        content_height = content.height()
                        viewport_height = viewport.height()
                        # 使用更宽松的判断条件
                        return content_height > viewport_height + 5
                    else:
                        # 水平方向：比较内容宽度和视口宽度
                        content_width = content.width()
                        viewport_width = viewport.width()
                        return content_width > viewport_width + 5
        except RuntimeError:
            pass
        
        return False
    
    def set_default_width(self, width):
        """
        设置滚动条默认宽度
        
        Args:
            width: 默认宽度（像素）
        """
        self._default_width = max(0, width)
        self._check_and_update_width()
    
    def update_width_immediately(self):
        """立即更新滚动条宽度（无动画）"""
        needs_scroll = self._needs_scroll()
        self._current_width = self._default_width if needs_scroll else 0
        if self._width_animation and self._width_animation.state() == QPropertyAnimation.Running:
            self._width_animation.stop()
        self._update_style()
    
    def set_periodic_check_interval(self, interval_ms):
        """
        设置定期检测间隔
        
        Args:
            interval_ms: 检测间隔（毫秒），默认500ms
        """
        self._periodic_check_timer.setInterval(max(100, interval_ms))
    
    def enable_periodic_check(self, enabled=True):
        """
        启用或禁用定期检测
        
        Args:
            enabled: 是否启用定期检测
        """
        if enabled:
            if not self._periodic_check_timer.isActive():
                self._periodic_check_timer.start()
        else:
            if self._periodic_check_timer.isActive():
                self._periodic_check_timer.stop()
    
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
        # 移除重入保护，因为动画需要频繁更新样式
        # if self._updating_style:
        #     return
        
        self._updating_style = True
        
        is_vertical = self.orientation() == Qt.Vertical
        # 使用动态计算的宽度
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
    
    _anim_handle_color = Property(QColor, fget=_get_anim_handle_color, fset=_set_anim_handle_color)
    
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
    def apply(widget, gesture_type=QScroller.TouchGesture, enable_mouse_drag=False):
        """
        为控件应用触摸惯性滚动

        Args:
            widget: 要应用平滑滚动的控件
            gesture_type: 手势类型
            enable_mouse_drag: 是否同时启用鼠标拖动滚动（模拟触摸滚动）
        """
        target = _get_target_widget(widget)
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, gesture_type)

        # 同时启用鼠标左键拖动滚动
        if enable_mouse_drag:
            QScroller.grabGesture(target, QScroller.LeftMouseButtonGesture)

        properties = scroller.scrollerProperties()

        properties.setScrollMetric(QScrollerProperties.OvershootDragResistanceFactor, 1.0)
        properties.setScrollMetric(QScrollerProperties.OvershootDragDistanceFactor, 0.0)
        properties.setScrollMetric(QScrollerProperties.OvershootScrollTime, 0)
        properties.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.8)
        properties.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.6)

        scroller.setScrollerProperties(properties)

        return scroller
    
    @staticmethod
    def apply_to_scroll_area(scroll_area, gesture_type=QScroller.TouchGesture, enable_mouse_drag=False, enable_smart_width=True):
        """
        为 QScrollArea 应用平滑滚动

        Args:
            scroll_area: QScrollArea 实例
            gesture_type: 手势类型
            enable_mouse_drag: 是否同时启用鼠标拖动滚动（模拟触摸滚动）
            enable_smart_width: 是否启用智能宽度控制（内容无需滚动时隐藏滚动条）
        """
        if not isinstance(scroll_area, QScrollArea):
            return None

        SmoothScroller._configure_scroll_area(scroll_area)
        SmoothScroller.apply(scroll_area, gesture_type, enable_mouse_drag)
        
        # 启用智能宽度控制
        if enable_smart_width:
            SmoothScroller._enable_smart_width(scroll_area)

        return scroll_area
    
    @staticmethod
    def _enable_smart_width(scroll_area):
        """
        为滚动区域启用智能宽度控制
        
        自动检测内容是否需要滚动，当不需要时隐藏滚动条
        """
        if not isinstance(scroll_area, QScrollArea):
            return
        
        # 获取当前滚动条
        v_scrollbar = scroll_area.verticalScrollBar()
        h_scrollbar = scroll_area.horizontalScrollBar()
        
        # 如果已经是 D_ScrollBar，设置关联
        if isinstance(v_scrollbar, D_ScrollBar):
            v_scrollbar.set_scroll_area(scroll_area)
        
        if isinstance(h_scrollbar, D_ScrollBar):
            h_scrollbar.set_scroll_area(scroll_area)
        
        # 监听内容变化
        def on_content_changed():
            # 使用单次定时器延迟检查，确保布局已更新
            from PySide6.QtCore import QTimer
            QTimer.singleShot(50, do_check)
        
        def do_check():
            try:
                if isinstance(v_scrollbar, D_ScrollBar):
                    v_scrollbar._check_and_update_width()
                if isinstance(h_scrollbar, D_ScrollBar):
                    h_scrollbar._check_and_update_width()
            except RuntimeError:
                pass
        
        # 使用事件过滤器监听尺寸变化
        class ResizeEventFilter(QObject):
            def __init__(self, callback):
                super().__init__()
                self.callback = callback
            
            def eventFilter(self, obj, event):
                from PySide6.QtCore import QEvent
                if event.type() == QEvent.Resize:
                    self.callback()
                return super().eventFilter(obj, event)
        
        # 创建并安装事件过滤器
        if not hasattr(scroll_area, '_smart_width_filter'):
            scroll_area._smart_width_filter = ResizeEventFilter(on_content_changed)
            scroll_area.installEventFilter(scroll_area._smart_width_filter)
            if scroll_area.widget():
                scroll_area.widget().installEventFilter(scroll_area._smart_width_filter)
        
        # 初始检查
        from PySide6.QtCore import QTimer
        def initial_check():
            try:
                do_check()
            except RuntimeError:
                pass
        QTimer.singleShot(100, initial_check)
    
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
