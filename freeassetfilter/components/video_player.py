#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

视频播放器组件
基于MPVPlayerCore实现视频播放界面，集成PlayerControlBar控制栏
"""

import os
from typing import Optional, Any, Dict, List

try:
    from mutagen import File as mutagen_file
except ImportError:
    mutagen_file = None

try:
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.m4a import M4A
except ImportError:
    MP3 = None
    FLAC = None
    OggVorbis = None
    M4A = None

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
    QFrame, QApplication, QFileDialog
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize, QEvent
from PySide6.QtGui import QFont, QColor, QPalette, QPainter, QPen, QCursor

from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEndFileReason
from freeassetfilter.core.mpv_manager import MPVManager, MPVState
from freeassetfilter.widgets.player_control_bar import PlayerControlBar
from freeassetfilter.widgets.D_hover_menu import D_HoverMenu
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.message_box import CustomMessageBox
from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.utils.global_mouse_monitor import GlobalMouseMonitor
from freeassetfilter.utils.app_logger import info, debug, warning, error


class DetachedVideoWindow(QWidget):
    """
    独立视频窗口
    用于承载分离后的视频播放器
    """
    
    closed = Signal()  # 窗口关闭信号
    focusChanged = Signal(bool)  # 窗口焦点变化信号，True表示获得焦点，False表示失去焦点
    spacePressed = Signal()  # 空格键按下信号
    escapePressed = Signal()  # ESC键按下信号
    leftArrowPressed = Signal()  # 左方向键按下信号（后退）
    rightArrowPressed = Signal()  # 右方向键按下信号（前进）
    upArrowPressed = Signal()  # 上方向键按下信号（音量增加）
    downArrowPressed = Signal()  # 下方向键按下信号（音量减少）
    key1Pressed = Signal()  # 数字键1按下信号（1x倍速）
    key2Pressed = Signal()  # 数字键2按下信号（2x倍速）
    key3Pressed = Signal()  # 数字键3按下信号（3x倍速）
    keyTildePressed = Signal()  # ~/`键按下信号（0.5x倍速）
    
    def __init__(self, parent=None):
        """
        初始化独立视频窗口
        
        Args:
            parent: 父窗口
        """
        super().__init__(parent)
        
        self._video_player = None
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置无边框窗口
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        
        # 设置焦点策略，确保窗口可以接收键盘事件
        self.setFocusPolicy(Qt.StrongFocus)
        
        self._init_ui()
        self.setWindowTitle("视频播放器 - FreeAssetFilter")
        self.showFullScreen()  # 显示为全屏窗口

        self._cursor_hidden = False

        # 窗口显示后主动获取焦点
        self.activateWindow()
        self.setFocus()
    
    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        # 窗口显示时获取焦点
        self._force_focus()
    
    def _force_focus(self):
        """强制获取焦点"""
        self.raise_()
        self.activateWindow()
        self.setFocus()
        # 使用定时器延迟再次获取焦点，确保在窗口完全显示后焦点仍然在此
        QTimer.singleShot(100, self._delayed_focus)
    
    def _delayed_focus(self):
        """延迟获取焦点"""
        if self.isVisible():
            self.raise_()
            self.activateWindow()
            self.setFocus()
    
    def _init_ui(self):
        """初始化UI"""
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._osd_widget = QWidget()
        self._osd_widget.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._osd_widget.setAttribute(Qt.WA_TranslucentBackground)
        self._osd_widget.setAttribute(Qt.WA_ShowWithoutActivating)

        osd_main_layout = QVBoxLayout(self._osd_widget)
        osd_main_layout.setContentsMargins(0, 0, 0, 0)
        osd_main_layout.setSpacing(8)

        self._osd_label = QLabel(self._osd_widget)
        self._osd_label.setAlignment(Qt.AlignCenter)
        self._osd_label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 180);
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                font-size: 16px;
            }
        """)
        osd_main_layout.addWidget(self._osd_label)

        self._osd_progress_widget = QWidget(self._osd_widget)
        self._osd_progress_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 180);
                border-radius: 6px;
            }
        """)
        self._osd_progress_widget.hide()

        progress_layout = QHBoxLayout(self._osd_progress_widget)
        progress_layout.setContentsMargins(12, 8, 12, 8)
        progress_layout.setSpacing(12)

        self._osd_time_label = QLabel(self._osd_progress_widget)
        self._osd_time_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
        self._osd_time_label.setMinimumWidth(60)
        progress_layout.addWidget(self._osd_time_label)

        self._osd_progress_bar = D_ProgressBar(self._osd_progress_widget, is_interactive=False)
        self._osd_progress_bar.setRange(0, 1000)
        self._osd_progress_bar.set_progress_color(QColor(255, 255, 255))
        self._osd_progress_bar.set_track_color(QColor(255, 255, 255, 128))
        progress_layout.addWidget(self._osd_progress_bar)

        self._osd_duration_label = QLabel(self._osd_progress_widget)
        self._osd_duration_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
        self._osd_duration_label.setMinimumWidth(60)
        self._osd_duration_label.setAlignment(Qt.AlignRight)
        progress_layout.addWidget(self._osd_duration_label)

        osd_main_layout.addWidget(self._osd_progress_widget)

        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.timeout.connect(self._hide_osd)

    def set_video_player(self, video_player: 'VideoPlayer'):
        """设置视频播放器"""
        self._video_player = video_player
        if self._main_layout:
            self._main_layout.addWidget(video_player)
    
    def focusInEvent(self, event):
        """窗口获得焦点事件"""
        super().focusInEvent(event)
        self.focusChanged.emit(True)
    
    def focusOutEvent(self, event):
        """窗口失去焦点事件"""
        super().focusOutEvent(event)
        self.focusChanged.emit(False)
    
    def keyPressEvent(self, event):
        """键盘按下事件处理"""
        if event.key() == Qt.Key_Space:
            self.spacePressed.emit()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            event.accept()
        elif event.key() == Qt.Key_Left:
            self.leftArrowPressed.emit()
            event.accept()
        elif event.key() == Qt.Key_Right:
            self.rightArrowPressed.emit()
            event.accept()
        elif event.key() == Qt.Key_Up:
            self.upArrowPressed.emit()
            event.accept()
        elif event.key() == Qt.Key_Down:
            self.downArrowPressed.emit()
            event.accept()
        elif event.key() == Qt.Key_1:
            self.key1Pressed.emit()
            event.accept()
        elif event.key() == Qt.Key_2:
            self.key2Pressed.emit()
            event.accept()
        elif event.key() == Qt.Key_3:
            self.key3Pressed.emit()
            event.accept()
        elif event.key() == Qt.Key_QuoteLeft:  # `键
            self.keyTildePressed.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def set_cursor_visible(self, visible: bool):
        """
        设置鼠标指针可见性

        Args:
            visible: True 显示指针，False 隐藏指针
        """
        if visible:
            if self._cursor_hidden:
                self.unsetCursor()
                self._cursor_hidden = False
        else:
            if not self._cursor_hidden:
                self.setCursor(Qt.BlankCursor)
                self._cursor_hidden = True

    def show_cursor(self):
        """显示鼠标指针"""
        self.set_cursor_visible(True)

    def hide_cursor(self):
        """隐藏鼠标指针"""
        self.set_cursor_visible(False)

    def reset_cursor(self):
        """重置鼠标指针为默认状态（显示）"""
        self.set_cursor_visible(True)

    def show_osd(self, message: str, duration: int = 2000):
        """
        显示OSD状态信息

        Args:
            message: 要显示的消息
            duration: 显示持续时间（毫秒），默认2000ms
        """
        self._osd_progress_widget.hide()
        self._osd_label.setText(message)
        self._osd_label.show()
        self._osd_label.adjustSize()

        screen_geometry = self.geometry()
        x = (screen_geometry.width() - self._osd_label.width()) // 2
        y = int(30 * self.dpi_scale)

        self._osd_widget.setFixedSize(self._osd_label.width(), self._osd_label.height())
        self._osd_widget.move(x, y)
        self._osd_widget.show()
        self._osd_timer.start(duration)

    def show_seek_osd(self, current_time: float, duration: float, direction: str, duration_ms: int = 2000):
        """
        显示跳转进度OSD

        Args:
            current_time: 当前播放位置（秒）
            duration: 总时长（秒）
            direction: 跳转方向，"forward" 或 "backward"
            duration_ms: 显示持续时间（毫秒），默认2000ms
        """
        self._osd_label.hide()

        current_str = self._format_time(current_time)
        duration_str = self._format_time(duration)

        self._osd_time_label.setText(current_str)
        self._osd_duration_label.setText(duration_str)

        if duration > 0:
            progress = int((current_time / duration) * 1000)
            self._osd_progress_bar.setValue(progress)
        else:
            self._osd_progress_bar.setValue(0)

        direction_text = "+5s" if direction == "forward" else "-5s"
        self._osd_time_label.setText(f"{direction_text}  {current_str}")

        self._osd_progress_widget.show()
        self._osd_progress_widget.adjustSize()

        screen_geometry = self.geometry()
        x = (screen_geometry.width() - self._osd_progress_widget.width()) // 2
        y = int(30 * self.dpi_scale)

        self._osd_widget.setFixedSize(self._osd_progress_widget.width(), self._osd_progress_widget.height())
        self._osd_widget.move(x, y)
        self._osd_widget.show()
        self._osd_timer.start(duration_ms)

    def _format_time(self, seconds: float) -> str:
        """
        格式化时间显示

        Args:
            seconds: 秒数

        Returns:
            str: 格式化的时间字符串 "HH:MM:SS" 或 "MM:SS"
        """
        if seconds <= 0:
            return "00:00"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def _hide_osd(self):
        """隐藏OSD"""
        self._osd_widget.hide()
        self._osd_label.show()
        self._osd_progress_widget.hide()

    def closeEvent(self, event):
        """窗口关闭事件"""
        self._hide_osd()
        self.closed.emit()
        super().closeEvent(event)
    



class VideoPlaceholder(QWidget):
    """
    视频占位符控件
    在没有加载视频时显示提示信息
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._message = "拖放视频文件到此处\n或使用文件选择器加载"
        self._setup_ui()
    
    def _setup_ui(self):
        """设置UI"""
        self.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        
        self._label = QLabel(self._message)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            "color: #666; font-size: 14px; background-color: transparent;"
        )
        layout.addWidget(self._label)
    
    def set_message(self, message: str):
        """设置提示消息"""
        self._message = message
        self._label.setText(message)
    
    def paintEvent(self, event):
        """绘制事件"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        pen = QPen(QColor("#333"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        
        margin = 20
        rect = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.drawRoundedRect(rect, 10, 10)


class VideoPlayer(QWidget):
    """
    视频播放器组件
    
    集成MPVPlayerCore和PlayerControlBar，提供完整的视频播放功能：
    - 视频渲染区域（嵌入MPV窗口）
    - 播放控制栏（播放/暂停、进度条、音量、速度等）
    - 文件加载和播放状态管理
    - 与主窗口的信号通信
    
    Signals:
        fileLoaded: 文件加载完成信号 (file_path: str)
        fileEnded: 文件播放结束信号
        errorOccurred: 错误发生信号 (error_message: str)
        idle_event: 空闲事件信号，用于异常检测
    """

    VIDEO_MODE = "video"
    AUDIO_MODE = "audio"

    fileLoaded = Signal(str, bool)  # 文件路径, 是否为音频文件
    fileEnded = Signal()
    errorOccurred = Signal(str)
    idle_event = Signal()
    
    def __init__(self, parent=None, show_lut_controls: bool = True, show_detach_button: bool = True, playback_mode: str = "video", initial_volume: int = None, initial_speed: float = None, control_bar_border_radius: int = None):
        """
        初始化视频播放器
        
        Args:
            parent: 父窗口部件
            show_lut_controls: 是否显示LUT相关控制按钮
            show_detach_button: 是否显示分离窗口按钮
            playback_mode: 播放模式，"video" 或 "audio"
            initial_volume: 初始音量值 (0-100)，None表示从设置读取
            initial_speed: 初始倍速值，None表示从设置读取
            control_bar_border_radius: 浮动控制栏圆角半径（像素），None表示使用默认值4像素
        """
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        self._current_file: str = ""
        self._playback_mode = playback_mode  # 播放模式：video 或 audio

        self._user_interacting = False
        self._pending_seek_value: Optional[int] = None
        
        # 分离窗口相关变量
        self._detached_window: Optional[DetachedVideoWindow] = None
        self._original_parent = parent  # 保存原始父窗口引用
        
        # 浮动控制栏相关
        self._floating_control_bar: Optional[D_HoverMenu] = None
        self._is_floating_mode = False  # 是否处于浮动模式
        self._control_bar_border_radius = control_bar_border_radius  # 浮动控制栏圆角半径
        self._cursor_activity_monitor: Optional[GlobalMouseMonitor] = None  # 分离窗口鼠标指针自动隐藏监控

        # MPV管理器实例（单例）
        self._mpv_manager: Optional[MPVManager] = None
        self._video_widget: Optional[QWidget] = None
        self._is_mpv_embedded = False
        self._component_id = f"video_player_{id(self)}"  # 组件唯一标识

        # 音频封面数据
        self._current_audio_cover: Optional[bytes] = None  # 当前音频文件的封面数据

        # 字幕状态缓存
        self._subtitle_state_cache: Dict[str, Any] = self._get_empty_subtitle_state()
        self._subtitle_track_dialog: Optional[CustomMessageBox] = None
        self._auto_subtitle_extensions = {
            ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".ttml",
            ".dfxp", ".smi", ".sami", ".rt", ".txt", ".sup", ".mpl", ".mks"
        }

        # 进度同步定时器
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(200)  # 每200ms同步一次
        self._sync_timer.timeout.connect(self._sync_progress_from_player)

        # 初始化设置管理器并读取初始设置
        # 从 QApplication 实例获取 SettingsManager，如果不存在则创建新实例
        app = QApplication.instance()
        if app and hasattr(app, 'settings_manager'):
            self._settings_manager = app.settings_manager
        else:
            self._settings_manager = SettingsManager()
        
        # 从设置管理器读取控制栏按钮可见性设置
        self._show_lut_controls = self._settings_manager.get_setting("player.control_bar_show_lut", False)
        self._show_detach_button = self._settings_manager.get_setting("player.control_bar_show_fullscreen", True)
        
        self._initial_volume = initial_volume if initial_volume is not None else self._settings_manager.get_player_volume()
        self._initial_speed = initial_speed if initial_speed is not None else self._settings_manager.get_player_speed()

        self._init_ui()
        self._init_mpv_manager()
        self._connect_signals()
        self._apply_player_settings()
        # 立即启动进度同步定时器
        if not self._sync_timer.isActive():
            self._sync_timer.start()
    
    def _init_ui(self):
        """初始化用户界面"""
        self.setStyleSheet("background-color: transparent;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        if self._playback_mode == self.VIDEO_MODE:
            self._init_video_mode_ui(main_layout)
        else:
            self._init_audio_mode_ui(main_layout)
        
        self._control_bar = PlayerControlBar(
            self, 
            show_lut_controls=self._show_lut_controls
        )
        self._control_bar.set_detach_button_visible(self._show_detach_button)
        main_layout.addWidget(self._control_bar)
        
        # 初始化浮动控制栏
        self._init_floating_control_bar()
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
    def _init_floating_control_bar(self):
        """初始化浮动控制栏"""
        # 不在这里初始化，而是在需要时动态设置
        self._floating_control_bar = None

    def _get_cursor_timeout_duration(self) -> int:
        """获取分离窗口鼠标指针自动隐藏超时时间（毫秒）"""
        timeout_seconds = self._settings_manager.get_setting("player.control_bar_timeout", 3)
        try:
            timeout_ms = int(float(timeout_seconds) * 1000)
        except (TypeError, ValueError):
            timeout_ms = 3000
        return max(1000, timeout_ms)

    def _ensure_cursor_activity_monitor(self):
        """确保分离窗口鼠标指针活动监控器已创建"""
        if self._cursor_activity_monitor is None:
            self._cursor_activity_monitor = GlobalMouseMonitor(
                self,
                timeout=self._get_cursor_timeout_duration()
            )
            self._cursor_activity_monitor.mouse_moved.connect(self._on_cursor_activity)
            self._cursor_activity_monitor.mouse_clicked.connect(self._on_cursor_activity)
            self._cursor_activity_monitor.mouse_scrolled.connect(self._on_cursor_activity)
            self._cursor_activity_monitor.timeout_reached.connect(self._on_cursor_hide_timeout)
        else:
            self._cursor_activity_monitor.timeout = self._get_cursor_timeout_duration()

    def _start_cursor_auto_hide_monitor(self):
        """启动分离窗口鼠标指针自动隐藏监控"""
        if not self._detached_window:
            return

        self._ensure_cursor_activity_monitor()

        if self._cursor_activity_monitor:
            self._cursor_activity_monitor.timeout = self._get_cursor_timeout_duration()
            self._detached_window.show_cursor()
            if not self._cursor_activity_monitor.is_monitoring():
                self._cursor_activity_monitor.start()
            self._cursor_activity_monitor.reset_timer()
            debug(f"[VideoPlayer] 鼠标指针自动隐藏监控已启动，超时: {self._cursor_activity_monitor.timeout}ms")

    def _stop_cursor_auto_hide_monitor(self):
        """停止分离窗口鼠标指针自动隐藏监控"""
        if self._cursor_activity_monitor and self._cursor_activity_monitor.is_monitoring():
            self._cursor_activity_monitor.stop()
            debug(f"[VideoPlayer] 鼠标指针自动隐藏监控已停止")

        if self._detached_window:
            self._detached_window.show_cursor()

    def _is_cursor_inside_detached_window(self) -> bool:
        """检查当前鼠标位置是否位于分离窗口范围内"""
        if not self._detached_window or not self._detached_window.isVisible():
            return False

        global_pos = QCursor.pos()
        return self._detached_window.frameGeometry().contains(global_pos)

    @Slot()
    def _on_cursor_activity(self):
        """处理分离窗口鼠标活动：显示鼠标指针并重置超时计时"""
        if not self._detached_window or not self._detached_window.isVisible():
            return

        if not self._is_cursor_inside_detached_window():
            return

        self._detached_window.show_cursor()
        if self._cursor_activity_monitor and self._cursor_activity_monitor.is_monitoring():
            self._cursor_activity_monitor.reset_timer()

    @Slot()
    def _on_cursor_hide_timeout(self):
        """处理分离窗口鼠标指针自动隐藏超时"""
        if not self._detached_window or not self._detached_window.isVisible():
            return

        self._detached_window.hide_cursor()
        debug(f"[VideoPlayer] 鼠标指针超时自动隐藏")

    def _switch_to_floating_mode(self):
        """切换到浮动控制栏模式"""
        if self._is_floating_mode:
            return
        
        debug(f"[VideoPlayer] 切换到浮动控制栏模式")
        self._is_floating_mode = True
        
        # 从原布局中移除控制栏
        main_layout = self.layout()
        if main_layout:
            main_layout.removeWidget(self._control_bar)
        
        # 创建浮动控制栏（以分离窗口为父窗口）
        # 注意：不使用子控件模式，因为MPV原生窗口可能会覆盖子控件
        parent_widget = self._detached_window if self._detached_window else self
        self._floating_control_bar = D_HoverMenu(
            parent_widget, 
            position=D_HoverMenu.Position_Bottom,
            stay_on_top=False,  # 禁用强制置顶
            hide_on_window_move=False,  # 窗口移动时不隐藏
            use_sub_widget_mode=False,  # 不使用子控件模式，使用独立窗口模式
            fill_width=True,  # 横向填充整个显示区域
            margin=30,  # 添加30像素的外边距
            border_radius=self._control_bar_border_radius if self._control_bar_border_radius is not None else 8  # 圆角半径
        )
        self._floating_control_bar.set_content(self._control_bar)

        # 根据设置决定是否启用鼠标移动检测（经典模式），需要在启用自动隐藏之前设置
        use_classic_mode = self._settings_manager.get_setting("player.fullscreen_classic_control_bar", True)
        self._floating_control_bar.set_mouse_move_detection(use_classic_mode)

        # 设置控制栏超时隐藏时间
        control_bar_timeout = self._settings_manager.get_setting("player.control_bar_timeout", 3)
        self._floating_control_bar.set_timeout_duration(control_bar_timeout * 1000)

        self._floating_control_bar.set_auto_hide_enabled(True)  # 启用自动隐藏功能

        # 连接浮动控制栏的键盘事件信号
        self._floating_control_bar.keyPressed.connect(self._on_floating_control_bar_key_pressed)

        # 连接浮动控制栏的显示/隐藏信号到鼠标指针控制
        self._floating_control_bar.controlBarShown.connect(self._on_control_bar_shown)
        self._floating_control_bar.controlBarHidden.connect(self._on_control_bar_hidden)

        # 获取屏幕尺寸并直接设置目标矩形区域
        # 分离窗口是全屏的，使用屏幕几何信息更可靠
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.geometry()
            # 设置目标矩形为整个屏幕（控制栏会显示在底部）
            self._floating_control_bar.set_target_rect(screen_geometry)
            debug(f"[VideoPlayer] 使用屏幕尺寸设置控制栏位置: {screen_geometry.width()}x{screen_geometry.height()}")
        elif hasattr(self, '_video_surface'):
            # 备用方案：使用视频渲染区域
            self._floating_control_bar.set_target_widget(self._video_surface)
        
        # 显示浮动控制栏
        self._floating_control_bar.show()

        # 显示浮动控制栏后，确保焦点回到分离窗口
        if self._detached_window:
            self._detached_window.activateWindow()
            self._detached_window.setFocus()
    
    def _switch_to_fixed_mode(self):
        """切换回固定控制栏模式"""
        if not self._is_floating_mode:
            return
        
        debug(f"[VideoPlayer] 切换到固定控制栏模式")
        self._is_floating_mode = False
        
        # 隐藏浮动控制栏
        if self._floating_control_bar:
            self._floating_control_bar.set_auto_hide_enabled(False)
            self._floating_control_bar.hide()
            # 从浮动控制栏中移除内容
            self._floating_control_bar.clear_content()
            self._floating_control_bar.deleteLater()
            self._floating_control_bar = None
        
        # 将控制栏添加回原布局
        main_layout = self.layout()
        if main_layout:
            main_layout.addWidget(self._control_bar)
        
        self._control_bar.show()
    
    def _init_video_mode_ui(self, main_layout: QVBoxLayout):
        """初始化视频模式UI布局"""
        video_container = QWidget()
        video_container.setStyleSheet("background-color: transparent;")
        
        video_layout = QVBoxLayout(video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        
        self._video_surface = QWidget()
        self._video_surface.setStyleSheet("background-color: transparent;")
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._video_surface.setAttribute(Qt.WA_NativeWindow)
        # 禁用视频表面的焦点，让父窗口处理键盘事件
        self._video_surface.setFocusPolicy(Qt.NoFocus)
        self._video_surface.installEventFilter(self)
        video_layout.addWidget(self._video_surface)
        
        main_layout.addWidget(video_container, 1)
    
    def _init_audio_mode_ui(self, main_layout: QVBoxLayout):
        """初始化音频模式UI布局"""
        from freeassetfilter.widgets.audio_background import AudioBackground
        
        audio_container = QWidget()
        audio_container.setStyleSheet("background-color: transparent;")
        
        audio_layout = QVBoxLayout(audio_container)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        
        self._audio_background = AudioBackground(self)
        audio_layout.addWidget(self._audio_background)
        
        self._video_surface = None
        
        main_layout.addWidget(audio_container, 1)
    
    def _init_mpv_manager(self):
        """初始化MPV管理器"""
        self._mpv_manager = MPVManager()
        # 注册组件到管理器
        self._mpv_manager.register_component(
            self._component_id,
            "VideoPlayer"
        )
        # 连接管理器信号
        self._connect_manager_signals()

    def _destroy_mpv_manager(self):
        """
        销毁MPV管理器引用
        注意：由于是单例模式，这里只是断开信号并注销组件，不会真正销毁管理器
        """
        debug(f"[VideoPlayer] 开始清理MPV管理器...")
        if self._mpv_manager:
            # 断开所有信号连接
            self._disconnect_manager_signals()
            # 注销组件
            self._mpv_manager.unregister_component(self._component_id)
            self._mpv_manager = None
            debug(f"[VideoPlayer] MPV管理器引用已清理")
        else:
            debug(f"[VideoPlayer] MPV管理器不存在，无需清理")

    def _connect_signals(self):
        """连接信号和槽"""
        self._control_bar.playPauseClicked.connect(self._on_play_pause_clicked)
        self._control_bar.progressChanged.connect(self._on_progress_changed)
        self._control_bar.userInteractStarted.connect(self._on_user_interact_started)
        self._control_bar.userInteractEnded.connect(self._on_user_interact_ended)
        self._control_bar.volumeChanged.connect(self._on_volume_changed)
        self._control_bar.muteChanged.connect(self._on_mute_changed)
        self._control_bar.speedChanged.connect(self._on_speed_changed)
        self._control_bar.lutSelected.connect(self._on_lut_selected)
        self._control_bar.lutCleared.connect(self._on_lut_cleared)
        self._control_bar.subtitleClicked.connect(self._on_subtitle_clicked)
        self._control_bar.detachClicked.connect(self._on_detach_clicked)
        self._control_bar.keyPressed.connect(self._on_control_bar_key_pressed)
        
    def _connect_manager_signals(self):
        """连接MPV管理器信号"""
        if self._mpv_manager:
            self._mpv_manager.stateChanged.connect(self._on_manager_state_changed)
            self._mpv_manager.positionChanged.connect(self._on_manager_position_changed)
            self._mpv_manager.volumeChanged.connect(self._on_manager_volume_changed)
            self._mpv_manager.mutedChanged.connect(self._on_manager_muted_changed)
            self._mpv_manager.speedChanged.connect(self._on_manager_speed_changed)
            self._mpv_manager.fileLoaded.connect(self._on_manager_file_loaded)
            self._mpv_manager.fileEnded.connect(self._on_manager_file_ended)
            self._mpv_manager.errorOccurred.connect(self._on_manager_error)
    
    def _disconnect_manager_signals(self):
        """断开MPV管理器信号"""
        if self._mpv_manager:
            try:
                self._mpv_manager.stateChanged.disconnect(self._on_manager_state_changed)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 stateChanged 信号时出错: {e}")
            try:
                self._mpv_manager.positionChanged.disconnect(self._on_manager_position_changed)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 positionChanged 信号时出错: {e}")
            try:
                self._mpv_manager.volumeChanged.disconnect(self._on_manager_volume_changed)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 volumeChanged 信号时出错: {e}")
            try:
                self._mpv_manager.mutedChanged.disconnect(self._on_manager_muted_changed)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 mutedChanged 信号时出错: {e}")
            try:
                self._mpv_manager.speedChanged.disconnect(self._on_manager_speed_changed)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 speedChanged 信号时出错: {e}")
            try:
                self._mpv_manager.fileLoaded.disconnect(self._on_manager_file_loaded)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 fileLoaded 信号时出错: {e}")
            try:
                self._mpv_manager.fileEnded.disconnect(self._on_manager_file_ended)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 fileEnded 信号时出错: {e}")
            try:
                self._mpv_manager.errorOccurred.disconnect(self._on_manager_error)
            except (RuntimeError, TypeError) as e:
                debug(f"[VideoPlayer] 断开 errorOccurred 信号时出错: {e}")
    
    def _apply_player_settings(self):
        """
        应用播放器设置
        使用初始化时读取的初始值应用到播放器组件
        注意：此方法只在控制栏上设置显示值，不实际应用到MPV核心
        MPV核心的设置将在 _embed_mpv_window 中完成
        """
        # 只在控制栏上设置显示值（不发射信号，避免触发保存）
        self._control_bar.set_volume(self._initial_volume, emit_signal=False)
        self._control_bar.set_speed(self._initial_speed, emit_signal=False)
    
    def _embed_mpv_window(self):
        """将MPV窗口嵌入到视频渲染区域"""
        if self._is_mpv_embedded or not self._mpv_manager:
            return
        
        # 初始化MPV管理器
        if not self._mpv_manager.initialize():
            self.errorOccurred.emit("无法初始化MPV播放器")
            return
        
        # 音频模式不需要嵌入MPV窗口，但同样需要应用初始设置
        if self._playback_mode == self.AUDIO_MODE:
            self._is_mpv_embedded = True
            # 应用初始设置（音量和倍速）
            self._mpv_manager.set_volume(self._initial_volume, component_id=self._component_id)
            self._mpv_manager.set_speed(self._initial_speed, component_id=self._component_id)
            return
        
        # 确保视频渲染区域有正确的窗口属性
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self._video_surface.setAttribute(Qt.WA_NativeWindow, True)
        
        # 确保视频渲染区域可见
        if not self._video_surface.isVisible():
            self._video_surface.show()
        
        # 获取窗口ID
        win_id = int(self._video_surface.winId())
        debug(f"[VideoPlayer] 视频渲染窗口ID: {win_id}")
        
        if self._mpv_manager.set_window_id(win_id, component_id=self._component_id):
            self._is_mpv_embedded = True
            # 嵌入后立即同步几何尺寸
            self._sync_mpv_geometry()
            # 嵌入后立即应用初始设置（音量和倍速）
            self._mpv_manager.set_volume(self._initial_volume, component_id=self._component_id)
            self._mpv_manager.set_speed(self._initial_speed, component_id=self._component_id)
    
    def _reconnect_mpv_window(self):
        """
        重新连接MPV窗口到新的渲染区域
        用于窗口分离/恢复时，只重新设置窗口ID，不重置MPV内核
        """
        if not self._mpv_manager:
            return
        
        debug(f"[VideoPlayer] 重新连接MPV窗口")
        
        # 确保视频渲染区域有正确的窗口属性
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self._video_surface.setAttribute(Qt.WA_NativeWindow, True)
        
        # 确保视频渲染区域可见
        if not self._video_surface.isVisible():
            self._video_surface.show()
        
        # 重新获取窗口ID
        win_id = int(self._video_surface.winId())
        debug(f"[VideoPlayer] 新视频渲染窗口ID: {win_id}")
        
        # 重新设置窗口ID
        if self._mpv_manager.set_window_id(win_id, component_id=self._component_id):
            debug(f"[VideoPlayer] MPV窗口重新连接成功")
            # 同步几何尺寸
            self._sync_mpv_geometry()
    
    def _on_play_pause_clicked(self):
        """播放/暂停按钮点击处理"""
        if not self._mpv_manager:
            return

        if self._mpv_manager.is_playing():
            self.pause()
        else:
            self.play()
    
    def _on_progress_changed(self, value: int):
        """进度条值变化处理"""
        if self._user_interacting and self._mpv_manager and self._mpv_manager.is_initialized():
            duration = self._mpv_manager.get_duration() or 0
            if duration > 0:
                position = (value / 1000.0) * duration
                self._mpv_manager.seek(position, component_id=self._component_id)
                self._update_time_display(position, duration)
        self._pending_seek_value = value
    
    def _on_user_interact_started(self):
        """用户开始与进度条交互"""
        self._user_interacting = True
    
    def _on_user_interact_ended(self):
        """用户结束与进度条交互"""
        self._user_interacting = False
    
    def _on_volume_changed(self, volume: int):
        """
        音量变化处理（用户通过控制栏调整时触发）
        
        Args:
            volume: 新的音量值 (0-100)
        """
        if self._mpv_manager:
            self._mpv_manager.set_volume(volume, component_id=self._component_id)
        # 保存音量设置到 last_volume（仅在用户调整时保存）
        if self._settings_manager:
            self._settings_manager.save_player_volume(volume)
    
    def _on_mute_changed(self, muted: bool):
        """静音状态变化处理"""
        if self._mpv_manager:
            self._mpv_manager.set_muted(muted, component_id=self._component_id)

    def _on_manager_state_changed(self, state: MPVState):
        """
        MPV管理器状态变化处理

        Args:
            state: 新的MPV状态
        """
        debug(f"[VideoPlayer] MPV状态变化: playing={state.is_playing}, paused={state.is_paused}")
        # 根据状态更新控制栏
        if state.is_playing and not state.is_paused:
            self._control_bar.set_playing(True)
        else:
            self._control_bar.set_playing(False)

    def _on_manager_position_changed(self, position: float, duration: float):
        """
        MPV管理器位置变化处理

        Args:
            position: 当前播放位置（秒）
            duration: 总时长（秒）
        """
        # 使用set_position方法同步进度和时间显示
        self._control_bar.set_position(position, duration)

    def _on_manager_volume_changed(self, volume: int):
        """
        MPV管理器音量变化处理

        Args:
            volume: 新的音量值 (0-100)
        """
        # 同步更新控制栏显示（不发射信号，避免循环）
        self._control_bar.set_volume(volume, emit_signal=False)

    def _on_manager_muted_changed(self, muted: bool):
        """
        MPV管理器静音状态变化处理

        Args:
            muted: 是否静音
        """
        # 同步更新控制栏显示（不发射信号，避免循环）
        self._control_bar.set_muted(muted)

    def _on_manager_speed_changed(self, speed: float):
        """
        MPV管理器播放速度变化处理

        Args:
            speed: 新的播放倍速
        """
        # 同步更新控制栏显示（不发射信号，避免循环）
        self._control_bar.set_speed(speed, emit_signal=False)

    def _sync_progress_from_player(self):
        """
        从播放器主动同步进度和状态到控制栏
        每200ms执行一次，确保进度条和时间标签显示准确
        """
        if not self._mpv_manager or self._user_interacting:
            return

        try:
            # 使用节流机制，减少不必要的UI更新
            import time
            current_time = time.time() * 1000
            if hasattr(self, '_last_sync_time') and (current_time - self._last_sync_time) < 100:
                return
            self._last_sync_time = current_time

            # 直接从MPVPlayerCore获取最新数据，不经过队列
            position = self._mpv_manager.get_position_direct()
            duration = self._mpv_manager.get_duration_direct()
            is_playing = self._mpv_manager.is_playing()
            is_paused = self._mpv_manager.is_paused()

            # 只有当值有变化时才更新UI
            last_pos = getattr(self, '_last_sync_position', None)
            last_dur = getattr(self, '_last_sync_duration', None)

            if position != last_pos or duration != last_dur:
                self._last_sync_position = position
                self._last_sync_duration = duration

                # 只有当duration有效时才更新
                if duration is not None and duration > 0 and position is not None:
                    self._control_bar.set_position(position, duration)
                elif position is not None:
                    # 即使duration无效也更新位置
                    self._control_bar.set_position(position, duration or 0)

            # 同步播放状态
            self._control_bar.set_playing(is_playing and not is_paused)

        except Exception as e:
            # 同步失败时不影响播放，仅记录日志
            warning(f"[VideoPlayer] 同步进度时出错: {e}")

    def _initialize_progress_display(self):
        """
        初始化进度显示
        文件加载后延迟调用，确保MPV已准备好时长信息
        """
        if not self._mpv_manager:
            return

        try:
            duration = self._mpv_manager.get_duration()
            position = self._mpv_manager.get_position()

            if duration is not None and duration > 0:
                self._control_bar.set_position(position or 0, duration)
                debug(f"[VideoPlayer] 初始化进度显示: position={position}, duration={duration}")
            else:
                QTimer.singleShot(200, self._initialize_progress_display)
        except Exception as e:
            warning(f"[VideoPlayer] 初始化进度显示失败: {e}")

    def _get_empty_subtitle_state(self) -> Dict[str, Any]:
        """获取默认的空字幕状态"""
        return {
            "has_available_subtitles": False,
            "has_embedded_subtitles": False,
            "has_external_subtitles": False,
            "is_subtitle_visible": False,
            "has_active_subtitle": False,
            "selected_track_id": None,
            "selected_track": None,
            "selected_track_external": False,
            "tracks": [],
        }

    def _reset_subtitle_state(self):
        """重置字幕状态缓存和按钮样式"""
        self._subtitle_state_cache = self._get_empty_subtitle_state()
        if hasattr(self, '_control_bar'):
            self._control_bar.set_subtitle_loaded(False)

    def _close_subtitle_track_dialog(self):
        """关闭字幕轨选择弹窗"""
        if self._subtitle_track_dialog:
            try:
                self._subtitle_track_dialog.close()
                self._subtitle_track_dialog.deleteLater()
            except RuntimeError:
                pass
            finally:
                self._subtitle_track_dialog = None

    def _get_embedded_subtitle_tracks(self, state: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """获取当前可用的内嵌字幕轨"""
        subtitle_state = state or self._subtitle_state_cache or self._get_empty_subtitle_state()
        tracks = subtitle_state.get("tracks") or []
        return [
            track for track in tracks
            if isinstance(track, dict) and not bool(track.get("external"))
        ]

    def _format_subtitle_track_label(self, track: Dict[str, Any], index: int) -> str:
        """格式化字幕轨显示文本"""
        if track.get("title"):
            title = str(track.get("title"))
        elif track.get("external_filename"):
            title = os.path.basename(str(track.get("external_filename")))
        elif track.get("lang"):
            title = f"字幕轨 {index + 1}"
        else:
            title = f"字幕轨 {track.get('id', index + 1)}"

        meta_parts = []
        if track.get("lang"):
            meta_parts.append(str(track.get("lang")).upper())
        meta_parts.append("外挂" if track.get("external") else "内嵌")
        if track.get("selected"):
            meta_parts.append("当前")

        return f"{title}（{' / '.join(meta_parts)}）" if meta_parts else title

    def _refresh_subtitle_state(self) -> Dict[str, Any]:
        """刷新字幕状态缓存并同步控制栏按钮样式"""
        default_state = self._get_empty_subtitle_state()

        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            self._subtitle_state_cache = default_state
            if hasattr(self, '_control_bar'):
                self._control_bar.set_subtitle_loaded(False)
            return default_state

        state = self._mpv_manager.get_subtitle_state()
        if not isinstance(state, dict):
            state = default_state
        else:
            merged_state = default_state.copy()
            merged_state.update(state)
            state = merged_state

        self._subtitle_state_cache = state

        is_subtitle_loaded = bool(
            state.get("has_active_subtitle") and state.get("is_subtitle_visible")
        )
        if hasattr(self, '_control_bar'):
            self._control_bar.set_subtitle_loaded(is_subtitle_loaded)

        return state

    def _find_matching_subtitle_file(self, video_path: str) -> Optional[str]:
        """查找与当前视频同目录、同名不同后缀的字幕文件"""
        if not video_path:
            return None

        base_dir = os.path.dirname(video_path)
        video_stem, video_ext = os.path.splitext(os.path.basename(video_path))
        video_ext = video_ext.lower()

        if not base_dir or not os.path.isdir(base_dir):
            return None

        try:
            candidates = []
            for entry in os.listdir(base_dir):
                entry_path = os.path.join(base_dir, entry)
                if not os.path.isfile(entry_path):
                    continue

                stem, ext = os.path.splitext(entry)
                ext = ext.lower()
                if stem != video_stem:
                    continue
                if ext == video_ext:
                    continue
                if ext not in self._auto_subtitle_extensions:
                    continue

                candidates.append(entry_path)

            if not candidates:
                return None

            candidates.sort()
            return candidates[0]
        except Exception as e:
            warning(f"[VideoPlayer] 自动匹配外挂字幕失败: {e}")
            return None

    def _load_subtitle_path(self, subtitle_path: str, show_osd: bool = True, emit_error: bool = True) -> bool:
        """加载指定字幕文件路径"""
        if not subtitle_path or not self._mpv_manager:
            return False

        success = self._mpv_manager.load_subtitle(
            subtitle_path,
            component_id=self._component_id
        )

        if success:
            info(f"[VideoPlayer] 外部字幕加载成功: {subtitle_path}")
            self._refresh_subtitle_state()
            QTimer.singleShot(100, self._refresh_subtitle_state)
            if show_osd and self._detached_window:
                self._detached_window.show_osd("字幕已加载")
        else:
            error(f"[VideoPlayer] 外部字幕加载失败: {subtitle_path}")
            if emit_error:
                self.errorOccurred.emit("字幕加载失败")

        return success

    def _try_auto_load_matching_subtitle(self):
        """尝试自动加载与当前视频同名的外挂字幕"""
        if not self._current_file or self._playback_mode != self.VIDEO_MODE:
            return

        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            return

        subtitle_state = self._refresh_subtitle_state()
        if subtitle_state.get("has_available_subtitles"):
            return

        matched_subtitle = self._find_matching_subtitle_file(self._current_file)
        if not matched_subtitle:
            return

        success = self._load_subtitle_path(
            matched_subtitle,
            show_osd=True,
            emit_error=False
        )
        if success:
            info(f"[VideoPlayer] 已自动加载同名外挂字幕: {matched_subtitle}")

    def _open_external_subtitle_picker(self) -> bool:
        """打开外部字幕文件选择器并加载字幕"""
        initial_dir = os.path.dirname(self._current_file) if self._current_file else ""
        subtitle_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字幕文件",
            initial_dir,
            "字幕文件 (*.srt *.ass *.ssa *.sub *.idx *.vtt *.ttml *.dfxp *.smi *.sami *.rt *.txt *.sup *.mpl *.mks);;所有文件 (*.*)"
        )

        if not subtitle_path:
            return False

        return self._load_subtitle_path(subtitle_path)

    def _open_subtitle_track_dialog(self, state: Optional[Dict[str, Any]] = None):
        """打开内嵌字幕轨选择弹窗"""
        subtitle_state = state or self._refresh_subtitle_state()
        embedded_tracks = self._get_embedded_subtitle_tracks(subtitle_state)

        if not embedded_tracks:
            self._open_external_subtitle_picker()
            return

        self._close_subtitle_track_dialog()

        dialog = CustomMessageBox(self)
        self._subtitle_track_dialog = dialog
        dialog.set_title("选择字幕轨")
        dialog.set_text("请选择当前视频要使用的内置字幕")
        dialog.set_list(
            [self._format_subtitle_track_label(track, index) for index, track in enumerate(embedded_tracks)],
            selection_mode="single",
            default_width=210,
            default_height=110,
            min_width=160,
            min_height=80
        )
        dialog.set_buttons(["导入外部字幕", "取消"], Qt.Horizontal, ["primary", "normal"])

        def clear_dialog_reference(*args):
            if self._subtitle_track_dialog is dialog:
                self._subtitle_track_dialog = None

        def apply_track(index: int):
            if index < 0 or index >= len(embedded_tracks):
                return

            track_id = embedded_tracks[index].get("id")
            if track_id is None:
                self.errorOccurred.emit("无效的字幕轨")
                return

            success = self._mpv_manager.set_subtitle_track(
                track_id,
                component_id=self._component_id
            ) if self._mpv_manager else False

            if success:
                info(f"[VideoPlayer] 切换字幕轨成功: {track_id}")
                self._refresh_subtitle_state()
                QTimer.singleShot(100, self._refresh_subtitle_state)
                if self._detached_window:
                    self._detached_window.show_osd("字幕已切换")
                dialog.close()
            else:
                error(f"[VideoPlayer] 切换字幕轨失败: {track_id}")
                self.errorOccurred.emit("切换字幕失败")

        def on_dialog_button_clicked(button_index: int):
            if button_index == 0:
                dialog.close()
                self._open_external_subtitle_picker()
            else:
                dialog.close()

        if dialog._list:
            dialog._list.itemClicked.connect(apply_track)
            dialog._list.itemDoubleClicked.connect(apply_track)

            selected_track_id = subtitle_state.get("selected_track_id")
            for index, track in enumerate(embedded_tracks):
                if track.get("id") == selected_track_id:
                    dialog._list.set_current_item(index)
                    break

        dialog.buttonClicked.connect(on_dialog_button_clicked)
        dialog.finished.connect(clear_dialog_reference)
        dialog.exec()

    def _on_manager_file_loaded(self, file_path: str):
        """
        MPV管理器文件加载完成处理

        Args:
            file_path: 加载的文件路径
        """
        info(f"[VideoPlayer] 文件加载完成: {file_path}")

        # 不直接设置播放状态，让 stateChanged 信号来处理，确保状态同步
        # self._control_bar.set_playing(True)

        if not self._sync_timer.isActive():
            self._sync_timer.start()

        # 获取当前实际速度值并同步到控制栏，确保按钮样式正确
        if self._mpv_manager:
            current_speed = self._mpv_manager.get_speed()
            if current_speed is not None:
                self._control_bar.set_speed(current_speed, emit_signal=False)
            # 获取当前实际音量值并同步到控制栏
            current_volume = self._mpv_manager.get_volume()
            if current_volume is not None:
                self._control_bar.set_volume(current_volume, emit_signal=False)

        QTimer.singleShot(200, self._initialize_progress_display)
        QTimer.singleShot(250, self._refresh_subtitle_state)
        QTimer.singleShot(350, self._try_auto_load_matching_subtitle)

    def _on_manager_file_ended(self, reason: int):
        """
        MPV管理器文件播放结束处理

        Args:
            reason: 结束原因代码
        """
        info(f"[VideoPlayer] 文件播放结束，原因: {reason}")
        self._control_bar.set_playing(False)
        # 停止进度同步定时器
        if self._sync_timer.isActive():
            self._sync_timer.stop()

    def _on_manager_error(self, error_code: int, error_message: str):
        """
        MPV管理器错误处理

        Args:
            error_code: 错误代码
            error_message: 错误信息
        """
        error(f"[VideoPlayer] MPV错误 [{error_code}]: {error_message}")
        self.errorOccurred.emit(f"播放器错误: {error_message}")

    def _on_speed_changed(self, speed: float):
        """
        倍速变化处理（用户通过控制栏调整时触发）

        Args:
            speed: 新的倍速值
        """
        if self._mpv_manager:
            self._mpv_manager.set_speed(speed, component_id=self._component_id)
        # 保存倍速设置到 last_speed（仅在用户调整时保存）
        if self._settings_manager:
            self._settings_manager.save_player_speed(speed)

    def _on_lut_selected(self, lut_path: str):
        """
        LUT选择处理
        
        Args:
            lut_path: 选中的LUT文件路径
        """
        debug(f"[VideoPlayer] 收到LUT选择信号: {lut_path}")
        if self._mpv_manager:
            debug(f"[VideoPlayer] MPV管理器存在，调用load_lut")
            success = self._mpv_manager.load_lut(lut_path, component_id=self._component_id)
            debug(f"[VideoPlayer] load_lut结果: {success}")
            if success:
                self._control_bar.set_lut_loaded(True)
            else:
                self.errorOccurred.emit("加载LUT失败")
    
    def _on_lut_cleared(self):
        """LUT清除处理"""
        if self._mpv_manager:
            success = self._mpv_manager.unload_lut(component_id=self._component_id)
            if success:
                self._control_bar.set_lut_loaded(False)

    def _on_subtitle_clicked(self):
        """字幕按钮点击处理"""
        if not self._current_file:
            self.errorOccurred.emit("请先加载视频文件后再操作字幕")
            return

        if not self._mpv_manager or not self._mpv_manager.is_initialized():
            self.errorOccurred.emit("播放器未初始化")
            return

        subtitle_state = self._refresh_subtitle_state()
        is_subtitle_loaded = bool(
            subtitle_state.get("has_active_subtitle") and subtitle_state.get("is_subtitle_visible")
        )

        if is_subtitle_loaded:
            success = self._mpv_manager.hide_subtitle(component_id=self._component_id)
            if success:
                info("[VideoPlayer] 当前字幕已隐藏")
                self._refresh_subtitle_state()
                QTimer.singleShot(100, self._refresh_subtitle_state)
                if self._detached_window:
                    self._detached_window.show_osd("字幕已隐藏")
            else:
                error("[VideoPlayer] 隐藏字幕失败")
                self.errorOccurred.emit("隐藏字幕失败")
            return

        if self._get_embedded_subtitle_tracks(subtitle_state):
            self._open_subtitle_track_dialog(subtitle_state)
            return

        self._open_external_subtitle_picker()

    def _on_detach_clicked(self):
        """分离窗口按钮点击处理"""
        if self._detached_window is None:
            self._detach_to_window()
        else:
            self._reattach_to_parent()
    
    def _on_control_bar_key_pressed(self, event):
        """
        处理控制栏传递过来的键盘事件
        在分离窗口模式下，将键盘事件转发到分离窗口处理
        
        Args:
            event: 键盘事件对象
        """
        # 只有在分离窗口模式下才处理
        if not self._detached_window:
            return
        
        # 根据按键类型执行相应的操作
        key = event.key()
        if key == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
        elif key == Qt.Key_Escape:
            self._reattach_to_parent()
            event.accept()
        elif key == Qt.Key_Left:
            self.seek_backward()
            event.accept()
        elif key == Qt.Key_Right:
            self.seek_forward()
            event.accept()
        elif key == Qt.Key_Up:
            self.volume_up()
            event.accept()
        elif key == Qt.Key_Down:
            self.volume_down()
            event.accept()
        elif key == Qt.Key_0:
            self.set_speed(1.0)
            event.accept()
        elif key == Qt.Key_1:
            self.set_speed(1.0)
            event.accept()
        elif key == Qt.Key_2:
            self.set_speed(2.0)
            event.accept()
        elif key == Qt.Key_3:
            self.set_speed(3.0)
            event.accept()
        elif key == Qt.Key_QuoteLeft:  # `键
            self.set_speed(0.5)
            event.accept()

    def _on_floating_control_bar_key_pressed(self, event):
        """
        处理浮动控制栏传递过来的键盘事件
        在分离窗口模式下，将键盘事件转发到分离窗口处理

        Args:
            event: 键盘事件对象
        """
        # 只有在分离窗口模式下才处理
        if not self._detached_window:
            return

        # 根据按键类型执行相应的操作
        key = event.key()
        if key == Qt.Key_Space:
            self.toggle_play_pause()
            event.accept()
        elif key == Qt.Key_Escape:
            self._reattach_to_parent()
            event.accept()
        elif key == Qt.Key_Left:
            self.seek_backward()
            event.accept()
        elif key == Qt.Key_Right:
            self.seek_forward()
            event.accept()
        elif key == Qt.Key_Up:
            self.volume_up()
            event.accept()
        elif key == Qt.Key_Down:
            self.volume_down()
            event.accept()
        elif key == Qt.Key_1:
            self.set_speed(1.0)
            event.accept()
        elif key == Qt.Key_2:
            self.set_speed(2.0)
            event.accept()
        elif key == Qt.Key_3:
            self.set_speed(3.0)
            event.accept()
        elif key == Qt.Key_QuoteLeft:  # `键
            self.set_speed(0.5)
            event.accept()

    def _on_control_bar_shown(self):
        """
        浮动控制栏显示时的处理
        鼠标指针显隐由独立计时器控制，此处仅保留日志
        """
        debug(f"[VideoPlayer] 控制栏显示")

    def _on_control_bar_hidden(self):
        """
        浮动控制栏隐藏时的处理
        鼠标指针显隐由独立计时器控制，此处仅保留日志
        """
        debug(f"[VideoPlayer] 控制栏隐藏")

    def _save_playback_state(self):
        """
        保存当前播放状态，用于分离窗口时恢复
        
        Returns:
            dict: 包含播放位置、音量、静音状态、播放状态、倍速的字典
        """
        state = {
            'position': 0.0,
            'duration': 0.0,
            'volume': 100,
            'muted': False,
            'playing': False,
            'speed': 1.0
        }
        
        if self._mpv_manager:
            state['position'] = self._mpv_manager.get_position() or 0.0
            state['duration'] = self._mpv_manager.get_duration() or 0.0
            state['volume'] = self._mpv_manager.get_volume() or 100
            state['muted'] = self._mpv_manager.is_muted() or False
            state['playing'] = self._mpv_manager.is_playing() or False
            state['speed'] = self._mpv_manager.get_speed() or 1.0
        
        return state
    
    def _restore_playback_state(self, state: dict):
        """
        恢复播放状态
        
        Args:
            state: 包含播放状态的字典
        """
        if not self._mpv_manager or not state:
            return
        
        # 恢复音量
        if 'volume' in state:
            self._mpv_manager.set_volume(state['volume'], component_id=self._component_id)
            self._control_bar.set_volume(state['volume'])
        
        # 恢复静音状态
        if 'muted' in state:
            self._mpv_manager.set_muted(state['muted'], component_id=self._component_id)
            self._control_bar.set_muted(state['muted'])
        
        # 恢复倍速
        if 'speed' in state:
            self._mpv_manager.set_speed(state['speed'], component_id=self._component_id)
            self._control_bar.set_speed(state['speed'])
        
        # 恢复播放位置
        if 'position' in state and state['position'] > 0:
            self._mpv_manager.seek(state['position'], component_id=self._component_id)
            self._control_bar.set_position(state['position'], state.get('duration', 0))
        
        # 恢复播放状态
        if state.get('playing', False):
            self._mpv_manager.play(component_id=self._component_id)
            self._control_bar.set_playing(True)
        else:
            self._mpv_manager.pause(component_id=self._component_id)
            self._control_bar.set_playing(False)
    
    def _detach_to_window(self):
        """
        将视频播放器分离到独立窗口
        """
        debug(f"[VideoPlayer] 开始分离窗口")

        # 保存原始父窗口和布局
        self._original_parent = self.parent()
        self._original_layout = None
        if self._original_parent and hasattr(self._original_parent, 'layout'):
            self._original_layout = self._original_parent.layout()

        # 先将播放器从原布局中移除
        if self._original_layout:
            self._original_layout.removeWidget(self)

        # 创建独立窗口
        self._detached_window = DetachedVideoWindow(None)

        # 将播放器添加到独立窗口
        self.setParent(self._detached_window)
        self._detached_window._main_layout.addWidget(self)

        # 更新控制栏的分离状态，并在窗口显示前立即切换为浮动模式
        # 避免无边框窗口已出现但控制栏仍停留在固定模式的视觉延迟
        self._control_bar.set_detached(True)
        self._switch_to_floating_mode()

        # 连接独立窗口的关闭信号
        self._detached_window.closed.connect(self._reattach_to_parent)
        # 连接独立窗口的焦点变化信号
        self._detached_window.focusChanged.connect(self._on_detached_window_focus_changed)
        # 连接独立窗口的空格键信号到播放/暂停切换
        self._detached_window.spacePressed.connect(self.toggle_play_pause)
        # 连接独立窗口的ESC键信号到恢复窗口
        self._detached_window.escapePressed.connect(self._reattach_to_parent)
        # 连接独立窗口的方向键信号到前进/后退
        self._detached_window.leftArrowPressed.connect(self.seek_backward)
        self._detached_window.rightArrowPressed.connect(self.seek_forward)
        # 连接独立窗口的上下键信号到音量调整
        self._detached_window.upArrowPressed.connect(self.volume_up)
        self._detached_window.downArrowPressed.connect(self.volume_down)
        # 连接独立窗口的数字键信号到倍速控制（1-3键，最高3x，`键0.5x）
        self._detached_window.key1Pressed.connect(lambda: self.set_speed(1.0))
        self._detached_window.key2Pressed.connect(lambda: self.set_speed(2.0))
        self._detached_window.key3Pressed.connect(lambda: self.set_speed(3.0))
        self._detached_window.keyTildePressed.connect(lambda: self.set_speed(0.5))

        # 显示独立窗口并强制获取焦点
        self._detached_window.show()
        self._detached_window._force_focus()

        # 分离窗口模式下独立控制鼠标指针显隐，不再依赖控制栏显示状态
        self._start_cursor_auto_hide_monitor()

        # 下一轮事件循环中完成几何同步和MPV重连，避免长时间等待导致控制栏晚切换
        def finalize_detach():
            debug(f"[VideoPlayer] 完成分离窗口初始化")
            if not self._detached_window:
                return

            # 处理所有待处理事件，确保窗口状态和几何已更新
            QApplication.processEvents()

            self._detached_window.raise_()
            self._detached_window.activateWindow()
            self._detached_window.setFocus()

            self._detached_window.updateGeometry()
            self.updateGeometry()
            if hasattr(self, '_video_surface') and self._video_surface:
                self._video_surface.updateGeometry()

            QApplication.processEvents()

            # 更新浮动控制栏位置，确保与最终窗口尺寸保持一致
            if self._floating_control_bar:
                screen = self._detached_window.screen() or QApplication.primaryScreen()
                if screen:
                    self._floating_control_bar.set_target_rect(screen.geometry())
                    self._floating_control_bar.show_immediately()

            # 重新连接MPV窗口到新的渲染区域
            self._reconnect_mpv_window()

            # 再次确保焦点在分离窗口上（MPV嵌入后可能会抢占焦点）
            self._detached_window.activateWindow()
            self._detached_window.setFocus()

        QTimer.singleShot(0, finalize_detach)

        debug(f"[VideoPlayer] 窗口分离完成")
    
    def _on_detached_window_focus_changed(self, has_focus: bool):
        """
        分离窗口焦点变化处理
        
        Args:
            has_focus: 窗口是否获得焦点
        """
        # 注意：不再通过焦点变化来控制控制栏的显示/隐藏
        # 因为浮动控制栏是独立窗口，点击它会抢走焦点，导致闪烁问题
        # 控制栏的显示/隐藏由 D_HoverMenu 自身的鼠标活动监测逻辑处理
        pass
    
    def _reattach_to_parent(self):
        """
        将视频播放器恢复到原父窗口
        """
        debug(f"[VideoPlayer] 开始恢复窗口")

        # 恢复前先停止分离窗口鼠标指针自动隐藏逻辑
        self._stop_cursor_auto_hide_monitor()
        
        # 先切换回固定控制栏模式
        self._switch_to_fixed_mode()
        
        # 隐藏并关闭独立窗口
        if self._detached_window:
            # 断开信号连接
            try:
                self._detached_window.closed.disconnect(self._reattach_to_parent)
                self._detached_window.focusChanged.disconnect(self._on_detached_window_focus_changed)
            except (RuntimeError, TypeError) as e:
                warning(f"[VideoPlayer] 断开信号连接时出错: {e}")
            
            # 先将播放器从独立窗口中移除
            if self._detached_window.layout():
                self._detached_window.layout().removeWidget(self)
            
            self._detached_window.hide()
            self._detached_window.deleteLater()
            self._detached_window = None
        
        # 更新控制栏的分离状态
        self._control_bar.set_detached(False)
        
        # 将播放器重新添加到原父窗口
        if self._original_parent and self._original_layout:
            self.setParent(self._original_parent)
            self._original_layout.addWidget(self)
        
        # 延迟执行，重新连接MPV窗口
        def delayed_reconnect():
            debug(f"[VideoPlayer] 延迟重新连接MPV窗口")
            # 只重新连接MPV窗口到新的渲染区域
            self._reconnect_mpv_window()
        
        QTimer.singleShot(100, delayed_reconnect)
        
        debug(f"[VideoPlayer] 窗口恢复完成")
    



    
    def mousePressEvent(self, event):
        """
        处理鼠标点击事件
        """
        super().mousePressEvent(event)
        # 使用节流机制，避免过于频繁地触发控制栏显示
        if self._is_floating_mode and self._floating_control_bar:
            import time
            current_time = time.time() * 1000
            if not hasattr(self, '_last_mouse_press_time') or (current_time - self._last_mouse_press_time) >= 200:
                self._last_mouse_press_time = current_time
                self._floating_control_bar.show_control_bar()

    def mouseDoubleClickEvent(self, event):
        """
        处理鼠标双击事件
        """
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, obj, event):
        """
        事件过滤器

        Args:
            obj: 事件源对象
            event: 事件对象

        Returns:
            bool: 是否已处理事件
        """
        if obj == self._video_surface:
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    if self._is_floating_mode and self._floating_control_bar:
                        import time
                        current_time = time.time() * 1000
                        if not hasattr(self, '_last_video_click_time') or (current_time - self._last_video_click_time) >= 200:
                            self._last_video_click_time = current_time
                            self._floating_control_bar.show_control_bar()
                            use_classic_mode = self._settings_manager.get_setting("player.fullscreen_classic_control_bar", True)
                            if not use_classic_mode:
                                self._floating_control_bar.reset_auto_hide_timer()
            elif event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self.toggle_play_pause()
                    event.accept()
                    return True

        return super().eventFilter(obj, event)
    
    def _on_mpv_state_changed(self, is_playing: bool):
        """MPV播放状态变化处理"""
        # 更新控制栏
        self._control_bar.set_playing(is_playing)

    def _on_mpv_position_changed(self, position: float, duration: float):
        """MPV播放位置变化处理"""
        if self._user_interacting:
            return

        if duration > 0:
            progress = int((position / duration) * 1000)
            # 更新控制栏
            self._control_bar.set_progress(progress)
            self._update_time_display(position, duration)

    def _on_mpv_duration_changed(self, duration: float):
        """MPV时长变化处理"""
        if duration > 0:
            # 更新控制栏
            self._control_bar.set_range(0, 1000)
            self._update_time_display(0, duration)

    def _on_mpv_volume_changed(self, volume: int):
        """MPV音量变化处理（MPV回调触发，不保存设置）"""
        # 更新控制栏（不发射信号，避免循环）
        self._control_bar.set_volume(volume, emit_signal=False)

    def _on_mpv_muted_changed(self, muted: bool):
        """MPV静音状态变化处理"""
        # 更新控制栏
        self._control_bar.set_muted(muted)

    def _on_mpv_speed_changed(self, speed: float):
        """MPV倍速变化处理（MPV回调触发，不保存设置）"""
        # 更新控制栏（不发射信号，避免循环）
        self._control_bar.set_speed(speed, emit_signal=False)

    def _on_mpv_file_loaded(self, file_path: str, is_audio: bool = False):
        """MPV文件加载完成处理

        Args:
            file_path: 加载的文件路径
            is_audio: 是否为纯音频文件（由MPV核心在主线程中检测，但此处优先使用load_file传入的值）
        """
        self._current_file = file_path

        self._control_bar.set_progress(0)
        self._control_bar.set_time_text("00:00", "00:00")
        # 注意：视频加载后会自动播放，按钮状态已在 load_file 中设置为播放状态

        # 转发文件加载完成信号
        self.fileLoaded.emit(file_path, is_audio)

    def _on_mpv_file_ended(self, reason: int):
        """MPV文件播放结束处理"""
        if reason == MpvEndFileReason.EOF:
            pass
        elif reason == MpvEndFileReason.ERROR:
            self.errorOccurred.emit("播放过程中发生错误")
        
        self.fileEnded.emit()
    
    def _on_mpv_error(self, error_code: int, error_message: str):
        """MPV错误处理"""
        self.errorOccurred.emit(error_message)
    
    def _on_mpv_seek_finished(self):
        """MPV跳转完成处理"""
        pass
    
    def _on_mpv_video_size_changed(self, width: int, height: int):
        """MPV视频尺寸变化处理"""
        pass
    
    def _update_time_display(self, position: float, duration: float):
        """更新时间显示"""
        current_str = self._format_time(position)
        duration_str = self._format_time(duration)
        # 更新控制栏
        self._control_bar.set_time_text(current_str, duration_str)
    
    def _format_time(self, seconds: float) -> str:
        """
        格式化时间为 MM:SS 或 HH:MM:SS 格式
        
        Args:
            seconds: 秒数
            
        Returns:
            str: 格式化后的时间字符串
        """
        if seconds < 0:
            seconds = 0
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def _extract_audio_cover(self, file_path: str) -> Optional[bytes]:
        """
        从音频文件中提取封面图像数据

        Args:
            file_path: 音频文件路径

        Returns:
            Optional[bytes]: 封面图像的二进制数据，如果没有封面则返回None
        """
        if not mutagen_file:
            return None

        try:
            audio = mutagen_file(file_path)
            if not audio:
                return None

            # 尝试从不同格式的音频文件中提取封面
            # 方法1: 从tags中查找封面数据
            if hasattr(audio, 'tags') and audio.tags:
                for key in ['cover', ' Cover', 'APIC:', 'covr', 'albumart']:
                    if key in audio.tags:
                        data = audio.tags[key].data
                        if isinstance(data, bytes):
                            return data

            # 方法2: 遍历所有tags查找图片数据
            if hasattr(audio, 'tags') and audio.tags:
                for tag in audio.tags.values():
                    if hasattr(tag, 'data') and isinstance(tag.data, bytes):
                        # 检查是否是图片数据（常见图片格式的头部）
                        data = tag.data
                        if len(data) > 10 and (
                            data[:3] == b'\xff\xd8\xff' or  # JPEG
                            data[:4] == b'\x89PNG' or       # PNG
                            data[:2] in [b'BM', b'GI', b'CI']  # BMP或其他
                        ):
                            return data

            return None

        except Exception as e:
            warning(f"[VideoPlayer] 提取音频封面失败: {e}")
            return None
    
    def load_file(self, file_path: str, is_audio: bool = False) -> bool:
        """
        加载视频文件

        Args:
            file_path: 视频文件路径
            is_audio: 是否为纯音频文件（根据文件后缀名判断）

        Returns:
            bool: 加载是否成功
        """
        if not os.path.exists(file_path):
            self.errorOccurred.emit(f"文件不存在: {file_path}")
            return False

        self._close_subtitle_track_dialog()
        self._reset_subtitle_state()
        was_detached_mode = bool(self._detached_window)
        if was_detached_mode:
            self._stop_cursor_auto_hide_monitor()

        if not self._is_mpv_embedded:
            self._embed_mpv_window()

        if not self._mpv_manager:
            self.errorOccurred.emit("播放器未初始化")
            return False

        # 根据播放模式处理文件加载
        if self._playback_mode == self.AUDIO_MODE:
            # 音频模式：直接加载并显示音频背景
            self._current_file = file_path
            result = self._mpv_manager.load_file(file_path, component_id=self._component_id)
            if result:
                # 从设置中获取背景样式
                background_style = self._settings_manager.get_setting("player.audio_background_style", "流体动画")
                
                # 根据背景样式设置模式
                from freeassetfilter.widgets.audio_background import AudioBackground
                if background_style == "封面模糊":
                    self._audio_background.setMode(AudioBackground.MODE_COVER_BLUR)
                else:
                    self._audio_background.setMode(AudioBackground.MODE_FLUID)
                
                self._audio_background.load()
                self._audio_background.show()
                # 提取并设置音频封面
                cover_data = self._extract_audio_cover(file_path)
                self._current_audio_cover = cover_data  # 保存封面数据供分离窗口使用
                
                # 同时设置音频封面和封面数据（支持两种模式）
                self._audio_background.setAudioCover(cover_data)
                self._audio_background.setCoverData(cover_data)
                
                # 设置为无限单曲循环模式
                self.set_loop_mode("yes")
                # 应用播放器设置（音量和倍速）
                self._apply_player_settings()
        else:
            # 视频模式：直接加载视频
            result = self._mpv_manager.load_file(file_path, component_id=self._component_id)
            if result:
                self._current_file = file_path
                # 设置为无限单曲循环模式
                self.set_loop_mode("yes")
                # 应用播放器设置（音量和倍速）
                self._apply_player_settings()

        if result and was_detached_mode and self._detached_window:
            self._start_cursor_auto_hide_monitor()

        return result
    
    def play(self) -> bool:
        """
        开始播放

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            if not self._is_mpv_embedded:
                self._embed_mpv_window()
            result = self._mpv_manager.play(component_id=self._component_id)
            if result:
                self._control_bar.set_playing(True)
                if self._detached_window:
                    self._detached_window.show_osd("播放")
            return result
        return False

    def pause(self) -> bool:
        """
        暂停播放

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            result = self._mpv_manager.pause(component_id=self._component_id)
            if result:
                self._control_bar.set_playing(False)
                if self._detached_window:
                    self._detached_window.show_osd("暂停")
            return result
        return False
    
    def stop(self) -> bool:
        """
        停止播放

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            result = self._mpv_manager.stop(component_id=self._component_id)
            if result:
                # 卸载音频背景（如果已创建）
                if self._audio_background is not None:
                    self._audio_background.unload()
            return result
        return False
    
    def seek(self, position: float) -> bool:
        """
        跳转到指定位置

        Args:
            position: 目标位置（秒）

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            return self._mpv_manager.seek(position, component_id=self._component_id)
        return False

    def set_volume(self, volume: int) -> bool:
        """
        设置音量

        Args:
            volume: 音量值（0-100）

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            return self._mpv_manager.set_volume(volume, component_id=self._component_id)
        return False

    def set_speed(self, speed: float) -> bool:
        """
        设置播放速度

        Args:
            speed: 播放速度（0.1-10.0）

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            return self._mpv_manager.set_speed(speed, component_id=self._component_id)
        return False

    def set_mute(self, muted: bool) -> bool:
        """
        设置静音状态

        Args:
            muted: 是否静音

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            return self._mpv_manager.set_muted(muted, component_id=self._component_id)
        return False

    def set_loop_mode(self, mode: str) -> bool:
        """
        设置循环播放模式

        Args:
            mode: 循环模式 ("no", "yes", "playlist")

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            return self._mpv_manager.set_loop(mode, component_id=self._component_id)
        return False

    def get_current_file(self) -> str:
        """
        获取当前播放的文件路径

        Returns:
            str: 文件路径
        """
        return self._current_file

    def is_playing(self) -> bool:
        """
        获取播放状态

        Returns:
            bool: 是否正在播放
        """
        if self._mpv_manager:
            return self._mpv_manager.is_playing()
        return False

    def get_position(self) -> float:
        """
        获取当前播放位置

        Returns:
            float: 当前位置（秒）
        """
        if self._mpv_manager:
            return self._mpv_manager.get_position() or 0.0
        return 0.0

    def get_duration(self) -> float:
        """
        获取视频总时长

        Returns:
            float: 总时长（秒）
        """
        if self._mpv_manager:
            return self._mpv_manager.get_duration() or 0.0
        return 0.0

    def get_video_size(self) -> tuple:
        """
        获取视频尺寸

        Returns:
            tuple: (宽度, 高度)
        """
        if self._mpv_manager:
            return self._mpv_manager.get_video_size()
        return (0, 0)

    def take_screenshot(self, file_path: str, include_subtitles: bool = True) -> bool:
        """
        截取当前帧

        Args:
            file_path: 保存路径
            include_subtitles: 是否包含字幕

        Returns:
            bool: 操作是否成功
        """
        # 注意：管理器模式可能不支持截图，需要直接访问MPV核心
        # 这里返回False，后续可以实现
        return False
    
    def load_media(self, file_path: str, is_audio: bool = False) -> bool:
        """
        加载媒体文件（load_file的别名，用于兼容UnifiedPreviewer）

        Args:
            file_path: 媒体文件路径
            is_audio: 是否为纯音频文件（根据文件后缀名判断）

        Returns:
            bool: 加载是否成功
        """
        return self.load_file(file_path, is_audio)
    
    def toggle_play_pause(self) -> bool:
        """
        切换播放/暂停状态

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            if self._mpv_manager.is_paused() or not self._mpv_manager.is_playing():
                return self.play()
            else:
                return self.pause()
        return False
    
    def seek_forward(self, seconds: float = 5.0) -> bool:
        """
        向前跳转指定秒数

        Args:
            seconds: 跳转秒数，默认为5秒

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            current_position = self._mpv_manager.get_position() or 0.0
            duration = self._mpv_manager.get_duration() or 0.0
            new_position = min(current_position + seconds, duration)
            result = self._mpv_manager.seek(new_position, component_id=self._component_id)
            if result and self._detached_window:
                self._detached_window.show_seek_osd(new_position, duration, "forward")
            return result
        return False

    def seek_backward(self, seconds: float = 5.0) -> bool:
        """
        向后跳转指定秒数

        Args:
            seconds: 跳转秒数，默认为5秒

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            current_position = self._mpv_manager.get_position() or 0.0
            duration = self._mpv_manager.get_duration() or 0.0
            new_position = max(current_position - seconds, 0.0)
            result = self._mpv_manager.seek(new_position, component_id=self._component_id)
            if result and self._detached_window:
                self._detached_window.show_seek_osd(new_position, duration, "backward")
            return result
        return False

    def set_speed(self, speed: float) -> bool:
        """
        设置播放倍速

        Args:
            speed: 播放倍速，如 0.5, 1.0, 2.0 等

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            success = self._mpv_manager.set_speed(speed, component_id=self._component_id)
            if success:
                self._speed = speed
                self._control_bar.set_speed(speed)
                debug(f"[VideoPlayer] 设置播放倍速为 {speed}x")
                if self._detached_window:
                    self._detached_window.show_osd(f"{speed}x")
            return success
        return False
    
    def volume_up(self, step: int = 5) -> bool:
        """
        增加音量

        Args:
            step: 音量步进值，默认为5

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            current_volume = self._mpv_manager.get_volume() or 0
            new_volume = min(current_volume + step, 100)
            result = self._mpv_manager.set_volume(new_volume, component_id=self._component_id)
            if result and self._detached_window:
                self._detached_window.show_osd(f"音量 {new_volume}%")
            return result
        return False

    def volume_down(self, step: int = 5) -> bool:
        """
        减少音量

        Args:
            step: 音量步进值，默认为5

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_manager:
            current_volume = self._mpv_manager.get_volume() or 0
            new_volume = max(current_volume - step, 0)
            result = self._mpv_manager.set_volume(new_volume, component_id=self._component_id)
            if result and self._detached_window:
                self._detached_window.show_osd(f"音量 {new_volume}%")
            return result
        return False
    
    def update_style(self):
        """更新样式，用于主题变化时调用"""
        self._control_bar.update_style()

    def set_control_bar_border_radius(self, radius: int):
        """
        设置浮动控制栏的圆角半径
        
        Args:
            radius: 圆角半径（像素），必须 >= 0
        """
        self._control_bar_border_radius = max(0, radius)
        # 如果浮动控制栏已创建，动态更新圆角
        if self._floating_control_bar is not None:
            self._floating_control_bar.set_border_radius(self._control_bar_border_radius)

    def get_control_bar_border_radius(self) -> int:
        """
        获取浮动控制栏的圆角半径
        
        Returns:
            int: 圆角半径（像素）
        """
        return self._control_bar_border_radius if self._control_bar_border_radius is not None else 8

    def cleanup(self, async_mode: bool = True):
        """
        清理资源，用于在组件被销毁前进行完整的资源释放
        这是关键方法：必须确保MPV完全销毁后才能创建新的播放器，否则会导致访问冲突
        
        Args:
            async_mode: 是否异步关闭（默认True，不阻塞UI）
        """
        debug(f"[VideoPlayer] ========== 开始清理资源 (async={async_mode}) ==========")

        self._close_subtitle_track_dialog()
        self._reset_subtitle_state()

        # 停止进度同步定时器
        debug(f"[VideoPlayer] 停止进度同步定时器...")
        if self._sync_timer.isActive():
            self._sync_timer.stop()
            debug(f"[VideoPlayer] 进度同步定时器已停止")

        # 停止播放（预清理的一部分）
        debug(f"[VideoPlayer] 停止播放...")
        if self._mpv_manager:
            try:
                self._mpv_manager.stop(component_id=self._component_id)
                debug(f"[VideoPlayer] 播放已停止")
            except Exception as e:
                warning(f"[VideoPlayer] 停止播放时出错: {e}")

        # 卸载音频背景（仅音频模式有）
        debug(f"[VideoPlayer] 卸载音频背景...")
        if hasattr(self, '_audio_background') and self._audio_background is not None:
            try:
                self._audio_background.unload()
                debug(f"[VideoPlayer] 音频背景已卸载")
            except Exception as e:
                warning(f"[VideoPlayer] 卸载音频背景时出错: {e}")

        # 关闭MPV管理器（使用异步模式，不阻塞UI）
        debug(f"[VideoPlayer] 关闭MPV管理器 (async={async_mode})...")
        if self._mpv_manager:
            try:
                self._mpv_manager.close(async_mode=async_mode, timeout=2.0)
                if async_mode:
                    debug(f"[VideoPlayer] MPV管理器异步关闭已启动")
                else:
                    debug(f"[VideoPlayer] MPV管理器已关闭")
            except Exception as e:
                warning(f"[VideoPlayer] 关闭MPV管理器时出错: {e}")
            finally:
                # 异步模式下不立即置空，让后台线程完成清理
                if not async_mode:
                    self._mpv_manager = None

        # 标记为未嵌入状态
        self._is_mpv_embedded = False
        debug(f"[VideoPlayer] ========== 资源清理完成 ==========")
    
    def wait_for_cleanup(self, timeout: float = 5.0) -> bool:
        """
        等待清理完成（在异步模式下使用）
        
        Args:
            timeout: 最大等待时间（秒）
            
        Returns:
            bool: 是否在超时前完成清理
        """
        if self._mpv_manager:
            return self._mpv_manager.wait_for_cleanup(timeout=timeout)
        return True

    def closeEvent(self, event):
        """
        关闭事件处理
        确保资源正确关闭并清理
        """
        self._stop_cursor_auto_hide_monitor()

        # 使用异步模式关闭MPV管理器，避免阻塞UI
        if self._mpv_manager:
            self._mpv_manager.close(async_mode=True, timeout=2.0)

        super().closeEvent(event)
    
    def sizeHint(self) -> QSize:
        """获取建议尺寸"""
        return QSize(640, 360)
    
    def minimumSizeHint(self) -> QSize:
        """获取最小建议尺寸"""
        return QSize(320, 180)

    def _sync_mpv_geometry(self):
        """
        同步MPV窗口几何尺寸与Qt窗口一致
        解决原生DLL窗口和Qt占位窗口尺寸不一致的问题
        """
        if not self._video_surface:
            return

        # 获取Qt窗口的实际几何尺寸（使用整数像素值）
        geometry = self._video_surface.geometry()
        x = int(geometry.x())
        y = int(geometry.y())
        width = int(geometry.width())
        height = int(geometry.height())

        # 注意：管理器模式不直接支持设置几何尺寸
        # 如果需要，可以通过管理器扩展此功能
        pass

    def resizeEvent(self, event):
        """
        窗口尺寸变化事件处理
        确保MPV渲染尺寸与Qt窗口尺寸同步
        """
        super().resizeEvent(event)
        # 当窗口尺寸变化时，同步MPV窗口尺寸
        if self._mpv_manager and self._is_mpv_embedded and hasattr(self, '_video_surface'):
            self._sync_mpv_geometry()
