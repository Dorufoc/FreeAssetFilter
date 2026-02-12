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
提供独立的视频/音频播放器控制栏功能
"""

import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, Signal

from freeassetfilter.widgets.D_widgets import CustomButton
from freeassetfilter.widgets.progress_widgets import D_ProgressBar
from freeassetfilter.widgets.D_volume_control import DVolumeControl
from freeassetfilter.widgets.dropdown_menu import CustomDropdownMenu


class PlayerControlBar(QWidget):
    """
    播放器控制栏组件
    
    提供完整的播放器控制功能，包括：
    - 播放/暂停控制
    - 进度条显示和拖拽
    - 时间显示
    - 音量控制
    - 播放速度控制
    - LUT加载按钮
    - 对比预览按钮
    - 窗口分离按钮
    
    Signals:
        playPauseClicked: 播放/暂停按钮被点击
        progressChanged: 进度条值变化（用户拖拽）
        userInteractStarted: 用户开始与进度条交互
        userInteractEnded: 用户结束与进度条交互
        volumeChanged: 音量值变化
        muteChanged: 静音状态变化
        speedChanged: 播放速度变化
        loadLutClicked: 加载LUT按钮被点击
        comparisonClicked: 对比预览按钮被点击（携带checked状态）
        detachClicked: 分离窗口按钮被点击
    """
    
    # 信号定义
    playPauseClicked = Signal()
    progressChanged = Signal(int)
    userInteractStarted = Signal()
    userInteractEnded = Signal()
    volumeChanged = Signal(int)
    muteChanged = Signal(bool)
    speedChanged = Signal(float)
    loadLutClicked = Signal()
    comparisonClicked = Signal(bool)
    detachClicked = Signal()
    
    def __init__(self, parent=None, show_lut_controls=True):
        """
        初始化播放器控制栏
        
        Args:
            parent: 父窗口部件
            show_lut_controls: 是否显示LUT相关控制按钮（加载LUT、对比预览）
        """
        super().__init__(parent)
        
        # 获取应用实例和DPI缩放因子
        app = self._get_app_instance()
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        self.default_font_size = getattr(app, 'default_font_size', 10)
        self.global_font = getattr(app, 'global_font', QFont())
        
        # 设置组件字体
        self.setFont(self.global_font)
        
        # 状态属性
        self._is_playing = False
        self._current_volume = 100
        self._is_muted = False
        self._current_speed = 1.0
        self._show_lut_controls = show_lut_controls
        self._is_detached = False
        
        # 倍速选项
        self.speed_options = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0]
        
        # 图标路径
        self._init_icon_paths()
        
        # 初始化UI
        self._init_ui()
    
    def _get_app_instance(self):
        """获取应用实例"""
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()
    
    def _init_icon_paths(self):
        """初始化图标路径"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        icons_path = os.path.join(current_dir, '..', 'icons')
        icons_path = os.path.abspath(icons_path)
        
        self._play_icon_path = os.path.join(icons_path, '播放时.svg')
        self._pause_icon_path = os.path.join(icons_path, '暂停时.svg')
        self._maxsize_icon_path = os.path.join(icons_path, 'maxsize.svg')
        self._minisize_icon_path = os.path.join(icons_path, 'minisize.svg')
    
    def _init_ui(self):
        """初始化用户界面"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 控制栏容器
        control_container = QWidget()
        scaled_border_radius = int(17.5 * self.dpi_scale)
        control_container.setStyleSheet(
            f"background-color: transparent; border: none; "
            f"border-radius: {scaled_border_radius}px {scaled_border_radius}px "
            f"{scaled_border_radius}px {scaled_border_radius}px;"
        )
        
        self.control_layout = QHBoxLayout(control_container)
        scaled_margin = int(7.5 * self.dpi_scale)
        scaled_spacing = int(7.5 * self.dpi_scale)
        self.control_layout.setContentsMargins(scaled_margin, scaled_margin, 
                                               scaled_margin, scaled_margin)
        self.control_layout.setSpacing(scaled_spacing)
        
        # 创建播放按钮
        self._create_play_button()
        
        # 创建进度条和时间显示区域
        self._create_progress_area()
        
        # 添加控制区域到主布局
        main_layout.addWidget(control_container)
    
    def _create_play_button(self):
        """创建播放/暂停按钮"""
        self.play_button = CustomButton(
            text="",
            parent=self,
            button_type="primary",
            display_mode="icon"
        )
        
        self._update_play_button_icon()
        self.play_button.clicked.connect(self._on_play_button_clicked)
        self.control_layout.addWidget(self.play_button)
    
    def _create_progress_area(self):
        """创建进度条和时间显示区域"""
        # 进度和时间容器
        progress_time_container = QWidget()
        progress_time_container.setStyleSheet("background-color: transparent; border: none;")
        progress_time_layout = QVBoxLayout(progress_time_container)
        progress_time_layout.setContentsMargins(0, 0, 0, 0)
        progress_time_layout.setSpacing(2)
        
        # 进度条
        self.progress_slider = D_ProgressBar(is_interactive=True)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        self.progress_slider.valueChanged.connect(self._on_progress_changed)
        self.progress_slider.userInteracting.connect(self._on_user_interact_started)
        self.progress_slider.userInteractionEnded.connect(self._on_user_interact_ended)
        progress_time_layout.addWidget(self.progress_slider)
        
        # 底部布局（时间标签、音量、倍速等）
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(int(5 * self.dpi_scale))
        
        # 时间标签
        self.time_label = QLabel("00:00 / 00:00")
        scaled_time_font_size = int(self.default_font_size * 0.8 * self.dpi_scale)
        self.time_label.setStyleSheet(
            f"color: #666; font-size: {scaled_time_font_size}px; "
            f"background-color: transparent;"
        )
        self.time_label.setFont(self.global_font)
        bottom_layout.addWidget(self.time_label)
        
        # 添加弹性空间
        bottom_layout.addStretch(1)
        
        # 音量控制
        self._create_volume_control(bottom_layout)
        
        # 倍速控制
        self._create_speed_control(bottom_layout)
        
        # LUT控制按钮
        if self._show_lut_controls:
            self._create_lut_controls(bottom_layout)
        
        # 窗口分离按钮
        self._create_detach_button(bottom_layout)
        
        # 将底部布局添加到进度时间布局
        progress_time_layout.addLayout(bottom_layout)
        
        # 将进度时间容器添加到控制布局
        self.control_layout.addWidget(progress_time_container, 1)
    
    def _create_volume_control(self, parent_layout):
        """创建音量控制组件"""
        self.volume_control = DVolumeControl(self)
        self.volume_control.set_volume(self._current_volume)
        self.volume_control.valueChanged.connect(self._on_volume_changed)
        self.volume_control.mutedChanged.connect(self._on_mute_changed)
        self.volume_control._d_volume._progress_bar.userInteractionEnded.connect(
            self._on_volume_interaction_ended
        )
        parent_layout.addWidget(self.volume_control)
    
    def _create_speed_control(self, parent_layout):
        """创建倍速控制组件"""
        # 倍速下拉菜单
        self.speed_dropdown = CustomDropdownMenu(self, position="top")
        scaled_drive_width = int(40 * self.dpi_scale)
        self.speed_dropdown.set_fixed_width(scaled_drive_width)
        self.speed_dropdown.setParent(None)
        
        # 设置倍速选项
        speed_items = [f"{speed}x" for speed in self.speed_options]
        self.speed_dropdown.set_items(speed_items, default_item=f"{self._current_speed}x")
        self.speed_dropdown.set_current_item(f"{self._current_speed}x")
        self.speed_dropdown.itemClicked.connect(self._on_speed_selected)
        
        # 设置字体
        scaled_font_size = int(self.default_font_size * self.dpi_scale)
        speed_dropdown_font = QFont(self.global_font)
        speed_dropdown_font.setPointSize(scaled_font_size)
        self.speed_dropdown.setFont(speed_dropdown_font)
        
        # 倍速按钮
        self.speed_button = CustomButton(
            text=f"{self._current_speed}x",
            button_type="normal",
            display_mode="text",
            height=18
        )
        speed_button_height = int(18 * self.dpi_scale)
        self.speed_button.setFixedHeight(speed_button_height)
        self.speed_dropdown.set_target_button(self.speed_button)
        self.speed_button.clicked.connect(self._show_speed_menu)
        
        parent_layout.addWidget(self.speed_button)
    
    def _create_lut_controls(self, parent_layout):
        """创建LUT控制按钮"""
        # 加载LUT按钮
        self.load_cube_button = CustomButton(
            text="加载LUT",
            button_type="normal",
            display_mode="text",
            height=18
        )
        cube_button_size = int(18 * self.dpi_scale)
        self.load_cube_button.setFixedSize(cube_button_size, cube_button_size)
        self.load_cube_button.clicked.connect(self._on_load_lut_clicked)
        parent_layout.addWidget(self.load_cube_button)
        
        # 对比预览按钮
        self.comparison_button = CustomButton(
            text="对比预览",
            button_type="normal",
            display_mode="text",
            height=18
        )
        comparison_button_size = int(18 * self.dpi_scale)
        self.comparison_button.setFixedSize(comparison_button_size, comparison_button_size)
        self.comparison_button.setCheckable(True)
        self.comparison_button.clicked.connect(self._on_comparison_clicked)
        self.comparison_button.hide()  # 默认隐藏
        parent_layout.addWidget(self.comparison_button)
    
    def _create_detach_button(self, parent_layout):
        """创建窗口分离按钮"""
        icon_path = (self._minisize_icon_path if self._is_detached 
                     else self._maxsize_icon_path)
        tooltip = "恢复窗口" if self._is_detached else "分离窗口"
        
        self.detach_button = CustomButton(
            text=icon_path,
            button_type="normal",
            display_mode="icon",
            height=18,
            tooltip_text=tooltip
        )
        detached_button_size = int(18 * self.dpi_scale)
        self.detach_button.setFixedSize(detached_button_size, detached_button_size)
        self.detach_button.clicked.connect(self._on_detach_clicked)
        
        parent_layout.addWidget(self.detach_button)
    
    # ========== 事件处理回调 ==========
    
    def _on_play_button_clicked(self):
        """播放按钮点击处理"""
        self.playPauseClicked.emit()
    
    def _on_progress_changed(self, value):
        """进度条值变化处理"""
        self.progressChanged.emit(value)
    
    def _on_user_interact_started(self):
        """用户开始与进度条交互"""
        self.userInteractStarted.emit()
    
    def _on_user_interact_ended(self):
        """用户结束与进度条交互"""
        self.userInteractEnded.emit()
    
    def _on_volume_changed(self, value):
        """音量变化处理"""
        self._current_volume = value
        self.volumeChanged.emit(value)
    
    def _on_mute_changed(self, muted):
        """静音状态变化处理"""
        self._is_muted = muted
        self.muteChanged.emit(muted)
    
    def _on_volume_interaction_ended(self):
        """音量交互结束处理"""
        # 可以在这里添加音量设置保存逻辑
        pass
    
    def _on_speed_selected(self, speed_text):
        """倍速选择处理"""
        speed = float(speed_text.replace('x', ''))
        self._current_speed = speed
        self.speed_button.setText(f"{speed}x")
        self.speedChanged.emit(speed)
    
    def _show_speed_menu(self):
        """显示倍速菜单"""
        self.speed_dropdown.set_target_button(self.speed_button)
        self.speed_dropdown.show_menu()
    
    def _on_load_lut_clicked(self):
        """加载LUT按钮点击处理"""
        self.loadLutClicked.emit()
    
    def _on_comparison_clicked(self, checked):
        """对比预览按钮点击处理"""
        self.comparisonClicked.emit(checked)
    
    def _on_detach_clicked(self):
        """分离窗口按钮点击处理"""
        self.detachClicked.emit()
    
    # ========== 公共方法 ==========
    
    def set_playing(self, is_playing):
        """
        设置播放状态
        
        Args:
            is_playing: 是否正在播放
        """
        self._is_playing = is_playing
        self._update_play_button_icon()
    
    def _update_play_button_icon(self):
        """更新播放按钮图标"""
        icon_path = (self._pause_icon_path if self._is_playing 
                     else self._play_icon_path)
        
        if os.path.exists(icon_path):
            self.play_button._icon_path = icon_path
            self.play_button._display_mode = "icon"
            self.play_button._render_icon()
            self.play_button.update()
    
    def set_progress(self, value):
        """
        设置进度条值
        
        Args:
            value: 进度值 (0-1000)
        """
        self.progress_slider.setValue(value)
    
    def get_progress(self):
        """
        获取当前进度值
        
        Returns:
            int: 当前进度值 (0-1000)
        """
        return self.progress_slider.value()
    
    def set_time_text(self, current_time_str, duration_str):
        """
        设置时间显示文本
        
        Args:
            current_time_str: 当前时间字符串 (如 "01:23")
            duration_str: 总时长字符串 (如 "05:00")
        """
        self.time_label.setText(f"{current_time_str} / {duration_str}")
    
    def set_volume(self, volume):
        """
        设置音量
        
        Args:
            volume: 音量值 (0-100)
        """
        self._current_volume = volume
        self.volume_control.set_volume(volume)
    
    def get_volume(self):
        """
        获取当前音量
        
        Returns:
            int: 当前音量值 (0-100)
        """
        return self._current_volume
    
    def set_muted(self, muted):
        """
        设置静音状态
        
        Args:
            muted: 是否静音
        """
        self._is_muted = muted
        self.volume_control.set_muted(muted)
    
    def is_muted(self):
        """
        获取静音状态
        
        Returns:
            bool: 是否静音
        """
        return self._is_muted
    
    def set_speed(self, speed):
        """
        设置播放速度
        
        Args:
            speed: 播放速度 (如 1.0, 1.5, 2.0)
        """
        if speed in self.speed_options:
            self._current_speed = speed
            self.speed_button.setText(f"{speed}x")
            self.speed_dropdown.set_current_item(f"{speed}x")
    
    def get_speed(self):
        """
        获取当前播放速度
        
        Returns:
            float: 当前播放速度
        """
        return self._current_speed
    
    def set_lut_loaded(self, loaded):
        """
        设置LUT加载状态
        
        Args:
            loaded: 是否已加载LUT
        """
        if self._show_lut_controls:
            self.load_cube_button.set_button_type("primary" if loaded else "normal")
            self.comparison_button.setVisible(loaded)
    
    def is_lut_loaded(self):
        """
        获取LUT加载状态

        Returns:
            bool: 是否已加载LUT
        """
        if not self._show_lut_controls:
            return False
        return self.load_cube_button.button_type == "primary"
    
    def set_comparison_mode(self, enabled):
        """
        设置对比预览模式
        
        Args:
            enabled: 是否启用对比预览
        """
        if self._show_lut_controls:
            self.comparison_button.setChecked(enabled)
            self.comparison_button.set_button_type("primary" if enabled else "normal")
    
    def is_comparison_mode(self):
        """
        获取对比预览模式状态
        
        Returns:
            bool: 是否启用对比预览
        """
        if not self._show_lut_controls:
            return False
        return self.comparison_button.isChecked()
    
    def set_detached(self, detached):
        """
        设置窗口分离状态
        
        Args:
            detached: 是否已分离
        """
        self._is_detached = detached
        icon_path = (self._minisize_icon_path if detached 
                     else self._maxsize_icon_path)
        tooltip = "恢复窗口" if detached else "分离窗口"
        
        if os.path.exists(icon_path):
            self.detach_button._icon_path = icon_path
            self.detach_button._tooltip_text = tooltip
            self.detach_button._render_icon()
            self.detach_button.update()
    
    def is_detached(self):
        """
        获取窗口分离状态
        
        Returns:
            bool: 是否已分离
        """
        return self._is_detached
    
    def show_lut_controls(self, show=True):
        """
        显示/隐藏LUT控制按钮
        
        Args:
            show: 是否显示
        """
        if self._show_lut_controls:
            self.load_cube_button.setVisible(show)
            if not self.is_lut_loaded():
                self.comparison_button.hide()
    
    def update_style(self):
        """更新样式，用于主题变化时调用"""
        self.volume_control.update_style()
        self.play_button.update_style()
        self.speed_button.update_style()
        if self._show_lut_controls:
            self.load_cube_button.update_style()
            self.comparison_button.update_style()
        self.detach_button.update_style()

    def set_detach_button_visible(self, visible):
        """
        设置分离窗口按钮的显示/隐藏

        Args:
            visible: 是否显示
        """
        self.detach_button.setVisible(visible)
