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
from typing import Optional

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
    QFrame, QApplication
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize
from PySide6.QtGui import QFont, QColor, QPalette, QPainter, QPen

from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEndFileReason
from freeassetfilter.core.mpv_manager import MPVManager, MPVState
from freeassetfilter.widgets.player_control_bar import PlayerControlBar
from freeassetfilter.core.settings_manager import SettingsManager


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
    
    def __init__(self, parent=None, show_lut_controls: bool = True, show_detach_button: bool = True, playback_mode: str = "video", initial_volume: int = None, initial_speed: float = None):
        """
        初始化视频播放器
        
        Args:
            parent: 父窗口部件
            show_lut_controls: 是否显示LUT相关控制按钮
            show_detach_button: 是否显示分离窗口按钮
            playback_mode: 播放模式，"video" 或 "audio"
            initial_volume: 初始音量值 (0-100)，None表示从设置读取
            initial_speed: 初始倍速值，None表示从设置读取
        """
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        self._current_file: str = ""
        self._playback_mode = playback_mode  # 播放模式：video 或 audio

        self._show_lut_controls = show_lut_controls
        self._show_detach_button = show_detach_button

        self._user_interacting = False
        self._pending_seek_value: Optional[int] = None

        # MPV管理器实例（单例）
        self._mpv_manager: Optional[MPVManager] = None
        self._video_widget: Optional[QWidget] = None
        self._is_mpv_embedded = False
        self._component_id = f"video_player_{id(self)}"  # 组件唯一标识

        # 音频封面数据
        self._current_audio_cover: Optional[bytes] = None  # 当前音频文件的封面数据

        # 进度同步定时器
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(200)  # 每200ms同步一次
        self._sync_timer.timeout.connect(self._sync_progress_from_player)

        # 初始化设置管理器并读取初始设置
        self._settings_manager = SettingsManager()
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
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
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
        print(f"[VideoPlayer] 开始清理MPV管理器...")
        if self._mpv_manager:
            # 断开所有信号连接
            self._disconnect_manager_signals()
            # 注销组件
            self._mpv_manager.unregister_component(self._component_id)
            self._mpv_manager = None
            print(f"[VideoPlayer] MPV管理器引用已清理")
        else:
            print(f"[VideoPlayer] MPV管理器不存在，无需清理")

    def _connect_signals(self):
        """连接信号和槽"""
        self._control_bar.playPauseClicked.connect(self._on_play_pause_clicked)
        self._control_bar.progressChanged.connect(self._on_progress_changed)
        self._control_bar.userInteractStarted.connect(self._on_user_interact_started)
        self._control_bar.userInteractEnded.connect(self._on_user_interact_ended)
        self._control_bar.volumeChanged.connect(self._on_volume_changed)
        self._control_bar.muteChanged.connect(self._on_mute_changed)
        self._control_bar.speedChanged.connect(self._on_speed_changed)
        self._control_bar.loadLutClicked.connect(self._on_load_lut_clicked)
        self._control_bar.detachClicked.connect(self._on_detach_clicked)
        
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
            except:
                pass
            try:
                self._mpv_manager.positionChanged.disconnect(self._on_manager_position_changed)
            except:
                pass
            try:
                self._mpv_manager.volumeChanged.disconnect(self._on_manager_volume_changed)
            except:
                pass
            try:
                self._mpv_manager.mutedChanged.disconnect(self._on_manager_muted_changed)
            except:
                pass
            try:
                self._mpv_manager.speedChanged.disconnect(self._on_manager_speed_changed)
            except:
                pass
            try:
                self._mpv_manager.fileLoaded.disconnect(self._on_manager_file_loaded)
            except:
                pass
            try:
                self._mpv_manager.fileEnded.disconnect(self._on_manager_file_ended)
            except:
                pass
            try:
                self._mpv_manager.errorOccurred.disconnect(self._on_manager_error)
            except:
                pass
    
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
        
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._video_surface.setAttribute(Qt.WA_NativeWindow)
        
        if not self._video_surface.isVisible():
            self._video_surface.show()
        
        win_id = int(self._video_surface.winId())
        
        if self._mpv_manager.set_window_id(win_id, component_id=self._component_id):
            self._is_mpv_embedded = True
            # 嵌入后立即同步几何尺寸
            self._sync_mpv_geometry()
            # 嵌入后立即应用初始设置（音量和倍速）
            self._mpv_manager.set_volume(self._initial_volume, component_id=self._component_id)
            self._mpv_manager.set_speed(self._initial_speed, component_id=self._component_id)
    
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
        if self._user_interacting and self._mpv_manager:
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
        print(f"[VideoPlayer] MPV状态变化: playing={state.is_playing}, paused={state.is_paused}")
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
        每500ms执行一次，确保进度条和时间标签显示准确
        """
        if not self._mpv_manager or self._user_interacting:
            return

        try:
            # 直接从MPVPlayerCore获取最新数据，不经过队列
            position = self._mpv_manager.get_position_direct()
            duration = self._mpv_manager.get_duration_direct()
            is_playing = self._mpv_manager.is_playing()
            is_paused = self._mpv_manager.is_paused()

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
            print(f"[VideoPlayer] 同步进度时出错: {e}")

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
                print(f"[VideoPlayer] 初始化进度显示: position={position}, duration={duration}")
            else:
                QTimer.singleShot(200, self._initialize_progress_display)
        except Exception as e:
            print(f"[VideoPlayer] 初始化进度显示失败: {e}")

    def _on_manager_file_loaded(self, file_path: str, is_audio: bool):
        """
        MPV管理器文件加载完成处理

        Args:
            file_path: 加载的文件路径
            is_audio: 是否为音频文件
        """
        print(f"[VideoPlayer] 文件加载完成: {file_path}, 是否音频: {is_audio}")

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

    def _on_manager_file_ended(self, reason: int):
        """
        MPV管理器文件播放结束处理

        Args:
            reason: 结束原因代码
        """
        print(f"[VideoPlayer] 文件播放结束，原因: {reason}")
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
        print(f"[VideoPlayer] MPV错误 [{error_code}]: {error_message}")
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

    def _on_load_lut_clicked(self):
        """加载LUT按钮点击处理"""
        pass

    def _on_detach_clicked(self):
        """分离窗口按钮点击处理 - 功能已禁用"""
        # 分离窗口功能已移除，此方法保留但不做任何操作
        print(f"[VideoPlayer] 分离窗口功能已禁用")
        pass
    
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
    


    def keyPressEvent(self, event):
        """
        处理键盘按键事件
        - 空格键：切换播放/暂停
        """
        if event.key() == Qt.Key_Space:
            self.toggle_play_pause()
        else:
            super().keyPressEvent(event)
    
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
            print(f"[VideoPlayer] 提取音频封面失败: {e}")
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
                
                # 应用播放器设置（音量和倍速）
                self._apply_player_settings()
        else:
            # 视频模式：直接加载视频
            result = self._mpv_manager.load_file(file_path, component_id=self._component_id)
            if result:
                self._current_file = file_path
                # 应用播放器设置（音量和倍速）
                self._apply_player_settings()

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
                # 同步更新控制栏状态，避免信号延迟导致按钮状态不同步
                self._control_bar.set_playing(True)
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
                # 同步更新控制栏状态，避免信号延迟导致按钮状态不同步
                self._control_bar.set_playing(False)
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
    
    def update_style(self):
        """更新样式，用于主题变化时调用"""
        self._control_bar.update_style()

    def cleanup(self):
        """
        清理资源，用于在组件被销毁前进行完整的资源释放
        这是关键方法：必须确保MPV完全销毁后才能创建新的播放器，否则会导致访问冲突
        """
        print(f"[VideoPlayer] ========== 开始清理资源 ==========")

        # 停止进度同步定时器
        print(f"[VideoPlayer] 停止进度同步定时器...")
        if self._sync_timer.isActive():
            self._sync_timer.stop()
            print(f"[VideoPlayer] 进度同步定时器已停止")

        # 停止播放
        print(f"[VideoPlayer] 停止播放...")
        if self._mpv_manager:
            try:
                self._mpv_manager.stop(component_id=self._component_id)
                print(f"[VideoPlayer] 播放已停止")
            except Exception as e:
                print(f"[VideoPlayer] 停止播放时出错: {e}")

        # 卸载音频背景（仅音频模式有）
        print(f"[VideoPlayer] 卸载音频背景...")
        if hasattr(self, '_audio_background') and self._audio_background is not None:
            try:
                self._audio_background.unload()
                print(f"[VideoPlayer] 音频背景已卸载")
            except Exception as e:
                print(f"[VideoPlayer] 卸载音频背景时出错: {e}")

        # 关闭MPV管理器
        print(f"[VideoPlayer] 关闭MPV管理器...")
        if self._mpv_manager:
            try:
                self._mpv_manager.close()
                print(f"[VideoPlayer] MPV管理器已关闭")
            except Exception as e:
                print(f"[VideoPlayer] 关闭MPV管理器时出错: {e}")
            finally:
                self._mpv_manager = None

        # 标记为未嵌入状态
        self._is_mpv_embedded = False
        print(f"[VideoPlayer] ========== 资源清理完成 ==========")

    def closeEvent(self, event):
        """
        关闭事件处理
        确保资源正确关闭并清理
        """
        # 关闭MPV管理器
        if self._mpv_manager:
            self._mpv_manager.close()

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
