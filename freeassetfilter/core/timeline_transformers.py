#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

时间线变换管线
负责通用记录的分组、合并、统计，以及向旧版时间线组件提供兼容输出。
"""

from __future__ import annotations

from collections import Counter
from itertools import groupby
from typing import Dict, Iterable, List

from PySide6.QtCore import QDateTime

from freeassetfilter.core.timeline_models import (
    LegacyMergedEventAdapter,
    TimelineBuildOptions,
    TimelineDataset,
    TimelineRecord,
    TimelineSegment,
    TimelineTrack,
    build_legacy_merged_events,
)


def _normalize_track_key(record: TimelineRecord, options: TimelineBuildOptions) -> str:
    """
    根据分组策略计算轨道 key
    """
    group_by = options.group_by

    if group_by == "asset_type":
        return record.asset_type or "unknown"

    if group_by == "date":
        return record.start_time.toString("yyyy-MM-dd")

    if group_by == "title":
        return record.title or "untitled"

    return record.group_key or "default"


def _normalize_track_label(record: TimelineRecord, options: TimelineBuildOptions) -> str:
    """
    根据分组策略计算轨道显示名
    """
    group_by = options.group_by

    if group_by == "asset_type":
        return record.asset_type or "unknown"

    if group_by == "date":
        return record.start_time.toString("yyyy-MM-dd")

    if group_by == "title":
        return record.title or "untitled"

    return record.group_label or record.group_key or "default"


def _deduplicate_keep_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []

    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)

    return result


def _build_segment_from_records(records: List[TimelineRecord], deduplicate_paths: bool = True) -> TimelineSegment:
    """
    从一组记录构建聚合片段
    """
    if not records:
        raise ValueError("records must not be empty")

    start_time = min(record.start_time for record in records)
    end_time = max(record.end_time for record in records)

    all_paths: List[str] = []
    all_types: List[str] = []
    record_ids: List[str] = []

    for record in records:
        record_ids.append(record.id)
        if record.source_path:
            all_paths.append(record.source_path)
        all_paths.extend(record.related_paths)
        if record.asset_type:
            all_types.append(record.asset_type)

    if deduplicate_paths:
        all_paths = _deduplicate_keep_order(all_paths)
        all_types = _deduplicate_keep_order(all_types)

    metadata: Dict[str, object] = {
        "record_count": len(records),
        "titles": [record.title for record in records],
        "group_keys": _deduplicate_keep_order([record.group_key for record in records]),
    }

    return TimelineSegment(
        start_time=start_time,
        end_time=end_time,
        record_ids=record_ids,
        paths=all_paths,
        asset_types=all_types,
        metadata=metadata,
    )


def build_tracks(records: List[TimelineRecord], options: TimelineBuildOptions | None = None) -> List[TimelineTrack]:
    """
    将原始记录构建为轨道列表
    """
    if not records:
        return []

    options = options or TimelineBuildOptions()

    sorted_records = sorted(
        records,
        key=lambda item: (
            _normalize_track_key(item, options),
            item.start_time.toMSecsSinceEpoch(),
            item.end_time.toMSecsSinceEpoch(),
            item.title,
        ),
    )

    tracks: List[TimelineTrack] = []

    for track_key, grouped in groupby(sorted_records, key=lambda item: _normalize_track_key(item, options)):
        grouped_records = list(grouped)
        if not grouped_records:
            continue

        track = TimelineTrack(
            key=track_key,
            label=_normalize_track_label(grouped_records[0], options),
        )

        if options.merge_mode == "strict":
            for record in grouped_records:
                track.add_segment(
                    _build_segment_from_records([record], deduplicate_paths=options.deduplicate_paths)
                )
        else:
            current_group: List[TimelineRecord] = [grouped_records[0]]
            current_end = grouped_records[0].end_time

            for record in grouped_records[1:]:
                gap = current_end.secsTo(record.start_time)
                should_merge = False

                if options.merge_mode == "overlap":
                    should_merge = gap <= 0
                else:
                    should_merge = gap <= options.gap_threshold_seconds

                if should_merge:
                    current_group.append(record)
                    if record.end_time > current_end:
                        current_end = record.end_time
                else:
                    track.add_segment(
                        _build_segment_from_records(
                            current_group,
                            deduplicate_paths=options.deduplicate_paths,
                        )
                    )
                    current_group = [record]
                    current_end = record.end_time

            if current_group:
                track.add_segment(
                    _build_segment_from_records(
                        current_group,
                        deduplicate_paths=options.deduplicate_paths,
                    )
                )

        track.stats = build_track_stats(track)
        tracks.append(track)

    return tracks


def build_track_stats(track: TimelineTrack) -> Dict[str, object]:
    """
    计算单轨统计信息
    """
    type_counter = Counter()

    for segment in track.segments:
        for asset_type in segment.asset_types:
            if asset_type:
                type_counter[asset_type] += 1

    earliest_start: QDateTime | None = None
    latest_end: QDateTime | None = None

    if track.segments:
        earliest_start = min(segment.start_time for segment in track.segments)
        latest_end = max(segment.end_time for segment in track.segments)

    return {
        "segment_count": len(track.segments),
        "asset_count": track.total_asset_count,
        "total_duration_seconds": track.total_duration_seconds,
        "asset_type_counts": dict(type_counter),
        "earliest_start": earliest_start,
        "latest_end": latest_end,
    }


def build_dataset(records: List[TimelineRecord], options: TimelineBuildOptions | None = None) -> TimelineDataset:
    """
    构建完整时间线数据集
    """
    options = options or TimelineBuildOptions()
    dataset = TimelineDataset(records=list(records))
    dataset.tracks = build_tracks(dataset.records, options)
    dataset.update_global_range_from_tracks()

    type_counter = Counter()
    for record in dataset.records:
        type_counter[record.asset_type or "unknown"] += 1

    dataset.summary = {
        "record_count": len(dataset.records),
        "track_count": len(dataset.tracks),
        "asset_type_counts": dict(type_counter),
        "group_by": options.group_by,
        "merge_mode": options.merge_mode,
        "gap_threshold_seconds": options.gap_threshold_seconds,
    }

    return dataset


def build_legacy_view(records: List[TimelineRecord], options: TimelineBuildOptions | None = None) -> List[LegacyMergedEventAdapter]:
    """
    构建旧版 AutoTimeline 可直接消费的 merged events 列表
    """
    dataset = build_dataset(records, options)
    return build_legacy_merged_events(dataset.tracks)
