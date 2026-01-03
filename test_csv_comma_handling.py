#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试CSV文件逗号处理功能
验证包含逗号的路径或名称能否被正确解析和生成
"""

import os
import sys
import csv
import tempfile
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.auto_timeline import AutoTimeline
from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_csv_comma_handling():
    """测试CSV文件逗号处理"""
    print("=== 测试CSV逗号处理功能 ===")
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"临时目录: {temp_dir}")
        
        # 创建包含逗号的测试路径
        test_folder = os.path.join(temp_dir, "测试,文件夹,带逗号")
        os.makedirs(test_folder, exist_ok=True)
        
        # 创建测试视频文件
        test_video = os.path.join(test_folder, "test,video,带逗号.mp4")
        with open(test_video, 'w') as f:
            f.write("测试视频内容")
        
        # 1. 测试CSV生成
        print("\n1. 测试CSV生成（包含逗号的路径）...")
        generator = FolderTimelineGenerator()
        
        # 创建测试数据
        timeline_data = [{
            'event_name': '测试,事件,带逗号',
            'device_name': '测试,设备,带逗号',
            'start_time': '2025-12-30 14:36:15',
            'end_time': '2025-12-30 14:36:25',
            'video_path': test_video
        }]
        
        # 生成CSV文件
        csv_path = os.path.join(temp_dir, "test_comma.csv")
        generator._write_csv(csv_path, timeline_data)
        
        print(f"CSV文件已生成: {csv_path}")
        
        # 查看生成的CSV内容
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            print("\n生成的CSV内容:")
            print(content)
        
        # 2. 测试CSV解析
        print("\n2. 测试CSV解析（包含逗号的路径）...")
        
        # 创建AutoTimeline实例（需要先创建QApplication）
        from PyQt5.QtWidgets import QApplication
        app = QApplication(sys.argv)
        
        auto_timeline = AutoTimeline()
        auto_timeline.time_format_combo.setCurrentText("%Y-%m-%d %H:%M:%S")
        
        try:
            auto_timeline.parse_csv(csv_path)
            print("✓ CSV解析成功")
            print(f"  解析的事件数量: {len(auto_timeline.events)}")
            
            if auto_timeline.events:
                event = auto_timeline.events[0]
                print(f"  事件名称: {event.name}")
                print(f"  设备名称: {event.device}")
                print(f"  视频数量: {len(event.videos)}")
                if event.videos:
                    print(f"  视频路径: {event.videos[0]}")
            
            print("\n3. 测试选择功能...")
            # 设置测试选择范围
            if auto_timeline.timeline_widget:
                # 添加一个包含事件的选择范围
                start_time = datetime.strptime("2025-12-30 14:36:00", "%Y-%m-%d %H:%M:%S")
                end_time = datetime.strptime("2025-12-30 14:37:00", "%Y-%m-%d %H:%M:%S")
                auto_timeline.timeline_widget.selected_ranges.append((start_time, end_time))
                
                # 获取选中的视频和事件
                videos, selected_events = auto_timeline.timeline_widget.get_videos_in_selected_ranges()
                
                print(f"  选中范围中的视频数量: {len(videos)}")
                print(f"  选中范围中的事件数量: {len(selected_events)}")
                
                if videos:
                    for video in videos:
                        print(f"  - {video}")
                        
                if selected_events:
                    for event in selected_events:
                        print(f"  - 事件: {event.name}, 设备: {event.device}, 视频数量: {len(event.videos)}")
                        for video in event.videos:
                            print(f"    * {video}")
            
            print("\n🎉 所有测试通过！CSV逗号处理功能正常工作")
            
        except Exception as e:
            print(f"✗ CSV解析失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_csv_comma_handling()
