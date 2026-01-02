import csv
import datetime
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.abspath('.'))

from freeassetfilter.components.auto_timeline import AutoTimeline, TimelineEvent, MergedEvent

# 创建AutoTimeline实例
timeline = AutoTimeline()

# 设置时间格式
timeline.time_format = "%Y-%m-%d %H:%M:%S"

# 测试CSV文件路径
test_csv = "test_video_timeline.csv"

print(f"测试CSV文件: {test_csv}")

# 读取CSV文件
with open(test_csv, 'r', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)  # 读取表头
    
    print(f"CSV表头: {header}")
    
    # 尝试自动识别列
    name_idx = -1
    device_idx = -1
    start_idx = -1
    end_idx = -1
    video_idx = -1  # 视频路径列索引

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
    events = []
    event_names = set()
    devices = set()
    
    print(f"\n读取数据行:")
    for row_idx, row in enumerate(reader, 2):  # 从第2行开始计数
        if len(row) < max(name_idx, device_idx, start_idx, end_idx) + 1:
            print(f"行 {row_idx}: 跳过 (行长度不足)")
            continue

        name = row[name_idx].strip()
        if not name:
            print(f"行 {row_idx}: 跳过 (无名称)")
            continue

        device = row[device_idx].strip() if device_idx != -1 else "默认设备"
        
        try:
            start_time = datetime.datetime.strptime(row[start_idx].strip(), timeline.time_format)
            end_time = datetime.datetime.strptime(row[end_idx].strip(), timeline.time_format)
        except ValueError as e:
            print(f"行 {row_idx}: 跳过 (时间格式错误: {str(e)})")
            continue

        if end_time <= start_time:
            print(f"行 {row_idx}: 跳过 (结束时间 <= 开始时间)")
            continue
        
        # 获取视频路径
        video_path = None
        if video_idx != -1 and len(row) > video_idx:
            video_path = row[video_idx].strip()
            print(f"行 {row_idx}: 视频路径: {video_path}")
        else:
            print(f"行 {row_idx}: 无视频路径 (video_idx: {video_idx}, 行长度: {len(row)})")
        
        # 创建事件
        event = TimelineEvent(name, device, start_time, end_time)
        
        # 添加视频路径（如果有）
        if video_path:
            event.add_video(video_path)
            print(f"行 {row_idx}: 添加视频路径到事件: {video_path}")
        
        print(f"行 {row_idx}: 事件创建完成，视频数量: {len(event.videos)}")
        
        events.append(event)
        event_names.add(name)
        devices.add(device)

print(f"\nCSV解析完成:")
print(f"  事件数量: {len(events)}")
print(f"  事件名称数量: {len(event_names)}")
print(f"  设备数量: {len(devices)}")

# 测试事件对象中的视频信息
print(f"\n事件视频信息测试:")
for i, event in enumerate(events[:5], 1):  # 只显示前5个事件
    print(f"事件 {i}: {event.name} - 设备: {event.device}")
    print(f"  时间范围: {event.start_time} 到 {event.end_time}")
    print(f"  视频数量: {len(event.videos)}")
    for video in event.videos:
        print(f"    视频路径: {video}")

# 测试合并事件
print(f"\n合并事件测试:")
from collections import defaultdict

event_groups = defaultdict(list)
for event in events:
    key = (event.name, event.device)
    event_groups[key].append(event)

merged_events = []
for (name, device), group_events in event_groups.items():
    merged_event = MergedEvent(name, device)
    
    # 收集所有视频文件信息
    for event in group_events:
        merged_event.add_videos(event.videos)
    
    print(f"合并事件: {name} - 设备: {device}")
    print(f"  原始事件数量: {len(group_events)}")
    print(f"  合并后的视频数量: {len(merged_event.videos)}")
    
    merged_events.append(merged_event)

print(f"\n合并事件完成:")
print(f"  合并事件数量: {len(merged_events)}")
