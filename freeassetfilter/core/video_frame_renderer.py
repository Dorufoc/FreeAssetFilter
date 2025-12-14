#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

视频帧渲染组件
基于QOpenGLWidget实现，用于高效显示ffmpeg解码后的视频帧
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QPixmap, QImage
from PyQt5.QtCore import Qt, pyqtSignal, QSize
import numpy as np


class VideoFrameRenderer(QWidget):
    """
    视频帧渲染组件
    用于高效显示ffmpeg解码后的视频帧
    """
    
    # 信号定义
    size_changed = pyqtSignal(int, int)  # 视频尺寸变化
    
    def __init__(self, parent=None):
        """
        初始化视频帧渲染组件
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        # 设置窗口属性
        self.setWindowTitle("Video Frame Renderer")
        self.setMinimumSize(400, 300)
        
        # 当前显示的图像
        self._current_pixmap = QPixmap()
        
        # 当前视频尺寸
        self._video_width = 0
        self._video_height = 0
        
        # 缩放模式
        self._scale_mode = Qt.KeepAspectRatio
        
        # 设置背景颜色
        self.setStyleSheet("background-color: black;")
    
    def set_scale_mode(self, mode):
        """
        设置缩放模式
        
        Args:
            mode: Qt.KeepAspectRatio, Qt.KeepAspectRatioByExpanding, Qt.IgnoreAspectRatio
        """
        self._scale_mode = mode
        self.update()
    
    def render_frame(self, frame: np.ndarray):
        """
        渲染视频帧
        
        Args:
            frame (np.ndarray): 视频帧数据，形状为 (height, width, 3)，格式为BGR
        """
        if frame is None or frame.size == 0:
            return
        
        # 获取视频帧尺寸
        height, width, channels = frame.shape
        
        # 检查是否需要更新视频尺寸
        if width != self._video_width or height != self._video_height:
            self._video_width = width
            self._video_height = height
            # 发送尺寸变化信号
            self.size_changed.emit(width, height)
        
        # 将BGR格式转换为RGB格式
        rgb_frame = np.ascontiguousarray(frame[:, :, ::-1])
        
        # 创建QImage对象
        image = QImage(
            rgb_frame.data,
            width,
            height,
            rgb_frame.strides[0],  # 每行的字节数
            QImage.Format_RGB888
        )
        
        # 转换为QPixmap
        self._current_pixmap = QPixmap.fromImage(image)
        
        # 更新UI
        self.update()
    
    def clear(self):
        """
        清除当前显示的视频帧
        """
        self._current_pixmap = QPixmap()
        self.update()
    
    def paintEvent(self, event):
        """
        绘制事件
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # 填充背景为黑色
        painter.fillRect(self.rect(), Qt.black)
        
        # 如果没有图像，直接返回
        if self._current_pixmap.isNull():
            painter.end()
            return
        
        # 计算绘制区域，保持纵横比
        rect = self.rect()
        
        if self._scale_mode == Qt.KeepAspectRatio:
            # 保持纵横比，不超出窗口
            scaled_pixmap = self._current_pixmap.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            draw_rect = scaled_pixmap.rect()
            draw_rect.moveCenter(rect.center())
        elif self._scale_mode == Qt.KeepAspectRatioByExpanding:
            # 保持纵横比，填满窗口
            scaled_pixmap = self._current_pixmap.scaled(rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            draw_rect = scaled_pixmap.rect()
            draw_rect.moveCenter(rect.center())
        else:  # Qt.IgnoreAspectRatio
            # 忽略纵横比，拉伸填满窗口
            draw_rect = rect
            scaled_pixmap = self._current_pixmap.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        
        # 绘制图像
        painter.drawPixmap(draw_rect, scaled_pixmap)
        
        painter.end()
    
    def resizeEvent(self, event):
        """
        窗口大小变化事件
        """
        super().resizeEvent(event)
        self.update()
    
    @property
    def video_width(self):
        """
        获取当前视频宽度
        
        Returns:
            int: 视频宽度
        """
        return self._video_width
    
    @property
    def video_height(self):
        """
        获取当前视频高度
        
        Returns:
            int: 视频高度
        """
        return self._video_height
    
    def minimumSizeHint(self):
        """
        最小尺寸提示
        """
        return QSize(400, 300)
    
    def sizeHint(self):
        """
        推荐尺寸提示
        """
        if self._video_width > 0 and self._video_height > 0:
            return QSize(self._video_width, self._video_height)
        return QSize(800, 600)
