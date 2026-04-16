#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

时间线布局与坐标映射层
负责时间轴范围、像素映射、轨道布局、命中测试与可见区域计算。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QDateTime, QRectF

from freeassetfilter.core.timeline_models import TimelineDataset, TimelineSegment, TimelineTrack


@dataclass
class TimelineLayoutMetrics:
    """
    时间线布局参数
    """

    top_axis_height: int = 30
    row_height: int = 40
    row_padding: int = 5
    min_segment_width: float = 2.0
    right_padding: int = 100
    px_per_second: float = 1.0


class TimelineViewportState:
    """
    时间线视口状态
    """

    def __init__(self):
        self.global_start_time: Optional[QDateTime] = None
        self.global_end_time: Optional[QDateTime] = None
        self.px_per_second: float = 1.0

    def set_range(self, start_time: Optional[QDateTime], end_time: Optional[QDateTime]) -> None:
        self.global_start_time = start_time
        self.global_end_time = end_time

    def set_scale(self, px_per_second: float) -> None:
        self.px_per_second = max(0.0001, px_per_second)

    def has_valid_range(self) -> bool:
        return bool(
            self.global_start_time
            and self.global_end_time
            and self.global_start_time <= self.global_end_time
        )

    def total_duration_seconds(self) -> int:
        if not self.has_valid_range():
            return 0
        return max(0, self.global_start_time.secsTo(self.global_end_time))

    def time_to_x(self, time_value: QDateTime) -> float:
        if not self.global_start_time:
            return 0.0
        return self.global_start_time.secsTo(time_value) * self.px_per_second

    def x_to_time(self, x_value: float) -> QDateTime:
        if not self.global_start_time:
            return QDateTime.currentDateTime()
        seconds = int(x_value / max(0.0001, self.px_per_second))
        return self.global_start_time.addSecs(seconds)


class TimelineLayoutEngine:
    """
    时间线布局引擎
    """

    def __init__(self, metrics: Optional[TimelineLayoutMetrics] = None):
        self.metrics = metrics or TimelineLayoutMetrics()
        self.viewport = TimelineViewportState()

    def configure_from_dataset(self, dataset: TimelineDataset) -> None:
        self.viewport.set_range(dataset.global_start_time, dataset.global_end_time)
        self.viewport.set_scale(self.metrics.px_per_second)

    def update_scale(self, px_per_second: float) -> None:
        self.metrics.px_per_second = max(0.0001, px_per_second)
        self.viewport.set_scale(self.metrics.px_per_second)

    def set_row_height(self, row_height: int) -> None:
        self.metrics.row_height = max(1, row_height)

    def total_content_height(self, track_count: int, viewport_height: int = 0) -> int:
        content_height = self.metrics.top_axis_height + track_count * self.metrics.row_height
        return max(content_height, viewport_height)

    def total_content_width(self, viewport_width: int = 0) -> int:
        content_width = int(self.viewport.total_duration_seconds() * self.metrics.px_per_second) + self.metrics.right_padding
        return max(content_width, viewport_width)

    def row_top(self, row_index: int) -> int:
        return self.metrics.top_axis_height + row_index * self.metrics.row_height

    def segment_rect(self, row_index: int, segment: TimelineSegment) -> QRectF:
        x_start = self.viewport.time_to_x(segment.start_time)
        duration = max(0, segment.start_time.secsTo(segment.end_time))
        width = max(self.metrics.min_segment_width, duration * self.metrics.px_per_second)
        y = self.row_top(row_index) + self.metrics.row_padding
        height = max(1, self.metrics.row_height - self.metrics.row_padding * 2)
        return QRectF(x_start, y, width, height)

    def visible_row_range(
        self,
        scroll_y: int,
        viewport_height: int,
        track_count: int,
        buffer_rows: int = 2,
    ) -> Tuple[int, int]:
        if track_count <= 0:
            return (0, 0)

        relative_top = max(0, scroll_y - self.metrics.top_axis_height)
        relative_bottom = max(0, scroll_y + viewport_height - self.metrics.top_axis_height)

        first_row = max(0, relative_top // max(1, self.metrics.row_height) - buffer_rows)
        last_row = min(
            track_count,
            relative_bottom // max(1, self.metrics.row_height) + 1 + buffer_rows,
        )
        return (first_row, last_row)

    def visible_time_range(
        self,
        scroll_x: int,
        viewport_width: int,
        buffer_pixels: int = 80,
    ) -> Tuple[Optional[QDateTime], Optional[QDateTime]]:
        if not self.viewport.has_valid_range():
            return (None, None)

        start_x = max(0, scroll_x - buffer_pixels)
        end_x = max(0, scroll_x + viewport_width + buffer_pixels)
        return (
            self.viewport.x_to_time(start_x),
            self.viewport.x_to_time(end_x),
        )

    def hit_test_segment(
        self,
        tracks: List[TimelineTrack],
        x: float,
        y: float,
    ) -> Optional[Dict[str, object]]:
        for row_index, track in enumerate(tracks):
            row_top = self.row_top(row_index)
            row_bottom = row_top + self.metrics.row_height

            if not (row_top <= y <= row_bottom):
                continue

            for segment_index, segment in enumerate(track.segments):
                rect = self.segment_rect(row_index, segment)
                if rect.contains(x, y):
                    return {
                        "row_index": row_index,
                        "segment_index": segment_index,
                        "track": track,
                        "segment": segment,
                        "rect": rect,
                    }

        return None

    def collect_segments_in_rect(
        self,
        tracks: List[TimelineTrack],
        selection_rect: QRectF,
    ) -> List[Dict[str, object]]:
        results: List[Dict[str, object]] = []

        for row_index, track in enumerate(tracks):
            for segment_index, segment in enumerate(track.segments):
                rect = self.segment_rect(row_index, segment)
                if rect.intersects(selection_rect):
                    results.append(
                        {
                            "row_index": row_index,
                            "segment_index": segment_index,
                            "track": track,
                            "segment": segment,
                            "rect": rect,
                        }
                    )

        return results

    def build_track_summary(self, track: TimelineTrack) -> Dict[str, object]:
        earliest_start = None
        latest_end = None

        if track.segments:
            earliest_start = min(segment.start_time for segment in track.segments)
            latest_end = max(segment.end_time for segment in track.segments)

        return {
            "key": track.key,
            "label": track.label,
            "segment_count": len(track.segments),
            "asset_count": track.total_asset_count,
            "total_duration_seconds": track.total_duration_seconds,
            "earliest_start": earliest_start,
            "latest_end": latest_end,
            "stats": dict(track.stats or {}),
        }
