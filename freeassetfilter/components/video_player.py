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

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, 
    QStackedLayout, QFrame, QApplication, QMainWindow
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont, QColor, QPalette, QPainter, QPen

from freeassetfilter.core.mpv_player_core import MPVPlayerCore, MpvEndFileReason
from freeassetfilter.widgets.player_control_bar import PlayerControlBar


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
        detachRequested: 分离窗口请求信号
        idle_event: 空闲事件信号，用于异常检测
    """
    
    fileLoaded = Signal(str, bool)  # 文件路径, 是否为音频文件
    fileEnded = Signal()
    errorOccurred = Signal(str)
    detachRequested = Signal()  # 分离窗口请求信号
    detachCompleted = Signal()  # 分离完成信号
    reattachCompleted = Signal()  # 重新附加完成信号
    idle_event = Signal()
    
    def __init__(self, parent=None, show_lut_controls: bool = True, show_detach_button: bool = True):
        """
        初始化视频播放器
        
        Args:
            parent: 父窗口部件
            show_lut_controls: 是否显示LUT相关控制按钮
            show_detach_button: 是否显示分离窗口按钮
        """
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        self._current_file: str = ""
        self._is_detached: bool = False
        self._show_lut_controls = show_lut_controls
        self._show_detach_button = show_detach_button
        
        self._user_interacting = False
        self._pending_seek_value: Optional[int] = None
        
        self._mpv_core: Optional[MPVPlayerCore] = None
        self._video_widget: Optional[QWidget] = None
        self._is_mpv_embedded = False
        
        # 分离窗口相关属性
        self._detach_window: Optional[QMainWindow] = None  # 分离窗口实例
        self._detach_video_surface: Optional[QWidget] = None  # 分离窗口中的视频表面
        self._detach_control_bar: Optional[PlayerControlBar] = None  # 分离窗口中的控制栏
        self._original_parent: Optional[QWidget] = None  # 原始父窗口
        self._original_geometry: Optional[QSize] = None  # 原始几何尺寸
        self._playback_state_before_detach: dict = {}  # 分离前的播放状态
        self._is_switching_window: bool = False  # 是否正在切换窗口（防止回调冲突）
        
        self._init_ui()
        self._init_mpv_core()
        self._connect_signals()
    
    def _init_ui(self):
        """初始化用户界面"""
        self.setStyleSheet("background-color: transparent;")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        video_container = QWidget()
        video_container.setStyleSheet("background-color: transparent;")
        self._video_stack = QStackedLayout(video_container)
        self._video_stack.setStackingMode(QStackedLayout.StackAll)
        self._video_stack.setContentsMargins(0, 0, 0, 0)
        
        self._placeholder = VideoPlaceholder(self)
        self._video_stack.addWidget(self._placeholder)

        self._video_surface = QWidget()
        self._video_surface.setStyleSheet("background-color: transparent;")
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._video_surface.setAttribute(Qt.WA_NativeWindow)
        self._video_stack.addWidget(self._video_surface)

        self._video_stack.setCurrentWidget(self._placeholder)
        
        main_layout.addWidget(video_container, 1)
        
        self._control_bar = PlayerControlBar(
            self, 
            show_lut_controls=self._show_lut_controls
        )
        self._control_bar.set_detach_button_visible(self._show_detach_button)
        main_layout.addWidget(self._control_bar)
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    
    def _init_mpv_core(self):
        """初始化MPV播放器核心"""
        self._mpv_core = MPVPlayerCore(self)
    
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
        
        if self._mpv_core:
            self._mpv_core.stateChanged.connect(self._on_mpv_state_changed, Qt.QueuedConnection)
            self._mpv_core.positionChanged.connect(self._on_mpv_position_changed, Qt.QueuedConnection)
            self._mpv_core.durationChanged.connect(self._on_mpv_duration_changed, Qt.QueuedConnection)
            self._mpv_core.volumeChanged.connect(self._on_mpv_volume_changed, Qt.QueuedConnection)
            self._mpv_core.mutedChanged.connect(self._on_mpv_muted_changed, Qt.QueuedConnection)
            self._mpv_core.speedChanged.connect(self._on_mpv_speed_changed, Qt.QueuedConnection)
            self._mpv_core.fileLoaded.connect(self._on_mpv_file_loaded, Qt.QueuedConnection)
            self._mpv_core.fileEnded.connect(self._on_mpv_file_ended, Qt.QueuedConnection)
            self._mpv_core.errorOccurred.connect(self._on_mpv_error, Qt.QueuedConnection)
            self._mpv_core.seekFinished.connect(self._on_mpv_seek_finished, Qt.QueuedConnection)
            self._mpv_core.videoSizeChanged.connect(self._on_mpv_video_size_changed, Qt.QueuedConnection)
    
    def _embed_mpv_window(self):
        """将MPV窗口嵌入到视频渲染区域"""
        if self._is_mpv_embedded or not self._mpv_core:
            return
        
        if not self._mpv_core.initialize():
            self.errorOccurred.emit("无法初始化MPV播放器")
            return
        
        self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._video_surface.setAttribute(Qt.WA_NativeWindow)
        self._video_surface.ensurePolished()
        
        if not self._video_surface.isVisible():
            self._video_surface.show()
        
        win_id = int(self._video_surface.winId())
        
        if self._mpv_core.set_window_id(win_id):
            self._is_mpv_embedded = True
            self._video_stack.setCurrentWidget(self._video_surface)
            # 嵌入后立即同步几何尺寸
            self._sync_mpv_geometry()
    
    def _on_play_pause_clicked(self):
        """播放/暂停按钮点击处理"""
        if not self._mpv_core:
            return

        if self._mpv_core.is_playing():
            self.pause()
        else:
            self.play()
    
    def _on_progress_changed(self, value: int):
        """进度条值变化处理"""
        if self._user_interacting and self._mpv_core:
            duration = self._mpv_core.get_duration() or 0
            if duration > 0:
                position = (value / 1000.0) * duration
                self._mpv_core.seek(position)
                self._update_time_display(position, duration)
        self._pending_seek_value = value
    
    def _on_user_interact_started(self):
        """用户开始与进度条交互"""
        self._user_interacting = True
    
    def _on_user_interact_ended(self):
        """用户结束与进度条交互"""
        self._user_interacting = False
    
    def _on_volume_changed(self, volume: int):
        """音量变化处理"""
        if self._mpv_core:
            self._mpv_core.set_volume(volume)
    
    def _on_mute_changed(self, muted: bool):
        """静音状态变化处理"""
        if self._mpv_core:
            self._mpv_core.set_mute(muted)

    def _on_speed_changed(self, speed: float):
        """
        倍速变化处理

        Args:
            speed: 新的倍速值
        """
        if self._mpv_core:
            self._mpv_core.set_speed(speed)

    def _on_load_lut_clicked(self):
        """加载LUT按钮点击处理"""
        pass

    def _on_detach_clicked(self):
        """分离窗口按钮点击处理 - 切换分离/返回状态"""
        if self._is_detached:
            # 当前已分离，执行返回操作
            self._reattach_to_parent()
        else:
            # 当前未分离，执行分离操作
            self._detach_to_window()
    
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
        
        if self._mpv_core:
            state['position'] = self._mpv_core.get_position() or 0.0
            state['duration'] = self._mpv_core.get_duration() or 0.0
            state['volume'] = self._mpv_core.get_volume() or 100
            state['muted'] = self._mpv_core.is_muted() or False
            state['playing'] = self._mpv_core.is_playing() or False
            state['speed'] = self._mpv_core.get_speed() or 1.0
        
        return state
    
    def _restore_playback_state(self, state: dict):
        """
        恢复播放状态
        
        Args:
            state: 包含播放状态的字典
        """
        if not self._mpv_core or not state:
            return
        
        # 恢复音量
        if 'volume' in state:
            self._mpv_core.set_volume(state['volume'])
            self._control_bar.set_volume(state['volume'])
        
        # 恢复静音状态
        if 'muted' in state:
            self._mpv_core.set_mute(state['muted'])
            self._control_bar.set_muted(state['muted'])
        
        # 恢复倍速
        if 'speed' in state:
            self._mpv_core.set_speed(state['speed'])
            self._control_bar.set_speed(state['speed'])
        
        # 恢复播放位置
        if 'position' in state and state['position'] > 0:
            self._mpv_core.seek(state['position'])
            self._control_bar.set_position(state['position'], state.get('duration', 0))
        
        # 恢复播放状态
        if state.get('playing', False):
            self._mpv_core.play()
            self._control_bar.set_playing(True)
        else:
            self._mpv_core.pause()
            self._control_bar.set_playing(False)
    
    def _detach_to_window(self):
        """
        将视频播放器分离到独立窗口
        创建无边框全屏窗口，在分离窗口中创建新的视频表面，MPV绑定到新表面
        """
        if self._is_detached or not self._current_file:
            return
        
        try:
            # 设置切换窗口标志，防止MPV回调冲突
            self._is_switching_window = True
            
            # 先收起原窗口控制栏的所有菜单
            self._control_bar.collapse_all_menus()
            
            # 保存原始状态
            self._original_parent = self.parentWidget()
            self._original_geometry = self.size()
            self._playback_state_before_detach = self._save_playback_state()
            
            # 暂停播放以避免切换窗口时的闪烁
            was_playing = self._mpv_core.is_playing() if self._mpv_core else False
            if was_playing:
                self._mpv_core.pause()
            
            # 创建分离窗口
            self._detach_window = QMainWindow()
            self._detach_window.setWindowTitle("视频播放 - FreeAssetFilter")
            
            # 设置无边框窗口
            self._detach_window.setWindowFlags(
                Qt.Window |
                Qt.FramelessWindowHint |
                Qt.WindowStaysOnTopHint
            )
            
            # 设置全屏
            screen = QApplication.primaryScreen()
            if screen:
                self._detach_window.setGeometry(screen.availableGeometry())
            
            # 设置黑色背景
            self._detach_window.setStyleSheet("background-color: black;")
            
            # 创建中心部件，使用绝对定位布局
            central_widget = QWidget()
            central_layout = QVBoxLayout(central_widget)
            central_layout.setContentsMargins(0, 0, 0, 0)
            central_layout.setSpacing(0)
            
            # 创建视频表面容器（填充整个区域）
            video_container = QWidget()
            video_container.setStyleSheet("background-color: black;")
            video_layout = QVBoxLayout(video_container)
            video_layout.setContentsMargins(0, 0, 0, 0)
            
            # 在视频容器中创建新的视频表面
            self._detach_video_surface = QWidget()
            self._detach_video_surface.setStyleSheet("background-color: black;")
            self._detach_video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
            self._detach_video_surface.setAttribute(Qt.WA_NativeWindow)
            video_layout.addWidget(self._detach_video_surface)
            
            central_layout.addWidget(video_container, 1)
            
            # 创建分离窗口的控制栏（固定在底部）
            self._detach_control_bar = PlayerControlBar(
                None,
                show_lut_controls=self._show_lut_controls
            )
            self._detach_control_bar.set_detach_button_visible(self._show_detach_button)
            self._detach_control_bar.set_detached(True)
            
            # 连接控制栏信号到当前播放器的槽
            self._connect_detach_control_bar_signals()
            
            # 同步控制栏状态
            self._sync_detach_control_bar_state()
            
            central_layout.addWidget(self._detach_control_bar)
            
            # 设置中心部件
            self._detach_window.setCentralWidget(central_widget)
            
            # 为分离窗口安装事件过滤器，处理ESC键退出
            self._detach_window.installEventFilter(self)
            
            # 显示分离窗口（必须先显示才能获取有效的窗口句柄）
            self._detach_window.show()
            self._detach_window.raise_()
            self._detach_window.activateWindow()
            
            # 更新分离状态
            self._is_detached = True
            self._control_bar.set_detached(True)
            
            # 等待窗口完全显示后重新绑定MPV
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self._finish_detach(was_playing))
            
        except Exception as e:
            print(f"[VideoPlayer] 分离窗口失败: {e}")
            # 清除切换窗口标志
            self._is_switching_window = False
            # 恢复原始状态
            self._is_detached = False
            self._control_bar.set_detached(False)
            self.errorOccurred.emit(f"分离窗口失败: {str(e)}")
    
    def _finish_detach(self, was_playing: bool):
        """
        完成分离窗口的后续操作
        重新绑定MPV窗口到分离窗口的视频表面
        
        Args:
            was_playing: 分离前是否正在播放
        """
        try:
            # 重新嵌入MPV窗口到分离窗口的视频表面
            self._reembed_mpv_to_detach_window()
            
            # 恢复播放状态
            self._restore_playback_state(self._playback_state_before_detach)
            
            # 如果之前在播放，恢复播放
            if was_playing and self._mpv_core:
                self._mpv_core.play()
            
            # 连接分离窗口的关闭事件
            if self._detach_window:
                self._detach_window.closeEvent = self._on_detach_window_close
            
            # 发射分离完成信号
            self.detachCompleted.emit()
            
            # 清除切换窗口标志
            self._is_switching_window = False
            
            print(f"[VideoPlayer] 窗口已分离到独立窗口: {self._current_file}")
            
        except Exception as e:
            # 清除切换窗口标志
            self._is_switching_window = False
            print(f"[VideoPlayer] 完成分离操作失败: {e}")
            self.errorOccurred.emit(f"分离窗口失败: {str(e)}")
    
    def _reembed_mpv_to_detach_window(self):
        """
        重新嵌入MPV窗口到分离窗口的视频表面
        将MPV的渲染目标从原窗口切换到分离窗口的新视频表面
        """
        if not self._mpv_core or not self._detach_window or not self._detach_video_surface:
            return
        
        try:
            # 确保分离窗口的视频表面控件准备好
            self._detach_video_surface.ensurePolished()
            
            if not self._detach_video_surface.isVisible():
                self._detach_video_surface.show()
            
            # 处理事件队列，确保窗口已创建
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            
            # 获取分离窗口视频表面的窗口句柄
            detach_win_id = int(self._detach_video_surface.winId())
            
            print(f"[VideoPlayer] 准备绑定到分离窗口，句柄: {detach_win_id}")
            
            # 重新设置MPV的渲染窗口
            if self._mpv_core.set_window_id(detach_win_id):
                print(f"[VideoPlayer] MPV已重新绑定到分离窗口: {detach_win_id}")
                # 刷新视频渲染
                self._mpv_core.refresh_video()
            else:
                print(f"[VideoPlayer] 警告: MPV重新绑定到分离窗口失败")
                
        except Exception as e:
            print(f"[VideoPlayer] 重新嵌入MPV窗口失败: {e}")
            raise
    
    def _reattach_to_parent(self):
        """
        将视频播放器重新附加到原始父窗口
        先将MPV绑定回原窗口的视频表面，再关闭分离窗口
        """
        if not self._is_detached:
            return
        
        try:
            # 设置切换窗口标志，防止MPV回调冲突
            self._is_switching_window = True
            
            # 先收起分离窗口控制栏的所有菜单
            if self._detach_control_bar:
                self._detach_control_bar.collapse_all_menus()
            
            # 保存当前播放状态
            current_state = self._save_playback_state()
            
            # 暂停播放以避免切换窗口时的闪烁
            was_playing = self._mpv_core.is_playing() if self._mpv_core else False
            if was_playing:
                self._mpv_core.pause()
            
            # 先将MPV绑定回原窗口的视频表面
            # 这样MPV会在分离窗口关闭前切换到原窗口的有效窗口句柄
            self._reembed_mpv_to_original_window()
            
            # 恢复播放状态
            self._restore_playback_state(current_state)
            
            # 如果之前在播放，恢复播放
            if was_playing and self._mpv_core:
                self._mpv_core.play()
            
            # 现在可以安全关闭分离窗口了
            # MPV已经不再依赖分离窗口的句柄
            if self._detach_window:
                # 临时移除关闭事件处理，避免递归
                self._detach_window.closeEvent = lambda event: event.accept()
                self._detach_window.close()
                self._detach_window = None
                self._detach_video_surface = None
                self._detach_control_bar = None
            
            # 发射重新附加完成信号
            self.reattachCompleted.emit()
            
            # 更新分离状态
            self._is_detached = False
            self._control_bar.set_detached(False)
            
            # 清除切换窗口标志
            self._is_switching_window = False
            
            print(f"[VideoPlayer] 窗口已返回原位置，MPV已重新绑定")
            
        except Exception as e:
            # 清除切换窗口标志
            self._is_switching_window = False
            print(f"[VideoPlayer] 返回原窗口失败: {e}")
            self.errorOccurred.emit(f"返回原窗口失败: {str(e)}")
    
    def _finish_reattach(self, state: dict, was_playing: bool):
        """
        完成返回原窗口的后续操作
        重新绑定MPV窗口到原视频表面并恢复播放状态
        
        Args:
            state: 播放状态字典
            was_playing: 返回前是否正在播放
        """
        try:
            # 重新嵌入MPV窗口到原视频表面
            self._reembed_mpv_to_original_window()
            
            # 恢复播放状态
            self._restore_playback_state(state)
            
            # 如果之前在播放，恢复播放
            if was_playing and self._mpv_core:
                self._mpv_core.play()
            
            print(f"[VideoPlayer] 窗口已返回原位置，MPV已重新绑定")
            
        except Exception as e:
            print(f"[VideoPlayer] 完成返回操作失败: {e}")
    
    def _reembed_mpv_to_original_window(self):
        """
        重新嵌入MPV窗口到原视频表面
        将MPV的渲染目标从分离窗口切换回原窗口的_video_surface
        """
        if not self._mpv_core:
            return
        
        try:
            # 确保原视频表面控件可见并准备好
            self._video_surface.setAttribute(Qt.WA_DontCreateNativeAncestors)
            self._video_surface.setAttribute(Qt.WA_NativeWindow)
            self._video_surface.ensurePolished()
            
            if not self._video_surface.isVisible():
                self._video_surface.show()
            
            # 处理事件队列，确保窗口已创建
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.processEvents()
            
            # 获取原视频表面的窗口句柄
            original_win_id = int(self._video_surface.winId())
            
            print(f"[VideoPlayer] 准备绑定到原窗口，句柄: {original_win_id}")
            
            # 重新设置MPV的渲染窗口
            if self._mpv_core.set_window_id(original_win_id):
                print(f"[VideoPlayer] MPV已重新绑定到原窗口: {original_win_id}")
                # 刷新视频渲染
                self._mpv_core.refresh_video()
                # 显示视频表面
                self._video_stack.setCurrentWidget(self._video_surface)
            else:
                print(f"[VideoPlayer] 警告: MPV重新绑定到原窗口失败")
                
        except Exception as e:
            print(f"[VideoPlayer] 重新嵌入MPV到原窗口失败: {e}")
            raise
    
    def _on_detach_window_close(self, event):
        """
        分离窗口关闭事件处理
        当用户关闭分离窗口时，自动返回原窗口
        
        Args:
            event: 关闭事件
        """
        # 接受关闭事件
        event.accept()
        
        # 执行返回操作
        QTimer.singleShot(0, self._reattach_to_parent)

    def _connect_detach_control_bar_signals(self):
        """
        连接分离窗口控制栏的信号到当前播放器的槽
        使分离窗口的控制栏能够控制视频播放
        """
        if not self._detach_control_bar:
            return
        
        # 连接控制栏信号到播放器的方法
        self._detach_control_bar.playPauseClicked.connect(self._on_play_pause_clicked)
        self._detach_control_bar.progressChanged.connect(self._on_progress_changed)
        self._detach_control_bar.userInteractStarted.connect(self._on_user_interact_started)
        self._detach_control_bar.userInteractEnded.connect(self._on_user_interact_ended)
        self._detach_control_bar.volumeChanged.connect(self._on_volume_changed)
        self._detach_control_bar.muteChanged.connect(self._on_mute_changed)
        self._detach_control_bar.speedChanged.connect(self._on_speed_changed)
        self._detach_control_bar.loadLutClicked.connect(self._on_load_lut_clicked)
        self._detach_control_bar.detachClicked.connect(self._on_detach_clicked)
    
    def _sync_detach_control_bar_state(self):
        """
        同步分离窗口控制栏的状态到当前播放器的状态
        确保分离窗口的控制栏显示正确的播放状态
        """
        if not self._detach_control_bar or not self._mpv_core:
            return

        # 同步播放状态
        self._detach_control_bar.set_playing(self._mpv_core.is_playing())

        # 同步进度
        position = self._mpv_core.get_position()
        duration = self._mpv_core.get_duration()
        if duration > 0:
            progress = int((position / duration) * 1000)
            self._detach_control_bar.set_progress(progress)

        # 同步时间显示
        current_str = self._format_time(position)
        duration_str = self._format_time(duration)
        self._detach_control_bar.set_time_text(current_str, duration_str)

        # 同步音量
        self._detach_control_bar.set_volume(self._mpv_core.get_volume())

        # 同步静音状态
        self._detach_control_bar.set_muted(self._mpv_core.is_muted())

        # 同步倍速
        self._detach_control_bar.set_speed(self._mpv_core.get_speed())

        # 更新控制栏样式（确保时间标签颜色等样式正确应用）
        self._detach_control_bar._update_style()
    
    def keyPressEvent(self, event):
        """
        处理键盘按键事件
        - ESC键：如果处于分离状态，返回原窗口
        - 空格键：切换播放/暂停
        """
        if event.key() == Qt.Key_Escape:
            if self._is_detached:
                self._reattach_to_parent()
            else:
                super().keyPressEvent(event)
        elif event.key() == Qt.Key_Space:
            self.toggle_play_pause()
        else:
            super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        """
        处理鼠标双击事件
        - 双击视频区域：切换分离状态
        """
        if event.button() == Qt.LeftButton:
            if self._is_detached:
                self._reattach_to_parent()
            else:
                self._detach_to_window()
        else:
            super().mouseDoubleClickEvent(event)

    def eventFilter(self, obj, event):
        """
        事件过滤器，处理分离窗口的键盘事件
        - ESC键：返回原窗口

        Args:
            obj: 事件源对象
            event: 事件对象

        Returns:
            bool: 是否已处理事件
        """
        if obj == self._detach_window and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Escape:
                # ESC键返回原窗口
                self._reattach_to_parent()
                return True
        return super().eventFilter(obj, event)
    
    def _on_mpv_state_changed(self, is_playing: bool):
        """MPV播放状态变化处理"""
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        # 同时更新原窗口和分离窗口的控制栏
        self._control_bar.set_playing(is_playing)
        if self._detach_control_bar:
            self._detach_control_bar.set_playing(is_playing)

    def _on_mpv_position_changed(self, position: float, duration: float):
        """MPV播放位置变化处理"""
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        if self._user_interacting:
            return

        if duration > 0:
            progress = int((position / duration) * 1000)
            # 同时更新原窗口和分离窗口的控制栏
            self._control_bar.set_progress(progress)
            if self._detach_control_bar:
                self._detach_control_bar.set_progress(progress)
            self._update_time_display(position, duration)

    def _on_mpv_duration_changed(self, duration: float):
        """MPV时长变化处理"""
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        if duration > 0:
            # 同时更新原窗口和分离窗口的控制栏
            self._control_bar.set_range(0, 1000)
            if self._detach_control_bar:
                self._detach_control_bar.set_range(0, 1000)
            self._update_time_display(0, duration)

    def _on_mpv_volume_changed(self, volume: int):
        """MPV音量变化处理"""
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        # 同时更新原窗口和分离窗口的控制栏
        self._control_bar.set_volume(volume)
        if self._detach_control_bar:
            self._detach_control_bar.set_volume(volume)

    def _on_mpv_muted_changed(self, muted: bool):
        """MPV静音状态变化处理"""
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        # 同时更新原窗口和分离窗口的控制栏
        self._control_bar.set_muted(muted)
        if self._detach_control_bar:
            self._detach_control_bar.set_muted(muted)

    def _on_mpv_speed_changed(self, speed: float):
        """MPV倍速变化处理"""
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        # 同时更新原窗口和分离窗口的控制栏
        self._control_bar.set_speed(speed)
        if self._detach_control_bar:
            self._detach_control_bar.set_speed(speed)

    def _on_mpv_file_loaded(self, file_path: str, is_audio: bool = False):
        """MPV文件加载完成处理

        Args:
            file_path: 加载的文件路径
            is_audio: 是否为纯音频文件（由MPV核心在主线程中检测）
        """
        self._current_file = file_path

        # 显示视频渲染表面（音频和视频都使用相同的显示方式）
        self._video_stack.setCurrentWidget(self._video_surface)

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
        # 如果正在切换窗口，跳过回调以避免冲突
        if self._is_switching_window:
            return
        current_str = self._format_time(position)
        duration_str = self._format_time(duration)
        # 同时更新原窗口和分离窗口的控制栏
        self._control_bar.set_time_text(current_str, duration_str)
        if self._detach_control_bar:
            self._detach_control_bar.set_time_text(current_str, duration_str)
    
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
    
    def load_file(self, file_path: str) -> bool:
        """
        加载视频文件
        
        Args:
            file_path: 视频文件路径
            
        Returns:
            bool: 加载是否成功
        """
        if not os.path.exists(file_path):
            self.errorOccurred.emit(f"文件不存在: {file_path}")
            return False
        
        if not self._is_mpv_embedded:
            self._embed_mpv_window()
        
        if not self._mpv_core:
            self.errorOccurred.emit("播放器未初始化")
            return False
        
        result = self._mpv_core.load_file(file_path)

        if result:
            self._current_file = file_path
            self._placeholder.hide()
            # 视频加载后会自动开始播放，延迟更新播放按钮为暂停图标
            # 使用 QTimer.singleShot 确保在异步信号处理完成后再更新状态
            QTimer.singleShot(100, lambda: self._control_bar.set_playing(True))

        return result
    
    def play(self) -> bool:
        """
        开始播放

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_core:
            if not self._is_mpv_embedded:
                self._embed_mpv_window()
            result = self._mpv_core.play()
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
        if self._mpv_core:
            result = self._mpv_core.pause()
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
        if self._mpv_core:
            result = self._mpv_core.stop()
            if result:
                self._video_stack.setCurrentWidget(self._placeholder)
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
        if self._mpv_core:
            return self._mpv_core.seek(position)
        return False
    
    def set_volume(self, volume: int) -> bool:
        """
        设置音量
        
        Args:
            volume: 音量值（0-100）
            
        Returns:
            bool: 操作是否成功
        """
        if self._mpv_core:
            return self._mpv_core.set_volume(volume)
        return False
    
    def set_speed(self, speed: float) -> bool:
        """
        设置播放速度
        
        Args:
            speed: 播放速度（0.1-10.0）
            
        Returns:
            bool: 操作是否成功
        """
        if self._mpv_core:
            return self._mpv_core.set_speed(speed)
        return False
    
    def set_mute(self, muted: bool) -> bool:
        """
        设置静音状态
        
        Args:
            muted: 是否静音
            
        Returns:
            bool: 操作是否成功
        """
        if self._mpv_core:
            return self._mpv_core.set_mute(muted)
        return False
    
    def set_loop_mode(self, mode: str) -> bool:
        """
        设置循环播放模式
        
        Args:
            mode: 循环模式 ("no", "yes", "playlist")
            
        Returns:
            bool: 操作是否成功
        """
        if self._mpv_core:
            return self._mpv_core.set_loop_mode(mode)
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
        if self._mpv_core:
            return self._mpv_core.is_playing()
        return False
    
    def get_position(self) -> float:
        """
        获取当前播放位置
        
        Returns:
            float: 当前位置（秒）
        """
        if self._mpv_core:
            return self._mpv_core.get_position() or 0.0
        return 0.0
    
    def get_duration(self) -> float:
        """
        获取视频总时长
        
        Returns:
            float: 总时长（秒）
        """
        if self._mpv_core:
            return self._mpv_core.get_duration() or 0.0
        return 0.0
    
    def get_video_size(self) -> tuple:
        """
        获取视频尺寸
        
        Returns:
            tuple: (宽度, 高度)
        """
        if self._mpv_core:
            return self._mpv_core.get_video_size()
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
        if self._mpv_core:
            return self._mpv_core.take_screenshot(file_path, include_subtitles)
        return False
    
    def set_detached(self, detached: bool):
        """
        设置窗口分离状态
        
        Args:
            detached: 是否已分离
        """
        self._is_detached = detached
        self._control_bar.set_detached(detached)
    
    def is_detached(self) -> bool:
        """
        获取窗口分离状态
        
        Returns:
            bool: 是否已分离
        """
        return self._is_detached
    
    def set_placeholder_message(self, message: str):
        """
        设置占位符提示消息
        
        Args:
            message: 提示消息
        """
        self._placeholder.set_message(message)
    
    def load_media(self, file_path: str) -> bool:
        """
        加载媒体文件（load_file的别名，用于兼容UnifiedPreviewer）
        
        Args:
            file_path: 媒体文件路径
            
        Returns:
            bool: 加载是否成功
        """
        return self.load_file(file_path)
    
    def toggle_play_pause(self) -> bool:
        """
        切换播放/暂停状态

        Returns:
            bool: 操作是否成功
        """
        if self._mpv_core:
            if self._mpv_core.is_paused() or not self._mpv_core.is_playing():
                return self.play()
            else:
                return self.pause()
        return False
    
    def update_style(self):
        """更新样式，用于主题变化时调用"""
        self._control_bar.update_style()
    
    def closeEvent(self, event):
        """
        关闭事件处理
        确保分离窗口正确关闭并清理资源
        """
        # 如果处于分离状态，先返回原窗口
        if self._is_detached:
            self._reattach_to_parent()
        
        # 关闭MPV核心
        if self._mpv_core:
            self._mpv_core.close()
        
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

        # 通知MPV核心更新几何尺寸
        if self._mpv_core:
            self._mpv_core.set_geometry(x, y, width, height)

    def resizeEvent(self, event):
        """
        窗口尺寸变化事件处理
        确保MPV渲染尺寸与Qt窗口尺寸同步
        """
        super().resizeEvent(event)
        # 当窗口尺寸变化时，同步MPV窗口尺寸
        if self._mpv_core and self._is_mpv_embedded and hasattr(self, '_video_surface'):
            self._sync_mpv_geometry()
