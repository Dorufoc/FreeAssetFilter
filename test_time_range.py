#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import datetime
from collections import defaultdict

# 模拟 TimelineEvent 和 MergedEvent 类
class TimelineEvent:
    def __init__(self, name, device, start_time, end_time, videos=None):
        self.name = name
        self.device = device
        self.start_time = start_time
        self.end_time = end_time
        self.videos = videos if videos else []

    def add_video(self, video_path):
        if video_path not in self.videos:
            self.videos.append(video_path)

class MergedEvent:
    def __init__(self, name, device):
        self.name = name
        self.device = device
        self.time_ranges = []
        self.videos = []

    def add_range(self, start_time, end_time):
        self.time_ranges.append((start_time, end_time))
        self.time_ranges.sort(key=lambda x: x[0])

    def add_videos(self, video_paths):
        for video_path in video_paths:
            if video_path not in self.videos:
                self.videos.append(video_path)

# 模拟时间范围比较逻辑
def test_time_range_comparison():
    # 创建测试时间
    t1 = datetime.datetime(2023, 1, 1, 10, 0, 0)
    t2 = datetime.datetime(2023, 1, 1, 11, 0, 0)
    t3 = datetime.datetime(2023, 1, 1, 12, 0, 0)
    
    # 创建测试事件
    event1 = TimelineEvent("Event1", "Device1", t1, t2, ["video1.mp4"])
    event2 = TimelineEvent("Event1", "Device1", t2, t3, ["video2.mp4"])
    
    # 创建合并事件
    merged_event = MergedEvent("Event1", "Device1")
    merged_event.add_videos(event1.videos + event2.videos)
    merged_event.add_range(t1, t2)
    merged_event.add_range(t2, t3)
    
    # 测试选中范围
    selected_ranges = [(datetime.datetime(2023, 1, 1, 10, 30, 0), datetime.datetime(2023, 1, 1, 11, 30, 0))]
    
    # 模拟 get_videos_in_selected_ranges 方法
    videos = set()
    for range_start, range_end in selected_ranges:
        print(f"选中区域: {range_start} 到 {range_end}")
        for event in [merged_event]:
            for event_start, event_end in event.time_ranges:
                print(f"  事件 '{event.name}' 时间范围: {event_start} 到 {event_end}")
                # 检查时间范围是否有交集
                if (event_start <= range_end) and (event_end >= range_start):
                    print(f"    -> 有交集！视频数量: {len(event.videos)}")
                    for video in event.videos:
                        videos.add(video)
                        print(f"      -> 添加视频: {video}")
    
    print(f"最终返回视频列表: {list(videos)}")
    print(f"视频数量: {len(videos)}")

# 测试重叠范围合并逻辑
def test_merge_overlapping_ranges():
    ranges = [
        (datetime.datetime(2023, 1, 1, 10, 0, 0), datetime.datetime(2023, 1, 1, 11, 0, 0)),
        (datetime.datetime(2023, 1, 1, 10, 30, 0), datetime.datetime(2023, 1, 1, 11, 30, 0)),
        (datetime.datetime(2023, 1, 1, 12, 0, 0), datetime.datetime(2023, 1, 1, 13, 0, 0))
    ]
    
    # 合并重叠范围
    if not ranges:
        print("无范围可合并")
        return []
        
    # 按起始时间排序
    sorted_ranges = sorted(ranges, key=lambda x: x[0])
    
    merged = [sorted_ranges[0]]
    
    for current_range in sorted_ranges[1:]:
        current_start, current_end = current_range
        last_start, last_end = merged[-1]
        
        # 如果当前范围与上一个范围有重叠或相邻，则合并
        if current_start <= last_end:
            # 合并两个范围，取最小的开始时间和最大的结束时间
            merged[-1] = (last_start, max(last_end, current_end))
            print(f"合并范围: ({last_start}, {last_end}) 和 ({current_start}, {current_end}) -> ({last_start}, {max(last_end, current_end)})")
        else:
            # 没有重叠，添加当前范围
            merged.append(current_range)
            print(f"添加新范围: ({current_start}, {current_end})")
            
    print(f"合并后的范围: {merged}")
    return merged

if __name__ == "__main__":
    print("=== 测试时间范围比较 ===")
    test_time_range_comparison()
    
    print("\n=== 测试重叠范围合并 ===")
    test_merge_overlapping_ranges()
