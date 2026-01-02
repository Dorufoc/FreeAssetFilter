#!/usr/bin/env python3
"""
测试时间轴功能的调试脚本
"""

import csv
import datetime
from collections import defaultdict

class TimelineEvent:
    """时间轴事件类"""
    def __init__(self, name, device, start_time, end_time, videos=None):
        self.name = name
        self.device = device
        self.start_time = start_time
        self.end_time = end_time
        self.videos = videos if videos else []  # 存储视频文件路径列表

    def duration(self):
        """返回事件持续时间（秒）"""
        return (self.end_time - self.start_time).total_seconds()
    
    def add_video(self, video_path):
        """添加视频文件路径"""
        if video_path not in self.videos:
            self.videos.append(video_path)


class MergedEvent:
    """合并后的事件类"""
    def __init__(self, name, device):
        self.name = name
        self.device = device
        self.time_ranges = []
        self.videos = []  # 存储视频文件路径列表

    def add_range(self, start_time, end_time):
        """添加时间范围"""
        self.time_ranges.append((start_time, end_time))
        # 按起始时间排序
        self.time_ranges.sort(key=lambda x: x[0])
    
    def add_video(self, video_path):
        """添加视频文件路径"""
        if video_path not in self.videos:
            self.videos.append(video_path)
    
    def add_videos(self, video_paths):
        """批量添加视频文件路径"""
        for video_path in video_paths:
            self.add_video(video_path)

    def duration(self):
        """返回总持续时间（秒）"""
        total = 0
        for start, end in self.time_ranges:
            total += (end - start).total_seconds()
        return total


def parse_csv(file_path, time_format):
    """解析CSV文件并返回事件列表"""
    events = []
    event_names = set()
    devices = set()
    
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)  # 读取表头
        
        # 尝试自动识别列
        name_idx = -1
        device_idx = -1
        start_idx = -1
        end_idx = -1
        video_idx = -1  # 视频路径列索引

        print("表头信息：")
        for i, col in enumerate(header):
            print(f"  列{i}: {col}")
        
        for i, col in enumerate(header):
            col_lower = col.lower().strip()
            print(f"检查列: {col} -> 小写: {col_lower} (索引: {i})")
            if 'name' in col_lower or '事件' in col_lower:
                name_idx = i
                print(f"识别到名称列: {col} (索引: {i})")
            elif 'device' in col_lower or '设备' in col_lower:
                device_idx = i
                print(f"识别到设备列: {col} (索引: {i})")
            elif 'start' in col_lower or '开始' in col_lower:
                start_idx = i
                print(f"识别到开始时间列: {col} (索引: {i})")
            elif 'end' in col_lower or '结束' in col_lower:
                end_idx = i
                print(f"识别到结束时间列: {col} (索引: {i})")
            elif 'video' in col_lower or '视频' in col_lower or 'path' in col_lower or '路径' in col_lower or 'file' in col_lower or '文件' in col_lower:
                # 尝试识别视频路径列
                video_idx = i
                print(f"识别到视频路径列: {col} (索引: {i})")
        
        print(f"最终识别的列索引: name_idx={name_idx}, device_idx={device_idx}, start_idx={start_idx}, end_idx={end_idx}, video_idx={video_idx}")

        if name_idx == -1 or start_idx == -1 or end_idx == -1:
            raise ValueError("无法识别CSV列：需要包含事件名称、开始时间和结束时间列")

        # 读取数据行
        print("\n读取数据行：")
        for row_idx, row in enumerate(reader):
            if row_idx > 5:  # 只显示前5行
                print(f"  ... 显示前5行，共{reader.line_num-1}行数据")
                break
                
            print(f"  行{row_idx+1}: {row}")
            
            if len(row) < max(name_idx, device_idx, start_idx, end_idx) + 1:
                print(f"    -> 跳过该行：列数不足")
                continue

            name = row[name_idx].strip()
            if not name:
                print(f"    -> 跳过该行：事件名称为空")
                continue

            device = row[device_idx].strip() if device_idx != -1 else "默认设备"
            
            try:
                start_time = datetime.datetime.strptime(row[start_idx].strip(), time_format)
                end_time = datetime.datetime.strptime(row[end_idx].strip(), time_format)
            except ValueError as e:
                print(f"    -> 跳过该行：时间格式错误：{str(e)}")
                continue

            if end_time <= start_time:
                print(f"    -> 跳过该行：结束时间早于开始时间")
                continue
            
            # 获取视频路径
            video_path = None
            if video_idx != -1 and len(row) > video_idx:
                video_path = row[video_idx].strip()
                print(f"    -> 视频路径: {video_path}")
            else:
                print(f"    -> 无视频路径 (video_idx: {video_idx}, 行长度: {len(row)})")
            
            # 创建事件
            event = TimelineEvent(name, device, start_time, end_time)
            
            # 添加视频路径（如果有）
            if video_path:
                event.add_video(video_path)
                print(f"    -> 添加视频到事件: {video_path}")
            
            print(f"    -> 事件创建完成，视频数量: {len(event.videos)}")
            
            events.append(event)
            event_names.add(name)
            devices.add(device)
    
    return events, event_names, devices


def merge_events(events, tolerance_unit="秒"):
    """合并相同事件名称的时间范围"""
    def _truncate_time(time):
        """根据宽容度单位截断时间"""
        if tolerance_unit == "秒":
            return time
        elif tolerance_unit == "分钟":
            return time.replace(second=0, microsecond=0)
        elif tolerance_unit == "小时":
            return time.replace(minute=0, second=0, microsecond=0)
        return time
    
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
        print(f"\n合并事件 {name}-{device}：")
        print(f"  原始事件数量: {len(group_events)}")
        total_videos = 0
        for event in group_events:
            print(f"    事件视频数量: {len(event.videos)}")
            total_videos += len(event.videos)
            merged_event.add_videos(event.videos)
        print(f"  合并后视频总数: {len(merged_event.videos)} (原始总计: {total_videos})")
        
        # 按起始时间排序
        group_events.sort(key=lambda x: x.start_time)
        
        # 合并同一宽容度时间范围内的事件
        current_start = group_events[0].start_time
        current_end = group_events[0].end_time
        
        for event in group_events[1:]:
            # 根据宽容度截断时间
            truncated_current_end = _truncate_time(current_end)
            truncated_event_start = _truncate_time(event.start_time)
            
            # 如果在同一宽容度时间范围内或者有重叠，合并
            if truncated_event_start <= truncated_current_end:
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
    
    return merged_events


def get_videos_in_selected_ranges(selected_ranges, merged_events):
    """获取所有选中区域内的视频文件"""
    videos = set()  # 使用集合避免重复
    
    print(f"\n获取选中区域内的视频：")
    print(f"选中区域数量: {len(selected_ranges)}")
    print(f"合并事件数量: {len(merged_events)}")
    
    # 遍历所有已保存的选中区域
    for i, (range_start, range_end) in enumerate(selected_ranges):
        print(f"选中区域 {i+1}: {range_start} 到 {range_end}")
        
        # 遍历所有合并事件
        for event in merged_events:
            # 遍历事件的所有时间范围
            for j, (event_start, event_end) in enumerate(event.time_ranges):
                print(f"  事件 '{event.name}' 时间范围 {j+1}: {event_start} 到 {event_end}")
                
                # 检查时间范围是否与选中区域有交集
                if (event_start <= range_end) and (event_end >= range_start):
                    print(f"    -> 有交集！视频数量: {len(event.videos)}")
                    # 添加该事件的所有视频文件
                    for video in event.videos:
                        videos.add(video)
                        print(f"      -> 添加视频: {video}")
    
    print(f"\n最终返回视频列表数量: {len(videos)}")
    return list(videos)  # 转换为列表返回


if __name__ == "__main__":
    # 测试CSV解析和视频处理
    print("=== 测试时间轴功能 ===")
    
    # 解析CSV文件
    file_path = "test_video_timeline.csv"
    time_format = "%Y-%m-%d %H:%M:%S"
    
    try:
        events, event_names, devices = parse_csv(file_path, time_format)
        print(f"\n解析完成：")
        print(f"  事件数量: {len(events)}")
        print(f"  事件名称: {event_names}")
        print(f"  设备: {devices}")
        
        # 合并事件
        merged_events = merge_events(events)
        print(f"\n事件合并完成：")
        print(f"  合并后事件数量: {len(merged_events)}")
        
        # 测试选中区域的视频获取
        # 创建一个测试选中区域（覆盖CSV中的部分时间）
        test_start = datetime.datetime(2023, 1, 1, 10, 10, 0)
        test_end = datetime.datetime(2023, 1, 1, 11, 10, 0)
        selected_ranges = [(test_start, test_end)]
        
        videos = get_videos_in_selected_ranges(selected_ranges, merged_events)
        print(f"\n测试结果：")
        print(f"  选中视频数量: {len(videos)}")
        for video in videos:
            print(f"    {video}")
            
    except Exception as e:
        print(f"错误：{str(e)}")
        import traceback
        traceback.print_exc()
