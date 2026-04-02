#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；
2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

缩略图生成管理模块
统一处理文件选择器和文件储存池的缩略图生成需求
"""

import os
import sys
import subprocess
import hashlib
import json
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Optional, Tuple, Callable, Dict, Set, List
from pathlib import Path
from dataclasses import dataclass
from freeassetfilter.core.media_probe import get_ffmpeg_path, get_ffprobe_path
from freeassetfilter.core.rust_thumbnail_bridge import RustThumbnailBridge

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.utils.path_utils import get_app_data_path

# 尝试导入PIL库
PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    warning("PIL库未安装，缩略图功能将受限")

@dataclass
class FrameCacheEntry:
    """帧缓存条目"""
    frame: any  # numpy array
    timestamp: float
    position: int
    estimated_bytes: int = 0


@dataclass
class VideoFrameCache:
    """视频帧缓存管理器"""
    max_entries: int = 5
    max_bytes: int = 32 * 1024 * 1024
    cache: Dict[int, FrameCacheEntry] = None
    last_accessed: float = 0
    current_bytes: int = 0
    
    def __post_init__(self):
        if self.cache is None:
            self.cache = {}
        self.last_accessed = time.time()

    def _estimate_frame_bytes(self, frame) -> int:
        """估算帧占用字节数"""
        if frame is None:
            return 0
        try:
            if hasattr(frame, 'nbytes'):
                return int(frame.nbytes)
            if hasattr(frame, 'itemsize') and hasattr(frame, 'size'):
                return int(frame.itemsize * frame.size)
            if hasattr(frame, '__len__'):
                return int(len(frame))
        except Exception:
            pass
        return 0

    def _evict_oldest(self):
        """移除最旧条目"""
        if not self.cache:
            return
        oldest_pos = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
        oldest_entry = self.cache.pop(oldest_pos)
        self.current_bytes = max(0, self.current_bytes - int(oldest_entry.estimated_bytes or 0))
        if oldest_entry.frame is not None:
            oldest_entry.frame = None
    
    def get(self, position: int) -> Optional:
        """获取缓存的帧"""
        self.last_accessed = time.time()
        if position in self.cache:
            self.cache[position].timestamp = time.time()
            return self.cache[position].frame
        return None
    
    def put(self, position: int, frame):
        """缓存帧"""
        self.last_accessed = time.time()
        if position in self.cache:
            old_entry = self.cache.pop(position)
            self.current_bytes = max(0, self.current_bytes - int(old_entry.estimated_bytes or 0))
            if old_entry.frame is not None:
                old_entry.frame = None

        estimated_bytes = self._estimate_frame_bytes(frame)
        self.cache[position] = FrameCacheEntry(
            frame=frame,
            timestamp=time.time(),
            position=position,
            estimated_bytes=estimated_bytes
        )
        self.current_bytes += estimated_bytes

        while len(self.cache) > self.max_entries or self.current_bytes > self.max_bytes:
            self._evict_oldest()
    
    def clear(self):
        """清空缓存，显式释放帧数据"""
        for entry in self.cache.values():
            if entry.frame is not None:
                entry.frame = None
        self.cache.clear()
        self.current_bytes = 0


class ThumbnailManager:
    """
    缩略图管理器
    统一管理缩略图的生成、缓存和清理
    """
    
    # 支持的图片格式
    IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg', '.avif', '.heic']
    # 支持的RAW格式
    RAW_FORMATS = ['.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf']
    # 支持的PSD格式
    PSD_FORMATS = ['.psd', '.psb']
    # 支持的视频格式
    VIDEO_FORMATS = ['.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.mxf']
    
    # 缩略图基础尺寸
    BASE_SIZE = 128
    
    # 缩略图质量
    QUALITY = 85

    # Rust 原生批量生成配置
    NATIVE_BATCH_SIZE_IMAGE = 16
    NATIVE_BATCH_SIZE_VIDEO = 6
    NATIVE_BATCH_WORKERS_IMAGE = 3
    NATIVE_BATCH_WORKERS_VIDEO = 2

    # 缩略图缓存格式（优先 JPG，兼容历史 PNG）
    THUMB_EXT_PRIMARY = '.jpg'
    THUMB_EXT_LEGACY = '.png'
    
    # 视频帧读取最大重试次数
    MAX_FRAME_READ_RETRIES = 3
    
    # 视频帧缓存过期时间（秒）
    FRAME_CACHE_EXPIRY = 60
    
    # 视频处理超时时间（秒）
    VIDEO_PROCESSING_TIMEOUT = 30
    BATCH_VIDEO_SUBPROCESS_TIMEOUT = 45
    FFPROBE_TIMEOUT = 8
    FFMPEG_SOFT_TIMEOUT = 12

    # 缩略图磁盘缓存限制
    MAX_THUMB_CACHE_SIZE = 500 * 1024 * 1024  # 500MB
    MAX_THUMB_CACHE_FILES = 10000
    THUMB_CACHE_TARGET_SIZE = int(MAX_THUMB_CACHE_SIZE * 0.8)
    THUMB_CACHE_TARGET_FILES = int(MAX_THUMB_CACHE_FILES * 0.8)

    # 视频帧缓存全局限制
    MAX_FRAME_CACHE_GROUPS = 128
    MAX_FRAME_CACHE_BYTES = 256 * 1024 * 1024
    MAX_FRAME_CACHE_BYTES_PER_GROUP = 32 * 1024 * 1024

    # SVG 渲染缓存限制
    MAX_SVG_CACHE_ENTRIES = 64
    
    # 最大图像尺寸限制（防止内存溢出）
    MAX_IMAGE_DIMENSION = 8192
    MAX_IMAGE_PIXELS = MAX_IMAGE_DIMENSION * MAX_IMAGE_DIMENSION
    
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, dpi_scale: float = 1.0):
        """
        初始化缩略图管理器
        
        Args:
            dpi_scale: DPI缩放因子，默认为1.0
        """
        if ThumbnailManager._initialized:
            # 更新DPI缩放因子
            self.dpi_scale = dpi_scale
            return
        
        ThumbnailManager._initialized = True
        self.dpi_scale = dpi_scale
        
        # 缩略图缓存目录
        self._thumb_dir = os.path.join(get_app_data_path(), 'thumbnails')
        os.makedirs(self._thumb_dir, exist_ok=True)
        
        # 视频帧缓存：文件路径 -> VideoFrameCache
        self._frame_caches: Dict[str, VideoFrameCache] = {}
        self._frame_cache_lock = threading.Lock()

        # Rust 原生缩略图引擎（统一承担高性能生成、调度与缓存）
        self._rust_bridge = RustThumbnailBridge()
        self._native_cache_limit = 200 * 1024 * 1024
        if self._rust_bridge.available:
            self._rust_bridge.set_cache_limit(self._native_cache_limit)

        # SVG 渲染缓存：(file_path, mtime) -> PIL.Image
        self._svg_render_cache: Dict[Tuple[str, float], Image.Image] = {}
        self._svg_cache_access_order: deque = deque()
        self._svg_cache_lock = threading.Lock()
        
        # 正在处理的视频文件集合（用于请求去重）
        self._processing_videos: Set[str] = set()
        self._processing_lock = threading.Lock()
        
        # 进程内直连视频解码限流：
        # 批量模式下的视频任务已经通过“1条硬解队列 + 2条软解队列 + 子进程隔离”调度，
        # 这里仅限制非批量直连路径，避免同一进程内过多软解任务争抢资源。
        self._video_semaphore = threading.Semaphore(1)
        
        debug(f"[ThumbnailManager] 初始化完成，缩略图目录: {self._thumb_dir}")
    
    def set_dpi_scale(self, dpi_scale: float):
        """
        设置DPI缩放因子
        
        Args:
            dpi_scale: DPI缩放因子
        """
        self.dpi_scale = dpi_scale
    
    def get_thumbnail_dir(self) -> str:
        """
        获取缩略图缓存目录路径
        
        Returns:
            str: 缩略图目录路径
        """
        return self._thumb_dir
    
    def _get_thumbnail_hash(self, file_path: str) -> str:
        """
        获取文件路径对应的缩略图哈希名
        """
        md5_hash = hashlib.md5(file_path.encode('utf-8'))
        return md5_hash.hexdigest()[:16]

    def get_thumbnail_path(self, file_path: str) -> str:
        """
        获取文件的主缩略图路径（优先格式）
        
        Args:
            file_path: 原始文件路径
            
        Returns:
            str: 缩略图文件路径
        """
        file_hash = self._get_thumbnail_hash(file_path)
        return os.path.join(self._thumb_dir, f"{file_hash}{self.THUMB_EXT_PRIMARY}")

    def get_legacy_thumbnail_path(self, file_path: str) -> str:
        """
        获取历史 PNG 缩略图路径（兼容旧缓存）
        """
        file_hash = self._get_thumbnail_hash(file_path)
        return os.path.join(self._thumb_dir, f"{file_hash}{self.THUMB_EXT_LEGACY}")

    def get_existing_thumbnail_path(self, file_path: str) -> Optional[str]:
        """
        获取当前实际存在的缩略图路径。
        优先返回主格式 JPG；若不存在则回退到历史/兼容 PNG。
        """
        thumbnail_path = self.get_thumbnail_path(file_path)
        if os.path.exists(thumbnail_path):
            return thumbnail_path

        legacy_path = self.get_legacy_thumbnail_path(file_path)
        if os.path.exists(legacy_path):
            return legacy_path

        return None
    
    def has_thumbnail(self, file_path: str) -> bool:
        """
        检查文件是否已有缩略图
        
        Args:
            file_path: 原始文件路径
            
        Returns:
            bool: 是否存在缩略图
        """
        return self.get_existing_thumbnail_path(file_path) is not None

    def _update_file_access_time(self, file_path: str):
        """
        更新文件访问时间（LRU语义）
        """
        try:
            now = time.time()
            os.utime(file_path, (now, now))
        except Exception:
            pass
    
    def is_media_file(self, file_path: str) -> bool:
        """
        判断文件是否为媒体文件（图片或视频）
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为媒体文件
        """
        suffix = os.path.splitext(file_path)[1].lower()
        return (
            suffix in self.IMAGE_FORMATS
            or suffix in self.RAW_FORMATS
            or suffix in self.PSD_FORMATS
            or suffix in self.VIDEO_FORMATS
        )
    
    def is_image_file(self, file_path: str) -> bool:
        """
        判断文件是否为图片文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为图片文件
        """
        suffix = os.path.splitext(file_path)[1].lower()
        return suffix in self.IMAGE_FORMATS or suffix in self.RAW_FORMATS or suffix in self.PSD_FORMATS
    
    def is_video_file(self, file_path: str) -> bool:
        """
        判断文件是否为视频文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为视频文件
        """
        suffix = os.path.splitext(file_path)[1].lower()
        return suffix in self.VIDEO_FORMATS
    
    def _check_image_size_limit(self, img: Image.Image) -> bool:
        """
        检查图像尺寸是否在限制范围内
        
        Args:
            img: PIL Image对象
            
        Returns:
            bool: 是否在限制范围内
        """
        width, height = img.size
        if width > self.MAX_IMAGE_DIMENSION or height > self.MAX_IMAGE_DIMENSION:
            warning(f"[ThumbnailManager] 图像尺寸超出限制: {width}x{height} > {self.MAX_IMAGE_DIMENSION}x{self.MAX_IMAGE_DIMENSION}")
            return False
        if width * height > self.MAX_IMAGE_PIXELS:
            warning(f"[ThumbnailManager] 图像像素数超出限制: {width * height} > {self.MAX_IMAGE_PIXELS}")
            return False
        return True
    
    def _check_and_enforce_limits_before_create(self):
        """
        在创建新缩略图前检查并强制执行缓存限制

        同时按照总大小与文件数量双阈值控制缓存目录，
        一旦超过任一限制，则按最近最少访问（LRU）清理到安全水位。
        """
        try:
            import glob

            if not os.path.exists(self._thumb_dir):
                return

            thumbnail_files = glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_PRIMARY}"))
            thumbnail_files.extend(glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_LEGACY}")))

            total_size = 0
            file_info_list = []

            for file_path in thumbnail_files:
                try:
                    stat = os.stat(file_path)
                    file_info_list.append((file_path, stat.st_atime, stat.st_size))
                    total_size += stat.st_size
                except (OSError, IOError):
                    continue

            current_file_count = len(file_info_list)
            if (
                total_size < self.MAX_THUMB_CACHE_SIZE
                and current_file_count < self.MAX_THUMB_CACHE_FILES
            ):
                return

            file_info_list.sort(key=lambda x: x[1])

            deleted_count = 0
            remaining_size = total_size
            remaining_count = current_file_count

            for file_path, _, file_size in file_info_list:
                if (
                    remaining_size <= self.THUMB_CACHE_TARGET_SIZE
                    and remaining_count <= self.THUMB_CACHE_TARGET_FILES
                ):
                    break

                try:
                    os.remove(file_path)
                    deleted_count += 1
                    remaining_size -= file_size
                    remaining_count -= 1
                except (OSError, IOError) as e:
                    debug(f"[ThumbnailManager] 删除缓存文件失败 {file_path}: {e}")

            if deleted_count > 0:
                debug(
                    "[ThumbnailManager] 缓存限制检查："
                    f"已清理 {deleted_count} 个旧缩略图，"
                    f"剩余 {max(remaining_count, 0)} 个文件 / {max(remaining_size, 0)} 字节"
                )

        except Exception as e:
            warning(f"[ThumbnailManager] 检查缓存限制时出错: {e}")
    
    def create_thumbnail(self, file_path: str, force_regenerate: bool = False) -> Optional[str]:
        """
        为文件创建缩略图

        Args:
            file_path: 文件路径
            force_regenerate: 是否强制重新生成，即使缩略图已存在

        Returns:
            Optional[str]: 缩略图路径，生成失败返回None
        """
        if not os.path.exists(file_path):
            warning(f"[ThumbnailManager] 文件不存在: {file_path}")
            return None

        thumbnail_path = self.get_thumbnail_path(file_path)
        legacy_thumbnail_path = self.get_legacy_thumbnail_path(file_path)

        # 如果缩略图已存在且不强制重新生成，优先返回 JPG，其次兼容历史 PNG
        if not force_regenerate:
            if os.path.exists(thumbnail_path):
                self._update_file_access_time(thumbnail_path)
                return thumbnail_path
            if os.path.exists(legacy_thumbnail_path):
                self._update_file_access_time(legacy_thumbnail_path)
                return legacy_thumbnail_path

        # 检查是否为媒体文件
        if not self.is_media_file(file_path):
            return None

        # 在创建新缩略图前检查缓存限制
        self._check_and_enforce_limits_before_create()

        # 生成缩略图
        try:
            suffix = os.path.splitext(file_path)[1].lower()
            use_python_dedicated = (
                suffix in self.RAW_FORMATS
                or suffix in self.PSD_FORMATS
                or suffix == '.svg'
            )

            # 优先使用 Rust 原生引擎（RAW/PSD/SVG 保留 Python 专用链路）
            result = None
            if not use_python_dedicated:
                result = self._create_native_thumbnail(file_path, thumbnail_path, legacy_thumbnail_path)

            # 回退到 Python 实现
            if result is None:
                if self.is_image_file(file_path):
                    result = self._create_image_thumbnail(file_path, thumbnail_path)
                elif self.is_video_file(file_path):
                    result = self._create_video_thumbnail(file_path, thumbnail_path)
                else:
                    result = None

            # 如果成功生成，更新访问时间
            if result and os.path.exists(result):
                self._update_file_access_time(result)

            return result
        except Exception as e:
            error(f"[ThumbnailManager] 生成缩略图失败: {file_path}, 错误: {e}")

        return None

    def create_thumbnails_batch(
        self,
        files_to_generate: List[Dict],
        progress_callback: Optional[Callable[[int, int, Dict, bool], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[int, int]:
        """
        批量创建缩略图（异步多队列 + 原生批处理版）

        调度目标：
        1. 原生图片/视频优先走 Rust 批量接口，减少 Python<->Rust 往返与进程调度开销；
        2. Python 专用链路（RAW/PSD/SVG / OpenCV回退）保持单项异步；
        3. 进度仍按“单文件完成”逐项回调，兼顾 UI 感知；
        4. 支持取消，取消后不再补位，但已提交批次允许自然完成。
        """
        total_count = len(files_to_generate)
        if total_count == 0:
            return 0, 0

        success_count = 0
        processed_count = 0

        native_stats_enabled = self._rust_bridge.available
        if native_stats_enabled:
            self._rust_bridge.reset_decode_stats()

        queue_limits = {
            "native_image": max(1, min(self.NATIVE_BATCH_WORKERS_IMAGE, max(1, (os.cpu_count() or 4) // 2))),
            # 视频任务改为 1 条原生队列（硬解优先）+ 2 条 FFmpeg 软解 worker。
            "native_video": 1,
            "python_image": max(1, min(2, (os.cpu_count() or 4) // 2 or 1)),
            "python_video": 2,
        }
        queue_batch_sizes = {
            "native_image": max(4, self.NATIVE_BATCH_SIZE_IMAGE),
            # 视频任务保持单文件粒度，确保单个坏文件可被独立超时并跳过。
            "native_video": 1,
            "python_image": 1,
            "python_video": 1,
        }
        queue_order = ["native_video", "python_video", "python_image", "native_image"]

        task_queues = {
            "native_image": deque(),
            "native_video": deque(),
            "python_image": deque(),
            "python_video": deque(),
        }
        queue_active_counts = {name: 0 for name in task_queues}
        queue_avg_duration = {
            "native_image": 0.35,
            "native_video": 1.8,
            "python_image": 0.35,
            "python_video": 2.0,
        }

        def _run_single_task(queue_name: str, item: Dict) -> Tuple[str, List[Tuple[Dict, bool, Optional[str]]], float]:
            start_time = time.perf_counter()
            file_path = item["file_path"]
            thumbnail_path = item["thumbnail_path"]
            legacy_thumbnail_path = item["legacy_thumbnail_path"]

            result_path = None
            success = False

            try:
                if queue_name == "native_image":
                    result_path = self._create_native_thumbnail(file_path, thumbnail_path, legacy_thumbnail_path)
                    if result_path is None:
                        result_path = self._create_image_thumbnail(file_path, legacy_thumbnail_path)
                elif queue_name == "native_video":
                    result_path = self._create_video_thumbnail_batch_safe(
                        file_path, thumbnail_path, legacy_thumbnail_path, prefer_native=True
                    )
                elif queue_name == "python_image":
                    result_path = self._create_image_thumbnail(file_path, thumbnail_path)
                elif queue_name == "python_video":
                    result_path = self._create_video_thumbnail_batch_safe(
                        file_path, thumbnail_path, legacy_thumbnail_path, prefer_native=False
                    )

                success = bool(result_path and os.path.exists(result_path))
                if success:
                    self._update_file_access_time(result_path)
            except Exception:
                success = False

            duration = time.perf_counter() - start_time
            return queue_name, [(item, success, result_path)], duration

        def _run_native_batch_task(queue_name: str, items: List[Dict]) -> Tuple[str, List[Tuple[Dict, bool, Optional[str]]], float]:
            start_time = time.perf_counter()
            outputs: List[Tuple[Dict, bool, Optional[str]]] = []

            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
            file_paths = [item["file_path"] for item in items]
            batch_jpgs: List[Optional[bytes]] = []

            try:
                if self._rust_bridge.available:
                    batch_jpgs = self._rust_bridge.generate_jpg_batch(file_paths, dpi_scaled_size, dpi_scaled_size)
            except Exception as e:
                warning(f"[ThumbnailManager] Rust批量缩略图生成失败，将逐项回退: {e}")
                batch_jpgs = [None for _ in items]

            if len(batch_jpgs) < len(items):
                batch_jpgs.extend([None] * (len(items) - len(batch_jpgs)))

            for item, jpg_bytes in zip(items, batch_jpgs):
                file_path = item["file_path"]
                thumbnail_path = item["thumbnail_path"]
                legacy_thumbnail_path = item["legacy_thumbnail_path"]

                result_path = None
                success = False

                try:
                    if jpg_bytes:
                        with open(thumbnail_path, "wb") as f:
                            f.write(jpg_bytes)
                        result_path = thumbnail_path
                    else:
                        result_path = self._create_native_thumbnail(file_path, thumbnail_path, legacy_thumbnail_path)
                        if result_path is None:
                            if queue_name == "native_video":
                                result_path = self._create_video_thumbnail_ffmpeg(file_path, thumbnail_path)
                            else:
                                result_path = self._create_image_thumbnail(file_path, legacy_thumbnail_path)

                    success = bool(result_path and os.path.exists(result_path))
                    if success:
                        self._update_file_access_time(result_path)
                except Exception:
                    success = False
                    result_path = None

                outputs.append((item, success, result_path))

            duration = time.perf_counter() - start_time
            return queue_name, outputs, duration

        info(f"[ThumbnailManager] 开始批量生成缩略图，总任务数: {total_count}")
        for file_data in files_to_generate:
            if cancel_check and cancel_check():
                break

            file_path = file_data.get("path", "")
            if not file_path or not os.path.exists(file_path):
                processed_count += 1
                if progress_callback:
                    progress_callback(processed_count, total_count, file_data, False)
                continue

            thumbnail_path = self.get_thumbnail_path(file_path)
            legacy_thumbnail_path = self.get_legacy_thumbnail_path(file_path)

            if os.path.exists(thumbnail_path) or os.path.exists(legacy_thumbnail_path):
                existing = thumbnail_path if os.path.exists(thumbnail_path) else legacy_thumbnail_path
                self._update_file_access_time(existing)
                success_count += 1
                processed_count += 1
                if progress_callback:
                    progress_callback(processed_count, total_count, file_data, True)
                continue

            suffix = os.path.splitext(file_path)[1].lower()
            is_video_file = suffix in self.VIDEO_FORMATS
            use_python_dedicated = (
                suffix in self.RAW_FORMATS
                or suffix in self.PSD_FORMATS
                or suffix == '.svg'
            )

            item = {
                "file_data": file_data,
                "file_path": file_path,
                "thumbnail_path": thumbnail_path,
                "legacy_thumbnail_path": legacy_thumbnail_path,
            }

            if is_video_file:
                if self._rust_bridge.available:
                    native_load = len(task_queues["native_video"]) / max(1, queue_limits["native_video"])
                    python_load = len(task_queues["python_video"]) / max(1, queue_limits["python_video"])
                    if native_load <= python_load:
                        task_queues["native_video"].append(item)
                    else:
                        task_queues["python_video"].append(item)
                else:
                    task_queues["python_video"].append(item)
            elif self._rust_bridge.available and not use_python_dedicated:
                task_queues["native_image"].append(item)
            else:
                task_queues["python_image"].append(item)

        def _has_pending_tasks() -> bool:
            return any(task_queues[name] for name in task_queues)

        def _select_queue_for_dispatch() -> Optional[str]:
            candidate_name = None
            candidate_score = None

            for name in queue_order:
                if not task_queues[name]:
                    continue
                if queue_active_counts[name] >= queue_limits[name]:
                    continue

                backlog = len(task_queues[name])
                active = queue_active_counts[name]
                avg_duration = max(queue_avg_duration[name], 0.05)
                batch_size = max(1, queue_batch_sizes.get(name, 1))

                score = ((backlog * batch_size) / (active + 1)) * (1.0 + min(avg_duration, 5.0))

                if name in ("native_video", "python_video"):
                    score *= 1.25

                if candidate_score is None or score > candidate_score:
                    candidate_name = name
                    candidate_score = score

            return candidate_name

        info(
            "[ThumbnailManager] 批量任务队列统计："
            f"native_video={len(task_queues['native_video'])}, "
            f"python_video={len(task_queues['python_video'])}, "
            f"native_image={len(task_queues['native_image'])}, "
            f"python_image={len(task_queues['python_image'])}, "
            "video_mode=1_hw_queue+2_sw_workers"
        )

        max_workers = sum(queue_limits.values())
        future_to_queue = {}
        cancelled = False

        def _consume_completed_futures(done_futures) -> None:
            nonlocal success_count, processed_count

            for future in done_futures:
                queue_name = future_to_queue.pop(future, None)
                if queue_name is not None and queue_active_counts[queue_name] > 0:
                    queue_active_counts[queue_name] -= 1

                try:
                    result_queue_name, result_items, duration = future.result()
                    prev_avg = queue_avg_duration[result_queue_name]
                    queue_avg_duration[result_queue_name] = prev_avg * 0.7 + duration * 0.3
                except Exception:
                    result_items = []

                for item, success, result_path in result_items:
                    if success:
                        success_count += 1

                    processed_count += 1
                    if progress_callback:
                        progress_callback(processed_count, total_count, item["file_data"], success)

        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="thumb_batch")
        try:
            while True:
                if cancel_check and cancel_check():
                    cancelled = True
                    break

                dispatched = False
                while True:
                    queue_name = _select_queue_for_dispatch()
                    if not queue_name:
                        break

                    batch_size = max(1, queue_batch_sizes.get(queue_name, 1))
                    batch_items = []
                    while task_queues[queue_name] and len(batch_items) < batch_size:
                        batch_items.append(task_queues[queue_name].popleft())

                    if not batch_items:
                        break

                    if queue_name.startswith("native_") and len(batch_items) > 1:
                        debug(f"[ThumbnailManager] 提交原生批量任务: queue={queue_name}, batch_size={len(batch_items)}")
                        future = executor.submit(_run_native_batch_task, queue_name, batch_items)
                    else:
                        debug(f"[ThumbnailManager] 提交单项任务: queue={queue_name}, file={batch_items[0]['file_path']}")
                        future = executor.submit(_run_single_task, queue_name, batch_items[0])

                    future_to_queue[future] = queue_name
                    queue_active_counts[queue_name] += 1
                    dispatched = True

                if not future_to_queue:
                    if not _has_pending_tasks():
                        break
                    if not dispatched:
                        time.sleep(0.01)
                    continue

                done, _ = wait(list(future_to_queue.keys()), timeout=0.1, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                _consume_completed_futures(done)

            if not cancelled:
                while future_to_queue:
                    done, _ = wait(list(future_to_queue.keys()), timeout=0.1, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    _consume_completed_futures(done)
            else:
                done_now = [future for future in list(future_to_queue.keys()) if future.done()]
                if done_now:
                    _consume_completed_futures(done_now)
        finally:
            if cancelled:
                for future in list(future_to_queue.keys()):
                    future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)

        info(
            f"[ThumbnailManager] 批量缩略图生成结束: success={success_count}, processed={processed_count}, cancelled={cancelled}"
        )

        if native_stats_enabled:
            stats = self._rust_bridge.get_decode_stats()
            if stats:
                hw_attempts = (
                    int(stats.get("d3d11va_attempts", 0))
                    + int(stats.get("dxva2_attempts", 0))
                    + int(stats.get("qsv_attempts", 0))
                )
                hw_hits = (
                    int(stats.get("d3d11va_hits", 0))
                    + int(stats.get("dxva2_hits", 0))
                    + int(stats.get("qsv_hits", 0))
                )
                sw_attempts = int(stats.get("software_attempts", 0))
                sw_hits = int(stats.get("software_hits", 0))
                sw_fallbacks = int(stats.get("software_fallbacks", 0))
                hw_hit_rate = (hw_hits / hw_attempts * 100.0) if hw_attempts > 0 else 0.0

                info(
                    "[ThumbnailManager] Rust视频解码统计："
                    f"硬解尝试={hw_attempts}, "
                    f"硬解命中={hw_hits}, "
                    f"硬解命中率={hw_hit_rate:.1f}%, "
                    f"D3D11VA={int(stats.get('d3d11va_hits', 0))}/{int(stats.get('d3d11va_attempts', 0))}, "
                    f"DXVA2={int(stats.get('dxva2_hits', 0))}/{int(stats.get('dxva2_attempts', 0))}, "
                    f"QSV={int(stats.get('qsv_hits', 0))}/{int(stats.get('qsv_attempts', 0))}, "
                    f"软解尝试={sw_attempts}, "
                    f"软解成功={sw_hits}, "
                    f"软解回退={sw_fallbacks}"
                )

        return success_count, processed_count
    
    def _create_native_thumbnail(self, file_path: str, thumbnail_path: str, legacy_thumbnail_path: str) -> Optional[str]:
        """
        使用 Rust 原生引擎生成缩略图
        
        Args:
            file_path: 文件路径
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 成功返回缩略图路径，失败返回None
        """
        if not self._rust_bridge.available:
            return None

        try:
            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)

            # 优先使用 Rust 直接 JPG 输出，降低磁盘 IO 与批量预览开销
            jpg_bytes = self._rust_bridge.generate_jpg(file_path, dpi_scaled_size, dpi_scaled_size)
            if jpg_bytes:
                with open(thumbnail_path, "wb") as f:
                    f.write(jpg_bytes)
                debug(f"[ThumbnailManager] Rust(JPG直出)缩略图生成成功: {thumbnail_path}")
                return thumbnail_path

            # 回退到 Rust JPEG 输出（兼容别名接口）
            jpeg_bytes = self._rust_bridge.generate_jpeg(file_path, dpi_scaled_size, dpi_scaled_size)
            if jpeg_bytes:
                with open(thumbnail_path, "wb") as f:
                    f.write(jpeg_bytes)
                debug(f"[ThumbnailManager] Rust(JPEG直出)缩略图生成成功: {thumbnail_path}")
                return thumbnail_path

            # 回退到 RGBA 路径
            if not PIL_AVAILABLE:
                return None

            generated = self._rust_bridge.generate_rgba(file_path, dpi_scaled_size, dpi_scaled_size)
            if not generated:
                return None

            raw, width, height, channels = generated
            if channels not in (3, 4):
                return None

            mode = "RGBA" if channels == 4 else "RGB"
            img = Image.frombytes(mode, (width, height), raw)
            if mode == "RGB":
                img = img.convert("RGBA")
            img = img.convert("RGB")
            img.save(thumbnail_path, format='JPEG', quality=self.QUALITY)
            try:
                img.close()
            except Exception:
                pass

            debug(f"[ThumbnailManager] Rust(RGBA回退)缩略图生成成功: {thumbnail_path}")
            return thumbnail_path
        except Exception as e:
            warning(f"[ThumbnailManager] Rust缩略图生成失败，回退Python: {file_path}, 错误: {e}")
            return None

    def _create_image_thumbnail(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """
        为图片文件创建缩略图
        
        Args:
            file_path: 图片文件路径
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 缩略图路径，失败返回None
        """
        if not PIL_AVAILABLE:
            warning("[ThumbnailManager] PIL库未安装，无法生成图片缩略图")
            return None
        
        img = None
        thumbnail = None
        img_converted = None
        
        try:
            suffix = os.path.splitext(file_path)[1].lower()
            
            # 加载图像
            img, success = self._load_image(file_path, suffix)
            if not success or img is None:
                return None
            
            # 检查图像尺寸限制
            if not self._check_image_size_limit(img):
                return None
            
            # 计算缩略图尺寸
            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
            
            # 使用thumbnail方法生成缩略图，保持宽高比
            img.thumbnail((dpi_scaled_size, dpi_scaled_size), Image.Resampling.LANCZOS)

            # 直接输出保持原始比例的缩略图，避免补白后在 JPEG 中显示为白边
            if img.mode == 'RGBA':
                thumbnail = img.convert("RGB")
            elif img.mode == 'P':
                img_converted = img.convert('RGBA')
                thumbnail = img_converted.convert("RGB")
            else:
                thumbnail = img.convert("RGB")

            thumbnail.save(thumbnail_path, format='JPEG', quality=self.QUALITY)
            
            debug(f"[ThumbnailManager] 图片缩略图生成成功: {thumbnail_path}")
            return thumbnail_path
            
        except Exception as e:
            warning(f"[ThumbnailManager] 生成图片缩略图失败: {file_path}, 错误: {e}")
            return None
        finally:
            # 确保所有Image对象都被关闭
            if img_converted is not None:
                try:
                    img_converted.close()
                except Exception:
                    pass
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
            if thumbnail is not None:
                try:
                    thumbnail.close()
                except Exception:
                    pass
    
    def _get_total_frame_cache_bytes(self) -> int:
        """获取所有视频帧缓存的总内存占用"""
        return sum(cache.current_bytes for cache in self._frame_caches.values())

    def _enforce_global_frame_cache_limit(self):
        """按内存预算清理全局视频帧缓存"""
        while (
            len(self._frame_caches) > self.MAX_FRAME_CACHE_GROUPS
            or self._get_total_frame_cache_bytes() > self.MAX_FRAME_CACHE_BYTES
        ):
            if not self._frame_caches:
                break
            oldest_key = min(
                self._frame_caches.keys(),
                key=lambda k: self._frame_caches[k].last_accessed
            )
            oldest_cache = self._frame_caches.pop(oldest_key, None)
            if oldest_cache is not None:
                oldest_cache.clear()

    def _get_or_create_frame_cache(self, file_path: str) -> VideoFrameCache:
        """获取或创建视频帧缓存"""
        with self._frame_cache_lock:
            # 清理过期缓存
            current_time = time.time()
            expired_keys = [
                k for k, v in self._frame_caches.items()
                if current_time - v.last_accessed > self.FRAME_CACHE_EXPIRY
            ]
            for k in expired_keys:
                cache = self._frame_caches.pop(k, None)
                if cache is not None:
                    cache.clear()

            # 获取或创建缓存
            if file_path not in self._frame_caches:
                self._enforce_global_frame_cache_limit()
                self._frame_caches[file_path] = VideoFrameCache(
                    max_bytes=self.MAX_FRAME_CACHE_BYTES_PER_GROUP
                )

            self._enforce_global_frame_cache_limit()
            return self._frame_caches[file_path]
    
    def _try_acquire_video_lock(self, file_path: str) -> bool:
        """尝试获取视频处理锁（请求去重）"""
        with self._processing_lock:
            if file_path in self._processing_videos:
                return False
            self._processing_videos.add(file_path)
            return True
    
    def _release_video_lock(self, file_path: str):
        """释放视频处理锁"""
        with self._processing_lock:
            self._processing_videos.discard(file_path)
    
    def _create_video_thumbnail(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """
        为视频文件创建缩略图

        仅使用 Rust 原生链路 / FFmpeg 软解链路，不再依赖 OpenCV。
        """
        # 请求去重：检查是否已有相同视频正在处理
        if not self._try_acquire_video_lock(file_path):
            debug(f"[ThumbnailManager] 视频正在处理中，跳过重复请求: {file_path}")
            return None

        try:
            with self._video_semaphore:
                result = self._create_video_thumbnail_ffmpeg(file_path, thumbnail_path)
                if result is not None:
                    return result

                warning("[ThumbnailManager] FFmpeg软解失败，无法生成视频缩略图")
                return None
        finally:
            self._release_video_lock(file_path)

    def _get_subprocess_creationflags(self) -> int:
        """获取适用于当前平台的子进程创建标志"""
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _get_video_duration_ffprobe(self, file_path: str) -> Optional[float]:
        """使用 ffprobe 获取视频时长（秒）"""
        command = [
            get_ffprobe_path(),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_entries",
            "format=duration:stream=codec_type,duration",
            "-show_streams",
            file_path,
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.FFPROBE_TIMEOUT,
                creationflags=self._get_subprocess_creationflags(),
            )
        except FileNotFoundError:
            warning("[ThumbnailManager] 未找到 ffprobe，可用性受限")
            return None
        except subprocess.TimeoutExpired:
            debug(f"[ThumbnailManager] ffprobe 获取视频时长超时: {file_path}")
            return None
        except Exception as e:
            debug(f"[ThumbnailManager] ffprobe 获取视频时长失败: {file_path}, 错误: {e}")
            return None

        if completed.returncode != 0:
            stderr_text = (completed.stderr or "").strip()
            if stderr_text:
                debug(f"[ThumbnailManager] ffprobe 异常输出: {stderr_text}")
            return None

        try:
            payload = json.loads(completed.stdout or "{}")
        except Exception:
            return None

        duration_candidates: List[float] = []

        format_info = payload.get("format") or {}
        format_duration = format_info.get("duration")
        if format_duration is not None:
            try:
                duration_candidates.append(float(format_duration))
            except (TypeError, ValueError):
                pass

        for stream in payload.get("streams") or []:
            if stream.get("codec_type") != "video":
                continue
            stream_duration = stream.get("duration")
            if stream_duration is None:
                continue
            try:
                duration_candidates.append(float(stream_duration))
            except (TypeError, ValueError):
                continue

        duration_candidates = [value for value in duration_candidates if value > 0]
        if not duration_candidates:
            return None

        return max(duration_candidates)

    def _get_ffmpeg_seek_candidates(self, file_path: str) -> List[float]:
        """生成 FFmpeg 抽帧的候选时间点（秒）"""
        duration = self._get_video_duration_ffprobe(file_path)
        if duration is None or duration <= 0:
            return [0.0]

        base_ratios = [0.15, 0.5, 0.03, 0.75, 0.9, 0.0]
        candidates: List[float] = []
        max_seek = max(0.0, duration - 0.05)

        for ratio in base_ratios:
            seek_seconds = duration * ratio
            seek_seconds = min(max(seek_seconds, 0.0), max_seek)
            seek_seconds = round(seek_seconds, 3)

            if any(abs(existing - seek_seconds) < 0.05 for existing in candidates):
                continue
            candidates.append(seek_seconds)

        if not candidates:
            return [0.0]
        return candidates

    def _create_video_thumbnail_ffmpeg(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """使用 FFmpeg 软解抽帧生成视频缩略图"""
        dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
        temp_output_path = f"{thumbnail_path}.ffmpeg.tmp.jpg"
        scale_filter = f"scale={dpi_scaled_size}:{dpi_scaled_size}:force_original_aspect_ratio=decrease:flags=lanczos"

        seek_candidates = self._get_ffmpeg_seek_candidates(file_path)

        for seek_seconds in seek_candidates:
            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
            except Exception:
                pass

            command = [
                get_ffmpeg_path(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-threads",
                "0",
            ]

            if seek_seconds > 0:
                command.extend(["-ss", f"{seek_seconds:.3f}"])

            command.extend([
                "-i",
                file_path,
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-frames:v",
                "1",
                "-vf",
                scale_filter,
                "-q:v",
                "4",
                temp_output_path,
            ])

            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.FFMPEG_SOFT_TIMEOUT,
                    creationflags=self._get_subprocess_creationflags(),
                )
            except FileNotFoundError:
                warning("[ThumbnailManager] 未找到 ffmpeg，无法执行软解缩略图生成")
                return None
            except subprocess.TimeoutExpired:
                debug(
                    f"[ThumbnailManager] FFmpeg软解抽帧超时: {file_path}, "
                    f"seek={seek_seconds:.3f}s"
                )
                continue
            except Exception as e:
                debug(
                    f"[ThumbnailManager] FFmpeg软解抽帧失败: {file_path}, "
                    f"seek={seek_seconds:.3f}s, 错误: {e}"
                )
                continue

            if completed.returncode == 0 and os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
                try:
                    os.replace(temp_output_path, thumbnail_path)
                    debug(
                        f"[ThumbnailManager] FFmpeg软解缩略图生成成功: {thumbnail_path}, "
                        f"seek={seek_seconds:.3f}s"
                    )
                    return thumbnail_path
                except Exception as e:
                    debug(f"[ThumbnailManager] FFmpeg缩略图落盘失败: {thumbnail_path}, 错误: {e}")
            else:
                stderr_text = (completed.stderr or "").strip()
                if stderr_text:
                    debug(
                        f"[ThumbnailManager] FFmpeg软解尝试失败: {file_path}, "
                        f"seek={seek_seconds:.3f}s, stderr={stderr_text}"
                    )

        try:
            if os.path.exists(temp_output_path):
                os.remove(temp_output_path)
        except Exception:
            pass

        warning(f"[ThumbnailManager] FFmpeg软解未能生成视频缩略图: {file_path}")
        return None

    def _create_video_thumbnail_batch_safe(
        self,
        file_path: str,
        thumbnail_path: str,
        legacy_thumbnail_path: str,
        prefer_native: bool = True
    ) -> Optional[str]:
        """批量模式下的视频缩略图生成入口

        通过独立子进程隔离底层阻塞风险：
        - 硬解队列：子进程内走 Rust 原生链路，失败后回退 FFmpeg 软解；
        - 软解队列：子进程内强制走 FFmpeg 软解；
        - 父进程使用真实超时控制；
        - 超时后直接跳过当前文件，避免整个批量任务被卡死。
        """
        timeout = max(int(self.BATCH_VIDEO_SUBPROCESS_TIMEOUT), int(self.VIDEO_PROCESSING_TIMEOUT) + 5)
        project_root = str(Path(__file__).resolve().parents[2])

        command = [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from freeassetfilter.core.thumbnail_manager import _run_batch_video_thumbnail_subprocess; "
                "sys.exit(_run_batch_video_thumbnail_subprocess("
                "sys.argv[1], float(sys.argv[2]), sys.argv[3].lower() in ('1', 'true', 'yes')"
                "))"
            ),
            file_path,
            str(float(self.dpi_scale)),
            "1" if prefer_native else "0",
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=project_root,
                creationflags=self._get_subprocess_creationflags(),
            )
        except subprocess.TimeoutExpired:
            warning(f"[ThumbnailManager] 视频缩略图生成超时，已跳过: {file_path}")
            return None
        except Exception as e:
            warning(f"[ThumbnailManager] 启动视频缩略图子进程失败，已跳过: {file_path}, 错误: {e}")
            return None

        if completed.returncode == 0:
            if os.path.exists(thumbnail_path):
                return thumbnail_path
            if os.path.exists(legacy_thumbnail_path):
                return legacy_thumbnail_path

        stderr_text = (completed.stderr or "").strip()
        if stderr_text:
            debug(f"[ThumbnailManager] 视频缩略图子进程异常输出: {stderr_text}")

        return None
    
    def _load_image(self, file_path: str, suffix: str) -> Tuple[Optional[Image.Image], bool]:
        """
        加载图像文件（带尺寸限制和下采样）

        Args:
            file_path: 图像文件路径
            suffix: 文件后缀名

        Returns:
            Tuple[Optional[Image.Image], bool]: (图像对象, 是否成功)
        """
        if not PIL_AVAILABLE:
            return None, False

        img = None
        raw = None

        try:
            if suffix in self.RAW_FORMATS:
                # RAW格式
                try:
                    import rawpy
                    raw = rawpy.imread(file_path)
                    rgb = raw.postprocess()
                    img = Image.fromarray(rgb)
                except ImportError:
                    warning(f"[ThumbnailManager] rawpy库未安装，无法加载RAW文件: {file_path}")
                    return None, False
            elif suffix in ['.avif', '.heic']:
                # AVIF和HEIC格式
                try:
                    import pillow_avif
                except ImportError:
                    pass
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except ImportError:
                    pass
                img = Image.open(file_path)
            elif suffix in self.PSD_FORMATS:
                # PSD格式
                psd = None
                try:
                    from psd_tools import PSDImage
                    psd = PSDImage.open(file_path)
                    img = psd.composite()
                except ImportError:
                    warning(f"[ThumbnailManager] psd-tools库未安装，无法加载PSD文件: {file_path}")
                    return None, False
                finally:
                    if psd is not None:
                        try:
                            psd.close()
                        except Exception:
                            pass
            elif suffix == '.svg':
                # SVG格式
                return self._load_svg_image(file_path)
            else:
                # 普通图像格式
                img = Image.open(file_path)

            # 检查图像尺寸并应用下采样
            img = self._apply_image_size_limit(img, file_path)

            return img, True

        except Exception as e:
            warning(f"[ThumbnailManager] 加载图像失败: {file_path}, 错误: {e}")
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
            return None, False
        finally:
            # 确保raw对象被关闭
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    pass

    def _apply_image_size_limit(self, img: Image.Image, file_path: str) -> Image.Image:
        """
        应用图像尺寸限制，对超大图像进行下采样

        Args:
            img: PIL图像对象
            file_path: 文件路径（用于日志）

        Returns:
            Image.Image: 处理后的图像
        """
        width, height = img.size
        total_pixels = width * height

        # 检查是否超过像素总数限制
        if total_pixels > self.MAX_IMAGE_PIXELS:
            scale = (self.MAX_IMAGE_PIXELS / total_pixels) ** 0.5
            new_width = int(width * scale)
            new_height = int(height * scale)
            debug(f"[ThumbnailManager] 图像像素数超限 ({total_pixels})，下采样至 {new_width}x{new_height}: {file_path}")
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            width, height = new_width, new_height

        # 检查是否超过尺寸限制
        if width > self.MAX_IMAGE_DIMENSION or height > self.MAX_IMAGE_DIMENSION:
            # 计算缩放比例
            scale = min(
                self.MAX_IMAGE_DIMENSION / width,
                self.MAX_IMAGE_DIMENSION / height
            )

            new_width = int(width * scale)
            new_height = int(height * scale)

            debug(f"[ThumbnailManager] 图像尺寸超限 ({width}x{height})，下采样至 {new_width}x{new_height}: {file_path}")

            # 使用LANCZOS重采样（高质量）
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        return img
    
    def _load_svg_image(self, file_path: str) -> Tuple[Optional[Image.Image], bool]:
        """
        加载SVG图像
        
        Args:
            file_path: SVG文件路径
            
        Returns:
            Tuple[Optional[Image.Image], bool]: (图像对象, 是否成功)
        """
        img = None
        qimage = None
        painter = None
        renderer = None
        cache_key = None
        
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QImage, QPainter
            from PySide6.QtCore import Qt

            file_mtime = os.path.getmtime(file_path)
            cache_key = (file_path, file_mtime)
            with self._svg_cache_lock:
                cached_img = self._svg_render_cache.get(cache_key)
                if cached_img is not None:
                    return cached_img.copy(), True
            
            # 直接使用QSvgRenderer渲染SVG，不经过SvgRenderer的复杂处理
            renderer = QSvgRenderer(file_path)
            
            if not renderer.isValid():
                warning(f"[ThumbnailManager] 无效的SVG文件: {file_path}")
                return None, False
            
            # 获取SVG的默认尺寸
            default_size = renderer.defaultSize()
            
            # 如果SVG没有设置尺寸，使用默认尺寸 256x256
            if default_size.width() <= 0 or default_size.height() <= 0:
                render_width, render_height = 256, 256
            else:
                # 保持原始比例，最大边为256
                max_size = 256
                scale = min(max_size / default_size.width(), max_size / default_size.height())
                render_width = int(default_size.width() * scale)
                render_height = int(default_size.height() * scale)
                
                # 确保最小尺寸为1
                render_width = max(1, render_width)
                render_height = max(1, render_height)
            
            # 检查尺寸限制
            if render_width > self.MAX_IMAGE_DIMENSION or render_height > self.MAX_IMAGE_DIMENSION:
                warning(f"[ThumbnailManager] SVG渲染尺寸超出限制: {render_width}x{render_height}")
                return None, False
            
            # 检查像素总数限制
            render_pixels = render_width * render_height
            if render_pixels > self.MAX_IMAGE_PIXELS:
                warning(f"[ThumbnailManager] SVG渲染像素数超出限制: {render_pixels} > {self.MAX_IMAGE_PIXELS}")
                return None, False
            
            # 创建QImage用于渲染 - 直接使用计算好的保持比例的尺寸
            qimage = QImage(render_width, render_height, QImage.Format_ARGB32_Premultiplied)
            qimage.fill(Qt.transparent)
            
            # 创建画家并渲染
            painter = QPainter(qimage)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            
            # 计算缩放因子 - 保持原始宽高比
            if default_size.width() > 0 and default_size.height() > 0:
                scale_x = render_width / default_size.width()
                scale_y = render_height / default_size.height()
                painter.scale(scale_x, scale_y)
            
            renderer.render(painter)
            
            # 转换为RGBA8888格式
            if qimage.format() != QImage.Format_RGBA8888:
                qimage = qimage.convertToFormat(QImage.Format_RGBA8888)
            
            # 获取图像数据
            width = qimage.width()
            height = qimage.height()
            ptr = qimage.constBits()
            
            # 处理不同版本的PySide6
            if hasattr(ptr, 'tobytes'):
                img_data = ptr.tobytes()
            elif hasattr(ptr, 'asstring'):
                img_data = ptr.asstring()
            else:
                img_data = bytes(ptr)
            
            # 验证数据长度
            expected_len = width * height * 4  # RGBA = 4 bytes per pixel
            if len(img_data) < expected_len:
                warning(f"[ThumbnailManager] SVG图像数据长度不足: {len(img_data)} < {expected_len}")
                return None, False
            
            # 创建PIL图像
            img = Image.frombytes("RGBA", (width, height), img_data)

            with self._svg_cache_lock:
                try:
                    self._svg_render_cache[cache_key] = img.copy()
                    self._svg_cache_access_order.append(cache_key)

                    while len(self._svg_cache_access_order) > self.MAX_SVG_CACHE_ENTRIES:
                        oldest_key = self._svg_cache_access_order.popleft()
                        if oldest_key == cache_key:
                            continue
                        old_img = self._svg_render_cache.pop(oldest_key, None)
                        if old_img is not None:
                            try:
                                old_img.close()
                            except Exception:
                                pass
                except Exception:
                    pass
            
            return img, True
            
        except Exception as e:
            warning(f"[ThumbnailManager] 加载SVG失败: {file_path}, 错误: {e}")
            return None, False
        finally:
            # 清理Qt资源
            if painter is not None:
                try:
                    painter.end()
                except Exception:
                    pass
            qimage = None
            renderer = None
            # 强制垃圾回收
            import gc
            gc.collect()
    
    def clear_all_thumbnails(self) -> int:
        """
        清理所有缩略图缓存
        
        Returns:
            int: 删除的文件数量
        """
        try:
            import glob
            
            if not os.path.exists(self._thumb_dir):
                return 0
            
            thumbnail_files = glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_PRIMARY}"))
            thumbnail_files.extend(glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_LEGACY}")))
            deleted_count = 0
            
            for file_path in thumbnail_files:
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except (OSError, IOError) as e:
                        debug(f"[ThumbnailManager] 删除缩略图文件失败 {file_path}: {e}")

            with self._frame_cache_lock:
                for cache in self._frame_caches.values():
                    cache.clear()
                self._frame_caches.clear()

            with self._svg_cache_lock:
                for cached_img in self._svg_render_cache.values():
                    try:
                        cached_img.close()
                    except Exception:
                        pass
                self._svg_render_cache.clear()
                self._svg_cache_access_order.clear()

            if self._rust_bridge.available:
                self._rust_bridge.clear_cache()
            
            info(f"[ThumbnailManager] 已清理 {deleted_count} 个缩略图缓存文件")
            return deleted_count
            
        except Exception as e:
            error(f"[ThumbnailManager] 清理缩略图缓存失败: {e}")
            return 0
    
    def get_thumbnail_count(self) -> int:
        """
        获取当前缩略图数量
        
        Returns:
            int: 缩略图文件数量
        """
        try:
            import glob

            if not os.path.exists(self._thumb_dir):
                return 0

            thumbnail_files = glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_PRIMARY}"))
            thumbnail_files.extend(glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_LEGACY}")))
            return len(thumbnail_files)

        except Exception as e:
            debug(f"获取缩略图数量失败: {e}")
            return 0

    def _get_all_thumbnail_files(self) -> List[Tuple[str, float]]:
        """
        获取所有缩略图文件及其时间戳

        Returns:
            List[Tuple[str, float]]: [(文件路径, 时间戳)]
        """
        thumbnail_files: List[Tuple[str, float]] = []

        try:
            if not os.path.exists(self._thumb_dir):
                return thumbnail_files

            for filename in os.listdir(self._thumb_dir):
                if filename.endswith(self.THUMB_EXT_PRIMARY) or filename.endswith(self.THUMB_EXT_LEGACY):
                    file_path = os.path.join(self._thumb_dir, filename)
                    try:
                        file_time = os.path.getctime(file_path)
                    except (OSError, IOError):
                        try:
                            file_time = os.path.getmtime(file_path)
                        except (OSError, IOError) as e:
                            debug(f"[ThumbnailManager] 获取文件时间失败 {file_path}: {e}")
                            continue
                    thumbnail_files.append((file_path, file_time))
        except (OSError, IOError) as e:
            debug(f"[ThumbnailManager] 访问缩略图目录失败 {self._thumb_dir}: {e}")

        return thumbnail_files

    def clean_thumbnails(self, cleanup_period_days: Optional[int] = None, max_cache_size: int = 2000) -> Tuple[int, int]:
        """
        清理缩略图缓存，删除超过最大数量的旧文件，或删除超过指定天数的文件

        Args:
            cleanup_period_days: 缓存清理周期（天），如果提供则删除超过此天数的文件
            max_cache_size: 按数量清理时允许保留的最大文件数

        Returns:
            Tuple[int, int]: (删除的文件数量, 剩余的文件数量)
        """
        thumbnail_files = self._get_all_thumbnail_files()
        total_files = len(thumbnail_files)
        files_to_delete_paths: List[str] = []

        if cleanup_period_days:
            current_time = time.time()
            cutoff_time = current_time - (cleanup_period_days * 86400)
            for file_path, file_time in thumbnail_files:
                if file_time < cutoff_time:
                    files_to_delete_paths.append(file_path)
        else:
            if total_files <= max_cache_size:
                return 0, total_files

            files_to_delete = total_files - max_cache_size
            thumbnail_files.sort(key=lambda x: x[1])
            files_to_delete_paths = [file_path for file_path, _ in thumbnail_files[:files_to_delete]]

        deleted_count = 0
        for file_path in files_to_delete_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    deleted_count += 1
            except (OSError, IOError) as e:
                debug(f"[ThumbnailManager] 删除缓存文件失败 {file_path}: {e}")

        return deleted_count, total_files - deleted_count

    def is_thumbnail_exists(self, file_path: str) -> bool:
        """
        检查指定文件的缩略图是否存在

        Args:
            file_path: 原始文件路径

        Returns:
            bool: 如果缩略图存在返回True，否则返回False
        """
        return self.has_thumbnail(file_path)

    def get_cache_statistics(self, max_cache_size: int = 2000) -> Dict[str, Optional[float]]:
        """
        获取缓存统计信息

        Args:
            max_cache_size: 用于计算占用比例的最大文件数阈值

        Returns:
            Dict[str, Optional[float]]: 缓存统计信息
        """
        thumbnail_files = self._get_all_thumbnail_files()
        total_files = len(thumbnail_files)

        if total_files == 0:
            return {
                "total_files": 0,
                "max_files": max_cache_size,
                "usage_percentage": 0,
                "oldest_file_time": None,
                "newest_file_time": None,
            }

        file_times = [file_time for _, file_time in thumbnail_files]
        oldest_time = min(file_times)
        newest_time = max(file_times)
        usage_percentage = (total_files / max_cache_size) * 100 if max_cache_size > 0 else 0

        return {
            "total_files": total_files,
            "max_files": max_cache_size,
            "usage_percentage": usage_percentage,
            "oldest_file_time": oldest_time,
            "newest_file_time": newest_time,
        }


def _run_batch_video_thumbnail_subprocess(file_path: str, dpi_scale: float, prefer_native: bool = True) -> int:
    """批量视频缩略图子进程入口"""
    try:
        manager = get_thumbnail_manager(dpi_scale)
        thumbnail_path = manager.get_thumbnail_path(file_path)
        legacy_thumbnail_path = manager.get_legacy_thumbnail_path(file_path)

        result = None
        if prefer_native:
            result = manager._create_native_thumbnail(file_path, thumbnail_path, legacy_thumbnail_path)

        if result is None:
            result = manager._create_video_thumbnail_ffmpeg(file_path, thumbnail_path)

        if result and os.path.exists(result):
            return 0
        return 2
    except Exception:
        return 1


# 全局缩略图管理器实例
_thumbnail_manager = None


def get_thumbnail_manager(dpi_scale: float = 1.0) -> ThumbnailManager:
    """
    获取全局缩略图管理器实例
    
    Args:
        dpi_scale: DPI缩放因子
        
    Returns:
        ThumbnailManager: 缩略图管理器实例
    """
    global _thumbnail_manager
    if _thumbnail_manager is None:
        _thumbnail_manager = ThumbnailManager(dpi_scale)
    else:
        _thumbnail_manager.set_dpi_scale(dpi_scale)
    return _thumbnail_manager


def create_thumbnail(file_path: str, dpi_scale: float = 1.0, force_regenerate: bool = False) -> Optional[str]:
    """
    便捷函数：为文件创建缩略图
    
    Args:
        file_path: 文件路径
        dpi_scale: DPI缩放因子
        force_regenerate: 是否强制重新生成
        
    Returns:
        Optional[str]: 缩略图路径，失败返回None
    """
    manager = get_thumbnail_manager(dpi_scale)
    return manager.create_thumbnail(file_path, force_regenerate)


def get_thumbnail_path(file_path: str) -> str:
    """
    便捷函数：获取文件主缩略图路径
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 主缩略图路径
    """
    manager = get_thumbnail_manager()
    return manager.get_thumbnail_path(file_path)


def get_existing_thumbnail_path(file_path: str) -> Optional[str]:
    """
    便捷函数：获取当前实际存在的缩略图路径。
    优先返回 JPG；若不存在则回退 PNG。
    """
    manager = get_thumbnail_manager()
    return manager.get_existing_thumbnail_path(file_path)


def has_thumbnail(file_path: str) -> bool:
    """
    便捷函数：检查文件是否已有缩略图
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否存在缩略图
    """
    manager = get_thumbnail_manager()
    return manager.has_thumbnail(file_path)


def is_media_file(file_path: str) -> bool:
    """
    便捷函数：判断文件是否为媒体文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否为媒体文件
    """
    manager = get_thumbnail_manager()
    return manager.is_media_file(file_path)


def is_image_file(file_path: str) -> bool:
    """
    便捷函数：判断文件是否为图片文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否为图片文件
    """
    manager = get_thumbnail_manager()
    return manager.is_image_file(file_path)


def is_video_file(file_path: str) -> bool:
    """
    便捷函数：判断文件是否为视频文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否为视频文件
    """
    manager = get_thumbnail_manager()
    return manager.is_video_file(file_path)


def clear_all_thumbnails() -> int:
    """
    便捷函数：清理所有缩略图缓存
    
    Returns:
        int: 删除的文件数量
    """
    manager = get_thumbnail_manager()
    return manager.clear_all_thumbnails()


def clean_thumbnails(cleanup_period_days: Optional[int] = None, max_cache_size: int = 2000) -> Tuple[int, int]:
    """
    便捷函数：清理缩略图缓存

    Args:
        cleanup_period_days: 缓存清理周期（天）
        max_cache_size: 按数量清理时允许保留的最大文件数

    Returns:
        Tuple[int, int]: (删除数量, 剩余数量)
    """
    manager = get_thumbnail_manager()
    return manager.clean_thumbnails(cleanup_period_days=cleanup_period_days, max_cache_size=max_cache_size)


def get_cache_statistics(max_cache_size: int = 2000) -> Dict[str, Optional[float]]:
    """
    便捷函数：获取缩略图缓存统计信息
    """
    manager = get_thumbnail_manager()
    return manager.get_cache_statistics(max_cache_size=max_cache_size)


# 模块导出
__all__ = [
    'ThumbnailManager',
    'get_thumbnail_manager',
    'create_thumbnail',
    'get_thumbnail_path',
    'get_existing_thumbnail_path',
    'has_thumbnail',
    'is_media_file',
    'is_image_file',
    'is_video_file',
    'clear_all_thumbnails',
    'clean_thumbnails',
    'get_cache_statistics',
]
