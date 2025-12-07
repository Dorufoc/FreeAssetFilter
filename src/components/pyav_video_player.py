#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

基于PyAV的视频播放器组件
提供完整的视频播放功能和用户界面
"""

import sys
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel,
    QFileDialog, QMessageBox, QFrame, QStyle, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect
from PyQt5.QtGui import QIcon, QPixmap, QImage, QFont, QPainter, QColor, QBrush, QPen

# 尝试导入PyAV
PYAV_AVAILABLE = False
try:
    import av
    PYAV_AVAILABLE = True
except Exception as e:
    print(f"PyAV库不可用: {e}")


class FluentProgressBar(QWidget):
    """
    Fluent Design风格的进度条控件
    播放过程中仅作为展示，用户交互时才响应
    """
    valueChanged = pyqtSignal(int)  # 值变化信号
    userInteracting = pyqtSignal()  # 用户开始交互信号
    userInteractionEnded = pyqtSignal()  # 用户结束交互信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 8)  # 更细的进度条，符合Fluent Design
        self.setMaximumHeight(20)
        
        # 进度条属性
        self._minimum = 0
        self._maximum = 1000
        self._value = 0  # 当前播放进度值
        self._display_value = 0  # 显示的进度值（用于播放过程中的展示）
        self._is_pressed = False
        self._last_pos = 0
        self._is_interacting = False  # 是否正在进行用户交互
        
        # Fluent Design外观属性
        self._bg_color = QColor(68, 68, 68)  # 深灰色背景
        self._progress_color = QColor(0, 120, 215)  # Fluent蓝色进度
        self._handle_color = QColor(255, 255, 255)  # 白色滑块
        self._handle_hover_color = QColor(255, 255, 255)  # 白色滑块（悬停）
        self._handle_pressed_color = QColor(255, 255, 255)  # 白色滑块（按下）
        self._handle_border_color = QColor(0, 120, 215)  # 蓝色边框
        self._handle_shadow_color = QColor(0, 0, 0, 128)  # 阴影颜色
        self._handle_radius = 8  # 滑块半径
        self._bar_height = 4  # 更细的进度条高度
        self._bar_radius = 2  # 进度条圆角
    
    def setRange(self, minimum, maximum):
        """
        设置进度条范围
        """
        self._minimum = minimum
        self._maximum = maximum
        self._value = minimum
        self._display_value = minimum
        self.update()
    
    def setValue(self, value):
        """
        设置进度条值（仅更新显示，不触发事件）
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._display_value != value and not self._is_interacting:
            self._display_value = value
            self.update()
    
    def setInteractiveValue(self, value):
        """
        设置交互后的进度值（触发事件）
        """
        if value < self._minimum:
            value = self._minimum
        elif value > self._maximum:
            value = self._maximum
        
        if self._value != value:
            self._value = value
            self._display_value = value
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
            self._is_interacting = True
            self._last_pos = event.pos().x()
            self.userInteracting.emit()
            # 计算点击位置对应的进度值
            self._update_value_from_pos(event.pos().x())
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件
        """
        if self._is_pressed and self._is_interacting:
            self._last_pos = event.pos().x()
            self._update_value_from_pos(event.pos().x())
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件
        """
        if self._is_pressed and event.button() == Qt.LeftButton:
            self._is_pressed = False
            self._is_interacting = False
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
        self.setInteractiveValue(value)
    
    def paintEvent(self, event):
        """
        绘制Fluent Design风格的进度条
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 计算绘制区域
        rect = self.rect()
        bar_width = rect.width() - (self._handle_radius * 2)
        bar_y = (rect.height() - self._bar_height) // 2
        
        # 绘制背景
        bg_rect = QRect(
            self._handle_radius, bar_y, 
            bar_width, self._bar_height
        )
        painter.setBrush(QBrush(self._bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bg_rect, self._bar_radius, self._bar_radius)
        
        # 绘制已播放部分（使用_display_value，只用于展示）
        progress_width = int(bar_width * (self._display_value - self._minimum) / (self._maximum - self._minimum))
        progress_rect = QRect(
            self._handle_radius, bar_y, 
            progress_width, self._bar_height
        )
        painter.setBrush(QBrush(self._progress_color))
        painter.drawRoundedRect(progress_rect, self._bar_radius, self._bar_radius)
        
        # 绘制滑块阴影
        # 滑块位置始终对应_value（交互后的位置），而不是_display_value（展示的位置）
        handle_x = self._handle_radius + int(bar_width * (self._value - self._minimum) / (self._maximum - self._minimum))
        handle_y = (rect.height() - self._handle_radius * 2) // 2
        
        # 绘制阴影
        shadow_rect = QRect(
            handle_x - 2, handle_y - 2, 
            self._handle_radius * 2 + 4, self._handle_radius * 2 + 4
        )
        painter.setBrush(QBrush(self._handle_shadow_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(shadow_rect)
        
        # 绘制滑块边框
        border_rect = QRect(
            handle_x, handle_y, 
            self._handle_radius * 2, self._handle_radius * 2
        )
        painter.setBrush(QBrush(self._handle_border_color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(border_rect)
        
        # 绘制滑块内部
        inner_rect = QRect(
            handle_x + 2, handle_y + 2, 
            self._handle_radius * 2 - 4, self._handle_radius * 2 - 4
        )
        painter.setBrush(QBrush(self._handle_color))
        painter.drawEllipse(inner_rect)
        
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


class PyAVVideoPlayer(QWidget):
    """
    基于PyAV的视频播放器组件
    提供完整的视频播放功能和用户界面
    """
    
    def __init__(self, parent=None, show_warning=True):
        """
        初始化视频播放器组件
        
        Args:
            parent: 父窗口部件
            show_warning: 是否显示警告信息
        """
        super().__init__(parent)
        
        # 初始化UI组件引用
        self.video_label = None
        self.progress_slider = None
        self.time_label = None
        self.play_button = None
        self.volume_slider = None
        self.volume_label = None
        self.timer = None
        
        # 播放器状态
        self.is_playing = False
        self.is_paused = False
        self.current_file = None
        self.container = None
        self.video_stream = None
        self.audio_stream = None
        self.video_frame_iterator = None
        self.audio_frame_iterator = None
        self.current_frame = 0
        self.total_frames = 0
        self.current_time = 0  # 当前播放时间（秒）
        self.total_time = 0  # 总时长（秒）
        self.fps = 30.0
        self.loop = True
        self._user_interacting = False
        
        # 音频相关
        self.audio_format = None
        self.audio_sample_rate = None
        self.audio_channels = None
        self.audio_buffer = None
        self.audio_paused = False
        
        # 初始化UI
        self.init_ui()
        
        # 初始化播放器
        if not PYAV_AVAILABLE:
            if show_warning:
                QMessageBox.warning(self, "警告", "PyAV库不可用，视频播放功能不可用\n请安装PyAV包：pip install av")
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 视频显示区域
        self.video_label = QLabel()
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black;")
        self.video_label.setMinimumSize(640, 360)
        self.video_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.video_label)
        
        # 控制栏
        control_bar = QFrame()
        control_bar.setStyleSheet("background-color: #333;")
        control_bar.setMinimumHeight(50)
        control_layout = QHBoxLayout(control_bar)
        control_layout.setContentsMargins(10, 5, 10, 5)
        control_layout.setSpacing(10)
        
        # 播放/暂停按钮
        self.play_button = QPushButton()
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setStyleSheet("background-color: #444; color: white; border: none; border-radius: 4px; padding: 8px;")
        self.play_button.clicked.connect(self.toggle_play_pause)
        control_layout.addWidget(self.play_button)
        
        # 时间标签
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("color: white;")
        control_layout.addWidget(self.time_label)
        
        # 使用QT自带的QSlider作为进度条
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        self.progress_slider.setStyleSheet("QSlider::groove:horizontal { background-color: #444; height: 4px; border-radius: 2px; } QSlider::handle:horizontal { background-color: white; border: 2px solid #0078d4; width: 16px; height: 16px; border-radius: 8px; margin: -6px 0; } QSlider::sub-page:horizontal { background-color: #0078d4; height: 4px; border-radius: 2px; }")
        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        self.progress_slider.valueChanged.connect(self._on_slider_value_changed)
        control_layout.addWidget(self.progress_slider, 1)
        
        # 音量标签
        self.volume_label = QLabel("🔊")
        self.volume_label.setStyleSheet("color: white;")
        control_layout.addWidget(self.volume_label)
        
        # 音量滑块
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.setMaximumWidth(100)
        control_layout.addWidget(self.volume_slider)
        
        main_layout.addWidget(control_bar)
        
        # 定时器，用于更新进度
        self.timer = QTimer(self)
        self.timer.setInterval(500)  # 500ms更新一次
        self.timer.timeout.connect(self.update_progress)
    
    def set_file(self, file_path):
        """
        设置要播放的视频文件
        
        Args:
            file_path (str): 视频文件路径
        """
        if not PYAV_AVAILABLE:
            return
        
        try:
            # 停止当前播放并重置状态
            self.stop()
            
            # 打开新文件
            self.current_file = file_path
            self.container = av.open(file_path)
            
            # 获取视频流
            self.video_stream = next((s for s in self.container.streams if s.type == 'video'), None)
            if not self.video_stream:
                QMessageBox.warning(self, "警告", "未找到视频流")
                return
            
            # 获取音频流
            self.audio_stream = next((s for s in self.container.streams if s.type == 'audio'), None)
            
            # 获取视频信息
            self.total_frames = self.video_stream.frames if self.video_stream.frames > 0 else 0
            self.fps = self.video_stream.average_rate if self.video_stream.average_rate else 30.0
            self.total_time = self.container.duration / 1000000 if self.container.duration else 0
            
            # 初始化视频帧迭代器
            self.video_frame_iterator = self.container.decode(video=0)
            
            # 初始化音频帧迭代器（如果有音频流）
            self.audio_frame_iterator = None
            if self.audio_stream:
                self.audio_frame_iterator = self.container.decode(audio=0)
                # 获取音频格式信息
                self.audio_format = self.audio_stream.format
                self.audio_sample_rate = self.audio_stream.sample_rate
                self.audio_channels = self.audio_stream.channels
                print(f"音频流信息: 格式={self.audio_format}, 采样率={self.audio_sample_rate}, 声道数={self.audio_channels}")
            
            # 重置播放状态
            self.current_frame = 0
            self.current_time = 0
            self._user_interacting = False
            
            # 更新UI
            self.time_label.setText(f"00:00 / {self.format_time(self.total_time)}")
            self.progress_slider.setValue(0)
            
            # 播放第一帧
            self._play_frame()
            
        except Exception as e:
            print(f"设置视频文件时出错: {e}")
            QMessageBox.warning(self, "警告", f"无法打开视频文件: {str(e)}")
    
    def _play_frame(self):
        """
        播放一帧视频
        """
        if not self.is_playing or not self.container or not self.video_frame_iterator:
            return
        
        try:
            # 获取下一帧
            frame = next(self.video_frame_iterator, None)
            if frame is None:
                # 视频播放结束
                if self.loop:
                    # 循环播放
                    self.restart()
                else:
                    # 停止播放
                    self.stop()
                return
            
            # 更新播放时间和帧计数
            self.current_frame += 1
            self.current_time = frame.time if frame.time is not None else self.current_frame / self.fps
            
            # 转换为QImage并显示
            img = frame.to_image()
            qimg = QImage(img.tobytes(), img.width, img.height, img.width * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            
            # 调整大小以适应显示区域
            scaled_pixmap = pixmap.scaled(self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.video_label.setPixmap(scaled_pixmap)
            
            # 继续播放下一帧
            if self.is_playing:
                # 计算下一帧的延迟
                delay = int(1000 / self.fps)
                QTimer.singleShot(delay, self._play_frame)
        
        except StopIteration:
            # 视频播放结束
            if self.loop:
                # 循环播放
                self.restart()
            else:
                # 停止播放
                self.stop()
        except Exception as e:
            print(f"播放帧时出错: {e}")
            # 简化错误处理，不停止播放，尝试继续
            if self.is_playing:
                delay = int(1000 / self.fps)
                QTimer.singleShot(delay, self._play_frame)
    
    def update_progress(self):
        """
        更新播放进度（由定时器调用，与视频播放解耦）
        """
        try:
            if self.is_playing and self.total_time > 0:
                # 更新时间标签
                current_time = self.current_time
                total_time = self.total_time
                self.time_label.setText(f"{self.format_time(current_time)} / {self.format_time(total_time)}")
                
                # 更新进度条（仅显示，不触发事件）
                if not self._user_interacting:
                    position = int((current_time / total_time) * 1000)
                    self.progress_slider.setValue(position)
                
                # 检测视频是否播放完成，如果是且启用了循环播放，则重新播放
                if (current_time >= total_time - 0.5) and self.loop and self.is_playing:
                    # 重新播放当前视频
                    self.restart()
        except Exception as e:
            print(f"更新进度时出错: {e}")
    
    def toggle_play_pause(self):
        """
        切换播放/暂停状态
        """
        if self.is_playing:
            self.pause()
        else:
            self.play()
    
    def play(self):
        """
        开始播放
        """
        if not self.current_file or not self.container:
            return
        
        self.is_playing = True
        self.is_paused = False
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.timer.start()
        self._play_frame()
    
    def pause(self):
        """
        暂停播放
        """
        self.is_playing = False
        self.is_paused = True
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.timer.stop()
    
    def stop(self):
        """
        停止播放
        """
        self.is_playing = False
        self.is_paused = False
        self.audio_paused = False
        self.play_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.timer.stop()
        
        # 关闭容器
        if self.container:
            try:
                self.container.close()
            except Exception as e:
                print(f"关闭容器时出错: {e}")
            self.container = None
        
        # 重置视频相关变量
        self.video_stream = None
        self.audio_stream = None
        self.video_frame_iterator = None
        self.audio_frame_iterator = None
        self.current_frame = 0
        self.current_time = 0
        
        # 重置音频相关变量
        self.audio_buffer = None
        self.audio_format = None
        self.audio_sample_rate = None
        self.audio_channels = None
        
        # 清空视频显示
        self.video_label.clear()
        self.video_label.setStyleSheet("background-color: black;")
    
    def restart(self):
        """
        重新开始播放
        """
        if self.current_file:
            self.set_file(self.current_file)
            self.play()
    
    def set_loop(self, loop):
        """
        设置是否循环播放
        
        Args:
            loop (bool): 是否循环播放
        """
        self.loop = loop
    
    def seek(self, value):
        """
        跳转到指定位置
        
        Args:
            value (int): 位置值（0-1000）
        """
        if not self.current_file or self.total_time <= 0:
            return
        
        try:
            # 计算目标时间
            position = value / 1000.0
            target_time = position * self.total_time
            
            # 停止当前播放
            was_playing = self.is_playing
            self.is_playing = False
            
            # 关闭当前容器
            if self.container:
                self.container.close()
            
            # 重新打开文件
            self.container = av.open(self.current_file)
            
            # 重新获取流信息
            self.video_stream = next((s for s in self.container.streams if s.type == 'video'), None)
            self.audio_stream = next((s for s in self.container.streams if s.type == 'audio'), None)
            
            # 跳转到指定位置（微秒）
            self.container.seek(int(target_time * 1000000))
            
            # 重新初始化迭代器
            self.video_frame_iterator = self.container.decode(video=0)
            if self.audio_stream:
                self.audio_frame_iterator = self.container.decode(audio=0)
            
            # 更新当前时间和帧计数
            self.current_time = target_time
            self.current_frame = int(target_time * self.fps)
            
            # 更新UI
            self.time_label.setText(f"{self.format_time(target_time)} / {self.format_time(self.total_time)}")
            self.progress_slider.setValue(value)
            
            # 播放第一帧
            self._play_frame()
            
            # 如果之前在播放，继续播放
            if was_playing:
                self.is_playing = True
                self.timer.start()
                self._play_frame()
        except Exception as e:
            print(f"跳转位置时出错: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_slider_pressed(self):
        """
        进度条被按下时的处理
        """
        self._user_interacting = True
        # 暂停定时器，避免进度更新干扰用户交互
        if self.timer.isActive():
            self.timer.stop()
    
    def _on_slider_released(self):
        """
        进度条被释放时的处理
        """
        # 获取最终位置并跳转到对应位置
        value = self.progress_slider.value()
        self.seek(value)
        
        # 恢复播放和定时器
        self._user_interacting = False
        if self.is_playing:
            self.timer.start()
    
    def _on_slider_value_changed(self, value):
        """
        进度条值变化时的处理
        """
        if self._user_interacting and self.total_time > 0:
            # 用户正在拖动进度条，只更新时间显示
            position = value / 1000.0
            seek_time = position * self.total_time
            self.time_label.setText(f"{self.format_time(seek_time)} / {self.format_time(self.total_time)}")
    
    @staticmethod
    def format_time(seconds):
        """
        格式化时间
        
        Args:
            seconds (float): 秒数
            
        Returns:
            str: 格式化后的时间字符串 (mm:ss)
        """
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def set_volume(self, value):
        """
        设置音量（PyAV视频播放暂时不支持音量控制）
        
        Args:
            value (int): 音量值（0-100）
        """
        pass
    
    def closeEvent(self, event):
        """
        窗口关闭事件
        """
        self.stop()
        event.accept()


# 测试代码
if __name__ == "__main__":
    from PyQt5.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    player = PyAVVideoPlayer()
    player.show()
    
    # 测试播放视频
    if len(sys.argv) > 1:
        player.set_file(sys.argv[1])
    
    sys.exit(app.exec_())
