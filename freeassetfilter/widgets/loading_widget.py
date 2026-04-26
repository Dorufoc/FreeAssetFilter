#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 加载状态转圈动画控件
使用SVG渲染器和QPropertyAnimation实现无限旋转动画，支持非线性缓动曲线
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPainter, QPixmap, QColor
from PySide6.QtSvg import QSvgRenderer
import os

from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.utils.app_logger import info, debug, warning, error


class LoadingSpinner(QWidget):
    """
    加载状态转圈动画控件
    特点：
    - 使用QSvgRenderer渲染SVG图标
    - 无限旋转动画，使用非线性缓动曲线
    - 销毁时同步暂停动画
    - 支持DPI缩放和主题颜色
    """
    
    def __init__(self, parent=None, icon_size=48, dpi_scale=1.0):
        super().__init__(parent)
        
        self._dpi_scale = dpi_scale
        self._icon_size = icon_size
        
        self._rotation_value = 0.0
        self._is_running = False
        
        self._rotation_animation = None
        
        self._loading_pixmap = QPixmap()
        self._accent_color = QColor("#0a59f7")
        self._background_color = None
        
        self._init_widget()
        self._load_svg_icon()
        self._setup_animations()
    
    def _init_widget(self):
        scaled_size = int(self._icon_size * self._dpi_scale)
        self.setFixedSize(scaled_size, scaled_size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
    
    def _load_svg_icon(self):
        icon_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons')
        icon_path = os.path.join(icon_dir, 'loading.svg')
        
        if not os.path.exists(icon_path):
            warning(f"LoadingSpinner: SVG图标不存在 - {icon_path}")
            return
        
        try:
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            svg_content = SvgRenderer._replace_svg_colors(svg_content)
            
            import re
            def rgba_to_hex(match):
                rgba_values = match.group(1).split(',')
                r = rgba_values[0].strip()
                g = rgba_values[1].strip()
                b = rgba_values[2].strip()
                a = rgba_values[3].strip()
                
                if '%' in r:
                    r = float(r.replace('%', '')) * 2.55
                else:
                    r = float(r)
                if '%' in g:
                    g = float(g.replace('%', '')) * 2.55
                else:
                    g = float(g)
                if '%' in b:
                    b = float(b.replace('%', '')) * 2.55
                else:
                    b = float(b)
                if '%' in a:
                    a = float(a.replace('%', '')) / 100
                else:
                    a = float(a)
                
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                a = max(0, min(1, a))
                a = int(a * 255)
                
                return f'#{int(r):02x}{int(g):02x}{int(b):02x}{a:02x}'
            
            svg_content = re.sub(r'rgba\(([^\)]+)\)', rgba_to_hex, svg_content)
            
            svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
            
            render_size = 256
            pixmap = QPixmap(render_size, render_size)
            pixmap.setDevicePixelRatio(1.0)
            pixmap.fill(Qt.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            svg_renderer.render(painter)
            painter.end()
            
            target_size = int(self._icon_size * self._dpi_scale)
            self._loading_pixmap = pixmap.scaled(
                target_size, 
                target_size, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            self._loading_pixmap.setDevicePixelRatio(self._dpi_scale if self._dpi_scale > 0 else 1.0)
            
        except (OSError, ValueError, RuntimeError) as e:
            error(f"LoadingSpinner: SVG加载失败 - {e}")
            self._loading_pixmap = QPixmap()
    
    def _setup_animations(self):
        self._rotation_animation = QPropertyAnimation(self, b"rotation")
        self._rotation_animation.setDuration(1200)
        self._rotation_animation.setStartValue(0.0)
        self._rotation_animation.setEndValue(360.0)
        self._rotation_animation.setLoopCount(-1)
        self._rotation_animation.setEasingCurve(QEasingCurve.Linear)
    
    def get_rotation(self):
        return self._rotation_value
    
    def set_rotation(self, value):
        self._rotation_value = value
        self.update()
    
    rotation = Property(float, fget=get_rotation, fset=set_rotation)
    
    def start(self):
        """
        开始动画
        """
        if self._is_running:
            return
        
        self._is_running = True
        
        if self._rotation_animation and self._rotation_animation.state() != QPropertyAnimation.Running:
            self._rotation_animation.start()
    
    def stop(self):
        """
        停止动画
        """
        self._is_running = False
        
        if self._rotation_animation:
            self._rotation_animation.stop()
        
        self._rotation_value = 0.0
        self.update()
    
    def is_running(self):
        """
        获取动画运行状态
        """
        return self._is_running
    
    def set_icon_size(self, size):
        """
        设置图标大小
        """
        self._icon_size = size
        scaled_size = int(size * self._dpi_scale)
        self.setFixedSize(scaled_size, scaled_size)
        self._load_svg_icon()
        self.update()
    
    def set_accent_color(self, color):
        """
        设置强调色
        """
        self._accent_color = QColor(color)
        self._load_svg_icon()
        self.update()

    def set_background_color(self, color):
        """
        设置绘制前用于清除旧帧的背景色。
        """
        self._background_color = QColor(color) if color else None
        self.update()
    
    def paintEvent(self, event):
        """
        绘制控件
        """
        if self._loading_pixmap.isNull():
            return
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), self._background_color or Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._rotation_value)
        
        pixmap_width = self._loading_pixmap.width() / self._dpi_scale if self._dpi_scale > 0 else self._loading_pixmap.width()
        pixmap_height = self._loading_pixmap.height() / self._dpi_scale if self._dpi_scale > 0 else self._loading_pixmap.height()
        
        painter.drawPixmap(
            int(-pixmap_width / 2),
            int(-pixmap_height / 2),
            self._loading_pixmap
        )
        
        painter.end()
    
    def deleteLater(self):
        """
        销毁控件时同步停止所有动画
        """
        self.stop()
        super().deleteLater()
    
    def hide(self):
        """
        隐藏控件时暂停动画
        """
        if self._is_running:
            if self._rotation_animation:
                self._rotation_animation.pause()
        super().hide()
    
    def show(self):
        """
        显示控件时恢复动画
        """
        if self._is_running:
            if self._rotation_animation and self._rotation_animation.state() == QPropertyAnimation.Paused:
                self._rotation_animation.resume()
        super().show()
    
    def set_visible(self, visible):
        """
        设置可见性
        """
        if visible:
            self.show()
        else:
            self.hide()
