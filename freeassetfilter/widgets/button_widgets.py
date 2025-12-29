#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 按钮类自定义控件
包含各种按钮类UI组件，如自定义按钮等
"""

from PyQt5.QtWidgets import (
    QPushButton, QWidget, QSizePolicy, QApplication
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize, QTimer
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
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
    
    def __init__(self, text="Button", parent=None, button_type="primary", display_mode="text", height=40):
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
        """
        # 图标模式下，向父类传递空文本，避免显示文字
        parent_text = text if display_mode == "text" else ""
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
        
        # 使用最新的DPI缩放因子重新计算按钮高度
        self._height = int(self._original_height * self.dpi_scale)
        
        # 添加阴影效果，应用最新的DPI缩放
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(int(2 * self.dpi_scale))
        shadow.setOffset(0, int(2 * self.dpi_scale))
        # 正确设置阴影颜色：黑色，带有适当的透明度
        shadow.setColor(QColor(0, 0, 0, 20))  # 使用黑色阴影更明显
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
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #0a59f7;
                    color: #ffffff;
                    border: {scaled_primary_border_width}px solid #0a59f7;
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #0c5bf9;
                    border-color: #0c5bf9;
                }}
                QPushButton:pressed {{
                    background-color: #0e5dfb;
                    border-color: #0e5dfb;
                }}
                QPushButton:disabled {{
                    background-color: #88A9EB;
                    color: #FFFFFF;
                    border-color: #88A9EB;
                }}
            """)
        elif self.button_type == "normal":
            # 普通方案
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #f8f9fa;
                    color: #0a59f7;
                    border: {scaled_primary_border_width}px solid #dee2e6;
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #e9ecef;
                    border-color: #adb5bd;
                }}
                QPushButton:pressed {{
                    background-color: #dee2e6;
                    border-color: #ced4da;
                }}
                QPushButton:disabled {{
                    background-color: #f8f9fa;
                    color: #adb5bd;
                    border-color: #dee2e6;
                }}
            """)
        elif self.button_type == "warning":
            # 警告按钮方案
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #ff0000;
                    color: #ffffff;
                    border: {scaled_primary_border_width}px solid #ff0000;
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #e60000;
                    border-color: #e60000;
                }}
                QPushButton:pressed {{
                    background-color: #cc0000;
                    border-color: #cc0000;
                }}
                QPushButton:disabled {{
                    background-color: #ff8080;
                    color: #FFFFFF;
                    border-color: #ff8080;
                }}
            """)
        else:  # secondary
            # 次选按钮方案：确保在白色背景下可见
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: #ffffff;
                    color: #0a59f7;
                    border: {scaled_border_width}px solid #0a59f7;
                    border-radius: {scaled_border_radius}px;
                    padding: {scaled_padding};
                    font-size: {scaled_font_size}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: #f0f4ff;
                    border-color: #0d6efd;
                }}
                QPushButton:pressed {{
                    background-color: #e0e7ff;
                    border-color: #0A51E0;
                }}
                QPushButton:disabled {{
                    background-color: #ffffff;
                    color: #DADFE4;
                    border-color: #DADFE4;
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
        如果是图标模式，先调用父类绘制按钮样式，再直接渲染SVG；否则调用父类绘制文字
        """
        if self._display_mode == "icon":
            # 图标模式，先绘制按钮样式（背景色、边框、圆角等）
            super().paintEvent(event)
            
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
