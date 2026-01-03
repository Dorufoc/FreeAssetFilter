#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试parse_csv方法处理缺少视频路径列的CSV文件
"""

import os
import sys
import csv
import tempfile
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication
from freeassetfilter.components.auto_timeline import AutoTimeline, TimelineEvent

# 创建QApplication实例
app = QApplication(sys.argv)


def test_parse_csv_without_video_path():
    """
    测试处理缺少视频路径列的CSV文件
    """
    print("=== 测试parse_csv处理缺少视频路径列的CSV文件 ===")
    
    # 创建临时CSV文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        writer = csv.writer(f)
        # 写入中文表头（缺少视频路径列）
        writer.writerow(['事件名称', '设备名称', '开始时间', '结束时间'])
        # 写入测试数据
        current_time = datetime.datetime.now()
        writer.writerow(['测试事件', '设备1', 
                        (current_time - datetime.timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S'),
                        (current_time - datetime.timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(['测试事件', '设备1', 
                        (current_time - datetime.timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S'),
                        (current_time - datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow(['测试事件2', '设备2', 
                        (current_time - datetime.timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S'),
                        (current_time - datetime.timedelta(minutes=25)).strftime('%Y-%m-%d %H:%M:%S')])
        
        temp_csv_path = f.name
    
    try:
        # 创建AutoTimeline实例
        timeline = AutoTimeline()
        
        # 设置时间格式
        timeline.time_format = "%Y-%m-%d %H:%M:%S"
        
        # 解析CSV文件
        print(f"\n解析CSV文件: {temp_csv_path}")
        timeline.parse_csv(temp_csv_path)
        
        # 检查事件
        print(f"\n解析后事件数量: {len(timeline.events)}")
        for i, event in enumerate(timeline.events):
            print(f"\n事件 {i+1}:")
            print(f"  名称: {event.name}")
            print(f"  设备: {event.device}")
            print(f"  开始时间: {event.start_time}")
            print(f"  结束时间: {event.end_time}")
            print(f"  视频数量: {len(event.videos)}")
            if event.videos:
                for video in event.videos:
                    print(f"    视频: {video}")
            else:
                print("    无视频路径")
        
        # 测试合并事件
        print(f"\n=== 测试合并事件 ===")
        timeline.merge_events()
        print(f"合并后事件数量: {len(timeline.merged_events)}")
        
        for i, merged_event in enumerate(timeline.merged_events):
            print(f"\n合并事件 {i+1}:")
            print(f"  名称: {merged_event.name}")
            print(f"  设备: {merged_event.device}")
            print(f"  时间范围数量: {len(merged_event.time_ranges)}")
            for j, (start_time, end_time) in enumerate(merged_event.time_ranges):
                print(f"    范围 {j+1}: {start_time} 到 {end_time}")
            print(f"  视频数量: {len(merged_event.videos)}")
            if merged_event.videos:
                for video in merged_event.videos:
                    print(f"    视频: {video}")
            else:
                print("    无视频路径")
        
        print("\n测试完成!")
        
    finally:
        # 删除临时文件
        os.unlink(temp_csv_path)


def test_parse_real_problem_csv():
    """
    测试解析实际的问题CSV文件
    """
    print("\n\n=== 测试解析实际的问题CSV文件 ===")
    
    # 实际问题CSV文件路径
    problem_csv_path = os.path.join(
        os.path.dirname(__file__),
        'data', 'timeline', 'timeline_20251230机关元旦晚会_20260101_211411.csv'
    )
    
    if not os.path.exists(problem_csv_path):
        print(f"CSV文件不存在: {problem_csv_path}")
        return
    
    try:
        # 创建AutoTimeline实例
        timeline = AutoTimeline()
        
        # 设置时间格式
        timeline.time_format = "%Y-%m-%d %H:%M:%S"
        
        # 解析CSV文件
        print(f"\n解析CSV文件: {problem_csv_path}")
        timeline.parse_csv(problem_csv_path)
        
        # 检查事件
        print(f"\n解析后事件数量: {len(timeline.events)}")
        
        # 只显示前5个事件
        for i, event in enumerate(timeline.events[:5]):
            print(f"\n事件 {i+1}:")
            print(f"  名称: {event.name}")
            print(f"  设备: {event.device}")
            print(f"  开始时间: {event.start_time}")
            print(f"  结束时间: {event.end_time}")
            print(f"  视频数量: {len(event.videos)}")
        
        if len(timeline.events) > 5:
            print(f"\n... 省略 {len(timeline.events) - 5} 个事件")
        
        # 测试合并事件
        print(f"\n=== 测试合并事件 ===")
        timeline.merge_events()
        print(f"合并后事件数量: {len(timeline.merged_events)}")
        
        # 只显示前3个合并事件
        for i, merged_event in enumerate(timeline.merged_events[:3]):
            print(f"\n合并事件 {i+1}:")
            print(f"  名称: {merged_event.name}")
            print(f"  设备: {merged_event.device}")
            print(f"  时间范围数量: {len(merged_event.time_ranges)}")
            print(f"  视频数量: {len(merged_event.videos)}")
        
        if len(timeline.merged_events) > 3:
            print(f"\n... 省略 {len(timeline.merged_events) - 3} 个合并事件")
        
        print("\n测试完成!")
        
    except Exception as e:
        print(f"解析CSV文件出错: {str(e)}")


if __name__ == "__main__":
    test_parse_csv_without_video_path()
    test_parse_real_problem_csv()
