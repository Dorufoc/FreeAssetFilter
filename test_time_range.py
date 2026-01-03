#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试时间范围重叠逻辑
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.auto_timeline import TimelineEvent, MergedEvent

def main():
    """主函数"""
    print("=== 测试时间范围重叠逻辑 ===")
    
    # 创建当前时间作为基准
    current_time = datetime.datetime.now()
    print(f"当前时间: {current_time}")
    
    # 创建一些测试事件
    event1 = TimelineEvent("事件1", "设备1", 
                         current_time - datetime.timedelta(minutes=30),
                         current_time - datetime.timedelta(minutes=20))
    event1.add_video("C:\test\video1.mp4")
    event1.add_video("C:\test\video2.mp4")
    
    event2 = TimelineEvent("事件1", "设备1", 
                         current_time - datetime.timedelta(minutes=15),
                         current_time - datetime.timedelta(minutes=5))
    event2.add_video("C:\test\video3.mp4")
    
    event3 = TimelineEvent("事件2", "设备2", 
                         current_time - datetime.timedelta(minutes=25),
                         current_time - datetime.timedelta(minutes=15))
    event3.add_video("C:\test\video4.mp4")
    event3.add_video("C:\test\video5.mp4")
    
    event4 = TimelineEvent("事件3", "设备1", 
                         current_time - datetime.timedelta(minutes=40),
                         current_time - datetime.timedelta(minutes=35))
    event4.add_video("C:\test\video6.mp4")
    
    # 创建合并事件
    merged_event1 = MergedEvent("事件1", "设备1")
    merged_event1.add_videos(event1.videos)
    merged_event1.add_videos(event2.videos)
    merged_event1.add_range(event1.start_time, event1.end_time)
    merged_event1.add_range(event2.start_time, event2.end_time)
    
    merged_event2 = MergedEvent("事件2", "设备2")
    merged_event2.add_videos(event3.videos)
    merged_event2.add_range(event3.start_time, event3.end_time)
    
    merged_event3 = MergedEvent("事件3", "设备1")
    merged_event3.add_videos(event4.videos)
    merged_event3.add_range(event4.start_time, event4.end_time)
    
    merged_events = [merged_event1, merged_event2, merged_event3]
    
    # 设置测试选中范围
    test_start = current_time - datetime.timedelta(minutes=40)
    test_end = current_time - datetime.timedelta(minutes=5)
    print(f"\n测试选中范围: {test_start} 到 {test_end}")
    
    # 测试时间范围重叠逻辑
    videos = set()
    for event in merged_events:
        for (event_start, event_end) in event.time_ranges:
            print(f"  事件 '{event.name}' 时间范围: {event_start} 到 {event_end}")
            
            # 检查时间范围是否有交集
            if (event_start <= test_end) and (event_end >= test_start):
                print(f"    -> 有交集！视频数量: {len(event.videos)}")
                for video in event.videos:
                    videos.add(video)
                    print(f"      -> 添加视频: {video}")
    
    print(f"\n最终获取到的视频数量: {len(videos)}")
    for video in videos:
        print(f"  {video}")

if __name__ == "__main__":
    main()
