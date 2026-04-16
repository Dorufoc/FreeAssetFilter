#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

时间线数据模型
用于承载通用资产时间线的数据结构，并兼容旧版自动时间线组件的输出形态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QDateTime


@dataclass
class TimelineRecord:
    """
    通用时间线原始记录

    说明：
    - 旧版 TimelineEvent 更偏视频专用；
    - 新版 TimelineRecord 面向更通用的资产/事件时间线；
    - 通过 metadata / tags / related_paths 承载扩展信息。
    """

    id: str
    title: str
    group_key: str
    group_label: str
    start_time: QDateTime
    end_time: QDateTime
    source_path: Optional[str] = None
    asset_type: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    related_paths: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> int:
        return max(0, self.start_time.secsTo(self.end_time))


@dataclass
class TimelineSegment:
    """
    轨道中的一个聚合片段
    """

    start_time: QDateTime
    end_time: QDateTime
    record_ids: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)
    asset_types: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> int:
        return max(0, self.start_time.secsTo(self.end_time))


@dataclass
class TimelineTrack:
    """
    一条时间线轨道
    """

    key: str
    label: str
    segments: List[TimelineSegment] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_segment(self, segment: TimelineSegment) -> None:
        self.segments.append(segment)

    @property
    def total_asset_count(self) -> int:
        total = 0
        for segment in self.segments:
            total += len(segment.paths)
        return total

    @property
    def total_duration_seconds(self) -> int:
        total = 0
        for segment in self.segments:
            total += segment.duration_seconds
        return total


@dataclass
class TimelineDataset:
    """
    时间线数据集
    """

    records: List[TimelineRecord] = field(default_factory=list)
    tracks: List[TimelineTrack] = field(default_factory=list)
    global_start_time: Optional[QDateTime] = None
    global_end_time: Optional[QDateTime] = None
    summary: Dict[str, Any] = field(default_factory=dict)

    def update_global_range_from_tracks(self) -> None:
        starts: List[QDateTime] = []
        ends: List[QDateTime] = []

        for track in self.tracks:
            for segment in track.segments:
                starts.append(segment.start_time)
                ends.append(segment.end_time)

        if starts and ends:
            self.global_start_time = min(starts)
            self.global_end_time = max(ends)
        else:
            self.global_start_time = None
            self.global_end_time = None


@dataclass
class TimelineSelection:
    """
    选区状态
    """

    selected_track_indexes: List[int] = field(default_factory=list)
    selected_segments: List[Dict[str, Any]] = field(default_factory=list)
    selection_start_time: Optional[QDateTime] = None
    selection_end_time: Optional[QDateTime] = None

    @property
    def selected_file_count(self) -> int:
        total = 0
        for segment in self.selected_segments:
            total += len(segment.get("paths", []))
        return total


@dataclass
class TimelineBuildOptions:
    """
    时间线构建参数
    """

    gap_threshold_seconds: int = 30
    group_by: str = "group"
    merge_mode: str = "gap"
    time_source: str = "modified"
    min_duration_seconds: int = 0
    deduplicate_paths: bool = True


class LegacyMergedEventAdapter:
    """
    兼容旧版 UI 的适配器

    旧版左侧表格和时间线绘制依赖：
    - merged_event.name
    - merged_event.device
    - merged_event.segments -> [(start, end, [paths]), ...]

    该适配器用于在底层数据升级后，仍能复用原有界面逻辑。
    """

    def __init__(self, track: TimelineTrack):
        self.name = track.label
        self.device = track.key
        self.segments = [
            (segment.start_time, segment.end_time, list(segment.paths))
            for segment in track.segments
        ]


def build_legacy_merged_events(tracks: List[TimelineTrack]) -> List[LegacyMergedEventAdapter]:
    """
    将新版轨道模型转换为旧版 merged events 视图模型
    """
    return [LegacyMergedEventAdapter(track) for track in tracks]
