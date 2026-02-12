#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源

音频背景组件
支持两种背景模式：
1. 流体动画 - 动态渐变背景，支持多种主题
2. 封面模糊 - 使用音频封面图像，拉伸到1440P并模糊处理
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QPointF, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QBrush, QLinearGradient, QPixmap, QImage
from PIL import Image, ImageFilter
import io
import random


class AudioBackground(QWidget):
    """
    音频背景组件
    
    支持两种模式：
    - fluid: 流体动画背景（动态渐变）
    - cover_blur: 封面模糊背景（使用音频封面）
    """
    
    # 信号定义
    themeChanged = Signal(str)
    speedChanged = Signal(float)
    
    # 背景模式常量
    MODE_FLUID = "fluid"
    MODE_COVER_BLUR = "cover_blur"
    
    def __init__(self, parent=None):
        """
        初始化音频背景组件
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        # 通用属性
        self._is_loaded = False
        self._current_mode = self.MODE_FLUID  # 默认使用流体动画
        
        # 流体动画相关属性
        self._current_theme = 'sunset'
        self._animation_speed = 1.0
        self._is_paused = False
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
        
        # 封面模糊相关属性
        self._cover_data = None  # 原始封面数据
        self._blurred_pixmap = None  # 模糊处理后的1440P图像
        
        # 设置透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")
        self.setVisible(False)
    
    # ==================== 通用方法 ====================
    
    def load(self, mode=None):
        """
        加载背景组件
        
        Args:
            mode: 背景模式，None则使用当前模式
        """
        if mode:
            self._current_mode = mode
        
        if self._is_loaded:
            return
        
        self._is_loaded = True
        self.setVisible(True)
        
        # 根据模式启动相应的背景
        if self._current_mode == self.MODE_FLUID:
            self._start_fluid_animation()
        
        self.update()
    
    def unload(self):
        """卸载背景组件"""
        if not self._is_loaded:
            return
        
        self._is_loaded = False
        
        # 停止流体动画
        self._stop_fluid_animation()
        
        # 清除封面数据
        self._cover_data = None
        self._blurred_pixmap = None
        
        self.setVisible(False)
    
    def isLoaded(self) -> bool:
        """检查是否已加载"""
        return self._is_loaded
    
    def setMode(self, mode: str):
        """
        设置背景模式
        
        Args:
            mode: 模式名称 ('fluid' 或 'cover_blur')
        """
        if mode not in [self.MODE_FLUID, self.MODE_COVER_BLUR]:
            return
        
        if self._current_mode == mode:
            return
        
        self._current_mode = mode
        
        if self._is_loaded:
            if mode == self.MODE_FLUID:
                self._blurred_pixmap = None
                self._start_fluid_animation()
            else:
                self._stop_fluid_animation()
                if self._cover_data:
                    self._process_cover()
            self.update()
    
    def getMode(self) -> str:
        """获取当前背景模式"""
        return self._current_mode
    
    # ==================== 流体动画方法 ====================
    
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
        """根据设置中的强调色生成主题色"""
        try:
            from freeassetfilter.core.settings_manager import SettingsManager
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
            
            return colors
        except Exception:
            return [
                QColor(176, 54, 238),
                QColor(189, 74, 245),
                QColor(156, 44, 220),
                QColor(201, 104, 250),
                QColor(142, 30, 195)
            ]
    
    def _start_fluid_animation(self):
        """启动流体动画"""
        if self._animation_timer is None:
            self._animation_timer = QTimer(self)
            self._animation_timer.timeout.connect(self._update_fluid_animation)
            self._animation_timer.start(16)
    
    def _stop_fluid_animation(self):
        """停止流体动画"""
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer.deleteLater()
            self._animation_timer = None
    
    def _update_fluid_animation(self):
        """更新流体动画"""
        if self._is_paused or self._current_mode != self.MODE_FLUID:
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
    
    def setTheme(self, theme: str):
        """
        设置流体动画主题
        
        Args:
            theme: 主题名称 ('sunset', 'ocean', 'aurora', 'accent')
        """
        if theme not in self._theme_colors:
            return
        
        self._current_theme = theme
        if self._is_loaded and self._current_mode == self.MODE_FLUID:
            self.update()
        self.themeChanged.emit(theme)
    
    def getTheme(self) -> str:
        """获取当前流体动画主题"""
        return self._current_theme
    
    def setAnimationSpeed(self, speed_factor: float):
        """
        设置流体动画速率
        
        Args:
            speed_factor: 速率因子 (0.1 - 2.0)
        """
        self._animation_speed = max(0.1, min(2.0, speed_factor))
        self.speedChanged.emit(self._animation_speed)
    
    def getAnimationSpeed(self) -> float:
        """获取流体动画速率"""
        return self._animation_speed
    
    def pauseAnimation(self, paused: bool = True):
        """
        暂停/恢复流体动画
        
        Args:
            paused: 是否暂停
        """
        self._is_paused = paused
    
    def isAnimationPaused(self) -> bool:
        """检查流体动画是否已暂停"""
        return self._is_paused
    
    def setCustomColors(self, colors: list):
        """
        设置流体动画自定义颜色（用于从封面提取的主色调）
        
        Args:
            colors: QColor 颜色列表（至少5个颜色）
        """
        if not colors or len(colors) < 5:
            return
        
        colors = colors[:5]
        self._theme_colors['custom'] = [QColor(c.red(), c.green(), c.blue()) for c in colors]
        self._current_theme = 'custom'
        self._initialize_gradients()
        
        if self._is_loaded and self._current_mode == self.MODE_FLUID:
            self.update()
    
    def useAccentTheme(self):
        """使用强调色生成的主题（无封面时的默认主题）"""
        if 'accent' not in self._theme_colors:
            self._theme_colors['accent'] = self._generate_accent_colors()
        self._current_theme = 'accent'
        self._initialize_gradients()
        
        if self._is_loaded and self._current_mode == self.MODE_FLUID:
            self.update()
    
    # ==================== 封面模糊方法 ====================
    
    def setCoverData(self, cover_data: bytes):
        """
        设置封面数据（用于封面模糊模式）
        
        Args:
            cover_data: 封面图像的二进制数据
        """
        self._cover_data = cover_data
        
        if self._is_loaded and self._current_mode == self.MODE_COVER_BLUR:
            self._process_cover()
            self.update()
    
    def _process_cover(self):
        """处理封面数据生成模糊图像"""
        if not self._cover_data:
            self._blurred_pixmap = None
            return
        
        try:
            # 从二进制数据加载图像
            image = Image.open(io.BytesIO(self._cover_data))
            
            # 转换为RGB模式
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # 目标分辨率 1440P (2560x1440)
            target_width = 2560
            target_height = 1440
            
            # 计算适合缩放的尺寸（保持比例，填满目标区域）
            img_width, img_height = image.size
            scale = max(target_width / img_width, target_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            
            # 缩放图像
            image_resized = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 居中裁剪到目标尺寸
            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            right = left + target_width
            bottom = top + target_height
            image_cropped = image_resized.crop((left, top, right, bottom))
            
            # 应用高斯模糊
            image_blurred = image_cropped.filter(ImageFilter.GaussianBlur(radius=30))
            
            # 转换为QPixmap
            self._blurred_pixmap = self._pil_to_pixmap(image_blurred)
            
        except Exception as e:
            print(f"[AudioBackground] 处理封面失败: {e}")
            self._blurred_pixmap = None
    
    def _pil_to_pixmap(self, pil_image) -> QPixmap:
        """将PIL图像转换为QPixmap"""
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')
        
        data = pil_image.tobytes('raw', 'RGBA')
        qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimage)
    
    def _calculate_scaled_rect(self) -> QRect:
        """计算保持比例填充的图像显示区域"""
        if not self._blurred_pixmap:
            return self.rect()
        
        widget_width = self.width()
        widget_height = self.height()
        pixmap_width = self._blurred_pixmap.width()
        pixmap_height = self._blurred_pixmap.height()
        
        if widget_width <= 0 or widget_height <= 0 or pixmap_width <= 0 or pixmap_height <= 0:
            return self.rect()
        
        # 计算缩放比例（填满整个区域）
        scale_x = widget_width / pixmap_width
        scale_y = widget_height / pixmap_height
        scale = max(scale_x, scale_y)
        
        new_width = int(pixmap_width * scale)
        new_height = int(pixmap_height * scale)
        
        x = (widget_width - new_width) // 2
        y = (widget_height - new_height) // 2
        
        return QRect(x, y, new_width, new_height)
    
    # ==================== 绘制方法 ====================
    
    def resizeEvent(self, event):
        """大小调整事件"""
        super().resizeEvent(event)
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
            painter.end()
            return
        
        if self._current_mode == self.MODE_FLUID:
            self._paint_fluid_background(painter, width, height)
        else:
            self._paint_cover_blur_background(painter, width, height)
        
        painter.end()
    
    def _paint_fluid_background(self, painter: QPainter, width: int, height: int):
        """绘制流体动画背景"""
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
        
        # 添加叠加层
        overlay = QLinearGradient(0, 0, 0, height)
        overlay.setColorAt(0, QColor(10, 10, 15, 8))
        overlay.setColorAt(0.2, QColor(10, 10, 15, 5))
        overlay.setColorAt(0.5, QColor(10, 10, 15, 3))
        overlay.setColorAt(0.8, QColor(10, 10, 15, 5))
        overlay.setColorAt(1, QColor(10, 10, 15, 8))
        
        painter.setBrush(QBrush(overlay))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, width, height)
    
    def _paint_cover_blur_background(self, painter: QPainter, width: int, height: int):
        """绘制封面模糊背景"""
        # 1. 绘制黑色背景（100%不透明）
        painter.fillRect(0, 0, width, height, QColor("#000000"))
        
        # 2. 绘制模糊图像（50%透明度）
        if self._blurred_pixmap and not self._blurred_pixmap.isNull():
            display_rect = self._calculate_scaled_rect()
            
            scaled_pixmap = self._blurred_pixmap.scaled(
                display_rect.width(),
                display_rect.height(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            painter.setOpacity(0.5)
            painter.drawPixmap(display_rect.x(), display_rect.y(), scaled_pixmap)
            painter.setOpacity(1.0)
    
    def clear(self):
        """清除数据"""
        self._cover_data = None
        self._blurred_pixmap = None
        self.update()
