#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

独立的视频播放器组件
提供完整的视频和音频播放功能和用户界面
"""

import sys
import os
import shutil

# 添加项目根目录到Python路径，确保包能被正确导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QSlider, QLabel,
    QFileDialog, QStyle, QMessageBox, QGraphicsBlurEffect, QSizePolicy
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QRect, QSize, QPoint, QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation, QMetaObject
from PySide6.QtGui import QIcon, QPainter, QColor, QPen, QBrush, QPixmap, QImage, QCursor, QPainterPath
from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.widgets.D_widgets import CustomButton
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.mouse_activity_monitor import MouseActivityMonitor
from freeassetfilter.widgets.control_menu import CustomControlMenu
from freeassetfilter.widgets.D_volume_control import DVolumeControl
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu
from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.widgets.audio_background import AudioBackground
from freeassetfilter.widgets.scrolling_text import ScrollingText
from freeassetfilter.core.color_extractor import extract_cover_colors

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

from freeassetfilter.core.mpv_player_core import MPVPlayerCore


class VideoPlayer(QWidget):
    """
    通用媒体播放器组件
    提供完整的视频和音频播放功能和用户界面
    """
    
    # 添加idle事件信号，用于异常检测
    idle_event = Signal()
    
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
        self.audio_background = None
        self._user_interacting = False
        
        # 获取应用实例和DPI缩放因子
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        # 获取全局默认字体大小和字体
        self.default_font_size = getattr(app, 'default_font_size', 10)
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 设置焦点策略，确保组件能够接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
        
        # 作为子组件，不设置窗口标题和最小尺寸，而是由父容器控制
        # 移除窗口属性，避免作为独立窗口弹出
        self.setStyleSheet("background-color: transparent;")
        
        # 初始化所有属性
        self.init_attributes()
        
        # 初始化播放器核心 - 默认使用MPV内核
        # print("[VideoPlayer] 初始化MPV播放器核心...")
        self.player_core = MPVPlayerCore()
        
        # 设置idle事件回调，用于异常检测
        self.player_core.set_on_idle_callback(self._on_idle_event)
        
        # 检查MPV内核是否初始化成功
        if not hasattr(self.player_core, '_mpv') or self.player_core._mpv is None:
            print("[VideoPlayer] 警告: MPV内核初始化失败，将使用简化模式")
            pass
        else:
            # print("[VideoPlayer] MPV内核初始化成功")
            pass
        
        # 创建UI组件
        self.init_ui()
        
        # 将MPV播放器绑定到video_frame窗口
        if self.video_frame:
            # print("[VideoPlayer] 绑定MPV播放器到video_frame窗口...")
            self.player_core.set_window(self.video_frame.winId())
        
        # 创建定时器用于更新进度
        self.timer = QTimer(self)
        self.timer.setInterval(100)  # 100ms更新一次，确保进度显示延迟不超过200ms
        self.timer.timeout.connect(self.update_progress)
        
        # 连接内核信号到适配层
        self._connect_core_signals()
        
        # 初始化定时器
        self.timer.start()
        
        # 应用保存的倍速设置到播放器核心
        self.set_speed(self._current_speed)
        
        # 延迟检查是否有LUT文件需要应用，避免启动过慢
        QTimer.singleShot(100, self.check_and_apply_lut_file)
    
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
        self.audio_info_label = QLabel()
        self.audio_container = QWidget()
        self.song_name_label = QLabel()
        self.artist_name_label = QLabel()
        self.cover_label = QLabel()  # 歌曲封面显示标签
        self.audio_icon_widget = None  # 音频图标SVG widget
        self.audio_icon_container = None  # 音频图标容器，用于居中显示
        self.audio_cover_label = None  # 音频封面图片标签
        self.audio_file_label = None  # 音频文件名标签（已废弃，使用scrolling_text替代）
        self.audio_file_scroll_area = None  # 文件名滚动区域（外层容器）
        self.audio_file_scroll_offset = 0  # 文件名滚动偏移量
        self.audio_file_needs_scroll = False  # 是否需要滚动
        self.audio_file_animation = None  # 文件名滚动动画
        self.scrolling_text = None  # 滚动文本控件（替代audio_file_label）
        self._audio_cover_data = None  # 音频文件封面数据
        
        # 控制组件
        self.progress_slider = D_ProgressBar(is_interactive=False)
        self.time_label = QLabel("00:00 / 00:00")
        self.play_button = None
        
        # 倍速控制组件
        self.speed_dropdown = None  # 将在init_ui中使用CustomDropdownMenu初始化
        self.speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
        self.is_speed_menu_visible = False
        self.speed_menu_timer = None  # 菜单关闭定时器
        
        # 使用自定义音量条浮动菜单
        self.volume_control = None  # 自定义音量控制组件
        
        # 状态标志
        self._user_interacting = False
        self.player_core = None
        self.timer = None
        
        # 播放器内核相关属性 - 仅使用MPV
        self._current_player = 'mpv'  # 固定使用MPV内核
        self._player_engines = {
            'mpv': MPVPlayerCore
        }
        self._current_file_path = ""  # 当前播放的文件路径

        # 使用SettingsManager获取音量和倍速设置
        settings_manager = SettingsManager()
        self._current_volume = settings_manager.get_player_volume()  # 当前音量
        self._current_speed = settings_manager.get_player_speed()  # 当前播放速度

        # 音量控制相关属性
        self._is_muted = False  # 静音状态
        self._previous_volume = self._current_volume  # 静音前的音量值
        
        # Cube色彩映射相关属性
        self.cube_path = None  # 当前加载的Cube文件路径
        self.cube_path_label = None  # 显示Cube文件路径的标签
        self.cube_loaded = False  # Cube文件是否已加载
        self.load_cube_button = None  # 加载Cube文件的按钮
        self.comparison_mode = False  # 是否启用对比预览模式
        self.comparison_button = None  # 对比预览模式切换按钮
        self.filtered_player_core = None  # 用于应用滤镜的播放器核心
        self.comparison_layout = None  # 对比预览布局
        self.original_video_frame = None  # 原视频显示区域
        self.filtered_video_frame = None  # 应用滤镜后的视频显示区域

        # 窗口分离相关属性
        self._detached_window = None  # 分离的独立窗口
        self._is_detached = False  # 是否处于分离状态
        self._detached_button = None  # 分离窗口按钮
        self._parent_container = None  # 原始父容器引用
        self._original_layout = None  # 原始布局引用
        self._saved_position = 0  # 分离前保存的播放位置
        self._saved_playing_state = False  # 分离前保存的播放状态
        self._maxsize_icon_path = None  # maxsize图标路径
        self._minisize_icon_path = None  # minisize图标路径

        # 内核适配层相关 - 仅使用MPV
        self._core_signal_adapters = {
            'mpv': self._connect_mpv_signals
        }

        # 视频渲染相关
        self._video_renderer = None
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 媒体显示区域设置
        self.media_frame.setStyleSheet("background-color: transparent;")
        self.media_frame.setMinimumSize(200, 200)
        
        # 视频显示区域设置 - MPV将直接渲染到这个窗口
        self.video_frame.setStyleSheet("background-color: transparent;")
        self.video_frame.setMinimumSize(200, 200)
        
        # 设置视频显示区域的布局
        video_layout = QVBoxLayout(self.video_frame)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(0)
        
        # 音频显示区域设置 - 使用QGridLayout实现叠加效果
        self.audio_stacked_widget.setStyleSheet("background-color: transparent;")
        audio_layout = QGridLayout(self.audio_stacked_widget)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.setSpacing(0)
        
        # 音频背景设置 - 移除背景色和模糊效果，避免边框视觉
        self.background_label.setStyleSheet("background-color: transparent;")
        self.background_label.setScaledContents(True)
        self.background_label.setAlignment(Qt.AlignCenter)
        self.background_label.setMinimumSize(200, 200)
        
        # 背景遮罩 - 设置为完全透明，移除边框效果
        self.overlay_widget.setStyleSheet("background-color: transparent;")
        
        # 从app对象获取全局默认字体大小
        app = QApplication.instance()
        default_font_size = getattr(app, 'default_font_size', 10)
        
        # 歌曲名称标签
        self.song_name_label = QLabel("歌曲名")
        # 应用DPI缩放因子到字体大小
        scaled_song_font_size = int(default_font_size * 1.2 * self.dpi_scale)  # 1.2倍于默认大小
        self.song_name_label.setFont(self.global_font)
        self.song_name_label.setStyleSheet(f"""
            color: white;
            font-size: {scaled_song_font_size}px;
            font-weight: 600;
            background-color: transparent;
            padding: 5px 0;
        """)
        self.song_name_label.setAlignment(Qt.AlignCenter)
        self.song_name_label.setWordWrap(True)
        self.song_name_label.setMaximumWidth(350)  # 设置最大宽度限制，确保在容器内正确换行
        
        # 作者名称标签
        self.artist_name_label = QLabel("作者名")
        # 应用DPI缩放因子到字体大小
        scaled_artist_font_size = int(default_font_size * 0.9 * self.dpi_scale)  # 0.9倍于默认大小
        self.artist_name_label.setFont(self.global_font)
        self.artist_name_label.setStyleSheet(f"""
            color: white;
            font-size: {scaled_artist_font_size}px;
            font-weight: 400;
            background-color: transparent;
            padding: 5px 0;
        """)
        self.artist_name_label.setAlignment(Qt.AlignCenter)
        self.artist_name_label.setWordWrap(True)
        self.artist_name_label.setMaximumWidth(350)  # 设置最大宽度限制，确保在容器内正确换行
        
        # 音频显示容器
        audio_container_layout = QVBoxLayout(self.audio_container)
        audio_container_layout.setContentsMargins(0, 0, 0, 0)
        audio_container_layout.setSpacing(7)
        audio_container_layout.setAlignment(Qt.AlignCenter)
        
        # 歌曲封面设置
        # 计算缩放后的封面大小（100dpx正方形）
        scaled_cover_size = int(50 * self.dpi_scale)
        self.cover_label.setFixedSize(scaled_cover_size, scaled_cover_size)
        self.cover_label.setAlignment(Qt.AlignCenter)
        # 设置封面的圆角矩形遮罩，使用透明背景
        self.cover_label.setStyleSheet(f"""
            background-color: transparent;
            border-radius: {int(scaled_cover_size * 0.1)}px;
        """)
        
        # 添加歌曲信息到容器（封面在最上面）
        audio_container_layout.addWidget(self.cover_label)
        audio_container_layout.addWidget(self.song_name_label)
        audio_container_layout.addWidget(self.artist_name_label)
        
        # 设置音频容器样式
        self.audio_container.setStyleSheet("background-color: transparent;")
        self.audio_container.setMinimumSize(150, 100)
        self.audio_container.setMaximumWidth(400)  # 设置最大宽度限制，防止布局错乱
        
        # 创建音频图标容器，用于居中显示SVG图标
        self.audio_icon_container = QWidget()
        self.audio_icon_container.setStyleSheet("background-color: transparent;")
        self.audio_icon_container.setMinimumSize(150, 100)
        icon_container_layout = QVBoxLayout(self.audio_icon_container)
        icon_container_layout.setContentsMargins(0, 0, 0, 0)
        icon_container_layout.setSpacing(int(5 * self.dpi_scale))
        icon_container_layout.setAlignment(Qt.AlignCenter)
        
        # 创建音频封面图片标签（与SVG图标大小一致）
        self.audio_cover_label = QLabel()
        self.audio_cover_label.setAlignment(Qt.AlignCenter)
        self.audio_cover_label.setStyleSheet("background-color: transparent; border: none;")
        self.audio_cover_label.hide()
        icon_container_layout.addWidget(self.audio_cover_label, 0, Qt.AlignCenter)
        
        # 创建音频文件名滚动区域（外层容器，用于裁切显示）
        # 完全填充可用横向区域，无边距限制
        self.audio_file_scroll_area = QWidget()
        self.audio_file_scroll_area.setStyleSheet("background-color: transparent;")
        self.audio_file_scroll_area.setMinimumSize(int(150 * self.dpi_scale), int(25 * self.dpi_scale))
        
        # 为滚动区域设置水平布局，完全填充
        scroll_area_layout = QHBoxLayout(self.audio_file_scroll_area)
        scroll_area_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area_layout.setSpacing(0)
        
        # 创建滚动文本控件替代QLabel，完全填充父容器宽度
        self.scrolling_text = ScrollingText(
            parent=self.audio_file_scroll_area,
            text="",
            width=0,  # 宽度为0表示完全填充父容器
            height=int(25 * self.dpi_scale),
            font_size=14,
            text_color="#FFFFFF",
            dpi_scale=self.dpi_scale,
            linear_animation=True,
            loop_mode=ScrollingText.LOOP_MODE_SINGLE
        )
        
        # 将滚动文本添加到布局中，完全填充
        scroll_area_layout.addWidget(self.scrolling_text)
        
        # 注意：audio_file_scroll_area 将在 _update_audio_icon 中按正确顺序添加
        # 以确保 SVG 图标在上，滚动文本在下
        
        # 创建音频背景组件（支持流体动画和封面模糊两种模式）
        self.audio_background = AudioBackground(self)
        self.audio_background.setStyleSheet("background-color: transparent; border: none;")
        self.audio_background.setMinimumSize(200, 200)
        
        # 构建音频叠加布局
        audio_layout.addWidget(self.audio_background, 0, 0)
        audio_layout.addWidget(self.background_label, 0, 0)
        audio_layout.addWidget(self.overlay_widget, 0, 0)
        audio_layout.addWidget(self.audio_container, 0, 0, Qt.AlignCenter)
        audio_layout.addWidget(self.audio_icon_container, 0, 0, Qt.AlignCenter)
        
        # 媒体布局
        media_layout = QVBoxLayout(self.media_frame)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(0)
        media_layout.addWidget(self.video_frame, 1)  # 设置拉伸因子为1，确保视频帧填充整个可用空间
        media_layout.addWidget(self.audio_stacked_widget, 1)  # 设置拉伸因子为1，确保音频界面也能填充整个可用空间
        
        # 音频界面默认隐藏
        self.audio_stacked_widget.hide()
        
        # 添加媒体区域到主布局
        main_layout.addWidget(self.media_frame, 1)

        # 使用独立的播放器控制栏组件（延迟导入避免循环导入）
        from freeassetfilter.widgets.player_control_bar import PlayerControlBar
        self.control_bar = PlayerControlBar(parent=self, show_lut_controls=True)
        self.control_bar.set_volume(self._current_volume)
        self.control_bar.set_speed(self._current_speed)

        # 根据设置控制全屏按钮的显示/隐藏
        self._update_detach_button_visibility()

        # 连接控制栏信号到播放器方法
        self.control_bar.playPauseClicked.connect(self.toggle_play_pause)
        self.control_bar.progressChanged.connect(self._handle_value_change)
        self.control_bar.userInteractStarted.connect(self._handle_user_start_interact)
        self.control_bar.userInteractEnded.connect(self._handle_user_end_interact)
        self.control_bar.volumeChanged.connect(self.set_volume)
        self.control_bar.muteChanged.connect(self._on_muted_changed)
        self.control_bar.speedChanged.connect(self._on_speed_changed_from_control_bar)
        self.control_bar.loadLutClicked.connect(self.load_cube_file)
        self.control_bar.comparisonClicked.connect(self.toggle_comparison_mode)
        self.control_bar.detachClicked.connect(self._toggle_detach_window)

        # 连接音量交互结束信号，用于保存音量设置
        self.control_bar.volume_control._d_volume._progress_bar.userInteractionEnded.connect(
            lambda: self.save_volume_setting(self._current_volume)
        )

        # 添加控制栏到主布局
        main_layout.addWidget(self.control_bar)

        # 保存控制栏引用到各个UI组件，保持向后兼容
        self.play_button = self.control_bar.play_button
        self.progress_slider = self.control_bar.progress_slider
        self.time_label = self.control_bar.time_label
        self.volume_control = self.control_bar.volume_control
        self.speed_button = self.control_bar.speed_button
        self.speed_dropdown = self.control_bar.speed_dropdown
        self.load_cube_button = self.control_bar.load_cube_button
        self.comparison_button = self.control_bar.comparison_button
        self._detached_button = self.control_bar.detach_button
    
    def toggle_speed_menu(self):
        """
        切换倍速菜单的显示/隐藏状态
        """
        if not hasattr(self, 'speed_menu') or self.speed_menu is None:
            self._init_speed_menu()
        else:
            self.show_speed_menu()
    
    def show_speed_menu(self, event=None):
        """
        显示倍速菜单
        """
        if not hasattr(self, 'speed_menu') or self.speed_menu is None:
            self._init_speed_menu()
        
        # 重新初始化菜单，确保选中状态正确
        self._init_speed_menu()
        
        # 显示菜单
        self.speed_menu.show()
        self.is_speed_menu_visible = True
    
    def hide_speed_menu(self):
        """
        隐藏倍速菜单
        """
        if hasattr(self, 'speed_menu') and self.speed_menu is not None:
            self.speed_menu.hide()
            self.is_speed_menu_visible = False
    
    def _on_speed_selected(self, speed):
        """
        处理倍速选择（来自下拉菜单）
        """
        # 将字符串类型的速度值转换为浮点数
        if isinstance(speed, str):
            speed = float(speed.replace('x', ''))

        # 设置播放速度
        self.set_speed(speed)

        # 更新倍速下拉菜单
        self.speed_dropdown.set_current_item(f"{speed}x")

        # 更新自定义按钮的文本
        self.speed_button.setText(f"{speed}x")

        # 保存倍速设置到 last_speed
        self.save_speed_setting(speed)

    def _on_speed_changed_from_control_bar(self, speed):
        """
        处理控制栏的倍速变化信号
        
        Args:
            speed: 播放速度值
        """
        # 设置播放速度
        self.set_speed(speed)
        # 保存倍速设置
        self.save_speed_setting(speed)
    
    def _update_play_button_icon(self):
        """
        更新播放/暂停按钮的SVG图标
        使用缓存机制避免频繁重新渲染相同的图标
        """
        try:
            # 获取图标路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_path = os.path.join(current_dir, '..', 'icons')
            icons_path = os.path.abspath(icons_path)
            
            # 根据播放状态选择不同图标
            if self.player_core and self.player_core.is_playing:
                icon_name = "暂停时.svg"
            else:
                icon_name = "播放时.svg"
            
            # 构建完整图标路径
            icon_path = os.path.join(icons_path, icon_name)
            
            # 检查文件是否存在
            if not os.path.exists(icon_path):
                print(f"[VideoPlayer] 图标文件不存在: {icon_path}")
                return
            
            # 缓存检查：如果图标路径没有变化，跳过重新渲染
            current_icon_attr = getattr(self.play_button, '_current_icon_path', None)
            if current_icon_attr == icon_path:
                # 图标没有变化，不需要重新渲染
                return
            
            # 更新CustomButton的图标
            self.play_button._icon_path = icon_path
            self.play_button._display_mode = "icon"
            self.play_button._current_icon_path = icon_path  # 记录当前图标路径
            self.play_button._render_icon()
            self.play_button.update()
        except Exception as e:
            print(f"[VideoPlayer] 更新播放按钮图标失败: {e}")
            import traceback
            traceback.print_exc()
    
    def toggle_play_pause(self):
        """
        切换播放状态（支持播放和暂停）
        """
        try:
            # 主播放器控制
            if self.player_core and hasattr(self.player_core, '_mpv') and self.player_core._mpv is not None:
                if not self.player_core.is_playing:
                    # print("[VideoPlayer] 开始播放媒体...")
                    self.player_core.play()
                    # 同时控制原始视频播放器
                    if hasattr(self, 'original_player_core') and self.original_player_core:
                        self.original_player_core.play()
                else:
                    # print("[VideoPlayer] 暂停播放媒体...")
                    
                    # 1. 先暂停主播放器
                    self.player_core.pause()
                    
                    # 2. 获取主播放器的当前位置
                    current_position = self.player_core.position
                    
                    # 3. 暂停原始视频播放器并同步位置
                    if hasattr(self, 'original_player_core') and self.original_player_core:
                        self.original_player_core.pause()
                        # 同步原始播放器位置到主播放器位置，确保左右视频完全同步
                        self.original_player_core.set_position(current_position)
                    
                    # print(f"[VideoPlayer] toggle_play_pause 暂停并同步位置: {current_position}")
            # 更新播放按钮图标
            self._update_play_button_icon()
        except Exception as e:
            print(f"[VideoPlayer] 播放操作失败: {e}")
            pass
            import traceback
            traceback.print_exc()
    
    def update_progress(self):
        """
        更新进度条和时间标签
        """
        if self.player_core:
            try:
                # 更新播放/暂停按钮图标（通过控制栏）
                if hasattr(self, 'control_bar') and self.control_bar:
                    self.control_bar.set_playing(self.player_core.is_playing)
                else:
                    self._update_play_button_icon()
                
                # 只有在用户不交互时才更新进度条
                if not self._user_interacting:
                    # 获取当前播放时间和总时长（毫秒）
                    current_time = self.player_core.time
                    duration = self.player_core.duration
                    
                    if duration > 0:
                        # 计算进度百分比
                        progress = (current_time / duration) * 1000
                        
                        # 使用控制栏更新进度
                        if hasattr(self, 'control_bar') and self.control_bar:
                            self.control_bar.set_progress(int(progress))
                            current_time_str = self._format_time(current_time / 1000)
                            duration_str = self._format_time(duration / 1000)
                            self.control_bar.set_time_text(current_time_str, duration_str)
                        else:
                            self.progress_slider.setValue(int(progress))
                            current_time_str = self._format_time(current_time / 1000)
                            duration_str = self._format_time(duration / 1000)
                            self.time_label.setText(f"{current_time_str} / {duration_str}")
                
                # 对比预览模式下同步左右播放器
                if self.comparison_mode and hasattr(self, 'original_player_core') and self.original_player_core:
                    try:
                        # 检查播放器实例是否有效
                        if not hasattr(self.player_core, '_mpv') or self.player_core._mpv is None:
                            return
                        if not hasattr(self.original_player_core, '_mpv') or self.original_player_core._mpv is None:
                            return
                            
                        # 获取主播放器的播放状态和时间信息（主播放器是右侧应用LUT的）
                        main_playing = self.player_core.is_playing
                        main_time = self.player_core.time
                        main_duration = self.player_core.duration
                        
                        # 获取原始播放器的信息（原始播放器是左侧的）
                        original_playing = self.original_player_core.is_playing
                        original_time = self.original_player_core.time
                        original_duration = self.original_player_core.duration
                        
                        # 确保两个播放器都有有效时长
                        if main_duration <= 0 or original_duration <= 0:
                            return
                        
                        # 1. 检查缓冲状态 - 如果主播放器正在缓冲，暂停原始播放器以避免抽搐
                        try:
                            main_buffer_status = self.player_core._get_property('core-idle')
                            if main_buffer_status is not None and main_buffer_status is True:
                                # 主播放器正在缓冲，暂停原始播放器
                                if original_playing:
                                    self.original_player_core.pause()
                                return
                        except Exception:
                            # 获取缓冲状态失败，继续执行
                            pass
                        
                        # 2. 同步播放状态 - 只有在状态不同时才操作
                        if main_playing != original_playing:
                            if main_playing:
                                self.original_player_core.play()
                            else:
                                self.original_player_core.pause()
                        
                        # 3. 计算进度差值（毫秒）
                        time_diff = abs(main_time - original_time)
                        
                        # 4. 当差值大于2秒时，让左侧视频seek到右侧相同时间+1秒
                        if time_diff > 2000:  # 2秒差异
                            # 计算右侧时间+1秒的位置（毫秒）
                            target_time = main_time + 1000  # 右侧时间+1秒
                            # 确保目标时间不超过媒体时长
                            if target_time < main_duration:
                                # 计算目标位置百分比
                                target_pos_percent = target_time / main_duration
                                # 设置原始播放器位置
                                self.original_player_core.set_position(target_pos_percent)
                    except Exception as sync_error:
                        # 同步错误不影响主播放器功能
                        print(f"[VideoPlayer] 同步播放器时发生错误: {sync_error}")
                        import traceback
                        traceback.print_exc()
            except Exception as e:
                pass
    
    def _handle_user_start_interact(self):
        """
        处理用户开始与进度条交互
        """
        self._user_interacting = True
    
    def _handle_user_end_interact(self):
        """
        处理用户结束与进度条交互
        """
        self._user_interacting = False
        # 执行进度跳转
        self._handle_user_seek()
    
    def _format_time(self, seconds):
        """
        将秒数格式化为 HH:MM:SS 或 MM:SS 格式
        
        Args:
            seconds (float): 秒数
            
        Returns:
            str: 格式化后的时间字符串
        """
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        
        if hours > 0:
            return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"
        else:
            return f"{int(minutes):02d}:{int(seconds):02d}"
    
    def _handle_value_change(self, value):
        """
        处理进度条值变化事件
        """
        if self.player_core and self._user_interacting:
            # 计算当前位置（秒）
            position = (value / 1000) * (self.player_core.duration / 1000)
            self.seek(position)
    
    def _handle_user_seek(self):
        """
        处理用户拖动进度条后的跳转
        """
        if self.player_core:
            # 获取当前进度条值
            value = self.progress_slider.value()
            # 计算当前位置（秒）
            position = (value / 1000) * (self.player_core.duration / 1000)
            self.seek(position)
    
    def pause_progress_update(self):
        """
        暂停进度更新（已禁用）
        """
        # 暂停功能已移除，进度更新始终启用
        pass
    
    def resume_progress_update(self):
        """
        恢复进度更新（已禁用）
        """
        # 暂停功能已移除，进度更新始终启用
        pass
    
    def update_volume_icon(self):
        """
        更新音量图标
        """
        # 根据音量值更新图标
        if self._is_muted or self._current_volume <= 0:
            # 设置静音图标
            self.volume_button.setText("🔇")
        elif self._current_volume < 50:
            # 设置低音量图标
            self.volume_button.setText("🔊")
        else:
            # 设置高音量图标
            self.volume_button.setText("🔊")
    
    def toggle_mute(self):
        """
        切换静音状态
        """
        if self.player_core:
            if self._is_muted:
                # 取消静音，恢复之前的音量
                self._is_muted = False
                self.set_volume(self._previous_volume)
            else:
                # 静音，保存当前音量
                self._is_muted = True
                self._previous_volume = self._current_volume
                self.set_volume(0)
    
    def _init_volume_menu(self, initial_volume):
        """
        初始化音量菜单
        """
        # 创建自定义控制菜单
        self.volume_menu = CustomControlMenu(self)
        
        # 创建音量菜单内容部件
        volume_content = QWidget()
        volume_content.setStyleSheet("background-color: transparent;")
        
        # 创建纵向布局
        volume_layout = QVBoxLayout(volume_content)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_layout.setSpacing(int(5 * self.dpi_scale))
        # 设置水平和垂直居中对齐
        volume_layout.setAlignment(Qt.AlignCenter)
        
        # 创建音量值显示标签
        self.volume_menu_label = QLabel(f"{initial_volume}%")
        font_size = int(7 * self.dpi_scale)
        self.volume_menu_label.setStyleSheet(
            "QLabel {" +
            #f"color: #333;" +
            #"font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;" +
            f"font-size: {font_size}px;" +
            "text-align: center;" +
            "background-color: transparent;" +
            "}"
        )
        
        # 创建纵向数值控制条
        self.volume_menu_slider = CustomValueBar(orientation=CustomValueBar.Vertical)
        self.volume_menu_slider.setRange(0, 100)
        self.volume_menu_slider.setValue(initial_volume)
        # 设置音量条样式，与横向音量条保持一致
        self.volume_menu_slider._bg_color = QColor(99, 99, 99)
        self.volume_menu_slider._progress_color = QColor(0, 120, 212)
        self.volume_menu_slider._handle_fill_color = QColor(255, 255, 255)
        self.volume_menu_slider._handle_border_color = QColor(0, 120, 212)
        
        # 设置纵向滑块尺寸
        scaled_width = int(20 * self.dpi_scale)
        scaled_height = int(60 * self.dpi_scale)
        self.volume_menu_slider.setFixedSize(scaled_width, scaled_height)
        
        # 添加组件到布局
        volume_layout.addWidget(self.volume_menu_label)
        volume_layout.addWidget(self.volume_menu_slider)
        
        # 设置菜单内容
        self.volume_menu.set_content(volume_content)
        
        # 设置目标按钮
        self.volume_menu.set_target_button(self.volume_button)
        
        # 连接信号
        self.volume_menu_slider.valueChanged.connect(self._on_volume_slider_changed)
    
    def toggle_volume_menu(self):
        """
        切换音量菜单的显示/隐藏状态
        """
        if self.volume_menu.isVisible():
            self.hide_volume_menu()
        else:
            self.show_volume_menu()
    
    def show_volume_menu(self, event=None):
        """
        显示音量菜单
        """
        if not self.volume_menu:
            return
        
        # 直接调用菜单的show()方法，让其内部处理位置计算
        self.volume_menu.show()
        self.is_volume_menu_visible = True
    
    def hide_volume_menu(self):
        """
        隐藏音量菜单
        """
        if self.volume_menu and self.volume_menu.isVisible():
            self.volume_menu.hide()
            self.is_volume_menu_visible = False
    
    def _handle_volume_button_leave(self, event):
        """
        处理音量按钮鼠标离开事件
        """
        pass
    
    def _on_volume_slider_changed(self, value):
        """
        处理音量滑块值变化事件
        """
        # 更新音量显示标签
        if hasattr(self, 'volume_menu_label') and self.volume_menu_label:
            self.volume_menu_label.setText(f"{value}%")
        
        # 更新音量
        self.set_volume(value)
        
    def _on_muted_changed(self, muted):
        """
        处理静音状态变化事件
        """
        self._is_muted = muted
        if muted:
            # 保存当前音量并设置为0
            self._previous_volume = self._current_volume
            self.player_core.set_volume(0)
            # 保存音量设置（保存静音前的音量）
            self.save_volume_setting(self._previous_volume)
        else:
            # 恢复之前的音量
            self.player_core.set_volume(self._previous_volume)
            # 保存音量设置（保存恢复后的音量）
            self.save_volume_setting(self._previous_volume)
    
    def load_volume_setting(self):
        """
        加载保存的音量设置
        """
        # 使用SettingsManager加载音量设置，默认音量为100
        settings_manager = SettingsManager()
        return settings_manager.get_setting('player.volume', 100)

    def load_volume_setting(self):
        """
        加载保存的音量设置
        已弃用：请使用 SettingsManager.get_player_volume()

        Returns:
            int: 音量值 (0-100)
        """
        settings_manager = SettingsManager()
        return settings_manager.get_player_volume()

    def save_volume_setting(self, volume):
        """
        保存音量设置到 last_volume

        Args:
            volume (int): 音量值 (0-100)
        """
        settings_manager = SettingsManager()
        settings_manager.save_player_volume(volume)

    def load_speed_setting(self):
        """
        加载保存的倍速设置
        已弃用：请使用 SettingsManager.get_player_speed()

        Returns:
            float: 倍速值
        """
        settings_manager = SettingsManager()
        return settings_manager.get_player_speed()

    def save_speed_setting(self, speed):
        """
        保存倍速设置到 last_speed

        Args:
            speed (float): 倍速值
        """
        settings_manager = SettingsManager()
        settings_manager.save_player_speed(speed)
    
    def load_cube_file(self):
        """
        加载或移除Cube文件
        - 如果已有LUT应用，移除LUT并恢复按钮样式
        - 如果没有LUT应用，触发LUT文件导入
        """
        try:
            # 检查当前是否有LUT应用
            if self.cube_loaded and self.cube_path:
                # 已有LUT应用，移除LUT效果
                # print("[VideoPlayer] 移除LUT效果...")
                self.clear_cube_file()
                # 恢复按钮为普通样式
                if hasattr(self, 'control_bar') and self.control_bar:
                    self.control_bar.set_lut_loaded(False)
                else:
                    self.load_cube_button.set_button_type("normal")
            else:
                # 没有LUT应用，触发LUT文件导入
                # 打开文件选择对话框
                cube_file, _ = QFileDialog.getOpenFileName(
                    self,
                    "选择Cube文件",
                    "",
                    "Cube文件 (*.cube);;所有文件 (*.*)"
                )

                if cube_file:
                    # 获取应用数据目录
                    data_dir = get_app_data_path()
                    # 构建目标Cube文件路径
                    target_cube_path = os.path.join(data_dir, "lut.cube")

                    # 复制用户选择的Cube文件到data目录，并重命名为lut.cube
                    shutil.copy2(cube_file, target_cube_path)
                    # print(f"[VideoPlayer] 已将Cube文件复制到: {target_cube_path}")

                    # 使用复制后的Cube文件
                    self.set_cube_file(target_cube_path)
                    # print(f"[VideoPlayer] 成功加载Cube文件: {cube_file}")
                    # 更新按钮为强调样式状态
                    if hasattr(self, 'control_bar') and self.control_bar:
                        self.control_bar.set_lut_loaded(True)
                    else:
                        self.load_cube_button.set_button_type("primary")
        except Exception as e:
            print(f"[VideoPlayer] LUT操作失败: {e}")
            import traceback
            traceback.print_exc()
    
    def toggle_comparison_mode(self, checked):
        """
        切换对比预览模式
        """
        try:
            self.comparison_mode = checked
            if checked:
                # print("[VideoPlayer] 启用对比预览模式")
                # 实现对比预览逻辑
                self._enable_comparison_mode()
                # 激活状态使用强调样式
                if hasattr(self, 'control_bar') and self.control_bar:
                    self.control_bar.set_comparison_mode(True)
                else:
                    self.comparison_button.set_button_type("primary")
                # 发送视频重新配置命令，确保两个视频区域都能正确显示
                if self.player_core and hasattr(self.player_core, '_mpv') and self.player_core._mpv is not None:
                    self.player_core._execute_command(['video-reconfig'])
                if hasattr(self, 'original_player_core') and self.original_player_core:
                    self.original_player_core._execute_command(['video-reconfig'])
            else:
                # print("[VideoPlayer] 禁用对比预览模式")
                # 恢复正常预览模式
                self._disable_comparison_mode()
                # 未激活状态使用普通样式
                if hasattr(self, 'control_bar') and self.control_bar:
                    self.control_bar.set_comparison_mode(False)
                else:
                    self.comparison_button.set_button_type("normal")
                # 发送视频重新配置命令，确保恢复后视频能正确显示
                if self.player_core and hasattr(self.player_core, '_mpv') and self.player_core._mpv is not None:
                    self.player_core._execute_command(['video-reconfig'])
        except Exception as e:
            print(f"[VideoPlayer] 切换对比预览模式失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _enable_comparison_mode(self):
        """
        启用对比预览模式
        - 创建两个视频播放区域
        - 左侧：原始视频（音量受音量条控制）
        - 右侧：应用了Cube滤镜的视频（音量静音，不受音量条控制）
        """
        # 检查是否已经初始化对比预览布局
        if not self.comparison_layout:
            # 移除当前的video_frame
            self.media_frame.layout().removeWidget(self.video_frame)
            self.media_frame.layout().removeWidget(self.audio_stacked_widget)
            
            # 创建对比预览布局
            self.comparison_layout = QHBoxLayout()
            self.comparison_layout.setContentsMargins(0, 0, 0, 0)
            self.comparison_layout.setSpacing(0)
            
            # 创建左侧原始视频区域
            self.original_video_frame = QWidget()
            self.original_video_frame.setStyleSheet("background-color: black;")
            
            # 创建右侧滤镜视频区域
            self.filtered_video_frame = QWidget()
            self.filtered_video_frame.setStyleSheet("background-color: black;")
            
            # 检查当前媒体类型，如果是音频则将对比预览窗口大小设置为0×0
            file_ext = os.path.splitext(self._current_file_path)[1].lower()
            audio_extensions = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.aiff', '.ape', '.opus']
            if file_ext in audio_extensions:
                self.original_video_frame.setMinimumSize(0, 0)
                self.original_video_frame.resize(0, 0)
                self.filtered_video_frame.setMinimumSize(0, 0)
                self.filtered_video_frame.resize(0, 0)
            else:
                self.original_video_frame.setMinimumSize(75, 50)
                self.filtered_video_frame.setMinimumSize(75, 50)
            
            # 添加到对比布局
            self.comparison_layout.addWidget(self.original_video_frame)
            self.comparison_layout.addWidget(self.filtered_video_frame)
            
            # 添加对比布局到媒体框架
            self.media_frame.layout().addLayout(self.comparison_layout)
            
            # 创建第二个MPV实例用于原始视频
            if not hasattr(self, 'original_player_core'):
                self.original_player_core = MPVPlayerCore()
                # 将原始视频播放器绑定到original_video_frame窗口
                self.original_player_core.set_window(self.original_video_frame.winId())
            
            # 确保主播放器绑定到filtered_video_frame窗口
            self.player_core.set_window(self.filtered_video_frame.winId())
        
        # 加载当前视频到两个播放器
        if self._current_file_path:
            # 保存当前播放状态
            current_playing = self.player_core.is_playing
            
            # 1. 同时加载视频到两个播放器
            self.player_core.set_media(self._current_file_path)
            self.original_player_core.set_media(self._current_file_path)
            
            # 2. 同时应用滤镜（仅主播放器）
            if self.cube_path and self.cube_loaded:
                self.player_core.enable_cube_filter(self.cube_path)
            
            # 3. 同时设置音量
            self.player_core.set_volume(0)  # 主播放器静音
            self.original_player_core.set_volume(self._current_volume)  # 原始播放器使用当前音量
            
            # 4. 开始播放媒体
            self.player_core.play()
            self.original_player_core.play()
            
            # 5. 设置初始位置（使用更精确的位置设置）
            # 立即设置初始位置，确保从相同位置开始播放
            self.player_core.set_position(0)
            self.original_player_core.set_position(0)
            
            # 6. 根据需要设置播放状态
            if not current_playing:
                # 确保媒体已经开始加载后再设置暂停
                self.player_core.pause()
                self.original_player_core.pause()
    
    def _disable_comparison_mode(self):
        """
        禁用对比预览模式
        - 恢复单一视频播放区域
        - 恢复套用LUT的视频的声音音量，受到音量条控制
        """
        if self.comparison_layout:
            # 移除对比布局
            while self.comparison_layout.count() > 0:
                widget = self.comparison_layout.itemAt(0).widget()
                if widget is not None:
                    self.comparison_layout.removeWidget(widget)
                    widget.hide()
            
            # 添加回原来的video_frame
            self.media_frame.layout().addWidget(self.video_frame)
            self.media_frame.layout().addWidget(self.audio_stacked_widget)
            
            # 将主播放器绑定回原来的video_frame窗口
            self.player_core.set_window(self.video_frame.winId())
            
            # 恢复视频播放
            if self._current_file_path:
                # print("[VideoPlayer] 关闭对比预览，重新加载视频到单个播放区域")
                # 先停止当前播放
                self.player_core.stop()
                # 清理滤镜资源
                self.player_core.disable_cube_filter()
                # 重新加载媒体
                self.player_core.set_media(self._current_file_path)
                # 继续应用LUT效果
                if self.cube_path and self.cube_loaded:
                    self.player_core.enable_cube_filter(self.cube_path)
                # 恢复播放
                self.player_core.play()
                # 继承当前音量
                self.player_core.set_volume(self._current_volume)
            
            # 停止并清理原始播放器
            if hasattr(self, 'original_player_core'):
                self.original_player_core.stop()
                self.original_player_core.disable_cube_filter()
                self.original_player_core.cleanup()
                delattr(self, 'original_player_core')
            
            # 重置对比预览相关属性
            self.original_video_frame = None
            self.filtered_video_frame = None
            self.comparison_layout = None
            # 确保原始播放器引用已被清理
            if hasattr(self, 'original_player_core'):
                delattr(self, 'original_player_core')
            
            # 重置对比模式标志
            self.comparison_mode = False
    
    def _connect_core_signals(self):
        """
        连接内核信号到适配层
        """
        pass
    
    def _on_idle_event(self):
        """
        处理MPVPlayerCore的idle事件回调，发射VideoPlayer的idle_event信号
        """
        self.idle_event.emit()
    
    def _connect_mpv_signals(self):
        """
        连接MPV内核信号
        """
        pass
    
    def keyPressEvent(self, event):
        """
        处理键盘按键事件
        - 空格键：切换播放/暂停状态
        """
        if event.key() == Qt.Key_Space:
            # 空格键按下，切换播放/暂停状态
            self.toggle_play_pause()
        else:
            # 其他按键事件，交给父类处理
            super().keyPressEvent(event)
    
    def focusInEvent(self, event):
        """
        处理焦点进入事件
        - 确保组件获得焦点时能够接收键盘事件
        """
        super().focusInEvent(event)
    
    def mousePressEvent(self, event):
        """
        处理鼠标点击事件
        - 点击组件时，确保获得焦点，以便接收键盘事件
        """
        self.setFocus()
        super().mousePressEvent(event)
    
    def load_media(self, file_path):
        """
        加载媒体文件
        
        Args:
            file_path: 媒体文件路径
        """
        if self.player_core:
            # 停止当前播放
            self.player_core.stop()
            # 同时停止原始视频播放器（如果存在）
            if hasattr(self, 'original_player_core') and self.original_player_core:
                self.original_player_core.stop()
            
            # 清理滤镜资源
            self.player_core.disable_cube_filter()
            if hasattr(self, 'original_player_core') and self.original_player_core:
                self.original_player_core.disable_cube_filter()
            
            # 设置新的媒体路径
            self._current_file_path = file_path
            
            # 检测文件类型
            file_ext = os.path.splitext(file_path)[1].lower()
            audio_extensions = ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.aiff', '.ape', '.opus']
            
            # 获取媒体布局
            media_layout = self.media_frame.layout()
            
            if file_ext in audio_extensions:
                # 播放音频时，确保只有audio_stacked_widget在布局中
                # 先清空布局
                while media_layout.count() > 0:
                    item = media_layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.hide()
                
                # 隐藏对比预览模式下的视频区域
                if hasattr(self, 'original_video_frame') and self.original_video_frame is not None:
                    self.original_video_frame.hide()
                if hasattr(self, 'filtered_video_frame') and self.filtered_video_frame is not None:
                    self.filtered_video_frame.hide()
                
                # 确保audio_stacked_widget在布局中并显示
                media_layout.addWidget(self.audio_stacked_widget)
                self.audio_stacked_widget.show()
                
                # 获取背景样式设置
                settings = SettingsManager()
                background_style = settings.get_setting("player.audio_background_style", "流体动画")
                
                # 根据设置加载对应的背景
                if background_style == "封面模糊":
                    if self.audio_background:
                        self.audio_background.load(AudioBackground.MODE_COVER_BLUR)
                else:
                    # 默认使用流体渐变背景
                    if self.audio_background:
                        self.audio_background.load(AudioBackground.MODE_FLUID)
                
                # 主播放器加载并播放音频
                self.player_core.set_media(file_path)
                self.player_core.play()
                
                # 提取并显示音频元数据和封面
                self.extract_audio_metadata(file_path, background_style)

                # 隐藏LUT按钮，因为音频没有画面需要应用LUT
                if hasattr(self, 'control_bar') and self.control_bar:
                    self.control_bar.show_lut_controls(False)
                else:
                    self.load_cube_button.hide()
                    self.comparison_button.hide()
            else:
                # 显示LUT按钮，因为视频有画面需要应用LUT
                if hasattr(self, 'control_bar') and self.control_bar:
                    self.control_bar.show_lut_controls(True)
                    self.control_bar.set_lut_loaded(self.cube_loaded)
                else:
                    self.load_cube_button.show()
                    # 只有在已经加载LUT的情况下才显示对比预览按钮
                    if self.cube_loaded:
                        self.comparison_button.show()
                    else:
                        self.comparison_button.hide()
                
                # 清除音频封面数据（视频模式下不显示音频封面）
                self._audio_cover_data = None
                
                # 检查是否处于对比预览模式
                is_comparison_mode = hasattr(self, 'comparison_mode') and self.comparison_mode
                
                if is_comparison_mode and hasattr(self, 'original_player_core') and self.original_player_core:
                    # 对比预览模式：保持对比布局
                    # print("[VideoPlayer] 处于对比预览模式，加载视频到两个播放区域")
                    
                    # 1. 同时加载视频到两个播放器
                    self.player_core.set_media(file_path)
                    self.original_player_core.set_media(file_path)
                    
                    # 2. 应用滤镜（仅主播放器）
                    if self.cube_path and os.path.exists(self.cube_path) and self.cube_loaded:
                        self.player_core.enable_cube_filter(self.cube_path)
                    
                    # 3. 同时设置音量
                    self.player_core.set_volume(self._current_volume)  # 右侧带滤镜视频使用当前音量
                    self.original_player_core.set_volume(0)  # 左侧原始视频静音
                    
                    # 4. 同时设置初始状态（暂停）
                    self.player_core.pause()
                    self.original_player_core.pause()
                    
                    # 5. 同时设置初始位置
                    self.player_core.set_position(0)
                    self.original_player_core.set_position(0)
                    
                    # 6. 同时开始播放
                    self.player_core.play()
                    self.original_player_core.play()
                    
                    # 4. 确保对比预览区域可见
                    if hasattr(self, 'original_video_frame') and self.original_video_frame is not None:
                        self.original_video_frame.show()
                    if hasattr(self, 'filtered_video_frame') and self.filtered_video_frame is not None:
                        self.filtered_video_frame.show()
                    
                    # 卸载音频背景（视频模式下不需要）
                    if self.audio_background:
                        self.audio_background.unload()
                else:
                    # 非对比预览模式：使用单个视频框架
                    # 先清空布局
                    while media_layout.count() > 0:
                        item = media_layout.takeAt(0)
                        widget = item.widget()
                        if widget is not None:
                            widget.hide()
                    
                    # 确保video_frame在布局中并显示
                    media_layout.addWidget(self.video_frame)
                    self.video_frame.setMinimumSize(150, 100)
                    self.video_frame.show()
                    
                    # 卸载音频背景（视频模式下不需要）
                    if self.audio_background:
                        self.audio_background.unload()
                    
                    # 主播放器加载并播放视频
                    self.player_core.set_media(file_path)
                    if self.cube_path and os.path.exists(self.cube_path) and self.cube_loaded:
                        self.player_core.enable_cube_filter(self.cube_path)
                    self.player_core.play()
            
            # 更新播放按钮状态
            self._update_play_button_icon()
    
    def extract_audio_metadata(self, file_path, background_style="流体动画"):
        """
        从音频文件中提取元数据和封面颜色
        
        Args:
            file_path: 音频文件路径
            background_style: 背景样式（"流体动画"或"封面模糊"）
        """
        cover_data = None
        
        try:
            cover_data = self._extract_cover_from_audio(file_path)
        except Exception as e:
            print(f"[VideoPlayer] 提取封面失败: {e}")
        
        self._audio_cover_data = cover_data
        
        if cover_data:
            if background_style == "封面模糊":
                # 使用封面模糊背景
                if self.audio_background and self.audio_background.isLoaded():
                    self.audio_background.setCoverData(cover_data)
            else:
                # 使用流体渐变背景，提取颜色
                colors = extract_cover_colors(cover_data, num_colors=5, min_distance=50.0)
                if colors and len(colors) >= 5:
                    if self.audio_background and self.audio_background.isLoaded():
                        self.audio_background.setCustomColors(colors)
                else:
                    self._use_default_theme()
        else:
            # 无封面时使用默认主题
            if background_style == "封面模糊":
                # 封面模糊模式下无封面时切换到流体动画模式并使用强调色主题
                if self.audio_background:
                    self.audio_background.load(AudioBackground.MODE_FLUID)
                    self.audio_background.useAccentTheme()
            else:
                self._use_default_theme()
        
        self._update_audio_icon()
        self.song_name_label.hide()
        self.artist_name_label.hide()
    
    def _extract_cover_from_audio(self, file_path: str) -> bytes:
        """
        从音频文件中提取封面图像数据
        
        Args:
            file_path: 音频文件路径
        
        Returns:
            封面图像的二进制数据，提取失败返回None
        """
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            
            if file_ext == '.mp3':
                return self._extract_cover_mp3(file_path)
            elif file_ext in ['.m4a', '.mp4']:
                return self._extract_cover_mp4(file_path)
            elif file_ext == '.flac':
                return self._extract_cover_flac(file_path)
            elif file_ext in ['.ogg', '.ogv']:
                return self._extract_cover_ogg(file_path)
            elif file_ext in ['.wav', '.aiff', '.aif']:
                return self._extract_cover_wav(file_path)
            else:
                return None
                
        except Exception as e:
            print(f"[VideoPlayer] 提取封面数据失败: {e}")
            return None
    
    def _extract_cover_mp3(self, file_path: str) -> bytes:
        """从MP3文件提取封面"""
        try:
            audio = ID3(file_path)
            for tag in ['APIC:', 'PIC:']:
                if tag in audio:
                    frame = audio[tag]
                    if hasattr(frame, 'data'):
                        return frame.data
                    elif hasattr(frame, 'image'):
                        return frame.image
            return None
        except Exception:
            return None
    
    def _extract_cover_mp4(self, file_path: str) -> bytes:
        """从M4A/MP4文件提取封面"""
        try:
            audio = MP4(file_path)
            if 'covr' in audio:
                cover_data = audio['covr'][0]
                if isinstance(cover_data, bytes):
                    return cover_data
            return None
        except Exception:
            return None
    
    def _extract_cover_flac(self, file_path: str) -> bytes:
        """从FLAC文件提取封面"""
        try:
            audio = FLAC(file_path)
            if audio.pictures:
                picture = audio.pictures[0]
                return picture.data
            return None
        except Exception:
            return None
    
    def _extract_cover_ogg(self, file_path: str) -> bytes:
        """从OGG文件提取封面"""
        try:
            audio = OggVorbis(file_path)
            if hasattr(audio, 'pictures') and audio.pictures:
                picture = audio.pictures[0]
                return picture.data
            return None
        except Exception:
            return None
    
    def _extract_cover_wav(self, file_path: str) -> bytes:
        """从WAV/AIFF文件提取封面"""
        try:
            audio = WAVE(file_path)
            if hasattr(audio, 'pictures') and audio.pictures:
                picture = audio.pictures[0]
                return picture.data
            return None
        except Exception:
            return None
    
    def _use_default_theme(self):
        """使用默认主题（无封面时使用强调色主题）"""
        if self.audio_background and self.audio_background.isLoaded():
            if self._audio_cover_data:
                settings = SettingsManager()
                theme = settings.get_setting('player/fluid_gradient_theme', 'sunset')
                self.audio_background.setTheme(theme)
            else:
                self.audio_background.useAccentTheme()
    
    def setFluidGradientTheme(self, theme: str):
        """
        设置流体渐变背景主题
        
        Args:
            theme: 主题名称 ('sunset', 'ocean', 'aurora')
        """
        if self.audio_background and self.audio_background.isLoaded():
            self.audio_background.setTheme(theme)
    
    def setFluidGradientSpeed(self, speed_factor: float):
        """
        设置流体渐变动画速率
        
        Args:
            speed_factor: 速率因子 (0.1 - 2.0)
        """
        if self.audio_background and self.audio_background.isLoaded():
            self.audio_background.setAnimationSpeed(speed_factor)
    
    def pauseFluidGradientAnimation(self, paused: bool = True):
        """
        暂停/恢复流体渐变动画
        
        Args:
            paused: 是否暂停
        """
        if self.audio_background and self.audio_background.isLoaded():
            self.audio_background.pauseAnimation(paused)
    
    def _create_rounded_pixmap(self, pixmap, radius):
        """
        创建带圆角的Pixmap
        
        Args:
            pixmap: 原始QPixmap
            radius: 圆角半径（像素）
        
        Returns:
            QPixmap: 带圆角的新pixmap
        """
        if pixmap.isNull():
            return pixmap
        
        size = pixmap.size()
        rounded = QPixmap(size)
        rounded.fill(Qt.transparent)
        
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
        painter.setClipPath(path)
        
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        
        return rounded
    
    def _update_audio_icon(self):
        """
        更新音频格式图标显示
        如果有封面数据则显示封面，否则显示SVG图标
        """
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            icons_path = os.path.join(current_dir, '..', 'icons')
            icons_path = os.path.abspath(icons_path)
            
            icon_name = "音乐_playing.svg"
            icon_path = os.path.join(icons_path, icon_name)
            
            if not os.path.exists(icon_path):
                print(f"[VideoPlayer] 音频图标文件不存在: {icon_path}")
                return
            
            scaled_cover_size = int(50 * self.dpi_scale)
            
            file_name = os.path.basename(self._current_file_path)
            name_without_ext = os.path.splitext(file_name)[0]
            
            # 停止旧的滚动动画（如果存在）
            if self.audio_file_animation:
                self.audio_file_animation.stop()
                try:
                    for i in range(self.audio_file_animation.animationCount()):
                        anim = self.audio_file_animation.animationAt(i)
                        if isinstance(anim, QPropertyAnimation):
                            anim.finished.disconnect(self._on_scroll_animation_finished)
                            break
                except (TypeError, RuntimeError):
                    pass
                self.audio_file_animation.deleteLater()
                self.audio_file_animation = None
            
            # 使用滚动文本控件设置文本
            if self.scrolling_text:
                self.scrolling_text.set_text(name_without_ext)
            
            icon_container_layout = self.audio_icon_container.layout()
            
            if self.audio_icon_widget is None:
                self.audio_icon_widget = SvgRenderer.render_svg_to_widget(icon_path, scaled_cover_size, self.dpi_scale)
                # 按正确顺序添加：先 SVG 图标，后滚动文本
                # 先移除可能已存在的滚动区域（如果之前添加过）
                if self.audio_file_scroll_area.parent() == self.audio_icon_container:
                    icon_container_layout.removeWidget(self.audio_file_scroll_area)
                # 添加 SVG 图标
                icon_container_layout.addWidget(self.audio_icon_widget, 0, Qt.AlignCenter)
                # 添加滚动文本区域（在 SVG 图标下方）
                icon_container_layout.addWidget(self.audio_file_scroll_area, 0, Qt.AlignHCenter)
            
            if self._audio_cover_data:
                if self.audio_icon_widget:
                    self.audio_icon_widget.hide()
                self.audio_cover_label.show()
                self.audio_cover_label.raise_()
                
                pixmap = QPixmap()
                image_data = io.BytesIO(self._audio_cover_data)
                pixmap.loadFromData(image_data.read())
                pixmap = pixmap.scaled(scaled_cover_size, scaled_cover_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                radius = int(6 * self.dpi_scale)
                pixmap = self._create_rounded_pixmap(pixmap, radius)
                self.audio_cover_label.setPixmap(pixmap)
            else:
                if self.audio_icon_widget:
                    self.audio_icon_widget.show()
                    self.audio_icon_widget.raise_()
                self.audio_cover_label.hide()
            
            self.audio_icon_container.show()
            
            self.cover_label.hide()
            # 注意：不能隐藏 audio_container，因为 audio_icon_container 是它的子控件
            # self.audio_container.hide()
            
        except Exception as e:
            print(f"[VideoPlayer] 更新音频格式图标失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _update_audio_file_scroll(self, name_without_ext):
        """
        更新音频文件名滚动状态（已废弃，功能由ScrollingText替代）
        
        Args:
            name_without_ext: 文件名（不含扩展名）
        """
        # 此方法已废弃，滚动功能由ScrollingText控件内部处理
        pass
    
    def _update_cover(self, cover_data):
        """
        更新封面显示
        
        Args:
            cover_data: 封面数据（字节）
        """
        # 停止滚动动画
        if self.audio_file_animation:
            self.audio_file_animation.stop()
            try:
                for i in range(self.audio_file_animation.animationCount()):
                    anim = self.audio_file_animation.animationAt(i)
                    if isinstance(anim, QPropertyAnimation):
                        anim.finished.disconnect(self._on_scroll_animation_finished)
                        break
            except (TypeError, RuntimeError):
                pass
            self.audio_file_animation.deleteLater()
            self.audio_file_animation = None
        self.audio_file_needs_scroll = False
        
        # 隐藏音频图标
        if self.audio_icon_widget:
            self.audio_icon_widget.hide()
        if self.audio_icon_container:
            self.audio_icon_container.hide()
        self.cover_label.show()
        self.audio_container.show()
        
        # 计算缩放后的封面大小（100dpx正方形）
        scaled_cover_size = int(50 * self.dpi_scale)
        
        if cover_data:
            try:
                # 从字节数据创建PIL Image
                pil_image = Image.open(io.BytesIO(cover_data))
                
                # 调整图像大小用于中央显示
                pil_image_cover = pil_image.resize((scaled_cover_size, scaled_cover_size), Image.Resampling.LANCZOS)
                
                # 创建QPixmap用于中央显示
                image_data = io.BytesIO()
                pil_image_cover.save(image_data, format='PNG')
                image_data.seek(0)
                pixmap = QPixmap()
                pixmap.loadFromData(image_data.read())
                from PySide6.QtGui import QGuiApplication
                pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                
                # 应用圆角矩形遮罩到中央封面
                rounded_pixmap = QPixmap(scaled_cover_size, scaled_cover_size)
                rounded_pixmap.fill(Qt.transparent)
                
                painter = QPainter(rounded_pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                
                # 创建圆角矩形路径
                radius = int(scaled_cover_size * 0.1)
                rect = QRect(0, 0, scaled_cover_size, scaled_cover_size)
                painter.setClipPath(self._get_rounded_rect_path(rect, radius))
                
                # 绘制图像
                painter.drawPixmap(rect, pixmap)
                painter.end()
                
                # 设置中央封面
                self.cover_label.setPixmap(rounded_pixmap)
                
                # 创建背景封面（使用原始封面图调整大小并应用模糊效果）
                # 获取background_label的当前大小
                background_size = self.background_label.size()
                
                # 调整封面大小以适应背景，保持宽高比
                pil_image_bg = pil_image.resize((background_size.width(), background_size.height()), Image.Resampling.LANCZOS)
                
                # 创建背景QPixmap
                bg_image_data = io.BytesIO()
                pil_image_bg.save(bg_image_data, format='PNG')
                bg_image_data.seek(0)
                bg_pixmap = QPixmap()
                bg_pixmap.loadFromData(bg_image_data.read())
                from PySide6.QtGui import QGuiApplication
                bg_pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                
                # 设置背景封面并应用高斯模糊效果
                self.background_label.setPixmap(bg_pixmap)
                self.background_label.setScaledContents(True)
                
            except Exception as e:
                print(f"[VideoPlayer] 处理封面失败: {e}")
                # 显示默认背景
                self._show_default_cover(scaled_cover_size)
        else:
            # 显示默认背景
            self._show_default_cover(scaled_cover_size)
    
    def _get_rounded_rect_path(self, rect, radius):
        """
        创建圆角矩形路径
        
        Args:
            rect: QRect对象
            radius: 圆角半径
        
        Returns:
            QPainterPath: 圆角矩形路径
        """
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        
        # 绘制圆角矩形
        path.moveTo(rect.left() + radius, rect.top())
        path.lineTo(rect.right() - radius, rect.top())
        path.arcTo(rect.right() - 2 * radius, rect.top(), 2 * radius, 2 * radius, 90, -90)
        path.lineTo(rect.right(), rect.bottom() - radius)
        path.arcTo(rect.right() - 2 * radius, rect.bottom() - 2 * radius, 2 * radius, 2 * radius, 0, -90)
        path.lineTo(rect.left() + radius, rect.bottom())
        path.arcTo(rect.left(), rect.bottom() - 2 * radius, 2 * radius, 2 * radius, 270, -90)
        path.lineTo(rect.left(), rect.top() + radius)
        path.arcTo(rect.left(), rect.top(), 2 * radius, 2 * radius, 180, -90)
        path.closeSubpath()
        
        return path
    
    def _on_scroll_animation_finished(self):
        """
        滚动动画结束回调（已废弃，功能由ScrollingText替代）
        """
        # 此方法已废弃，滚动功能由ScrollingText控件内部处理
        pass
    
    def _scroll_audio_file_label(self):
        """
        使用QPropertyAnimation实现文件名滚动效果（已废弃，功能由ScrollingText替代）
        """
        # 此方法已废弃，滚动功能由ScrollingText控件内部处理
        pass
    
    def _show_default_cover(self, size):
        """
        显示默认封面
        
        Args:
            size: 封面大小
        """
        # 停止滚动动画
        if self.audio_file_animation:
            self.audio_file_animation.stop()
            try:
                for i in range(self.audio_file_animation.animationCount()):
                    anim = self.audio_file_animation.animationAt(i)
                    if isinstance(anim, QPropertyAnimation):
                        anim.finished.disconnect(self._on_scroll_animation_finished)
                        break
            except (TypeError, RuntimeError):
                pass
            self.audio_file_animation.deleteLater()
            self.audio_file_animation = None
        self.audio_file_needs_scroll = False
        
        # 停止滚动文本控件
        if self.scrolling_text:
            self.scrolling_text.stop()
        
        # 隐藏音频图标
        if self.audio_icon_widget:
            self.audio_icon_widget.hide()
        if self.audio_icon_container:
            self.audio_icon_container.hide()
        self.cover_label.show()
        self.audio_container.show()
        
        # 创建默认背景
        default_pixmap = QPixmap(size, size)
        default_pixmap.fill(QColor(51, 51, 51))  # 深灰色背景
        from PySide6.QtGui import QGuiApplication
        default_pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
        
        # 设置到封面标签
        self.cover_label.setPixmap(default_pixmap)
        
        # 设置背景标签为深灰色，与默认封面颜色保持一致
        self.background_label.clear()
        self.background_label.setStyleSheet("background-color: #333333;")
    
    def play(self):
        """
        播放媒体
        """
        result = False
        if self.player_core:
            result = self.player_core.play()
            # 同时控制原始视频播放器
            if hasattr(self, 'original_player_core') and self.original_player_core:
                self.original_player_core.play()
        return result
    
    def pause(self):
        """
        暂停媒体
        """
        try:
            if self.player_core and hasattr(self.player_core, '_mpv') and self.player_core._mpv is not None:
                # print("[VideoPlayer] 暂停播放媒体...")
                
                # 1. 先暂停主播放器
                self.player_core.pause()
                
                # 2. 获取主播放器的当前位置
                current_position = self.player_core.position
                
                # 3. 暂停原始视频播放器并同步位置
                if hasattr(self, 'original_player_core') and self.original_player_core:
                    self.original_player_core.pause()
                    # 同步原始播放器位置到主播放器位置，确保左右视频完全同步
                    self.original_player_core.set_position(current_position)
                
                # 4. 更新播放按钮图标
                self._update_play_button_icon()
                
                # print(f"[VideoPlayer] 暂停并同步位置: {current_position}")
        except Exception as e:
            print(f"[VideoPlayer] 暂停操作失败: {e}")
            import traceback
            traceback.print_exc()
    
    def stop(self):
        """
        停止媒体
        """
        if self.player_core:
            self.player_core.stop()
            if hasattr(self, 'original_player_core') and self.original_player_core:
                self.original_player_core.stop()
        
        if self.audio_file_animation:
            self.audio_file_animation.stop()
            try:
                for i in range(self.audio_file_animation.animationCount()):
                    anim = self.audio_file_animation.animationAt(i)
                    if isinstance(anim, QPropertyAnimation):
                        anim.finished.disconnect(self._on_scroll_animation_finished)
                        break
            except (TypeError, RuntimeError):
                pass
            self.audio_file_animation.deleteLater()
            self.audio_file_animation = None
        
        if self.audio_stacked_widget:
            self.audio_stacked_widget.hide()
        
        if self.audio_background:
            self.audio_background.unload()
    
    def seek(self, position):
        """
        跳转到指定位置
        
        Args:
            position: 跳转位置（秒）
        """
        if self.player_core and hasattr(self.player_core, '_mpv') and self.player_core._mpv is not None:
            # 转换为0-1范围的位置
            try:
                duration = self.player_core.duration / 1000 if hasattr(self.player_core, 'duration') else 0
                if duration <= 0:
                    # 如果获取时长失败，尝试从播放器获取当前时长
                    duration = self.player_core._get_property_double('duration') if hasattr(self.player_core, '_get_property_double') else 0
                
                if duration > 0:
                    normalized_position = position / duration
                    # 确保位置在0-1范围内
                    normalized_position = max(0.0, min(1.0, normalized_position))
                    
                    # 同时设置两个播放器的位置
                    self.player_core.set_position(normalized_position)
                    if hasattr(self, 'original_player_core') and self.original_player_core and hasattr(self.original_player_core, '_mpv') and self.original_player_core._mpv is not None:
                        self.original_player_core.set_position(normalized_position)
            except Exception as e:
                print(f"[VideoPlayer] 跳转到指定位置失败: {e}")
    
    def set_volume(self, volume):
        """
        设置音量

        Args:
            volume: 音量值（0-100）
        """
        if volume < 0:
            volume = 0
        elif volume > 100:
            volume = 100

        if self.player_core:
            if self.comparison_mode:
                # 对比预览模式下：
                # - 只控制原始视频的音量（左侧）
                # - 应用了LUT滤镜的视频保持静音（右侧）
                if hasattr(self, 'original_player_core') and self.original_player_core:
                    self.original_player_core.set_volume(volume)
                # 主播放器（带滤镜）保持静音
                self.player_core.set_volume(0)
            else:
                # 非对比预览模式下，控制所有播放器的音量
                self.player_core.set_volume(volume)
                # 同时控制原始视频播放器（如果存在）
                if hasattr(self, 'original_player_core') and self.original_player_core:
                    self.original_player_core.set_volume(volume)

            self._current_volume = volume
            self._previous_volume = volume

            # 同步控制栏音量显示
            if hasattr(self, 'control_bar') and self.control_bar:
                self.control_bar.set_volume(volume)

        # 更新自定义音量控制组件的状态
        if hasattr(self, 'volume_control') and self.volume_control:
            self.volume_control.set_volume(volume)

        # 更新静音状态
        if volume == 0:
            self._is_muted = True
            if hasattr(self, 'volume_control') and self.volume_control:
                self.volume_control.set_muted(True)
        else:
            self._is_muted = False
            if hasattr(self, 'volume_control') and self.volume_control:
                self.volume_control.set_muted(False)
    
    def set_speed(self, speed):
        """
        设置播放速度
        
        Args:
            speed: 播放速度（0.5-3.0）
        """
        if self.player_core:
            self.player_core.set_speed(speed)
            # 同时控制原始视频播放器
            if hasattr(self, 'original_player_core') and self.original_player_core:
                self.original_player_core.set_speed(speed)
            self._current_speed = speed
            self.speed_dropdown.set_current_item(f"{speed}x")
            # 保存倍速设置到配置文件
            self.save_speed_setting(speed)
    
    def _update_lut_button_style(self, is_active):
        """
        更新LUT按钮样式
        
        Args:
            is_active: 是否激活状态（蓝底白字）
        """
        if not self.load_cube_button:
            return
        
        # 获取缩放参数
        scaled_border = int(0.5 * self.dpi_scale)
        scaled_padding = int(2.5 * self.dpi_scale)
        scaled_padding_right = int(5 * self.dpi_scale)
        scaled_border_radius = int(2.5 * self.dpi_scale)
        scaled_min_width = int(40 * self.dpi_scale)
        scaled_font_size = int(8 * self.dpi_scale)
        
        # 使用CustomButton的set_button_type方法更新样式，保持一致性
        if is_active:
            # 激活状态使用primary类型（蓝底白字）
            self.load_cube_button.set_button_type("primary")
        else:
            # 非激活状态使用normal类型（普通样式）
            self.load_cube_button.set_button_type("normal")
    
    def set_cube_file(self, cube_path):
        """
        设置Cube文件路径
        
        Args:
            cube_path: Cube文件路径
        """
        if self.player_core:
            self.cube_path = cube_path
            self.cube_loaded = self.player_core.enable_cube_filter(cube_path)
            # 如果成功加载LUT，更新按钮样式并显示对比预览按钮
            if self.cube_loaded:
                self._update_lut_button_style(True)
                self.comparison_button.show()
    
    def clear_cube_file(self):
        """
        清除Cube文件设置
        """
        # print("[VideoPlayer] 开始清除Cube文件设置")
        
        # 1. 首先确保对比预览模式已关闭
        if self.comparison_mode:
            # print("[VideoPlayer] 移除LUT前，先关闭对比预览模式")
            self.toggle_comparison_mode(False)
        
        # 2. 保存当前播放状态
        is_playing = False
        current_volume = self._current_volume
        if self.player_core:
            is_playing = self.player_core.is_playing
            # print(f"[VideoPlayer] 保存当前播放状态: 正在播放={is_playing}, 音量={current_volume}")
        
        # 3. 移除data目录中的lut.cube文件
        data_dir = get_app_data_path()
        lut_path = os.path.join(data_dir, "lut.cube")
        if os.path.exists(lut_path):
            try:
                os.remove(lut_path)
                # print(f"[VideoPlayer] 已删除LUT文件: {lut_path}")
            except Exception as e:
                print(f"[VideoPlayer] 删除LUT文件失败: {e}")
        
        # 4. 禁用LUT滤镜
        # print("[VideoPlayer] 禁用LUT滤镜")
        if self.player_core:
            # 使用player_core的disable_cube_filter方法移除滤镜
            self.player_core.disable_cube_filter()
            # 确保音量正确
            self.player_core.set_volume(current_volume)
        
        # 5. 重置LUT相关属性
        self.cube_path = None
        self.cube_loaded = False
        
        # 6. 更新按钮样式和状态
        self._update_lut_button_style(False)
        self.comparison_button.hide()
        self.load_cube_button.setText("加载LUT")
        
        # 7. 确保播放状态正确恢复
        if self.player_core and is_playing:
            # 如果之前在播放，确保继续播放
            if self.player_core._get_property_bool('pause'):
                self.player_core._set_property_bool('pause', False)
            # print(f"[VideoPlayer] 已恢复播放状态")
        
        # print("[VideoPlayer] Cube文件设置已清除")
    
    def check_and_apply_lut_file(self):
        """
        检查data目录中是否有lut.cube文件，如果有则应用它
        """
        print("[VideoPlayer] 检查是否有LUT文件需要应用")
        
        # 获取data目录路径
        data_dir = get_app_data_path()
        lut_path = os.path.join(data_dir, "lut.cube")
        
        # 检查lut.cube文件是否存在
        if os.path.exists(lut_path):
            # print(f"[VideoPlayer] 发现LUT文件: {lut_path}")
            # 应用LUT滤镜
            self.set_cube_file(lut_path)
        else:
            print("[VideoPlayer] 未发现LUT文件")
            # 确保LUT相关属性已重置
            self.cube_path = None
            self.cube_loaded = False
            # 更新按钮样式和状态
            self._update_lut_button_style(False)
            self.comparison_button.hide()
            self.load_cube_button.setText("加载LUT")
    
    def closeEvent(self, event):
        """
        窗口关闭事件，释放所有资源
        """
        # 停止播放
        self.stop()
        
        # 释放MPV资源
        if hasattr(self, 'player_core') and self.player_core:
            self.player_core.cleanup()
            self.player_core = None
        
        # 停止定时器
        if hasattr(self, 'timer') and self.timer:
            self.timer.stop()
            self.timer = None
        
        # 调用父类方法
        super().closeEvent(event)
    
    def resizeEvent(self, event):
        """
        窗口大小变化事件
        通知MPV播放器窗口大小已经改变，确保视频渲染区域正确跟随显示区域变化
        """
        super().resizeEvent(event)
        
        # 确保MPV内核已初始化
        if self.player_core and hasattr(self.player_core, '_mpv') and self.player_core._mpv is not None:
            try:
                # MPV会自动检测窗口大小变化，不需要显式发送video-reconfig命令
                # 这个命令在新版本的MPV中可能已经不存在或名称已更改
                # print(f"[VideoPlayer] resizeEvent: 视频窗口大小已调整，MPV将自动适应新大小")
                pass
            except Exception as e:
                print(f"[VideoPlayer] resizeEvent: 处理窗口大小变化失败 - {e}")
    
    def mouseDoubleClickEvent(self, event):
        """
        鼠标双击事件
        """
        pass

    def _update_detach_button_visibility(self):
        """
        根据设置更新分离窗口按钮的显示/隐藏
        读取 player.enable_fullscreen 设置，控制全屏按钮的可见性
        """
        try:
            # 获取设置管理器
            settings_manager = None
            app = QApplication.instance()
            if app is not None and hasattr(app, 'settings_manager'):
                settings_manager = app.settings_manager
            else:
                settings_manager = SettingsManager()

            # 读取设置
            enable_fullscreen = settings_manager.get_setting("player.enable_fullscreen", False)

            # 设置按钮可见性
            if self.control_bar:
                self.control_bar.set_detach_button_visible(enable_fullscreen)
        except Exception as e:
            # 如果读取设置失败，默认隐藏按钮
            if self.control_bar:
                self.control_bar.set_detach_button_visible(False)

    def _toggle_detach_window(self):
        """
        切换窗口分离/合并状态
        将视频播放组件分离为独立窗口或合并回主窗口
        """
        if self._is_detached:
            self._merge_window()
        else:
            self._detach_window()

    def _detach_window(self):
        """
        将视频播放器分离为独立窗口
        继承当前播放状态、进度、音量等所有内部状态
        """
        try:
            # 保存当前播放状态
            self._saved_position = self.player_core.position if self.player_core else 0
            self._saved_playing_state = self.player_core.is_playing if self.player_core else False
            self._current_file_path_before_detach = self._current_file_path

            # 创建独立窗口
            from PySide6.QtWidgets import QMainWindow

            class DetachedVideoWindow(QMainWindow):
                """分离的视频播放窗口 - 无边框全屏窗口
                
                布局结构：
                - 主窗口：只负责渲染视频内容
                - 控制栏覆盖窗口：独立的浮动窗口，包含控制栏
                """

                def __init__(self, video_player, parent=None):
                    super().__init__(parent)
                    self.video_player = video_player
                    self.setWindowTitle("视频播放器 - FreeAssetFilter")

                    self.setWindowFlags(Qt.FramelessWindowHint)
                    
                    self.setStyleSheet("background-color: #000000;")

                    app = QApplication.instance()
                    if hasattr(app, 'windowIcon') and app.windowIcon():
                        self.setWindowIcon(app.windowIcon())

                    central_widget = QWidget()
                    central_widget.setStyleSheet("background-color: #000000;")
                    self.setCentralWidget(central_widget)
                    
                    central_layout = QVBoxLayout(central_widget)
                    central_layout.setContentsMargins(0, 0, 0, 0)
                    central_layout.setSpacing(0)
                    
                    # 注意：media_frame 的父窗口设置由 setup_media_frame 方法处理
                    # 这里只创建占位符，不直接操作 media_frame
                    
                    self._create_control_overlay()
                    
                    self.setMouseTracking(True)
                    # 使用事件过滤器处理双击事件，避免直接替换 mouseDoubleClickEvent
                    self.video_frame = self.video_player.media_frame
                    if self.video_frame:
                        self.video_frame.setMouseTracking(True)

                    self.installEventFilter(self)

                    self._hide_control_bar_visible = True

                    self._mouse_monitor = None
                
                def setup_media_frame(self):
                    """设置媒体框架到分离窗口（在窗口显示后调用）"""
                    # 将 media_frame 从原父窗口移除并添加到分离窗口
                    if self.video_player.media_frame:
                        self.video_player.media_frame.setParent(self.centralWidget())
                        self.video_player.media_frame.setStyleSheet("background-color: transparent;")
                        self.video_player.media_frame.setGeometry(self.centralWidget().rect())
                        
                        # 添加到布局
                        layout = self.centralWidget().layout()
                        if layout:
                            layout.addWidget(self.video_player.media_frame, 1)
                        
                        # 更新 video_frame 几何属性
                        if self.video_player.media_frame.layout():
                            self.video_player.media_frame.layout().update()
                            self.video_player.video_frame.setGeometry(self.video_player.media_frame.rect())
                
                def start_mouse_monitor(self):
                    """启动鼠标监控（在窗口显示后调用）"""
                    if self._mouse_monitor is None:
                        self._mouse_monitor = MouseActivityMonitor(timeout=3000)
                        self._mouse_monitor.activity_callback = self._on_mouse_activity
                        self._mouse_monitor.timeout_callback = self._on_timeout_reached
                    self._mouse_monitor.start()
                
                def _create_control_overlay(self):
                    """创建控制栏覆盖窗口"""
                    self.control_overlay = QWidget(self, Qt.Tool)
                    self.control_overlay.setWindowTitle("控制栏")
                    self.control_overlay.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
                    
                    self.control_overlay.setAttribute(Qt.WA_TranslucentBackground, True)
                    self.control_overlay.setStyleSheet("background-color: transparent;")
                    
                    self.control_container = None
                    for i in range(self.video_player.layout().count()):
                        item = self.video_player.layout().itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            if isinstance(widget, QWidget) and widget != self.video_player.media_frame:
                                self.control_container = widget
                                break
                    
                    if self.control_container:
                        app = QApplication.instance()
                        if hasattr(app, 'settings_manager'):
                            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#2D2D2D")
                        else:
                            base_color = "#2D2D2D"
                        
                        scaled_radius = int(8 * self.video_player.dpi_scale)
                        
                        self.control_container.setStyleSheet("")
                        self.control_container.setAttribute(Qt.WA_StyledBackground, True)
                        self.control_container.setObjectName("DetachedControlBar")
                        
                        self.control_container.setStyleSheet(f"""
                            #DetachedControlBar {{
                                background-color: {base_color};
                                border: none;
                                border-radius: {scaled_radius}px;
                            }}
                        """)
                        
                        control_height = int(50 * self.video_player.dpi_scale)
                        self.control_container.setFixedHeight(control_height)
                        
                        overlay_content = QWidget(self.control_overlay)
                        overlay_content.setObjectName("ControlOverlayContent")
                        overlay_content.setStyleSheet("#ControlOverlayContent { background-color: transparent; }")
                        
                        self.control_container.setParent(overlay_content)
                        self.control_container.setGeometry(0, 0, 100, control_height)
                        
                        overlay_layout = QVBoxLayout(self.control_overlay)
                        overlay_layout.setContentsMargins(0, 0, 0, 0)
                        overlay_layout.setSpacing(0)
                        overlay_layout.addWidget(overlay_content)
                        
                        self._update_control_position()
                    
                    self.control_overlay.installEventFilter(self)

                def _on_mouse_activity(self):
                    """鼠标活动处理"""
                    if not self._hide_control_bar_visible:
                        self._show_control_bar()

                def _on_timeout_reached(self):
                    """空闲超时处理"""
                    self._hide_control_bar()

                def _show_control_bar(self):
                    """显示控制栏"""
                    if hasattr(self, 'control_overlay') and self.control_overlay:
                        self.control_overlay.show()
                        self.control_overlay.raise_()
                        self._hide_control_bar_visible = True

                def _hide_control_bar(self):
                    """隐藏控制栏"""
                    if hasattr(self, 'control_overlay') and self.control_overlay:
                        self.control_overlay.hide()
                        self._hide_control_bar_visible = False
                
                def _update_control_position(self):
                    """更新控制栏位置"""
                    if not hasattr(self, 'control_container') or not self.control_container:
                        return
                    
                    if not hasattr(self, 'control_overlay') or not self.control_overlay:
                        return
                    
                    margin = int(20 * self.video_player.dpi_scale)
                    bottom_margin = int(30 * self.video_player.dpi_scale)
                    
                    control_width = self.width() - 2 * margin
                    control_height = self.control_container.height()
                    
                    x = margin
                    y = self.height() - control_height - bottom_margin
                    
                    self.control_overlay.setGeometry(x, y, control_width, control_height)
                    self.control_container.setGeometry(0, 0, control_width, control_height)
                    
                    self.control_overlay.show()
                    self.control_overlay.raise_()
                
                def resizeEvent(self, event):
                    super().resizeEvent(event)
                    
                    if self.video_player.media_frame.parent() == self.centralWidget():
                        self.video_player.media_frame.setGeometry(self.centralWidget().rect())
                        if self.video_player.media_frame.layout():
                            self.video_player.media_frame.layout().update()
                            self.video_player.video_frame.setGeometry(self.video_player.media_frame.rect())
                    
                    self._update_control_position()
                
                def showEvent(self, event):
                    super().showEvent(event)
                    # 在窗口显示后设置 media_frame
                    self.setup_media_frame()
                    if hasattr(self, 'control_overlay') and self.control_overlay:
                        self.control_overlay.show()
                        self.control_overlay.raise_()
                        self._hide_control_bar_visible = True
                    # 启动鼠标监控
                    self.start_mouse_monitor()
                
                def closeEvent(self, event):
                    if hasattr(self, '_mouse_monitor') and self._mouse_monitor:
                        self._mouse_monitor.stop()
                    
                    if hasattr(self, 'control_overlay') and self.control_overlay:
                        self.control_overlay.close()
                    super().closeEvent(event)
                
                def moveEvent(self, event):
                    super().moveEvent(event)
                    if hasattr(self, 'control_overlay') and self.control_overlay:
                        self._update_control_position()

                def eventFilter(self, obj, event):
                    """事件过滤器 - 确保窗口始终保持活跃状态"""
                    if obj == self:
                        if event.type() == event.WindowDeactivate:
                            # 窗口失去焦点时，延迟重新激活
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(100, self._ensure_focus)
                        elif event.type() == event.WindowActivate:
                            # 窗口获得焦点时，确保在最前
                            self._ensure_on_top()
                    return super().eventFilter(obj, event)

                def _ensure_focus(self):
                    """确保分离窗口获得焦点"""
                    try:
                        if self.isVisible() and self.video_player._is_detached:
                            self.raise_()
                            self.activateWindow()
                            self._ensure_on_top()
                    except Exception as e:
                        print(f"[DetachedWindow] 确保焦点失败: {e}")

                def _ensure_on_top(self):
                    """确保窗口在最前（使用Win32 API）"""
                    try:
                        import ctypes
                        hwnd = int(self.winId())
                        # SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW = 0x0001 | 0x0002 | 0x0040
                        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0043)
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception as e:
                        print(f"[DetachedWindow] 置顶失败: {e}")

                def _on_video_double_click(self, event):
                    """双击视频区域切换全屏/退出全屏"""
                    if self.isFullScreen():
                        self.showNormal()
                        # 恢复全屏前的窗口大小
                        if hasattr(self, '_normal_geometry'):
                            self.setGeometry(self._normal_geometry)
                    else:
                        self._normal_geometry = self.geometry()
                        self.showFullScreen()

                def keyPressEvent(self, event):
                    """按键事件 - ESC退出全屏"""
                    if event.key() == Qt.Key_Escape:
                        if self.isFullScreen():
                            self.showNormal()
                            # 恢复全屏前的窗口大小
                            if hasattr(self, '_normal_geometry'):
                                self.setGeometry(self._normal_geometry)
                        else:
                            # 非全屏状态下ESC关闭窗口（合并回主窗口）
                            self.video_player._merge_window()
                    else:
                        super().keyPressEvent(event)

                def closeEvent(self, event):
                    """窗口关闭时合并回主窗口"""
                    # 标记正在关闭，防止递归调用
                    if hasattr(self, '_is_closing') and self._is_closing:
                        event.accept()
                        return
                    self._is_closing = True

                    # 先断开事件过滤器，防止在关闭过程中触发事件
                    self.removeEventFilter(self)

                    # 通知播放器合并窗口（会进行控件转移和窗口清理）
                    self.video_player._merge_from_window()

                    # 确保窗口被完全销毁
                    self.deleteLater()

                    event.accept()



            # 保存原始父容器和布局引用
            self._parent_container = self.parent()
            self._original_layout = self.layout()

            # 暂停当前播放
            if self.player_core and self._saved_playing_state:
                self.player_core.pause()

            # 清除MPV窗口绑定（在窗口操作前）
            if self.player_core:
                self.player_core.clear_window()

            # 创建并显示独立窗口
            self._detached_window = DetachedVideoWindow(self)

            # 获取屏幕几何信息
            screen = QApplication.primaryScreen().geometry()

            # 设置窗口为全屏大小（无边框最大化）
            self._detached_window.setGeometry(screen)

            # 显示独立窗口
            self._detached_window.show()

            # 更新分离状态
            self._is_detached = True

            # 更新控制栏的分离状态
            if hasattr(self, 'control_bar') and self.control_bar:
                self.control_bar.set_detached(True)
            else:
                # 向后兼容：直接更新按钮
                self._detached_button._icon_path = self._minisize_icon_path
                self._detached_button._render_icon()
                self._detached_button.update()
                self._detached_button._tooltip_text = "合并窗口"

            # 延迟重新绑定MPV播放器到新的视频窗口
            # 等待 showEvent 中的 setup_media_frame 完成
            def _delayed_bind_player():
                if not self._is_detached:
                    return
                if self.video_frame and self.player_core:
                    # 切换窗口句柄
                    self.player_core.set_window(self.video_frame.winId())
                    # 根据保存的播放状态恢复（如果之前是播放状态则恢复播放）
                    if self._saved_playing_state:
                        self.player_core.play()
                    print("[VideoPlayer] MPV播放器已重新绑定到分离窗口")

            # 使用延迟，确保窗口完全显示并设置好 media_frame 后再绑定MPV
            QTimer.singleShot(100, _delayed_bind_player)

            print("[VideoPlayer] 窗口已分离为独立窗口")

        except Exception as e:
            print(f"[VideoPlayer] 分离窗口失败: {e}")
            import traceback
            traceback.print_exc()
            self._is_detached = False

    def _merge_from_window(self):
        """
        从分离窗口中合并回主窗口
        由分离窗口的closeEvent调用，不执行窗口关闭操作
        """
        try:
            if not self._detached_window:
                return

            # 保存当前播放状态
            saved_position = self.player_core.position if self.player_core else 0
            saved_playing_state = self.player_core.is_playing if self.player_core else False
            saved_file_path = self._current_file_path

            # 暂停播放
            if self.player_core and saved_playing_state:
                self.player_core.pause()

            # 先从分离窗口中移除控件，设置父窗口为None，然后重新添加回原布局

            # 1. 处理媒体框架 - 从分离窗口的堆叠容器中移除并重新设置父窗口
            self.media_frame.setParent(None)
            self.media_frame.setParent(self)

            # 2. 获取控制容器 - 直接从分离窗口实例中获取
            control_container = getattr(self._detached_window, 'control_container', None)

            # 如果找到控制容器，从分离窗口中移除并重新设置父窗口
            if control_container:
                control_container.setParent(None)
                control_container.setParent(self)
                # 恢复控制容器的原始样式表（透明背景）
                scaled_radius = int(17.5 * self.dpi_scale)
                control_container.setStyleSheet(f"background-color: transparent; border: none; border-radius: {scaled_radius}px {scaled_radius}px {scaled_radius}px {scaled_radius}px;")
                # 重置控制容器的固定高度限制
                control_container.setFixedHeight(int(50 * self.dpi_scale))

            # 3. 将分离窗口引用置为None（在closeEvent中会调用deleteLater）
            self._detached_window = None

            # 4. 将控件重新添加回原布局
            # 确保媒体框架在原布局中
            self._original_layout.removeWidget(self.media_frame)
            self._original_layout.insertWidget(0, self.media_frame, 1)

            # 重新添加控制容器到原布局
            if control_container:
                self._original_layout.removeWidget(control_container)
                self._original_layout.addWidget(control_container)

            # 更新分离状态
            self._is_detached = False

            # 更新控制栏的分离状态
            if hasattr(self, 'control_bar') and self.control_bar:
                self.control_bar.set_detached(False)
            else:
                # 向后兼容：直接更新按钮
                self._detached_button._icon_path = self._maxsize_icon_path
                self._detached_button._render_icon()
                self._detached_button.update()
                self._detached_button._tooltip_text = "分离窗口"

            # 重新绑定MPV播放器到原来的视频窗口（只切换窗口，不重新加载媒体）
            if self.video_frame and self.player_core:
                # 切换窗口句柄
                self.player_core.set_window(self.video_frame.winId())
                # 根据保存的播放状态恢复（如果之前是播放状态则恢复播放）
                if saved_playing_state:
                    self.player_core.play()

            print("[VideoPlayer] 窗口已合并回主窗口")

        except Exception as e:
            print(f"[VideoPlayer] 从分离窗口合并失败: {e}")
            import traceback
            traceback.print_exc()

    def _merge_window(self):
        """
        将分离的窗口合并回主窗口
        继承独立窗口中的所有播放状态
        """
        try:
            if not self._detached_window:
                return

            # 保存当前播放状态
            saved_position = self.player_core.position if self.player_core else 0
            saved_playing_state = self.player_core.is_playing if self.player_core else False
            saved_file_path = self._current_file_path

            # 暂停播放
            if self.player_core and saved_playing_state:
                self.player_core.pause()

            # 先从分离窗口中移除控件，设置父窗口为None，然后重新添加回原布局
            # 这一步必须在关闭分离窗口之前完成

            # 1. 处理媒体框架 - 从分离窗口的堆叠容器中移除并重新设置父窗口
            self.media_frame.setParent(None)
            self.media_frame.setParent(self)

            # 2. 获取控制容器 - 直接从分离窗口实例中获取
            control_container = getattr(self._detached_window, 'control_container', None)

            # 如果找到控制容器，从分离窗口中移除并重新设置父窗口
            if control_container:
                control_container.setParent(None)
                control_container.setParent(self)
                # 恢复控制容器的原始样式表（透明背景）
                scaled_radius = int(17.5 * self.dpi_scale)
                control_container.setStyleSheet(f"background-color: transparent; border: none; border-radius: {scaled_radius}px {scaled_radius}px {scaled_radius}px {scaled_radius}px;")
                # 重置控制容器的固定高度限制
                control_container.setFixedHeight(int(50 * self.dpi_scale))

            # 3. 关闭独立窗口（此时控件已经安全移除）
            self._detached_window.close()
            self._detached_window = None

            # 4. 将控件重新添加回原布局
            # 确保媒体框架在原布局中
            self._original_layout.removeWidget(self.media_frame)
            self._original_layout.insertWidget(0, self.media_frame, 1)

            # 重新添加控制容器到原布局
            if control_container:
                self._original_layout.removeWidget(control_container)
                self._original_layout.addWidget(control_container)

            # 更新分离状态
            self._is_detached = False

            # 更新按钮图标为maxsize，提示文本改为"分离窗口"
            self._detached_button._icon_path = self._maxsize_icon_path
            self._detached_button._render_icon()
            self._detached_button.update()
            self._detached_button._tooltip_text = "分离窗口"

            # 重新绑定MPV播放器到原来的视频窗口（只切换窗口，不重新加载媒体）
            if self.video_frame and self.player_core:
                # 切换窗口句柄
                self.player_core.set_window(self.video_frame.winId())
                # 根据保存的播放状态恢复（如果之前是播放状态则恢复播放）
                if saved_playing_state:
                    self.player_core.play()

            print("[VideoPlayer] 窗口已合并回主窗口")

        except Exception as e:
            print(f"[VideoPlayer] 合并窗口失败: {e}")
            import traceback
            traceback.print_exc()
    
    
