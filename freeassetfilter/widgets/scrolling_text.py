#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 滚动文本自定义控件
实现单行文本的横向滚动效果，支持鼠标悬停暂停
"""

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QPoint, pyqtProperty
from PyQt5.QtGui import QFont, QColor, QFontMetrics, QPainter, QPaintEvent


class ScrollingText(QWidget):
    """
    滚动文本控件
    
    功能特性：
    - 具有指定横向宽度限制的容器布局
    - 单行文本显示，文本长度不受限制
    - 智能滚动逻辑：文本宽度超过容器宽度时自动启用滚动
    - 平滑的横向滚动动画（右→左→停顿→左→右→循环）
    - 鼠标悬停暂停功能
    - 性能优化，确保动画流畅
    
    信号：
        clicked: 点击信号
    """
    
    clicked = pyqtSignal()  # 点击信号
    
    def __init__(self, parent=None, text="", width=200, height=30, 
                 font_size=None, text_color=None, dpi_scale=1.0):
        """
        初始化滚动文本控件
        
        参数：
            parent (QWidget): 父控件
            text (str): 显示的文本内容
            width (int): 控件宽度（未缩放值）
            height (int): 控件高度（未缩放值）
            font_size (int): 字体大小（未缩放值），默认使用应用全局字体大小
            text_color (str): 文本颜色，默认使用主题色
            dpi_scale (float): DPI缩放比例
        """
        super().__init__(parent)
        
        # 保存原始参数用于DPI变化时重新计算
        self._original_width = width
        self._original_height = height
        self._original_font_size = font_size
        self._dpi_scale = dpi_scale
        
        # 文本内容
        self._text = text
        
        # 文本颜色
        self._text_color = QColor(text_color or "#333333")
        
        # 动画状态控制
        self._is_scrolling = False          # 是否正在滚动
        self._is_paused = False             # 是否暂停
        self._scroll_direction = 1          # 滚动方向：1=向左，-1=向右
        
        # 滚动偏移量（用于动画）
        self._scroll_offset = 0
        
        # 初始化UI
        self._init_ui()
        
        # 启用鼠标跟踪
        self.setMouseTracking(True)
        
        # 延迟初始化动画（确保布局完成）
        QTimer.singleShot(100, self._init_scroll_animation)
    
    def _init_ui(self):
        """初始化UI布局和控件"""
        # 设置控件固定大小
        scaled_width = int(self._original_width * self._dpi_scale)
        scaled_height = int(self._original_height * self._dpi_scale)
        self.setFixedSize(scaled_width, scaled_height)
        
        # 设置字体
        app = QApplication.instance()
        font_size = self._original_font_size or getattr(app, 'default_font_size', 14)
        scaled_font_size = int(font_size * self._dpi_scale)
        
        self._font = QFont()
        self._font.setPointSize(scaled_font_size)
        
        # 计算文本尺寸
        self._update_text_metrics()
    
    def _update_text_metrics(self):
        """更新文本尺寸信息"""
        font_metrics = QFontMetrics(self._font)
        self._text_width = font_metrics.horizontalAdvance(self._text)
        self._text_height = font_metrics.height()
        self._container_width = self.width()
        self._container_height = self.height()
        self._scroll_distance = max(0, self._text_width - self._container_width)
    
    def _init_scroll_animation(self):
        """初始化滚动动画"""
        # 重新计算文本尺寸
        self._update_text_metrics()
        
        # 判断是否需要滚动
        if self._scroll_distance <= 0:
            # 文本不需要滚动，居中显示
            self._is_scrolling = False
            self._scroll_offset = (self._container_width - self._text_width) // 2
            self.update()
            return
        
        # 需要滚动，创建动画
        self._create_scroll_animation()
    
    def _create_scroll_animation(self):
        """创建滚动动画"""
        if self._scroll_distance <= 0:
            return
        
        # 初始化偏移量为0（从左侧开始）
        self._scroll_offset = 0
        
        # 创建正向滚动动画（从右到左）
        self._forward_animation = QPropertyAnimation(self, b"scroll_offset")
        self._forward_animation.setDuration(3000)  # 3秒滚动时间
        self._forward_animation.setStartValue(0)
        self._forward_animation.setEndValue(-self._scroll_distance)
        self._forward_animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        # 创建反向滚动动画（从左到右）
        self._backward_animation = QPropertyAnimation(self, b"scroll_offset")
        self._backward_animation.setDuration(3000)
        self._backward_animation.setStartValue(-self._scroll_distance)
        self._backward_animation.setEndValue(0)
        self._backward_animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        # 连接动画完成信号
        self._forward_animation.finished.connect(self._on_forward_finished)
        self._backward_animation.finished.connect(self._on_backward_finished)
        
        # 标记为可滚动状态
        self._is_scrolling = True
        
        # 开始动画
        self._start_scroll_cycle()
    
    @pyqtProperty(float)
    def scroll_offset(self):
        """获取当前滚动偏移量"""
        return self._scroll_offset
    
    @scroll_offset.setter
    def scroll_offset(self, value):
        """设置滚动偏移量并触发重绘"""
        self._scroll_offset = value
        self.update()
    
    def _start_scroll_cycle(self):
        """开始滚动循环"""
        if not self._is_scrolling or self._is_paused:
            return
        
        # 从正向滚动开始
        self._scroll_direction = 1
        self._forward_animation.start()
    
    def _on_forward_finished(self):
        """正向滚动完成回调"""
        if not self._is_scrolling or self._is_paused:
            return
        
        # 停顿1秒后开始反向滚动
        QTimer.singleShot(1000, self._start_backward)
    
    def _start_backward(self):
        """开始反向滚动"""
        if not self._is_scrolling or self._is_paused:
            return
        
        self._scroll_direction = -1
        self._backward_animation.start()
    
    def _on_backward_finished(self):
        """反向滚动完成回调"""
        if not self._is_scrolling or self._is_paused:
            return
        
        # 停顿1秒后开始下一轮循环
        QTimer.singleShot(1000, self._start_scroll_cycle)
    
    def paintEvent(self, event):
        """
        绘制事件处理
        使用QPainter直接绘制文本，避免子控件被裁剪的问题
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        
        # 设置字体
        painter.setFont(self._font)
        
        # 设置文本颜色
        painter.setPen(self._text_color)
        
        # 计算垂直居中位置
        font_metrics = QFontMetrics(self._font)
        text_height = font_metrics.height()
        ascent = font_metrics.ascent()
        y = (self._container_height - text_height) // 2 + ascent
        
        # 绘制文本（使用滚动偏移量）
        painter.drawText(int(self._scroll_offset), int(y), self._text)
    
    def set_text(self, text):
        """
        设置文本内容
        
        参数：
            text (str): 要显示的文本
        """
        self._text = text
        
        # 停止现有动画
        self.stop()
        
        # 重新初始化动画
        QTimer.singleShot(50, self._init_scroll_animation)
    
    def get_text(self):
        """
        获取当前文本
        
        返回：
            str: 当前显示的文本
        """
        return self._text
    
    def set_text_color(self, color):
        """
        设置文本颜色
        
        参数：
            color (str): 十六进制颜色值，如"#333333"
        """
        self._text_color = QColor(color)
        self.update()
    
    def set_font_size(self, font_size):
        """
        设置字体大小
        
        参数：
            font_size (int): 字体大小（未缩放值）
        """
        self._original_font_size = font_size
        scaled_font_size = int(font_size * self._dpi_scale)
        
        self._font.setPointSize(scaled_font_size)
        
        # 重新计算滚动
        self._update_scroll()
    
    def set_dpi_scale(self, dpi_scale):
        """
        设置DPI缩放比例
        
        参数：
            dpi_scale (float): DPI缩放比例
        """
        self._dpi_scale = dpi_scale
        
        # 更新控件大小
        scaled_width = int(self._original_width * dpi_scale)
        scaled_height = int(self._original_height * dpi_scale)
        self.setFixedSize(scaled_width, scaled_height)
        
        # 更新字体大小
        if self._original_font_size:
            scaled_font_size = int(self._original_font_size * dpi_scale)
            self._font.setPointSize(scaled_font_size)
        
        # 重新计算滚动
        self._update_scroll()
    
    def _update_scroll(self):
        """更新滚动状态"""
        # 停止现有动画
        self.stop()
        
        # 重新初始化
        QTimer.singleShot(50, self._init_scroll_animation)
    
    def pause(self):
        """暂停滚动动画"""
        if not self._is_scrolling:
            return
        
        self._is_paused = True
        
        if hasattr(self, '_forward_animation') and self._forward_animation.state() == QPropertyAnimation.Running:
            self._forward_animation.pause()
        elif hasattr(self, '_backward_animation') and self._backward_animation.state() == QPropertyAnimation.Running:
            self._backward_animation.pause()
    
    def resume(self):
        """恢复滚动动画"""
        if not self._is_scrolling:
            return
        
        self._is_paused = False
        
        if hasattr(self, '_forward_animation') and self._forward_animation.state() == QPropertyAnimation.Paused:
            self._forward_animation.resume()
        elif hasattr(self, '_backward_animation') and self._backward_animation.state() == QPropertyAnimation.Paused:
            self._backward_animation.resume()
        else:
            # 如果没有暂停的动画，重新开始循环
            self._start_scroll_cycle()
    
    def stop(self):
        """停止滚动动画"""
        self._is_scrolling = False
        self._is_paused = False
        
        if hasattr(self, '_forward_animation'):
            self._forward_animation.stop()
        if hasattr(self, '_backward_animation'):
            self._backward_animation.stop()
        
        self._scroll_offset = 0
        self.update()
    
    def start(self):
        """开始滚动动画"""
        if self._is_scrolling:
            return
        
        self._update_scroll()
    
    def enterEvent(self, event):
        """鼠标进入事件"""
        super().enterEvent(event)
        self.pause()
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        super().leaveEvent(event)
        self.resume()
    
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
    
    def resizeEvent(self, event):
        """大小改变事件"""
        super().resizeEvent(event)
        
        # 更新容器尺寸
        self._container_width = self.width()
        self._container_height = self.height()
        
        # 容器大小改变时重新计算滚动
        if self._text:
            QTimer.singleShot(50, self._update_scroll)
    
    def is_scrolling_active(self):
        """
        判断是否正在滚动
        
        返回：
            bool: 是否正在滚动
        """
        return self._is_scrolling
    
    def is_paused(self):
        """
        判断是否处于暂停状态
        
        返回：
            bool: 是否暂停
        """
        return self._is_paused
