#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 滚动文本自定义控件
实现单行文本的横向滚动效果，支持鼠标悬停暂停
"""

from PyQt5.QtWidgets import QWidget, QApplication, QSizePolicy
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QPoint, pyqtProperty
from PyQt5.QtGui import QFont, QColor, QFontMetrics, QPainter, QPaintEvent


class ScrollingText(QWidget):
    """
    滚动文本控件
    
    功能特性：
    - 具有指定横向宽度限制的容器布局
    - 单行文本显示，文本长度不受限制
    - 智能滚动逻辑：文本宽度超过容器宽度时自动启用滚动
    - 支持线性和非线性动画
    - 支持单向循环和PingPong循环模式
    - 鼠标悬停暂停功能
    - 性能优化，确保动画流畅
    
    信号：
        clicked: 点击信号
    """
    
    clicked = pyqtSignal()  # 点击信号
    
    # 循环模式常量
    LOOP_MODE_SINGLE = "single"      # 单向循环：左→右→闪现回左→右
    LOOP_MODE_PINGPONG = "pingpong"  # PingPong：左→右→停顿→右→左
    
    def __init__(self, parent=None, text="", width=200, height=30, 
                 font_size=None, text_color=None, dpi_scale=1.0,
                 linear_animation=True, loop_mode=None):
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
            linear_animation (bool): 是否使用线性动画，True=线性，False=非线性（缓动），默认True
            loop_mode (str): 循环模式，"single"=单向循环，"pingpong"=往返循环，默认"single"
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
        
        # 动画配置
        self._linear_animation = linear_animation
        self._loop_mode = loop_mode or self.LOOP_MODE_SINGLE
        
        # 动画状态控制
        self._is_scrolling = False          # 是否正在滚动
        self._is_paused = False             # 是否暂停
        
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
        # 设置控件大小
        # 如果原始宽度为0，则完全填充父容器宽度
        if self._original_width <= 0:
            # 让布局系统自动设置宽度（完全填充父容器）
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumHeight(int(self._original_height * self._dpi_scale))
        else:
            # 使用固定宽度
            scaled_width = int(self._original_width * self._dpi_scale)
            scaled_height = int(self._original_height * self._dpi_scale)
            self.setFixedSize(scaled_width, scaled_height)
        
        # 设置字体
        app = QApplication.instance()
        # 使用原始字体大小，不在这里进行DPI缩放
        # 因为字体渲染系统会自动处理DPI缩放
        font_size = self._original_font_size or getattr(app, 'default_font_size', 14)
        
        self._font = QFont()
        self._font.setPointSize(font_size)
        
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
    
    def _calculate_scroll_duration(self):
        """
        根据文本长度计算滚动动画持续时间
        
        算法：保持滚动速度（像素/秒）相对恒定
        - 基础速度：25像素/秒
        - 最短持续时间：2000毫秒（避免过短文本滚动太快）
        - 最长持续时间：15000毫秒（避免过长文本滚动太慢）
        
        返回：
            int: 动画持续时间（毫秒）
        """
        # 基础速度：25像素/秒
        base_speed = 25 * self._dpi_scale
        
        # 计算基础持续时间
        duration = int((self._scroll_distance / base_speed) * 1000)
        
        # 限制在合理范围内
        min_duration = 2000  # 最短2秒
        max_duration = 15000  # 最长15秒
        
        return max(min_duration, min(duration, max_duration))
    
    def _get_easing_curve(self):
        """
        获取动画缓动曲线
        
        返回：
            QEasingCurve: 缓动曲线对象
        """
        if self._linear_animation:
            return QEasingCurve.Linear
        else:
            return QEasingCurve.InOutQuad
    
    def _create_scroll_animation(self):
        """创建滚动动画"""
        if self._scroll_distance <= 0:
            return
        
        # 初始化偏移量为0（从左侧开始）
        self._scroll_offset = 0
        
        # 根据文本长度计算动画持续时间
        scroll_duration = self._calculate_scroll_duration()
        
        # 获取缓动曲线
        easing_curve = self._get_easing_curve()
        
        # 创建正向滚动动画（从右到左）
        self._forward_animation = QPropertyAnimation(self, b"scroll_offset")
        self._forward_animation.setDuration(scroll_duration)
        self._forward_animation.setStartValue(0)
        self._forward_animation.setEndValue(-self._scroll_distance)
        self._forward_animation.setEasingCurve(easing_curve)
        
        # 连接动画完成信号
        self._forward_animation.finished.connect(self._on_forward_finished)
        
        # 如果是PingPong模式，创建反向动画
        if self._loop_mode == self.LOOP_MODE_PINGPONG:
            self._backward_animation = QPropertyAnimation(self, b"scroll_offset")
            self._backward_animation.setDuration(scroll_duration)
            self._backward_animation.setStartValue(-self._scroll_distance)
            self._backward_animation.setEndValue(0)
            self._backward_animation.setEasingCurve(easing_curve)
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
        
        # 开始正向滚动
        self._forward_animation.start()
    
    def _on_forward_finished(self):
        """正向滚动完成回调"""
        if not self._is_scrolling or self._is_paused:
            return
        
        if self._loop_mode == self.LOOP_MODE_PINGPONG:
            # PingPong模式：停顿后开始反向滚动
            QTimer.singleShot(1000, self._start_backward)
        else:
            # 单向循环模式：停顿后闪现回起点，重新开始
            QTimer.singleShot(500, self._restart_single_loop)
    
    def _start_backward(self):
        """开始反向滚动（PingPong模式）"""
        if not self._is_scrolling or self._is_paused:
            return
        
        self._backward_animation.start()
    
    def _on_backward_finished(self):
        """反向滚动完成回调（PingPong模式）"""
        if not self._is_scrolling or self._is_paused:
            return
        
        # 停顿1秒后开始下一轮循环
        QTimer.singleShot(1000, self._start_scroll_cycle)
    
    def _restart_single_loop(self):
        """重新开始单向循环"""
        if not self._is_scrolling or self._is_paused:
            return
        
        # 闪现回起点（无动画）
        self._scroll_offset = 0
        self.update()
        
        # 短暂停顿后开始下一轮
        QTimer.singleShot(200, self._start_scroll_cycle)
    
    def resizeEvent(self, event):
        """
        大小改变事件处理
        实时监测控件大小变化，重新计算滚动状态
        """
        super().resizeEvent(event)
        # 重新计算容器尺寸和滚动状态
        self._update_text_metrics()
        self._recalculate_scroll_state()
    
    def _recalculate_scroll_state(self):
        """
        重新计算滚动状态
        根据当前容器宽度决定是居中显示还是滚动
        """
        # 重新计算滚动距离
        self._scroll_distance = max(0, self._text_width - self._container_width)
        
        if self._scroll_distance <= 0:
            # 文本不需要滚动，居中显示
            if self._is_scrolling:
                # 从滚动模式切换到居中模式
                self._is_scrolling = False
                self._scroll_offset = (self._container_width - self._text_width) // 2
                self.update()
        else:
            # 文本需要滚动
            if not self._is_scrolling:
                # 从居中模式切换到滚动模式，创建动画
                self._create_scroll_animation()
            else:
                # 已经在滚动模式，重新计算动画终点
                self._update_animation_end_position()
    
    def _update_animation_end_position(self):
        """更新动画终点位置（用于大小改变时）"""
        if not self._forward_animation:
            return
        
        end_value = -self._scroll_distance
        self._forward_animation.setEndValue(end_value)
        
        if self._backward_animation:
            self._backward_animation.setStartValue(end_value)
    
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
        # 使用原始字体大小，不在这里进行DPI缩放
        # 因为字体渲染系统会自动处理DPI缩放
        self._font.setPointSize(font_size)
        
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
        
        # 注意：字体大小不随DPI缩放而改变
        # 因为字体渲染系统会自动处理DPI缩放
        # 只需重新计算滚动参数
        
        # 重新计算滚动
        self._update_scroll()
    
    def set_linear_animation(self, linear):
        """
        设置是否使用线性动画
        
        参数：
            linear (bool): True=线性动画，False=非线性动画（缓动）
        """
        self._linear_animation = linear
        
        # 重新创建动画
        self._update_scroll()
    
    def set_loop_mode(self, mode):
        """
        设置循环模式
        
        参数：
            mode (str): "single"=单向循环，"pingpong"=往返循环
        """
        if mode not in (self.LOOP_MODE_SINGLE, self.LOOP_MODE_PINGPONG):
            raise ValueError(f"无效的循环模式: {mode}，可选值: 'single', 'pingpong'")
        
        self._loop_mode = mode
        
        # 重新创建动画
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
