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
import re
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple, Callable, Dict, Set, List, Union
from pathlib import Path
from dataclasses import dataclass
from freeassetfilter.core.media_probe import get_ffmpeg_path, get_ffprobe_path
from freeassetfilter.core.rust_thumbnail_bridge import RustThumbnailBridge
from freeassetfilter.core.image_color_utils import load_raw_image, normalize_pil_image

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.perf_metrics import (
    increment_perf_counter,
    set_perf_metadata,
    track_perf,
)

# 尝试导入PIL库
PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    warning("PIL库未安装，缩略图功能受限")


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


@dataclass
class SvgRenderCacheEntry:
    """SVG 渲染缓存条目"""
    image: any
    mtime: float
    last_validated_at: float


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
    DEFAULT_NATIVE_BATCH_WORKERS_IMAGE = 3
    DEFAULT_NATIVE_BATCH_WORKERS_VIDEO = 1
    DEFAULT_PYTHON_BATCH_WORKERS_VIDEO = 2

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
    MAX_SVG_CACHE_ENTRIES = 256
    SVG_CACHE_REVALIDATE_INTERVAL_SECONDS = 1.0
    PATH_EXISTS_CACHE_TTL_SECONDS = 1.0

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
        self._available_hwaccels: List[str] = []
        self._native_batch_workers_image = self._get_native_batch_workers_image()
        self._native_batch_workers_video = self._get_native_batch_workers_video()
        self._python_batch_workers_video = self._get_python_batch_workers_video()
        if self._rust_bridge.available:
            self._rust_bridge.set_cache_limit(self._native_cache_limit)
            self._available_hwaccels = self._rust_bridge.get_available_hwaccels()
            self._rust_bridge.set_max_concurrent_hw_video_decodes(self._native_batch_workers_video)

        # 父进程聚合子进程 stderr 中的解码路径日志，
        # 解决“批量视频在子进程执行而父进程内 Rust decode_stats 为 0”的统计缺口。
        self._subprocess_decode_stats_lock = threading.Lock()
        self._subprocess_decode_stats = self._make_empty_subprocess_decode_stats()

        # SVG 渲染缓存：file_path -> SvgRenderCacheEntry
        self._svg_render_cache: OrderedDict[str, SvgRenderCacheEntry] = OrderedDict()
        self._svg_cache_lock = threading.Lock()
        self._path_exists_cache: Dict[str, Tuple[bool, float]] = {}
        self._path_exists_cache_lock = threading.Lock()
        set_perf_metadata("thumbnail.load_svg_image", "max_entries", self.MAX_SVG_CACHE_ENTRIES)
        set_perf_metadata(
            "thumbnail.load_svg_image",
            "revalidate_interval_ms",
            int(self.SVG_CACHE_REVALIDATE_INTERVAL_SECONDS * 1000),
        )

        # 正在处理的视频文件集合（用于请求去重）
        self._processing_videos: Set[str] = set()
        self._processing_lock = threading.Lock()

        # 进程内直连视频解码限流：
        # 批量模式下的视频任务已经通过“1条硬解队列 + 2条软解队列 + 子进程隔离”调度，
        # 这里仅限制非批量直连路径，避免同一进程内过多软解任务争抢资源。
        self._video_semaphore = threading.Semaphore(1)

        debug(
            f"初始化完成: thumb_dir={self._thumb_dir}, "
            f"img_workers={self._native_batch_workers_image}, "
            f"video_workers={self._native_batch_workers_video}, "
            f"hwaccels={self._available_hwaccels}"
        )

    def _get_cpu_count_safe(self) -> int:
        """安全获取 CPU 核心数"""
        return max(1, int(os.cpu_count() or 1))

    def _get_native_batch_workers_image(self) -> int:
        """按 CPU 核心数动态计算原生图片批处理并发数"""
        cpu_count = self._get_cpu_count_safe()
        return max(1, cpu_count)

    def _get_native_batch_workers_video(self) -> int:
        """按硬解后端数量做更积极的启发式估算，避免仅按后端类型数导致硬件利用率偏低"""
        cpu_count = self._get_cpu_count_safe()
        if not self._rust_bridge.available:
            return self.DEFAULT_NATIVE_BATCH_WORKERS_VIDEO

        try:
            hwaccels = self._rust_bridge.get_available_hwaccels()
        except Exception:
            hwaccels = []

        detected_count = len([name for name in hwaccels if name])
        if detected_count <= 0:
            return self.DEFAULT_NATIVE_BATCH_WORKERS_VIDEO

        # “可用硬解后端数”通常小于“可承载的并行硬解会话数”，
        # 因此这里使用更积极的估算：以后端数 * 2 作为基础并发，
        # 再受 CPU 核数与安全上限共同约束，避免保守到吃不满硬件。
        estimated_workers = detected_count * 2
        cpu_cap = max(1, cpu_count - 1)
        safe_cap = 8
        return max(1, min(estimated_workers, cpu_cap, safe_cap))

    def _get_python_batch_workers_video(self) -> int:
        """按 CPU 核心数减 1 计算软解并发数，为主线程保留一个核心"""
        cpu_count = self._get_cpu_count_safe()
        return max(1, cpu_count - 1)

    def _make_empty_subprocess_decode_stats(self) -> Dict[str, int]:
        """创建父进程侧的子进程视频解码路径聚合统计结构"""
        return {
            "submitted": 0,
            "decode_path_lines": 0,
            "hw_verified": 0,
            "hw_unverified": 0,
            "software": 0,
            "software_fallback": 0,
            "d3d11va": 0,
            "dxva2": 0,
            "qsv": 0,
            "unknown_hw_mode": 0,
        }

    @staticmethod
    def _close_pil_image_quietly(image) -> None:
        """安静关闭 PIL 图像对象。"""
        if image is None:
            return
        try:
            image.close()
        except Exception:
            pass

    def _get_cached_path_exists(self, path: str, force_refresh: bool = False) -> bool:
        """带短 TTL 的存在性缓存，减少热路径重复查盘。"""
        if not path:
            return False

        now = time.monotonic()
        ttl = max(0.0, float(self.PATH_EXISTS_CACHE_TTL_SECONDS))

        if not force_refresh:
            with self._path_exists_cache_lock:
                cached_entry = self._path_exists_cache.get(path)
            if cached_entry is not None:
                exists, cached_at = cached_entry
                if ttl <= 0 or (now - cached_at) <= ttl:
                    return exists

        exists = os.path.exists(path)
        with self._path_exists_cache_lock:
            self._path_exists_cache[path] = (exists, now)
        return exists

    def _set_cached_path_exists(self, path: str, exists: bool) -> None:
        """显式更新存在性缓存。"""
        if not path:
            return
        with self._path_exists_cache_lock:
            self._path_exists_cache[path] = (exists, time.monotonic())

    def _clear_path_exists_cache(self) -> None:
        """清空存在性缓存。"""
        with self._path_exists_cache_lock:
            self._path_exists_cache.clear()

    def _get_existing_thumbnail_path_from_paths(
        self,
        thumbnail_path: str,
        legacy_thumbnail_path: str,
    ) -> Optional[str]:
        """返回当前存在的缩略图路径，优先主格式，其次兼容旧格式。"""
        if self._get_cached_path_exists(thumbnail_path):
            return thumbnail_path
        if self._get_cached_path_exists(legacy_thumbnail_path):
            return legacy_thumbnail_path
        return None

    def _set_svg_cache_metadata_locked(self) -> None:
        """更新 SVG 缓存当前容量指标。调用方需持有 SVG 缓存锁。"""
        set_perf_metadata("thumbnail.load_svg_image", "current_entries", len(self._svg_render_cache))

    def _pop_svg_cache_entry_locked(self, file_path: str) -> Optional[SvgRenderCacheEntry]:
        """弹出 SVG 缓存条目并释放缓存图像。调用方需持有 SVG 缓存锁。"""
        entry = self._svg_render_cache.pop(file_path, None)
        if entry is not None:
            self._close_pil_image_quietly(entry.image)
        return entry

    def _get_cached_svg_image(self, file_path: str):
        """优先走热缓存命中，仅在冷命中时重新校验 mtime。"""
        event_name = "thumbnail.load_svg_image"
        now = time.monotonic()

        with self._svg_cache_lock:
            entry = self._svg_render_cache.get(file_path)
            if entry is None:
                increment_perf_counter(event_name, "cache_miss")
                self._set_svg_cache_metadata_locked()
                return None

            if now - entry.last_validated_at < self.SVG_CACHE_REVALIDATE_INTERVAL_SECONDS:
                self._svg_render_cache.move_to_end(file_path)
                increment_perf_counter(event_name, "cache_hit")
                increment_perf_counter(event_name, "hot_cache_hit")
                self._set_svg_cache_metadata_locked()
                return entry.image.copy()

        try:
            current_mtime = os.path.getmtime(file_path)
        except OSError:
            increment_perf_counter(event_name, "stat_failure")
            with self._svg_cache_lock:
                if self._pop_svg_cache_entry_locked(file_path) is not None:
                    increment_perf_counter(event_name, "stat_invalidated")
                increment_perf_counter(event_name, "cache_miss")
                self._set_svg_cache_metadata_locked()
            return None

        with self._svg_cache_lock:
            entry = self._svg_render_cache.get(file_path)
            if entry is None:
                increment_perf_counter(event_name, "cache_miss")
                self._set_svg_cache_metadata_locked()
                return None

            if entry.mtime != current_mtime:
                self._pop_svg_cache_entry_locked(file_path)
                increment_perf_counter(event_name, "stale_invalidated")
                increment_perf_counter(event_name, "cache_miss")
                self._set_svg_cache_metadata_locked()
                return None

            entry.last_validated_at = now
            self._svg_render_cache.move_to_end(file_path)
            increment_perf_counter(event_name, "cache_hit")
            increment_perf_counter(event_name, "revalidated_cache_hit")
            self._set_svg_cache_metadata_locked()
            return entry.image.copy()

    def _store_svg_cache_image(self, file_path: str, img) -> None:
        """缓存 SVG 渲染结果，并维护 LRU 淘汰。"""
        event_name = "thumbnail.load_svg_image"

        try:
            file_mtime = os.path.getmtime(file_path)
        except OSError:
            increment_perf_counter(event_name, "store_stat_failure")
            return

        cached_copy = img.copy()
        now = time.monotonic()

        with self._svg_cache_lock:
            self._pop_svg_cache_entry_locked(file_path)
            self._svg_render_cache[file_path] = SvgRenderCacheEntry(
                image=cached_copy,
                mtime=file_mtime,
                last_validated_at=now,
            )

            while len(self._svg_render_cache) > self.MAX_SVG_CACHE_ENTRIES:
                _, evicted_entry = self._svg_render_cache.popitem(last=False)
                self._close_pil_image_quietly(evicted_entry.image)
                increment_perf_counter(event_name, "cache_eviction")

            self._set_svg_cache_metadata_locked()

    def _shutdown_thumbnail_batch_executor_async(
        self,
        executor: ThreadPoolExecutor,
        *,
        cancel_futures: bool,
        reason: str,
    ) -> None:
        """在守护线程中回收线程池，避免当前调用线程卡在 shutdown(wait=True)。"""

        def _shutdown() -> None:
            try:
                executor.shutdown(wait=True, cancel_futures=cancel_futures)
            except Exception as exc:
                warning(f"异步关闭缩略图线程池失败({reason}): {exc}")

        cleanup_thread = threading.Thread(
            target=_shutdown,
            name=f"thumb_batch_shutdown_{reason}",
            daemon=True,
        )
        cleanup_thread.start()

    def _reset_subprocess_decode_stats(self) -> None:
        """重置父进程聚合的子进程视频解码路径统计"""
        with self._subprocess_decode_stats_lock:
            self._subprocess_decode_stats = self._make_empty_subprocess_decode_stats()

    def _get_subprocess_decode_stats(self) -> Dict[str, int]:
        """获取父进程聚合的子进程视频解码路径统计快照"""
        with self._subprocess_decode_stats_lock:
            return dict(self._subprocess_decode_stats)

    def _record_subprocess_decode_stats(self, stderr_text: str) -> str:
        """解析子进程 stderr 中的 decode path 日志并累加统计。

        Returns:
            str: 过滤掉 decode path 行后的剩余 stderr 文本
        """
        if not stderr_text:
            return ""

        remaining_lines: List[str] = []
        decode_path_detected = False

        for raw_line in stderr_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if "[thumbnail_generator] decode path " not in line:
                remaining_lines.append(raw_line)
                continue

            decode_path_detected = True

            mode_match = re.search(r"\bmode=([^\s]+)", line)
            verified_match = re.search(r"\bverified_hw=([^\s]+)", line)
            fallback_match = re.search(r"\bsoftware_fallback=([^\s]+)", line)

            mode = mode_match.group(1).strip().lower() if mode_match else "software"
            verified_hw = verified_match.group(1).strip().lower() == "true" if verified_match else False
            software_fallback = fallback_match.group(1).strip().lower() == "true" if fallback_match else False

            with self._subprocess_decode_stats_lock:
                self._subprocess_decode_stats["decode_path_lines"] += 1

                if software_fallback:
                    self._subprocess_decode_stats["software_fallback"] += 1

                if mode == "software":
                    self._subprocess_decode_stats["software"] += 1
                    continue

                if verified_hw:
                    self._subprocess_decode_stats["hw_verified"] += 1
                else:
                    self._subprocess_decode_stats["hw_unverified"] += 1

                if mode == "d3d11va":
                    self._subprocess_decode_stats["d3d11va"] += 1
                elif mode == "dxva2":
                    self._subprocess_decode_stats["dxva2"] += 1
                elif mode == "qsv":
                    self._subprocess_decode_stats["qsv"] += 1
                else:
                    self._subprocess_decode_stats["unknown_hw_mode"] += 1

        if decode_path_detected:
            return "\n".join(line for line in remaining_lines if line.strip())

        return stderr_text

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
        with track_perf("thumbnail.get_existing_thumbnail_path"):
            thumbnail_path = self.get_thumbnail_path(file_path)
            legacy_path = self.get_legacy_thumbnail_path(file_path)
            existing = self._get_existing_thumbnail_path_from_paths(thumbnail_path, legacy_path)
            if existing:
                increment_perf_counter("thumbnail.get_existing_thumbnail_path", "cache_hit")
                return existing

            increment_perf_counter("thumbnail.get_existing_thumbnail_path", "cache_miss")
            return None

    def has_thumbnail(self, file_path: str) -> bool:
        """
        检查文件是否已有缩略图

        Args:
            file_path: 原始文件路径

        Returns:
            bool: 是否存在缩略图
        """
        with track_perf("thumbnail.has_thumbnail"):
            exists = self.get_existing_thumbnail_path(file_path) is not None
            increment_perf_counter(
                "thumbnail.has_thumbnail",
                "cache_hit" if exists else "cache_miss",
            )
            return exists

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
            warning(f"图像尺寸超限: {width}x{height}")
            return False
        if width * height > self.MAX_IMAGE_PIXELS:
            warning(f"图像像素超限: {width * height}")
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
                    self._set_cached_path_exists(file_path, False)
                    deleted_count += 1
                    remaining_size -= file_size
                    remaining_count -= 1
                except (OSError, IOError) as e:
                    debug(f"删除缓存文件失败 {file_path}: {e}")

            if deleted_count > 0:
                debug(f"缓存清理: 删除{deleted_count}个, 剩余{max(remaining_count, 0)}个")

        except Exception as e:
            warning(f"检查缓存限制失败: {e}")

    def create_thumbnail(self, file_path: str, force_regenerate: bool = False) -> Optional[str]:
        """
        为文件创建缩略图

        Args:
            file_path: 文件路径
            force_regenerate: 是否强制重新生成，即使缩略图已存在

        Returns:
            Optional[str]: 缩略图路径，生成失败返回None
        """
        with track_perf("thumbnail.create_thumbnail"):
            if not self._get_cached_path_exists(file_path):
                increment_perf_counter("thumbnail.create_thumbnail", "missing_source")
                warning(f"文件不存在: {file_path}")
                return None

            thumbnail_path = self.get_thumbnail_path(file_path)
            legacy_thumbnail_path = self.get_legacy_thumbnail_path(file_path)

            # 如果缩略图已存在且不强制重新生成，优先返回 JPG，其次兼容历史 PNG
            if not force_regenerate:
                existing = self._get_existing_thumbnail_path_from_paths(thumbnail_path, legacy_thumbnail_path)
                if existing:
                    increment_perf_counter("thumbnail.create_thumbnail", "cache_hit")
                    self._update_file_access_time(existing)
                    return existing

            increment_perf_counter("thumbnail.create_thumbnail", "cache_miss")

            # 检查是否为媒体文件
            if not self.is_media_file(file_path):
                increment_perf_counter("thumbnail.create_thumbnail", "non_media_skipped")
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
                    increment_perf_counter("thumbnail.create_thumbnail", "python_fallback")
                    if self.is_image_file(file_path):
                        result = self._create_image_thumbnail(file_path, thumbnail_path)
                    elif self.is_video_file(file_path):
                        result = self._create_video_thumbnail(file_path, thumbnail_path)
                    else:
                        result = None

                # 如果成功生成，更新访问时间
                if result and self._get_cached_path_exists(result, force_refresh=True):
                    self._set_cached_path_exists(result, True)
                    increment_perf_counter("thumbnail.create_thumbnail", "success")
                    self._update_file_access_time(result)
                else:
                    increment_perf_counter("thumbnail.create_thumbnail", "failure")

                return result
            except Exception as e:
                increment_perf_counter("thumbnail.create_thumbnail", "failure")
                error(f"[ThumbnailManager] 生成缩略图失败: {file_path}, 错误: {e}")

            return None

    def create_thumbnails_batch(
        self,
        files_to_generate: List[Union[str, Dict]],
        progress_callback: Optional[Callable[[int, int, Union[str, Dict], bool], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> Tuple[int, int]:
        """
        批量创建缩略图（异步多队列 + 原生批处理版）。

        参数：
            files_to_generate: 待生成缩略图的文件列表，兼容字符串路径列表与包含 path/file_path 字段的字典列表。
            progress_callback: 单文件完成后的进度回调，回调参数依次为当前完成数、总数、原始文件项、是否成功。
            cancel_check: 取消检查函数，返回 True 时停止继续投递新任务。

        返回值：
            Tuple[int, int]: 成功数量与已处理数量。

        异常场景：
            函数内部会吞掉单文件处理异常，确保批处理流程不中断。

        调度目标：
        1. 原生图片/视频优先走 Rust 批量接口，减少 Python<->Rust 往返与进程调度开销；
        2. Python 专用链路（RAW/PSD/SVG / OpenCV回退）保持单项异步；
        3. 进度仍按“单文件完成”逐项回调，兼顾 UI 感知；
        4. 支持取消，取消后不再补位，但已提交批次允许自然完成。
        """
        total_count = len(files_to_generate)
        if total_count == 0:
            return 0, 0

        set_perf_metadata("thumbnail.create_thumbnails_batch", "native_bridge_available", self._rust_bridge.available)
        increment_perf_counter("thumbnail.create_thumbnails_batch", "batch_invocations")

        success_count = 0
        processed_count = 0

        native_stats_enabled = self._rust_bridge.available
        video_decode_submitted_count = 0
        self._reset_subprocess_decode_stats()
        if native_stats_enabled:
            self._rust_bridge.reset_decode_stats()

        queue_limits = {
            "native_image": self._native_batch_workers_image,
            # 视频任务并发基于已探测到的可用硬解后端数量做启发式估算，
            # 并同步下发到 Rust 原生层的硬解槽位限制中，避免过度保守。
            "native_video": self._native_batch_workers_video,
            "python_image": max(1, min(2, self._get_cpu_count_safe() // 2 or 1)),
            # 软解并发按 CPU 核心数 - 1，为 UI / 主线程保留一个核心。
            "python_video": self._python_batch_workers_video,
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

                success = bool(result_path and self._get_cached_path_exists(result_path, force_refresh=True))
                if success:
                    self._set_cached_path_exists(result_path, True)
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
                warning(f"Rust批量生成失败，逐项回退: {e}")
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
                        self._set_cached_path_exists(thumbnail_path, True)
                    else:
                        result_path = self._create_native_thumbnail(file_path, thumbnail_path, legacy_thumbnail_path)
                        if result_path is None:
                            if queue_name == "native_video":
                                result_path = self._create_video_thumbnail_ffmpeg(file_path, thumbnail_path)
                            else:
                                result_path = self._create_image_thumbnail(file_path, legacy_thumbnail_path)

                    success = bool(result_path and self._get_cached_path_exists(result_path, force_refresh=True))
                    if success:
                        self._set_cached_path_exists(result_path, True)
                        self._update_file_access_time(result_path)
                except Exception:
                    success = False
                    result_path = None

                outputs.append((item, success, result_path))

            duration = time.perf_counter() - start_time
            return queue_name, outputs, duration

        def _normalize_batch_file_data(file_data: Union[str, Dict]) -> Tuple[str, Union[str, Dict]]:
            """标准化批量任务输入，统一提取文件路径并保留原始回调对象。"""
            if isinstance(file_data, str):
                return file_data, file_data
            if isinstance(file_data, dict):
                file_path = file_data.get("path") or file_data.get("file_path") or ""
                return file_path, file_data
            return "", file_data

        info(f"开始批量生成缩略图: total={total_count}")
        with track_perf("thumbnail.create_thumbnails_batch"):
            for file_data in files_to_generate:
                if cancel_check and cancel_check():
                    break

                file_path, callback_file_data = _normalize_batch_file_data(file_data)
                if not file_path or not self._get_cached_path_exists(file_path):
                    increment_perf_counter("thumbnail.create_thumbnails_batch", "missing_source")
                    processed_count += 1
                    if progress_callback:
                        progress_callback(processed_count, total_count, callback_file_data, False)
                    continue

                thumbnail_path = self.get_thumbnail_path(file_path)
                legacy_thumbnail_path = self.get_legacy_thumbnail_path(file_path)
                existing = self._get_existing_thumbnail_path_from_paths(thumbnail_path, legacy_thumbnail_path)

                if existing:
                    increment_perf_counter("thumbnail.create_thumbnails_batch", "cache_hit")
                    self._update_file_access_time(existing)
                    success_count += 1
                    processed_count += 1
                    if progress_callback:
                        progress_callback(processed_count, total_count, callback_file_data, True)
                    continue

                increment_perf_counter("thumbnail.create_thumbnails_batch", "cache_miss")

                suffix = os.path.splitext(file_path)[1].lower()
                is_video_file = suffix in self.VIDEO_FORMATS
                use_python_dedicated = (
                    suffix in self.RAW_FORMATS
                    or suffix in self.PSD_FORMATS
                    or suffix == '.svg'
                )

                item = {
                    "file_data": callback_file_data,
                    "file_path": file_path,
                    "thumbnail_path": thumbnail_path,
                    "legacy_thumbnail_path": legacy_thumbnail_path,
                }

                if is_video_file:
                    increment_perf_counter("thumbnail.create_thumbnails_batch", "video_submitted")
                    video_decode_submitted_count += 1
                    if self._rust_bridge.available:
                        native_load = len(task_queues["native_video"]) / max(1, queue_limits["native_video"])
                        python_load = len(task_queues["python_video"]) / max(1, queue_limits["python_video"])
                        if native_load <= python_load:
                            increment_perf_counter("thumbnail.create_thumbnails_batch", "queue_native_video")
                            task_queues["native_video"].append(item)
                        else:
                            increment_perf_counter("thumbnail.create_thumbnails_batch", "queue_python_video")
                            task_queues["python_video"].append(item)
                    else:
                        increment_perf_counter("thumbnail.create_thumbnails_batch", "queue_python_video")
                        task_queues["python_video"].append(item)
                elif self._rust_bridge.available and not use_python_dedicated:
                    increment_perf_counter("thumbnail.create_thumbnails_batch", "queue_native_image")
                    task_queues["native_image"].append(item)
                else:
                    increment_perf_counter("thumbnail.create_thumbnails_batch", "queue_python_image")
                    task_queues["python_image"].append(item)

        max_workers = sum(queue_limits.values())

        def _has_pending_tasks() -> bool:
            return any(task_queues[name] for name in task_queues)

        def _get_effective_queue_limit(queue_name: str) -> int:
            """获取队列当前可用的动态上限。

            - native_video 保持硬上限，避免突破 Rust 原生硬解槽位；
            - 其他队列可借用“当前无待处理任务”的空闲队列额度，
              避免高效队列等待低效队列释放基础配额。
            """
            base_limit = max(1, queue_limits[queue_name])

            if queue_name == "native_video":
                return base_limit

            borrowed_capacity = 0
            for other_name in queue_limits:
                if other_name == queue_name:
                    continue
                if task_queues[other_name]:
                    continue
                idle_slots = max(0, queue_limits[other_name] - queue_active_counts[other_name])
                borrowed_capacity += idle_slots

            return max(1, min(max_workers, base_limit + borrowed_capacity))

        def _get_dispatch_backlog(queue_name: str) -> int:
            """获取调度视角下的有效 backlog。

            - python_video 可接管 native_video 的积压任务，避免软解线程空转；
            - native_video 在自身空闲时，也可接管 python_video 的待处理任务，
              避免硬解线程提前跑空后闲置。
            """
            backlog = len(task_queues[queue_name])

            if queue_name == "python_video" and backlog == 0:
                native_video_backlog = len(task_queues["native_video"])
                native_video_capacity = max(1, queue_limits["native_video"])
                native_video_overflow = max(0, native_video_backlog - native_video_capacity)
                backlog += native_video_overflow

            if queue_name == "native_video" and backlog == 0:
                backlog += len(task_queues["python_video"])

            return backlog

        def _select_queue_for_dispatch() -> Optional[str]:
            candidate_name = None
            candidate_score = None
            total_active = sum(queue_active_counts.values())

            for name in queue_order:
                backlog = _get_dispatch_backlog(name)
                if backlog <= 0:
                    continue

                effective_limit = _get_effective_queue_limit(name)
                if queue_active_counts[name] >= effective_limit:
                    continue
                if total_active >= max_workers:
                    continue

                active = queue_active_counts[name]
                avg_duration = max(queue_avg_duration[name], 0.05)
                batch_size = max(1, queue_batch_sizes.get(name, 1))

                score = ((backlog * batch_size) / (active + 1)) * (1.0 + min(avg_duration, 5.0))

                if name in ("native_video", "python_video"):
                    score *= 1.25

                # 对能够借用空闲额度的队列给予轻微倾斜，减少“快队列等待慢队列”。
                if effective_limit > queue_limits[name]:
                    score *= 1.1

                # 当 python_video 正在接管 native_video 积压任务时，进一步提升其优先级，
                # 避免出现“软解线程空闲但仍等待硬解队列慢速消费”的情况。
                if name == "python_video" and not task_queues["python_video"] and len(task_queues["native_video"]) > queue_limits["native_video"]:
                    score *= 1.2

                # 当 native_video 自身已空，但 python_video 仍有积压时，
                # 允许硬解线程主动继续吃任务，避免“硬解先完成后空闲”。
                if name == "native_video" and not task_queues["native_video"] and task_queues["python_video"]:
                    score *= 1.15

                if candidate_score is None or score > candidate_score:
                    candidate_name = name
                    candidate_score = score

            return candidate_name

        def _pop_batch_items_for_queue(queue_name: str, batch_size: int) -> List[Dict]:
            """按调度策略为目标队列取出待执行任务。"""
            batch_items: List[Dict] = []

            while task_queues[queue_name] and len(batch_items) < batch_size:
                batch_items.append(task_queues[queue_name].popleft())

            # python_video 允许从 native_video 中接管超出硬解并发能力的积压任务
            if queue_name == "python_video" and len(batch_items) < batch_size:
                native_video_capacity = max(1, queue_limits["native_video"])
                while (
                    len(batch_items) < batch_size
                    and len(task_queues["native_video"]) > native_video_capacity
                ):
                    batch_items.append(task_queues["native_video"].popleft())

            # native_video 在自身队列耗尽时，允许继续接管 python_video 的待处理任务，
            # 避免硬解线程提前空闲。
            if queue_name == "native_video" and len(batch_items) < batch_size:
                while task_queues["python_video"] and len(batch_items) < batch_size:
                    batch_items.append(task_queues["python_video"].popleft())

            return batch_items

        info(
            f"队列统计: native_video={len(task_queues['native_video'])}, "
            f"python_video={len(task_queues['python_video'])}, "
            f"native_image={len(task_queues['native_image'])}, "
            f"python_image={len(task_queues['python_image'])}"
        )

        future_to_queue = {}
        completed_signal = threading.Event()
        cancelled = False

        def _mark_future_completed(_future) -> None:
            completed_signal.set()

        def _consume_completed_futures(done_futures) -> None:
            nonlocal success_count, processed_count

            consumed_any = False
            for future in done_futures:
                queue_name = future_to_queue.pop(future, None)
                if queue_name is None:
                    continue

                consumed_any = True
                if queue_active_counts[queue_name] > 0:
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

            if consumed_any and not future_to_queue:
                completed_signal.clear()

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
                    batch_items = _pop_batch_items_for_queue(queue_name, batch_size)

                    if not batch_items:
                        break

                    if queue_name.startswith("native_") and len(batch_items) > 1:
                        # debug(f"提交原生批量任务: queue={queue_name}, batch_size={len(batch_items)}")
                        future = executor.submit(_run_native_batch_task, queue_name, batch_items)
                    else:
                        # debug(f"提交单项任务: queue={queue_name}, file={batch_items[0]['file_path']}")
                        future = executor.submit(_run_single_task, queue_name, batch_items[0])

                    future.add_done_callback(_mark_future_completed)
                    future_to_queue[future] = queue_name
                    queue_active_counts[queue_name] += 1
                    dispatched = True

                if not future_to_queue:
                    if not _has_pending_tasks():
                        break
                    continue

                done_now = [future for future in list(future_to_queue.keys()) if future.done()]
                if done_now:
                    _consume_completed_futures(done_now)
                    continue

                if dispatched:
                    continue

                completed_signal.wait(timeout=0.1)
                completed_signal.clear()

                done_now = [future for future in list(future_to_queue.keys()) if future.done()]
                if done_now:
                    _consume_completed_futures(done_now)

            if not cancelled:
                while future_to_queue:
                    done_now = [future for future in list(future_to_queue.keys()) if future.done()]
                    if done_now:
                        _consume_completed_futures(done_now)
                        continue

                    completed_signal.wait(timeout=0.1)
                    completed_signal.clear()
            else:
                done_now = [future for future in list(future_to_queue.keys()) if future.done()]
                if done_now:
                    _consume_completed_futures(done_now)
        finally:
            remaining_futures = list(future_to_queue.keys())
            if cancelled:
                for future in remaining_futures:
                    future.cancel()
                if remaining_futures:
                    debug(f"批量生成取消后转异步关闭线程池: remaining={len(remaining_futures)}")
                    self._shutdown_thumbnail_batch_executor_async(
                        executor,
                        cancel_futures=True,
                        reason="cancelled",
                    )
                else:
                    executor.shutdown(wait=False, cancel_futures=True)
            else:
                if remaining_futures:
                    warning(f"批量生成结束时仍有未完成任务，转异步关闭线程池: remaining={len(remaining_futures)}")
                    self._shutdown_thumbnail_batch_executor_async(
                        executor,
                        cancel_futures=False,
                        reason="drain",
                    )
                else:
                    executor.shutdown(wait=False)

        increment_perf_counter("thumbnail.create_thumbnails_batch", "processed", processed_count)
        increment_perf_counter("thumbnail.create_thumbnails_batch", "success", success_count)
        increment_perf_counter("thumbnail.create_thumbnails_batch", "failure", max(0, processed_count - success_count))
        if cancelled:
            increment_perf_counter("thumbnail.create_thumbnails_batch", "cancelled")
        set_perf_metadata("thumbnail.create_thumbnails_batch", "last_total_count", total_count)
        set_perf_metadata("thumbnail.create_thumbnails_batch", "last_processed_count", processed_count)
        set_perf_metadata("thumbnail.create_thumbnails_batch", "last_success_count", success_count)

        info(f"批量生成结束: success={success_count}, processed={processed_count}")

        subprocess_stats = self._get_subprocess_decode_stats()
        subprocess_stats["submitted"] = int(video_decode_submitted_count)

        if video_decode_submitted_count > 0:
            total_hw_modes = (
                int(subprocess_stats.get("d3d11va", 0))
                + int(subprocess_stats.get("dxva2", 0))
                + int(subprocess_stats.get("qsv", 0))
                + int(subprocess_stats.get("unknown_hw_mode", 0))
            )
            total_soft_modes = int(subprocess_stats.get("software", 0))
            total_decode_path_lines = int(subprocess_stats.get("decode_path_lines", 0))
            total_decode_events = total_hw_modes + total_soft_modes
            verified_hw = int(subprocess_stats.get("hw_verified", 0))
            fallback_count = int(subprocess_stats.get("software_fallback", 0))
            subprocess_hw_hit_rate = (verified_hw / total_decode_events * 100.0) if total_decode_events > 0 else 0.0

            info(
                f"子进程解码统计: hw={verified_hw}, "
                f"hw_rate={subprocess_hw_hit_rate:.1f}%, "
                f"sw={total_soft_modes}, fallback={fallback_count}"
            )

            if total_decode_path_lines == 0:
                info("子进程未采集到decode path日志")

        if native_stats_enabled:
            stats = self._rust_bridge.get_decode_stats() or {}
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
                f"Rust解码统计: hw={hw_hits}/{hw_attempts}, "
                f"hw_rate={hw_hit_rate:.1f}%, sw={sw_hits}/{sw_attempts}, fallback={sw_fallbacks}"
            )

            if video_decode_submitted_count > 0 and hw_attempts == 0 and sw_attempts == 0:
                info("批量视频在子进程执行，父进程Rust统计为0")

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
        with track_perf("thumbnail.create_native_thumbnail"):
            if not self._rust_bridge.available:
                increment_perf_counter("thumbnail.create_native_thumbnail", "bridge_unavailable")
                return None

            try:
                dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)

                # 优先使用 Rust 直接 JPG 输出，降低磁盘 IO 与批量预览开销
                jpg_bytes = self._rust_bridge.generate_jpg(file_path, dpi_scaled_size, dpi_scaled_size)
                if jpg_bytes:
                    increment_perf_counter("thumbnail.create_native_thumbnail", "jpg_direct")
                    with open(thumbnail_path, "wb") as f:
                        f.write(jpg_bytes)
                    # debug(f"Rust(JPG)生成成功: {thumbnail_path}")
                    return thumbnail_path

                # 回退到 Rust JPEG 输出（兼容别名接口）
                jpeg_bytes = self._rust_bridge.generate_jpeg(file_path, dpi_scaled_size, dpi_scaled_size)
                if jpeg_bytes:
                    increment_perf_counter("thumbnail.create_native_thumbnail", "jpeg_direct")
                    with open(thumbnail_path, "wb") as f:
                        f.write(jpeg_bytes)
                    # debug(f"Rust(JPEG)生成成功: {thumbnail_path}")
                    return thumbnail_path

                # 回退到 RGBA 路径
                if not PIL_AVAILABLE:
                    increment_perf_counter("thumbnail.create_native_thumbnail", "pil_unavailable")
                    return None

                generated = self._rust_bridge.generate_rgba(file_path, dpi_scaled_size, dpi_scaled_size)
                if not generated:
                    increment_perf_counter("thumbnail.create_native_thumbnail", "rgba_fallback_miss")
                    return None

                raw, width, height, channels = generated
                if channels not in (3, 4):
                    increment_perf_counter("thumbnail.create_native_thumbnail", "invalid_channels")
                    return None

                increment_perf_counter("thumbnail.create_native_thumbnail", "rgba_fallback")
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

                # debug(f"Rust(RGBA)生成成功: {thumbnail_path}")
                return thumbnail_path
            except Exception as e:
                increment_perf_counter("thumbnail.create_native_thumbnail", "failure")
                warning(f"Rust生成失败，回退Python: {file_path}, {e}")
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
            warning("PIL未安装，无法生成图片缩略图")
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

            # debug(f"图片缩略图生成成功: {thumbnail_path}")
            return thumbnail_path

        except Exception as e:
            warning(f"生成图片缩略图失败: {file_path}, {e}")
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
            # debug(f"视频正在处理中，跳过重复请求: {file_path}")
            return None

        try:
            with self._video_semaphore:
                result = self._create_video_thumbnail_ffmpeg(file_path, thumbnail_path)
                if result is not None:
                    return result

                warning("FFmpeg软解失败，无法生成视频缩略图")
                return None
        finally:
            self._release_video_lock(file_path)

    def _get_subprocess_creationflags(self) -> int:
        """获取适用于当前平台的子进程创建标志"""
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _get_subprocess_startupinfo(self):
        """获取适用于当前平台的子进程启动信息，用于隐藏窗口"""
        startupinfo = None
        if sys.platform == "win32":
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            except Exception:
                pass
        return startupinfo

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
                startupinfo=self._get_subprocess_startupinfo(),
            )
        except FileNotFoundError:
            warning("ffprobe未找到")
            return None
        except subprocess.TimeoutExpired:
            # debug(f"ffprobe超时: {file_path}")
            return None
        except Exception as e:
            # debug(f"ffprobe失败: {file_path}, {e}")
            return None

        if completed.returncode != 0:
            # stderr_text = (completed.stderr or "").strip()
            # if stderr_text:
            #     debug(f"ffprobe异常: {stderr_text}")
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
        with track_perf("thumbnail.create_video_thumbnail_ffmpeg"):
            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
            temp_output_path = f"{thumbnail_path}.ffmpeg.tmp.jpg"
            scale_filter = f"scale={dpi_scaled_size}:{dpi_scaled_size}:force_original_aspect_ratio=decrease:flags=lanczos"

            seek_candidates = self._get_ffmpeg_seek_candidates(file_path)
            increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "seek_candidates", len(seek_candidates))

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
                        startupinfo=self._get_subprocess_startupinfo(),
                    )
                except FileNotFoundError:
                    increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "ffmpeg_missing")
                    warning("ffmpeg未找到")
                    return None
                except subprocess.TimeoutExpired:
                    increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "timeout")
                    # debug(f"FFmpeg超时: {file_path}, seek={seek_seconds:.3f}s")
                    continue
                except Exception as e:
                    increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "subprocess_error")
                    # debug(f"FFmpeg失败: {file_path}, seek={seek_seconds:.3f}s, {e}")
                    continue

                if completed.returncode == 0 and os.path.exists(temp_output_path) and os.path.getsize(temp_output_path) > 0:
                    try:
                        os.replace(temp_output_path, thumbnail_path)
                        increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "success")
                        # debug(f"FFmpeg生成成功: {thumbnail_path}, seek={seek_seconds:.3f}s")
                        return thumbnail_path
                    except Exception as e:
                        increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "replace_error")
                        # debug(f"FFmpeg落盘失败: {thumbnail_path}, {e}")
                else:
                    increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "attempt_failed")
                    # stderr_text = (completed.stderr or "").strip()
                    # if stderr_text:
                    #     debug(f"FFmpeg尝试失败: {file_path}, seek={seek_seconds:.3f}s")

            try:
                if os.path.exists(temp_output_path):
                    os.remove(temp_output_path)
            except Exception:
                pass

            increment_perf_counter("thumbnail.create_video_thumbnail_ffmpeg", "failure")
            warning(f"FFmpeg未能生成视频缩略图: {file_path}")
            return None

    def _build_video_thumbnail_subprocess_command(
        self,
        file_path: str,
        prefer_native: bool
    ) -> List[str]:
        """
        构建视频缩略图工作子进程命令。

        - 打包态：直接调用当前 exe，并通过内部参数进入 worker 模式
        - 开发态：通过 `python -m freeassetfilter.app.main` 进入同一入口
        """
        prefer_native_arg = "1" if prefer_native else "0"
        dpi_scale_arg = str(float(self.dpi_scale))

        if getattr(sys, "frozen", False):
            return [
                sys.executable,
                "--faf-thumbnail-worker",
                file_path,
                dpi_scale_arg,
                prefer_native_arg,
            ]

        return [
            sys.executable,
            "-m",
            "freeassetfilter.app.main",
            "--faf-thumbnail-worker",
            file_path,
            dpi_scale_arg,
            prefer_native_arg,
        ]

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
        with track_perf("thumbnail.create_video_thumbnail_batch_safe"):
            increment_perf_counter(
                "thumbnail.create_video_thumbnail_batch_safe",
                "prefer_native" if prefer_native else "prefer_python",
            )
            timeout = max(int(self.BATCH_VIDEO_SUBPROCESS_TIMEOUT), int(self.VIDEO_PROCESSING_TIMEOUT) + 5)
            project_root = str(Path(__file__).resolve().parents[2])

            command = self._build_video_thumbnail_subprocess_command(
                file_path,
                prefer_native,
            )

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
                    startupinfo=self._get_subprocess_startupinfo(),
                )
            except subprocess.TimeoutExpired:
                increment_perf_counter("thumbnail.create_video_thumbnail_batch_safe", "timeout")
                warning(f"视频缩略图生成超时，已跳过: {file_path}")
                return None
            except Exception as e:
                increment_perf_counter("thumbnail.create_video_thumbnail_batch_safe", "subprocess_error")
                warning(f"启动视频缩略图子进程失败，已跳过: {file_path}, {e}")
                return None

            stderr_text = (completed.stderr or "").strip()
            filtered_stderr_text = self._record_subprocess_decode_stats(stderr_text)

            if completed.returncode == 0:
                increment_perf_counter("thumbnail.create_video_thumbnail_batch_safe", "success")
                if filtered_stderr_text:
                    debug(f"视频缩略图子进程输出: {filtered_stderr_text}")
                if self._get_cached_path_exists(thumbnail_path, force_refresh=True):
                    self._set_cached_path_exists(thumbnail_path, True)
                    return thumbnail_path
                if self._get_cached_path_exists(legacy_thumbnail_path, force_refresh=True):
                    self._set_cached_path_exists(legacy_thumbnail_path, True)
                    return legacy_thumbnail_path
                increment_perf_counter("thumbnail.create_video_thumbnail_batch_safe", "missing_output")
                return None

            increment_perf_counter("thumbnail.create_video_thumbnail_batch_safe", "failure")
            if filtered_stderr_text:
                debug(f"视频缩略图子进程异常输出: {filtered_stderr_text}")

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

        try:
            if suffix in self.RAW_FORMATS:
                # RAW格式
                try:
                    img = load_raw_image(
                        file_path,
                        half_size=False,
                        use_camera_wb=True,
                        no_auto_bright=True,
                        output_bps=8,
                    )
                except ImportError:
                    warning(f"rawpy未安装，无法加载RAW: {file_path}")
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
                img = normalize_pil_image(Image.open(file_path))
            elif suffix in self.PSD_FORMATS:
                # PSD格式
                psd = None
                try:
                    from psd_tools import PSDImage
                    psd = PSDImage.open(file_path)
                    img = normalize_pil_image(psd.composite())
                except ImportError:
                    warning(f"psd-tools未安装，无法加载PSD: {file_path}")
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
                img = normalize_pil_image(Image.open(file_path))

            # 检查图像尺寸并应用下采样
            img = self._apply_image_size_limit(img, file_path)

            return img, True

        except Exception as e:
            warning(f"加载图像失败: {file_path}, {e}")
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
            return None, False

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
            # debug(f"图像像素超限 ({total_pixels})，下采样至 {new_width}x{new_height}: {file_path}")
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

            # debug(f"图像尺寸超限 ({width}x{height})，下采样至 {new_width}x{new_height}: {file_path}")

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
        event_name = "thumbnail.load_svg_image"

        try:
            with track_perf(event_name):
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtGui import QImage, QPainter
                from PySide6.QtCore import Qt

                cached_img = self._get_cached_svg_image(file_path)
                if cached_img is not None:
                    return cached_img, True

                # 直接使用QSvgRenderer渲染SVG，不经过SvgRenderer的复杂处理
                renderer = QSvgRenderer(file_path)

                if not renderer.isValid():
                    increment_perf_counter(event_name, "invalid_svg")
                    warning(f"无效SVG文件: {file_path}")
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
                    increment_perf_counter(event_name, "oversized_dimensions")
                    warning(f"SVG尺寸超限: {render_width}x{render_height}")
                    return None, False

                # 检查像素总数限制
                render_pixels = render_width * render_height
                if render_pixels > self.MAX_IMAGE_PIXELS:
                    increment_perf_counter(event_name, "oversized_pixels")
                    warning(f"SVG像素超限: {render_pixels}")
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
                    increment_perf_counter(event_name, "short_image_data")
                    warning(f"SVG数据长度不足: {len(img_data)} < {expected_len}")
                    return None, False

                # 创建PIL图像
                img = Image.frombytes("RGBA", (width, height), img_data)
                self._store_svg_cache_image(file_path, img)
                increment_perf_counter(event_name, "render_success")
                return img, True

        except Exception as e:
            increment_perf_counter(event_name, "failure")
            warning(f"加载SVG失败: {file_path}, {e}")
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
                        self._set_cached_path_exists(file_path, False)
                        deleted_count += 1
                    except (OSError, IOError) as e:
                        debug(f"[ThumbnailManager] 删除缩略图文件失败 {file_path}: {e}")

            with self._frame_cache_lock:
                for cache in self._frame_caches.values():
                    cache.clear()
                self._frame_caches.clear()

            with self._svg_cache_lock:
                for entry in self._svg_render_cache.values():
                    self._close_pil_image_quietly(entry.image)
                self._svg_render_cache.clear()
                self._set_svg_cache_metadata_locked()

            if self._rust_bridge.available:
                self._rust_bridge.clear_cache()

            self._clear_path_exists_cache()

            info(f"已清理 {deleted_count} 个缩略图缓存")
            return deleted_count

        except Exception as e:
            error(f"清理缩略图缓存失败: {e}")
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
            # debug(f"获取缩略图数量失败: {e}")
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
                            # debug(f"获取文件时间失败 {file_path}: {e}")
                            continue
                    thumbnail_files.append((file_path, file_time))
        except (OSError, IOError) as e:
            # debug(f"访问缩略图目录失败 {self._thumb_dir}: {e}")
            pass

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
                    self._set_cached_path_exists(file_path, False)
                    deleted_count += 1
            except (OSError, IOError) as e:
                # debug(f"删除缓存文件失败 {file_path}: {e}")
                pass

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
