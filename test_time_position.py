#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试时间位置转换功能
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import datetime
from PyQt5.QtCore import QPoint
from freeassetfilter.components.auto_timeline import TimelineWidget

# 测试get_time_at_position方法
def test_get_time_at_position():
    print("测试get_time_at_position方法...")
    
    # 创建一个TimelineWidget实例
    timeline_widget = TimelineWidget()
    
    # 设置测试数据
    timeline_widget.min_time = datetime.datetime(2025, 12, 30, 15, 24, 0)
    timeline_widget.max_time = datetime.datetime(2025, 12, 30, 15, 25, 0)
    timeline_widget.total_time = (timeline_widget.max_time - timeline_widget.min_time).total_seconds()
    timeline_widget.time_margin = 10
    timeline_widget.content_width = 1000
    
    # 测试不同位置的时间计算
    test_positions = [10, 500, 1000]
    for pos in test_positions:
        time = timeline_widget.get_time_at_position(pos)
        print(f"位置 {pos}px 对应的时间: {time}")

# 测试CSV文件解析
def test_csv_parsing():
    print("\n测试CSV文件解析...")
    
    import csv
    
    # 读取测试CSV文件
    csv_path = "C:\\Users\\Dorufoc\\Desktop\\code\\FreeAssetFilter\\test_video_timeline.csv"
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        print(f"CSV表头: {header}")
        
        # 尝试识别列
        name_idx = -1
        device_idx = -1
        start_idx = -1
        end_idx = -1
        video_idx = -1
        
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
                video_idx = i
                print(f"识别到视频路径列: {col} (索引: {i})")
        
        print(f"最终识别的列索引: name_idx={name_idx}, device_idx={device_idx}, start_idx={start_idx}, end_idx={end_idx}, video_idx={video_idx}")
        
        # 读取几行数据
        print("\nCSV数据行:")
        for i, row in enumerate(reader):
            if i >= 5:  # 只显示前5行
                break
            print(f"行 {i+1}: {row}")
            
            # 解析时间和视频路径
            if start_idx != -1 and end_idx != -1 and len(row) > max(start_idx, end_idx):
                try:
                    start_time = datetime.datetime.strptime(row[start_idx].strip(), "%Y-%m-%d %H:%M:%S")
                    end_time = datetime.datetime.strptime(row[end_idx].strip(), "%Y-%m-%d %H:%M:%S")
                    print(f"  时间范围: {start_time} 到 {end_time}")
                except ValueError as e:
                    print(f"  时间解析错误: {e}")
            
            if video_idx != -1 and len(row) > video_idx:
                video_path = row[video_idx].strip()
                print(f"  视频路径: {video_path}")

if __name__ == "__main__":
    test_get_time_at_position()
    test_csv_parsing()
