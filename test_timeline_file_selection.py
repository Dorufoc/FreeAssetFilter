#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试时间轴文件选择功能
验证：
1. CSV生成包含视频路径
2. 视频路径解析正确
3. 合并事件后视频路径保留
4. 选中区域文件获取正常
"""

import os
import sys
import tempfile
import shutil
import csv
import json
import datetime
import subprocess

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator
from freeassetfilter.components.auto_timeline import TimelineEvent

# 导入PyQt5用于GUI测试
from PyQt5.QtWidgets import QApplication

# 创建QApplication实例用于GUI测试
global_app = None
if not QApplication.instance():
    global_app = QApplication([])

# 延迟导入AutoTimeline以确保QApplication已创建
from freeassetfilter.components.auto_timeline import AutoTimeline


def create_test_video_file(path, mod_time=None):
    """创建测试视频文件"""
    with open(path, 'w') as f:
        f.write('test video content')
    
    if mod_time:
        # 设置修改时间
        os.utime(path, (mod_time.timestamp(), mod_time.timestamp()))


def create_test_structure(base_dir):
    """创建测试目录结构"""
    # 创建事件目录
    event1_dir = os.path.join(base_dir, "Event1-FX6")
    event2_dir = os.path.join(base_dir, "Event2-A7S3")
    
    os.makedirs(event1_dir, exist_ok=True)
    os.makedirs(event2_dir, exist_ok=True)
    
    # 创建测试视频文件
    test_time = datetime.datetime(2025, 12, 30, 15, 0, 0)
    
    # Event1-FX6目录
    for i in range(5):
        video_path = os.path.join(event1_dir, f"video_{i}.mp4")
        create_test_video_file(video_path, test_time + datetime.timedelta(minutes=i))
    
    # Event2-A7S3目录
    for i in range(3):
        video_path = os.path.join(event2_dir, f"clip_{i}.mp4")
        create_test_video_file(video_path, test_time + datetime.timedelta(minutes=i*2))


def test_csv_generation():
    """测试CSV生成功能"""
    print("\n=== 测试CSV生成功能 ===")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    print(f"创建临时测试目录: {temp_dir}")
    
    try:
        # 创建测试结构
        create_test_structure(temp_dir)
        
        # 创建生成器实例
        generator = FolderTimelineGenerator()
        
        # 生成输出CSV路径
        output_csv = os.path.join(temp_dir, "test_timeline.csv")
        
        # 生成CSV
        success, message = generator.generate_timeline_csv(temp_dir, output_csv)
        
        if not success:
            print(f"CSV生成失败: {message}")
            return False
        
        print(f"CSV生成成功: {message}")
        
        # 检查CSV文件内容
        with open(output_csv, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            print(f"CSV表头: {header}")
            
            # 验证视频路径列存在
            if '视频路径' not in header:
                print("错误：CSV中没有视频路径列")
                return False
            
            # 读取几行数据验证
            rows = list(reader)
            print(f"CSV数据行数: {len(rows)}")
            
            if len(rows) > 0:
                print(f"第一行数据: {rows[0]}")
                print(f"是否包含视频路径: {'是' if rows[0][4] else '否'}")
        
        # 检查映射文件
        mapping_file = os.path.join(generator.data_dir, 'timeline_mapping.json')
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
            
            normalized_dir = os.path.normpath(temp_dir)
            if normalized_dir in mapping_data:
                print(f"映射文件包含源目录: {normalized_dir}")
                print(f"映射到CSV: {mapping_data[normalized_dir]['csv_path']}")
            else:
                print("映射文件中没有找到源目录")
        else:
            print("映射文件不存在")
            
        return True
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)


def test_video_path_parsing():
    """测试视频路径解析功能"""
    print("\n=== 测试视频路径解析功能 ===")
    
    # 创建测试事件
    event1 = TimelineEvent("Event1", "FX6", 
                          datetime.datetime(2025, 12, 30, 15, 0, 0),
                          datetime.datetime(2025, 12, 30, 15, 10, 0))
    event1.add_video("/test/video1.mp4")
    event1.add_video("/test/video2.mp4")
    
    event2 = TimelineEvent("Event1", "FX6", 
                          datetime.datetime(2025, 12, 30, 15, 15, 0),
                          datetime.datetime(2025, 12, 30, 15, 25, 0))
    event2.add_video("/test/video3.mp4")
    
    # 创建测试AutoTimeline实例
    auto_timeline = AutoTimeline()
    auto_timeline.events = [event1, event2]
    
    # 测试合并事件
    auto_timeline.tolerance_unit = "秒"
    auto_timeline.tolerance_multiplier = 60
    auto_timeline.merge_events()
    
    print(f"合并前事件数量: {len(auto_timeline.events)}")
    print(f"合并后事件数量: {len(auto_timeline.merged_events)}")
    
    for merged_event in auto_timeline.merged_events:
        print(f"合并事件 '{merged_event.name}' - '{merged_event.device}'")
        print(f"  时间范围数量: {len(merged_event.time_ranges)}")
        print(f"  视频数量: {len(merged_event.videos)}")
        for video in merged_event.videos:
            print(f"    - {video}")
    
    # 测试选中区域文件获取
    auto_timeline.selected_ranges = [
        (datetime.datetime(2025, 12, 30, 15, 5, 0), datetime.datetime(2025, 12, 30, 15, 20, 0))
    ]
    
    selected_videos = auto_timeline.get_videos_in_selected_ranges()
    print(f"\n选中区域视频数量: {len(selected_videos)}")
    for video in selected_videos:
        print(f"  - {video}")
    
    return len(selected_videos) == 3


def test_fuzzy_selection():
    """测试模糊选择功能"""
    print("\n=== 测试模糊选择功能 ===")
    
    # 创建测试事件
    event1 = TimelineEvent("Event1", "FX6", 
                          datetime.datetime(2025, 12, 30, 15, 0, 0),
                          datetime.datetime(2025, 12, 30, 15, 10, 0))
    event1.add_video("/test/video1.mp4")
    
    event2 = TimelineEvent("Event1", "FX6", 
                          datetime.datetime(2025, 12, 30, 15, 25, 0),
                          datetime.datetime(2025, 12, 30, 15, 35, 0))
    event2.add_video("/test/video2.mp4")
    
    # 创建测试AutoTimeline实例
    auto_timeline = AutoTimeline()
    auto_timeline.events = [event1, event2]
    auto_timeline.merge_events()
    
    # 设置宽容度为30秒
    auto_timeline.tolerance_unit = "秒"
    auto_timeline.tolerance_multiplier = 30
    
    # 选中区域靠近event2，但不重叠
    auto_timeline.selected_ranges = [
        (datetime.datetime(2025, 12, 30, 15, 24, 0), datetime.datetime(2025, 12, 30, 15, 24, 30))
    ]
    
    selected_videos = auto_timeline.get_videos_in_selected_ranges()
    print(f"模糊选择视频数量: {len(selected_videos)}")
    for video in selected_videos:
        print(f"  - {video}")
    
    return len(selected_videos) == 1  # event2应该被选中（因为宽容度30秒）


if __name__ == "__main__":
    print("时间轴文件选择功能测试")
    
    # 运行所有测试
    tests = [
        test_csv_generation,
        test_video_path_parsing,
        test_fuzzy_selection
    ]
    
    results = []
    for i, test in enumerate(tests):
        try:
            result = test()
            results.append(result)
            status = "✓" if result else "✗"
            print(f"\n测试 {i+1}/{len(tests)}: {test.__name__} - {status}")
        except Exception as e:
            results.append(False)
            print(f"\n测试 {i+1}/{len(tests)}: {test.__name__} - ✗ 错误: {str(e)}")
    
    # 统计结果
    passed = sum(results)
    total = len(results)
    
    print(f"\n=== 测试结果 ===")
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("所有测试通过！")
        sys.exit(0)
    else:
        print("部分测试失败！")
        sys.exit(1)
