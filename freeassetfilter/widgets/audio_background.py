#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源

音频背景组件
支持两种背景模式：
1. 流体动画 - Apple Music 风格的大面积柔和流体色块背景
2. 封面模糊 - 使用音频封面图像，拉伸并模糊处理
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPointF, Signal, QRect, QRectF, QRunnable, QThreadPool, QMutex, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter,
    QColor,
    QRadialGradient,
    QBrush,
    QLinearGradient,
    QPixmap,
    QImage,
    QPainterPath,
)
from PySide6.QtSvgWidgets import QSvgWidget
from PIL import Image, ImageFilter
from collections import OrderedDict
import io
import json
import random
import os
import math
import hashlib
import time
import tempfile
import threading

from freeassetfilter.utils.app_logger import info, debug, warning

try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    _OPENGL_WIDGET_AVAILABLE = True
except ImportError:
    QOpenGLWidget = QWidget
    _OPENGL_WIDGET_AVAILABLE = False


class CoverCache:
    """
    封面图像缓存类，使用 OrderedDict 实现 LRU 策略
    缓存内容：封面二进制哈希 -> {colors, blurred_pixmap, cover_pixmap}
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
        return hashlib.md5(cover_data).hexdigest()

    def get(self, cover_data: bytes):
        key = self._get_key(cover_data)
        self._mutex.lock()
        try:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None
        finally:
            self._mutex.unlock()

    def put(self, cover_data: bytes, colors=None, blurred_pixmap=None, cover_pixmap=None):
        key = self._get_key(cover_data)
        self._mutex.lock()
        try:
            if key in self._cache:
                existing = self._cache[key]
                merged = {
                    'colors': colors if colors is not None else existing.get('colors'),
                    'blurred_pixmap': (
                        blurred_pixmap if blurred_pixmap is not None else existing.get('blurred_pixmap')
                    ),
                    'cover_pixmap': cover_pixmap if cover_pixmap is not None else existing.get('cover_pixmap'),
                    'timestamp': time.time(),
                }
                self._cache.move_to_end(key)
                self._cache[key] = merged
                return

            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)

            self._cache[key] = {
                'colors': colors,
                'blurred_pixmap': blurred_pixmap,
                'cover_pixmap': cover_pixmap,
                'timestamp': time.time(),
            }
        finally:
            self._mutex.unlock()

    def clear(self):
        self._mutex.lock()
        try:
            self._cache.clear()
        finally:
            self._mutex.unlock()


class PersistentBackgroundColorCache:
    """
    背景色持久化缓存（单文件 JSON）

    仅缓存：
    - 封面二进制哈希 -> 颜色列表 [(r, g, b), ...]

    不缓存 pixmap，避免文件过大。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, max_entries=500):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_entries=500):
        if getattr(self, "_initialized", False):
            return

        self._initialized = True
        self._max_entries = max_entries
        self._cache_lock = threading.RLock()
        self._cache = OrderedDict()
        self._cache_file = self._get_cache_file_path()
        self._load()

    def _get_cache_file_path(self) -> str:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        data_dir = os.path.join(project_root, "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "audio_background_color_cache.json")

    def _get_key(self, cover_data: bytes) -> str:
        return hashlib.md5(cover_data).hexdigest()

    def _load(self):
        with self._cache_lock:
            try:
                if not os.path.exists(self._cache_file):
                    self._cache = OrderedDict()
                    return

                with open(self._cache_file, "r", encoding="utf-8") as file:
                    data = json.load(file)

                entries = data.get("entries", [])
                loaded = OrderedDict()
                for item in entries:
                    key = item.get("key")
                    colors = item.get("colors")
                    if not key or not isinstance(colors, list):
                        continue

                    normalized_colors = []
                    for color in colors[:5]:
                        if (
                            isinstance(color, (list, tuple))
                            and len(color) >= 3
                        ):
                            normalized_colors.append(
                                [int(color[0]), int(color[1]), int(color[2])]
                            )

                    if normalized_colors:
                        loaded[key] = {
                            "colors": normalized_colors,
                            "timestamp": float(item.get("timestamp", time.time())),
                        }

                self._cache = loaded
                debug(f"[PersistentBackgroundColorCache] 已加载 {len(self._cache)} 条颜色缓存")

            except (OSError, IOError, ValueError, TypeError, json.JSONDecodeError) as e:
                warning(f"[PersistentBackgroundColorCache] 加载缓存失败: {e}")
                self._cache = OrderedDict()

    def _save(self):
        with self._cache_lock:
            try:
                entries = []
                for key, value in self._cache.items():
                    entries.append({
                        "key": key,
                        "colors": value.get("colors", []),
                        "timestamp": value.get("timestamp", time.time()),
                    })

                payload = {
                    "version": 1,
                    "entries": entries,
                }

                cache_dir = os.path.dirname(self._cache_file)
                os.makedirs(cache_dir, exist_ok=True)

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=cache_dir,
                    delete=False,
                    suffix=".tmp"
                ) as tmp_file:
                    json.dump(payload, tmp_file, ensure_ascii=False, indent=2)
                    tmp_file.flush()
                    os.fsync(tmp_file.fileno())
                    temp_path = tmp_file.name

                os.replace(temp_path, self._cache_file)

            except (OSError, IOError, TypeError, ValueError) as e:
                warning(f"[PersistentBackgroundColorCache] 保存缓存失败: {e}")
            finally:
                temp_path = locals().get("temp_path")
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

    def get_colors(self, cover_data: bytes):
        key = self._get_key(cover_data)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                item = self._cache[key]
                return item.get("colors")
            return None

    def put_colors(self, cover_data: bytes, colors):
        if not cover_data or not colors:
            return

        normalized_colors = []
        for color in colors[:5]:
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                normalized_colors.append([int(color[0]), int(color[1]), int(color[2])])

        if not normalized_colors:
            return

        key = self._get_key(cover_data)
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)

            self._cache[key] = {
                "colors": normalized_colors,
                "timestamp": time.time(),
            }

            while len(self._cache) > self._max_entries:
                self._cache.popitem(last=False)

        self._save()


class ColorExtractionTask(QRunnable):
    """
    颜色提取任务类，继承自 QRunnable
    在后台线程中执行颜色提取，避免阻塞主线程
    优先使用 Rust DLL 实现，随后进行视觉增强后处理
    """

    def __init__(self, task_id: int, cover_data: bytes, callback, widget_ref):
        super().__init__()
        self.task_id = task_id
        self.cover_data = cover_data
        self.callback = callback
        self.widget_ref = widget_ref
        self._cancel_event = threading.Event()

        self._rust_available = False
        self._rust_module = None
        try:
            from ..core.native import rust_color_extractor
            self._rust_available = True
            self._rust_module = rust_color_extractor
        except ImportError:
            pass

    def cancel(self):
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self):
        if self.is_cancelled():
            return

        try:
            base_colors = None
            rust_palette_ready = False

            if self._rust_available:
                base_colors = self._extract_colors_rust()
                if base_colors and len(base_colors) >= 5:
                    rust_palette_ready = True
                elif not base_colors:
                    warning("[ColorExtractionTask] Rust 提取失败，降级到 Python 实现")

            if not base_colors and not self.is_cancelled():
                base_colors = self._extract_colors_python()

            if self.is_cancelled():
                return

            if not base_colors:
                if self.callback and not self.is_cancelled():
                    self.callback(self.task_id, None)
                return

            if rust_palette_ready:
                styled_colors = [
                    (int(c[0]), int(c[1]), int(c[2]))
                    for c in base_colors[:5]
                    if isinstance(c, (list, tuple)) and len(c) >= 3
                ]
            else:
                styled_colors = self._build_visual_palette(base_colors)

            if self.callback and not self.is_cancelled():
                self.callback(self.task_id, styled_colors)

        except (RuntimeError, ValueError, IOError) as e:
            warning(f"[ColorExtractionTask] 颜色提取失败: {e}")
            if self.callback and not self.is_cancelled():
                self.callback(self.task_id, None)

    def _extract_colors_rust(self) -> list:
        try:
            import struct

            start_time = time.time()

            image = Image.open(io.BytesIO(self.cover_data))
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            width, height = image.size
            pixels = image.tobytes()

            header = struct.pack('ii', width, height)
            image_data = header + pixels

            # Rust 端已经包含聚类、主题筛选与视觉配色构建
            colors_rgb = self._rust_module.extract_colors(
                image_data,
                num_colors=5,
                min_distance=22.0,
                max_image_size=160,
            )

            elapsed = (time.time() - start_time) * 1000
            debug(f"[ColorExtractionTask] Rust 提取完成，耗时 {elapsed:.2f}ms")
            return colors_rgb

        except (ImportError, AttributeError, RuntimeError, IOError, ValueError) as e:
            warning(f"[ColorExtractionTask] Rust 提取异常: {e}")
            return None

    def _extract_colors_python(self) -> list:
        try:
            image = Image.open(io.BytesIO(self.cover_data))
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            small_image = image.copy()
            small_image.thumbnail((160, 160), Image.Resampling.LANCZOS)

            pixels = list(small_image.getdata())
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
                if brightness > 245 or brightness < 12:
                    continue

                valid_pixels.append((r, g, b))

            if len(valid_pixels) < 10:
                return None

            if len(valid_pixels) > 6000:
                valid_pixels = random.sample(valid_pixels, 6000)

            centroids, cluster_sizes = self._kmeans_lab(valid_pixels, k=8, max_iters=30)
            centroid_info = list(zip(centroids, cluster_sizes))
            centroid_info.sort(key=lambda x: x[1], reverse=True)

            selected_colors_lab = []
            min_delta_e = 26.0

            for centroid, _size in centroid_info:
                if len(selected_colors_lab) >= 6:
                    break

                if all(self._ciede2000(centroid, selected) >= min_delta_e for selected in selected_colors_lab):
                    selected_colors_lab.append(centroid)

            if len(selected_colors_lab) < 4:
                for centroid, _size in centroid_info:
                    if centroid not in selected_colors_lab:
                        selected_colors_lab.append(centroid)
                    if len(selected_colors_lab) >= 6:
                        break

            final_colors = [self._lab_to_rgb(lab) for lab in selected_colors_lab[:6]]
            debug("[ColorExtractionTask] Python 提取完成")
            return final_colors

        except (IOError, ValueError) as e:
            warning(f"[ColorExtractionTask] Python 提取失败: {e}")
            return None

    def _rgb_to_lab(self, rgb):
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

        x = x ** (1 / 3) if x > 0.008856 else 7.787 * x + 16 / 116
        y = y ** (1 / 3) if y > 0.008856 else 7.787 * y + 16 / 116
        z = z ** (1 / 3) if z > 0.008856 else 7.787 * z + 16 / 116

        l_val = 116 * y - 16
        a_val = 500 * (x - y)
        b_val = 200 * (y - z)

        return (l_val, a_val, b_val)

    def _lab_to_rgb(self, lab):
        l_val, a_val, b_val = lab

        y = (l_val + 16) / 116
        x = a_val / 500 + y
        z = y - b_val / 200

        x = x ** 3 if x ** 3 > 0.008856 else (x - 16 / 116) / 7.787
        y = y ** 3 if y ** 3 > 0.008856 else (y - 16 / 116) / 7.787
        z = z ** 3 if z ** 3 > 0.008856 else (z - 16 / 116) / 7.787

        x *= 95.047
        y *= 100.0
        z *= 108.883

        x /= 100
        y /= 100
        z /= 100

        r = x * 3.2406 + y * -1.5372 + z * -0.4986
        g = x * -0.9689 + y * 1.8758 + z * 0.0415
        b = x * 0.0557 + y * -0.2040 + z * 1.0570

        r = 1.055 * (r ** (1 / 2.4)) - 0.055 if r > 0.0031308 else 12.92 * r
        g = 1.055 * (g ** (1 / 2.4)) - 0.055 if g > 0.0031308 else 12.92 * g
        b = 1.055 * (b ** (1 / 2.4)) - 0.055 if b > 0.0031308 else 12.92 * b

        r = max(0, min(1, r))
        g = max(0, min(1, g))
        b = max(0, min(1, b))

        return (int(r * 255), int(g * 255), int(b * 255))

    def _ciede2000(self, lab1, lab2):
        l1, a1, b1 = lab1
        l2, a2, b2 = lab2

        c1 = math.sqrt(a1 ** 2 + b1 ** 2)
        c2 = math.sqrt(a2 ** 2 + b2 ** 2)
        c_avg = (c1 + c2) / 2

        g_factor = 0.5 * (1 - math.sqrt(c_avg ** 7 / (c_avg ** 7 + 25 ** 7))) if c_avg else 0

        a1_prime = a1 * (1 + g_factor)
        a2_prime = a2 * (1 + g_factor)

        c1_prime = math.sqrt(a1_prime ** 2 + b1 ** 2)
        c2_prime = math.sqrt(a2_prime ** 2 + b2 ** 2)

        h1_prime = math.degrees(math.atan2(b1, a1_prime)) % 360
        h2_prime = math.degrees(math.atan2(b2, a2_prime)) % 360

        delta_l_prime = l2 - l1
        delta_c_prime = c2_prime - c1_prime

        if c1_prime * c2_prime == 0:
            delta_h_prime = 0
        else:
            if abs(h2_prime - h1_prime) <= 180:
                delta_h_prime = h2_prime - h1_prime
            elif h2_prime - h1_prime > 180:
                delta_h_prime = h2_prime - h1_prime - 360
            else:
                delta_h_prime = h2_prime - h1_prime + 360

        delta_h_component = 2 * math.sqrt(c1_prime * c2_prime) * math.sin(math.radians(delta_h_prime / 2))

        l_avg = (l1 + l2) / 2
        c_avg_prime = (c1_prime + c2_prime) / 2

        if c1_prime * c2_prime == 0:
            h_avg_prime = h1_prime + h2_prime
        else:
            if abs(h1_prime - h2_prime) <= 180:
                h_avg_prime = (h1_prime + h2_prime) / 2
            elif h1_prime + h2_prime < 360:
                h_avg_prime = (h1_prime + h2_prime + 360) / 2
            else:
                h_avg_prime = (h1_prime + h2_prime - 360) / 2

        t_factor = (
            1
            - 0.17 * math.cos(math.radians(h_avg_prime - 30))
            + 0.24 * math.cos(math.radians(2 * h_avg_prime))
            + 0.32 * math.cos(math.radians(3 * h_avg_prime + 6))
            - 0.20 * math.cos(math.radians(4 * h_avg_prime - 63))
        )

        delta_theta = 30 * math.exp(-((h_avg_prime - 275) / 25) ** 2)
        r_c = 2 * math.sqrt(c_avg_prime ** 7 / (c_avg_prime ** 7 + 25 ** 7)) if c_avg_prime else 0
        s_l = 1 + (0.015 * (l_avg - 50) ** 2) / math.sqrt(20 + (l_avg - 50) ** 2)
        s_c = 1 + 0.045 * c_avg_prime
        s_h = 1 + 0.015 * c_avg_prime * t_factor
        r_t = -math.sin(math.radians(2 * delta_theta)) * r_c

        return math.sqrt(
            (delta_l_prime / s_l) ** 2
            + (delta_c_prime / s_c) ** 2
            + (delta_h_component / s_h) ** 2
            + r_t * (delta_c_prime / s_c) * (delta_h_component / s_h)
        )

    def _kmeans_lab(self, pixels_rgb, k=8, max_iters=50):
        pixels_lab = [self._rgb_to_lab(p) for p in pixels_rgb]
        random.shuffle(pixels_lab)
        centroids = pixels_lab[:k]
        cluster_sizes = [0] * k

        for _iteration in range(max_iters):
            clusters = [[] for _ in range(k)]
            new_cluster_sizes = [0] * k

            for pixel in pixels_lab:
                min_dist = float('inf')
                closest = 0
                for index, centroid in enumerate(centroids):
                    dist = self._ciede2000(pixel, centroid)
                    if dist < min_dist:
                        min_dist = dist
                        closest = index
                clusters[closest].append(pixel)
                new_cluster_sizes[closest] += 1

            new_centroids = []
            for cluster in clusters:
                if cluster:
                    avg_l = sum(p[0] for p in cluster) / len(cluster)
                    avg_a = sum(p[1] for p in cluster) / len(cluster)
                    avg_b = sum(p[2] for p in cluster) / len(cluster)
                    new_centroids.append((avg_l, avg_a, avg_b))
                else:
                    new_centroids.append(random.choice(pixels_lab))

            converged = True
            for index in range(k):
                if self._ciede2000(centroids[index], new_centroids[index]) > 1.0:
                    converged = False
                    break

            centroids = new_centroids
            cluster_sizes = new_cluster_sizes

            if converged:
                break

        return centroids, cluster_sizes

    def _build_visual_palette(self, colors_rgb):
        """
        从基础提取结果构建 3 个主题色 + 2 个过渡色：
        [主题色1, 过渡色1, 主题色2, 过渡色2, 主题色3]

        优先使用已提取结果，避免重复对封面再次做 KMeans。
        """
        theme_colors = self._extract_theme_seed_colors_from_base(colors_rgb)

        # 仅在基础结果不足时才回退到二次提取（低概率路径）
        if len(theme_colors) < 3:
            theme_colors = self._extract_theme_seed_colors()

        if len(theme_colors) < 3:
            return None

        ordered = sorted(theme_colors[:3], key=lambda c: 999 if c.hue() < 0 else c.hue())
        transition_1 = self._mix_transition_color(ordered[0], ordered[1])
        transition_2 = self._mix_transition_color(ordered[1], ordered[2])

        palette = [
            ordered[0],
            transition_1,
            ordered[1],
            transition_2,
            ordered[2],
        ]

        result = [(c.red(), c.green(), c.blue()) for c in palette]
        debug(
            "[ColorExtractionTask] 视觉配色生成完成: "
            + ", ".join([f"({r},{g},{b})" for r, g, b in result])
        )
        return result

    def _extract_theme_seed_colors_from_base(self, colors_rgb):
        """
        基于已有提取结果选择 3 个主题种子色，避免再次遍历整张封面图。
        """
        prepared = []
        for color in colors_rgb or []:
            if not isinstance(color, (list, tuple)) or len(color) < 3:
                continue
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            prepared.append(self._prepare_color_for_background(QColor(r, g, b)))

        if not prepared:
            return []

        # 优先高饱和/高亮，增强流体背景视觉层次
        prepared.sort(key=lambda c: (c.saturation(), c.value()), reverse=True)

        selected = []
        min_hue_distance = 20
        for color in prepared:
            if len(selected) >= 3:
                break

            hue = color.hue()
            if all(self._hue_distance(hue, chosen.hue()) >= min_hue_distance for chosen in selected):
                selected.append(color)

        if len(selected) < 3:
            for color in prepared:
                if len(selected) >= 3:
                    break
                if color not in selected:
                    selected.append(color)

        return selected[:3]

    def _extract_theme_seed_colors(self):
        """
        从封面图中提取 3 个主题色：
        - 优先按占比排序
        - 但彼此不能过近
        """
        try:
            image = Image.open(io.BytesIO(self.cover_data))
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            small_image = image.copy()
            small_image.thumbnail((160, 160), Image.Resampling.LANCZOS)

            pixels = list(small_image.getdata())
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
                if brightness > 245 or brightness < 12:
                    continue

                valid_pixels.append((r, g, b))

            if len(valid_pixels) < 10:
                return []

            if len(valid_pixels) > 6000:
                valid_pixels = random.sample(valid_pixels, 6000)

            centroids, cluster_sizes = self._kmeans_lab(valid_pixels, k=8, max_iters=30)
            centroid_info = list(zip(centroids, cluster_sizes))
            centroid_info.sort(key=lambda x: x[1], reverse=True)

            selected = []
            for centroid, _size in centroid_info:
                if len(selected) >= 3:
                    break

                if all(self._ciede2000(centroid, chosen) >= 18.0 for chosen in selected):
                    selected.append(centroid)

            if len(selected) < 3:
                for centroid, _size in centroid_info:
                    if len(selected) >= 3:
                        break
                    if centroid not in selected:
                        selected.append(centroid)

            return [self._prepare_color_for_background(QColor(*self._lab_to_rgb(lab))) for lab in selected[:3]]

        except (IOError, ValueError) as e:
            warning(f"[ColorExtractionTask] 提取主题种子色失败: {e}")
            return []

    def _mix_transition_color(self, color_a: QColor, color_b: QColor) -> QColor:
        mixed = QColor(
            int((color_a.red() + color_b.red()) / 2),
            int((color_a.green() + color_b.green()) / 2),
            int((color_a.blue() + color_b.blue()) / 2),
        )
        return self._prepare_color_for_background(mixed, extra_saturation=1.02)

    def _prepare_color_for_background(self, color: QColor, extra_saturation: float = 1.0) -> QColor:
        h, s, v, a = color.getHsv()
        if h < 0:
            h = random.randint(0, 359)

        s = max(88, min(235, int(s * 1.12 * extra_saturation)))
        v = max(92, min(230, int(v * 1.08)))
        return QColor.fromHsv(h, s, v, a)

    def _shift_color(self, color: QColor, hue_shift=0, saturation_mul=1.0, value_mul=1.0) -> QColor:
        h, s, v, a = color.getHsv()
        if h < 0:
            h = random.randint(0, 359)

        h = (h + hue_shift) % 360
        s = max(84, min(235, int(s * saturation_mul)))
        v = max(82, min(235, int(v * value_mul)))
        return QColor.fromHsv(h, s, v, a)

    def _hue_distance(self, h1: int, h2: int) -> int:
        if h1 < 0 or h2 < 0:
            return 180
        diff = abs(h1 - h2) % 360
        return min(diff, 360 - diff)


class FluidOpenGLLayer(QOpenGLWidget):
    """
    基于 QOpenGLWidget 的流体渲染层（GPU 路径）。
    渲染逻辑委托给 AudioBackground._paint_fluid_background。
    """

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self._host = host
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintGL(self):
        if not self._host or not self._host.isLoaded():
            return
        if self._host.getMode() != self._host.MODE_FLUID:
            return

        width = self.width()
        height = self.height()
        if width <= 0 or height <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._host._paint_fluid_background(painter, width, height)
        painter.end()


class AudioBackground(QWidget):
    """
    音频背景组件

    支持两种模式：
    - fluid: Apple Music 风格流体动画背景
    - cover_blur: 封面模糊背景
    """

    themeChanged = Signal(str)
    speedChanged = Signal(float)

    MODE_FLUID = "fluid"
    MODE_COVER_BLUR = "cover_blur"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._is_loaded = False
        self._current_mode = self.MODE_FLUID

        self._current_theme = 'sunset'
        self._animation_speed = 1.0
        self._is_paused = False
        self._animation_timer = None
        self._animation_start_time = time.perf_counter()

        self._theme_colors = {
            'sunset': [
                QColor(255, 109, 126),
                QColor(255, 168, 114),
                QColor(255, 123, 209),
                QColor(234, 85, 169),
                QColor(124, 56, 215),
            ],
            'ocean': [
                QColor(35, 188, 240),
                QColor(34, 139, 230),
                QColor(0, 196, 170),
                QColor(72, 226, 255),
                QColor(24, 87, 188),
            ],
            'aurora': [
                QColor(0, 255, 166),
                QColor(51, 214, 255),
                QColor(97, 129, 255),
                QColor(183, 102, 255),
                QColor(0, 232, 205),
            ],
            'accent': self._generate_accent_colors(),
        }

        self._fluid_blobs = []
        self._fluid_render_scale = 0.38
        self._fluid_blob_softness = 1.12
        self._initialize_fluid_blobs()

        # 流体渲染缓冲复用，避免每帧创建 QImage
        self._fluid_buffer = None
        self._fluid_buffer_size = (0, 0)

        # GPU 流体渲染层
        self._gpu_fluid_enabled = False
        self._fluid_gl_layer = None

        self._cover_data = None
        self._blurred_pixmap = None
        self._blurred_pixmap_key = None

        # 模糊背景缩放缓存，避免 paintEvent 中重复 scaled()
        self._scaled_blur_pixmap_cache = None
        self._scaled_blur_cache_size = (0, 0)
        self._scaled_blur_cache_source_key = None

        self._cover_pixmap = None
        self._cover_source_image = None
        self._cover_source_key = None

        self._cover_size = 200
        self._max_cover_size = 200
        self._min_cover_size = 80
        self._has_resolved_cover_colors = False

        self._color_task_id = 0
        self._current_color_task = None
        self._thread_pool = QThreadPool()
        self._thread_pool.setMaxThreadCount(2)

        self._cover_cache = CoverCache()
        self._persistent_color_cache = PersistentBackgroundColorCache()

        self._cover_container = QWidget(self)
        self._cover_container.setStyleSheet("background: transparent; border: none;")
        self._cover_container.hide()

        self._cover_layout = QVBoxLayout(self._cover_container)
        self._cover_layout.setContentsMargins(0, 0, 0, 0)
        self._cover_layout.setAlignment(Qt.AlignCenter)

        self._cover_label = QLabel(self._cover_container)
        self._cover_label.setAlignment(Qt.AlignCenter)
        self._cover_label.setStyleSheet("background: transparent; border: none;")
        self._cover_label.hide()
        self._cover_layout.addWidget(self._cover_label, alignment=Qt.AlignCenter)

        self._svg_container = QWidget(self._cover_container)
        self._svg_container.setStyleSheet("background: transparent; border: none;")
        self._svg_container_layout = QVBoxLayout(self._svg_container)
        self._svg_container_layout.setContentsMargins(0, 0, 0, 0)
        self._svg_container_layout.setAlignment(Qt.AlignCenter)
        self._svg_container.hide()
        self._cover_layout.addWidget(self._svg_container, alignment=Qt.AlignCenter)

        self._svg_widget = None

        self._cover_opacity_effect = QGraphicsOpacityEffect(self._cover_container)
        self._cover_opacity_effect.setOpacity(1.0)
        self._cover_container.setGraphicsEffect(self._cover_opacity_effect)
        self._cover_fade_anim = QPropertyAnimation(self._cover_opacity_effect, b"opacity", self)
        self._cover_fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._cover_fade_anim.finished.connect(self._on_cover_fade_finished)
        self._cover_fade_phase = None
        self._pending_cover_data = None

        self._theme_transition_previous_colors = None
        self._theme_transition_start_time = 0.0
        self._theme_transition_duration = 0.28

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background-color: transparent;")
        self.setVisible(False)

        self._init_fluid_gl_layer()

    # ==================== 通用方法 ====================

    def _init_fluid_gl_layer(self):
        # 默认禁用 GPU 流体层，避免 Windows 下 QOpenGLWidget 首次 show/hide 触发整窗闪烁。
        # 需要启用时可设置环境变量：FAF_ENABLE_AUDIO_BG_GPU=1
        enable_gpu = os.environ.get("FAF_ENABLE_AUDIO_BG_GPU", "0") == "1"
        if not enable_gpu:
            self._gpu_fluid_enabled = False
            self._fluid_gl_layer = None
            debug("[AudioBackground] GPU 流体渲染层已禁用（默认）")
            return

        if not _OPENGL_WIDGET_AVAILABLE:
            self._gpu_fluid_enabled = False
            self._fluid_gl_layer = None
            return

        try:
            self._fluid_gl_layer = FluidOpenGLLayer(self, self)
            self._fluid_gl_layer.setGeometry(self.rect())
            self._fluid_gl_layer.hide()
            self._fluid_gl_layer.lower()
            self._gpu_fluid_enabled = True
            debug("[AudioBackground] 已启用 GPU 流体渲染层")
        except Exception as e:
            self._fluid_gl_layer = None
            self._gpu_fluid_enabled = False
            warning(f"[AudioBackground] 启用 GPU 流体渲染失败，回退 CPU 路径: {e}")

    def _show_fluid_gl_layer(self):
        if self._gpu_fluid_enabled and self._fluid_gl_layer:
            self._fluid_gl_layer.setGeometry(self.rect())
            self._fluid_gl_layer.show()
            self._fluid_gl_layer.lower()
            self._cover_container.raise_()

    def _hide_fluid_gl_layer(self):
        if self._fluid_gl_layer:
            self._fluid_gl_layer.hide()

    def _request_fluid_repaint(self):
        if (
            self._gpu_fluid_enabled
            and self._fluid_gl_layer
            and self._fluid_gl_layer.isVisible()
        ):
            self._fluid_gl_layer.update()
        else:
            self.update()

    def load(self, mode=None):
        if mode:
            self._current_mode = mode

        if self._is_loaded:
            return

        self._is_loaded = True
        self.setVisible(True)

        if self._current_mode == self.MODE_FLUID:
            self._start_fluid_animation()
            self._show_fluid_gl_layer()
        else:
            self._hide_fluid_gl_layer()

        self._cover_container.show()
        self._cover_container.raise_()
        QTimer.singleShot(0, self._init_cover_container_geometry)
        self.update()

    def _init_cover_container_geometry(self):
        self._cover_container.setGeometry(self.rect())
        self._update_cover_size()
        if self._fluid_gl_layer:
            self._fluid_gl_layer.setGeometry(self.rect())
            self._fluid_gl_layer.lower()
        self._cover_container.raise_()

    def unload(self):
        if not self._is_loaded:
            return

        self._is_loaded = False
        self._stop_fluid_animation()
        self._hide_fluid_gl_layer()

        if self._current_color_task:
            self._current_color_task.cancel()
            self._current_color_task = None

        # 音频封面配色提取使用了 QThreadPool，若应用关闭时仅 cancel 而不等待，
        # worker 线程可能仍在执行，导致主窗口关闭后进程残留。
        # 这里在卸载阶段等待短时间，尽量确保后台任务已经退出。
        if self._thread_pool is not None:
            try:
                self._thread_pool.waitForDone(1500)
            except Exception as e:
                warning(f"[AudioBackground] 等待颜色提取线程池结束失败: {e}")

        self._cover_data = None
        self._blurred_pixmap = None
        self._blurred_pixmap_key = None
        self._cover_pixmap = None
        self._cover_source_image = None
        self._cover_source_key = None
        self._has_resolved_cover_colors = False
        self._pending_cover_data = None
        self._cover_fade_phase = None
        self._cover_fade_anim.stop()
        self._cover_opacity_effect.setOpacity(1.0)
        self._theme_transition_previous_colors = None

        self._fluid_buffer = None
        self._fluid_buffer_size = (0, 0)
        self._invalidate_blur_scaled_cache()

        self._cover_label.hide()
        self._svg_container.hide()
        self._cover_container.hide()

        if self._svg_widget:
            self._svg_widget.hide()
            self._svg_widget.deleteLater()
            self._svg_widget = None

        self.setVisible(False)

    def isLoaded(self) -> bool:
        return self._is_loaded

    def setMode(self, mode: str):
        if mode not in [self.MODE_FLUID, self.MODE_COVER_BLUR]:
            return

        if self._current_mode == mode:
            return

        self._current_mode = mode

        if self._is_loaded:
            if mode == self.MODE_FLUID:
                self._blurred_pixmap = None
                self._blurred_pixmap_key = None
                self._invalidate_blur_scaled_cache()
                self._start_fluid_animation()
                self._show_fluid_gl_layer()
                self._request_fluid_repaint()
            else:
                self._hide_fluid_gl_layer()
                self._stop_fluid_animation()
                if self._cover_data:
                    self._process_cover()
                self.update()

    def getMode(self) -> str:
        return self._current_mode

    # ==================== 流体动画方法 ====================

    def _initialize_fluid_blobs(self):
        """
        更强调流动感：大面积主团块 + 明显运动的高亮团块。
        坐标和运动均使用归一化值，实际绘制时再映射到窗口尺寸。
        """
        self._fluid_blobs = [
            {
                "base_pos": QPointF(0.16, 0.20),
                "orbit": QPointF(0.14, 0.10),
                "radius": 0.58,
                "scale_x": 1.34,
                "scale_y": 1.06,
                "phase": 0.0,
                "speed": 0.34,
                "opacity": 0.72,
                "color_index": 0,
                "layer": "base",
            },
            {
                "base_pos": QPointF(0.84, 0.24),
                "orbit": QPointF(0.13, 0.11),
                "radius": 0.50,
                "scale_x": 1.20,
                "scale_y": 1.34,
                "phase": 1.1,
                "speed": 0.30,
                "opacity": 0.62,
                "color_index": 1,
                "layer": "base",
            },
            {
                "base_pos": QPointF(0.30, 0.80),
                "orbit": QPointF(0.11, 0.12),
                "radius": 0.53,
                "scale_x": 1.28,
                "scale_y": 1.20,
                "phase": 2.2,
                "speed": 0.28,
                "opacity": 0.56,
                "color_index": 2,
                "layer": "base",
            },
            {
                "base_pos": QPointF(0.78, 0.72),
                "orbit": QPointF(0.14, 0.10),
                "radius": 0.45,
                "scale_x": 1.42,
                "scale_y": 1.10,
                "phase": 3.0,
                "speed": 0.33,
                "opacity": 0.54,
                "color_index": 3,
                "layer": "base",
            },
            {
                "base_pos": QPointF(0.50, 0.46),
                "orbit": QPointF(0.10, 0.10),
                "radius": 0.38,
                "scale_x": 1.10,
                "scale_y": 1.52,
                "phase": 4.1,
                "speed": 0.24,
                "opacity": 0.44,
                "color_index": 4,
                "layer": "base",
            },
            {
                "base_pos": QPointF(0.60, 0.16),
                "orbit": QPointF(0.09, 0.08),
                "radius": 0.28,
                "scale_x": 1.30,
                "scale_y": 0.88,
                "phase": 0.8,
                "speed": 0.42,
                "opacity": 0.42,
                "color_index": 2,
                "layer": "highlight",
            },
            {
                "base_pos": QPointF(0.20, 0.58),
                "orbit": QPointF(0.10, 0.06),
                "radius": 0.26,
                "scale_x": 0.96,
                "scale_y": 1.24,
                "phase": 2.8,
                "speed": 0.40,
                "opacity": 0.38,
                "color_index": 1,
                "layer": "highlight",
            },
            {
                "base_pos": QPointF(0.84, 0.52),
                "orbit": QPointF(0.07, 0.09),
                "radius": 0.22,
                "scale_x": 1.12,
                "scale_y": 1.12,
                "phase": 5.0,
                "speed": 0.48,
                "opacity": 0.34,
                "color_index": 0,
                "layer": "highlight",
            },
        ]

    def _generate_accent_colors(self):
        try:
            from freeassetfilter.core.settings_manager import SettingsManager
            settings = SettingsManager()
            accent_hex = settings.get_setting("appearance.colors.accent_color", "#B036EE")
            accent_color = QColor(accent_hex)
            return [
                self._adjust_color(accent_color, hue_shift=-18, sat_mul=1.08, val_mul=0.88),
                self._adjust_color(accent_color, hue_shift=0, sat_mul=1.10, val_mul=0.95),
                self._adjust_color(accent_color, hue_shift=18, sat_mul=0.96, val_mul=1.08),
                self._adjust_color(accent_color, hue_shift=36, sat_mul=0.85, val_mul=1.15),
                self._adjust_color(accent_color, hue_shift=-32, sat_mul=1.10, val_mul=0.72),
            ]
        except (ImportError, AttributeError, ValueError) as e:
            debug(f"[AudioBackground] 生成强调色主题失败: {e}")
            return [
                QColor(176, 54, 238),
                QColor(205, 82, 246),
                QColor(132, 83, 255),
                QColor(238, 107, 255),
                QColor(86, 42, 176),
            ]

    def _adjust_color(self, color: QColor, hue_shift=0, sat_mul=1.0, val_mul=1.0, alpha=None) -> QColor:
        h, s, v, a = color.getHsv()
        if h < 0:
            h = 280
        h = (h + hue_shift) % 360
        s = max(40, min(255, int(s * sat_mul)))
        v = max(25, min(255, int(v * val_mul)))
        if alpha is not None:
            a = alpha
        return QColor.fromHsv(h, s, v, a)

    def _start_fluid_animation(self):
        if self._animation_timer is None:
            self._animation_timer = QTimer(self)
            self._animation_timer.timeout.connect(self._update_fluid_animation)
            self._animation_timer.start(33)
            self._animation_start_time = time.perf_counter()
        elif not self._animation_timer.isActive():
            self._animation_timer.start(33)

    def _stop_fluid_animation(self):
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer.deleteLater()
            self._animation_timer = None

    def pauseAnimation(self, paused: bool = True):
        self._is_paused = paused
        if self._animation_timer:
            if paused:
                self._animation_timer.stop()
            elif self._is_loaded and self._current_mode == self.MODE_FLUID:
                self._animation_timer.start(33)

    def resumeAnimation(self):
        self.pauseAnimation(False)

    def isAnimationPaused(self) -> bool:
        return self._is_paused

    def _update_fluid_animation(self):
        if self._is_paused or self._current_mode != self.MODE_FLUID:
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        self._request_fluid_repaint()

    def setTheme(self, theme: str):
        if theme not in self._theme_colors:
            return

        previous_colors = self._copy_theme_colors(self._theme_colors.get(self._current_theme))
        self._current_theme = theme
        self._begin_theme_transition(previous_colors)

        if self._is_loaded and self._current_mode == self.MODE_FLUID:
            self._request_fluid_repaint()
        self.themeChanged.emit(theme)

    def getTheme(self) -> str:
        return self._current_theme

    def setAnimationSpeed(self, speed_factor: float):
        self._animation_speed = max(0.1, min(2.0, speed_factor))
        self.speedChanged.emit(self._animation_speed)

    def getAnimationSpeed(self) -> float:
        return self._animation_speed

    def setCustomColors(self, colors: list):
        if not colors or len(colors) < 5:
            return

        previous_colors = self._copy_theme_colors(self._theme_colors.get(self._current_theme))
        colors = colors[:5]
        self._theme_colors['custom'] = [QColor(c.red(), c.green(), c.blue()) for c in colors]
        self._current_theme = 'custom'
        self._has_resolved_cover_colors = True
        self._begin_theme_transition(previous_colors)

        if self._is_loaded and self._current_mode == self.MODE_FLUID:
            self._request_fluid_repaint()

    def useAccentTheme(self):
        previous_colors = self._copy_theme_colors(self._theme_colors.get(self._current_theme))
        self._theme_colors['accent'] = self._generate_accent_colors()
        self._current_theme = 'accent'
        self._has_resolved_cover_colors = False
        self._begin_theme_transition(previous_colors)

        if self._is_loaded and self._current_mode == self.MODE_FLUID:
            self._request_fluid_repaint()

    # ==================== 封面显示方法 ====================

    def _compute_cover_key(self, cover_data: bytes) -> str:
        if not cover_data:
            return ""
        return hashlib.md5(cover_data).hexdigest()

    def _invalidate_blur_scaled_cache(self):
        self._scaled_blur_pixmap_cache = None
        self._scaled_blur_cache_size = (0, 0)
        self._scaled_blur_cache_source_key = None

    def setAudioCover(self, cover_data: bytes = None):
        if self._current_color_task:
            self._current_color_task.cancel()
            self._current_color_task = None

        self._pending_cover_data = cover_data

        if not self._has_visible_cover_content():
            self._apply_audio_cover_content(self._pending_cover_data)
            self._start_cover_fade_in()
            return

        self._start_cover_fade_out()

    def _has_visible_cover_content(self) -> bool:
        has_cover = self._cover_label.pixmap() is not None and not self._cover_label.pixmap().isNull()
        has_svg = self._svg_widget is not None
        return has_cover or has_svg

    def _start_cover_fade_out(self):
        self._cover_fade_anim.stop()
        self._cover_fade_phase = "out"
        self._cover_fade_anim.setDuration(140)
        self._cover_fade_anim.setStartValue(self._cover_opacity_effect.opacity())
        self._cover_fade_anim.setEndValue(0.0)
        self._cover_fade_anim.start()

    def _start_cover_fade_in(self):
        self._cover_fade_anim.stop()
        self._cover_fade_phase = "in"
        self._cover_fade_anim.setDuration(180)
        self._cover_fade_anim.setStartValue(self._cover_opacity_effect.opacity())
        self._cover_fade_anim.setEndValue(1.0)
        self._cover_fade_anim.start()

    def _on_cover_fade_finished(self):
        if self._cover_fade_phase == "out":
            self._apply_audio_cover_content(self._pending_cover_data)
            self._cover_opacity_effect.setOpacity(0.0)
            self._start_cover_fade_in()
            return

        self._cover_fade_phase = None

    def _apply_audio_cover_content(self, cover_data: bytes = None):
        self._cover_data = cover_data
        self._cover_source_key = self._compute_cover_key(cover_data) if cover_data else None
        self._cover_source_image = None

        self._cover_label.hide()
        self._svg_container.hide()

        if self._svg_widget:
            self._svg_widget.hide()
            self._svg_widget.deleteLater()
            self._svg_widget = None

        if cover_data:
            try:
                self._svg_container.hide()

                cached = self._cover_cache.get(cover_data)
                if cached and cached.get('cover_pixmap'):
                    self._cover_pixmap = cached['cover_pixmap']
                    self._cover_label.setPixmap(self._cover_pixmap)
                    self._cover_label.setMinimumSize(self._cover_pixmap.size())
                    self._cover_label.show()
                    self._cover_layout.update()
                    debug("[AudioBackground] 使用缓存的封面图像")

                    if cached.get('colors'):
                        colors = cached['colors']
                        qt_colors = [QColor(r, g, b) for r, g, b in colors]
                        self.setCustomColors(qt_colors)
                        debug("[AudioBackground] 使用内存缓存的颜色主题")
                    else:
                        persisted_colors = self._persistent_color_cache.get_colors(cover_data)
                        if persisted_colors:
                            qt_colors = [QColor(r, g, b) for r, g, b in persisted_colors[:5]]
                            self.setCustomColors(qt_colors)
                            self._cover_cache.put(cover_data, colors=persisted_colors[:5])
                            debug("[AudioBackground] 使用持久化缓存的颜色主题")
                        else:
                            if not self._has_resolved_cover_colors:
                                self.useAccentTheme()
                            self._start_color_extraction(cover_data)

                    self._cover_container.setGeometry(self.rect())
                    self._cover_layout.update()
                    return

                image = Image.open(io.BytesIO(cover_data))
                if image.mode != 'RGBA':
                    image = image.convert('RGBA')

                # 保存一次源图，后续 resize 时直接复用，避免重复解码 bytes
                self._cover_source_image = image.copy()

                display_image = image.copy()
                display_image.thumbnail((self._cover_size, self._cover_size), Image.Resampling.LANCZOS)

                self._cover_pixmap = self._pil_to_pixmap(display_image)
                info(f"[AudioBackground] 已加载音频封面: {display_image.size}")

                self._cover_label.setPixmap(self._cover_pixmap)
                self._cover_label.setMinimumSize(self._cover_pixmap.size())
                self._cover_label.show()
                self._cover_layout.update()

                persisted_colors = self._persistent_color_cache.get_colors(cover_data)
                if persisted_colors:
                    qt_colors = [QColor(r, g, b) for r, g, b in persisted_colors[:5]]
                    self.setCustomColors(qt_colors)
                    debug("[AudioBackground] 使用持久化缓存的颜色主题")
                    self._cover_cache.put(cover_data, cover_pixmap=self._cover_pixmap, colors=persisted_colors[:5])
                else:
                    if not self._has_resolved_cover_colors:
                        self.useAccentTheme()
                    self._cover_cache.put(cover_data, cover_pixmap=self._cover_pixmap)
                    self._start_color_extraction(cover_data)

            except (IOError, ValueError) as e:
                warning(f"[AudioBackground] 加载封面失败: {e}")
                self._cover_pixmap = None
                self._cover_source_image = None
                self._cover_source_key = None
                self._load_default_cover()
                self.useAccentTheme()
        else:
            self._cover_pixmap = None
            self._cover_source_image = None
            self._cover_source_key = None
            self._load_default_cover()
            self.useAccentTheme()

        self._cover_container.setGeometry(self.rect())
        self._cover_layout.update()

    def _start_color_extraction(self, cover_data: bytes):
        self._color_task_id += 1
        task_id = self._color_task_id

        task = ColorExtractionTask(
            task_id=task_id,
            cover_data=cover_data,
            callback=self._on_color_extraction_finished,
            widget_ref=self,
        )
        self._current_color_task = task
        self._thread_pool.start(task)
        debug(f"[AudioBackground] 启动颜色提取任务 #{task_id}")

    def _on_color_extraction_finished(self, task_id: int, colors: list):
        if self._current_color_task is None or task_id != self._current_color_task.task_id:
            debug(f"[AudioBackground] 忽略旧任务 #{task_id} 的结果")
            return

        self._current_color_task = None

        if colors and len(colors) >= 5:
            qt_colors = [QColor(r, g, b) for r, g, b in colors[:5]]
            self.setCustomColors(qt_colors)

            if self._cover_data:
                self._cover_cache.put(self._cover_data, colors=colors[:5])
                self._persistent_color_cache.put_colors(self._cover_data, colors[:5])

            info(f"[AudioBackground] 任务 #{task_id} 完成，已应用提取的颜色主题")
        else:
            if self._has_resolved_cover_colors:
                warning(f"[AudioBackground] 任务 #{task_id} 未能提取足够颜色，保留当前主题")
            else:
                warning(f"[AudioBackground] 任务 #{task_id} 未能提取足够颜色，使用默认主题")
                self.useAccentTheme()

    def _load_default_cover(self):
        try:
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
                warning("[AudioBackground] 未找到音乐SVG图标")
                return

            while self._svg_container_layout.count() > 0:
                item = self._svg_container_layout.takeAt(0)
                if item.widget():
                    item.widget().hide()

            from ..core.svg_renderer import SvgRenderer

            with open(svg_path, 'r', encoding='utf-8') as file:
                svg_content = file.read()

            svg_content = SvgRenderer._replace_svg_colors(svg_content)

            self._svg_widget = QSvgWidget()
            self._svg_widget.load(svg_content.encode('utf-8'))
            self._svg_widget.setStyleSheet("background: transparent; border: none;")

            svg_size = self._svg_widget.renderer().defaultSize()
            aspect_ratio = svg_size.width() / svg_size.height() if svg_size.height() > 0 else 1.0

            if aspect_ratio >= 1:
                widget_width = self._cover_size
                widget_height = int(self._cover_size / aspect_ratio)
            else:
                widget_height = self._cover_size
                widget_width = int(self._cover_size * aspect_ratio)

            self._svg_widget.setFixedSize(widget_width, widget_height)
            self._svg_container_layout.addWidget(self._svg_widget, alignment=Qt.AlignCenter)
            self._svg_container.show()
            self._svg_container_layout.update()
            self._cover_layout.update()

            info(f"[AudioBackground] 已加载默认音乐图标: {svg_path}, 尺寸: {widget_width}x{widget_height}")

        except (IOError, OSError, ValueError) as e:
            warning(f"[AudioBackground] 加载默认图标失败: {e}")

    def _reload_current_cover(self):
        if self._cover_data is None:
            return

        try:
            if self._cover_source_image is None:
                source_image = Image.open(io.BytesIO(self._cover_data))
                if source_image.mode != 'RGBA':
                    source_image = source_image.convert('RGBA')
                self._cover_source_image = source_image

            display_image = self._cover_source_image.copy()
            display_image.thumbnail((self._cover_size, self._cover_size), Image.Resampling.LANCZOS)

            self._cover_pixmap = self._pil_to_pixmap(display_image)
            self._cover_label.setPixmap(self._cover_pixmap)
            self._cover_label.setMinimumSize(self._cover_pixmap.size())
            self._cover_layout.update()

            debug(f"[AudioBackground] 封面已重新调整尺寸: {display_image.size}")

        except (IOError, ValueError) as e:
            warning(f"[AudioBackground] 重新加载封面失败: {e}")

    def _reload_current_svg(self):
        if self._svg_widget is None:
            return

        try:
            svg_size = self._svg_widget.renderer().defaultSize()
            aspect_ratio = svg_size.width() / svg_size.height() if svg_size.height() > 0 else 1.0

            if aspect_ratio >= 1:
                widget_width = self._cover_size
                widget_height = int(self._cover_size / aspect_ratio)
            else:
                widget_height = self._cover_size
                widget_width = int(self._cover_size * aspect_ratio)

            self._svg_widget.setFixedSize(widget_width, widget_height)
            self._svg_container_layout.update()

            debug(f"[AudioBackground] SVG图标已重新调整尺寸: {widget_width}x{widget_height}")

        except (AttributeError, ValueError) as e:
            warning(f"[AudioBackground] 重新调整SVG尺寸失败: {e}")

    # ==================== 封面模糊方法 ====================

    def setCoverData(self, cover_data: bytes):
        self._cover_data = cover_data

        if self._is_loaded and self._current_mode == self.MODE_COVER_BLUR:
            self._process_cover()
            self.update()

    def _process_cover(self):
        if not self._cover_data:
            self._blurred_pixmap = None
            self._blurred_pixmap_key = None
            self._invalidate_blur_scaled_cache()
            self.update()
            return

        cover_key = self._compute_cover_key(self._cover_data)

        cached = self._cover_cache.get(self._cover_data)
        if cached and cached.get('blurred_pixmap'):
            self._blurred_pixmap = cached['blurred_pixmap']
            self._blurred_pixmap_key = cover_key
            self._invalidate_blur_scaled_cache()
            self.update()
            return

        try:
            image = Image.open(io.BytesIO(self._cover_data))
            if image.mode != 'RGB':
                image = image.convert('RGB')

            target_width = 1920
            target_height = 1080

            img_width, img_height = image.size
            scale = max(target_width / img_width, target_height / img_height)
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)

            image_resized = image.resize((new_width, new_height), Image.Resampling.BILINEAR)

            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            right = left + target_width
            bottom = top + target_height
            image_cropped = image_resized.crop((left, top, right, bottom))

            image_blurred = image_cropped.filter(ImageFilter.GaussianBlur(radius=15))
            self._blurred_pixmap = self._pil_to_pixmap(image_blurred)
            self._blurred_pixmap_key = cover_key
            self._invalidate_blur_scaled_cache()

            self._cover_cache.put(self._cover_data, blurred_pixmap=self._blurred_pixmap)

        except (IOError, ValueError) as e:
            warning(f"[AudioBackground] 处理封面失败: {e}")
            self._blurred_pixmap = None
            self._blurred_pixmap_key = None
            self._invalidate_blur_scaled_cache()

    def _pil_to_pixmap(self, pil_image) -> QPixmap:
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')

        data = pil_image.tobytes('raw', 'RGBA')
        qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
        return QPixmap.fromImage(qimage)

    def _calculate_scaled_rect(self) -> QRect:
        if not self._blurred_pixmap:
            return self.rect()

        widget_width = self.width()
        widget_height = self.height()
        pixmap_width = self._blurred_pixmap.width()
        pixmap_height = self._blurred_pixmap.height()

        if widget_width <= 0 or widget_height <= 0 or pixmap_width <= 0 or pixmap_height <= 0:
            return self.rect()

        scale_x = widget_width / pixmap_width
        scale_y = widget_height / pixmap_height
        scale = max(scale_x, scale_y)

        new_width = int(pixmap_width * scale)
        new_height = int(pixmap_height * scale)

        x = (widget_width - new_width) // 2
        y = (widget_height - new_height) // 2

        return QRect(x, y, new_width, new_height)

    def _get_scaled_blur_pixmap(self, width: int, height: int):
        if (
            self._blurred_pixmap is None
            or self._blurred_pixmap.isNull()
            or width <= 0
            or height <= 0
        ):
            return None

        cache_size = (width, height)
        cache_source_key = self._blurred_pixmap_key

        if (
            self._scaled_blur_pixmap_cache is not None
            and self._scaled_blur_cache_size == cache_size
            and self._scaled_blur_cache_source_key == cache_source_key
            and not self._scaled_blur_pixmap_cache.isNull()
        ):
            return self._scaled_blur_pixmap_cache

        scaled = self._blurred_pixmap.scaled(
            width,
            height,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )

        self._scaled_blur_pixmap_cache = scaled
        self._scaled_blur_cache_size = cache_size
        self._scaled_blur_cache_source_key = cache_source_key
        return scaled

    def _get_or_create_fluid_buffer(self, render_width: int, render_height: int):
        if (
            self._fluid_buffer is None
            or self._fluid_buffer_size != (render_width, render_height)
        ):
            self._fluid_buffer = QImage(render_width, render_height, QImage.Format_ARGB32_Premultiplied)
            self._fluid_buffer_size = (render_width, render_height)

        self._fluid_buffer.fill(Qt.transparent)
        return self._fluid_buffer

    # ==================== 绘制方法 ====================

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_loaded and self._cover_container.isVisible():
            self._cover_container.setGeometry(self.rect())
            self._update_cover_size()

        if self._fluid_gl_layer:
            self._fluid_gl_layer.setGeometry(self.rect())
            self._fluid_gl_layer.lower()
            self._cover_container.raise_()

        self._invalidate_blur_scaled_cache()
        self.update()

    def _update_cover_size(self):
        if not self._is_loaded:
            return

        available_width = self.width()
        available_height = self.height() - 100

        current_size = self._cover_size
        if current_size <= available_width and current_size <= available_height:
            if current_size < self._max_cover_size:
                new_size = min(self._max_cover_size, int(min(available_width, available_height)))
                if new_size > current_size:
                    self._cover_size = new_size
                    if self._cover_pixmap is not None:
                        self._reload_current_cover()
                    elif self._svg_widget is not None:
                        self._reload_current_svg()
            return

        max_size = min(available_width, available_height)
        new_size = max(self._min_cover_size, min(self._max_cover_size, int(max_size)))

        if new_size != self._cover_size:
            self._cover_size = new_size
            if self._cover_pixmap is not None:
                self._reload_current_cover()
            elif self._svg_widget is not None:
                self._reload_current_svg()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._current_mode == self.MODE_FLUID and self._is_loaded:
            self.pauseAnimation(True)
            debug("[AudioBackground] 窗口隐藏，暂停动画")

    def showEvent(self, event):
        super().showEvent(event)
        if self._current_mode == self.MODE_FLUID and self._is_loaded:
            self.resumeAnimation()
            debug("[AudioBackground] 窗口显示，恢复动画")

    def paintEvent(self, event):
        if not self._is_loaded or not self.isVisible():
            return

        # GPU 路径下流体由 QOpenGLWidget 子控件绘制，父控件无需重复绘制
        if (
            self._current_mode == self.MODE_FLUID
            and self._gpu_fluid_enabled
            and self._fluid_gl_layer
            and self._fluid_gl_layer.isVisible()
        ):
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
        colors = self._theme_colors.get(self._current_theme, self._theme_colors['sunset'])
        if len(colors) < 5:
            colors = self._theme_colors['sunset']

        progress = 1.0
        previous_colors = self._theme_transition_previous_colors
        if previous_colors:
            elapsed = time.perf_counter() - self._theme_transition_start_time
            progress = max(0.0, min(1.0, elapsed / self._theme_transition_duration))
            if progress >= 1.0:
                self._theme_transition_previous_colors = None
                previous_colors = None

        if previous_colors:
            self._paint_fluid_layer(painter, width, height, previous_colors, 1.0 - progress)

        self._paint_fluid_layer(painter, width, height, colors, progress)

    def _paint_fluid_layer(self, painter: QPainter, width: int, height: int, colors: list, opacity_scale: float):
        if opacity_scale <= 0.0:
            return

        painter.save()
        painter.setOpacity(opacity_scale)

        top_base = self._mix_colors(colors[3], QColor(72, 56, 102), 0.22)
        mid_base = self._mix_colors(colors[0], QColor(60, 54, 92), 0.26)
        bottom_base = self._mix_colors(colors[1], QColor(54, 56, 88), 0.28)

        background = QLinearGradient(0, 0, width, height)
        background.setColorAt(0.0, self._with_alpha(top_base, 255))
        background.setColorAt(0.45, self._with_alpha(mid_base, 255))
        background.setColorAt(1.0, self._with_alpha(bottom_base, 255))
        painter.fillRect(0, 0, width, height, background)

        render_width = max(128, int(width * self._fluid_render_scale))
        render_height = max(128, int(height * self._fluid_render_scale))
        scale_to_buffer_x = render_width / max(1, width)
        scale_to_buffer_y = render_height / max(1, height)
        radius_scale = max(scale_to_buffer_x, scale_to_buffer_y)

        fluid_buffer = self._get_or_create_fluid_buffer(render_width, render_height)

        buffer_painter = QPainter(fluid_buffer)
        buffer_painter.setRenderHint(QPainter.Antialiasing, True)
        buffer_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        buffer_painter.setCompositionMode(QPainter.CompositionMode_Screen)

        t = (time.perf_counter() - self._animation_start_time) * self._animation_speed

        blob_states = []
        for blob in self._fluid_blobs:
            color = colors[blob["color_index"] % len(colors)]
            center_x, center_y, radius, scale_x, scale_y, alpha = self._compute_blob_state(
                blob, t, width, height
            )
            blob_states.append((blob, color, center_x, center_y, radius, scale_x, scale_y, alpha))

            softness = self._fluid_blob_softness + (0.18 if blob["layer"] == "highlight" else 0.0)
            blend_alpha = 0.98 if blob["layer"] == "highlight" else 0.92
            self._draw_soft_blob(
                buffer_painter,
                center_x * scale_to_buffer_x,
                center_y * scale_to_buffer_y,
                radius * radius_scale,
                scale_x,
                scale_y,
                self._tint_blob_color(color, blob["layer"]),
                min(1.0, alpha * blend_alpha),
                softness=softness,
            )

        buffer_painter.end()

        painter.drawImage(QRect(0, 0, width, height), fluid_buffer)

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Screen)
        for blob, color, center_x, center_y, radius, scale_x, scale_y, alpha in blob_states:
            if blob["layer"] == "highlight":
                definition_color = self._adjust_color(color, sat_mul=1.00, val_mul=1.24)
                definition_radius = radius * 0.76
                definition_alpha = min(1.0, alpha * 0.46)
            else:
                definition_color = self._adjust_color(color, sat_mul=1.08, val_mul=1.10)
                definition_radius = radius * 0.68
                definition_alpha = min(1.0, alpha * 0.30)

            self._draw_blob_definition(
                painter,
                center_x,
                center_y,
                definition_radius,
                scale_x,
                scale_y,
                definition_color,
                definition_alpha,
            )
        painter.restore()

        self._paint_global_haze(painter, width, height, colors)
        painter.restore()

    def _compute_blob_state(self, blob: dict, t: float, width: int, height: int):
        base_pos = blob["base_pos"]
        orbit = blob["orbit"]
        phase = blob["phase"]
        speed = blob["speed"]

        x = (
            base_pos.x()
            + math.sin(t * speed + phase) * orbit.x()
            + math.cos(t * speed * 0.57 + phase * 1.3) * 0.035
            + math.sin(t * speed * 1.22 + phase * 0.5) * 0.020
        )
        y = (
            base_pos.y()
            + math.cos(t * speed * 0.92 + phase * 1.3) * orbit.y()
            + math.sin(t * speed * 0.52 + phase * 0.7) * 0.028
            + math.cos(t * speed * 1.08 + phase * 1.1) * 0.016
        )

        pulse = 1.0 + math.sin(t * speed * 1.35 + phase) * 0.18 + math.cos(t * speed * 0.64 + phase) * 0.08
        stretch = 1.0 + math.sin(t * speed * 0.96 + phase * 1.7) * 0.18
        squish = 1.0 + math.cos(t * speed * 0.88 + phase * 0.9) * 0.14

        radius = max(width, height) * blob["radius"] * pulse
        scale_x = blob["scale_x"] * stretch
        scale_y = blob["scale_y"] * squish

        alpha = blob["opacity"] * (0.88 + 0.16 * math.sin(t * speed * 1.05 + phase * 1.2))

        center_x = x * width
        center_y = y * height
        return center_x, center_y, radius, scale_x, scale_y, alpha

    def _draw_soft_blob(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
        scale_x: float,
        scale_y: float,
        color: QColor,
        opacity: float,
        softness: float = 1.42,
    ):
        rx = radius * scale_x
        ry = radius * scale_y
        outer_radius = max(rx, ry) * max(1.0, softness)

        gradient = QRadialGradient(0, 0, outer_radius)
        gradient.setColorAt(0.00, self._with_alpha(self._adjust_color(color, sat_mul=1.10, val_mul=1.12), int(255 * opacity)))
        gradient.setColorAt(0.16, self._with_alpha(self._adjust_color(color, sat_mul=1.05, val_mul=1.10), int(236 * opacity)))
        gradient.setColorAt(0.34, self._with_alpha(color, int(182 * opacity)))
        gradient.setColorAt(0.58, self._with_alpha(self._adjust_color(color, sat_mul=0.96, val_mul=1.03), int(92 * opacity)))
        gradient.setColorAt(0.82, self._with_alpha(self._adjust_color(color, sat_mul=0.90, val_mul=1.00), int(22 * opacity)))
        gradient.setColorAt(1.00, QColor(0, 0, 0, 0))

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.translate(center_x, center_y)

        if outer_radius > 0:
            painter.scale(rx / outer_radius, ry / outer_radius)

        painter.fillRect(
            QRectF(-outer_radius, -outer_radius, outer_radius * 2, outer_radius * 2),
            QBrush(gradient),
        )
        painter.restore()

    def _draw_blob_definition(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        radius: float,
        scale_x: float,
        scale_y: float,
        color: QColor,
        opacity: float,
    ):
        rx = radius * scale_x
        ry = radius * scale_y
        outer_radius = max(rx, ry)

        gradient = QRadialGradient(0, 0, outer_radius)
        gradient.setColorAt(0.00, self._with_alpha(self._adjust_color(color, sat_mul=1.04, val_mul=1.18), int(190 * opacity)))
        gradient.setColorAt(0.18, self._with_alpha(self._adjust_color(color, sat_mul=1.02, val_mul=1.10), int(124 * opacity)))
        gradient.setColorAt(0.38, self._with_alpha(color, int(62 * opacity)))
        gradient.setColorAt(0.58, self._with_alpha(self._adjust_color(color, sat_mul=0.96, val_mul=1.02), int(18 * opacity)))
        gradient.setColorAt(1.00, QColor(0, 0, 0, 0))

        painter.save()
        painter.setPen(Qt.NoPen)
        painter.translate(center_x, center_y)

        if outer_radius > 0:
            painter.scale(rx / outer_radius, ry / outer_radius)

        painter.fillRect(
            QRectF(-outer_radius, -outer_radius, outer_radius * 2, outer_radius * 2),
            QBrush(gradient),
        )
        painter.restore()

    def _paint_global_haze(self, painter: QPainter, width: int, height: int, colors: list):
        vertical_wash = QLinearGradient(0, 0, 0, height)
        vertical_wash.setColorAt(0.0, self._with_alpha(self._adjust_color(colors[3], sat_mul=0.90, val_mul=1.10), 8))
        vertical_wash.setColorAt(0.50, QColor(255, 255, 255, 0))
        vertical_wash.setColorAt(1.0, self._with_alpha(self._adjust_color(colors[1], sat_mul=0.92, val_mul=1.06), 6))
        painter.fillRect(0, 0, width, height, vertical_wash)

        horizontal_wash = QLinearGradient(0, 0, width, 0)
        horizontal_wash.setColorAt(0.0, self._with_alpha(self._adjust_color(colors[0], sat_mul=0.88, val_mul=1.10), 8))
        horizontal_wash.setColorAt(0.18, QColor(255, 255, 255, 0))
        horizontal_wash.setColorAt(0.82, QColor(255, 255, 255, 0))
        horizontal_wash.setColorAt(1.0, self._with_alpha(self._adjust_color(colors[2], sat_mul=0.88, val_mul=1.08), 8))
        painter.fillRect(0, 0, width, height, horizontal_wash)

        center_lift = QRadialGradient(width * 0.50, height * 0.50, max(width, height) * 0.92)
        center_lift.setColorAt(0.0, self._with_alpha(self._adjust_color(colors[4], sat_mul=0.82, val_mul=1.16), 18))
        center_lift.setColorAt(0.58, self._with_alpha(self._adjust_color(colors[0], sat_mul=0.84, val_mul=1.10), 8))
        center_lift.setColorAt(1.0, self._with_alpha(self._adjust_color(colors[1], sat_mul=0.86, val_mul=1.06), 4))
        painter.fillRect(0, 0, width, height, center_lift)

    def _begin_theme_transition(self, previous_colors):
        if not previous_colors or not self._is_loaded or self._current_mode != self.MODE_FLUID:
            self._theme_transition_previous_colors = None
            return

        self._theme_transition_previous_colors = [QColor(c) for c in previous_colors[:5]]
        self._theme_transition_start_time = time.perf_counter()

    def _copy_theme_colors(self, colors):
        if not colors:
            return None
        return [QColor(c) for c in colors[:5]]

    def _tint_blob_color(self, color: QColor, layer: str) -> QColor:
        if layer == "highlight":
            return self._adjust_color(color, sat_mul=0.92, val_mul=1.18)
        return self._adjust_color(color, sat_mul=1.04, val_mul=0.98)

    def _mix_colors(self, color_a: QColor, color_b: QColor, factor: float) -> QColor:
        factor = max(0.0, min(1.0, factor))
        inv = 1.0 - factor
        return QColor(
            int(color_a.red() * inv + color_b.red() * factor),
            int(color_a.green() * inv + color_b.green() * factor),
            int(color_a.blue() * inv + color_b.blue() * factor),
        )

    def _with_alpha(self, color: QColor, alpha: int) -> QColor:
        result = QColor(color)
        result.setAlpha(max(0, min(255, alpha)))
        return result

    def _paint_cover_blur_background(self, painter: QPainter, width: int, height: int):
        painter.fillRect(0, 0, width, height, QColor("#000000"))

        scaled_pixmap = self._get_scaled_blur_pixmap(width, height)
        if scaled_pixmap and not scaled_pixmap.isNull():
            draw_x = (width - scaled_pixmap.width()) // 2
            draw_y = (height - scaled_pixmap.height()) // 2
            painter.setOpacity(1.0)
            painter.drawPixmap(draw_x, draw_y, scaled_pixmap)

    def clear(self):
        self._cover_data = None
        self._blurred_pixmap = None
        self._blurred_pixmap_key = None
        self._cover_pixmap = None
        self._cover_source_image = None
        self._cover_source_key = None
        self._fluid_buffer = None
        self._fluid_buffer_size = (0, 0)
        self._invalidate_blur_scaled_cache()
        self._hide_fluid_gl_layer()
        self.update()