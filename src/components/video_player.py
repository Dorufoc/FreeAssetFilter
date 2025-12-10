#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

独立的视频播放器组件
提供完整的视频和音频播放功能和用户界面
"""

import sys
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel,
    QFileDialog, QStyle, QMessageBox, QGraphicsBlurEffect
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QIcon, QPainter, QColor, QPen, QBrush, QPixmap, QImage
from src.utils.svg_renderer import SvgRenderer

# 用于读取音频文件封面
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.aiff import AIFF
from mutagen.apev2 import APEv2
from mutagen.asf import ASF

# 用于图像处理
from PIL import Image
import io

from src.core.player_core import PlayerCore


class CustomProgressBar(QWidget):
    """
    自定义进度条控件
    支持点击任意位置跳转和拖拽功能
    """
    valueChanged = pyqtSignal(int)  # 值变化信号
    userInteracting = pyqtSignal()  # 用户开始交互信号
    userInteractionEnded = pyqtSignal()  # 用户结束交互信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 28)
        self.setMaximumHeight(28)
        
        # 进度条属性
        self._minimum = 0
        self._maximum = 1000
        self._value = 0
        self._is_pressed = False
        self._last_pos = 0
        
        # 外观属性
        self._bg_color = QColor(99, 99, 99)  # 进度条背景颜色
        self._progress_color = QColor(0, 120, 212)  # #0078d4
        self._handle_color = QColor(0, 120, 212)  # #0078d4
        self._handle_hover_color = QColor(16, 110, 190)  # #106ebe
        self._handle_pressed_color = QColor(0, 90, 158)  # #005a9e
        self._handle_radius = 12
        self._bar_height = 6
        self._bar_radius = 3
        
        # SVG 图标路径
        import os
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Icon')
        self._icon_path = os.path.join(icon_dir, '条-顶-尾.svg')
        self._head_icon_path = os.path.join(icon_dir, '条-顶-头.svg')
        self._middle_icon_path = os.path.join(icon_dir, '条-顶-中.svg')
        
        # 渲染 SVG 图标为 QPixmap
        self._handle_pixmap = SvgRenderer.render_svg_to_pixmap(self._icon_path, self._handle_radius * 2)
        self._head_pixmap = SvgRenderer.render_svg_to_pixmap(self._head_icon_path, self._handle_radius * 2)
        # 条顶中 SVG 会在绘制时根据需要直接渲染，这里只保存路径
    
    def setRange(self, minimum, maximum):
        """
        设置进度条范围
        """
        self._minimum = minimum
        self._maximum = maximum
        self.update()
    
    def setValue(self, value):
        """
        设置进度条值
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self.update()
    
    def value(self):
        """
        获取当前进度值
        """
        return self._value
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        if event.button() == Qt.LeftButton:
            self._is_pressed = True
            self._last_pos = event.pos().x()
            self.userInteracting.emit()
            # 计算点击位置对应的进度值
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
            self.userInteractionEnded.emit()
    
    def _update_value_from_pos(self, x_pos):
        """
        根据鼠标位置更新进度值
        """
        # 计算进度条总宽度
        bar_width = self.width() - (self._handle_radius * 2)
        # 计算鼠标在进度条上的相对位置
        relative_x = x_pos - self._handle_radius
        if relative_x < 0:
            relative_x = 0
        elif relative_x > bar_width:
            relative_x = bar_width
        
        # 计算对应的进度值
        ratio = relative_x / bar_width
        value = int(self._minimum + ratio * (self._maximum - self._minimum))
        self.setValue(value)
    
    def paintEvent(self, event):
        """
        绘制进度条
        """
        # 确保Qt已导入
        from PyQt5.QtCore import Qt
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        
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
        
        # 绘制已播放部分
        progress_width = int(bar_width * (self._value - self._minimum) / (self._maximum - self._minimum))
        progress_rect = QRect(
            self._handle_radius, bar_y, 
            progress_width, self._bar_height
        )
        
        # 使用条顶中 SVG 图形填充已播放部分
        if progress_width > 0:
            try:
                from PyQt5.QtSvg import QSvgRenderer
                from PyQt5.QtGui import QPixmap, QTransform
                from PyQt5.QtCore import Qt
                
                # 先渲染 SVG 到临时 QPixmap
                svg_renderer = QSvgRenderer(self._middle_icon_path)
                # 使用与头和尾相同的尺寸
                icon_size = self._handle_radius * 2
                temp_pixmap = QPixmap(icon_size, icon_size)
                temp_pixmap.fill(Qt.transparent)
                painter_temp = QPainter(temp_pixmap)
                svg_renderer.render(painter_temp)
                painter_temp.end()
                
                # 将临时 pixmap 旋转 90 度
                transform = QTransform()
                transform.rotate(90)
                rotated_pixmap = temp_pixmap.transformed(transform, Qt.SmoothTransformation)
                
                # 计算与头和尾相同的纵向宽度的矩形
                # 头图标的纵向宽度是 self._handle_radius * 2
                # 计算垂直居中的位置
                middle_y = (rect.height() - self._handle_radius * 2) // 2
                middle_rect = QRect(
                    self._handle_radius, middle_y, 
                    progress_width, self._handle_radius * 2
                )
                
                # 拉伸渲染旋转后的 pixmap 到中间矩形
                painter.drawPixmap(middle_rect, rotated_pixmap)
            except Exception as e:
                print(f"渲染条顶中 SVG 失败: {e}")
                # 备用方案：使用纯色填充
                painter.setBrush(QBrush(self._progress_color))
                painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        else:
            # 进度为0时，不绘制已播放部分
            pass
        
        # 绘制已完成区域的起始点 - 使用条-顶-头.svg图标（逆时针旋转90度）
        head_x = -self._handle_radius // 2  # 向左偏移一点
        head_y = (rect.height() - self._handle_radius * 2) // 2
        
        if not self._head_pixmap.isNull():
            # 保存当前画家状态
            painter.save()
            
            # 计算旋转中心
            center_x = head_x + self._handle_radius
            center_y = head_y + self._handle_radius
            
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
        handle_y = (rect.height() - self._handle_radius * 2) // 2
        
        # 确保图标已正确加载
        if not self._handle_pixmap.isNull():
            # 保存当前画家状态
            painter.save()
            
            # 计算旋转中心
            center_x = handle_x + self._handle_radius
            center_y = handle_y + self._handle_radius
            
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
            painter.drawEllipse(handle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
        
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
        self._handle_radius = 12
        # 设置合理的最小宽度，确保音量条有足够的可见区域
        min_width = 100  # 固定最小宽度，确保音量条不会被压缩得太小
        self.setMinimumSize(min_width, 28)
        self.setMaximumHeight(28)
        
        # 音量条属性
        self._minimum = 0
        self._maximum = 100
        self._value = 50  # 默认音量50%
        self._is_pressed = False
        self._last_pos = 0
        
        # 外观属性
        self._bg_color = QColor(99, 99, 99)  # 音量条背景颜色
        self._progress_color = QColor(0, 120, 212)  # #0078d4
        self._bar_height = 6
        self._bar_radius = 3
        
        # SVG 图标路径 - 只使用进度条按钮.svg
        import os
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Icon')
        self._progress_button_icon = os.path.join(icon_dir, '进度条按钮.svg')
        
        # 渲染 SVG 图标为 QPixmap
        self._handle_pixmap = SvgRenderer.render_svg_to_pixmap(self._progress_button_icon, self._handle_radius * 2)
    
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
        
        # 绘制滑块 - 只使用进度条按钮.svg 图标
        handle_x = self._handle_radius + progress_width
        # 确保滑块不会超出音量条范围，考虑实际窗口宽度
        max_handle_x = max(self._handle_radius, self.width() - self._handle_radius * 2)
        handle_x = min(handle_x, max_handle_x)
        # 确保滑块不会小于最小值
        handle_x = max(handle_x, self._handle_radius)
        handle_y = (rect.height() - self._handle_radius * 2) // 2
        
        # 确保图标已正确加载
        if not self._handle_pixmap.isNull():
            # 保存当前画家状态
            painter.save()
            
            # 计算旋转中心
            center_x = handle_x + self._handle_radius
            center_y = handle_y + self._handle_radius
            
            # 移动坐标原点到旋转中心
            painter.translate(center_x, center_y)
            
            # 绘制图标（不需要旋转）
            painter.drawPixmap(-self._handle_radius, -self._handle_radius, self._handle_pixmap)
            
            # 恢复画家状态
            painter.restore()
        else:
            # 备用方案：如果 SVG 加载失败，绘制圆形滑块
            painter.setBrush(QBrush(self._progress_color))
            painter.setPen(Qt.NoPen)  # 去除滑块边框
            painter.drawEllipse(handle_x, handle_y, self._handle_radius * 2, self._handle_radius * 2)
        
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


class VideoPlayer(QWidget):
    """
    通用媒体播放器组件
    提供完整的视频和音频播放功能和用户界面
    """
    
    def __init__(self, parent=None):
        """
        初始化视频播放器组件
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        # 确保所有属性在初始化前都被定义
        self.media_frame = None
        self.video_frame = None
        self.audio_stacked_widget = None
        self.background_label = None
        self.overlay_widget = None
        self.cover_label = None
        self.audio_info_label = None
        self.audio_container = None
        self.progress_slider = None
        self.time_label = None
        self.play_button = None
        self.timer = None
        self.player_core = None
        self._user_interacting = False
        
        # 设置窗口属性
        self.setWindowTitle("Video Player")
        self.setMinimumSize(480, 400)
        
        # 初始化所有属性
        self.init_attributes()
        
        # 创建UI组件
        self.init_ui()
        
        # 初始化播放器核心
        self.player_core = PlayerCore()
        
        # 创建定时器用于更新进度
        self.timer = QTimer(self)
        self.timer.setInterval(500)  # 500ms更新一次，减少UI更新频率，提高流畅度
        self.timer.timeout.connect(self.update_progress)
    
    def init_attributes(self):
        """
        初始化所有属性，确保在使用前都被定义
        """
        # 媒体显示区域
        self.media_frame = QWidget()
        self.video_frame = QWidget()
        self.audio_stacked_widget = QWidget()
        self.background_label = QLabel()
        self.overlay_widget = QWidget()
        self.cover_label = QLabel()
        self.audio_info_label = QLabel()
        self.audio_container = QWidget()
        
        # 控制组件
        self.progress_slider = CustomProgressBar()
        self.time_label = QLabel("00:00 / 00:00")
        self.play_button = QPushButton()
        self.volume_slider = CustomVolumeBar()  # 音量控制条
        self.volume_button = QPushButton()  # 音量图标按钮，替换文字描述
        
        # 倍速控制组件
        self.speed_button = QPushButton("1.0x")
        self.speed_menu = None  # 将在init_ui中初始化
        self.speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
        self.is_speed_menu_visible = False
        self.speed_menu_timer = None  # 菜单关闭定时器
        
        # 状态标志
        self._user_interacting = False
        self.player_core = None
        self.timer = None
        
        # 音量控制相关属性
        self._is_muted = False  # 静音状态
        self._previous_volume = 50  # 静音前的音量值
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 媒体显示区域设置
        self.media_frame.setStyleSheet("background-color: white;")
        self.media_frame.setMinimumSize(400, 300)
        
        # 视频显示区域设置
        self.video_frame.setStyleSheet("background-color: transparent;")
        self.video_frame.setMinimumSize(400, 300)
        
        # 音频显示区域设置
        audio_layout = QVBoxLayout(self.audio_stacked_widget)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(0)
        
        # 音频背景设置
        self.background_label.setStyleSheet("background-color: #1a1a1a;")
        self.background_label.setScaledContents(True)
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setMinimumSize(400, 300)
        
        # 添加模糊效果
        self.blur_effect = QGraphicsBlurEffect()
        self.blur_effect.setBlurRadius(20)
        self.background_label.setGraphicsEffect(self.blur_effect)
        
        # 背景遮罩
        self.overlay_widget.setStyleSheet("background-color: rgba(0, 0, 0, 0.5);")
        
        # 封面图显示
        self.cover_label.setStyleSheet("""
            background-color: #2d2d2d;
            border-radius: 15px;
            border: none;
            color: white;
            font-size: 100px;
        """)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setMinimumSize(200, 200)
        self.cover_label.setMaximumSize(300, 300)
        self.cover_label.setScaledContents(True)
        
        # 音频信息标签
        self.audio_info_label.setText("正在播放音频")
        self.audio_info_label.setStyleSheet("""
            color: white;
            font-size: 18px;
            font-weight: bold;
            background-color: transparent;
            padding: 15px 0;
        """)
        self.audio_info_label.setAlignment(Qt.AlignCenter)
        self.audio_info_label.setWordWrap(True)
        
        # 音频显示容器
        audio_container_layout = QVBoxLayout(self.audio_container)
        audio_container_layout.setContentsMargins(0, 0, 0, 0)
        audio_container_layout.setSpacing(15)
        audio_container_layout.setAlignment(Qt.AlignCenter)
        
        # 添加封面图和文件名到容器
        audio_container_layout.addWidget(self.cover_label)
        audio_container_layout.addWidget(self.audio_info_label)
        
        # 设置音频容器样式
        self.audio_container.setStyleSheet("background-color: transparent;")
        self.audio_container.setMinimumSize(400, 300)
        
        # 构建音频堆叠布局
        audio_layout.addWidget(self.background_label)
        audio_layout.addWidget(self.overlay_widget)
        audio_layout.addWidget(self.audio_container)
        
        # 媒体布局
        media_layout = QVBoxLayout(self.media_frame)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(0)
        media_layout.addWidget(self.video_frame)
        media_layout.addWidget(self.audio_stacked_widget)
        
        # 音频界面默认隐藏
        self.audio_stacked_widget.hide()
        
        # 添加媒体区域到主布局
        main_layout.addWidget(self.media_frame, 1)
        
        # 控制按钮区域 - 根据Figma设计稿更新样式
        control_container = QWidget()
        control_container.setStyleSheet("background-color: #FFFFFF; border: 1px solid #FFFFFF; border-radius: 45x 45px 45px 45px;")
        self.control_layout = QHBoxLayout(control_container)
        self.control_layout.setContentsMargins(6, 6, 6, 6)
        self.control_layout.setSpacing(6)
        
        # 播放/暂停按钮 - 更新为白色背景和边框
        self.play_button.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #FFFFFF;
                padding: 12px 12px;
                border-radius: 0px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #FFFFFF;
            }
            QPushButton:pressed {
                background-color: #FFFFFF;
            }
        """)
        
        # 初始化鼠标悬停状态变量
        self._is_mouse_over_play_button = False
        
        # 设置播放按钮SVG图标
        self._update_play_button_icon()
        self.play_button.clicked.connect(self.toggle_play_pause)
        # 连接鼠标事件
        self.play_button.enterEvent = lambda event: self._update_mouse_hover_state(True)
        self.play_button.leaveEvent = lambda event: self._update_mouse_hover_state(False)
        self.control_layout.addWidget(self.play_button)
        
        # 进度条和时间标签 - 从主布局移动到播放按钮右侧
        # 创建一个垂直布局容器，用于放置进度条、时间标签和音量控件
        progress_time_container = QWidget()
        progress_time_container.setStyleSheet("background-color: #FFFFFF; border: 1px solid #FFFFFF;")
        progress_time_layout = QVBoxLayout(progress_time_container)
        progress_time_layout.setContentsMargins(0, 0, 0, 0)
        progress_time_layout.setSpacing(1)
        
        # 自定义进度条设置
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        # 连接进度条信号
        self.progress_slider.userInteractionEnded.connect(self._handle_user_seek)
        self.progress_slider.userInteracting.connect(self.pause_progress_update)
        self.progress_slider.userInteractionEnded.connect(self.resume_progress_update)
        progress_time_layout.addWidget(self.progress_slider)
        
        # 创建一个水平布局来放置音量控制、时间标签和倍速按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        
        # 音量图标按钮设置
        self.volume_button.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #FFFFFF;
                padding: 5px;
                border-radius: 0px;
                min-width: 20px;
                max-width: 20px;
                max-height: 20px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
        """)
        # 设置鼠标指针为手型，表示可点击
        self.volume_button.setCursor(Qt.PointingHandCursor)
        # 添加点击事件，实现一键静音/恢复
        self.volume_button.clicked.connect(self.toggle_mute)
        bottom_layout.addWidget(self.volume_button)  # 音量图标居左
        # 初始化音量图标
        self.update_volume_icon()
        
        # 音量控制条设置
        self.volume_slider.setRange(0, 100)
        # 加载保存的音量设置
        saved_volume = self.load_volume_setting()
        # 设置音量滑块值
        self.volume_slider.setValue(saved_volume)
        # 设置初始音量
        if self.player_core:
            self.player_core.set_volume(saved_volume)
        # 保存当前音量作为静音前的初始音量
        self._previous_volume = saved_volume
        # 连接音量条信号
        self.volume_slider.valueChanged.connect(self.set_volume)
        bottom_layout.addWidget(self.volume_slider)  # 音量滑块居左
        
        # 添加伸缩项，将音量组件和时间/倍速组件分开
        bottom_layout.addStretch(1)
        
        # 时间标签样式
        self.time_label.setStyleSheet("""
            color: #000000;
            background-color: #FFFFFF;
            padding: 0 5px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            font-size: 16px;
            text-align: left;
            border: 1px solid #FFFFFF;
        """)
        bottom_layout.addWidget(self.time_label)  # 时间标签在进度条右侧
        
        # 添加倍速控制按钮
        self.speed_button.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #FFFFFF;
                padding: 15px 10px;
                border-radius: 20px;
                min-width: 40px;
                max-width: 40px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
        """)
        # 将点击事件改为鼠标悬停事件
        self.speed_button.enterEvent = self.show_speed_menu
        self.speed_button.leaveEvent = lambda event: self._handle_speed_button_leave(event)
        bottom_layout.addWidget(self.speed_button)  # 倍速按钮居右
        
        # 将水平布局添加到垂直布局中
        progress_time_layout.addLayout(bottom_layout)
        
        # 将包含进度条和时间/音量控件的容器添加到控制布局中
        self.control_layout.addWidget(progress_time_container, 1)
        
        main_layout.addWidget(control_container)
        
        # 初始化菜单关闭定时器
        from PyQt5.QtCore import QTimer
        self.speed_menu_timer = QTimer(self)
        self.speed_menu_timer.setInterval(300)  # 300毫秒延迟
        self.speed_menu_timer.setSingleShot(True)  # 单次触发
        self.speed_menu_timer.timeout.connect(self.hide_speed_menu)
        
        # 创建倍速菜单（使用QMenu实现真正的浮动窗口）
        from PyQt5.QtWidgets import QMenu
        self.speed_menu = QMenu(self)
        self.speed_menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 5px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 16px;
            }
            QMenu::item {
                padding: 8px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0078d4;
                color: white;
            }
        """)
        
        # 添加倍速菜单项
        for speed in self.speed_options:
            action = self.speed_menu.addAction(f"{speed}x")
            action.triggered.connect(lambda checked, s=speed: self.set_speed(s))
        
        # 为菜单添加事件过滤器，用于监听enter和leave事件
        self.speed_menu.installEventFilter(self)
        
        # 设置主窗口样式 - 根据Figma设计稿更新大圆角
        self.setStyleSheet("""
            background-color: #1a1a1a;
            border-radius: 20px;
        """)
        
        
    def eventFilter(self, obj, event):
        """
        事件过滤器，用于监听菜单的enter和leave事件
        
        Args:
            obj: 事件对象
            event: PyQt事件对象
        
        Returns:
            bool: 是否拦截事件
        """
        from PyQt5.QtCore import QEvent
        
        if obj == self.speed_menu:
            if event.type() == QEvent.Enter:
                # 鼠标进入菜单，停止定时器
                if self.speed_menu_timer:
                    self.speed_menu_timer.stop()
            elif event.type() == QEvent.Leave:
                # 鼠标离开菜单，只有当鼠标不在倍速按钮上时才启动定时器
                if self.speed_menu_timer and self.is_speed_menu_visible and not self._is_mouse_over_speed_button():
                    self.speed_menu_timer.start()
        return False
    
    def show_speed_menu(self, event=None):
        """
        显示倍速菜单
        
        Args:
            event: PyQt事件对象，可选
        """
        # 停止任何现有的定时器
        if self.speed_menu_timer:
            self.speed_menu_timer.stop()
        
        # 获取倍速按钮的位置
        button_pos = self.speed_button.mapToGlobal(self.speed_button.rect().topLeft())
        
        # 使用QMenu的popup方法显示菜单，这不会阻塞主线程
        menu_height = len(self.speed_options) * 35 + 10
        menu_y = button_pos.y() - menu_height - 5
        menu_pos = button_pos
        menu_pos.setY(menu_y)
        self.speed_menu.popup(menu_pos)
        self.is_speed_menu_visible = True
    
    def hide_speed_menu(self, event=None):
        """
        隐藏倍速菜单
        
        Args:
            event: PyQt事件对象，可选
        """
        # 停止定时器
        if self.speed_menu_timer:
            self.speed_menu_timer.stop()
        
        # 关闭菜单
        self.speed_menu.close()
        self.is_speed_menu_visible = False
    
    def _is_mouse_over_speed_button(self):
        """
        检查鼠标是否在倍速按钮上
        
        Returns:
            bool: 鼠标是否在倍速按钮上
        """
        from PyQt5.QtGui import QCursor
        # 获取鼠标全局位置
        global_pos = QCursor.pos()
        # 转换为相对于倍速按钮的位置
        local_pos = self.speed_button.mapFromGlobal(global_pos)
        # 检查是否在按钮范围内
        return self.speed_button.rect().contains(local_pos)
    
    def _handle_speed_button_leave(self, event):
        """
        处理倍速按钮的鼠标离开事件
        启动定时器，300毫秒后关闭菜单
        
        Args:
            event: PyQt事件对象
        """
        # 只有当鼠标不在倍速按钮上且菜单可见时，才启动定时器
        if self.speed_menu_timer and self.is_speed_menu_visible and not self._is_mouse_over_speed_button():
            self.speed_menu_timer.start()
    
    def set_speed(self, speed):
        """
        设置播放速度
        
        Args:
            speed (float): 播放速度
        """
        # 更新倍速按钮显示
        self.speed_button.setText(f"{speed}x")
        
        # 设置播放器速度
        if self.player_core:
            self.player_core.set_rate(speed)
        
        # 隐藏菜单 - QMenu会自动处理关闭，这里只需要更新状态
        self.is_speed_menu_visible = False
    
    def extract_cover_art(self, file_path):
        """
        从音频文件中提取封面图
        
        Args:
            file_path (str): 音频文件路径
        
        Returns:
            QPixmap or None: 封面图，如果没有则返回None
        """
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            # 根据文件类型选择不同的提取方法
            if ext in ['.mp3', '.aiff', '.ape', '.wav']:
                # ID3格式文件
                try:
                    audio = ID3(file_path)
                    if 'APIC:' in audio:
                        apic = audio['APIC:']
                        return self._pixmap_from_bytes(apic.data)
                except Exception:
                    pass
            elif ext in ['.m4a', '.mp4']:
                # MP4格式文件
                try:
                    audio = MP4(file_path)
                    if 'covr' in audio:
                        covr = audio['covr'][0]
                        return self._pixmap_from_bytes(covr)
                except Exception:
                    pass
            elif ext == '.flac':
                # FLAC格式文件
                try:
                    audio = FLAC(file_path)
                    if 'picture' in audio:
                        picture = audio['picture'][0]
                        return self._pixmap_from_bytes(picture.data)
                except Exception:
                    pass
            elif ext == '.ogg':
                # OGG格式文件
                try:
                    audio = OggVorbis(file_path)
                    # OGG文件封面图处理比较复杂，这里简化处理
                    pass
                except Exception:
                    pass
            elif ext == '.wma':
                # WMA格式文件
                try:
                    audio = ASF(file_path)
                    # ASF文件封面图处理
                    pass
                except Exception:
                    pass
            
            return None
        except Exception:
            return None
    
    def _pixmap_from_bytes(self, data):
        """
        将字节数据转换为QPixmap
        
        Args:
            data (bytes): 图像字节数据
        
        Returns:
            QPixmap or None: 转换后的QPixmap，如果失败则返回None
        """
        try:
            # 使用PIL处理图像数据
            pil_image = Image.open(io.BytesIO(data))
            
            # 转换为RGB格式
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            
            # 转换为QImage
            img_data = pil_image.tobytes()
            q_image = QImage(img_data, pil_image.width, pil_image.height, pil_image.width * 3, QImage.Format_RGB888)
            
            # 转换为QPixmap
            return QPixmap.fromImage(q_image)
        except Exception:
            return None
    
    def open_file(self):
        """
        打开媒体文件（视频或音频）
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开媒体文件", "", 
            "视频文件 (*.mp4 *.mov *.m4v *.flv *.mxf *.3gp *.mpg *.avi *.wmv *.mkv *.webm *.vob *.ogv *.rmvb);;音频文件 (*.mp3 *.wav *.flac *.aac *.ogg *.wma *.m4a *.aiff *.ape *.opus);;所有文件 (*)"
        )
        
        if file_path:
            self.load_media(file_path)
    
    def load_media(self, file_path):
        """
        加载媒体文件（视频或音频）
        
        Args:
            file_path (str): 媒体文件路径
        """
        try:
            print(f"VideoPlayer.load_media: 正在加载文件: {file_path}")
            # 确保player_core已初始化
            if not self.player_core:
                self.player_core = PlayerCore()
            
            # 停止当前播放并重置进度条
            self.player_core.stop()
            self.progress_slider.setValue(0)
            self.time_label.setText("00:00 / 00:00")
            
            # 尝试设置媒体
            media_set = self.player_core.set_media(file_path)
            print(f"VideoPlayer.load_media: 设置媒体结果: {media_set}")
            
            if media_set:
                # 获取文件扩展名，判断文件类型
                ext = os.path.splitext(file_path)[1].lower()
                
                # 检查是否为视频文件
                is_video = ext in self.player_core.SUPPORTED_VIDEO_FORMATS
                # 检查是否为音频文件
                is_audio = ext in self.player_core.SUPPORTED_AUDIO_FORMATS
                
                if is_video:
                    # 视频文件：显示视频帧，隐藏音频界面
                    self.video_frame.show()
                    self.audio_stacked_widget.hide()
                    # 设置视频输出窗口
                    self.player_core.set_window(self.video_frame.winId())
                elif is_audio:
                    # 音频文件：隐藏视频帧，显示音频界面
                    self.video_frame.hide()
                    self.audio_stacked_widget.show()
                    # 清除视频输出窗口
                    self.player_core.clear_window()
                    
                    # 提取音频封面图
                    cover_pixmap = self.extract_cover_art(file_path)
                    
                    if cover_pixmap:
                        # 设置封面图到背景（模糊效果）
                        self.background_label.setPixmap(cover_pixmap.scaled(
                            self.media_frame.size(), 
                            Qt.KeepAspectRatioByExpanding, 
                            Qt.SmoothTransformation
                        ))
                        
                        # 设置封面图到中央显示（圆角正方形）
                        self.cover_label.setPixmap(cover_pixmap.scaled(
                            self.cover_label.size(), 
                            Qt.KeepAspectRatio, 
                            Qt.SmoothTransformation
                        ))
                        
                        # 重置封面图样式为圆角正方形
                        self.cover_label.setStyleSheet("""
                            background-color: #2d2d2d;
                            border-radius: 15px;
                            border: none;
                        """)
                    else:
                        # 没有封面图，使用默认样式
                        self.background_label.setStyleSheet("background-color: #1a1a1a;")
                        self.background_label.setPixmap(QPixmap())
                        
                        # 设置默认音乐图标
                        self.cover_label.setPixmap(QPixmap())
                        self.cover_label.setText("🎵")
                        self.cover_label.setStyleSheet("""
                            background-color: #2d2d2d;
                            border-radius: 15px;
                            border: none;
                            color: white;
                            font-size: 100px;
                        """)
                    
                    # 更新音频文件名，移除扩展名，添加适当padding
                    file_name = os.path.basename(file_path)
                    file_name_no_ext = os.path.splitext(file_name)[0]
                    self.audio_info_label.setText(file_name_no_ext)
                
                # 更新窗口标题
                self.setWindowTitle(f"Media Player - {os.path.basename(file_path)}")
                
                # 启用循环播放
                self.player_core.set_loop(True)
                
                # 重置倍速为默认1.0x
                self.set_speed(1.0)
                
                # 开始播放
                if not self.player_core.play():
                    # 播放失败，显示警告
                    print(f"警告：无法播放媒体文件 - {file_path}")
                
                self.update_play_button()
                self.timer.start()
            else:
                print(f"VideoPlayer.load_media: 设置媒体失败")
                # 显示友好的错误信息
                QMessageBox.information(self, "信息", f"无法加载媒体文件: {os.path.basename(file_path)}\n可能是VLC配置问题或文件格式不支持。")
        except Exception as e:
            print(f"加载媒体时出错: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "警告", f"媒体播放可能有问题: {str(e)}")
    
    def toggle_play_pause(self):
        """
        切换播放/暂停状态
        """
        try:
            current_state = self.player_core.is_playing
            if current_state:
                self.player_core.pause()
            else:
                # 播放可能失败，需要检查返回值
                success = self.player_core.play()
                # 如果播放失败，确保状态保持一致
                if not success:
                    self.player_core._is_playing = False
            # 立即更新按钮图标
            self._update_play_button_icon()
        except Exception as e:
            print(f"切换播放状态时出错: {e}")
    
    def stop(self):
        """
        停止播放
        """
        try:
            if self.player_core:
                self.player_core.stop()
            self.update_play_button()
            self.update_progress()
            if self.timer:
                self.timer.stop()
        except Exception as e:
            print(f"停止播放时出错: {e}")
    
    def set_volume(self, value):
        """
        设置音量
        
        Args:
            value (int): 音量值（0-100）
        """
        try:
            if self.player_core:
                # 如果当前是静音状态，取消静音
                if self._is_muted:
                    self._is_muted = False
                
                # 保存当前音量作为静音前的音量
                self._previous_volume = value
                
                # 设置播放器音量
                self.player_core.set_volume(value)
                
                # 保存音量设置
                self.save_volume_setting(value)
                
                # 更新音量图标
                self.update_volume_icon()
        except Exception as e:
            print(f"设置音量时出错: {e}")
    
    def save_volume_setting(self, volume):
        """
        保存音量设置到配置文件
        
        Args:
            volume (int): 音量值（0-100）
        """
        import os
        import json
        
        try:
            # 配置文件路径
            config_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
            config_file = os.path.join(config_dir, 'player_config.json')
            
            # 确保配置目录存在
            os.makedirs(config_dir, exist_ok=True)
            
            # 读取现有配置
            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # 更新音量设置
            config['volume'] = volume
            
            # 保存配置
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存音量设置时出错: {e}")
    
    def load_volume_setting(self):
        """
        从配置文件加载音量设置
        
        Returns:
            int: 保存的音量值，默认50
        """
        import os
        import json
        
        try:
            # 配置文件路径
            config_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
            config_file = os.path.join(config_dir, 'player_config.json')
            
            # 读取配置
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get('volume', 50)
        except Exception as e:
            print(f"加载音量设置时出错: {e}")
        
        return 50  # 默认音量
    
    def update_volume_icon(self):
        """
        根据音量状态更新音量图标
        """
        try:
            # 图标路径
            icon_dir = os.path.join(os.path.dirname(__file__), '..', 'Icon')
            
            # 固定图标大小
            fixed_icon_size = 32
            
            # 根据静音状态选择不同的图标
            if self._is_muted:
                # 静音状态使用音量静音图标
                icon_path = os.path.join(icon_dir, '音量静音.svg')
            else:
                # 非静音状态使用普通音量图标
                icon_path = os.path.join(icon_dir, '音量.svg')
            
            # 渲染SVG图标为QPixmap
            from src.utils.svg_renderer import SvgRenderer
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, fixed_icon_size)
            
            # 设置按钮图标
            self.volume_button.setIcon(QIcon(pixmap))
            self.volume_button.setIconSize(QSize(fixed_icon_size, fixed_icon_size))
        except Exception as e:
            print(f"更新音量图标时出错: {e}")
    
    def toggle_mute(self):
        """
        一键静音/恢复音量
        """
        try:
            if self.player_core:
                if self._is_muted:
                    # 当前是静音状态，恢复之前的音量
                    self._is_muted = False
                    # 恢复音量值
                    volume = self._previous_volume
                    # 先设置播放器音量，再更新滑块，避免触发不必要的信号
                    self.player_core.set_volume(volume)
                    # 断开信号连接，避免触发set_volume导致_previous_volume被修改
                    self.volume_slider.valueChanged.disconnect(self.set_volume)
                    # 更新音量滑块
                    self.volume_slider.setValue(volume)
                    # 重新连接信号
                    self.volume_slider.valueChanged.connect(self.set_volume)
                else:
                    # 当前不是静音状态，保存当前音量并静音
                    # 1. 保存当前音量
                    current_volume = self.volume_slider.value()
                    # 2. 设置静音状态
                    self._is_muted = True
                    # 3. 保存当前音量到_previous_volume
                    self._previous_volume = current_volume
                    # 4. 先设置播放器音量为0
                    self.player_core.set_volume(0)
                    # 5. 断开信号连接，避免触发set_volume导致_previous_volume被修改
                    self.volume_slider.valueChanged.disconnect(self.set_volume)
                    # 6. 更新音量滑块为0
                    self.volume_slider.setValue(0)
                    # 7. 重新连接信号
                    self.volume_slider.valueChanged.connect(self.set_volume)
                
                # 更新音量图标
                self.update_volume_icon()
        except Exception as e:
            print(f"切换静音状态时出错: {e}")
    
    def seek(self, value):
        """
        跳转到指定位置
        
        Args:
            value (int): 位置值（0-1000）
        """
        try:
            if self.player_core and self.player_core.duration > 0:
                position = value / 1000.0
                self.player_core.set_position(position)
        except Exception as e:
            print(f"跳转位置时出错: {e}")
    
    def set_file(self, file_path):
        """
        设置要播放的媒体文件（视频或音频）
        
        Args:
            file_path (str): 文件路径
        """
        self.load_media(file_path)
    
    def set_loop(self, loop):
        """
        设置是否循环播放
        
        Args:
            loop (bool): 是否循环播放
        """
        try:
            if self.player_core:
                self.player_core.set_loop(loop)
        except Exception as e:
            print(f"设置循环播放时出错: {e}")
    
    def update_play_button(self):
        """
        更新播放按钮图标
        """
        # 保持兼容，实际由_update_play_button_icon处理
        self._update_play_button_icon()
    
    def _update_mouse_hover_state(self, is_hovered):
        """
        更新鼠标悬停状态并更新按钮图标
        
        Args:
            is_hovered: 是否有鼠标悬停在按钮上
        """
        self._is_mouse_over_play_button = is_hovered
        self._update_play_button_icon()
    
    def _update_play_button_icon(self):
        """
        根据播放状态和鼠标悬停状态更新播放按钮的SVG图标
        使用固定的图标大小，避免在布局过程中频繁计算和更新图标，防止窗口大小闪烁
        """
        icon_path = "src/Icon/"
        
        # 使用固定的图标大小，不依赖于按钮的实际大小
        # 根据按钮的最小高度(40px)的比例计算得出
        fixed_icon_size = 68  # 调整图标大小，默认为24px (40px * 0.6 = 24px)
        
        # 根据播放状态和鼠标悬停状态选择不同的SVG图标
        if self.player_core and self.player_core.is_playing:
            if self._is_mouse_over_play_button:
                pixmap = SvgRenderer.render_svg_to_pixmap(icon_path + "暂停时-按下.svg", fixed_icon_size)
            else:
                pixmap = SvgRenderer.render_svg_to_pixmap(icon_path + "暂停时.svg", fixed_icon_size)
        else:
            if self._is_mouse_over_play_button:
                pixmap = SvgRenderer.render_svg_to_pixmap(icon_path + "播放时-按下.svg", fixed_icon_size)
            else:
                pixmap = SvgRenderer.render_svg_to_pixmap(icon_path + "播放时.svg", fixed_icon_size)
        
        # 设置固定的图标大小，确保在任何情况下都不会改变
        self.play_button.setIcon(QIcon(pixmap))
        self.play_button.setIconSize(QSize(fixed_icon_size, fixed_icon_size))
    
    def pause_progress_update(self):
        """
        暂停进度更新（拖动进度条时）
        """
        self._user_interacting = True
    
    def resume_progress_update(self):
        """
        恢复进度更新（释放进度条时）
        """
        self._user_interacting = False
    
    def _handle_user_seek(self):
        """
        处理用户结束交互时的seek操作
        """
        # 跳转到指定位置
        value = self.progress_slider.value()
        self.seek(value)
    
    def update_progress(self):
        """
        更新播放进度
        """
        try:
            if self.player_core and self.player_core.duration > 0:
                # 更新时间标签
                current_time = self.format_time(self.player_core.time)
                total_time = self.format_time(self.player_core.duration)
                self.time_label.setText(f"{current_time} / {total_time}")
                
                # 更新进度条
                if not self._user_interacting:
                    position = int(self.player_core.position * 1000)
                    self.progress_slider.setValue(position)
                
                # 检测视频是否播放完成，如果是且启用了循环播放，则重新播放
                if (self.player_core.position >= 0.99 and not self.player_core.is_playing):
                    # 重新设置媒体并播放
                    try:
                        # 重置进度条
                        self.progress_slider.setValue(0)
                        # 重新播放当前视频
                        self.player_core.stop()
                        if self.player_core.play():
                            print(f"视频已重新开始循环播放")
                    except Exception as e:
                        print(f"循环播放失败: {e}")
        except Exception as e:
            print(f"更新进度时出错: {e}")
    
    def format_time(self, milliseconds):
        """
        格式化时间（毫秒 -> mm:ss）
        
        Args:
            milliseconds (int): 毫秒值
        
        Returns:
            str: 格式化后的时间字符串
        """
        try:
            seconds = int(milliseconds / 1000)
            minutes = seconds // 60
            seconds %= 60
            return f"{minutes:02d}:{seconds:02d}"
        except Exception as e:
            print(f"格式化时间时出错: {e}")
            return "00:00"
    
    def closeEvent(self, event):
        """
        窗口关闭事件处理
        """
        try:
            # 停止播放
            if self.player_core:
                self.player_core.cleanup()
            if self.timer:
                self.timer.stop()
            event.accept()
        except Exception as e:
            print(f"关闭窗口时出错: {e}")
            event.accept()


# 如果直接运行此文件，则启动视频播放器
if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec_())