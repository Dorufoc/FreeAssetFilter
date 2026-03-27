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
import hashlib
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Optional, Tuple, Callable, Dict, Set, List
from pathlib import Path
from dataclasses import dataclass
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

# 尝试导入OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    warning("OpenCV库未安装，视频缩略图功能将不可用")


@dataclass
class FrameCacheEntry:
    """帧缓存条目"""
    frame: any  # numpy array
    timestamp: float
    position: int


@dataclass
class VideoFrameCache:
    """视频帧缓存管理器"""
    max_entries: int = 5
    cache: Dict[int, FrameCacheEntry] = None
    last_accessed: float = 0
    
    def __post_init__(self):
        if self.cache is None:
            self.cache = {}
        self.last_accessed = time.time()
    
    def get(self, position: int) -> Optional:
        """获取缓存的帧"""
        self.last_accessed = time.time()
        if position in self.cache:
            return self.cache[position].frame
        return None
    
    def put(self, position: int, frame):
        """缓存帧"""
        self.last_accessed = time.time()
        # 如果缓存已满，移除最旧的条目并显式释放帧数据
        if len(self.cache) >= self.max_entries:
            oldest_pos = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
            oldest_entry = self.cache[oldest_pos]
            if oldest_entry.frame is not None:
                oldest_entry.frame = None
            del self.cache[oldest_pos]
        self.cache[position] = FrameCacheEntry(
            frame=frame,
            timestamp=time.time(),
            position=position
        )
    
    def clear(self):
        """清空缓存，显式释放帧数据"""
        for entry in self.cache.values():
            if entry.frame is not None:
                entry.frame = None
        self.cache.clear()


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

    # 缩略图缓存格式（优先 JPG，兼容历史 PNG）
    THUMB_EXT_PRIMARY = '.jpg'
    THUMB_EXT_LEGACY = '.png'
    
    # 视频帧读取最大重试次数
    MAX_FRAME_READ_RETRIES = 3
    
    # 视频帧缓存过期时间（秒）
    FRAME_CACHE_EXPIRY = 60
    
    # 视频处理超时时间（秒）
    VIDEO_PROCESSING_TIMEOUT = 30
    
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
        
        # 正在处理的视频文件集合（用于请求去重）
        self._processing_videos: Set[str] = set()
        self._processing_lock = threading.Lock()
        
        # 并发控制信号量
        self._video_semaphore = threading.Semaphore(3)
        
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
        
        检查缩略图缓存目录大小，如果超过限制则清理最旧的文件
        """
        try:
            import glob
            max_cache_size = 500 * 1024 * 1024  # 500MB
            max_cache_files = 10000
            
            if not os.path.exists(self._thumb_dir):
                return
            
            thumbnail_files = glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_PRIMARY}"))
            thumbnail_files.extend(glob.glob(os.path.join(self._thumb_dir, f"*{self.THUMB_EXT_LEGACY}")))
            
            if len(thumbnail_files) < max_cache_files:
                return
            
            total_size = 0
            file_info_list = []
            
            for file_path in thumbnail_files:
                try:
                    stat = os.stat(file_path)
                    file_info_list.append((file_path, stat.st_atime, stat.st_size))
                    total_size += stat.st_size
                except (OSError, IOError):
                    continue
            
            if total_size < max_cache_size and len(file_info_list) < max_cache_files:
                return
            
            file_info_list.sort(key=lambda x: x[1])
            
            files_to_delete = max(1, len(file_info_list) // 10)
            deleted_count = 0
            
            for file_path, _, _ in file_info_list[:files_to_delete]:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except (OSError, IOError) as e:
                    debug(f"[ThumbnailManager] 删除缓存文件失败 {file_path}: {e}")
            
            if deleted_count > 0:
                debug(f"[ThumbnailManager] 缓存限制检查：已清理 {deleted_count} 个旧缩略图")
                
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
                    result = self._create_image_thumbnail(file_path, legacy_thumbnail_path)
                elif self.is_video_file(file_path):
                    result = self._create_video_thumbnail(file_path, legacy_thumbnail_path)
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
        批量创建缩略图（异步多队列调度版）

        调度目标：
        1. 进度按“实际完成出队”更新，而不是按提交顺序更新；
        2. 不同任务类型走不同队列（原生图片 / Python图片 / 视频）；
        3. 根据各队列积压量、活动数、平均耗时动态补位，尽量兼顾吞吐与 UI 可感知进度；
        4. 支持取消，取消后返回已完成数量。
        """
        total_count = len(files_to_generate)
        if total_count == 0:
            return 0, 0

        success_count = 0
        processed_count = 0

        queue_limits = {
            "native_image": max(2, min(6, (os.cpu_count() or 4))),
            "native_video": max(1, min(3, max(1, (os.cpu_count() or 4) // 2))),
            "python_image": max(1, min(2, (os.cpu_count() or 4) // 2 or 1)),
        }
        queue_order = ["native_video", "python_image", "native_image"]

        task_queues = {
            "native_image": deque(),
            "native_video": deque(),
            "python_image": deque(),
        }
        queue_active_counts = {name: 0 for name in task_queues}
        queue_avg_duration = {
            "native_image": 0.15,
            "native_video": 1.5,
            "python_image": 0.35,
        }

        def _run_task(queue_name: str, item: Dict) -> Tuple[str, Dict, bool, Optional[str], float]:
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
                    # 视频缩略图优先走 Rust 原生链路。
                    # Rust 侧已在 lib.rs 中通过 decode_video_with_opencv() 支持视频解码与缩略图生成。
                    # 这里使用“单项原生任务”而不是 batch 接口，确保进度可按实际完成逐项回调到 UI。
                    result_path = self._create_native_thumbnail(file_path, thumbnail_path, legacy_thumbnail_path)
                    if result_path is None:
                        result_path = self._create_video_thumbnail(file_path, legacy_thumbnail_path)
                elif queue_name == "python_image":
                    result_path = self._create_image_thumbnail(file_path, legacy_thumbnail_path)

                success = bool(result_path and os.path.exists(result_path))
                if success:
                    self._update_file_access_time(result_path)
            except Exception:
                success = False

            duration = time.perf_counter() - start_time
            return queue_name, item, success, result_path, duration

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
                    task_queues["native_video"].append(item)
                else:
                    task_queues["python_image"].append(item)
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

                # 优先积压高、当前活动少、平均耗时长的队列，
                # 让重任务能更早启动，同时避免单类任务独占所有槽位。
                score = (backlog / (active + 1)) * (1.0 + min(avg_duration, 5.0))

                if candidate_score is None or score > candidate_score:
                    candidate_name = name
                    candidate_score = score

            return candidate_name

        max_workers = sum(queue_limits.values())
        future_to_queue = {}

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="thumb_batch") as executor:
            while True:
                if cancel_check and cancel_check():
                    break

                dispatched = False
                while True:
                    queue_name = _select_queue_for_dispatch()
                    if not queue_name:
                        break

                    item = task_queues[queue_name].popleft()
                    future = executor.submit(_run_task, queue_name, item)
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

                for future in done:
                    queue_name = future_to_queue.pop(future, None)
                    if queue_name is not None and queue_active_counts[queue_name] > 0:
                        queue_active_counts[queue_name] -= 1

                    try:
                        result_queue_name, item, success, result_path, duration = future.result()
                        prev_avg = queue_avg_duration[result_queue_name]
                        queue_avg_duration[result_queue_name] = prev_avg * 0.7 + duration * 0.3
                        file_data = item["file_data"]
                    except Exception:
                        result_queue_name = queue_name or "python_image"
                        file_data = {"path": "", "name": ""}
                        success = False
                        duration = queue_avg_duration[result_queue_name]

                    if success:
                        success_count += 1

                    processed_count += 1
                    if progress_callback:
                        progress_callback(processed_count, total_count, file_data, success)

            # 如果已经取消，不再继续给等待中的排队任务补位；
            # 但已提交的任务允许自然完成并计入已处理进度，使 UI 能反映“真实已完成数”。
            while future_to_queue:
                done, _ = wait(list(future_to_queue.keys()), timeout=0.1, return_when=FIRST_COMPLETED)
                if not done:
                    continue

                for future in done:
                    queue_name = future_to_queue.pop(future, None)
                    if queue_name is not None and queue_active_counts[queue_name] > 0:
                        queue_active_counts[queue_name] -= 1

                    try:
                        result_queue_name, item, success, result_path, duration = future.result()
                        prev_avg = queue_avg_duration[result_queue_name]
                        queue_avg_duration[result_queue_name] = prev_avg * 0.7 + duration * 0.3
                        file_data = item["file_data"]
                    except Exception:
                        result_queue_name = queue_name or "python_image"
                        file_data = {"path": "", "name": ""}
                        success = False

                    if success:
                        success_count += 1

                    processed_count += 1
                    if progress_callback:
                        progress_callback(processed_count, total_count, file_data, success)

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
            new_width, new_height = img.size
            
            # 创建透明背景
            dpi_scaled_background_size = int(self.BASE_SIZE * self.dpi_scale)
            thumbnail = Image.new("RGBA", (dpi_scaled_background_size, dpi_scaled_background_size), (0, 0, 0, 0))
            
            # 居中绘制
            x_offset = (dpi_scaled_background_size - new_width) // 2
            y_offset = (dpi_scaled_background_size - new_height) // 2
            
            # 处理不同模式的图像
            if img.mode == 'RGBA':
                thumbnail.paste(img, (x_offset, y_offset), img)
            elif img.mode == 'P':
                img_converted = img.convert('RGBA')
                thumbnail.paste(img_converted, (x_offset, y_offset), img_converted)
            else:
                img_converted = img.convert('RGBA')
                thumbnail.paste(img_converted, (x_offset, y_offset))
            
            # 保存缩略图
            thumbnail = thumbnail.convert("RGB")
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
                del self._frame_caches[k]
            
            # 获取或创建缓存
            if file_path not in self._frame_caches:
                self._frame_caches[file_path] = VideoFrameCache()
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
    
    def _read_frame_with_retry(self, cap, position: int, use_keyframe: bool = True, max_retries: int = None) -> Optional:
        """
        带重试机制的帧读取
        
        Args:
            cap: OpenCV视频捕获对象
            position: 帧位置（帧索引或0-1之间的比例）
            use_keyframe: 是否优先使用关键帧定位
            max_retries: 最大重试次数，默认使用类配置
            
        Returns:
            Optional: 视频帧，失败返回None
        """
        if max_retries is None:
            max_retries = self.MAX_FRAME_READ_RETRIES
        
        for attempt in range(max_retries):
            try:
                # 根据类型设置位置
                if isinstance(position, float) and 0 <= position <= 1:
                    # 比例位置
                    cap.set(cv2.CAP_PROP_POS_AVI_RATIO, position)
                else:
                    # 帧索引位置
                    if use_keyframe and attempt == 0:
                        # 首次尝试：使用关键帧定位（更快）
                        cap.set(cv2.CAP_PROP_POS_FRAMES, int(position))
                        # 读取关键帧
                        ret, frame = cap.read()
                        if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                            return frame
                        # 关键帧读取失败，继续尝试
                        continue
                    else:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, int(position))
                
                ret, frame = cap.read()
                if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                    return frame
                    
            except Exception as e:
                debug(f"读取视频帧失败 (位置: {position}, 尝试: {attempt + 1}): {e}")
            
            # 短暂延迟后重试
            if attempt < max_retries - 1:
                time.sleep(0.01 * (attempt + 1))
        
        return None
    
    def _create_video_thumbnail(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """
        为视频文件创建缩略图（优化版本）
        
        优化点：
        1. 帧缓存机制 - 避免重复解码相同位置
        2. 关键帧优先定位 - 提高定位速度
        3. 限制重试次数 - 避免无限循环
        4. 并发控制 - 限制同时处理的视频数量
        5. 请求去重 - 避免同时处理同一个视频
        
        Args:
            file_path: 视频文件路径
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 缩略图路径，失败返回None
        """
        if not CV2_AVAILABLE:
            warning("[ThumbnailManager] OpenCV库未安装，无法生成视频缩略图")
            return None
        
        if not PIL_AVAILABLE:
            warning("[ThumbnailManager] PIL库未安装，无法生成视频缩略图")
            return None
        
        # 请求去重：检查是否已有相同视频正在处理
        if not self._try_acquire_video_lock(file_path):
            debug(f"[ThumbnailManager] 视频正在处理中，跳过重复请求: {file_path}")
            return None
        
        try:
            # 并发控制
            with self._video_semaphore:
                return self._create_video_thumbnail_internal(file_path, thumbnail_path)
        finally:
            self._release_video_lock(file_path)
    
    def _create_video_thumbnail_internal(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """内部视频缩略图生成逻辑（带超时控制）"""
        import concurrent.futures

        def _process_video() -> Optional[str]:
            cap = None
            try:
                cap = cv2.VideoCapture(file_path)
                if not cap.isOpened():
                    warning(f"[ThumbnailManager] 无法打开视频文件: {file_path}")
                    return None

                # 获取视频信息
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS)

                # 获取帧缓存
                frame_cache = self._get_or_create_frame_cache(file_path)

                frame = None
                cached_positions = []

                # 定义读取策略（按优先级排序）
                strategies = []

                # 策略1: 优先读取第240帧（跳过可能损坏的开头）
                if total_frames > 240:
                    strategies.append(('frame', 240))

                # 策略2: 读取50%相对位置
                if total_frames > 0:
                    strategies.append(('ratio', 0.5))

                # 策略3: 读取第2帧
                strategies.append(('frame', 2))

                # 策略4: 读取第1帧
                strategies.append(('frame', 1))

                # 策略5: 尝试其他相对位置
                for ratio in [0.03, 0.1, 0.7, 0.9]:
                    strategies.append(('ratio', ratio))

                # 执行策略
                for strategy_type, position in strategies:
                    # 检查缓存
                    cache_key = int(position * 1000) if strategy_type == 'ratio' else position
                    cached_frame = frame_cache.get(cache_key)
                    if cached_frame is not None:
                        frame = cached_frame
                        cached_positions.append(cache_key)
                        debug(f"[ThumbnailManager] 使用缓存帧 (位置: {position})")
                        break

                    # 读取新帧
                    if strategy_type == 'ratio':
                        frame = self._read_frame_with_retry(cap, position, use_keyframe=False)
                    else:
                        frame = self._read_frame_with_retry(cap, position, use_keyframe=True)

                    if frame is not None:
                        # 缓存成功读取的帧
                        frame_cache.put(cache_key, frame)
                        break

                if frame is None:
                    warning(f"[ThumbnailManager] 无法从视频中读取有效帧: {file_path}")
                    return None

                # 处理并保存帧
                return self._process_and_save_video_frame(frame, thumbnail_path)

            except Exception as e:
                error(f"[ThumbnailManager] 生成视频缩略图失败: {file_path}, 错误: {e}")
                return None
            finally:
                # 确保VideoCapture对象被释放
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
                # 强制垃圾回收以释放内存
                import gc
                gc.collect()

        # 使用超时控制执行视频处理
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_process_video)
                return future.result(timeout=self.VIDEO_PROCESSING_TIMEOUT)
        except concurrent.futures.TimeoutError:
            warning(f"[ThumbnailManager] 视频处理超时 ({self.VIDEO_PROCESSING_TIMEOUT}秒): {file_path}")
            return None
        except Exception as e:
            error(f"[ThumbnailManager] 视频处理异常: {file_path}, 错误: {e}")
            return None
    
    def _process_and_save_video_frame(self, frame, thumbnail_path: str) -> Optional[str]:
        """
        处理视频帧并保存为缩略图
        
        Args:
            frame: 视频帧
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 缩略图路径，失败返回None
        """
        frame_pil = None
        thumbnail = None
        downsampled_frame = None
        
        try:
            # 计算原始宽高比
            original_height, original_width = frame.shape[:2]
            aspect_ratio = original_width / original_height
            
            # 检查帧尺寸限制
            if original_width > self.MAX_IMAGE_DIMENSION or original_height > self.MAX_IMAGE_DIMENSION:
                warning(f"[ThumbnailManager] 视频帧尺寸超出限制: {original_width}x{original_height}")
                return None
            
            # 检查像素总数限制
            total_pixels = original_width * original_height
            if total_pixels > self.MAX_IMAGE_PIXELS:
                warning(f"[ThumbnailManager] 视频帧像素数超出限制: {total_pixels} > {self.MAX_IMAGE_PIXELS}")
                return None
            
            # 计算新尺寸
            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
            
            if aspect_ratio > 1:
                new_width = dpi_scaled_size
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = dpi_scaled_size
                new_width = int(new_height * aspect_ratio)
            
            # 对于超大视频帧，先进行适度下采样
            resized_frame = None
            
            if total_pixels > 10000000:
                min_downsample_width = max(new_width * 2, 1024)
                min_downsample_height = max(new_height * 2, 1024)
                
                downsample_ratio = min(
                    original_width / min_downsample_width,
                    original_height / min_downsample_height
                )
                
                if downsample_ratio > 1:
                    downsampled_width = int(original_width / downsample_ratio)
                    downsampled_height = int(original_height / downsample_ratio)
                    downsampled_frame = cv2.resize(
                        frame,
                        (downsampled_width, downsampled_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )
                    resized_frame = cv2.resize(
                        downsampled_frame,
                        (new_width, new_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )
                else:
                    resized_frame = cv2.resize(
                        frame,
                        (new_width, new_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )
            else:
                resized_frame = cv2.resize(
                    frame,
                    (new_width, new_height),
                    interpolation=cv2.INTER_LANCZOS4
                )
            
            # 转换为PIL图像
            frame_pil = Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB))
            
            # 检查PIL图像尺寸限制
            if not self._check_image_size_limit(frame_pil):
                return None
            
            # 创建透明背景
            dpi_scaled_background_size = int(self.BASE_SIZE * self.dpi_scale)
            thumbnail = Image.new(
                "RGBA",
                (dpi_scaled_background_size, dpi_scaled_background_size),
                (0, 0, 0, 0)
            )
            
            # 居中绘制
            x_offset = (dpi_scaled_background_size - new_width) // 2
            y_offset = (dpi_scaled_background_size - new_height) // 2
            thumbnail.paste(frame_pil, (x_offset, y_offset))
            
            # 保存缩略图
            thumbnail = thumbnail.convert("RGB")
            thumbnail.save(thumbnail_path, format='JPEG', quality=self.QUALITY)
            
            debug(f"[ThumbnailManager] 视频缩略图生成成功: {thumbnail_path}")
            return thumbnail_path
            
        except Exception as e:
            error(f"[ThumbnailManager] 处理视频帧失败: {e}")
            return None
        finally:
            # 确保所有Image对象都被关闭
            if frame_pil is not None:
                try:
                    frame_pil.close()
                except Exception:
                    pass
            if thumbnail is not None:
                try:
                    thumbnail.close()
                except Exception:
                    pass
            # 清理临时变量
            downsampled_frame = None
            resized_frame = None
            import gc
            gc.collect()
    
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
        
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QImage, QPainter
            from PySide6.QtCore import Qt
            
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
]
