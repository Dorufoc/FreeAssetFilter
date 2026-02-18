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

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsDropShadowEffect
from PySide6.QtCore import Qt, QTimer, QPointF, Signal, QRect, QRunnable, QThreadPool, QMutex
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QBrush, QLinearGradient, QPixmap, QImage
from PySide6.QtSvgWidgets import QSvgWidget
from PIL import Image, ImageFilter
from collections import Counter, OrderedDict
import io
import random
import os
import math
import hashlib
import time


class CoverCache:
    """
    封面图像缓存类，使用 OrderedDict 实现 LRU 策略
    最大缓存条目数为 50
    缓存内容：文件路径 -> {colors, blurred_pixmap, cover_pixmap}
    """
    _instance = None
    _mutex = QMutex()
    
    def __new__(cls, max_size=50):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = OrderedDict()
            cls._instance._max_size = max_size
        return cls._instance
    
    def _get_key(self, cover_data: bytes) -> str:
        """根据封面数据生成唯一key"""
        return hashlib.md5(cover_data).hexdigest()
    
    def get(self, cover_data: bytes):
        """获取缓存项，如果存在则移动到末尾（最近使用）"""
        key = self._get_key(cover_data)
        self._mutex.lock()
        try:
            if key in self._cache:
                # 移动到末尾表示最近使用
                self._cache.move_to_end(key)
                return self._cache[key]
            return None
        finally:
            self._mutex.unlock()
    
    def put(self, cover_data: bytes, colors=None, blurred_pixmap=None, cover_pixmap=None):
        """添加缓存项，如果已满则移除最旧的项"""
        key = self._get_key(cover_data)
        self._mutex.lock()
        try:
            # 如果已存在，先移除
            if key in self._cache:
                self._cache.move_to_end(key)
            
            # 检查是否需要移除最旧的项
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            
            # 添加新项
            self._cache[key] = {
                'colors': colors,
                'blurred_pixmap': blurred_pixmap,
                'cover_pixmap': cover_pixmap,
                'timestamp': time.time()
            }
        finally:
            self._mutex.unlock()
    
    def clear(self):
        """清空缓存"""
        self._mutex.lock()
        try:
            self._cache.clear()
        finally:
            self._mutex.unlock()


class ColorExtractionTask(QRunnable):
    """
    颜色提取任务类，继承自 QRunnable
    在后台线程中执行颜色提取，避免阻塞主线程
    """
    def __init__(self, task_id: int, cover_data: bytes, callback, widget_ref):
        super().__init__()
        self.task_id = task_id
        self.cover_data = cover_data
        self.callback = callback
        self.widget_ref = widget_ref
        self._is_cancelled = False
    
    def cancel(self):
        """取消任务"""
        self._is_cancelled = True
    
    def is_cancelled(self) -> bool:
        """检查任务是否被取消"""
        return self._is_cancelled
    
    def run(self):
        """在后台线程中执行颜色提取"""
        if self._is_cancelled:
            return
        
        try:
            # 从二进制数据加载图像
            image = Image.open(io.BytesIO(self.cover_data))
            
            # 转换为RGBA模式
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            
            if self._is_cancelled:
                return
            
            # 提取颜色
            colors = self._extract_colors(image)
            
            if self._is_cancelled:
                return
            
            # 回调到主线程
            if self.callback and not self._is_cancelled:
                self.callback(self.task_id, colors)
                
        except Exception as e:
            print(f"[ColorExtractionTask] 颜色提取失败: {e}")
            if self.callback and not self._is_cancelled:
                self.callback(self.task_id, None)
    
    def _extract_colors(self, image: Image.Image) -> list:
        """
        从封面图像中提取5个占比最高且差异明显的颜色
        使用K-Means聚类 + CIEDE2000色差算法
        """
        try:
            import random
            
            # 缩小图像以加快处理速度
            small_image = image.copy()
            small_image.thumbnail((150, 150), Image.Resampling.LANCZOS)
            
            # 获取所有像素颜色
            pixels = list(small_image.getdata())
            
            # 过滤掉透明像素和接近白色/黑色的像素
            valid_pixels = []
            for pixel in pixels:
                if len(pixel) == 4:
                    r, g, b, a = pixel
                    if a < 128:
                        continue
                elif len(pixel) == 3:
                    r, g, b = pixel
                else:
                    continue
                brightness = (r + g + b) / 3
                if brightness > 240 or brightness < 20:
                    continue
                valid_pixels.append((r, g, b))
            
            if len(valid_pixels) < 10:
                return None
            
            # 随机采样以减少计算量
            if len(valid_pixels) > 5000:
                valid_pixels = random.sample(valid_pixels, 5000)
            
            # 执行K-Means聚类
            centroids, cluster_sizes = self._kmeans_lab(valid_pixels, k=8, max_iters=30)
            
            # 将聚类中心按像素数量排序
            centroid_info = list(zip(centroids, cluster_sizes))
            centroid_info.sort(key=lambda x: x[1], reverse=True)
            
            # 使用CIEDE2000筛选差异明显的颜色
            min_delta_e = 20
            selected_colors_lab = []
            
            for centroid, size in centroid_info:
                if len(selected_colors_lab) >= 5:
                    break
                
                is_different = True
                for selected in selected_colors_lab:
                    delta_e = self._ciede2000(centroid, selected)
                    if delta_e < min_delta_e:
                        is_different = False
                        break
                
                if is_different:
                    selected_colors_lab.append(centroid)
            
            # 如果选不够5个，降低阈值继续选择
            if len(selected_colors_lab) < 5:
                for centroid, size in centroid_info:
                    if len(selected_colors_lab) >= 5:
                        break
                    if centroid not in selected_colors_lab:
                        is_different = True
                        for selected in selected_colors_lab:
                            delta_e = self._ciede2000(centroid, selected)
                            if delta_e < 10:
                                is_different = False
                                break
                        if is_different:
                            selected_colors_lab.append(centroid)
            
            # 如果仍然不足5个，生成互补色
            while len(selected_colors_lab) < 5:
                if len(selected_colors_lab) == 0:
                    new_lab = (random.uniform(20, 80), random.uniform(-100, 100), random.uniform(-100, 100))
                else:
                    avg_L = sum(c[0] for c in selected_colors_lab) / len(selected_colors_lab)
                    avg_a = sum(c[1] for c in selected_colors_lab) / len(selected_colors_lab)
                    avg_b = sum(c[2] for c in selected_colors_lab) / len(selected_colors_lab)
                    new_lab = (100 - avg_L, -avg_a, -avg_b)
                
                is_different = True
                for selected in selected_colors_lab:
                    if self._ciede2000(new_lab, selected) < min_delta_e:
                        is_different = False
                        break
                
                if is_different:
                    selected_colors_lab.append(new_lab)
                else:
                    perturbed = (
                        max(0, min(100, new_lab[0] + random.uniform(-20, 20))),
                        max(-128, min(127, new_lab[1] + random.uniform(-30, 30))),
                        max(-128, min(127, new_lab[2] + random.uniform(-30, 30)))
                    )
                    selected_colors_lab.append(perturbed)
            
            # 转换为RGB
            final_colors = [self._lab_to_rgb(lab) for lab in selected_colors_lab[:5]]
            return final_colors
            
        except Exception as e:
            print(f"[ColorExtractionTask] 提取颜色失败: {e}")
            return None
    
    def _rgb_to_lab(self, rgb):
        """将RGB转换为Lab色彩空间"""
        r, g, b = [x / 255.0 for x in rgb]
        
        r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r / 12.92
        g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g / 12.92
        b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b / 12.92
        
        r *= 100
        g *= 100
        b *= 100
        
        x = r * 0.4124 + g * 0.3576 + b * 0.1805
        y = r * 0.2126 + g * 0.7152 + b * 0.0722
        z = r * 0.0193 + g * 0.1192 + b * 0.9505
        
        x /= 95.047
        y /= 100.0
        z /= 108.883
        
        x = x ** (1/3) if x > 0.008856 else 7.787 * x + 16/116
        y = y ** (1/3) if y > 0.008856 else 7.787 * y + 16/116
        z = z ** (1/3) if z > 0.008856 else 7.787 * z + 16/116
        
        L = 116 * y - 16
        a = 500 * (x - y)
        b_val = 200 * (y - z)
        
        return (L, a, b_val)
    
    def _lab_to_rgb(self, lab):
        """将Lab转换回RGB"""
        L, a, b_val = lab
        
        y = (L + 16) / 116
        x = a / 500 + y
        z = y - b_val / 200
        
        x = x ** 3 if x ** 3 > 0.008856 else (x - 16/116) / 7.787
        y = y ** 3 if y ** 3 > 0.008856 else (y - 16/116) / 7.787
        z = z ** 3 if z ** 3 > 0.008856 else (z - 16/116) / 7.787
        
        x *= 95.047
        y *= 100.0
        z *= 108.883
        
        x /= 100
        y /= 100
        z /= 100
        
        r = x * 3.2406 + y * -1.5372 + z * -0.4986
        g = x * -0.9689 + y * 1.8758 + z * 0.0415
        b = x * 0.0557 + y * -0.2040 + z * 1.0570
        
        r = 1.055 * (r ** (1/2.4)) - 0.055 if r > 0.0031308 else 12.92 * r
        g = 1.055 * (g ** (1/2.4)) - 0.055 if g > 0.0031308 else 12.92 * g
        b = 1.055 * (b ** (1/2.4)) - 0.055 if b > 0.0031308 else 12.92 * b
        
        r = max(0, min(1, r))
        g = max(0, min(1, g))
        b = max(0, min(1, b))
        
        return (int(r * 255), int(g * 255), int(b * 255))
    
    def _ciede2000(self, lab1, lab2):
        """计算两个Lab颜色之间的CIEDE2000色差"""
        L1, a1, b1 = lab1
        L2, a2, b2 = lab2
        
        C1 = math.sqrt(a1**2 + b1**2)
        C2 = math.sqrt(a2**2 + b2**2)
        C_avg = (C1 + C2) / 2
        
        G = 0.5 * (1 - math.sqrt(C_avg**7 / (C_avg**7 + 25**7)))
        
        a1_prime = a1 * (1 + G)
        a2_prime = a2 * (1 + G)
        
        C1_prime = math.sqrt(a1_prime**2 + b1**2)
        C2_prime = math.sqrt(a2_prime**2 + b2**2)
        
        h1_prime = math.degrees(math.atan2(b1, a1_prime)) % 360
        h2_prime = math.degrees(math.atan2(b2, a2_prime)) % 360
        
        delta_L_prime = L2 - L1
        delta_C_prime = C2_prime - C1_prime
        
        if C1_prime * C2_prime == 0:
            delta_h_prime = 0
        else:
            if abs(h2_prime - h1_prime) <= 180:
                delta_h_prime = h2_prime - h1_prime
            elif h2_prime - h1_prime > 180:
                delta_h_prime = h2_prime - h1_prime - 360
            else:
                delta_h_prime = h2_prime - h1_prime + 360
        
        delta_H_prime = 2 * math.sqrt(C1_prime * C2_prime) * math.sin(math.radians(delta_h_prime / 2))
        
        L_avg = (L1 + L2) / 2
        C_avg_prime = (C1_prime + C2_prime) / 2
        
        if C1_prime * C2_prime == 0:
            h_avg_prime = h1_prime + h2_prime
        else:
            if abs(h1_prime - h2_prime) <= 180:
                h_avg_prime = (h1_prime + h2_prime) / 2
            elif h1_prime + h2_prime < 360:
                h_avg_prime = (h1_prime + h2_prime + 360) / 2
            else:
                h_avg_prime = (h1_prime + h2_prime - 360) / 2
        
        T = (1 -
             0.17 * math.cos(math.radians(h_avg_prime - 30)) +
             0.24 * math.cos(math.radians(2 * h_avg_prime)) +
             0.32 * math.cos(math.radians(3 * h_avg_prime + 6)) -
             0.20 * math.cos(math.radians(4 * h_avg_prime - 63)))
        
        delta_theta = 30 * math.exp(-((h_avg_prime - 275) / 25) ** 2)
        R_C = 2 * math.sqrt(C_avg_prime**7 / (C_avg_prime**7 + 25**7))
        S_L = 1 + (0.015 * (L_avg - 50) ** 2) / math.sqrt(20 + (L_avg - 50) ** 2)
        S_C = 1 + 0.045 * C_avg_prime
        S_H = 1 + 0.015 * C_avg_prime * T
        R_T = -math.sin(math.radians(2 * delta_theta)) * R_C
        
        delta_E = math.sqrt(
            (delta_L_prime / S_L) ** 2 +
            (delta_C_prime / S_C) ** 2 +
            (delta_H_prime / S_H) ** 2 +
            R_T * (delta_C_prime / S_C) * (delta_H_prime / S_H)
        )
        
        return delta_E
    
    def _kmeans_lab(self, pixels_rgb, k=8, max_iters=50):
        """在Lab空间进行K-Means聚类"""
        pixels_lab = [self._rgb_to_lab(p) for p in pixels_rgb]
        
        random.shuffle(pixels_lab)
        centroids = pixels_lab[:k]
        cluster_sizes = [0] * k
        
        for iteration in range(max_iters):
            clusters = [[] for _ in range(k)]
            new_cluster_sizes = [0] * k
            
            for pixel in pixels_lab:
                min_dist = float('inf')
                closest = 0
                for i, centroid in enumerate(centroids):
                    dist = self._ciede2000(pixel, centroid)
                    if dist < min_dist:
                        min_dist = dist
                        closest = i
                clusters[closest].append(pixel)
                new_cluster_sizes[closest] += 1
            
            new_centroids = []
            for i, cluster in enumerate(clusters):
                if cluster:
                    avg_L = sum(p[0] for p in cluster) / len(cluster)
                    avg_a = sum(p[1] for p in cluster) / len(cluster)
                    avg_b = sum(p[2] for p in cluster) / len(cluster)
                    new_centroids.append((avg_L, avg_a, avg_b))
                else:
                    new_centroids.append(random.choice(pixels_lab))
            
            converged = True
            for i in range(k):
                if self._ciede2000(centroids[i], new_centroids[i]) > 1.0:
                    converged = False
                    break
            
            centroids = new_centroids
            cluster_sizes = new_cluster_sizes
            
            if converged:
                break
        
        return centroids, cluster_sizes


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
        self._blurred_pixmap = None  # 模糊处理后的1080P图像

        # 封面显示相关属性（用于流体背景模式）
        self._cover_pixmap = None  # 封面图像（用于中央显示）
        self._cover_size = 200  # 封面显示尺寸
        self._max_cover_size = 200  # 封面最大尺寸
        self._min_cover_size = 80  # 封面最小尺寸
        self._cover_margin = 40  # 封面与窗口边缘的最小间距

        # 异步颜色提取任务管理
        self._color_task_id = 0  # 任务ID计数器
        self._current_color_task = None  # 当前正在运行的颜色提取任务
        self._thread_pool = QThreadPool()  # 线程池用于执行颜色提取任务
        self._thread_pool.setMaxThreadCount(2)  # 最多2个并发任务

        # 缓存实例
        self._cover_cache = CoverCache()

        # 创建封面显示容器（用于显示封面或SVG图标）
        # 使用QWidget作为居中容器，通过布局系统实现居中，避免手动计算像素值
        self._cover_container = QWidget(self)
        self._cover_container.setStyleSheet("background: transparent; border: none;")
        self._cover_container.hide()

        # 使用垂直布局实现垂直居中
        self._cover_layout = QVBoxLayout(self._cover_container)
        self._cover_layout.setContentsMargins(0, 0, 0, 0)
        self._cover_layout.setAlignment(Qt.AlignCenter)

        # 封面图像标签 - 使用Qt.AlignCenter实现内容居中
        # 注意：必须指定父对象为_cover_container，以便使用其布局系统进行居中
        self._cover_label = QLabel(self._cover_container)
        self._cover_label.setAlignment(Qt.AlignCenter)
        self._cover_label.setStyleSheet("background: transparent; border: none;")
        self._cover_label.hide()
        self._cover_layout.addWidget(self._cover_label, alignment=Qt.AlignCenter)

        # SVG图标容器 - 使用QWidget包装以实现居中
        # 注意：必须指定父对象为_cover_container，以便使用其布局系统进行居中
        self._svg_container = QWidget(self._cover_container)
        self._svg_container.setStyleSheet("background: transparent; border: none;")
        self._svg_container_layout = QVBoxLayout(self._svg_container)
        self._svg_container_layout.setContentsMargins(0, 0, 0, 0)
        self._svg_container_layout.setAlignment(Qt.AlignCenter)
        self._svg_container.hide()
        self._cover_layout.addWidget(self._svg_container, alignment=Qt.AlignCenter)

        # SVG图标widget
        self._svg_widget = None

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

        # 显示封面容器（布局系统会自动处理居中）
        self._cover_container.show()
        # 使用延迟调用确保AudioBackground已经有正确尺寸
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._init_cover_container_geometry())

        self.update()

    def _init_cover_container_geometry(self):
        """
        初始化封面容器几何区域
        在组件加载时根据窗口大小调整封面尺寸
        """
        self._cover_container.setGeometry(self.rect())
        # 根据当前窗口大小调整封面尺寸
        self._update_cover_size()
    
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
        self._cover_pixmap = None

        # 隐藏封面显示
        self._cover_label.hide()
        self._svg_container.hide()
        self._cover_container.hide()
        if self._svg_widget:
            self._svg_widget.hide()
            self._svg_widget.deleteLater()
            self._svg_widget = None

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
        """启动流体动画 - 定时器间隔从16ms改为33ms（30FPS）以优化性能"""
        if self._animation_timer is None:
            self._animation_timer = QTimer(self)
            self._animation_timer.timeout.connect(self._update_fluid_animation)
            self._animation_timer.start(33)  # 30 FPS
    
    def _stop_fluid_animation(self):
        """停止流体动画"""
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer.deleteLater()
            self._animation_timer = None
    
    def pauseAnimation(self):
        """暂停流体动画"""
        self._is_paused = True
        if self._animation_timer:
            self._animation_timer.stop()
    
    def resumeAnimation(self):
        """恢复流体动画"""
        self._is_paused = False
        if self._animation_timer and self._is_loaded and self._current_mode == self.MODE_FLUID:
            self._animation_timer.start(33)
    
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
    
    # ==================== 封面显示方法（流体背景模式）====================

    def setAudioCover(self, cover_data: bytes = None):
        """
        设置音频封面图像（用于流体背景模式的中央显示）
        同时从封面提取主色调设置流体背景颜色
        使用异步颜色提取和缓存机制优化性能

        Args:
            cover_data: 封面图像的二进制数据，如果为None则显示默认音乐图标并使用强调色主题
        """
        # 取消之前的颜色提取任务
        if self._current_color_task:
            self._current_color_task.cancel()
            self._current_color_task = None

        # 保存原始封面数据以便后续重新加载
        self._cover_data = cover_data

        # 隐藏当前的封面显示
        self._cover_label.hide()
        self._svg_container.hide()
        if self._svg_widget:
            self._svg_widget.hide()
            self._svg_widget.deleteLater()
            self._svg_widget = None

        if cover_data:
            try:
                # 确保SVG容器被隐藏，避免遮挡封面
                self._svg_container.hide()
                
                # 检查缓存
                cached = self._cover_cache.get(cover_data)
                if cached and cached.get('cover_pixmap'):
                    # 使用缓存的封面图像
                    self._cover_pixmap = cached['cover_pixmap']
                    self._cover_label.setPixmap(self._cover_pixmap)
                    self._cover_label.setMinimumSize(self._cover_pixmap.size())
                    self._cover_label.show()
                    self._cover_layout.update()
                    print(f"[AudioBackground] 使用缓存的封面图像")

                    # 使用缓存的颜色
                    if cached.get('colors'):
                        colors = cached['colors']
                        qt_colors = [QColor(r, g, b) for r, g, b in colors]
                        self.setCustomColors(qt_colors)
                        print(f"[AudioBackground] 使用缓存的颜色主题")
                    else:
                        # 启动异步颜色提取
                        self._start_color_extraction(cover_data)

                    # 确保封面容器大小正确并更新布局
                    self._cover_container.setGeometry(self.rect())
                    self._cover_layout.update()
                    return

                # 从二进制数据加载图像
                image = Image.open(io.BytesIO(cover_data))

                # 转换为RGBA模式
                if image.mode != 'RGBA':
                    image = image.convert('RGBA')

                # 缩放到合适的显示尺寸（保持比例）
                max_size = self._cover_size
                display_image = image.copy()
                display_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                # 转换为QPixmap
                self._cover_pixmap = self._pil_to_pixmap(display_image)
                print(f"[AudioBackground] 已加载音频封面: {display_image.size}")

                # 显示封面图像（布局系统会自动居中）
                self._cover_label.setPixmap(self._cover_pixmap)
                # 不设置固定大小，让布局系统控制居中
                self._cover_label.setMinimumSize(self._cover_pixmap.size())
                self._cover_label.show()
                # 强制更新布局
                self._cover_layout.update()

                # 先显示默认主题（强调色），然后异步提取颜色
                self.useAccentTheme()

                # 缓存封面图像
                self._cover_cache.put(cover_data, cover_pixmap=self._cover_pixmap)

                # 启动异步颜色提取
                self._start_color_extraction(cover_data)

            except Exception as e:
                print(f"[AudioBackground] 加载封面失败: {e}")
                self._cover_pixmap = None
                # 加载默认SVG图标并使用强调色主题
                self._load_default_cover()
                self.useAccentTheme()
        else:
            self._cover_pixmap = None
            # 加载默认SVG图标并使用强调色主题
            self._load_default_cover()
            self.useAccentTheme()

        # 确保封面容器大小正确并更新布局
        self._cover_container.setGeometry(self.rect())
        self._cover_layout.update()

    def _start_color_extraction(self, cover_data: bytes):
        """
        启动异步颜色提取任务

        Args:
            cover_data: 封面图像的二进制数据
        """
        # 生成新任务ID
        self._color_task_id += 1
        task_id = self._color_task_id

        # 创建并启动颜色提取任务
        task = ColorExtractionTask(
            task_id=task_id,
            cover_data=cover_data,
            callback=self._on_color_extraction_finished,
            widget_ref=self
        )
        self._current_color_task = task
        self._thread_pool.start(task)
        print(f"[AudioBackground] 启动颜色提取任务 #{task_id}")

    def _on_color_extraction_finished(self, task_id: int, colors: list):
        """
        颜色提取完成回调

        Args:
            task_id: 任务ID
            colors: 提取的颜色列表 [(r,g,b), ...] 或 None
        """
        # 检查是否是当前任务（忽略已取消的旧任务）
        if self._current_color_task is None or task_id != self._current_color_task.task_id:
            print(f"[AudioBackground] 忽略旧任务 #{task_id} 的结果")
            return

        self._current_color_task = None

        if colors and len(colors) >= 5:
            # 转换为QColor并设置主题
            qt_colors = [QColor(r, g, b) for r, g, b in colors[:5]]
            self.setCustomColors(qt_colors)

            # 缓存颜色
            if self._cover_data:
                self._cover_cache.put(self._cover_data, colors=colors[:5])

            print(f"[AudioBackground] 任务 #{task_id} 完成，已应用提取的颜色主题")
        else:
            print(f"[AudioBackground] 任务 #{task_id} 未能提取足够颜色，使用默认主题")
            self.useAccentTheme()

    def _extract_colors_from_cover(self, image: Image.Image):
        """
        从封面图像中提取5个占比最高且差异明显的颜色作为流体背景配色
        使用K-Means聚类 + CIEDE2000色差算法，在Lab色彩空间进行颜色提取

        Args:
            image: PIL Image对象
        """
        try:
            import random

            # 缩小图像以加快处理速度，同时保持足够的颜色信息
            small_image = image.copy()
            small_image.thumbnail((150, 150), Image.Resampling.LANCZOS)

            # 获取所有像素颜色
            pixels = list(small_image.getdata())

            # 过滤掉透明像素和接近白色/黑色的像素
            valid_pixels = []
            for pixel in pixels:
                # 处理不同模式的图像（RGB/RGBA等）
                if len(pixel) == 4:
                    r, g, b, a = pixel
                    if a < 128:
                        continue
                elif len(pixel) == 3:
                    r, g, b = pixel
                else:
                    continue
                brightness = (r + g + b) / 3
                if brightness > 240 or brightness < 20:
                    continue
                valid_pixels.append((r, g, b))

            if len(valid_pixels) < 10:
                self.useAccentTheme()
                return

            # 随机采样以减少计算量（最多5000个像素）
            if len(valid_pixels) > 5000:
                valid_pixels = random.sample(valid_pixels, 5000)

            # 将RGB转换为Lab色彩空间
            def rgb_to_lab(rgb):
                """将RGB转换为Lab色彩空间"""
                r, g, b = [x / 255.0 for x in rgb]

                # RGB to XYZ
                r = r if r > 0.04045 else r / 12.92
                g = g if g > 0.04045 else g / 12.92
                b = b if b > 0.04045 else b / 12.92

                r = ((r + 0.055) / 1.055) ** 2.4 if r > 0.04045 else r
                g = ((g + 0.055) / 1.055) ** 2.4 if g > 0.04045 else g
                b = ((b + 0.055) / 1.055) ** 2.4 if b > 0.04045 else b

                r *= 100
                g *= 100
                b *= 100

                x = r * 0.4124 + g * 0.3576 + b * 0.1805
                y = r * 0.2126 + g * 0.7152 + b * 0.0722
                z = r * 0.0193 + g * 0.1192 + b * 0.9505

                # XYZ to Lab
                x /= 95.047
                y /= 100.0
                z /= 108.883

                x = x ** (1/3) if x > 0.008856 else 7.787 * x + 16/116
                y = y ** (1/3) if y > 0.008856 else 7.787 * y + 16/116
                z = z ** (1/3) if z > 0.008856 else 7.787 * z + 16/116

                L = 116 * y - 16
                a = 500 * (x - y)
                b_val = 200 * (y - z)

                return (L, a, b_val)

            # 将Lab转换回RGB
            def lab_to_rgb(lab):
                """将Lab转换回RGB"""
                L, a, b_val = lab

                y = (L + 16) / 116
                x = a / 500 + y
                z = y - b_val / 200

                x = x ** 3 if x ** 3 > 0.008856 else (x - 16/116) / 7.787
                y = y ** 3 if y ** 3 > 0.008856 else (y - 16/116) / 7.787
                z = z ** 3 if z ** 3 > 0.008856 else (z - 16/116) / 7.787

                x *= 95.047
                y *= 100.0
                z *= 108.883

                x /= 100
                y /= 100
                z /= 100

                r = x * 3.2406 + y * -1.5372 + z * -0.4986
                g = x * -0.9689 + y * 1.8758 + z * 0.0415
                b = x * 0.0557 + y * -0.2040 + z * 1.0570

                r = 1.055 * (r ** (1/2.4)) - 0.055 if r > 0.0031308 else 12.92 * r
                g = 1.055 * (g ** (1/2.4)) - 0.055 if g > 0.0031308 else 12.92 * g
                b = 1.055 * (b ** (1/2.4)) - 0.055 if b > 0.0031308 else 12.92 * b

                r = max(0, min(1, r))
                g = max(0, min(1, g))
                b = max(0, min(1, b))

                return (int(r * 255), int(g * 255), int(b * 255))

            # 计算CIEDE2000色差
            def ciede2000(lab1, lab2):
                """计算两个Lab颜色之间的CIEDE2000色差"""
                L1, a1, b1 = lab1
                L2, a2, b2 = lab2

                # 计算C和h
                C1 = math.sqrt(a1**2 + b1**2)
                C2 = math.sqrt(a2**2 + b2**2)
                C_avg = (C1 + C2) / 2

                G = 0.5 * (1 - math.sqrt(C_avg**7 / (C_avg**7 + 25**7)))

                a1_prime = a1 * (1 + G)
                a2_prime = a2 * (1 + G)

                C1_prime = math.sqrt(a1_prime**2 + b1**2)
                C2_prime = math.sqrt(a2_prime**2 + b2**2)

                h1_prime = math.degrees(math.atan2(b1, a1_prime)) % 360
                h2_prime = math.degrees(math.atan2(b2, a2_prime)) % 360

                # 计算ΔL', ΔC', ΔH'
                delta_L_prime = L2 - L1
                delta_C_prime = C2_prime - C1_prime

                if C1_prime * C2_prime == 0:
                    delta_h_prime = 0
                else:
                    if abs(h2_prime - h1_prime) <= 180:
                        delta_h_prime = h2_prime - h1_prime
                    elif h2_prime - h1_prime > 180:
                        delta_h_prime = h2_prime - h1_prime - 360
                    else:
                        delta_h_prime = h2_prime - h1_prime + 360

                delta_H_prime = 2 * math.sqrt(C1_prime * C2_prime) * math.sin(math.radians(delta_h_prime / 2))

                # 计算权重函数
                L_avg = (L1 + L2) / 2
                C_avg_prime = (C1_prime + C2_prime) / 2

                if C1_prime * C2_prime == 0:
                    h_avg_prime = h1_prime + h2_prime
                else:
                    if abs(h1_prime - h2_prime) <= 180:
                        h_avg_prime = (h1_prime + h2_prime) / 2
                    elif h1_prime + h2_prime < 360:
                        h_avg_prime = (h1_prime + h2_prime + 360) / 2
                    else:
                        h_avg_prime = (h1_prime + h2_prime - 360) / 2

                T = (1 -
                     0.17 * math.cos(math.radians(h_avg_prime - 30)) +
                     0.24 * math.cos(math.radians(2 * h_avg_prime)) +
                     0.32 * math.cos(math.radians(3 * h_avg_prime + 6)) -
                     0.20 * math.cos(math.radians(4 * h_avg_prime - 63)))

                delta_theta = 30 * math.exp(-((h_avg_prime - 275) / 25) ** 2)
                R_C = 2 * math.sqrt(C_avg_prime**7 / (C_avg_prime**7 + 25**7))
                S_L = 1 + (0.015 * (L_avg - 50) ** 2) / math.sqrt(20 + (L_avg - 50) ** 2)
                S_C = 1 + 0.045 * C_avg_prime
                S_H = 1 + 0.015 * C_avg_prime * T
                R_T = -math.sin(math.radians(2 * delta_theta)) * R_C

                # 计算最终色差
                delta_E = math.sqrt(
                    (delta_L_prime / S_L) ** 2 +
                    (delta_C_prime / S_C) ** 2 +
                    (delta_H_prime / S_H) ** 2 +
                    R_T * (delta_C_prime / S_C) * (delta_H_prime / S_H)
                )

                return delta_E

            # K-Means聚类
            def kmeans_lab(pixels_rgb, k=8, max_iters=50):
                """在Lab空间进行K-Means聚类"""
                # 转换为Lab空间
                pixels_lab = [rgb_to_lab(p) for p in pixels_rgb]

                # 随机初始化聚类中心
                random.shuffle(pixels_lab)
                centroids = pixels_lab[:k]
                cluster_sizes = [0] * k

                for iteration in range(max_iters):
                    # 分配像素到最近的聚类中心
                    clusters = [[] for _ in range(k)]
                    new_cluster_sizes = [0] * k

                    for pixel in pixels_lab:
                        min_dist = float('inf')
                        closest = 0
                        for i, centroid in enumerate(centroids):
                            dist = ciede2000(pixel, centroid)
                            if dist < min_dist:
                                min_dist = dist
                                closest = i
                        clusters[closest].append(pixel)
                        new_cluster_sizes[closest] += 1

                    # 更新聚类中心
                    new_centroids = []
                    for i, cluster in enumerate(clusters):
                        if cluster:
                            # 计算加权平均
                            avg_L = sum(p[0] for p in cluster) / len(cluster)
                            avg_a = sum(p[1] for p in cluster) / len(cluster)
                            avg_b = sum(p[2] for p in cluster) / len(cluster)
                            new_centroids.append((avg_L, avg_a, avg_b))
                        else:
                            # 空聚类，随机选择一个新的中心
                            new_centroids.append(random.choice(pixels_lab))

                    # 检查收敛
                    converged = True
                    for i in range(k):
                        if ciede2000(centroids[i], new_centroids[i]) > 1.0:
                            converged = False
                            break

                    centroids = new_centroids
                    cluster_sizes = new_cluster_sizes

                    if converged:
                        break

                return centroids, cluster_sizes

            # 执行K-Means聚类（K=8，后续筛选为5个）
            centroids, cluster_sizes = kmeans_lab(valid_pixels, k=8, max_iters=30)

            # 将聚类中心按像素数量排序
            centroid_info = list(zip(centroids, cluster_sizes))
            centroid_info.sort(key=lambda x: x[1], reverse=True)

            # 使用CIEDE2000筛选差异明显的颜色（阈值：20）
            min_delta_e = 20  # CIEDE2000色差阈值
            selected_colors_lab = []

            for centroid, size in centroid_info:
                if len(selected_colors_lab) >= 5:
                    break

                # 检查与已选颜色的差异
                is_different = True
                for selected in selected_colors_lab:
                    delta_e = ciede2000(centroid, selected)
                    if delta_e < min_delta_e:
                        is_different = False
                        break

                if is_different:
                    selected_colors_lab.append(centroid)

            # 如果选不够5个，降低阈值继续选择
            if len(selected_colors_lab) < 5:
                for centroid, size in centroid_info:
                    if len(selected_colors_lab) >= 5:
                        break
                    if centroid not in selected_colors_lab:
                        # 检查与已选颜色的差异（使用更低的阈值）
                        is_different = True
                        for selected in selected_colors_lab:
                            delta_e = ciede2000(centroid, selected)
                            if delta_e < 10:  # 降低阈值
                                is_different = False
                                break
                        if is_different:
                            selected_colors_lab.append(centroid)

            # 如果仍然不足5个，生成互补色
            while len(selected_colors_lab) < 5:
                if len(selected_colors_lab) == 0:
                    # 随机生成
                    new_lab = (random.uniform(20, 80), random.uniform(-100, 100), random.uniform(-100, 100))
                else:
                    # 找到已有颜色在Lab空间中距离最远的点
                    avg_L = sum(c[0] for c in selected_colors_lab) / len(selected_colors_lab)
                    avg_a = sum(c[1] for c in selected_colors_lab) / len(selected_colors_lab)
                    avg_b = sum(c[2] for c in selected_colors_lab) / len(selected_colors_lab)
                    # 在Lab空间中取反方向
                    new_lab = (100 - avg_L, -avg_a, -avg_b)

                # 验证差异性
                is_different = True
                for selected in selected_colors_lab:
                    if ciede2000(new_lab, selected) < min_delta_e:
                        is_different = False
                        break

                if is_different:
                    selected_colors_lab.append(new_lab)
                else:
                    # 强制添加，但进行随机扰动
                    perturbed = (
                        max(0, min(100, new_lab[0] + random.uniform(-20, 20))),
                        max(-128, min(127, new_lab[1] + random.uniform(-30, 30))),
                        max(-128, min(127, new_lab[2] + random.uniform(-30, 30)))
                    )
                    selected_colors_lab.append(perturbed)

            # 转换为RGB
            final_colors = [lab_to_rgb(lab) for lab in selected_colors_lab[:5]]

            # 转换为QColor列表
            qt_colors = [QColor(r, g, b) for r, g, b in final_colors]

            # 设置自定义颜色主题
            self.setCustomColors(qt_colors)

            # 打印调试信息
            debug_info = []
            for i, lab in enumerate(selected_colors_lab[:5]):
                debug_info.append(f"Lab{i}=({lab[0]:.0f},{lab[1]:.0f},{lab[2]:.0f})")
            print(f"[AudioBackground] 从封面提取了{len(selected_colors_lab)}个颜色: {', '.join(debug_info)}")

        except Exception as e:
            print(f"[AudioBackground] 从封面提取颜色失败: {e}")
            import traceback
            traceback.print_exc()
            self.useAccentTheme()

    def _load_default_cover(self):
        """加载默认音乐图标（SVG）"""
        try:
            # 查找音乐图标SVG文件
            possible_paths = [
                os.path.join(os.path.dirname(__file__), '..', 'icons', '音乐_playing.svg'),
                os.path.join(os.path.dirname(__file__), '..', 'icons', '音乐.svg'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', '音乐_playing.svg'),
                os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', '音乐.svg'),
            ]

            svg_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    svg_path = path
                    break

            if not svg_path:
                print("[AudioBackground] 未找到音乐SVG图标")
                return

            # 清理布局中可能残留的widget
            while self._svg_container_layout.count() > 0:
                item = self._svg_container_layout.takeAt(0)
                if item.widget():
                    item.widget().hide()

            # 读取SVG文件并进行颜色替换
            from ..core.svg_renderer import SvgRenderer
            with open(svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            svg_content = SvgRenderer._replace_svg_colors(svg_content)

            # 创建QSvgWidget并添加到SVG容器布局中
            self._svg_widget = QSvgWidget()
            self._svg_widget.load(svg_content.encode('utf-8'))
            self._svg_widget.setStyleSheet("background: transparent; border: none;")

            # 获取SVG原始尺寸并设置widget大小
            svg_size = self._svg_widget.renderer().defaultSize()
            aspect_ratio = svg_size.width() / svg_size.height() if svg_size.height() > 0 else 1.0

            # 计算适合cover_size的尺寸（保持比例）
            if aspect_ratio >= 1:
                widget_width = self._cover_size
                widget_height = int(self._cover_size / aspect_ratio)
            else:
                widget_height = self._cover_size
                widget_width = int(self._cover_size * aspect_ratio)

            self._svg_widget.setFixedSize(widget_width, widget_height)

            # 将SVG widget添加到容器布局中（布局会自动居中）
            self._svg_container_layout.addWidget(self._svg_widget, alignment=Qt.AlignCenter)
            self._svg_container.show()
            # 强制更新布局
            self._svg_container_layout.update()
            self._cover_layout.update()

            print(f"[AudioBackground] 已加载默认音乐图标: {svg_path}, 尺寸: {widget_width}x{widget_height}")

        except Exception as e:
            print(f"[AudioBackground] 加载默认图标失败: {e}")
            import traceback
            traceback.print_exc()

    def _reload_current_cover(self):
        """
        重新加载当前封面图像以应用新的尺寸
        使用原始封面数据重新生成指定尺寸的封面图像
        """
        if self._cover_data is None:
            return

        try:
            # 从原始数据重新加载图像
            image = Image.open(io.BytesIO(self._cover_data))

            # 转换为RGBA模式
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            # 缩放到新的显示尺寸（保持比例）
            display_image = image.copy()
            display_image.thumbnail((self._cover_size, self._cover_size), Image.Resampling.LANCZOS)

            # 转换为QPixmap
            self._cover_pixmap = self._pil_to_pixmap(display_image)

            # 更新封面显示
            self._cover_label.setPixmap(self._cover_pixmap)
            self._cover_label.setMinimumSize(self._cover_pixmap.size())
            self._cover_layout.update()

            print(f"[AudioBackground] 封面已重新调整尺寸: {display_image.size}")

        except Exception as e:
            print(f"[AudioBackground] 重新加载封面失败: {e}")

    def _reload_current_svg(self):
        """
        重新调整SVG图标尺寸
        """
        if self._svg_widget is None:
            return

        try:
            # 获取SVG原始尺寸
            svg_size = self._svg_widget.renderer().defaultSize()
            aspect_ratio = svg_size.width() / svg_size.height() if svg_size.height() > 0 else 1.0

            # 计算适合新cover_size的尺寸（保持比例）
            if aspect_ratio >= 1:
                widget_width = self._cover_size
                widget_height = int(self._cover_size / aspect_ratio)
            else:
                widget_height = self._cover_size
                widget_width = int(self._cover_size * aspect_ratio)

            self._svg_widget.setFixedSize(widget_width, widget_height)
            self._svg_container_layout.update()

            print(f"[AudioBackground] SVG图标已重新调整尺寸: {widget_width}x{widget_height}")

        except Exception as e:
            print(f"[AudioBackground] 重新调整SVG尺寸失败: {e}")

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
            self.update()
            return
        
        # 检查缓存
        cache = CoverCache()
        cached = cache.get(self._cover_data)
        if cached and cached.get('blurred_pixmap'):
            self._blurred_pixmap = cached['blurred_pixmap']
            self.update()
            return
        
        try:
            # 从二进制数据加载图像
            image = Image.open(io.BytesIO(self._cover_data))
            
            # 转换为RGB模式
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # 目标分辨率 1080P (1920x1080) - 从2560x1440降低以优化性能
            target_width = 1920
            target_height = 1080
            
            # 计算适合缩放的尺寸（保持比例，填满目标区域）
            img_width, img_height = image.size
            scale = max(target_width / img_width, target_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            
            # 缩放图像 - 使用BILINEAR代替LANCZOS以提高性能
            image_resized = image.resize((new_width, new_height), Image.Resampling.BILINEAR)
            
            # 居中裁剪到目标尺寸
            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            right = left + target_width
            bottom = top + target_height
            image_cropped = image_resized.crop((left, top, right, bottom))
            
            # 应用高斯模糊 - 半径从30降至15以优化性能
            image_blurred = image_cropped.filter(ImageFilter.GaussianBlur(radius=15))
            
            # 转换为QPixmap
            self._blurred_pixmap = self._pil_to_pixmap(image_blurred)
            
            # 存入缓存
            cache.put(self._cover_data, blurred_pixmap=self._blurred_pixmap)
            
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
        """
        大小调整事件
        窗口大小变化时更新封面容器几何区域，确保封面图片始终居中显示
        同时根据窗口大小自动调整封面尺寸
        """
        super().resizeEvent(event)
        # 封面容器使用整个父窗口区域，布局系统会自动居中内容
        if self._is_loaded and self._cover_container.isVisible():
            self._cover_container.setGeometry(self.rect())
            # 根据窗口大小自动调整封面尺寸
            self._update_cover_size()
        self.update()

    def _update_cover_size(self):
        """
        根据窗口大小自动调整封面尺寸
        优先保持封面居中，空间不足时缩小，空间充足时恢复
        """
        if not self._is_loaded:
            return

        # 获取当前窗口可用空间（减去控制栏高度约100像素，边距只影响布局不影响图片本身）
        available_width = self.width()
        available_height = self.height() - 100

        # 计算当前封面尺寸是否能容纳在可用空间中
        current_size = self._cover_size

        # 如果当前尺寸可以容纳且未达到最大尺寸，尝试恢复
        if current_size <= available_width and current_size <= available_height:
            # 如果当前尺寸小于最大尺寸，尝试恢复到最大尺寸
            if current_size < self._max_cover_size:
                # 计算可以恢复到的尺寸（不超过最大尺寸）
                new_size = min(self._max_cover_size, int(min(available_width, available_height)))
                # 只有当新尺寸大于当前尺寸时才更新
                if new_size > current_size:
                    self._cover_size = new_size
                    # 重新加载当前封面以应用新尺寸
                    if self._cover_pixmap is not None:
                        self._reload_current_cover()
                    elif self._svg_widget is not None:
                        self._reload_current_svg()
            return

        # 空间不足，需要缩小封面
        # 计算适合当前窗口的最大封面尺寸
        max_size = min(available_width, available_height)

        # 限制在最小和最大尺寸之间（最小尺寸限制图片本身的大小，不受边距影响）
        new_size = max(self._min_cover_size, min(self._max_cover_size, int(max_size)))

        # 如果尺寸发生变化，更新封面显示
        if new_size != self._cover_size:
            self._cover_size = new_size
            # 重新加载当前封面以应用新尺寸
            if self._cover_pixmap is not None:
                self._reload_current_cover()
            elif self._svg_widget is not None:
                self._reload_current_svg()

    def hideEvent(self, event):
        """
        窗口隐藏事件
        在窗口不可见时暂停动画以节省资源
        """
        super().hideEvent(event)
        # 暂停流体动画
        if self._current_mode == self.MODE_FLUID and self._is_loaded:
            self.pauseAnimation()
            print("[AudioBackground] 窗口隐藏，暂停动画")

    def showEvent(self, event):
        """
        窗口显示事件
        在窗口重新可见时恢复动画
        """
        super().showEvent(event)
        # 恢复流体动画
        if self._current_mode == self.MODE_FLUID and self._is_loaded:
            self.resumeAnimation()
            print("[AudioBackground] 窗口显示，恢复动画")

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

        # 封面图像现在通过 _cover_container widget 显示，不需要在这里绘制

    def _paint_cover_blur_background(self, painter: QPainter, width: int, height: int):
        """绘制封面模糊背景"""
        # 1. 绘制黑色背景（100%不透明）
        painter.fillRect(0, 0, width, height, QColor("#000000"))
        
        # 2. 绘制模糊图像（100%不透明，完全填充）
        if self._blurred_pixmap and not self._blurred_pixmap.isNull():
            display_rect = self._calculate_scaled_rect()
            
            scaled_pixmap = self._blurred_pixmap.scaled(
                display_rect.width(),
                display_rect.height(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            
            # 计算居中位置
            draw_x = (width - scaled_pixmap.width()) // 2
            draw_y = (height - scaled_pixmap.height()) // 2
            
            painter.setOpacity(1.0)
            painter.drawPixmap(draw_x, draw_y, scaled_pixmap)
    
    def clear(self):
        """清除数据"""
        self._cover_data = None
        self._blurred_pixmap = None
        self.update()
