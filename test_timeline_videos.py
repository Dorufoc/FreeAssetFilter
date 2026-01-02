#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试时间轴组件的视频选择功能
"""

import sys
import os
import datetime
from collections import defaultdict

# 添加项目根目录到Python路径
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.auto_timeline import TimelineEvent, MergedEvent


def merge_overlapping_ranges(ranges):
    """合并重叠的时间范围"""
    if not ranges:
        return []
    
    # 按开始时间排序
    sorted_ranges = sorted(ranges, key=lambda x: x[0])
    
    merged = [sorted_ranges[0]]
    for current_start, current_end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        
        # 如果当前范围与上一个范围重叠或相邻，合并它们
        if current_start <= last_end:
            merged[-1] = (last_start, max(last_end, current_end))
        else:
            merged.append((current_start, current_end))
    
    return merged


def get_videos_in_selected_ranges(merged_events, selected_ranges):
    """获取所有选中区域内的视频文件"""
    videos = set()  # 使用集合避免重复
    
    # 遍历所有已保存的选中区域
    for range_start, range_end in selected_ranges:
        # 遍历所有合并事件
        for event in merged_events:
            # 遍历事件的所有时间范围
            for event_start, event_end in event.time_ranges:
                # 检查时间范围是否与选中区域有交集
                if (event_start <= range_end) and (event_end >= range_start):
                    # 添加该事件的所有视频文件
                    for video in event.videos:
                        videos.add(video)
    
    return list(videos)  # 转换为列表返回


def parse_csv(file_path):
    """解析CSV文件"""
    import csv
    from collections import defaultdict
    
    events = []
    event_names = set()
    devices = set()
    
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        # 尝试自动识别列
        name_idx = -1
        device_idx = -1
        start_idx = -1
        end_idx = -1
        video_idx = -1  # 视频路径列索引

        for i, col in enumerate(header):
            col_lower = col.lower().strip()
            if 'name' in col_lower or '事件' in col_lower:
                name_idx = i
            elif 'device' in col_lower or '设备' in col_lower:
                device_idx = i
            elif 'start' in col_lower or '开始' in col_lower:
                start_idx = i
            elif 'end' in col_lower or '结束' in col_lower:
                end_idx = i
            elif 'video' in col_lower or '视频' in col_lower or 'path' in col_lower or '路径' in col_lower:
                # 尝试识别视频路径列
                video_idx = i

        if name_idx == -1 or start_idx == -1 or end_idx == -1:
            raise ValueError("无法识别CSV列：需要包含事件名称、开始时间和结束时间列")

        # 读取数据行
        for row in reader:
            if len(row) < max(name_idx, device_idx, start_idx, end_idx) + 1:
                continue

            name = row[name_idx].strip()
            if not name:
                continue

            device = row[device_idx].strip() if device_idx != -1 else "默认设备"
            
            try:
                start_time = datetime.datetime.strptime(row[start_idx].strip(), "%Y-%m-%d %H:%M:%S")
                end_time = datetime.datetime.strptime(row[end_idx].strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError as e:
                raise ValueError(f"时间格式错误：{str(e)}")

            if end_time <= start_time:
                continue
            
            # 获取视频路径
            video_path = None
            if video_idx != -1 and len(row) > video_idx:
                video_path = row[video_idx].strip()
            
            # 创建事件
            event = TimelineEvent(name, device, start_time, end_time)
            
            # 添加视频路径（如果有）
            if video_path:
                event.add_video(video_path)
            
            events.append(event)
            event_names.add(name)
            devices.add(device)
    
    return events, event_names, devices


def merge_events(events):
    """合并相同事件名称的时间范围"""
    # 按事件名称和设备分组
    event_groups = defaultdict(list)
    for event in events:
        key = (event.name, event.device)
        event_groups[key].append(event)

    # 合并每个组内的事件
    merged_events = []
    for (name, device), group_events in event_groups.items():
        merged_event = MergedEvent(name, device)
        
        # 收集所有视频文件信息
        for event in group_events:
            merged_event.add_videos(event.videos)
        
        # 按起始时间排序
        group_events.sort(key=lambda x: x.start_time)
        
        # 合并时间范围
        current_start = group_events[0].start_time
        current_end = group_events[0].end_time
        
        for event in group_events[1:]:
            # 如果时间范围重叠或相邻，合并
            if event.start_time <= current_end:
                # 合并时间范围
                current_end = max(current_end, event.end_time)
            else:
                # 不连续，保存当前范围并开始新范围
                merged_event.add_range(current_start, current_end)
                current_start = event.start_time
                current_end = event.end_time
        
        # 添加最后一个范围
        merged_event.add_range(current_start, current_end)
        merged_events.append(merged_event)

    # 按事件名称排序
    merged_events.sort(key=lambda x: (x.name, x.device))
    
    return merged_events


def test_timeline_videos():
    """测试时间轴的视频选择功能"""
    print("=== 测试时间轴视频选择功能 ===")
    
    # 测试1: 加载包含视频路径的CSV文件
    print("\n1. 测试加载包含视频路径的CSV文件...")
    try:
        csv_path = "test_video_timeline.csv"
        events, event_names, devices = parse_csv(csv_path)
        print(f"   ✓ 成功加载CSV文件: {csv_path}")
        print(f"   ✓ 加载的事件数量: {len(events)}")
        print(f"   ✓ 事件名称数量: {len(event_names)}")
        print(f"   ✓ 设备数量: {len(devices)}")
        
        # 显示加载的事件和视频信息
        for i, event in enumerate(events):
            print(f"     事件{i+1}: {event.name} ({event.device}) - {event.start_time} 至 {event.end_time}")
            if event.videos:
                print(f"        视频: {', '.join(event.videos)}")
            else:
                print("        无视频")
        
    except Exception as e:
        print(f"   ✗ 加载CSV失败: {e}")
        return False
    
    # 测试2: 合并事件
    print("\n2. 测试合并事件...")
    try:
        merged_events = merge_events(events)
        print(f"   ✓ 合并后的事件数量: {len(merged_events)}")
        
        # 显示合并后的事件和视频信息
        for i, event in enumerate(merged_events):
            print(f"     合并事件{i+1}: {event.name} ({event.device})")
            print(f"        时间范围: {event.time_ranges}")
            if event.videos:
                print(f"        视频: {', '.join(event.videos)}")
            else:
                print("        无视频")
        
    except Exception as e:
        print(f"   ✗ 合并事件失败: {e}")
        return False
    
    # 测试3: 选择范围并获取视频列表
    print("\n3. 测试选择范围并获取视频列表...")
    try:
        # 添加选择范围（覆盖事件1和事件2）
        start_time = datetime.datetime.strptime("2023-01-01 10:00:00", "%Y-%m-%d %H:%M:%S")
        end_time = datetime.datetime.strptime("2023-01-01 11:30:00", "%Y-%m-%d %H:%M:%S")
        selected_ranges = [(start_time, end_time)]
        
        # 获取选中范围内的视频文件
        videos = get_videos_in_selected_ranges(merged_events, selected_ranges)
        print(f"   ✓ 添加选择范围: {start_time} 至 {end_time}")
        print(f"   ✓ 选中的视频数量: {len(videos)}")
        if videos:
            print(f"   ✓ 选中的视频: {', '.join(videos)}")
        else:
            print("   ✗ 未找到任何视频文件！")
            return False
            
    except Exception as e:
        print(f"   ✗ 测试选择范围失败: {e}")
        return False
    
    # 测试4: 测试重叠范围合并
    print("\n4. 测试重叠范围合并...")
    try:
        # 添加重叠的选择范围
        start_time2 = datetime.datetime.strptime("2023-01-01 11:00:00", "%Y-%m-%d %H:%M:%S")
        end_time2 = datetime.datetime.strptime("2023-01-01 12:30:00", "%Y-%m-%d %H:%M:%S")
        selected_ranges.append((start_time2, end_time2))
        
        # 合并重叠范围
        merged_ranges = merge_overlapping_ranges(selected_ranges)
        print(f"   ✓ 添加重叠范围后，合并为 {len(merged_ranges)} 个范围")
        
        # 获取合并后的选中范围内的视频文件
        videos = get_videos_in_selected_ranges(merged_events, merged_ranges)
        print(f"   ✓ 合并后选中的视频数量: {len(videos)}")
        if videos:
            print(f"   ✓ 合并后选中的视频: {', '.join(videos)}")
        else:
            print("   ✗ 未找到任何视频文件！")
            return False
            
    except Exception as e:
        print(f"   ✗ 测试重叠范围合并失败: {e}")
        return False
    
    print("\n=== 所有测试通过！时间轴视频选择功能正常工作 ===")
    return True


if __name__ == "__main__":
    test_timeline_videos()