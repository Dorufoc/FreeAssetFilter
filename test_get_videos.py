#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试get_videos_in_selected_ranges方法的逻辑
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from freeassetfilter.components.auto_timeline import TimelineEvent, MergedEvent


def test_time_range_overlap():
    """测试时间范围重叠检测逻辑"""
    print("=== 测试时间范围重叠检测 ===")
    
    # 创建测试数据
    merged_events = []
    
    # 添加测试事件1
    event1 = TimelineEvent("Event1", "Camera1", datetime.datetime(2023, 1, 1, 10, 0, 0), datetime.datetime(2023, 1, 1, 10, 10, 0))
    event1.videos = ["/path/to/video1.mp4", "/path/to/video2.mp4"]
    merged_event1 = MergedEvent(event1.name, event1.device)
    merged_event1.add_range(event1.start_time, event1.end_time)
    merged_event1.add_videos(event1.videos)
    merged_events.append(merged_event1)
    
    # 添加测试事件2
    event2 = TimelineEvent("Event2", "Camera2", datetime.datetime(2023, 1, 1, 10, 5, 0), datetime.datetime(2023, 1, 1, 10, 15, 0))
    event2.videos = ["/path/to/video3.mp4"]
    merged_event2 = MergedEvent(event2.name, event2.device)
    merged_event2.add_range(event2.start_time, event2.end_time)
    merged_event2.add_videos(event2.videos)
    merged_events.append(merged_event2)
    
    # 添加测试事件3
    event3 = TimelineEvent("Event3", "Camera3", datetime.datetime(2023, 1, 1, 10, 20, 0), datetime.datetime(2023, 1, 1, 10, 30, 0))
    event3.videos = ["/path/to/video4.mp4"]
    merged_event3 = MergedEvent(event3.name, event3.device)
    merged_event3.add_range(event3.start_time, event3.end_time)
    merged_event3.add_videos(event3.videos)
    merged_events.append(merged_event3)
    
    # 测试选中范围1：与事件1和事件2重叠
    selected_ranges = [(datetime.datetime(2023, 1, 1, 10, 2, 0), datetime.datetime(2023, 1, 1, 10, 8, 0))]
    print(f"测试选中范围: {selected_ranges[0][0]} 到 {selected_ranges[0][1]}")
    
    # 模拟get_videos_in_selected_ranges方法的逻辑
    videos = set()
    for range_start, range_end in selected_ranges:
        # 应用宽容度扩展
        tolerance_seconds = 0  # 先不使用宽容度
        extended_start = range_start - datetime.timedelta(seconds=tolerance_seconds)
        extended_end = range_end + datetime.timedelta(seconds=tolerance_seconds)
        
        for event in merged_events:
            for (event_start, event_end) in event.time_ranges:
                print(f"  事件 '{event.name}' 时间范围: {event_start} 到 {event_end}")
                
                # 检查时间范围是否有交集
                if (event_start <= extended_end) and (event_end >= extended_start):
                    print(f"    -> 有交集！视频数量: {len(event.videos)}")
                    for video in event.videos:
                        videos.add(video)
                        print(f"      -> 添加视频: {video}")
    
    print(f"\n测试结果：找到 {len(videos)} 个视频文件")
    for video in videos:
        print(f"- {video}")
    
    # 期望结果：应该包含事件1和事件2的视频
    expected_videos = {"/path/to/video1.mp4", "/path/to/video2.mp4", "/path/to/video3.mp4"}
    if videos == expected_videos:
        print("✅ 测试通过！")
    else:
        print("❌ 测试失败！")
        print(f"期望: {expected_videos}")
        print(f"实际: {videos}")
    
    print("\n" + "="*50 + "\n")


def test_with_tolerance():
    """测试带宽容度的时间范围重叠检测"""
    print("=== 测试带宽容度的时间范围重叠检测 ===")
    
    # 创建测试数据
    merged_events = []
    
    # 添加测试事件
    event = TimelineEvent("Event1", "Camera1", datetime.datetime(2023, 1, 1, 10, 0, 0), datetime.datetime(2023, 1, 1, 10, 10, 0))
    event.videos = ["/path/to/video1.mp4"]
    merged_event = MergedEvent(event.name, event.device)
    merged_event.add_range(event.start_time, event.end_time)
    merged_event.add_videos(event.videos)
    merged_events.append(merged_event)
    
    # 测试选中范围：与事件有时间间隔，但在宽容度范围内
    selected_ranges = [(datetime.datetime(2023, 1, 1, 10, 10, 10), datetime.datetime(2023, 1, 1, 10, 10, 20))]
    print(f"测试选中范围: {selected_ranges[0][0]} 到 {selected_ranges[0][1]}")
    
    # 模拟get_videos_in_selected_ranges方法的逻辑
    videos = set()
    for range_start, range_end in selected_ranges:
        # 应用宽容度扩展（15秒）
        tolerance_seconds = 15
        extended_start = range_start - datetime.timedelta(seconds=tolerance_seconds)
        extended_end = range_end + datetime.timedelta(seconds=tolerance_seconds)
        print(f"扩展后范围: {extended_start} 到 {extended_end}")
        
        for event in merged_events:
            for (event_start, event_end) in event.time_ranges:
                print(f"  事件 '{event.name}' 时间范围: {event_start} 到 {event_end}")
                
                # 检查时间范围是否有交集
                if (event_start <= extended_end) and (event_end >= extended_start):
                    print(f"    -> 有交集！视频数量: {len(event.videos)}")
                    for video in event.videos:
                        videos.add(video)
                        print(f"      -> 添加视频: {video}")
    
    print(f"\n测试结果：找到 {len(videos)} 个视频文件")
    for video in videos:
        print(f"- {video}")
    
    # 期望结果：应该包含事件的视频（因为宽容度扩展了选中范围）
    expected_videos = {"/path/to/video1.mp4"}
    if videos == expected_videos:
        print("✅ 测试通过！")
    else:
        print("❌ 测试失败！")
        print(f"期望: {expected_videos}")
        print(f"实际: {videos}")
    
    print("\n" + "="*50 + "\n")


if __name__ == "__main__":
    test_time_range_overlap()
    test_with_tolerance()