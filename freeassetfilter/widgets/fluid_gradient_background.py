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
import random

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from freeassetfilter.core.settings_manager import SettingsManager


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
            ],
            'accent': self._generate_accent_colors()
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
            QPointF(0.15, 0.25),
            QPointF(0.85, 0.2),
            QPointF(0.25, 0.75),
            QPointF(0.75, 0.8),
            QPointF(0.1, 0.6),
            QPointF(0.9, 0.55),
            QPointF(0.35, 0.1),
            QPointF(0.65, 0.95),
            QPointF(0.45, 0.35)
        ]
        
        self._gradient_radii = [
            2.0, 1.8, 1.9, 1.7, 1.85,
            2.1, 1.6, 2.2, 1.75, 1.95
        ]
        
        self._gradient_velocities = [
            (0.0025, -0.0018),
            (-0.0020, 0.0025),
            (0.0030, 0.0018),
            (-0.0018, -0.0030),
            (0.0035, -0.0020),
            (-0.0030, 0.0025),
            (0.0020, -0.0035),
            (-0.0025, -0.0030),
            (0.0025, 0.0020),
            (-0.0020, 0.0030)
        ]
    
    def _generate_accent_colors(self):
        """
        根据设置中的强调色生成5个主题色
        基于强调色，在色相、饱和度、明度上产生邻近但不同的变化
        
        Returns:
            list: 生成的5个QColor颜色列表
        """
        try:
            settings = SettingsManager()
            accent_hex = settings.get_setting("appearance.colors.accent_color", "#B036EE")
            accent_color = QColor(accent_hex)
            
            h, s, v, a = accent_color.getHsv()
            
            colors = []
            
            hue_variations = [0, -25, 25, -15, 15]
            sat_variations = [1.0, 0.85, 0.9, 0.95, 0.8]
            val_variations = [0.85, 0.95, 0.75, 0.9, 0.8]
            
            for i in range(5):
                new_h = (h + hue_variations[i]) % 360
                new_s = max(0, min(255, int(s * sat_variations[i])))
                new_v = max(0, min(255, int(v * val_variations[i])))
                
                new_color = QColor.fromHsv(new_h, new_s, new_v, a)
                colors.append(new_color)
            
            print(f"[FluidGradient] 根据强调色 {accent_hex} 生成的主题色:")
            for i, c in enumerate(colors):
                print(f"  颜色{i+1}: HSV({c.hue()}, {c.saturation()}, {c.value()}) -> RGB({c.red()}, {c.green()}, {c.blue()})")
            
            return colors
            
        except Exception as e:
            print(f"[FluidGradient] 生成强调色主题失败，使用默认值: {e}")
            return [
                QColor(176, 54, 238),
                QColor(189, 74, 245),
                QColor(156, 44, 220),
                QColor(201, 104, 250),
                QColor(142, 30, 195)
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
        """更新动画（Ping-Pong 振荡效果）"""
        if self._is_paused:
            return
        
        width = self.width()
        height = self.height()
        
        if width <= 0 or height <= 0:
            return
        
        for i in range(len(self._gradient_centers)):
            cx, cy = self._gradient_velocities[i]
            
            new_x = self._gradient_centers[i].x() + cx * self._animation_speed
            new_y = self._gradient_centers[i].y() + cy * self._animation_speed
            
            if new_x <= -0.2 or new_x >= 1.2:
                self._gradient_velocities[i] = (-cx, cy)
                new_x = self._gradient_centers[i].x() + (-cx) * self._animation_speed
            
            if new_y <= -0.2 or new_y >= 1.2:
                self._gradient_velocities[i] = (cx, -cy)
                new_y = self._gradient_centers[i].y() + (cy) * self._animation_speed
            
            self._gradient_centers[i].setX(new_x)
            self._gradient_centers[i].setY(new_y)
        
        self.update()
    
    def paintEvent(self, event):
        """绘制事件"""
        if not self._is_loaded or not self.isVisible():
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        width = self.width()
        height = self.height()
        
        if width <= 0 or height <= 0:
            return
        
        colors = self._theme_colors.get(self._current_theme, self._theme_colors['sunset'])
        
        opacity_factors = [0.55, 0.45, 0.5, 0.4, 0.45, 0.35, 0.4, 0.3, 0.35, 0.25]
        
        for i in range(min(10, len(self._gradient_centers))):
            center = self._gradient_centers[i]
            radius = max(width, height) * self._gradient_radii[i]
            
            center_x = center.x() * width
            center_y = center.y() * height
            
            color1 = colors[i % len(colors)]
            color2 = colors[(i + 1) % len(colors)]
            color3 = colors[(i + 2) % len(colors)]
            
            gradient = QRadialGradient(center_x, center_y, radius)
            gradient.setColorAt(0, color1)
            gradient.setColorAt(0.2, color1)
            gradient.setColorAt(0.5, color2)
            gradient.setColorAt(0.8, color3)
            gradient.setColorAt(1, QColor(0, 0, 0, 0))
            
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            
            painter.setOpacity(opacity_factors[i])
            painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
        
        painter.setOpacity(1.0)
        
        overlay = QLinearGradient(0, 0, 0, height)
        overlay.setColorAt(0, QColor(10, 10, 15, 8))
        overlay.setColorAt(0.2, QColor(10, 10, 15, 5))
        overlay.setColorAt(0.5, QColor(10, 10, 15, 3))
        overlay.setColorAt(0.8, QColor(10, 10, 15, 5))
        overlay.setColorAt(1, QColor(10, 10, 15, 8))
        
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
            print("[FluidGradient] 设置自定义颜色失败：颜色不足")
            return
        
        colors = colors[:5]
        print(f"[FluidGradient] 设置自定义颜色，数量: {len(colors)}")
        for i, c in enumerate(colors):
            print(f"  颜色{i+1}: RGB({c.red()}, {c.green()}, {c.blue()})")
        
        self._theme_colors['custom'] = [QColor(c.red(), c.green(), c.blue()) for c in colors]
        self._current_theme = 'custom'
        self._initialize_gradients()
        print(f"[FluidGradient] 当前主题已切换为: {self._current_theme}")
        self.update()
    
    def useAccentTheme(self):
        """使用强调色生成的主题（无封面时的默认主题）"""
        if 'accent' not in self._theme_colors:
            self._theme_colors['accent'] = self._generate_accent_colors()
        self._current_theme = 'accent'
        self._initialize_gradients()
        print(f"[FluidGradient] 已切换为强调色主题")
        self.update()
