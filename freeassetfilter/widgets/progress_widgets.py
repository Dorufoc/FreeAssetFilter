#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 进度条类自定义控件
包含各种进度条类UI组件，如自定义进度条、数值控制条、音量控制条等
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QSizePolicy, QApplication, QDialog, QLineEdit, 
    QScrollArea
)
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QBrush, QIcon, QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

# 用于SVG渲染
from freeassetfilter.core.svg_renderer import SvgRenderer
import os


class CustomProgressBar(QWidget):
    """
    自定义进度条控件
    支持点击任意位置跳转和拖拽功能
    特点：
    - 自定义外观，包括背景色、进度色和滑块样式
    - 使用SVG图标作为滑块
    - 支持悬停和点击状态变化
    - 提供丰富的信号机制
    - 支持横向和纵向布局
    """
    valueChanged = pyqtSignal(int)  # 值变化信号
    userInteracting = pyqtSignal()  # 用户开始交互信号
    userInteractionEnded = pyqtSignal()  # 用户结束交互信号
    
    # 方向常量
    Horizontal = 0
    Vertical = 1
    
    def __init__(self, parent=None, is_interactive=True):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 方向属性
        self._orientation = self.Horizontal
        
        # 设置默认尺寸，应用DPI缩放
        # 尺寸关系：进度条高度 = 滑块半径，滑块直径 = 2 × 进度条高度
        # 这样滑块比进度条大，视觉上更协调
        self._bar_height = int(3 * self.dpi_scale)  # 进度条高度
        self._handle_radius = self._bar_height  # 滑块半径 = 进度条高度
        self._bar_radius = self._bar_height // 2  # 圆角半径 = 进度条高度的一半
        
        scaled_min_width = int(50 * self.dpi_scale)
        scaled_min_height = self._bar_height + self._handle_radius * 2  # 总高度 = 进度条高度 + 2×滑块半径
        self.setMinimumSize(scaled_min_width, scaled_min_height)
        self.setMaximumHeight(scaled_min_height)
        
        # 获取全局字体
        self.global_font = getattr(app, 'global_font', QFont())
        self.setFont(self.global_font)
        
        # 进度条属性
        self._minimum = 0
        self._maximum = 1000
        self._value = 0
        self._is_pressed = False
        self._last_pos = 0
        self._is_interactive = is_interactive  # 新增：控制是否可交互
        
        # 外观属性，应用DPI缩放
        # 尝试从应用实例获取主题颜色
        app = QApplication.instance()
        
        # 获取辅助颜色auxiliary_color
        auxiliary_color = "#f1f3f5"  # 默认辅助色
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            # 获取主题颜色
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)
            progress_color_str = settings_manager.get_setting("appearance.colors.progress_bar_fg", "#4ECDC4")
            handle_color_str = settings_manager.get_setting("appearance.colors.slider_handle", "#4ECDC4")
            handle_hover_color_str = settings_manager.get_setting("appearance.colors.slider_handle_hover", "#5EE0D8")
            
            # 使用主题颜色
            self._bg_color = QColor(auxiliary_color)
            self._progress_color = QColor(progress_color_str)
            self._handle_color = QColor(handle_color_str)
            self._handle_hover_color = QColor(handle_hover_color_str)
            self._handle_pressed_color = QColor(handle_color_str).darker(120)  # 按比例变暗
        else:
            # 使用默认颜色
            self._bg_color = QColor(auxiliary_color)  # 使用默认辅助色
            self._progress_color = QColor(10, 89, 247)  # #0a59f7
            self._handle_color = QColor(0, 120, 212)  # #0078d4
            self._handle_hover_color = QColor(16, 110, 190)  # #106ebe
            self._handle_pressed_color = QColor(0, 90, 158)  # #005a9e
        
        # SVG 图标路径
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        self._icon_path = os.path.join(icon_dir, '条-顶-尾.svg')
        self._head_icon_path = os.path.join(icon_dir, '条-顶-头.svg')
        self._middle_icon_path = os.path.join(icon_dir, '条-顶-中.svg')
        
        # 渲染 SVG 图标为 QPixmap，传递DPI缩放因子
        self._handle_pixmap = SvgRenderer.render_svg_to_pixmap(self._icon_path, self._handle_radius * 2, self.dpi_scale)
        self._head_pixmap = SvgRenderer.render_svg_to_pixmap(self._head_icon_path, self._handle_radius * 2, self.dpi_scale)
        # 条顶中 SVG 会在绘制时根据需要直接渲染，这里只保存路径
    
    def setOrientation(self, orientation):
        """
        设置进度条方向
        
        Args:
            orientation: 方向常量，Horizontal 或 Vertical
        """
        if self._orientation != orientation:
            self._orientation = orientation
            
            # 应用DPI缩放因子到尺寸限制
            scaled_min_width = int(200 * self.dpi_scale)
            scaled_square_dim = self._bar_height + self._handle_radius * 2
            
            # 根据新方向更新尺寸限制
            if orientation == self.Horizontal:
                self.setMinimumSize(scaled_min_width, self._bar_height + self._handle_radius * 2)
                self.setMaximumHeight(self._bar_height + self._handle_radius * 2)
            else:  # Vertical
                self.setMinimumSize(scaled_square_dim, scaled_min_width)
                self.setMaximumWidth(scaled_square_dim)
            
            self.update()
    
    def orientation(self):
        """
        获取进度条方向
        
        Returns:
            int: 方向常量
        """
        return self._orientation
    
    def setRange(self, minimum, maximum):
        """
        设置进度条范围
        
        Args:
            minimum (int): 最小值
            maximum (int): 最大值
        """
        self._minimum = minimum
        self._maximum = maximum
        self.update()
    
    def setValue(self, value):
        """
        设置进度条值
        
        Args:
            value (int): 进度值
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)
    
    def value(self):
        """
        获取当前进度值
        
        Returns:
            int: 当前进度值
        """
        return self._value
    
    def setInteractive(self, is_interactive):
        """
        设置进度条是否可交互
        
        Args:
            is_interactive (bool): 是否可交互
        """
        self._is_interactive = is_interactive
        self.update()
    
    def isInteractive(self):
        """
        获取进度条是否可交互
        
        Returns:
            bool: 是否可交互
        """
        return self._is_interactive
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件，处理用户开始交互
        """
        if self._is_interactive and event.button() == Qt.LeftButton:
            self._is_pressed = True
            if self._orientation == self.Horizontal:
                self._last_pos = event.pos().x()
                self._update_value_from_pos(self._last_pos)
            else:  # Vertical
                self._last_pos = event.pos().y()
                self._update_value_from_pos(self._last_pos)
            self.userInteracting.emit()
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件，处理拖拽交互
        """
        if self._is_interactive and self._is_pressed:
            if self._orientation == self.Horizontal:
                self._last_pos = event.pos().x()
                self._update_value_from_pos(self._last_pos)
            else:  # Vertical
                self._last_pos = event.pos().y()
                self._update_value_from_pos(self._last_pos)
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件，处理用户结束交互
        """
        if self._is_interactive and self._is_pressed and event.button() == Qt.LeftButton:
            self._is_pressed = False
            self.userInteractionEnded.emit()
    
    def _update_value_from_pos(self, pos):
        """
        根据鼠标位置更新进度值
        
        Args:
            pos (int): 鼠标坐标（横向为X坐标，纵向为Y坐标）
        """
        if self._orientation == self.Horizontal:
            # 横向处理
            # 计算进度条总宽度
            bar_length = self.width() - (self._handle_radius * 2)
            # 计算鼠标在进度条上的相对位置
            relative_pos = pos - self._handle_radius
            if relative_pos < 0:
                relative_pos = 0
            elif relative_pos > bar_length:
                relative_pos = bar_length
            
            # 计算对应的进度值
            if bar_length > 0:
                ratio = relative_pos / bar_length
            else:
                ratio = 0.0
            value = int(self._minimum + ratio * (self._maximum - self._minimum))
        else:  # Vertical
            # 纵向处理 - 滑动方向修正：向上滑动数值增加，向下滑动数值减少
            # 计算进度条总高度
            bar_length = self.height() - (self._handle_radius * 2)
            # 计算鼠标在进度条上的相对位置
            relative_pos = pos - self._handle_radius
            if relative_pos < 0:
                relative_pos = 0
            elif relative_pos > bar_length:
                relative_pos = bar_length
            
            # 计算对应的进度值 - 反向映射：relative_pos越大，值越小
            if bar_length > 0:
                ratio = 1.0 - (relative_pos / bar_length)
            else:
                ratio = 0.0
            value = int(self._minimum + ratio * (self._maximum - self._minimum))
        
        self.setValue(value)
    
    def paintEvent(self, event):
        """
        绘制进度条
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
        if self._orientation == self.Horizontal:
            # 横向绘制
            # 计算进度条参数
            bar_y = (rect.height() - self._bar_height) // 2
            bar_width = rect.width() - 2 * self._handle_radius
            
            # 绘制背景
            bg_rect = QRect(
                self._handle_radius, bar_y, 
                bar_width, self._bar_height
            )
            
            painter.setBrush(QBrush(self._bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
            
            # 计算已完成部分宽度
            progress_width = int(bar_width * (self._value - self._minimum) / (self._maximum - self._minimum))
            
            if progress_width > 0:
                if self._is_interactive:
                    # 可交互进度条 - 原有样式
                    # 使用条顶中 SVG 图形填充已播放部分
                    # 使用修复过的 SvgRenderer 方法渲染 SVG 到临时 QPixmap，传递DPI缩放因子
                    icon_size = self._handle_radius * 2
                    temp_pixmap = SvgRenderer.render_svg_to_pixmap(self._middle_icon_path, icon_size, self.dpi_scale)
                    
                    # 将临时 pixmap 旋转 90 度
                    from PyQt5.QtCore import Qt as QtCore
                    from PyQt5.QtGui import QTransform
                    transform = QTransform()
                    transform.rotate(90)
                    rotated_pixmap = temp_pixmap.transformed(transform, QtCore.SmoothTransformation)
                    
                    # 计算对齐位置（进度条中心与滑块中心对齐）
                    # bar_y + bar_height/2 = handle_center_y + handle_radius
                    # handle_center_y = bar_y + bar_height/2 - handle_radius
                    # 由于 bar_height = handle_radius:
                    # handle_center_y = bar_y + handle_radius/2 - handle_radius = bar_y - handle_radius/2
                    offset_y = (self._bar_height - self._handle_radius * 2) // 2
                    handle_center_y = bar_y + offset_y
                    
                    # 计算中间矩形（进度条填充区域）
                    middle_rect = QRect(
                        self._handle_radius, bar_y, 
                        progress_width, self._bar_height
                    )
                    
                    # 拉伸渲染旋转后的 pixmap 到中间矩形
                    painter.drawPixmap(middle_rect, rotated_pixmap)
                    
                    # 绘制已完成区域的起始点 - 使用条-顶-头.svg图标（逆时针旋转90度）
                    head_x = self._handle_radius  # 从起始位置开始
                    
                    if not self._head_pixmap.isNull():
                        # 保存当前画家状态
                        painter.save()
                        
                        # 计算旋转中心（进度条中心与滑块中心对齐）
                        # center_y = bar_y + bar_height/2
                        center_x = head_x + self._handle_radius
                        center_y = bar_y + self._bar_height // 2
                        
                        # 移动坐标原点到旋转中心
                        painter.translate(center_x, center_y)
                        
                        # 逆时针旋转90度
                        painter.rotate(-90)
                        
                        # 绘制旋转后的图标
                        painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._head_pixmap)
                        
                        # 恢复画家状态
                        painter.restore()
                    
                    # 绘制滑块 - 使用 SVG 图标（逆时针旋转90度）
                    handle_x = self._handle_radius + progress_width
                    # 确保滑块不会超出进度条范围
                    handle_x = min(handle_x, self.width() - self._handle_radius * 2)
                    
                    # 确保图标已正确加载
                    if not self._handle_pixmap.isNull():
                        # 保存当前画家状态
                        painter.save()
                        
                        # 计算旋转中心（进度条中心与滑块中心对齐）
                        # center_y = bar_y + bar_height/2
                        center_x = handle_x + self._handle_radius
                        center_y = bar_y + self._bar_height // 2
                        
                        # 移动坐标原点到旋转中心
                        painter.translate(center_x, center_y)
                        
                        # 逆时针旋转90度
                        painter.rotate(-90)
                        
                        # 绘制旋转后的图标
                        painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._handle_pixmap)
                        
                        # 恢复画家状态
                        painter.restore()
                    else:
                        # 备用方案：如果 SVG 加载失败，绘制圆形滑块
                        painter.setBrush(QBrush(
                            self._handle_pressed_color if self._is_pressed else 
                            self._handle_hover_color if self.underMouse() else 
                            self._handle_color
                        ))
                        painter.setPen(Qt.NoPen)  # 去除滑块边框
                        painter.drawEllipse(handle_x, handle_center_y, self._handle_radius * 2, self._handle_radius * 2)
                else:
                    # 不可交互进度条 - 使用纯色填充，类似CustomValueBar
                    progress_rect = QRect(
                        self._handle_radius, bar_y, 
                        progress_width, self._bar_height
                    )
                    painter.setBrush(QBrush(self._progress_color))
                    painter.setPen(Qt.NoPen)
                    painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        else:  # Vertical
            # 纵向绘制
            # 计算进度条参数
            bar_x = (rect.width() - self._bar_height) // 2
            bar_height = rect.height() - 2 * self._handle_radius
            
            # 绘制背景
            bg_rect = QRect(
                bar_x, self._handle_radius, 
                self._bar_height, bar_height
            )
            
            painter.setBrush(QBrush(self._bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
            
            # 计算已完成部分高度
            progress_height = int(bar_height * (self._value - self._minimum) / (self._maximum - self._minimum))
            
            if progress_height > 0:
                if self._is_interactive:
                    # 可交互进度条 - 纵向样式
                    # 使用条顶中 SVG 图形填充已播放部分
                    # 使用修复过的 SvgRenderer 方法渲染 SVG 到临时 QPixmap，传递DPI缩放因子
                    icon_size = self._handle_radius * 2
                    temp_pixmap = SvgRenderer.render_svg_to_pixmap(self._middle_icon_path, icon_size, self.dpi_scale)
                    
                    # 计算对齐位置（进度条中心与滑块中心对齐）
                    # bar_x + bar_height/2 = handle_center_x + handle_radius
                    # handle_center_x = bar_x + bar_height/2 - handle_radius
                    # 由于 bar_height = handle_radius:
                    # handle_center_x = bar_x + handle_radius/2 - handle_radius = bar_x - handle_radius/2
                    offset_x = (self._bar_height - self._handle_radius * 2) // 2
                    handle_center_x = bar_x + offset_x
                    
                    # 计算中间矩形 - 从顶部开始向下延伸（使用进度条高度）
                    middle_rect = QRect(
                        bar_x, self._handle_radius, 
                        self._bar_height, progress_height
                    )
                    
                    # 拉伸渲染 pixmap 到中间矩形
                    painter.drawPixmap(middle_rect, temp_pixmap)
                    
                    # 绘制已完成区域的起始点 - 使用条-顶-头.svg图标
                    head_y = self._handle_radius  # 从起始位置开始
                    
                    if not self._head_pixmap.isNull():
                        # 保存当前画家状态
                        painter.save()
                        
                        # 计算旋转中心（进度条中心与滑块中心对齐）
                        # center_x = bar_x + bar_height/2
                        center_x = bar_x + self._bar_height // 2
                        center_y = head_y + self._handle_radius
                        
                        # 移动坐标原点到旋转中心
                        painter.translate(center_x, center_y)
                        
                        # 绘制图标（不需要旋转）
                        painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._head_pixmap)
                        
                        # 恢复画家状态
                        painter.restore()
                    
                    # 绘制滑块 - 使用 SVG 图标
                    handle_y = self._handle_radius + progress_height
                    # 确保滑块不会超出进度条范围
                    handle_y = min(handle_y, self.height() - self._handle_radius * 2)
                    
                    # 确保图标已正确加载
                    if not self._handle_pixmap.isNull():
                        # 保存当前画家状态
                        painter.save()
                        
                        # 计算旋转中心（进度条中心与滑块中心对齐）
                        # center_x = bar_x + bar_height/2
                        center_x = bar_x + self._bar_height // 2
                        center_y = handle_y + self._handle_radius
                        
                        # 移动坐标原点到旋转中心
                        painter.translate(center_x, center_y)
                        
                        # 绘制旋转后的图标
                        painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._handle_pixmap)
                        
                        # 恢复画家状态
                        painter.restore()
                    else:
                        # 备用方案：如果 SVG 加载失败，绘制圆形滑块
                        painter.setBrush(QBrush(
                            self._handle_pressed_color if self._is_pressed else 
                            self._handle_hover_color if self.underMouse() else 
                            self._handle_color
                        ))
                        painter.setPen(Qt.NoPen)  # 去除滑块边框
                        painter.drawEllipse(handle_center_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
                else:
                    # 不可交互进度条 - 使用纯色填充，类似CustomValueBar
                    progress_rect = QRect(
                        bar_x, self._handle_radius, 
                        self._bar_height, progress_height
                    )
                    painter.setBrush(QBrush(self._progress_color))
                    painter.setPen(Qt.NoPen)
                    painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        
        painter.end()
    
    def enterEvent(self, event):
        """
        鼠标进入事件
        """
        self.update()
    
    def leaveEvent(self, event):
        """
        鼠标离开事件
        """
        self.update()


class CustomValueBar(QWidget):
    """
    自定义数值控制条组件
    支持横向和竖向两种显示方式，滑块为圆形设计
    """
    valueChanged = pyqtSignal(int)  # 值变化信号
    userInteracting = pyqtSignal()  # 用户开始交互信号
    userInteractionEnded = pyqtSignal()  # 用户结束交互信号
    
    # 方向常量
    Horizontal = 0
    Vertical = 1
    
    def __init__(self, parent=None, orientation=Horizontal, interactive=True):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 方向属性
        self._orientation = orientation
        
        # 交互属性
        self._interactive = interactive
        
        # 设置尺寸参数
        # 尺寸关系：进度条高度 = 滑块半径，滑块直径 = 2 × 进度条高度
        # 这样滑块比进度条大，视觉上更协调
        self._bar_size = int(3 * self.dpi_scale)  # 进度条尺寸（横向为高度，竖向为宽度）
        self._handle_radius = self._bar_size  # 滑块半径 = 进度条尺寸
        self._bar_radius = self._bar_size // 2  # 圆角半径 = 进度条尺寸的一半
        
        # 应用DPI缩放因子到尺寸
        scaled_min_width = int(100 * self.dpi_scale)
        scaled_min_height = self._bar_size + self._handle_radius * 2  # 总高度 = 进度条尺寸 + 2×滑块半径
        scaled_square_dim = self._bar_size + self._handle_radius * 2
        
        # 根据方向设置最小和最大尺寸，应用DPI缩放
        if self._orientation == self.Horizontal:
            self.setMinimumSize(scaled_min_width, scaled_min_height)
            self.setMaximumHeight(scaled_min_height)
        else:  # Vertical
            self.setMinimumSize(scaled_square_dim, scaled_min_width)
            self.setMaximumWidth(scaled_square_dim)
        
        # 进度条属性
        self._minimum = 0
        self._maximum = 1000
        self._value = 0
        self._is_pressed = False
        self._last_pos = 0
        
        # 外观属性，应用DPI缩放（尺寸参数已在上面设置）
        
        # 尝试从应用实例获取主题颜色
        app = QApplication.instance()
        
        # 获取辅助颜色auxiliary_color
        auxiliary_color = "#f1f3f5"  # 默认辅助色
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            # 获取主题颜色
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)
            progress_color_str = settings_manager.get_setting("appearance.colors.progress_bar_fg", "#4ECDC4")
            handle_color_str = settings_manager.get_setting("appearance.colors.slider_handle", "#4ECDC4")
            handle_hover_color_str = settings_manager.get_setting("appearance.colors.slider_handle_hover", "#5EE0D8")
            
            # 使用主题颜色
            self._bg_color = QColor(auxiliary_color)
            self._progress_color = QColor(progress_color_str)
            self._handle_border_color = QColor(handle_color_str)
            self._handle_fill_color = QColor(255, 255, 255)  # 内部填充为纯白色
        else:
            # 使用默认颜色
            self._bg_color = QColor(auxiliary_color)  # 使用默认辅助色
            self._progress_color = QColor(0, 120, 212)  # 已完成区域颜色（蓝色，与不可交互进度条一致）
            self._handle_border_color = QColor(0, 120, 212)  # 边框为蓝色，与进度条颜色一致
            self._handle_fill_color = QColor(255, 255, 255)  # 内部填充为纯白色
        
        self._handle_border_width = int(1 * self.dpi_scale)  # 边框宽度，响应DPI缩放
    
    def setRange(self, minimum, maximum):
        """
        设置数值条范围
        """
        self._minimum = minimum
        self._maximum = maximum
        self.update()
    
    def setValue(self, value):
        """
        设置数值条值
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)
    
    def value(self):
        """
        获取当前数值
        """
        return self._value
    
    def setOrientation(self, orientation):
        """
        设置数值条方向
        
        Args:
            orientation: 方向常量，Horizontal 或 Vertical
        """
        if self._orientation != orientation:
            self._orientation = orientation
            
            # 应用DPI缩放因子到尺寸
            scaled_min_width = int(100 * self.dpi_scale)
            scaled_min_height = int(20 * self.dpi_scale)
            scaled_square_dim = int(20 * self.dpi_scale)
            
            # 根据新方向更新尺寸限制，应用DPI缩放
            if orientation == self.Horizontal:
                self.setMinimumSize(scaled_min_width, scaled_min_height)
                self.setMaximumHeight(scaled_min_height)
            else:  # Vertical
                self.setMinimumSize(scaled_square_dim, scaled_min_width)
                self.setMaximumWidth(scaled_square_dim)
            
            self.update()
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        if self._interactive and event.button() == Qt.LeftButton:
            self._is_pressed = True
            if self._orientation == self.Horizontal:
                self._last_pos = event.pos().x()
                self._update_value_from_pos(self._last_pos)
            else:  # Vertical
                self._last_pos = event.pos().y()
                self._update_value_from_pos(self._last_pos)
            self.userInteracting.emit()
        else:
            # 不可交互时，调用父类实现
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件
        """
        if self._interactive and self._is_pressed:
            if self._orientation == self.Horizontal:
                self._last_pos = event.pos().x()
                self._update_value_from_pos(self._last_pos)
            else:  # Vertical
                self._last_pos = event.pos().y()
                self._update_value_from_pos(self._last_pos)
        else:
            # 不可交互时，调用父类实现
            super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件
        """
        if self._interactive and self._is_pressed and event.button() == Qt.LeftButton:
            self._is_pressed = False
            self.userInteractionEnded.emit()
        else:
            # 不可交互时，调用父类实现
            super().mouseReleaseEvent(event)
    
    def setInteractive(self, interactive):
        """
        设置数值条是否可交互
        
        Args:
            interactive: 是否可交互
        """
        self._interactive = interactive
        self.update()
    
    def _update_value_from_pos(self, pos):
        """
        根据鼠标位置更新数值
        
        Args:
            pos: 鼠标位置（横向为x坐标，竖向为y坐标）
        """
        if self._orientation == self.Horizontal:
            # 横向处理
            # 计算数值条总宽度
            bar_length = self.width() - (self._handle_radius * 2)
            # 计算鼠标在数值条上的相对位置
            relative_pos = pos - self._handle_radius
            if relative_pos < 0:
                relative_pos = 0
            elif relative_pos > bar_length:
                relative_pos = bar_length
                
            # 计算对应的值
            if bar_length > 0:
                ratio = relative_pos / bar_length
            else:
                ratio = 0.0
            value = int(self._minimum + ratio * (self._maximum - self._minimum))
        else:  # Vertical
            # 竖向处理 - 滑动方向修正：向上滑动数值增加，向下滑动数值减少
            # 计算数值条总高度
            bar_length = self.height() - (self._handle_radius * 2)
            # 计算鼠标在数值条上的相对位置
            relative_pos = pos - self._handle_radius
            if relative_pos < 0:
                relative_pos = 0
            elif relative_pos > bar_length:
                relative_pos = bar_length
                
            # 计算对应的值 - 反向映射：relative_pos越大，值越小
            if bar_length > 0:
                ratio = 1.0 - (relative_pos / bar_length)
            else:
                ratio = 0.0
            value = int(self._minimum + ratio * (self._maximum - self._minimum))
        
        self.setValue(value)
    
    def paintEvent(self, event):
        """
        绘制数值控制条
        """
        # 确保Qt已导入
        from PyQt5.QtCore import Qt
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
        if self._orientation == self.Horizontal:
            # 横向绘制
            # 计算数值条参数
            bar_y = (rect.height() - self._bar_size) // 2
            bar_length = rect.width() - 2 * self._handle_radius
            
            # 绘制背景
            bg_rect = QRect(
                self._handle_radius, bar_y, 
                bar_length, self._bar_size
            )
            
            painter.setBrush(QBrush(self._bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
            
            # 绘制已完成部分
            if (self._maximum - self._minimum) > 0:
                progress_ratio = (self._value - self._minimum) / (self._maximum - self._minimum)
            else:
                progress_ratio = 0.0
            progress_length = int(bar_length * progress_ratio)
            progress_rect = QRect(
                self._handle_radius, bar_y, 
                progress_length, self._bar_size
            )
            
            painter.setBrush(QBrush(self._progress_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
            
            # 绘制圆形滑块
            handle_x = self._handle_radius + progress_length
            # 确保滑块不会超出数值条范围
            handle_x = min(handle_x, self.width() - self._handle_radius * 2)
            # 计算对齐位置（进度条中心与滑块中心对齐）
            # bar_y + bar_size/2 = handle_y + handle_radius
            # handle_y = bar_y + bar_size/2 - handle_radius
            # 由于 bar_size = handle_radius:
            # handle_y = bar_y + handle_radius/2 - handle_radius = bar_y - handle_radius/2
            offset_y = (self._bar_size - self._handle_radius * 2) // 2
            handle_y = bar_y + offset_y
            
            # 绘制圆形滑块：内部填充为纯白色，边框为蓝色
            # 绘制外圆（边框）
            painter.setBrush(Qt.NoBrush)  # 无边框填充
            painter.setPen(QPen(self._handle_border_color, self._handle_border_width))
            painter.drawEllipse(handle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
            
            # 绘制内圆（填充）
            inner_radius = self._handle_radius - self._handle_border_width
            inner_x = handle_x + self._handle_border_width
            inner_y = handle_y + self._handle_border_width
            painter.setBrush(QBrush(self._handle_fill_color))
            painter.setPen(Qt.NoPen)  # 无填充边框
            painter.drawEllipse(inner_x, inner_y, inner_radius * 2, inner_radius * 2)
        else:  # Vertical
            # 竖向绘制
            # 计算数值条参数
            bar_x = (rect.width() - self._bar_size) // 2
            bar_length = rect.height() - 2 * self._handle_radius
            
            # 绘制背景
            bg_rect = QRect(
                bar_x, self._handle_radius, 
                self._bar_size, bar_length
            )
            
            painter.setBrush(QBrush(self._bg_color))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
            
            # 绘制已完成部分
            if (self._maximum - self._minimum) > 0:
                progress_ratio = (self._value - self._minimum) / (self._maximum - self._minimum)
            else:
                progress_ratio = 0.0
            progress_length = int(bar_length * progress_ratio)
            
            # 只有当progress_length > 0时才绘制已完成部分，避免值为0时的视觉偏移
            if progress_length > 0:
                # 竖向进度条：已完成部分从底部开始向上延伸
                progress_rect = QRect(
                    bar_x, 
                    self._handle_radius + (bar_length - progress_length),  # 底部对齐
                    self._bar_size, 
                    progress_length
                )
                
                painter.setBrush(QBrush(self._progress_color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
            
            # 绘制圆形滑块 - 修正位置计算：值越大，滑块越靠上
            handle_y = self._handle_radius + (bar_length - progress_length)
            # 确保滑块不会超出数值条范围
            handle_y = max(handle_y, self._handle_radius)
            handle_y = min(handle_y, rect.height() - self._handle_radius * 2)
            # 计算对齐位置（进度条中心与滑块中心对齐）
            # bar_x + bar_size/2 = handle_x + handle_radius
            # handle_x = bar_x + bar_size/2 - handle_radius
            # 由于 bar_size = handle_radius:
            # handle_x = bar_x + handle_radius/2 - handle_radius = bar_x - handle_radius/2
            offset_x = (self._bar_size - self._handle_radius * 2) // 2
            handle_x = bar_x + offset_x
            
            # 绘制圆形滑块：内部填充为纯白色，边框为蓝色
            # 绘制外圆（边框）
            painter.setBrush(Qt.NoBrush)  # 无边框填充
            painter.setPen(QPen(self._handle_border_color, self._handle_border_width))
            painter.drawEllipse(handle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
            
            # 绘制内圆（填充）
            inner_radius = self._handle_radius - self._handle_border_width
            inner_x = handle_x + self._handle_border_width
            inner_y = handle_y + self._handle_border_width
            painter.setBrush(QBrush(self._handle_fill_color))
            painter.setPen(Qt.NoPen)  # 无填充边框
            painter.drawEllipse(inner_x, inner_y, inner_radius * 2, inner_radius * 2)
        
        painter.end()
    
    def enterEvent(self, event):
        """
        鼠标进入事件
        """
        self.update()
    
    def leaveEvent(self, event):
        """
        鼠标离开事件
        """
        self.update()


class CustomVolumeBar(QWidget):
    """
    自定义音量控制条
    支持点击任意位置调整音量和拖拽功能
    """
    valueChanged = pyqtSignal(int)  # 值变化信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 设置尺寸参数
        # 尺寸关系：进度条高度 = 滑块半径，滑块直径 = 2 × 进度条高度
        # 这样滑块比进度条大，视觉上更协调
        self._bar_height = int(6 * self.dpi_scale)  # 进度条高度（比一般的进度条大一点）
        self._handle_radius = self._bar_height  # 滑块半径 = 进度条高度
        self._bar_radius = self._bar_height // 2  # 圆角半径 = 进度条高度的一半
        
        # 设置最小尺寸为滑块直径加上一定余量，确保滑块始终可见
        scaled_min_width = int(self._handle_radius * 3)  # 滑块直径 + 两侧余量
        scaled_height = self._bar_height + self._handle_radius * 2  # 总高度 = 进度条高度 + 2×滑块半径
        self.setMinimumSize(scaled_min_width, scaled_height)
        self.setMaximumHeight(scaled_height)
        
        # 音量条属性
        self._minimum = 0
        self._maximum = 100
        self._value = 50  # 默认音量50%
        self._is_pressed = False
        self._last_pos = 0
        
        # 圆形滑块颜色属性
        self._handle_fill_color = QColor(255, 255, 255)  # 内部填充为纯白色
        self._handle_border_width = int(2 * self.dpi_scale)  # 边框宽度，响应DPI缩放
        
        # 尝试从应用实例获取主题颜色
        
        # 获取辅助颜色auxiliary_color
        auxiliary_color = "#f1f3f5"  # 默认辅助色
        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            # 获取主题颜色
            auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", auxiliary_color)
            progress_color_str = settings_manager.get_setting("appearance.colors.progress_bar_fg", "#4ECDC4")
            handle_color_str = settings_manager.get_setting("appearance.colors.slider_handle", "#4ECDC4")
            
            # 使用主题颜色
            self._bg_color = QColor(auxiliary_color)
            self._progress_color = QColor(progress_color_str)
            self._handle_border_color = QColor(handle_color_str)
        else:
            # 使用默认颜色
            self._bg_color = QColor(auxiliary_color)  # 使用默认辅助色
            self._progress_color = QColor(0, 120, 212)  # #0078d4
            self._handle_border_color = QColor(0, 120, 212)  # 边框为蓝色，与进度条颜色一致
    
    def setRange(self, minimum, maximum):
        """
        设置音量条范围
        """
        self._minimum = minimum
        self._maximum = maximum
        self.update()
    
    def setValue(self, value):
        """
        设置音量条值
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)
    
    def value(self):
        """
        获取当前音量值
        """
        return self._value
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        if event.button() == Qt.LeftButton:
            self._is_pressed = True
            self._last_pos = event.pos().x()
            # 计算点击位置对应的音量值
            self._update_value_from_pos(event.pos().x())
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件
        """
        if self._is_pressed:
            self._last_pos = event.pos().x()
            self._update_value_from_pos(event.pos().x())
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件
        """
        if self._is_pressed and event.button() == Qt.LeftButton:
            self._is_pressed = False
    
    def _update_value_from_pos(self, x_pos):
        """
        根据鼠标位置更新音量值
        """
        # 计算音量条总宽度，确保不小于0
        effective_width = max(0, self.width() - (self._handle_radius * 2))
        bar_width = effective_width
        # 计算鼠标在音量条上的相对位置
        relative_x = x_pos - self._handle_radius
        if relative_x < 0:
            relative_x = 0
        elif relative_x > bar_width:
            relative_x = bar_width
        
        # 计算对应的音量值，避免除以0
        if bar_width > 0:
            ratio = relative_x / bar_width
        else:
            ratio = 0.0
        value = int(self._minimum + ratio * (self._maximum - self._minimum))
        self.setValue(value)
    
    def paintEvent(self, event):
        """
        绘制音量条
        """
        # 确保Qt已导入
        from PyQt5.QtCore import Qt
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
        # 计算音量条参数
        bar_y = (rect.height() - self._bar_height) // 2
        # 确保bar_width不小于0
        bar_width = max(0, rect.width() - 2 * self._handle_radius)
        
        # 绘制背景 - 确保背景矩形宽度不小于0
        bg_rect = QRect(
            self._handle_radius, bar_y, 
            bar_width, self._bar_height
        )
        
        painter.setBrush(QBrush(self._bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
        
        # 绘制已音量部分 - 使用纯色填充，不使用其他SVG图标
        # 确保分母不为0
        if (self._maximum - self._minimum) > 0:
            progress_ratio = (self._value - self._minimum) / (self._maximum - self._minimum)
        else:
            progress_ratio = 0.0
        progress_width = int(bar_width * progress_ratio)
        progress_rect = QRect(
            self._handle_radius, bar_y, 
            progress_width, self._bar_height
        )
        
        painter.setBrush(QBrush(self._progress_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        
        # 绘制滑块 - 使用圆形滑块
        handle_x = self._handle_radius + progress_width
        # 确保滑块不会超出音量条范围，考虑实际窗口宽度
        max_handle_x = max(self._handle_radius, self.width() - self._handle_radius * 2)
        handle_x = min(handle_x, max_handle_x)
        # 确保滑块不会小于最小值
        handle_x = max(handle_x, self._handle_radius)
        # 计算对齐位置（进度条中心与滑块中心对齐）
        # bar_y + bar_height/2 = handle_y + handle_radius
        # handle_y = bar_y + bar_height/2 - handle_radius
        # 由于 bar_height = handle_radius:
        # handle_y = bar_y + handle_radius/2 - handle_radius = bar_y - handle_radius/2
        offset_y = (self._bar_height - self._handle_radius * 2) // 2
        handle_y = bar_y + offset_y
        
        # 绘制圆形滑块：内部填充为纯白色，边框为蓝色
        # 绘制外圆（边框）
        painter.setBrush(Qt.NoBrush)  # 无边框填充
        painter.setPen(QPen(self._handle_border_color, self._handle_border_width))
        painter.drawEllipse(handle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
        
        # 绘制内圆（填充）
        inner_radius = self._handle_radius - self._handle_border_width
        inner_x = handle_x + self._handle_border_width
        inner_y = handle_y + self._handle_border_width
        painter.setBrush(QBrush(self._handle_fill_color))
        painter.setPen(Qt.NoPen)  # 无填充边框
        painter.drawEllipse(inner_x, inner_y, inner_radius * 2, inner_radius * 2)
        
        painter.end()
    
    def enterEvent(self, event):
        """
        鼠标进入事件
        """
        self.update()
    
    def leaveEvent(self, event):
        """
        鼠标离开事件
        """
        self.update()
