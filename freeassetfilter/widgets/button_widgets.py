#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 按钮类自定义控件
包含各种按钮类UI组件，如自定义按钮等
"""

from PyQt5.QtWidgets import (
    QPushButton, QWidget, QSizePolicy, QApplication, QStyleOptionButton
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize, QTimer
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
    """
    
    def __init__(self, text="Button", parent=None, button_type="primary", display_mode="text", height=40, tooltip_text=""):
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
        
        # 延迟渲染图标，确保按钮尺寸已确定
        QTimer.singleShot(0, self._render_icon)
    
    def update_style(self):
        """
        更新按钮样式
        """
        # 获取应用实例和最新的DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取当前主题颜色，如果没有则使用默认值
        from freeassetfilter.core.settings_manager import SettingsManager
        settings_manager = SettingsManager()
        current_colors = settings_manager.get_setting("appearance.colors", {})
        
        # 使用最新的DPI缩放因子重新计算按钮高度
        self._height = int(self._original_height * self.dpi_scale)
        
        # 添加阴影效果，应用最新的DPI缩放
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(int(2 * self.dpi_scale))
        shadow.setOffset(0, int(2 * self.dpi_scale))
        # 正确设置阴影颜色：黑色，带有适当的透明度
        shadow.setColor(QColor(0, 0, 0, 0))  # 使用黑色阴影更明显
        self.setGraphicsEffect(shadow)
        
        # 设置固定高度，与CustomInputBox保持一致
        self.setFixedHeight(self._height)
        
        # 从app对象获取全局默认字体大小
        default_font_size = getattr(app, 'default_font_size', 18)
        
        # 应用最新的DPI缩放因子到按钮样式参数
        # 计算适合的圆角半径，确保在各种尺寸下都合适
        # 对于图标按钮，使用高度的一半作为圆角半径
        # 对于文字按钮，使用固定的圆角半径（20px）
        if self._display_mode == "icon":
            scaled_border_radius = self._height // 2
        else:
            scaled_border_radius = int(20 * self.dpi_scale)
        scaled_padding = f"{int(8 * self.dpi_scale)}px {int(12 * self.dpi_scale)}px"
        scaled_font_size = int(default_font_size * self.dpi_scale)
        scaled_border_width = int(2 * self.dpi_scale)  # 边框宽度随DPI缩放
        scaled_primary_border_width = int(1 * self.dpi_scale)  # 主要按钮边框宽度随DPI缩放
        
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
            # 设置最小宽度，确保短文字按钮不会太小，应用DPI缩放
            self.setMinimumWidth(int(100 * self.dpi_scale))
            self.setMaximumWidth(16777215)
            # 确保按钮宽度能容纳文字内容
            self.adjustSize()
        
        if self.button_type == "primary":
            # 强调色方案
            # 使用主题颜色
            bg_color = current_colors.get("button_primary_normal", current_colors.get("button_normal", "#2D2D2D"))
            hover_color = current_colors.get("button_primary_hover", current_colors.get("button_hover", "#3C3C3C"))
            pressed_color = current_colors.get("button_primary_pressed", current_colors.get("button_pressed", "#4C4C4C"))
            text_color = current_colors.get("button_primary_text", current_colors.get("button_text", "#FFFFFF"))
            border_color = current_colors.get("button_primary_border", current_colors.get("button_border", "#5C5C5C"))
            disabled_bg = "#888888"
            disabled_text = "#FFFFFF"
            disabled_border = "#666666"
            
            # 对于图标按钮，文字颜色与背景颜色一致，按下时等于按下时的背景颜色
            if self._display_mode == "icon":
                # 图标模式下文字颜色与背景颜色一致
                text_color = bg_color
                pressed_text_color = pressed_color
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
            
            # 对于图标按钮，文字颜色与背景颜色一致，按下时等于按下时的背景颜色
            if self._display_mode == "icon":
                # 图标模式下文字颜色与背景颜色一致
                text_color = bg_color
                pressed_text_color = pressed_color
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
        elif self.button_type == "warning":
            # 警告按钮方案
            # 使用主题颜色
            bg_color = current_colors.get("notification_error", "#F44336")
            hover_color = "#E63946"
            pressed_color = "#D62828"
            text_color = current_colors.get("notification_text", "#FFFFFF")
            border_color = current_colors.get("notification_error", "#F44336")
            disabled_bg = "#FF8A80"
            disabled_text = "#FFFFFF"
            disabled_border = "#FF5252"
            
            # 对于图标按钮，文字颜色与背景颜色一致，按下时等于按下时的背景颜色
            if self._display_mode == "icon":
                # 图标模式下文字颜色与背景颜色一致
                text_color = bg_color
                pressed_text_color = pressed_color
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
            
            # 对于图标按钮，文字颜色与背景颜色一致，按下时等于按下时的背景颜色
            if self._display_mode == "icon":
                # 图标模式下文字颜色与背景颜色一致
                text_color = bg_color
                pressed_text_color = pressed_color
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
                icon_size = button_size * 0.6
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
            
            # 如果有图标路径，直接使用QSvgRenderer渲染SVG
            if self._icon_path and os.path.exists(self._icon_path):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
                
                try:
                    from PyQt5.QtSvg import QSvgRenderer
                    from PyQt5.QtCore import QRectF
                    
                    # 使用QSvgRenderer直接渲染SVG，不转换为位图
                    svg_renderer = QSvgRenderer(self._icon_path)
                    
                    # 计算合适的图标大小，确保图标不会超出按钮范围
                    button_size = min(self.width(), self.height())
                    icon_size = button_size * 0.6
                    
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
