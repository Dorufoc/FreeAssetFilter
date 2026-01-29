#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源

流体渐变背景组件
为视频播放器提供沉浸式动态背景效果
使用QWidget + QPainter绘制，性能优化版
"""

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QTimer, QPointF, pyqtSignal, QRect
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QBrush, QLinearGradient


class FluidGradientBackground(QWidget):
    """
    流体渐变背景组件
    使用QPainter绘制苹果音乐风格的流体渐变效果
    
    Features:
        - 多层渐变叠加动画
        - 主题切换支持（日落、海洋、极光）
        - 动画速率控制
        - 暂停/恢复功能
        - 性能优化：使用QPainter而非WebEngine
    """
    
    themeChanged = pyqtSignal(str)
    speedChanged = pyqtSignal(float)
    
    def __init__(self, parent=None):
        """
        初始化流体渐变背景组件
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        self._current_theme = 'sunset'
        self._animation_speed = 1.0
        self._is_paused = False
        self._is_loaded = False
        self._animation_timer = None
        
        self._theme_colors = {
            'sunset': [
                QColor(255, 107, 107),
                QColor(254, 202, 87),
                QColor(255, 159, 243),
                QColor(243, 104, 224),
                QColor(255, 71, 87)
            ],
            'ocean': [
                QColor(10, 189, 227),
                QColor(16, 172, 132),
                QColor(0, 210, 211),
                QColor(84, 160, 255),
                QColor(46, 134, 222)
            ],
            'aurora': [
                QColor(0, 255, 135),
                QColor(94, 239, 255),
                QColor(0, 97, 255),
                QColor(255, 0, 255),
                QColor(0, 255, 204)
            ]
        }
        
        self._gradient_centers = []
        self._gradient_radii = []
        self._gradient_velocities = []
        self._initialize_gradients()
        
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")
        self.setVisible(False)
    
    def _initialize_gradients(self):
        """初始化渐变参数"""
        self._gradient_centers = [
            QPointF(0.5, 0.5),
            QPointF(0.2, 0.3),
            QPointF(0.8, 0.2),
            QPointF(0.4, 0.7),
            QPointF(0.7, 0.8),
            QPointF(0.3, 0.6),
            QPointF(0.6, 0.4),
            QPointF(0.1, 0.8),
            QPointF(0.9, 0.5),
            QPointF(0.5, 0.1)
        ]
        
        self._gradient_radii = [
            0.8, 0.7, 0.75, 0.65, 0.7,
            0.85, 0.6, 0.9, 0.55, 0.8
        ]
        
        self._gradient_velocities = [
            (0.0003, 0.0002),
            (-0.00025, 0.0003),
            (0.00035, -0.0002),
            (-0.0002, 0.00035),
            (0.0004, 0.00025),
            (-0.00035, -0.0003),
            (0.00025, 0.0004),
            (-0.0003, 0.00035),
            (0.0003, -0.00025),
            (-0.00025, -0.00035)
        ]
    
    def load(self):
        """加载背景（延迟初始化）"""
        if self._is_loaded:
            return
        
        self._is_loaded = True
        self.setVisible(True)
        
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._update_animation)
        self._animation_timer.start(16)
        
        self.update()
    
    def unload(self):
        """卸载背景（释放资源）"""
        if not self._is_loaded:
            return
        
        self._is_loaded = False
        
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer.deleteLater()
            self._animation_timer = None
        
        self.setVisible(False)
        self.update()
    
    def isLoaded(self) -> bool:
        """检查是否已加载"""
        return self._is_loaded
    
    def _update_animation(self):
        """更新动画"""
        if self._is_paused:
            return
        
        width = self.width()
        height = self.height()
        
        if width <= 0 or height <= 0:
            return
        
        for i in range(len(self._gradient_centers)):
            cx, cy = self._gradient_velocities[i]
            self._gradient_centers[i].setX(
                self._gradient_centers[i].x() + cx * self._animation_speed
            )
            self._gradient_centers[i].setY(
                self._gradient_centers[i].y() + cy * self._animation_speed
            )
            
            self._gradient_centers[i].setX(max(0.1, min(0.9, self._gradient_centers[i].x())))
            self._gradient_centers[i].setY(max(0.1, min(0.9, self._gradient_centers[i].y())))
        
        self.update()
    
    def paintEvent(self, event):
        """绘制事件"""
        if not self._is_loaded or not self.isVisible():
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        if width <= 0 or height <= 0:
            return
        
        colors = self._theme_colors.get(self._current_theme, self._theme_colors['sunset'])
        
        opacity_factors = [0.6, 0.5, 0.55, 0.45, 0.5, 0.35, 0.4, 0.3, 0.35, 0.25]
        
        for i in range(min(10, len(self._gradient_centers))):
            center = self._gradient_centers[i]
            radius = max(width, height) * self._gradient_radii[i]
            
            center_x = center.x() * width
            center_y = center.y() * height
            
            gradient = QRadialGradient(center_x, center_y, radius)
            gradient.setColorAt(0, colors[i % len(colors)])
            gradient.setColorAt(0.5, colors[i % len(colors)])
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            
            painter.setOpacity(opacity_factors[i])
            painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
        
        painter.setOpacity(1.0)
        
        overlay = QLinearGradient(0, 0, 0, height)
        overlay.setColorAt(0, QColor(10, 10, 15, 100))
        overlay.setColorAt(0.5, QColor(10, 10, 15, 40))
        overlay.setColorAt(1, QColor(10, 10, 15, 130))
        
        painter.setBrush(QBrush(overlay))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, width, height)
    
    def setTheme(self, theme: str):
        """
        设置主题
        
        Args:
            theme: 主题名称 ('sunset', 'ocean', 'aurora')
        """
        if theme not in self._theme_colors:
            return
        
        self._current_theme = theme
        self.update()
        self.themeChanged.emit(theme)
    
    def getTheme(self) -> str:
        """获取当前主题"""
        return self._current_theme
    
    def setAnimationSpeed(self, speed_factor: float):
        """
        设置动画速率
        
        Args:
            speed_factor: 速率因子 (0.1 - 2.0)
        """
        self._animation_speed = max(0.1, min(2.0, speed_factor))
        self.speedChanged.emit(self._animation_speed)
        self.update()
    
    def getAnimationSpeed(self) -> float:
        """获取动画速率"""
        return self._animation_speed
    
    def pauseAnimation(self, paused: bool = True):
        """
        暂停/恢复动画
        
        Args:
            paused: 是否暂停
        """
        self._is_paused = paused
    
    def isAnimationPaused(self) -> bool:
        """检查动画是否已暂停"""
        return self._is_paused
    
    def resetAnimation(self):
        """重置动画"""
        self._animation_speed = 1.0
        self._is_paused = False
        self._initialize_gradients()
        self.update()
        self.speedChanged.emit(1.0)
    
    def resizeEvent(self, event):
        """大小调整事件"""
        super().resizeEvent(event)
        self.update()
    
    def setCustomColors(self, colors: list):
        """
        设置自定义颜色（用于从封面提取的主色调）
        
        Args:
            colors: QColor 颜色列表（至少5个颜色）
        """
        if not colors or len(colors) < 5:
            return
        
        colors = colors[:5]
        self._theme_colors['custom'] = [QColor(c) if not isinstance(c, QColor) else QColor(c) for c in colors]
        self._current_theme = 'custom'
        self.update()
