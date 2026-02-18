#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

播放器控制栏组件
提供视频播放器的完整控制界面，包括播放/暂停、进度条、音量、速度、循环和LUT控制
"""

import os
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QApplication,
    QSizePolicy, QFrame, QGraphicsDropShadowEffect
)
from PySide6.QtGui import QEnterEvent
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, Property, QSize
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPixmap

from .progress_widgets import D_ProgressBar
from .button_widgets import CustomButton
from .D_volume_control import DVolumeControl
from .dropdown_menu import CustomDropdownMenu
from .lut_manager_dialog import LutManagerDialog


class PlayerControlBar(QWidget):
    """
    播放器控制栏组件

    提供完整的视频播放控制界面，包括：
    - 播放/暂停按钮
    - 进度条（支持拖拽和点击跳转）
    - 当前时间/总时长显示
    - 音量控制（带悬浮菜单）
    - LUT加载控制
    - 分离窗口按钮

    Signals:
        playPauseClicked: 播放/暂停按钮点击信号
        progressChanged: 进度变化信号 (value: int)
        userInteractStarted: 用户开始交互信号
        userInteractEnded: 用户结束交互信号
        volumeChanged: 音量变化信号 (volume: int)
        muteChanged: 静音状态变化信号 (muted: bool)
        loadLutClicked: 加载LUT按钮点击信号
        detachClicked: 分离窗口按钮点击信号
        speedChanged: 倍速变化信号 (speed: float)
        lutSelected: LUT选择信号 (lut_path: str)
        lutCleared: LUT清除信号
    """

    playPauseClicked = Signal()
    progressChanged = Signal(int)
    userInteractStarted = Signal()
    userInteractEnded = Signal()
    volumeChanged = Signal(int)
    muteChanged = Signal(bool)
    loadLutClicked = Signal()
    detachClicked = Signal()
    speedChanged = Signal(float)
    lutSelected = Signal(str)
    lutCleared = Signal()
    
    def __init__(self, parent=None, show_lut_controls: bool = True, show_detach_button: bool = True):
        """
        初始化播放器控制栏
        
        Args:
            parent: 父控件
            show_lut_controls: 是否显示LUT相关控制按钮
            show_detach_button: 是否显示分离窗口按钮
        """
        super().__init__(parent)
        
        app = QApplication.instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.global_font = getattr(app, 'global_font', QFont())
        
        self._is_playing = False
        self._current_position = 0.0
        self._duration = 0.0
        self._volume = 100
        self._is_muted = False
        self._is_seeking = False
        self._user_interacting = False
        self._is_detached = False
        self._is_lut_loaded = False
        self._speed = 1.0  # 当前播放倍速
        self._block_volume_signal = False  # 用于阻止音量信号循环
        self._block_speed_signal = False   # 用于阻止倍速信号循环

        self._show_lut_controls = show_lut_controls
        self._show_detach_button = show_detach_button

        # 音量控制防抖定时器
        self._volume_debounce_timer = QTimer(self)
        self._volume_debounce_timer.setSingleShot(True)
        self._volume_debounce_timer.timeout.connect(self._emit_volume_changed)
        self._pending_volume = None

        self._init_ui()
        self._connect_signals()
        self._update_style()
    
    def _init_ui(self):
        """初始化UI组件"""
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: transparent;")

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        control_container = QWidget()
        scaled_border_radius = int(17.5 * self.dpi_scale)
        control_container.setStyleSheet(
            f"background-color: transparent; border: none; "
            f"border-radius: {scaled_border_radius}px;"
        )
        self.control_layout = QHBoxLayout(control_container)
        scaled_margin = int(7.5 * self.dpi_scale)
        scaled_spacing = int(7.5 * self.dpi_scale)
        self.control_layout.setContentsMargins(
            scaled_margin, scaled_margin, scaled_margin, scaled_margin
        )
        self.control_layout.setSpacing(scaled_spacing)

        self._play_button = self._create_icon_button(
            "播放时.svg",
            "暂停时.svg",
            tooltip_text="播放/暂停",
            height=20,
            button_type="primary"
        )
        self.control_layout.addWidget(self._play_button)

        progress_time_container = QWidget()
        progress_time_container.setStyleSheet("background-color: transparent; border: none;")
        progress_time_layout = QVBoxLayout(progress_time_container)
        progress_time_layout.setContentsMargins(0, 0, 0, 0)
        progress_time_layout.setSpacing(2)

        self._progress_bar = D_ProgressBar(
            orientation=D_ProgressBar.Horizontal,
            is_interactive=True
        )
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setAnimationEasingCurve(QEasingCurve(QEasingCurve.Linear))
        self._progress_bar.setAnimationDuration(200)
        self._progress_bar.setAnimationEnabled(True)
        progress_time_layout.addWidget(self._progress_bar)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        scaled_spacing = int(5 * self.dpi_scale)
        bottom_layout.setSpacing(scaled_spacing)

        self._time_label = QLabel("00:00 / 00:00")
        self._time_label.setFont(self.global_font)
        self._time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        scaled_padding = int(2.5 * self.dpi_scale)
        # 字体大小和颜色由 _update_style 方法从设置中动态获取并设置
        self._time_label.setStyleSheet(
            f"QLabel {{ background-color: transparent; "
            f"padding: 0 {scaled_padding}px; border: none; }}"
        )
        bottom_layout.addWidget(self._time_label)

        bottom_layout.addStretch(1)

        # 音量控制按钮
        self._volume_control = DVolumeControl(self)
        self._volume_control.set_volume(self._volume)
        bottom_layout.addWidget(self._volume_control)

        # 倍速按钮
        self._speed_button = self._create_icon_button(
            "speed.svg",
            tooltip_text="播放倍速",
            height=20,
            button_type="normal"
        )
        bottom_layout.addWidget(self._speed_button)

        # 倍速下拉菜单
        self._speed_menu = CustomDropdownMenu(self, position="top", use_internal_button=False)
        scaled_speed_width = int(60 * self.dpi_scale)
        self._speed_menu.set_fixed_width(scaled_speed_width)
        speed_items = [
            {"text": "0.5x", "data": 0.5},
            {"text": "0.75x", "data": 0.75},
            {"text": "1.0x", "data": 1.0},
            {"text": "1.25x", "data": 1.25},
            {"text": "1.5x", "data": 1.5},
            {"text": "2.0x", "data": 2.0},
            {"text": "3.0x", "data": 3.0}
        ]
        self._speed_menu.set_items(speed_items, default_item=speed_items[2])  # 默认1.0x
        self._speed_menu.set_target_button(self._speed_button)
        self._speed_menu.itemClicked.connect(self._on_speed_item_clicked)

        if self._show_lut_controls:
            self._lut_button = self._create_icon_button(
                "lut.svg",
                tooltip_text="加载LUT",
                height=20
            )
            bottom_layout.addWidget(self._lut_button)

        if self._show_detach_button:
            self._detach_button = self._create_icon_button(
                "maxsize.svg",
                alt_icon_name="minisize.svg",
                tooltip_text="分离窗口",
                height=20
            )
            bottom_layout.addWidget(self._detach_button)

        progress_time_layout.addLayout(bottom_layout)

        self.control_layout.addWidget(progress_time_container, 1)

        main_layout.addWidget(control_container)

        self.setMinimumHeight(int(40 * self.dpi_scale))
        self.setMaximumHeight(int(60 * self.dpi_scale))
    
    def _create_icon_button(self, icon_name: str, alt_icon_name: str = None, tooltip_text: str = "", height: int = 20, button_type: str = "normal") -> CustomButton:
        """
        创建图标按钮

        Args:
            icon_name: 主图标文件名
            alt_icon_name: 备用图标文件名（用于切换状态）
            tooltip_text: 提示文本
            height: 按钮高度（默认24，会自动应用DPI缩放）
            button_type: 按钮类型，可选值："primary"（强调色）、"normal"（普通样式）

        Returns:
            CustomButton: 图标按钮
        """
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        icon_path = os.path.join(icon_dir, icon_name)

        # 使用与文件选择器相同的创建方式，传入height参数
        button = CustomButton(
            icon_path,
            button_type=button_type,
            display_mode="icon",
            height=height,
            tooltip_text=tooltip_text
        )

        button._alt_icon_name = alt_icon_name
        button._primary_icon_name = icon_name

        return button
    
    def _connect_signals(self):
        """连接信号槽"""
        self._play_button.clicked.connect(self._on_play_button_clicked)

        self._progress_bar.valueChanged.connect(self._on_progress_value_changed)
        self._progress_bar.userInteracting.connect(self._on_user_interacting_start)
        self._progress_bar.userInteractionEnded.connect(self._on_user_interacting_end)

        # 音量控制信号
        self._volume_control.valueChanged.connect(self._on_volume_value_changed)
        self._volume_control.mutedChanged.connect(self._on_mute_changed)

        # 倍速按钮信号
        self._speed_button.clicked.connect(self._on_speed_button_clicked)

        if self._show_lut_controls:
            self._lut_button.clicked.connect(self._on_lut_button_clicked)

        if self._show_detach_button:
            self._detach_button.clicked.connect(self._on_detach_button_clicked)
    
    def _update_style(self):
        """更新样式"""
        app = QApplication.instance()

        # 更新全局字体，确保使用settings.json中定义的字体大小
        self.global_font = getattr(app, 'global_font', QFont())
        self._time_label.setFont(self.global_font)

        if hasattr(app, 'settings_manager'):
            settings_manager = app.settings_manager
            # 从设置中获取 second color 作为字体颜色
            text_color = settings_manager.get_setting(
                "appearance.colors.secondary_color", "#FFFFFF"
            )
        else:
            text_color = "#FFFFFF"

        # 样式表中只设置颜色，不设置字体大小（字体大小由setFont控制）
        self._time_label.setStyleSheet(
            f"QLabel {{ color: {text_color}; "
            f"font-weight: normal; background-color: transparent; }}"
        )

        # 更新播放按钮图标
        if hasattr(self, '_play_button'):
            self._update_play_button_icon()
    
    def _format_time(self, seconds: float) -> str:
        """
        格式化时间显示
        
        Args:
            seconds: 秒数
            
        Returns:
            str: 格式化的时间字符串 (MM:SS 或 HH:MM:SS)
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
    
    def _update_time_display(self):
        """更新时间显示"""
        current_str = self._format_time(self._current_position)
        duration_str = self._format_time(self._duration)
        self._time_label.setText(f"{current_str} / {duration_str}")
    
    def _update_progress_bar(self):
        """更新进度条"""
        if not self._user_interacting:
            if self._duration > 0:
                progress = int((self._current_position / self._duration) * 1000)
            else:
                progress = 0
            
            self._progress_bar.setValue(progress, use_animation=True)
    
    def _update_play_button_icon(self):
        """更新播放按钮图标"""
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        
        if self._is_playing:
            icon_name = self._play_button._alt_icon_name or "暂停时.svg"
        else:
            icon_name = self._play_button._primary_icon_name or "播放时.svg"
        
        icon_path = os.path.join(icon_dir, icon_name)
        self._play_button._icon_path = icon_path
        self._play_button.update()
    
    def _on_play_button_clicked(self):
        """播放按钮点击处理"""
        self.playPauseClicked.emit()
    
    def _on_progress_value_changed(self, value: int):
        """进度条值变化处理"""
        self.progressChanged.emit(value)
    
    def _on_user_interacting_start(self):
        """用户开始交互处理"""
        self._user_interacting = True
        self.userInteractStarted.emit()
    
    def _on_user_interacting_end(self):
        """用户结束交互处理"""
        self._user_interacting = False
        self.userInteractEnded.emit()

    def _on_lut_button_clicked(self):
        """LUT按钮点击处理"""
        # 打开LUT管理弹窗
        self._open_lut_manager_dialog()
    
    def _open_lut_manager_dialog(self):
        """打开LUT管理弹窗"""
        # 获取设置管理器
        app = QApplication.instance()
        settings_manager = getattr(app, 'settings_manager', None)
        
        # 创建并显示LUT管理弹窗
        dialog = LutManagerDialog(self, settings_manager)
        dialog.lutSelected.connect(self._on_lut_selected)
        dialog.lutCleared.connect(self._on_lut_cleared)
        
        dialog.exec()
    
    def _on_lut_selected(self, lut_path: str):
        """LUT选择处理"""
        self._is_lut_loaded = True
        self._update_lut_button_style()
        self.lutSelected.emit(lut_path)
    
    def _on_lut_cleared(self):
        """LUT清除处理"""
        self._is_lut_loaded = False
        self._update_lut_button_style()
        self.lutCleared.emit()
    
    def _update_lut_button_style(self):
        """更新LUT按钮样式（根据LUT加载状态）"""
        if not hasattr(self, '_lut_button'):
            return
        
        # 根据LUT状态设置按钮高亮
        if self._is_lut_loaded:
            # LUT已加载，使用强调样式
            self._lut_button.set_button_type("primary")
        else:
            # LUT未加载，使用普通样式
            self._lut_button.set_button_type("normal")
        
        self._lut_button.update()
    
    def set_lut_loaded(self, loaded: bool):
        """
        设置LUT加载状态
        
        Args:
            loaded: 是否已加载LUT
        """
        self._is_lut_loaded = loaded
        self._update_lut_button_style()

    def _on_detach_button_clicked(self):
        """分离窗口按钮点击处理"""
        self.detachClicked.emit()

    def _on_volume_value_changed(self, value: int):
        """
        音量值变化处理（带防抖机制）

        Args:
            value: 新的音量值（0-100）
        """
        self._volume = value
        self._pending_volume = value
        # 使用防抖定时器，延迟50ms发射信号，避免高频操作导致卡顿
        self._volume_debounce_timer.start(50)

    def _emit_volume_changed(self):
        """发射音量变化信号（防抖后）"""
        if self._pending_volume is not None:
            self.volumeChanged.emit(self._pending_volume)
            self._pending_volume = None

    def _on_mute_changed(self, muted: bool):
        """
        静音状态变化处理

        Args:
            muted: 是否静音
        """
        self._is_muted = muted
        self.muteChanged.emit(muted)

    def _on_speed_button_clicked(self):
        """倍速按钮点击处理"""
        self._speed_menu.set_target_button(self._speed_button)
        self._speed_menu.show_menu()

    def _on_speed_item_clicked(self, speed: float):
        """
        倍速选项点击处理

        Args:
            speed: 选中的倍速值
        """
        self.set_speed(speed)

    def set_playing(self, is_playing: bool):
        """
        设置播放状态
        
        Args:
            is_playing: 是否正在播放
        """
        if self._is_playing != is_playing:
            self._is_playing = is_playing
            self._update_play_button_icon()
    
    def set_progress(self, value: int, use_animation: bool = True):
        """
        设置进度条值
        
        Args:
            value: 进度值（0-1000）
            use_animation: 是否使用动画，默认为 True
        """
        self._progress_bar.setValue(value, use_animation=use_animation)
    
    def set_range(self, minimum: int, maximum: int):
        """
        设置进度条范围
        
        Args:
            minimum: 最小值
            maximum: 最大值
        """
        self._progress_bar.setRange(minimum, maximum)
    
    def set_time_text(self, current: str, duration: str):
        """
        设置时间显示文本
        
        Args:
            current: 当前时间字符串
            duration: 总时长字符串
        """
        self._time_label.setText(f"{current} / {duration}")
    
    def set_position(self, position: float, duration: float = None):
        """
        设置播放位置
        
        Args:
            position: 当前位置（秒）
            duration: 总时长（秒），可选
        """
        self._current_position = max(0, position)
        
        if duration is not None:
            self._duration = max(0, duration)
        
        self._update_time_display()
        self._update_progress_bar()
    
    def set_duration(self, duration: float):
        """
        设置总时长
        
        Args:
            duration: 总时长（秒）
        """
        self._duration = max(0, duration)
        self._update_time_display()
    
    def set_volume(self, volume: int, emit_signal: bool = True):
        """
        设置音量

        Args:
            volume: 音量值（0-100）
            emit_signal: 是否发射volumeChanged信号，默认为True
                        当从MPV回调更新UI时设置为False以避免循环
        """
        volume = max(0, min(100, volume))
        if self._volume != volume:
            self._volume = volume
            # 停止防抖定时器，避免外部设置音量时与防抖信号冲突
            self._volume_debounce_timer.stop()
            self._pending_volume = None
            # 同步更新音量控制组件显示
            if hasattr(self, '_volume_control'):
                self._volume_control.set_volume(volume)
            # 仅在允许时发射信号，避免循环触发
            if emit_signal and not self._block_volume_signal:
                self.volumeChanged.emit(volume)

    def set_muted(self, muted: bool):
        """
        设置静音状态

        Args:
            muted: 是否静音
        """
        if self._is_muted != muted:
            self._is_muted = muted
            # 同步更新音量控制组件显示
            if hasattr(self, '_volume_control'):
                self._volume_control.set_muted(muted)
            self.muteChanged.emit(muted)

    def set_speed(self, speed: float, emit_signal: bool = True):
        """
        设置播放倍速

        Args:
            speed: 倍速值
            emit_signal: 是否发射speedChanged信号，默认为True
                        当从MPV回调更新UI时设置为False以避免循环
        """
        old_speed = self._speed
        self._speed = speed
        # 同步更新下拉菜单选中项
        if hasattr(self, '_speed_menu'):
            # 查找对应的选项并设置为当前选中
            for item in self._speed_menu._items:
                if item.get('data') == speed:
                    self._speed_menu.set_current_item(item)
                    break
        # 无论速度值是否变化，都更新按钮样式，确保每次都检查当前速度是否为1.0
        self._update_speed_button_style()
        # 仅在速度值变化且允许时发射信号，避免循环触发
        if old_speed != speed and emit_signal and not self._block_speed_signal:
            self.speedChanged.emit(speed)

    def _update_speed_button_style(self):
        """更新倍速按钮样式（根据当前倍速切换普通/强调样式）"""
        if hasattr(self, '_speed_button'):
            # 倍速不为1.0时使用强调样式，否则使用普通样式
            button_type = "primary" if self._speed != 1.0 else "normal"
            self._speed_button.set_button_type(button_type)
            self._speed_button.update_style()

    def get_speed(self) -> float:
        """获取当前播放倍速"""
        return self._speed

    def set_detached(self, detached: bool):
        """
        设置分离状态，同时更新分离按钮图标
        
        Args:
            detached: 是否已分离
        """
        self._is_detached = detached
        self._update_detach_button_icon()
    
    def _update_detach_button_icon(self):
        """更新分离按钮图标"""
        if not hasattr(self, '_detach_button') or not self._detach_button:
            return
        
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        
        if self._is_detached:
            # 分离状态下显示"收缩"图标（minisize.svg）
            icon_name = self._detach_button._alt_icon_name or "minisize.svg"
            tooltip_text = "返回原窗口"
        else:
            # 非分离状态下显示"扩展"图标（maxsize.svg）
            icon_name = self._detach_button._primary_icon_name or "maxsize.svg"
            tooltip_text = "分离窗口"
        
        icon_path = os.path.join(icon_dir, icon_name)
        self._detach_button._icon_path = icon_path
        self._detach_button.setToolTip(tooltip_text)
        self._detach_button.update()
    
    def set_detach_button_visible(self, visible: bool):
        """
        设置分离按钮可见性
        
        Args:
            visible: 是否可见
        """
        if hasattr(self, '_detach_button') and self._detach_button:
            self._detach_button.setVisible(visible)
    
    def set_lut_loaded(self, loaded: bool):
        """
        设置LUT加载状态
        
        Args:
            loaded: 是否已加载LUT
        """
        self._is_lut_loaded = loaded
    
    def is_lut_loaded(self) -> bool:
        """获取LUT加载状态"""
        return self._is_lut_loaded
    
    def get_volume(self) -> int:
        """获取当前音量"""
        return self._volume

    def get_loop_mode(self) -> str:
        """获取当前循环模式"""
        return self._loop_mode
    
    def is_playing(self) -> bool:
        """获取播放状态"""
        return self._is_playing
    
    def is_detached(self) -> bool:
        """获取分离状态"""
        return self._is_detached
    
    def update_style(self):
        """更新主题样式"""
        self._update_style()
        self._progress_bar.update()
        self._update_play_button_icon()
        # 更新所有按钮的样式
        if hasattr(self, '_play_button'):
            self._play_button.update_style()
        if hasattr(self, '_loop_button'):
            self._loop_button.update_style()
        if hasattr(self, '_speed_label'):
            self._speed_label.update_style()
        if self._show_lut_controls and hasattr(self, '_lut_button'):
            self._lut_button.update_style()
        if self._show_detach_button and hasattr(self, '_detach_button'):
            self._detach_button.update_style()
        # 更新音量控制组件样式
        if hasattr(self, '_volume_control'):
            self._volume_control.update_style()
        # 更新倍速按钮样式
        if hasattr(self, '_speed_button'):
            self._update_speed_button_style()
    
    def hideEvent(self, event):
        """隐藏事件"""
        super().hideEvent(event)
        self.collapse_all_menus()
    
    def collapse_all_menus(self):
        """
        收起所有展开的菜单
        包括倍速菜单和音量菜单
        """
        # 收起倍速菜单
        if hasattr(self, '_speed_menu'):
            self._speed_menu.hide_menu()
        
        # 收起音量菜单
        if hasattr(self, '_volume_control'):
            self._volume_control._hide_volume_menu()
