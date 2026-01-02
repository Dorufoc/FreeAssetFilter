import csv
import datetime
from collections import defaultdict

class TimelineEvent:
    """时间轴事件类"""
    def __init__(self, name, device, start_time, end_time):
        self.name = name
        self.device = device
        self.start_time = start_time
        self.end_time = end_time
        self.videos = []  # 存储视频文件路径列表
    
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

def parse_csv(file_path, time_format="%Y-%m-%d %H:%M:%S"):
    """解析CSV文件"""
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
        
        print("\n=== CSV列识别 ===")
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
        print("\n=== CSV数据解析 ===")
        for row in reader:
            if len(row) < max(name_idx, device_idx, start_idx, end_idx) + 1:
                continue
            
            name = row[name_idx].strip()
            if not name:
                continue
            
            device = row[device_idx].strip() if device_idx != -1 else "默认设备"
            
            try:
                start_time = datetime.datetime.strptime(row[start_idx].strip(), time_format)
                end_time = datetime.datetime.strptime(row[end_idx].strip(), time_format)
            except ValueError as e:
                print(f"时间格式错误：{str(e)}")
                continue
            
            if end_time <= start_time:
                print(f"结束时间早于或等于开始时间，跳过该行：{name}")
                continue
            
            # 获取视频路径
            video_path = None
            if video_idx != -1 and len(row) > video_idx:
                video_path = row[video_idx].strip()
                print(f"  行数据中的视频路径: {video_path}")
            else:
                print(f"  行数据中无视频路径 (video_idx: {video_idx}, 行长度: {len(row)})")
            
            # 创建事件
            event = TimelineEvent(name, device, start_time, end_time)
            
            # 添加视频路径（如果有）
            if video_path:
                event.add_video(video_path)
                print(f"  添加视频路径到事件: {video_path}")
            
            print(f"  事件创建完成，视频数量: {len(event.videos)}")
            
            events.append(event)
            event_names.add(name)
            devices.add(device)
    
    print(f"\n=== CSV解析结果 ===")
    print(f"总事件数: {len(events)}")
    print(f"唯一事件名称数: {len(event_names)}")
    print(f"唯一设备数: {len(devices)}")
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
        for event in group_events:
            merged_event.add_videos(event.videos)
        
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
    
    # 按事件名称排序
    merged_events.sort(key=lambda x: (x.name, x.device))
    
    print(f"\n=== 事件合并结果 ===")
    print(f"合并后事件数: {len(merged_events)}")
    for i, event in enumerate(merged_events):
        print(f"  合并事件 {i+1}: {event.name} - {event.device}")
        print(f"    时间范围数量: {len(event.time_ranges)}")
        for j, (start, end) in enumerate(event.time_ranges):
            print(f"      范围 {j+1}: {start} 到 {end}")
        print(f"    视频数量: {len(event.videos)}")
        for video in event.videos:
            print(f"      视频路径: {video}")
    
    return merged_events

def merge_overlapping_ranges(ranges):
    """合并重叠或相邻的时间范围"""
    if not ranges:
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
        else:
            # 没有重叠，添加当前范围
            merged.append(current_range)
            
    return merged

def get_videos_in_selected_ranges(merged_events, selected_ranges):
    """获取所有选中区域内的视频文件"""
    videos = set()  # 使用集合避免重复
    
    print(f"\n=== 选中范围与视频匹配 ===")
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
    
    print(f"\n=== 最终结果 ===")
    print(f"最终返回视频列表数量: {len(videos)}")
    for video in videos:
        print(f"  {video}")
    
    return list(videos)  # 转换为列表返回

# 测试函数
def test_timeline_video_selection():
    """测试时间轴视频选择功能"""
    print("===== 时间轴视频选择测试 =====")
    
    # 1. 解析CSV文件
    csv_file = "test_video_timeline.csv"
    try:
        events, event_names, devices = parse_csv(csv_file)
        if not events:
            print("错误：CSV文件中没有有效的事件")
            return
    except Exception as e:
        print(f"解析CSV文件时出错：{str(e)}")
        return
    
    # 2. 合并事件
    merged_events = merge_events(events)
    if not merged_events:
        print("错误：没有合并后的事件")
        return
    
    # 3. 创建测试选中区域
    # 获取所有事件的时间范围
    all_times = []
    for event in merged_events:
        for start, end in event.time_ranges:
            all_times.append(start)
            all_times.append(end)
    
    if not all_times:
        print("错误：没有有效的时间范围")
        return
    
    min_time = min(all_times)
    max_time = max(all_times)
    
    # 创建一个覆盖所有事件的选中区域
    test_selected_ranges = [(min_time, max_time)]
    
    # 4. 测试视频选择
    selected_videos = get_videos_in_selected_ranges(merged_events, test_selected_ranges)
    
    print(f"\n===== 测试完成 =====")
    print(f"选中的视频数量: {len(selected_videos)}")
    return selected_videos

if __name__ == "__main__":
    test_timeline_video_selection()
