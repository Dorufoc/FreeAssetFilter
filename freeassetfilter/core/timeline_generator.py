#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

时间线生成器核心模块
负责时间线数据的加载、处理和合并算法

说明：
- 保留旧版 AutoTimeline 所依赖的接口；
- 内部升级为通用资产时间线数据管线；
- 为后续多类型时间线扩展提供基础能力。
"""

from __future__ import annotations

import concurrent.futures
import csv
import json
import os
import sys
import threading
import uuid
from itertools import groupby
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from PySide6.QtCore import QDateTime, QThread, Qt, Signal

from freeassetfilter.core.media_probe import get_video_duration_seconds
from freeassetfilter.core.timeline_models import (
    TimelineBuildOptions,
    TimelineRecord,
)
from freeassetfilter.core.timeline_transformers import build_dataset, build_legacy_view
from freeassetfilter.utils.app_logger import debug, error, exception_details, info, warning
from freeassetfilter.utils.perf_metrics import increment_perf_counter, set_perf_metadata, track_perf


_DURATION_CACHE_LOCK = threading.Lock()
_DURATION_CACHE = None
_DURATION_CACHE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "timeline")
)
_DURATION_CACHE_PATH = os.path.join(_DURATION_CACHE_DIR, "video_duration_cache.json")


def _ensure_duration_cache_loaded():
    """懒加载视频时长缓存"""
    global _DURATION_CACHE

    with _DURATION_CACHE_LOCK:
        if _DURATION_CACHE is not None:
            return

        _DURATION_CACHE = {}
        try:
            if os.path.exists(_DURATION_CACHE_PATH):
                with open(_DURATION_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        _DURATION_CACHE = data
        except Exception as e:
            warning(f"加载视频时长缓存失败: {e}")
            _DURATION_CACHE = {}


def _make_duration_cache_key(file_path: str, stat_result: os.stat_result) -> str:
    """生成基于路径+mtime+size的缓存键"""
    normalized_path = os.path.normcase(os.path.abspath(file_path))
    return f"{normalized_path}|{int(stat_result.st_mtime)}|{stat_result.st_size}"


def _prune_duration_cache_locked():
    """清理已失效的视频时长缓存项"""
    stale_keys = []

    for cache_key, payload in _DURATION_CACHE.items():
        if not isinstance(payload, dict):
            stale_keys.append(cache_key)
            continue

        file_path = payload.get("path")
        if not file_path:
            stale_keys.append(cache_key)
            continue

        try:
            stat_result = os.stat(file_path)
            expected_key = _make_duration_cache_key(file_path, stat_result)
            if expected_key != cache_key:
                stale_keys.append(cache_key)
        except OSError:
            stale_keys.append(cache_key)

    for cache_key in stale_keys:
        _DURATION_CACHE.pop(cache_key, None)


def save_duration_cache():
    """将视频时长缓存持久化到磁盘"""
    _ensure_duration_cache_loaded()

    with _DURATION_CACHE_LOCK:
        try:
            os.makedirs(_DURATION_CACHE_DIR, exist_ok=True)
            _prune_duration_cache_locked()
            with open(_DURATION_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(_DURATION_CACHE, f, ensure_ascii=False, indent=2)
        except Exception as e:
            warning(f"保存视频时长缓存失败: {e}")


def get_video_duration(file_path):
    """
    获取视频文件的真实时长（秒）

    Args:
        file_path: str - 视频文件路径

    Returns:
        float - 视频时长（秒），如果无法获取则返回默认值60秒
    """
    with track_perf("timeline.get_video_duration"):
        default_duration = 60.0
        _ensure_duration_cache_loaded()

        try:
            stat_result = os.stat(file_path)
        except OSError as e:
            increment_perf_counter("timeline.get_video_duration", "stat_failure")
            debug(f"获取视频文件状态失败 {file_path}: {e}")
            return default_duration

        cache_key = _make_duration_cache_key(file_path, stat_result)
        with _DURATION_CACHE_LOCK:
            cached_payload = _DURATION_CACHE.get(cache_key)
            if isinstance(cached_payload, dict):
                cached_duration = cached_payload.get("duration")
                if isinstance(cached_duration, (int, float)) and cached_duration > 0:
                    increment_perf_counter("timeline.get_video_duration", "cache_hit")
                    return float(cached_duration)

        increment_perf_counter("timeline.get_video_duration", "cache_miss")
        duration = get_video_duration_seconds(file_path)
        if duration is None or duration <= 0:
            increment_perf_counter("timeline.get_video_duration", "default_duration_fallback")
            debug(f"ffprobe 获取视频时长失败或结果无效，使用默认时长: {file_path}")
            duration = default_duration

        with _DURATION_CACHE_LOCK:
            _DURATION_CACHE[cache_key] = {
                "path": os.path.abspath(file_path),
                "mtime": int(stat_result.st_mtime),
                "size": stat_result.st_size,
                "duration": float(duration),
            }

        increment_perf_counter("timeline.get_video_duration", "success")
        return float(duration)


def detect_asset_type(file_path: str) -> str:
    """
    根据文件扩展名推断资产类型
    """
    suffix = os.path.splitext(file_path)[1].lower().lstrip(".")

    video_formats = {
        "mp4",
        "avi",
        "mov",
        "wmv",
        "mkv",
        "flv",
        "webm",
        "mpg",
        "mpeg",
        "mxf",
        "m4v",
        "ts",
        "mts",
        "m2ts",
        "3gp",
        "vob",
        "ogv",
        "rmvb",
    }
    audio_formats = {"mp3", "wav", "flac", "ogg", "wma", "m4a", "aac", "opus", "aiff", "ape"}
    image_formats = {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "bmp",
        "webp",
        "tiff",
        "svg",
        "avif",
        "heic",
        "cr2",
        "cr3",
        "nef",
        "arw",
        "dng",
        "orf",
        "psd",
        "ico",
    }
    document_formats = {"pdf", "txt", "md", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "json", "xml"}
    archive_formats = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"}

    if suffix in video_formats:
        return "video"
    if suffix in audio_formats:
        return "audio"
    if suffix in image_formats:
        return "image"
    if suffix in document_formats:
        return "document"
    if suffix in archive_formats:
        return "archive"
    return "unknown"


def resolve_time_range_from_file(
    file_path: str,
    time_source: str = "modified",
    default_duration_seconds: int = 60,
) -> Tuple[QDateTime, QDateTime]:
    """
    从文件推导时间范围

    当前支持：
    - modified: 修改时间
    - created: 创建时间
    - auto: 优先 modified，保留后续扩展空间
    """
    stat_result = os.stat(file_path)

    if time_source == "created":
        start_timestamp = int(stat_result.st_ctime)
    else:
        start_timestamp = int(stat_result.st_mtime)

    start_time = QDateTime.fromSecsSinceEpoch(start_timestamp)
    asset_type = detect_asset_type(file_path)

    if asset_type == "video":
        duration_seconds = int(get_video_duration(file_path))
    else:
        duration_seconds = int(default_duration_seconds)

    end_time = start_time.addSecs(max(1, duration_seconds))
    return start_time, end_time


class TimelineEvent:
    """
    旧版单一事件模型
    保留用于兼容 AutoTimeline 当前逻辑
    """

    def __init__(self, name, device, start_time, end_time, videos=None):
        self.name = name
        self.device = device
        self.start_time = start_time
        self.end_time = end_time
        self.videos = videos or []

    def to_record(self) -> TimelineRecord:
        """
        转换为新版 TimelineRecord
        """
        source_path = self.videos[0] if self.videos else None
        related_paths = list(self.videos[1:]) if len(self.videos) > 1 else []
        asset_type = detect_asset_type(source_path) if source_path else "unknown"

        return TimelineRecord(
            id=str(uuid.uuid4()),
            title=self.name,
            group_key=self.device,
            group_label=self.device,
            start_time=self.start_time,
            end_time=self.end_time,
            source_path=source_path,
            asset_type=asset_type,
            metadata={
                "legacy_name": self.name,
                "legacy_device": self.device,
            },
            tags=[],
            related_paths=related_paths,
        )


class MergedEvent:
    """
    旧版聚合事件模型
    """

    def __init__(self, name, device):
        self.name = name
        self.device = device
        self.segments = []

    def add_segment(self, start, end, videos):
        self.segments.append((start, end, videos))


class TimelineParams:
    """
    时间线全局参数
    保持现有接口，但改为普通实例对象，避免单例串扰
    """

    def __init__(self):
        self.px_per_second = 1.0
        self.row_height = 45
        self.gap_threshold = 30
        self.gap_threshold_unit = "sec"
        self.global_start_time = None
        self.global_end_time = None
        self.dpi_scale = 1.0
        self.group_by = "group"
        self.merge_mode = "gap"
        self.time_source = "modified"
        self.min_duration_seconds = 0

    @property
    def gap_threshold_seconds(self):
        if self.gap_threshold_unit == "min":
            return self.gap_threshold * 60
        if self.gap_threshold_unit == "hour":
            return self.gap_threshold * 3600
        return self.gap_threshold

    def to_build_options(self) -> TimelineBuildOptions:
        return TimelineBuildOptions(
            gap_threshold_seconds=self.gap_threshold_seconds,
            group_by=self.group_by,
            merge_mode=self.merge_mode,
            time_source=self.time_source,
            min_duration_seconds=self.min_duration_seconds,
            deduplicate_paths=True,
        )


def events_to_records(events: List[TimelineEvent]) -> List[TimelineRecord]:
    """
    旧事件列表 -> 新记录列表
    """
    records: List[TimelineRecord] = []
    for event in events:
        try:
            records.append(event.to_record())
        except Exception as e:
            warning(f"转换 TimelineEvent 到 TimelineRecord 失败: {e}")
    return records


def records_to_legacy_merged_events(
    records: List[TimelineRecord],
    options: Optional[TimelineBuildOptions] = None,
) -> List[MergedEvent]:
    """
    新记录列表 -> 旧版 MergedEvent 列表
    """
    legacy_tracks = build_legacy_view(records, options)
    merged_events: List[MergedEvent] = []

    for item in legacy_tracks:
        merged = MergedEvent(item.name, item.device)
        for start, end, videos in item.segments:
            merged.add_segment(start, end, list(videos))
        merged_events.append(merged)

    return merged_events


def merge_logic(events, gap_threshold_seconds):
    """
    兼容旧版的合并逻辑入口
    """
    if not events:
        return []

    records = events_to_records(events)
    options = TimelineBuildOptions(
        gap_threshold_seconds=gap_threshold_seconds,
        group_by="group",
        merge_mode="gap",
        time_source="modified",
        min_duration_seconds=0,
        deduplicate_paths=True,
    )
    return records_to_legacy_merged_events(records, options)


def generate_csv_from_events(events, csv_path):
    """
    从 TimelineEvent 列表生成CSV文件
    """
    fieldnames = ["event_name", "device", "start_time", "end_time", "video_path"]

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for event in events:
            for video_path in event.videos:
                row = {
                    "event_name": event.name,
                    "device": event.device,
                    "start_time": event.start_time.toString(Qt.ISODate),
                    "end_time": event.end_time.toString(Qt.ISODate),
                    "video_path": video_path,
                }
                writer.writerow(row)


class FolderScanner(QThread):
    """
    文件夹扫描线程

    保持旧版输出：
    scan_finished(list[TimelineEvent], csv_path, json_path)

    内部增强：
    - 支持多资产类型识别
    - 支持时间来源策略
    - 支持生成统一 TimelineEvent 供旧 UI 使用
    """

    scan_finished = Signal(list, str, str)
    progress = Signal(int, int)

    def __init__(self, path, time_source: str = "modified"):
        super().__init__()
        self.path = path
        self.time_source = time_source
        self.data_timeline_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "timeline")

        if not os.path.exists(self.data_timeline_dir):
            os.makedirs(self.data_timeline_dir)

    def run(self):
        with track_perf("timeline.folder_scanner.run"):
            results = []
            asset_files = []
            subfolder_set = set()
            main_folder_name = os.path.basename(self.path) or os.path.abspath(self.path)

            set_perf_metadata("timeline.folder_scanner.run", "last_scan_path", self.path)
            debug(f"开始扫描文件夹: {self.path}")

            try:
                for root, dirs, files in os.walk(self.path):
                    if root == self.path:
                        subfolder_name = main_folder_name
                    else:
                        subfolder_name = os.path.basename(root)

                    subfolder_set.add(subfolder_name)

                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            stat = os.stat(file_path)
                            mod_time = int(stat.st_mtime)
                            asset_files.append((file, file_path, subfolder_name, mod_time))
                            increment_perf_counter("timeline.folder_scanner.run", "asset_candidates")
                        except OSError as e:
                            increment_perf_counter("timeline.folder_scanner.run", "stat_failure")
                            exception_details(f"[TimelineGenerator] 获取文件信息出错: {file_path}", e)
            except Exception as e:
                increment_perf_counter("timeline.folder_scanner.run", "scan_failure")
                exception_details("[TimelineGenerator] 扫描过程中出错", e)

            asset_count = len(asset_files)
            set_perf_metadata("timeline.folder_scanner.run", "last_video_count", asset_count)
            debug(f"扫描完成，找到 {asset_count} 个文件，开始并发处理")

            if asset_count > 0:
                max_workers = min(8, os.cpu_count() or 4)
                set_perf_metadata("timeline.folder_scanner.run", "last_max_workers", max_workers)

                processed_count = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_asset = {
                        executor.submit(self._process_single_asset, file_info): file_info
                        for file_info in asset_files
                    }

                    for future in concurrent.futures.as_completed(future_to_asset):
                        asset_info = future_to_asset[future]
                        try:
                            event = future.result()
                            if event:
                                increment_perf_counter("timeline.folder_scanner.run", "event_created")
                                results.append(event)
                        except concurrent.futures.CancelledError as e:
                            increment_perf_counter("timeline.folder_scanner.run", "cancelled")
                            file_name, file_path, *_ = asset_info
                            warning(f"处理文件 {file_name} 被取消: {e}")
                        except Exception as e:
                            increment_perf_counter("timeline.folder_scanner.run", "processing_failure")
                            file_name, file_path, *_ = asset_info
                            exception_details(f"[TimelineGenerator] 处理文件时出错: {file_name}", e)

                        processed_count += 1
                        self.progress.emit(processed_count, asset_count)

            debug(f"文件处理完成: {len(results)}/{asset_count} 成功, 子文件夹: {len(subfolder_set)}")

            csv_path = self._generate_csv(results, main_folder_name)
            json_path = self._generate_json(main_folder_name, asset_count, subfolder_set, results)

            save_duration_cache()
            increment_perf_counter("timeline.folder_scanner.run", "success")
            self.scan_finished.emit(results, csv_path, json_path)

    def _generate_csv(self, events, main_folder_name):
        """
        生成统一时间线 CSV 文件
        """
        import datetime

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file_name = f"{main_folder_name}_{timestamp}.csv"
        csv_path = os.path.join(self.data_timeline_dir, csv_file_name)

        fieldnames = [
            "main_folder",
            "subfolder",
            "asset_type",
            "modification_time",
            "end_time",
            "file_path",
        ]

        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for event in events:
                asset_type = detect_asset_type(event.videos[0]) if event.videos else "unknown"
                for video_path in event.videos:
                    row = {
                        "main_folder": main_folder_name,
                        "subfolder": event.device,
                        "asset_type": asset_type,
                        "modification_time": event.start_time.toString("yyyy-MM-dd HH:mm:ss"),
                        "end_time": event.end_time.toString("yyyy-MM-dd HH:mm:ss"),
                        "file_path": video_path,
                    }
                    writer.writerow(row)

        info(f"CSV文件已生成: {csv_path}")
        return csv_path

    def _process_single_asset(self, asset_info):
        """
        处理单个资产文件，生成 TimelineEvent
        """
        with track_perf("timeline.process_single_video"):
            file_name, file_path, subfolder_name, mod_time = asset_info

            try:
                start_time, end_time = resolve_time_range_from_file(
                    file_path,
                    time_source=self.time_source,
                    default_duration_seconds=60,
                )

                event = TimelineEvent(
                    name=file_name,
                    device=subfolder_name,
                    start_time=start_time,
                    end_time=end_time,
                    videos=[file_path],
                )

                increment_perf_counter("timeline.process_single_video", "success")
                return event
            except (OSError, ValueError) as e:
                increment_perf_counter("timeline.process_single_video", "failure")
                exception_details(f"[TimelineGenerator] 处理文件时出错: {file_name}", e)
                return None

    def _generate_json(self, main_folder_name, file_count, subfolder_set, events):
        """
        生成 JSON 记录文件
        """
        import datetime

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_file_name = f"{main_folder_name}_{timestamp}.json"
        json_path = os.path.join(self.data_timeline_dir, json_file_name)

        processed_files = []
        asset_type_counts: Dict[str, int] = {}

        for event in events:
            for file_path in event.videos:
                processed_files.append(os.path.basename(file_path))
                asset_type = detect_asset_type(file_path)
                asset_type_counts[asset_type] = asset_type_counts.get(asset_type, 0) + 1

        json_data = {
            "main_folder_path": self.path,
            "main_folder_name": main_folder_name,
            "file_total_count": file_count,
            "subfolder_count": len(subfolder_set),
            "subfolder_names": list(subfolder_set),
            "creation_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "processed_files": processed_files,
            "asset_type_counts": asset_type_counts,
            "time_source": self.time_source,
        }

        with open(json_path, "w", encoding="utf-8") as jsonfile:
            json.dump(json_data, jsonfile, ensure_ascii=False, indent=2)

        info(f"JSON记录已生成: {json_path}")
        return json_path


class CSVParser(QThread):
    """
    异步解析 CSV 文件，生成 TimelineEvent 列表
    """

    finished = Signal(list)
    progress = Signal(int, int)

    def __init__(self, file_path, time_source: str = "modified"):
        super().__init__()
        self.file_path = file_path
        self.time_source = time_source

    def run(self):
        results = []

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f) - 1

            processed_count = 0

            with open(self.file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []

                name_col = None
                device_col = None
                start_col = None
                end_col = None
                video_col = None
                asset_type_col = None

                for col in fieldnames:
                    col_lower = col.lower()
                    if any(keyword in col_lower for keyword in ["event", "name", "事件"]):
                        name_col = col
                    elif any(keyword in col_lower for keyword in ["device", "设备", "subfolder", "group"]):
                        device_col = col
                    elif any(keyword in col_lower for keyword in ["start", "开始", "modification_time"]):
                        start_col = col
                    elif any(keyword in col_lower for keyword in ["end", "结束"]):
                        end_col = col
                    elif any(keyword in col_lower for keyword in ["video", "path", "路径", "file_path"]):
                        video_col = col
                    elif "asset_type" in col_lower:
                        asset_type_col = col

                for row in reader:
                    try:
                        if name_col and row.get(name_col):
                            name = row.get(name_col, "Unknown")
                        elif video_col and row.get(video_col):
                            name = os.path.basename(row[video_col])
                        else:
                            name = "Unknown"

                        if start_col and row.get(start_col):
                            start_time = self.parse_datetime(row[start_col])
                        elif video_col and row.get(video_col) and os.path.exists(row[video_col]):
                            start_time, inferred_end_time = resolve_time_range_from_file(
                                row[video_col],
                                time_source=self.time_source,
                            )
                        else:
                            start_time = QDateTime.currentDateTime()

                        if end_col and row.get(end_col):
                            end_time = self.parse_datetime(row[end_col])
                        elif video_col and row.get(video_col) and os.path.exists(row[video_col]):
                            _, end_time = resolve_time_range_from_file(
                                row[video_col],
                                time_source=self.time_source,
                            )
                        else:
                            end_time = start_time.addSecs(60)

                        if end_time <= start_time:
                            end_time = start_time.addSecs(1)

                        videos = []
                        device = "Default"

                        if video_col and row.get(video_col):
                            video_path = row[video_col]
                            videos = [video_path]

                            if device_col is None or not row.get(device_col):
                                device = os.path.basename(os.path.dirname(video_path)) or "Default"

                        if device_col and row.get(device_col):
                            device = row.get(device_col)

                        event = TimelineEvent(name, device, start_time, end_time, videos)
                        results.append(event)
                    except (ValueError, KeyError) as e:
                        error(f"Error parsing row {row}: {e}")
                    finally:
                        processed_count += 1
                        self.progress.emit(processed_count, max(0, line_count))
        except (OSError, csv.Error) as e:
            error(f"Error reading CSV file: {e}")

        save_duration_cache()
        self.finished.emit(results)

    def parse_datetime(self, datetime_str):
        """
        智能解析时间字符串
        """
        if not datetime_str:
            return QDateTime.currentDateTime()

        try:
            timestamp = int(datetime_str)
            return QDateTime.fromSecsSinceEpoch(timestamp)
        except (ValueError, TypeError):
            pass

        dt = QDateTime.fromString(datetime_str, Qt.ISODate)
        if dt.isValid():
            return dt

        formats = [
            "yyyy-MM-dd HH:mm:ss",
            "yyyy/MM/dd HH:mm:ss",
            "MM/dd/yyyy HH:mm:ss",
            "dd/MM/yyyy HH:mm:ss",
            "yyyy-MM-dd",
            "yyyy/MM/dd",
            "MM/dd/yyyy",
            "dd/MM/yyyy",
        ]

        for fmt in formats:
            dt = QDateTime.fromString(datetime_str, fmt)
            if dt.isValid():
                return dt

        return QDateTime.currentDateTime()


def build_timeline_dataset_from_events(
    events: List[TimelineEvent],
    params: Optional[TimelineParams] = None,
):
    """
    从旧版 TimelineEvent 列表构建新版数据集
    """
    params = params or TimelineParams()
    records = events_to_records(events)
    return build_dataset(records, params.to_build_options())
