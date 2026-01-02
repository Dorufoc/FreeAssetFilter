#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试CSV解析功能，查看视频路径是否能被正确识别
"""

import csv
import datetime

# 测试CSV文件路径
test_csv_path = "C:\\Users\\Dorufoc\\Desktop\\code\\FreeAssetFilter\\test_video_timeline.csv"

def parse_csv(file_path):
    """解析CSV文件"""
    events = []
    time_format = "%Y-%m-%d %H:%M:%S"

    with open(file_path, 'r', encoding='utf-8') as f:
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
            print(f"列 {i}: {col} (小写: {col_lower})")
            if 'name' in col_lower or '事件' in col_lower:
                name_idx = i
                print(f"  -> 识别为事件名称列")
            elif 'device' in col_lower or '设备' in col_lower:
                device_idx = i
                print(f"  -> 识别为设备列")
            elif 'start' in col_lower or '开始' in col_lower:
                start_idx = i
                print(f"  -> 识别为开始时间列")
            elif 'end' in col_lower or '结束' in col_lower:
                end_idx = i
                print(f"  -> 识别为结束时间列")
            elif 'video' in col_lower or '视频' in col_lower or 'path' in col_lower or '路径' in col_lower:
                # 尝试识别视频路径列
                video_idx = i
                print(f"  -> 识别为视频路径列")

        print(f"\n识别结果:")
        print(f"事件名称列索引: {name_idx}")
        print(f"设备列索引: {device_idx}")
        print(f"开始时间列索引: {start_idx}")
        print(f"结束时间列索引: {end_idx}")
        print(f"视频路径列索引: {video_idx}")

        if name_idx == -1 or start_idx == -1 or end_idx == -1:
            raise ValueError("无法识别CSV列：需要包含事件名称、开始时间和结束时间列")

        # 读取数据行
        print(f"\n数据行:")
        for row in reader:
            print(f"  行: {row}")
            if len(row) < max(name_idx, device_idx, start_idx, end_idx) + 1:
                print(f"    -> 跳过，列数不足")
                continue

            name = row[name_idx].strip()
            if not name:
                print(f"    -> 跳过，事件名称为空")
                continue

            device = row[device_idx].strip() if device_idx != -1 else "默认设备"
            
            try:
                start_time = datetime.datetime.strptime(row[start_idx].strip(), time_format)
                end_time = datetime.datetime.strptime(row[end_idx].strip(), time_format)
            except ValueError as e:
                print(f"    -> 时间格式错误: {str(e)}")
                continue

            if end_time <= start_time:
                print(f"    -> 跳过，结束时间 <= 开始时间")
                continue
            
            # 获取视频路径
            video_path = None
            if video_idx != -1 and len(row) > video_idx:
                video_path = row[video_idx].strip()
                print(f"    -> 视频路径: {video_path}")
            
            # 创建事件对象
            event = {
                "name": name,
                "device": device,
                "start_time": start_time,
                "end_time": end_time,
                "video_path": video_path
            }
            
            events.append(event)
            print(f"    -> 添加事件: {name} - {device}")

    return events

if __name__ == "__main__":
    print("开始测试CSV解析...")
    try:
        events = parse_csv(test_csv_path)
        print(f"\n解析完成，共添加 {len(events)} 个事件")
        
        # 打印所有事件的视频路径
        print(f"\n事件视频路径列表:")
        for i, event in enumerate(events):
            print(f"  事件 {i+1}: {event['name']} - {event['device']} - 视频: {event['video_path']}")
            
    except Exception as e:
        print(f"测试失败: {str(e)}")
