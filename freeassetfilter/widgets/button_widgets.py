#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 按钮类自定义控件
包含各种按钮类UI组件，如自定义按钮等
"""

from PyQt5.QtWidgets import (
    QPushButton, QWidget, QSizePolicy, QApplication, QStyleOptionButton
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize, QTimer, QPropertyAnimation, pyqtProperty, QEasingCurve, QParallelAnimationGroup
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PyQt5.QtWidgets import QStyle
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# 用于SVG渲染
from freeassetfilter.core.svg_renderer import SvgRenderer
import os


class CustomButton(QPushButton):
    """
    自定义按钮组件
    特点：
    - 圆角设计
    - 悬停和点击效果
    - 支持强调色和次选色方案
    - 支持文字和图标两种显示模式
    - 支持非线性动画过渡效果
    """
    
    @pyqtProperty(QColor)
    def anim_bg_color(self):
        return self._anim_bg_color
    
    @anim_bg_color.setter
    def anim_bg_color(self, color):
        self._anim_bg_color = color
        self._update_button_style()
    
    @pyqtProperty(QColor)
    def anim_border_color(self):
        return self._anim_border_color
    
    @anim_border_color.setter
    def anim_border_color(self, color):
        self._anim_border_color = color
        self._update_button_style()
    
    @pyqtProperty(QColor)
    def anim_text_color(self):
        return self._anim_text_color
    
    @anim_text_color.setter
    def anim_text_color(self, color):
        self._anim_text_color = color
        self._update_button_style()
    
    def _update_button_style(self):
        """根据当前动画颜色更新按钮样式"""
        if not hasattr(self, '_style_colors') or not self._style_colors:
            return

        scaled_border_radius = self._height // 2
        scaled_padding = f"{int(4 * self.dpi_scale)}px {int(6 * self.dpi_scale)}px"
        scaled_font_size = int(getattr(QApplication.instance(), 'default_font_size', 18) * self.dpi_scale)

        if self.button_type == "primary":
            border_width = int(0.5 * self.dpi_scale)
        else:
            border_width = int(1 * self.dpi_scale)

        # 处理颜色字符串，支持透明色
        def get_color_string(color):
            if color.alpha() < 255:
                return color.name(QColor.HexArgb)
            return color.name()

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {get_color_string(self._anim_bg_color)};
                color: {get_color_string(self._anim_text_color)};
                border: {border_width}px solid {get_color_string(self._anim_border_color)};
                border-radius: {scaled_border_radius}px;
                padding: {scaled_padding};
                font-size: {scaled_font_size}px;
                font-weight: 600;
            }}
        """)
    
    def __init__(self, text="Button", parent=None, button_type="primary", display_mode="text", height=20, tooltip_text=""):
        """
        初始化自定义按钮
        
        Args:
            text (str): 按钮文本或SVG图标路径
            parent (QWidget): 父控件
            button_type (str): 按钮类型，可选值："primary"（强调色）、"secondary"（次选色）、"normal"（普通样式）、"warning"（警告样式）
            display_mode (str): 显示模式，可选值："text"（文字显示）、"icon"（图标显示）
                              当未传入该参数或参数为空时，默认启用文字显示功能
                              当传入该参数且参数不为空时，启用图标显示功能
            height (int): 按钮高度，默认为40px，与CustomInputBox保持一致
            tooltip_text (str): 用于悬浮信息显示的不可见文本
        """
        # 图标模式下，向父类传递tooltip_text或空文本
        parent_text = text if display_mode == "text" else tooltip_text
        super().__init__(parent_text, parent)
        self.button_type = button_type
        
        # 原始高度（未缩放），用于在DPI变化时重新计算
        self._original_height = height
        
        # 显示模式：text（文字）或icon（图标）
        self._display_mode = display_mode
        # SVG图标路径
        self._icon_path = text if self._display_mode == "icon" else None
        # 渲染后的图标Pixmap
        self._icon_pixmap = None
        # 悬浮信息文本
        self._tooltip_text = tooltip_text
        
        # 获取全局字体
        app = QApplication.instance()
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        self.update_style()
        
        # 初始化动画属性
        self._init_animations()
        
        # 延迟渲染图标，确保按钮尺寸已确定
        QTimer.singleShot(0, self._render_icon)
    
    def _init_animations(self):
        """初始化按钮状态切换动画"""
        # 获取颜色配置
        app = QApplication.instance()
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        
        current_colors = settings_manager.get_setting("appearance.colors", {})
        
        def darken_color(color_hex, percentage):
            color = QColor(color_hex)
            current_theme = settings_manager.get_setting("appearance.theme", "default")
            is_dark_mode = (current_theme == "dark")

            if is_dark_mode:
                # 深色模式下变浅 - 使用加法逻辑，使黑色也能变亮
                # 从当前颜色向白色方向移动
                # 根据颜色亮度调整幅度，越暗的颜色使用越大的幅度
                luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255
                if luminance < 0.1:  # 非常暗的颜色（如纯黑）
                    adjusted_percentage = min(percentage * 2.5, 0.4)  # 最大40%
                elif luminance < 0.3:  # 较暗的颜色
                    adjusted_percentage = min(percentage * 1.8, 0.35)  # 最大35%
                else:
                    adjusted_percentage = percentage

                r = min(255, int(color.red() + (255 - color.red()) * adjusted_percentage))
                g = min(255, int(color.green() + (255 - color.green()) * adjusted_percentage))
                b = min(255, int(color.blue() + (255 - color.blue()) * adjusted_percentage))
            else:
                # 浅色模式下加深 - 使用乘法逻辑
                r = max(0, int(color.red() * (1 - percentage)))
                g = max(0, int(color.green() * (1 - percentage)))
                b = max(0, int(color.blue() * (1 - percentage)))
            return QColor(r, g, b)
        
        accent_color = current_colors.get("accent_color", "#007AFF")
        secondary_color = current_colors.get("secondary_color", "#333333")
        base_color = current_colors.get("base_color", "#ffffff")
        
        # 根据按钮类型设置颜色
        if self.button_type == "primary":
            normal_bg = QColor(accent_color)
            hover_bg = darken_color(accent_color, 0.1)
            pressed_bg = darken_color(accent_color, 0.2)
            normal_border = QColor(accent_color)
            hover_border = QColor(accent_color)
            pressed_border = QColor(accent_color)
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = QColor(base_color)
                hover_text = QColor(base_color)
                pressed_text = QColor(base_color)
        elif self.button_type == "normal":
            normal_bg = QColor(base_color)
            hover_bg = darken_color(base_color, 0.1)
            pressed_bg = darken_color(base_color, 0.2)
            normal_border = QColor(base_color)
            hover_border = QColor(base_color)
            pressed_border = QColor(base_color)
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = QColor(secondary_color)
                hover_text = QColor(secondary_color)
                pressed_text = QColor(secondary_color)
        elif self.button_type == "warning":
            warning_color = current_colors.get("notification_error", "#F44336")
            normal_bg = QColor(warning_color)
            hover_bg = darken_color(warning_color, 0.1)
            pressed_bg = darken_color(warning_color, 0.2)
            normal_border = QColor(warning_color)
            hover_border = darken_color(warning_color, 0.1)
            pressed_border = darken_color(warning_color, 0.2)
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = QColor(current_colors.get("notification_text", "#FFFFFF"))
                hover_text = QColor(current_colors.get("notification_text", "#FFFFFF"))
                pressed_text = QColor(current_colors.get("notification_text", "#FFFFFF"))
        else:  # secondary
            normal_bg = QColor(base_color)
            hover_bg = darken_color(base_color, 0.1)
            pressed_bg = darken_color(base_color, 0.2)
            normal_border = QColor(accent_color)
            hover_border = QColor(accent_color)
            pressed_border = QColor(accent_color)
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = QColor(accent_color)
                hover_text = QColor(accent_color)
                pressed_text = QColor(accent_color)
        
        # 存储颜色配置供样式更新使用
        self._style_colors = {
            'normal_bg': normal_bg,
            'hover_bg': hover_bg,
            'pressed_bg': pressed_bg,
            'normal_border': normal_border,
            'hover_border': hover_border,
            'pressed_border': pressed_border,
            'normal_text': normal_text,
            'hover_text': hover_text,
            'pressed_text': pressed_text
        }
        
        # 初始化动画颜色属性
        self._anim_bg_color = QColor(normal_bg)
        self._anim_border_color = QColor(normal_border)
        self._anim_text_color = QColor(normal_text)
        
        # 创建悬停进入动画
        self._hover_anim_group = QParallelAnimationGroup(self)
        
        self._anim_hover_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_hover_bg.setStartValue(normal_bg)
        self._anim_hover_bg.setEndValue(hover_bg)
        self._anim_hover_bg.setDuration(150)
        self._anim_hover_bg.setEasingCurve(QEasingCurve.OutCubic)
        
        self._anim_hover_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_hover_border.setStartValue(normal_border)
        self._anim_hover_border.setEndValue(hover_border)
        self._anim_hover_border.setDuration(150)
        self._anim_hover_border.setEasingCurve(QEasingCurve.OutCubic)
        
        self._anim_hover_text = QPropertyAnimation(self, b"anim_text_color")
        self._anim_hover_text.setStartValue(normal_text)
        self._anim_hover_text.setEndValue(hover_text)
        self._anim_hover_text.setDuration(150)
        self._anim_hover_text.setEasingCurve(QEasingCurve.OutCubic)
        
        self._hover_anim_group.addAnimation(self._anim_hover_bg)
        self._hover_anim_group.addAnimation(self._anim_hover_border)
        self._hover_anim_group.addAnimation(self._anim_hover_text)
        
        # 创建悬停离开动画（返回正常状态）
        self._leave_anim_group = QParallelAnimationGroup(self)
        
        self._anim_leave_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_leave_bg.setStartValue(hover_bg)
        self._anim_leave_bg.setEndValue(normal_bg)
        self._anim_leave_bg.setDuration(200)
        self._anim_leave_bg.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_leave_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_leave_border.setStartValue(hover_border)
        self._anim_leave_border.setEndValue(normal_border)
        self._anim_leave_border.setDuration(200)
        self._anim_leave_border.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_leave_text = QPropertyAnimation(self, b"anim_text_color")
        self._anim_leave_text.setStartValue(hover_text)
        self._anim_leave_text.setEndValue(normal_text)
        self._anim_leave_text.setDuration(200)
        self._anim_leave_text.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._leave_anim_group.addAnimation(self._anim_leave_bg)
        self._leave_anim_group.addAnimation(self._anim_leave_border)
        self._leave_anim_group.addAnimation(self._anim_leave_text)
        
        # 创建按下动画
        self._press_anim_group = QParallelAnimationGroup(self)
        
        self._anim_press_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_press_bg.setStartValue(hover_bg)
        self._anim_press_bg.setEndValue(pressed_bg)
        self._anim_press_bg.setDuration(80)
        self._anim_press_bg.setEasingCurve(QEasingCurve.OutQuad)
        
        self._anim_press_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_press_border.setStartValue(hover_border)
        self._anim_press_border.setEndValue(pressed_border)
        self._anim_press_border.setDuration(80)
        self._anim_press_border.setEasingCurve(QEasingCurve.OutQuad)
        
        self._anim_press_text = QPropertyAnimation(self, b"anim_text_color")
        self._anim_press_text.setStartValue(hover_text)
        self._anim_press_text.setEndValue(pressed_text)
        self._anim_press_text.setDuration(80)
        self._anim_press_text.setEasingCurve(QEasingCurve.OutQuad)
        
        self._press_anim_group.addAnimation(self._anim_press_bg)
        self._press_anim_group.addAnimation(self._anim_press_border)
        self._press_anim_group.addAnimation(self._anim_press_text)
        
        # 创建释放动画（返回悬停状态）
        self._release_anim_group = QParallelAnimationGroup(self)
        
        self._anim_release_bg = QPropertyAnimation(self, b"anim_bg_color")
        self._anim_release_bg.setStartValue(pressed_bg)
        self._anim_release_bg.setEndValue(hover_bg)
        self._anim_release_bg.setDuration(150)
        self._anim_release_bg.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_release_border = QPropertyAnimation(self, b"anim_border_color")
        self._anim_release_border.setStartValue(pressed_border)
        self._anim_release_border.setEndValue(hover_border)
        self._anim_release_border.setDuration(150)
        self._anim_release_border.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._anim_release_text = QPropertyAnimation(self, b"anim_text_color")
        self._anim_release_text.setStartValue(pressed_text)
        self._anim_release_text.setEndValue(hover_text)
        self._anim_release_text.setDuration(150)
        self._anim_release_text.setEasingCurve(QEasingCurve.InOutQuad)
        
        self._release_anim_group.addAnimation(self._anim_release_bg)
        self._release_anim_group.addAnimation(self._anim_release_border)
        self._release_anim_group.addAnimation(self._anim_release_text)
        
        # 应用初始样式
        self._update_button_style()
    
    def enterEvent(self, event):
        """鼠标进入事件，触发动画"""
        # 先停止可能正在进行的动画
        self._leave_anim_group.stop()
        self._hover_anim_group.stop()
        self._release_anim_group.stop()
        
        # 根据当前状态决定动画
        colors = self._style_colors
        if self._anim_bg_color == colors['pressed_bg']:
            # 如果当前是按下状态，释放到悬停
            self._release_anim_group.start()
        else:
            # 否则从当前状态动画到悬停状态
            self._anim_hover_bg.setStartValue(self._anim_bg_color)
            self._anim_hover_bg.setEndValue(colors['hover_bg'])
            self._anim_hover_border.setStartValue(self._anim_border_color)
            self._anim_hover_border.setEndValue(colors['hover_border'])
            self._anim_hover_text.setStartValue(self._anim_text_color)
            self._anim_hover_text.setEndValue(colors['hover_text'])
            self._hover_anim_group.start()
        
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件，触发动画"""
        self._hover_anim_group.stop()
        self._press_anim_group.stop()
        
        colors = self._style_colors
        self._anim_leave_bg.setStartValue(self._anim_bg_color)
        self._anim_leave_bg.setEndValue(colors['normal_bg'])
        self._anim_leave_border.setStartValue(self._anim_border_color)
        self._anim_leave_border.setEndValue(colors['normal_border'])
        self._anim_leave_text.setStartValue(self._anim_text_color)
        self._anim_leave_text.setEndValue(colors['normal_text'])
        self._leave_anim_group.start()
        
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        """鼠标按下事件，触发动画"""
        self._hover_anim_group.stop()
        self._leave_anim_group.stop()
        
        colors = self._style_colors
        self._anim_press_bg.setStartValue(self._anim_bg_color)
        self._anim_press_bg.setEndValue(colors['pressed_bg'])
        self._anim_press_border.setStartValue(self._anim_border_color)
        self._anim_press_border.setEndValue(colors['pressed_border'])
        self._anim_press_text.setStartValue(self._anim_text_color)
        self._anim_press_text.setEndValue(colors['pressed_text'])
        self._press_anim_group.start()
        
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件，触发动画"""
        self._press_anim_group.stop()
        
        colors = self._style_colors
        # 判断鼠标是否在按钮上，决定返回到悬停状态还是正常状态
        if self.rect().contains(event.pos()):
            # 鼠标在按钮上，返回到悬停状态
            target_bg = colors['hover_bg']
            target_border = colors['hover_border']
            target_text = colors['hover_text']
        else:
            # 鼠标不在按钮上，直接返回到正常状态
            target_bg = colors['normal_bg']
            target_border = colors['normal_border']
            target_text = colors['normal_text']
        
        self._anim_release_bg.setStartValue(self._anim_bg_color)
        self._anim_release_bg.setEndValue(target_bg)
        self._anim_release_border.setStartValue(self._anim_border_color)
        self._anim_release_border.setEndValue(target_border)
        self._anim_release_text.setStartValue(self._anim_text_color)
        self._anim_release_text.setEndValue(target_text)
        self._release_anim_group.start()
        
        super().mouseReleaseEvent(event)
    
    def update_style(self):
        """
        更新按钮样式
        """
        # 获取应用实例和最新的DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 从应用实例获取设置管理器，而不是创建新实例
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
        else:
            # 回退方案：如果应用实例中没有settings_manager，再创建新实例
            from freeassetfilter.core.settings_manager import SettingsManager
            settings_manager = SettingsManager()
        
        current_colors = settings_manager.get_setting("appearance.colors", {})
        
        # 从基础颜色计算其他颜色（如果不存在的话）
        def darken_color(color_hex, percentage):
            color = QColor(color_hex)
            # 获取当前主题模式
            current_theme = settings_manager.get_setting("appearance.theme", "default")
            is_dark_mode = (current_theme == "dark")

            if is_dark_mode:
                # 深色模式下变浅 - 使用加法逻辑，使黑色也能变亮
                # 从当前颜色向白色方向移动
                # 根据颜色亮度调整幅度，越暗的颜色使用越大的幅度
                luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255
                if luminance < 0.1:  # 非常暗的颜色（如纯黑）
                    adjusted_percentage = min(percentage * 2.5, 0.4)  # 最大40%
                elif luminance < 0.3:  # 较暗的颜色
                    adjusted_percentage = min(percentage * 1.8, 0.35)  # 最大35%
                else:
                    adjusted_percentage = percentage

                r = min(255, int(color.red() + (255 - color.red()) * adjusted_percentage))
                g = min(255, int(color.green() + (255 - color.green()) * adjusted_percentage))
                b = min(255, int(color.blue() + (255 - color.blue()) * adjusted_percentage))
            else:
                # 浅色模式下加深 - 使用乘法逻辑
                r = max(0, int(color.red() * (1 - percentage)))
                g = max(0, int(color.green() * (1 - percentage)))
                b = max(0, int(color.blue() * (1 - percentage)))
            return f"#{r:02x}{g:02x}{b:02x}"

        # 获取基础颜色
        accent_color = current_colors.get("accent_color", "#007AFF")
        secondary_color = current_colors.get("secondary_color", "#333333")
        normal_color = current_colors.get("normal_color", "#e0e0e0")
        auxiliary_color = current_colors.get("auxiliary_color", "#f1f3f5")
        base_color = current_colors.get("base_color", "#ffffff")
        
        # 窗口颜色
        current_colors["window_background"] = auxiliary_color  # 辅助色
        current_colors["window_border"] = normal_color  # 普通色
        
        # 强调样式按钮颜色
        current_colors["button_primary_normal"] = accent_color  # 强调色
        current_colors["button_primary_hover"] = darken_color(accent_color, 0.1)  # 强调色加深10%
        current_colors["button_primary_pressed"] = darken_color(accent_color, 0.2)  # 强调色加深20%
        current_colors["button_primary_text"] = base_color  # 底层色
        current_colors["button_primary_border"] = accent_color  # 强调色
        
        # 普通样式按钮颜色
        current_colors["button_normal_normal"] = base_color  # 底层色
        current_colors["button_normal_hover"] = darken_color(base_color, 0.1)  # 底层色加深10%
        current_colors["button_normal_pressed"] = darken_color(base_color, 0.2)  # 底层色加深20%
        current_colors["button_normal_text"] = secondary_color  # 次选色
        current_colors["button_normal_border"] = secondary_color  # 次选色
        
        # 次选样式按钮颜色
        current_colors["button_secondary_normal"] = base_color  # 底层色
        current_colors["button_secondary_hover"] = darken_color(base_color, 0.1)  # 底层色加深10%
        current_colors["button_secondary_pressed"] = darken_color(base_color, 0.2)  # 底层色加深20%
        current_colors["button_secondary_text"] = accent_color  # 强调色
        current_colors["button_secondary_border"] = accent_color  # 强调色
        
        # 文字颜色
        current_colors["text_normal"] = secondary_color  # 次选色
        current_colors["text_disabled"] = auxiliary_color  # 辅助色
        current_colors["text_highlight"] = accent_color  # 强调色
        current_colors["text_placeholder"] = normal_color  # 普通色
        
        # 输入框颜色
        current_colors["input_background"] = base_color  # 底层色
        current_colors["input_border"] = normal_color  # 普通色
        current_colors["input_focus_border"] = accent_color  # 强调色
        current_colors["input_text"] = secondary_color  # 次选色
        
        # 列表颜色
        current_colors["list_background"] = auxiliary_color  # 辅助色
        current_colors["list_item_normal"] = normal_color  # 普通色
        current_colors["list_item_hover"] = darken_color(normal_color, 0.1)  # 普通色加深10%
        current_colors["list_item_selected"] = accent_color  # 强调色
        current_colors["list_item_text"] = secondary_color  # 次选色
        
        # 滑块颜色
        current_colors["slider_track"] = base_color  # 底层色
        current_colors["slider_handle"] = accent_color  # 强调色
        current_colors["slider_handle_hover"] = accent_color  # 强调色
        
        # 进度条颜色
        current_colors["progress_bar_bg"] = base_color  # 底层色
        current_colors["progress_bar_fg"] = accent_color  # 强调色
        
        # 移除通用按钮颜色（向后兼容类）
        if "button_normal" in current_colors:
            del current_colors["button_normal"]
        if "button_hover" in current_colors:
            del current_colors["button_hover"]
        if "button_pressed" in current_colors:
            del current_colors["button_pressed"]
        if "button_text" in current_colors:
            del current_colors["button_text"]
        if "button_border" in current_colors:
            del current_colors["button_border"]
        
        # 使用最新的DPI缩放因子重新计算按钮高度（保持原始值，因为我们已经在初始化时减半了）
        self._height = int(self._original_height * self.dpi_scale)
        
        # 添加阴影效果，应用最新的DPI缩放
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(int(1 * self.dpi_scale))
        shadow.setOffset(0, int(1 * self.dpi_scale))
        # 正确设置阴影颜色：黑色，带有适当的透明度
        shadow.setColor(QColor(0, 0, 0, 0))  # 使用黑色阴影更明显
        self.setGraphicsEffect(shadow)
        
        # 设置固定高度，与CustomInputBox保持一致
        self.setFixedHeight(self._height)
        
        # 从app对象获取全局默认字体大小
        default_font_size = getattr(app, 'default_font_size', 18)
        
        # 应用最新的DPI缩放因子到按钮样式参数
        # 计算适合的圆角半径，确保在各种尺寸下都合适
        # 所有按钮都使用高度的一半作为圆角半径，确保圆角完整覆盖边缘
        scaled_border_radius = self._height // 2
        scaled_padding = f"{int(4 * self.dpi_scale)}px {int(6 * self.dpi_scale)}px"
        scaled_font_size = int(default_font_size * self.dpi_scale)
        scaled_border_width = int(1 * self.dpi_scale)  # 边框宽度随DPI缩放
        scaled_primary_border_width = int(0.5 * self.dpi_scale)  # 主要按钮边框宽度随DPI缩放
        
        # 更新全局字体大小，确保文字显示正确
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 设置大小策略，允许按钮根据内容调整宽度
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        # 如果是图标模式，设置固定宽度等于高度，保持正方形
        if self._display_mode == "icon":
            self.setFixedWidth(self._height)
        else:
            # 文字模式，确保按钮有足够的宽度
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            # 设置最小宽度，确保短文字按钮不会太小，应用DPI缩放（调整为原始的一半）
            self.setMinimumWidth(int(25 * self.dpi_scale))
            self.setMaximumWidth(16777215)
            # 确保按钮宽度能容纳文字内容
            self.adjustSize()
            # 根据文本内容计算并设置最小宽度，确保文本完整显示
            self._update_minimum_width_for_text()
        
        if self.button_type == "primary":
            # 强调色方案
            # 使用主题颜色
            bg_color = current_colors.get("button_primary_normal", accent_color)
            hover_color = current_colors.get("button_primary_hover", darken_color(accent_color, 0.1))
            pressed_color = current_colors.get("button_primary_pressed", darken_color(accent_color, 0.2))
            text_color = current_colors.get("button_primary_text", base_color)
            border_color = current_colors.get("button_primary_border", accent_color)
            disabled_bg = "#888888"
            disabled_text = "#FFFFFF"
            disabled_border = "#666666"
            
            # 对于图标按钮，文字颜色设为透明
            if self._display_mode == "icon":
                # 图标模式下文字颜色设为透明
                text_color = "transparent"
                pressed_text_color = "transparent"
            else:
                # 文字模式下使用正常文字颜色
                pressed_text_color = text_color
            
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: {scaled_primary_border_width}px solid {border_color};
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                    border-color: {hover_color};
                }}
                QPushButton:pressed {{
                    background-color: {pressed_color};
                    color: {pressed_text_color};
                    border-color: {pressed_color};
                }}
                QPushButton:disabled {{
                    background-color: {disabled_bg};
                    color: {disabled_text};
                    border-color: {disabled_border};
                }}
            """)
        elif self.button_type == "normal":
            # 普通方案
            # 使用主题颜色
            bg_color = current_colors.get("button_normal_normal", current_colors.get("window_background", "#1E1E1E"))
            hover_color = current_colors.get("button_normal_hover", current_colors.get("list_item_hover", "#3C3C3C"))
            pressed_color = current_colors.get("button_normal_pressed", current_colors.get("list_item_selected", "#4ECDC4"))
            text_color = current_colors.get("button_normal_text", current_colors.get("text_normal", "#FFFFFF"))
            border_color = current_colors.get("button_normal_border", current_colors.get("window_border", "#3C3C3C"))
            disabled_bg = "#2D2D2D"
            disabled_text = "#666666"
            disabled_border = "#444444"
            
            # 对于图标按钮，文字颜色设为透明
            if self._display_mode == "icon":
                # 图标模式下文字颜色设为透明
                text_color = "transparent"
                pressed_text_color = "transparent"
            else:
                # 文字模式下使用正常文字颜色
                pressed_text_color = text_color
            
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: {scaled_primary_border_width}px solid {border_color};
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                    border-color: {hover_color};
                }}
                QPushButton:pressed {{
                    background-color: {hover_color};  /* 使用hover时的颜色 */
                    color: {pressed_text_color};
                    border-color: {border_color};  /* 使用默认状态的边框颜色 */
                }}
                QPushButton:disabled {{
                    background-color: {disabled_bg};
                    color: {disabled_text};
                    border-color: {disabled_border};
                }}
            """)
        elif self.button_type == "warning":
            # 警告按钮方案
            # 使用主题颜色
            warning_color = current_colors.get("notification_error", "#F44336")
            bg_color = current_colors.get("button_warning_normal", warning_color)
            hover_color = current_colors.get("button_warning_hover", darken_color(warning_color, 0.1))
            pressed_color = current_colors.get("button_warning_pressed", darken_color(warning_color, 0.2))
            text_color = current_colors.get("button_warning_text", current_colors.get("notification_text", "#FFFFFF"))
            border_color = current_colors.get("button_warning_border", warning_color)
            disabled_bg = "#FF8A80"
            disabled_text = "#FFFFFF"
            disabled_border = "#FF5252"
            
            # 对于图标按钮，文字颜色设为透明
            if self._display_mode == "icon":
                # 图标模式下文字颜色设为透明
                text_color = "transparent"
                pressed_text_color = "transparent"
            else:
                # 文字模式下使用正常文字颜色
                pressed_text_color = text_color
            
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: {scaled_primary_border_width}px solid {border_color};
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                    border-color: {hover_color};
                }}
                QPushButton:pressed {{
                    background-color: {pressed_color};
                    color: {pressed_text_color};
                    border-color: {pressed_color};
                }}
                QPushButton:disabled {{
                    background-color: {disabled_bg};
                    color: {disabled_text};
                    border-color: {disabled_border};
                }}
            """)
        else:  # secondary
            # 次选按钮方案：确保在白色背景下可见
            # 使用主题颜色
            bg_color = current_colors.get("button_secondary_normal", current_colors.get("window_background", "#1E1E1E"))
            hover_color = current_colors.get("button_secondary_hover", current_colors.get("list_item_hover", "#3C3C3C"))
            pressed_color = current_colors.get("button_secondary_pressed", current_colors.get("list_item_selected", "#4ECDC4"))
            text_color = current_colors.get("button_secondary_text", current_colors.get("text_highlight", "#4ECDC4"))
            border_color = current_colors.get("button_secondary_border", current_colors.get("text_highlight", "#4ECDC4"))
            disabled_bg = "#2D2D2D"
            disabled_text = "#666666"
            disabled_border = "#444444"
            
            # 对于图标按钮，文字颜色设为透明
            if self._display_mode == "icon":
                # 图标模式下文字颜色设为透明
                text_color = "transparent"
                pressed_text_color = "transparent"
            else:
                # 文字模式下使用正常文字颜色
                pressed_text_color = text_color
            
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {bg_color};
                    color: {text_color};
                    border: {scaled_border_width}px solid {border_color};
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {hover_color};
                    border-color: {border_color};  /* 使用默认状态的边框颜色 */
                }}
                QPushButton:pressed {{
                    background-color: {hover_color};  /* 使用hover时的颜色 */
                    color: {pressed_text_color};
                    border-color: {border_color};  /* 使用默认状态的边框颜色 */
                }}
                QPushButton:disabled {{
                    background-color: {disabled_bg};
                    color: {disabled_text};
                    border-color: {disabled_border};
                }}
            """)
        
        # 更新动画颜色配置
        self._update_anim_colors(current_colors, accent_color, secondary_color, base_color, settings_manager)
    
    def _update_anim_colors(self, current_colors, accent_color, secondary_color, base_color, settings_manager=None):
        """更新动画颜色配置"""
        if not hasattr(self, '_style_colors'):
            return

        # 如果没有传入settings_manager，尝试从应用实例获取
        if settings_manager is None:
            app = QApplication.instance()
            if hasattr(app, 'settings_manager'):
                settings_manager = app.settings_manager
            else:
                from freeassetfilter.core.settings_manager import SettingsManager
                settings_manager = SettingsManager()
        
        def get_color(color_hex):
            return QColor(color_hex)
        
        def darken_color_qcolor(color_hex, percentage):
            color = QColor(color_hex)
            # 从settings_manager获取当前主题模式
            current_theme = settings_manager.get_setting("appearance.theme", "default")
            is_dark_mode = (current_theme == "dark")

            if is_dark_mode:
                # 深色模式下变浅 - 使用加法逻辑，使黑色也能变亮
                # 从当前颜色向白色方向移动
                # 根据颜色亮度调整幅度，越暗的颜色使用越大的幅度
                luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255
                if luminance < 0.1:  # 非常暗的颜色（如纯黑）
                    adjusted_percentage = min(percentage * 2.5, 0.4)  # 最大40%
                elif luminance < 0.3:  # 较暗的颜色
                    adjusted_percentage = min(percentage * 1.8, 0.35)  # 最大35%
                else:
                    adjusted_percentage = percentage

                r = min(255, int(color.red() + (255 - color.red()) * adjusted_percentage))
                g = min(255, int(color.green() + (255 - color.green()) * adjusted_percentage))
                b = min(255, int(color.blue() + (255 - color.blue()) * adjusted_percentage))
            else:
                # 浅色模式下加深 - 使用乘法逻辑
                r = max(0, int(color.red() * (1 - percentage)))
                g = max(0, int(color.green() * (1 - percentage)))
                b = max(0, int(color.blue() * (1 - percentage)))
            return QColor(r, g, b)
        
        if self.button_type == "primary":
            normal_bg = get_color(current_colors.get("button_primary_normal", accent_color))
            hover_bg = get_color(current_colors.get("button_primary_hover", darken_color_qcolor(accent_color, 0.1)))
            pressed_bg = get_color(current_colors.get("button_primary_pressed", darken_color_qcolor(accent_color, 0.2)))
            normal_border = get_color(current_colors.get("button_primary_border", accent_color))
            hover_border = get_color(current_colors.get("button_primary_border", accent_color))
            pressed_border = get_color(current_colors.get("button_primary_border", accent_color))
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = get_color(current_colors.get("button_primary_text", base_color))
                hover_text = get_color(current_colors.get("button_primary_text", base_color))
                pressed_text = get_color(current_colors.get("button_primary_text", base_color))
        elif self.button_type == "normal":
            normal_bg = get_color(current_colors.get("button_normal_normal", base_color))
            hover_bg = get_color(current_colors.get("button_normal_hover", darken_color_qcolor(base_color, 0.1)))
            pressed_bg = get_color(current_colors.get("button_normal_pressed", darken_color_qcolor(base_color, 0.2)))
            normal_border = normal_bg
            hover_border = hover_bg
            pressed_border = pressed_bg
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = get_color(current_colors.get("button_normal_text", secondary_color))
                hover_text = get_color(current_colors.get("button_normal_text", secondary_color))
                pressed_text = get_color(current_colors.get("button_normal_text", secondary_color))
        elif self.button_type == "warning":
            warning_color = current_colors.get("notification_error", "#F44336")
            normal_bg = get_color(current_colors.get("button_warning_normal", warning_color))
            hover_bg = get_color(current_colors.get("button_warning_hover", darken_color_qcolor(warning_color, 0.1)))
            pressed_bg = get_color(current_colors.get("button_warning_pressed", darken_color_qcolor(warning_color, 0.2)))
            normal_border = get_color(current_colors.get("button_warning_border", warning_color))
            hover_border = get_color(current_colors.get("button_warning_border", darken_color_qcolor(warning_color, 0.1)))
            pressed_border = get_color(current_colors.get("button_warning_border", darken_color_qcolor(warning_color, 0.2)))
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = get_color(current_colors.get("button_warning_text", current_colors.get("notification_text", "#FFFFFF")))
                hover_text = get_color(current_colors.get("button_warning_text", current_colors.get("notification_text", "#FFFFFF")))
                pressed_text = get_color(current_colors.get("button_warning_text", current_colors.get("notification_text", "#FFFFFF")))
        else:  # secondary
            normal_bg = get_color(current_colors.get("button_secondary_normal", base_color))
            hover_bg = get_color(current_colors.get("button_secondary_hover", darken_color_qcolor(base_color, 0.1)))
            pressed_bg = get_color(current_colors.get("button_secondary_pressed", darken_color_qcolor(base_color, 0.2)))
            normal_border = get_color(current_colors.get("button_secondary_border", accent_color))
            hover_border = get_color(current_colors.get("button_secondary_border", accent_color))
            pressed_border = get_color(current_colors.get("button_secondary_border", accent_color))
            if self._display_mode == "icon":
                # 图标模式下文本颜色设为透明
                transparent = QColor(0, 0, 0, 0)
                normal_text = transparent
                hover_text = transparent
                pressed_text = transparent
            else:
                normal_text = get_color(current_colors.get("button_secondary_text", accent_color))
                hover_text = get_color(current_colors.get("button_secondary_text", accent_color))
                pressed_text = get_color(current_colors.get("button_secondary_text", accent_color))
        
        self._style_colors = {
            'normal_bg': normal_bg,
            'hover_bg': hover_bg,
            'pressed_bg': pressed_bg,
            'normal_border': normal_border,
            'hover_border': hover_border,
            'pressed_border': pressed_border,
            'normal_text': normal_text,
            'hover_text': hover_text,
            'pressed_text': pressed_text
        }
        
        # 更新动画的起始和结束值
        self._anim_hover_bg.setStartValue(normal_bg)
        self._anim_hover_bg.setEndValue(hover_bg)
        self._anim_hover_border.setStartValue(normal_border)
        self._anim_hover_border.setEndValue(hover_border)
        self._anim_hover_text.setStartValue(normal_text)
        self._anim_hover_text.setEndValue(hover_text)
        
        self._anim_leave_bg.setStartValue(hover_bg)
        self._anim_leave_bg.setEndValue(normal_bg)
        self._anim_leave_border.setStartValue(hover_border)
        self._anim_leave_border.setEndValue(normal_border)
        self._anim_leave_text.setStartValue(hover_text)
        self._anim_leave_text.setEndValue(normal_text)
        
        self._anim_press_bg.setStartValue(hover_bg)
        self._anim_press_bg.setEndValue(pressed_bg)
        self._anim_press_border.setStartValue(hover_border)
        self._anim_press_border.setEndValue(pressed_border)
        self._anim_press_text.setStartValue(hover_text)
        self._anim_press_text.setEndValue(pressed_text)
        
        self._anim_release_bg.setStartValue(pressed_bg)
        self._anim_release_bg.setEndValue(hover_bg)
        self._anim_release_border.setStartValue(pressed_border)
        self._anim_release_border.setEndValue(hover_border)
        self._anim_release_text.setStartValue(pressed_text)
        self._anim_release_text.setEndValue(hover_text)

        # 同步当前动画属性值与新的normal状态一致，避免按钮类型切换后出现颜色闪烁
        self._anim_bg_color = QColor(normal_bg)
        self._anim_border_color = QColor(normal_border)
        self._anim_text_color = QColor(normal_text)

    def set_primary(self, is_primary):
        """
        设置按钮是否使用强调色（兼容旧接口）
        
        Args:
            is_primary (bool): 是否使用强调色
        """
        self.button_type = "primary" if is_primary else "secondary"
        self.update_style()
        self.resizeEvent(None)  # 触发resizeEvent，更新圆角半径
    
    def set_button_type(self, button_type):
        """
        设置按钮类型
        
        Args:
            button_type (str): 按钮类型，可选值："primary"、"secondary"、"normal"、"warning"
        """
        self.button_type = button_type
        self.update_style()
        self.resizeEvent(None)  # 触发resizeEvent，更新圆角半径
    
    def setText(self, text):
        """
        重写setText方法，在设置文本后自动更新最小宽度
        
        Args:
            text (str): 按钮文本
        """
        super().setText(text)
        # 文本改变后，重新计算最小宽度
        if self._display_mode == "text":
            self._update_minimum_width_for_text()
    
    def _update_minimum_width_for_text(self):
        """
        根据文本内容计算并设置按钮的最小宽度，确保文本完整显示不被裁切
        
        计算逻辑：
        - 使用当前字体计算文本的宽度
        - 加上左右内边距（padding）
        - 加上左右边框宽度
        - 加上额外的安全边距，确保文本不会被裁切
        """
        if self._display_mode == "icon":
            return
        
        # 获取当前文本
        text = self.text()
        if not text:
            return
        
        # 使用当前字体计算文本宽度
        font_metrics = self.fontMetrics()
        text_width = font_metrics.horizontalAdvance(text)
        
        # 获取样式参数（与update_style中保持一致）
        scaled_padding_horizontal = int(6 * self.dpi_scale)  # 水平方向内边距
        border_width = int(0.5 * self.dpi_scale) if self.button_type == "primary" else int(1 * self.dpi_scale)
        
        # 计算最小宽度：文本宽度 + 左右内边距 + 左右边框 + 安全边距
        # 安全边距用于防止某些字体或渲染差异导致的裁切
        safety_margin = int(4 * self.dpi_scale)
        min_width = text_width + (scaled_padding_horizontal * 2) + (border_width * 2) + safety_margin
        
        # 确保最小宽度不会小于预设的最小值
        absolute_min = int(25 * self.dpi_scale)
        min_width = max(min_width, absolute_min)
        
        # 设置最小宽度
        self.setMinimumWidth(min_width)
    
    def _render_icon(self):
        """
        渲染SVG图标为QPixmap
        调用项目中已开发的SVG渲染组件进行图标渲染
        """
        try:
            if self._icon_path and os.path.exists(self._icon_path):
                # 计算合适的图标大小，确保图标不会超出按钮范围
                # 先获取按钮的实际尺寸，考虑DPI缩放
                button_size = min(self.width(), self.height())
                # 图标大小为按钮尺寸的90%，不直接乘以DPI缩放因子（在SvgRenderer中处理）
                icon_size = button_size * 0.52
                # 使用项目中已有的SvgRenderer渲染SVG图标，传递DPI缩放因子
                self._icon_pixmap = SvgRenderer.render_svg_to_pixmap(self._icon_path, int(icon_size), self.dpi_scale)
            else:
                self._icon_pixmap = None
        except Exception as e:
            print(f"渲染SVG图标失败: {e}")
            self._icon_pixmap = None
    
    def resizeEvent(self, event):
        """
        大小变化事件
        如果是图标模式，重新渲染图标
        注意：不再动态修改样式表，而是在update_style()中一次性设置
        """
        super().resizeEvent(event)
        
        # 检查DPI缩放因子是否变化
        app = QApplication.instance()
        new_dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 如果DPI缩放因子发生变化，更新按钮样式
        if new_dpi_scale != self.dpi_scale:
            self.update_style()
        
        # 如果是图标模式，重新渲染图标以适应新尺寸
        if self._display_mode == "icon":
            self._render_icon()
    
    def paintEvent(self, event):
        """
        绘制按钮
        如果是图标模式，先调用父类绘制按钮样式但不绘制文字，再直接渲染SVG；否则调用父类绘制文字
        """
        if self._display_mode == "icon":
            # 获取当前绘制器
            painter = QPainter(self)
            
            # 保存绘制器状态
            painter.save()
            
            # 绘制按钮样式（背景、边框等）
            # 我们不调用super().paintEvent(event)，因为它会绘制文字
            # 而是直接绘制按钮的背景和边框
            style_option = QStyleOptionButton()
            self.initStyleOption(style_option)
            
            # 绘制按钮背景和边框
            self.style().drawControl(QStyle.CE_PushButtonBevel, style_option, painter, self)
            self.style().drawControl(QStyle.CE_PushButton, style_option, painter, self)
            
            # 恢复绘制器状态
            painter.restore()
            
            # 如果有图标路径，使用SvgRenderer预处理并渲染SVG
            if self._icon_path and os.path.exists(self._icon_path):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
                
                try:
                    from PyQt5.QtSvg import QSvgRenderer
                    from PyQt5.QtCore import QRectF
                    
                    # 读取SVG文件内容并进行颜色替换预处理
                    with open(self._icon_path, 'r', encoding='utf-8') as f:
                        svg_content = f.read()

                    # 预处理SVG内容：替换颜色
                    # 强调样式（primary）按钮的SVG图标需要将#000000替换为base_color
                    force_black_to_base = (self.button_type == "primary")
                    svg_content = SvgRenderer._replace_svg_colors(svg_content, force_black_to_base=force_black_to_base)
                    
                    # 使用预处理后的内容创建QSvgRenderer
                    svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
                    
                    # 计算合适的图标大小，确保图标不会超出按钮范围
                    button_size = min(self.width(), self.height())
                    icon_size = button_size * 0.52
                    
                    # 计算图标绘制位置（居中）
                    icon_rect = painter.window()
                    icon_rect.setWidth(int(icon_size))
                    icon_rect.setHeight(int(icon_size))
                    icon_rect.moveCenter(painter.window().center())
                    
                    # 将QRect转换为QRectF，因为QSvgRenderer.render方法期望第二个参数是QRectF类型
                    icon_rectf = QRectF(icon_rect)
                    
                    # 直接渲染SVG到按钮上
                    svg_renderer.render(painter, icon_rectf)
                except Exception as e:
                    print(f"直接渲染SVG图标失败: {e}")
                    # 如果直接渲染失败，回退到使用位图
                    if self._icon_pixmap:
                        # 计算图标绘制位置（居中）
                        icon_rect = self._icon_pixmap.rect()
                        icon_rect.moveCenter(painter.window().center())
                        
                        # 绘制图标
                        painter.drawPixmap(icon_rect, self._icon_pixmap)
                
                painter.end()
        else:
            # 文字模式，调用父类绘制文字
            super().paintEvent(event)


from freeassetfilter.widgets.smooth_scroller import D_ScrollBar
