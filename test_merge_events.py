#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试多个事件的合并功能
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication
from freeassetfilter.components.auto_timeline import AutoTimeline

# 创建一个简单的测试应用来测试合并功能
class MergeTestApp:
    def __init__(self):
        self.timeline = AutoTimeline()
        
    def generate_test_events(self):
        """生成测试事件数据"""
        # 创建多个连续的事件
        events = []
        base_time = datetime.datetime(2023, 1, 1, 0, 0, 0)
        
        # 创建第一个事件序列（连续的多个视频片段）
        for i in range(10):
            event = type('Event', (), {
                'name': '测试视频序列1',
                'device': 'Camera1',
                'start_time': base_time + datetime.timedelta(seconds=i*60),
                'end_time': base_time + datetime.timedelta(seconds=(i+1)*60 + 10)
            })
            events.append(event)
        
        # 创建第二个事件序列（有一些重叠）
        for i in range(10):
            event = type('Event', (), {
                'name': '测试视频序列2',
                'device': 'Camera2',
                'start_time': base_time + datetime.timedelta(seconds=30 + i*60),
                'end_time': base_time + datetime.timedelta(seconds=90 + i*60)
            })
            events.append(event)
        
        return events
    
    def test_merge(self):
        """测试合并功能"""
        print("开始测试合并功能...")
        
        # 设置测试事件
        events = self.generate_test_events()
        print(f"原始事件数量: {len(events)}")
        
        # 保存原始事件
        self.timeline.events = events
        
        # 提取事件名称和设备
        self.timeline.event_names = list(set(e.name for e in events))
        self.timeline.devices = list(set(e.device for e in events))
        
        # 设置宽容度单位
        self.timeline.tolerance_unit = "秒"
        self.timeline.tolerance_multiplier = 1
        
        # 执行合并
        self.timeline.merge_events()
        
        # 显示合并结果
        print(f"合并后事件数量: {len(self.timeline.merged_events)}")
        
        for i, merged_event in enumerate(self.timeline.merged_events):
            print(f"\n合并事件 {i+1}:")
            print(f"  名称: {merged_event.name}")
            print(f"  设备: {merged_event.device}")
            print(f"  时间范围数量: {len(merged_event.time_ranges)}")
            print(f"  总时长: {merged_event.duration():.2f}秒")
            
            for j, (start, end) in enumerate(merged_event.time_ranges):
                duration = (end - start).total_seconds()
                print(f"  范围 {j+1}: {start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')} ({duration:.2f}秒)")
        
        print("\n合并测试完成！")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_app = MergeTestApp()
    test_app.test_merge()
    sys.exit(0)
