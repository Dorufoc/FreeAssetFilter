#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

基于ffmpeg的视频播放器组件
提供完整的视频播放功能和用户界面
"""

import sys
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel,
    QFileDialog, QStyle, QMessageBox, QGraphicsBlurEffect, QMenu, QWidgetAction
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect, QSize
from PyQt5.QtGui import QIcon, QPainter, QColor, QPen, QBrush, QPixmap, QImage

from freeassetfilter.core.ffplayer_core import FFPlayerCore
from freeassetfilter.core.video_frame_renderer import VideoFrameRenderer
from freeassetfilter.utils.svg_renderer import SvgRenderer

# 复用VLC播放器的自定义组件
from freeassetfilter.components.video_player import CustomProgressBar, CustomVolumeBar, CustomValueBar


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
        
        # 设置样式
        self.setStyleSheet("background-color: transparent;")
    
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
            self.valueChanged.emit(value)
    
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
        
        painter.setBrush(QBrush(self._progress_color))
        painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        
        # 绘制滑块
        handle_x = self._handle_radius + progress_width
        # 确保滑块不会超出进度条范围
        handle_x = min(handle_x, self.width() - self._handle_radius * 2)
        handle_y = (rect.height() - self._handle_radius * 2) // 2
        
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
        # 设置最小尺寸为滑块直径加上一定余量，确保滑块始终可见
        min_width = self._handle_radius * 3  # 滑块直径 + 两侧余量
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
        
        # 绘制已音量部分 - 使用纯色填充
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
        
        # 绘制滑块
        handle_x = self._handle_radius + progress_width
        # 确保滑块不会超出音量条范围，考虑实际窗口宽度
        max_handle_x = max(self._handle_radius, self.width() - self._handle_radius * 2)
        handle_x = min(handle_x, max_handle_x)
        # 确保滑块不会小于最小值
        handle_x = max(handle_x, self._handle_radius)
        handle_y = (rect.height() - self._handle_radius * 2) // 2
        
        # 备用方案：绘制圆形滑块
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


class FFVideoPlayer(QWidget):
    """
    基于ffmpeg的视频播放器组件
    提供完整的视频播放功能和用户界面
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
        self.video_renderer = None
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
        self.setWindowTitle("FFVideo Player")
        self.setMinimumSize(400, 300)
        
        # 初始化所有属性
        self.init_attributes()
        
        # 创建UI组件
        self.init_ui()
        
        # 初始化播放器核心
        self.player_core = FFPlayerCore()
        
        # 连接信号
        self._connect_signals()
    
    def init_attributes(self):
        """
        初始化所有属性，确保在使用前都被定义
        """
        # 媒体显示区域
        self.media_frame = QWidget()
        self.video_frame = QWidget()
        self.video_renderer = None
        self.audio_stacked_widget = QWidget()
        self.background_label = QLabel()
        self.overlay_widget = QWidget()
        self.cover_label = QLabel()
        self.audio_info_label = QLabel()
        self.audio_container = QWidget()
        
        # 控制组件
        self.progress_slider = CustomProgressBar()  # 视频进度条使用可交互进度条
        self.time_label = QLabel("00:00 / 00:00")
        self.play_button = QPushButton()
        self.volume_slider = CustomVolumeBar()  # 音量控制条
        self.volume_button = QPushButton()  # 音量图标按钮
        
        # 倍速控制组件
        self.speed_button = QPushButton("1.0x")
        self.speed_menu = None  # 将在init_ui中初始化
        self.speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
        self.is_speed_menu_visible = False
        self.speed_menu_timer = None  # 菜单关闭定时器
        
        # 音量菜单组件
        self.volume_menu = None  # 音量菜单
        self.is_volume_menu_visible = False
        self.volume_menu_timer = None  # 音量菜单关闭定时器
        
        # LUT控制组件
        self.lut_button = QPushButton("LUT")
        self.lut_menu = None  # LUT菜单
        self.is_lut_menu_visible = False
        self.lut_menu_timer = None  # LUT菜单关闭定时器
        self.current_lut = None
        
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
        self.media_frame.setStyleSheet("background-color: black;")
        self.media_frame.setMinimumSize(400, 300)
        
        # 视频显示区域设置
        self.video_frame.setStyleSheet("background-color: transparent;")
        self.video_frame.setMinimumSize(400, 300)
        
        # 创建视频渲染组件
        self.video_renderer = VideoFrameRenderer()
        
        # 视频显示区域布局
        video_layout = QVBoxLayout(self.video_frame)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)
        video_layout.addWidget(self.video_renderer)
        
        # 音频显示区域设置
        audio_layout = QVBoxLayout(self.audio_stacked_widget)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(0)
        
        # 音频背景设置
        self.background_label.setStyleSheet("background-color: #1a1a1a;")
        self.background_label.setScaledContents(True)
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setMinimumSize(400, 300)
        
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
        
        # 控制按钮区域
        control_container = QWidget()
        control_container.setStyleSheet("background-color: #FFFFFF; border: 1px solid #FFFFFF; border-radius: 35px 35px 35px 35px;")
        self.control_layout = QHBoxLayout(control_container)
        self.control_layout.setContentsMargins(15, 15, 15, 15)
        self.control_layout.setSpacing(15)
        
        # 初始化鼠标悬停状态变量
        self._is_mouse_over_play_button = False
        
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
        
        # 设置播放按钮SVG图标
        self._update_play_button_icon()
        self.play_button.clicked.connect(self.toggle_play_pause)
        # 连接鼠标事件
        self.play_button.enterEvent = lambda event: self._update_mouse_hover_state(True)
        self.play_button.leaveEvent = lambda event: self._update_mouse_hover_state(False)
        self.control_layout.addWidget(self.play_button)
        
        # 进度条和时间标签
        # 创建一个垂直布局容器，用于放置进度条、时间标签和音量控件
        progress_time_container = QWidget()
        progress_time_container.setStyleSheet("background-color: #FFFFFF; border: 1px solid #FFFFFF;")
        progress_time_layout = QVBoxLayout(progress_time_container)
        progress_time_layout.setContentsMargins(0, 0, 0, 0)
        progress_time_layout.setSpacing(2)
        
        # 自定义进度条设置
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        # 连接进度条信号
        self.progress_slider.userInteractionEnded.connect(self._handle_user_seek)
        self.progress_slider.userInteracting.connect(self.pause_progress_update)
        self.progress_slider.userInteractionEnded.connect(self.resume_progress_update)
        progress_time_layout.addWidget(self.progress_slider)
        
        # 创建一个水平布局来放置时间标签和音量控制
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        
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
        bottom_layout.addWidget(self.time_label)
        
        # 添加伸缩项
        bottom_layout.addStretch(1)
        
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
        bottom_layout.addWidget(self.volume_button)
        # 初始化音量图标
        self.update_volume_icon()
        
        # 音量按钮悬停显示音量菜单
        self.volume_button.enterEvent = self.show_volume_menu
        self.volume_button.leaveEvent = lambda event: self._handle_volume_button_leave(event)
        
        # 加载保存的音量设置
        saved_volume = self.load_volume_setting()
        # 设置初始音量
        if self.player_core:
            self.player_core.set_volume(saved_volume)
        # 保存当前音量作为静音前的初始音量
        self._previous_volume = saved_volume
        
        # 初始化音量菜单
        self._init_volume_menu(saved_volume)
        
        # 添加倍速控制按钮
        self.speed_button.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #FFFFFF;
                padding: 5px 10px;
                border-radius: 5px;
                min-width: 60px;
                max-width: 60px;
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
        bottom_layout.addWidget(self.speed_button)
        
        # 添加LUT控制按钮
        self.lut_button.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #000000;
                border: 1px solid #FFFFFF;
                padding: 5px 10px;
                border-radius: 5px;
                min-width: 40px;
                max-width: 40px;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
        """)
        # 添加点击事件，实现LUT加载
        self.lut_button.clicked.connect(self.load_lut_file)
        bottom_layout.addWidget(self.lut_button)
        
        # 将水平布局添加到垂直布局中
        progress_time_layout.addLayout(bottom_layout)
        
        # 将包含进度条和时间/音量控件的容器添加到控制布局中
        self.control_layout.addWidget(progress_time_container, 1)
        
        main_layout.addWidget(control_container)
        
        # 创建倍速菜单
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
        
        # 设置主窗口样式
        self.setStyleSheet("""
            background-color: #1a1a1a;
            border-radius: 20px;
        """)
    
    def _connect_signals(self):
        """
        连接信号
        """
        # 连接播放器核心信号
        self.player_core.play_state_changed.connect(self._on_play_state_changed)
        self.player_core.time_updated.connect(self._on_time_updated)
        self.player_core.position_changed.connect(self._on_position_changed)
        self.player_core.frame_available.connect(self.video_renderer.render_frame)
        
        # 连接音量滑块信号
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
    
    def _on_play_state_changed(self, is_playing):
        """
        播放状态变化回调
        
        Args:
            is_playing (bool): 是否正在播放
        """
        self._update_play_button_icon()
    
    def _on_time_updated(self, current_time, duration):
        """
        时间更新回调
        
        Args:
            current_time (int): 当前播放时间，毫秒
            duration (int): 总时长，毫秒
        """
        # 更新时间标签
        current_str = self._format_time(current_time)
        duration_str = self._format_time(duration)
        self.time_label.setText(f"{current_str} / {duration_str}")
    
    def _on_position_changed(self, position):
        """
        播放位置变化回调
        
        Args:
            position (float): 播放位置，范围 0.0-1.0
        """
        if not self._user_interacting:
            # 更新进度条
            self.progress_slider.setValue(int(position * 1000))
    
    def _on_volume_changed(self, volume):
        """
        音量变化回调
        
        Args:
            volume (int): 音量值，范围 0-100
        """
        if self.player_core:
            self.player_core.set_volume(volume)
    
    def _format_time(self, milliseconds):
        """
        格式化时间
        
        Args:
            milliseconds (int): 毫秒数
            
        Returns:
            str: 格式化后的时间字符串，格式为 HH:MM:SS 或 MM:SS
        """
        seconds = milliseconds // 1000
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    
    def toggle_play_pause(self):
        """
        切换播放/暂停状态
        """
        if not self.player_core:
            return
        
        if self.player_core.is_playing:
            self.player_core.pause()
        else:
            self.player_core.play()
        self._update_play_button_icon()
    
    def _update_play_button_icon(self):
        """
        根据播放状态和鼠标悬停状态更新播放按钮的SVG图标
        使用固定的图标大小，避免在布局过程中频繁计算和更新图标，防止窗口大小闪烁
        复用VLC播放器的图标路径和文件名，确保视觉表现一致
        """
        # 获取正确的图标路径
        import os
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        
        # 使用固定的图标大小，不依赖于按钮的实际大小
        # 根据按钮的最小高度(40px)的比例计算得出
        fixed_icon_size = 68  # 调整图标大小，默认为24px (40px * 0.6 = 24px)
        
        # 根据播放状态和鼠标悬停状态选择不同的SVG图标
        # 复用VLC播放器的图标文件名，确保视觉表现一致
        if self.player_core and self.player_core.is_playing:
            if self._is_mouse_over_play_button:
                icon_path = os.path.join(icon_dir, "暂停时-按下.svg")
            else:
                icon_path = os.path.join(icon_dir, "暂停时.svg")
        else:
            if self._is_mouse_over_play_button:
                icon_path = os.path.join(icon_dir, "播放时-按下.svg")
            else:
                icon_path = os.path.join(icon_dir, "播放时.svg")
        
        # 渲染SVG图标
        pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, fixed_icon_size)
        
        # 设置固定的图标大小，确保在任何情况下都不会改变
        self.play_button.setIcon(QIcon(pixmap))
        self.play_button.setIconSize(QSize(fixed_icon_size, fixed_icon_size))
    
    def _update_mouse_hover_state(self, is_hovering):
        """
        更新鼠标悬停状态并刷新图标
        
        Args:
            is_hovering (bool): 是否悬停在播放按钮上
        """
        self._is_mouse_over_play_button = is_hovering
        self._update_play_button_icon()
    
    def load_media(self, file_path):
        """
        加载媒体文件
        
        Args:
            file_path (str): 媒体文件路径
        """
        # 停止当前播放并重置状态
        self.player_core.stop()
        
        # 重置UI状态
        self.progress_slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.play_button.setText("▶")
        
        if self.player_core.load_media(file_path):
            # 更新音频信息
            self.audio_info_label.setText(os.path.basename(file_path))
            
            # 自动开始播放
            self.player_core.play()
            
            return True
        return False
    
    def stop(self):
        """
        停止播放
        """
        if self.player_core:
            self.player_core.stop()
    
    def _handle_user_seek(self):
        """
        处理用户拖动进度条事件
        """
        if self.player_core:
            position = self.progress_slider.value() / 1000.0
            self.player_core.set_position(position)
        self._user_interacting = False
    
    def pause_progress_update(self):
        """
        暂停进度更新
        """
        self._user_interacting = True
    
    def resume_progress_update(self):
        """
        恢复进度更新
        """
        self._handle_user_seek()
    
    def show_speed_menu(self, event=None):
        """
        显示倍速菜单
        
        Args:
            event: PyQt事件对象，可选
        """
        # 获取倍速按钮的位置
        button_pos = self.speed_button.mapToGlobal(self.speed_button.rect().topLeft())
        
        # 显示菜单
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
        self.speed_menu.close()
        self.is_speed_menu_visible = False
    
    def _handle_speed_button_leave(self, event):
        """
        处理倍速按钮的鼠标离开事件
        """
        self.hide_speed_menu()
    
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
        
        # 隐藏菜单
        self.is_speed_menu_visible = False
    
    def toggle_mute(self):
        """
        切换静音状态
        """
        if not self.player_core:
            return
        
        self._is_muted = not self._is_muted
        if self._is_muted:
            # 保存当前音量
            self._previous_volume = self.player_core.volume
            # 设置音量为0
            self.player_core.set_volume(0)
        else:
            # 恢复之前的音量
            self.player_core.set_volume(self._previous_volume)
        
        # 更新音量图标
        self.update_volume_icon()
    
    def update_volume_icon(self):
        """
        根据音量状态更新音量图标
        """
        try:
            # 图标路径
            icon_dir = os.path.join(os.path.dirname(__file__), '..', 'icons')
            
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
            from freeassetfilter.utils.svg_renderer import SvgRenderer
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, fixed_icon_size)
            
            # 设置按钮图标
            self.volume_button.setIcon(QIcon(pixmap))
            self.volume_button.setIconSize(QSize(fixed_icon_size, fixed_icon_size))
        except Exception as e:
            print(f"更新音量图标时出错: {e}")
    
    def show_volume_menu(self, event=None):
        """
        显示音量调节菜单
        
        Args:
            event (QEvent, optional): 鼠标事件对象，由PyQt自动传递
        """
        # 检查音量菜单是否已初始化
        if not hasattr(self, 'volume_menu'):
            saved_volume = self.load_volume_setting()
            self._init_volume_menu(saved_volume)
        
        # 计算菜单位置（音量按钮下方居中）
        button_pos = self.volume_button.mapToGlobal(self.volume_button.rect().center())
        menu_width = self.volume_menu.sizeHint().width()
        menu_height = self.volume_menu.sizeHint().height()
        
        # 菜单位置：音量按钮下方，水平居中对齐
        menu_pos = QPoint(button_pos.x() - menu_width // 2, button_pos.y() + 10)
        
        # 显示菜单
        self.volume_menu.popup(menu_pos)
        self.is_volume_menu_visible = True
    
    def _handle_volume_button_leave(self, event):
        """
        处理音量按钮鼠标离开事件
        """
        # 检查鼠标是否移动到了音量菜单上
        if hasattr(self, 'volume_menu') and self.is_volume_menu_visible:
            menu_pos = self.volume_menu.mapToGlobal(QPoint(0, 0))
            menu_rect = QRect(menu_pos, self.volume_menu.sizeHint())
            
            if not menu_rect.contains(QCursor.pos()):
                self.is_volume_menu_visible = False
    
    def _init_volume_menu(self, initial_volume):
        """
        初始化音量调节菜单
        
        Args:
            initial_volume (int): 初始音量值
        """
        # 创建音量菜单
        self.volume_menu = QMenu(self)
        self.is_volume_menu_visible = False
        
        # 创建音量菜单的自定义控件
        volume_control_widget = QWidget()
        main_layout = QVBoxLayout(volume_control_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        main_layout.setAlignment(Qt.AlignCenter)
        
        # 添加音量值显示标签
        volume_label = QLabel()
        volume_label.setText(f"{initial_volume}%")
        volume_label.setAlignment(Qt.AlignCenter)
        volume_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-size: 16px;
                font-weight: bold;
                color: #000000;
                background-color: transparent;
                border: none;
            }
        """)
        # 固定标签宽度，防止文本变化导致布局抖动
        volume_label.setFixedWidth(50)
        main_layout.addWidget(volume_label)
        
        # 创建音量滑块区域
        slider_container = QWidget()
        slider_container.setStyleSheet("background-color: transparent;")
        slider_layout = QHBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setAlignment(Qt.AlignCenter)
        
        # 创建竖向自定义数值条作为音量滑块
        from freeassetfilter.components.video_player import CustomValueBar
        self.volume_menu_slider = CustomValueBar(orientation=CustomValueBar.Vertical)
        self.volume_menu_slider.setRange(0, 100)
        self.volume_menu_slider.setValue(initial_volume)
        self.volume_menu_slider.setFixedSize(28, 160)
        # 连接滑块信号
        self.volume_menu_slider.valueChanged.connect(self._on_volume_slider_changed)
        
        slider_layout.addWidget(self.volume_menu_slider)
        main_layout.addWidget(slider_container)
        
        # 保存标签引用
        self.volume_menu_label = volume_label
        
        # 使用QWidgetAction将自定义控件添加到菜单
        volume_action = QWidgetAction(self.volume_menu)
        volume_action.setDefaultWidget(volume_control_widget)
        self.volume_menu.addAction(volume_action)
        
        # 为菜单添加事件过滤器，用于监听enter和leave事件
        self.volume_menu.installEventFilter(self)
    
    def _on_volume_slider_changed(self, value=None):
        """
        处理音量滑块变化事件
        
        Args:
            value (int, optional): 音量值
        """
        if value is None:
            value = self.volume_menu_slider.value()
        
        # 更新音量设置
        if self.player_core:
            self.player_core.set_volume(value)
        
        # 如果当前不是静音状态，保存当前音量作为静音前的音量
        if not self._is_muted:
            self._previous_volume = value
        
        # 更新音量图标
        self.update_volume_icon()
        
        # 更新音量标签
        if hasattr(self, 'volume_menu_label') and self.volume_menu_label:
            self.volume_menu_label.setText(f"{value}%")
        
        # 保存音量设置
        self.save_volume_setting(value)
    
    def load_volume_setting(self):
        """
        从配置文件加载音量设置
        
        Returns:
            int: 保存的音量值，默认为50
        """
        try:
            # 尝试从配置文件加载音量设置
            config_dir = os.path.expanduser("~/.freeassetfilter")
            config_file = os.path.join(config_dir, "player_config.json")
            
            if os.path.exists(config_file):
                import json
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get("volume", 50)
        except Exception:
            pass
        
        # 默认音量为50
        return 50
    
    def save_volume_setting(self, volume):
        """
        将音量设置保存到配置文件
        
        Args:
            volume (int): 音量值
        """
        try:
            # 确保配置目录存在
            config_dir = os.path.expanduser("~/.freeassetfilter")
            os.makedirs(config_dir, exist_ok=True)
            
            # 保存音量设置
            config_file = os.path.join(config_dir, "player_config.json")
            import json
            
            # 读取现有配置
            config = {}
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            # 更新音量设置
            config["volume"] = volume
            
            # 保存配置
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception:
            pass
    
    def load_lut_file(self):
        """
        加载LUT文件
        """
        # 打开文件选择对话框
        lut_path, _ = QFileDialog.getOpenFileName(
            self, "选择LUT文件", "/", "LUT Files (*.cube)"
        )
        
        if lut_path:
            # 加载LUT文件
            if self.player_core.load_lut(lut_path):
                self.current_lut = lut_path
                QMessageBox.information(self, "成功", f"LUT文件加载成功: {os.path.basename(lut_path)}")
            else:
                QMessageBox.warning(self, "失败", f"LUT文件加载失败: {os.path.basename(lut_path)}")
    
    def _format_time(self, milliseconds):
        """
        格式化时间
        
        Args:
            milliseconds (int): 毫秒数
            
        Returns:
            str: 格式化后的时间字符串，格式为 MM:SS
        """
        seconds = milliseconds // 1000
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def closeEvent(self, event):
        """
        关闭事件
        """
        # 停止播放
        self.stop()
        event.accept()
