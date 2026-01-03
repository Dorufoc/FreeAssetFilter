#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动时间轴组件测试脚本
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication
from freeassetfilter.components.auto_timeline import AutoTimeline, TimelineEvent

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建并显示自动时间轴窗口
    timeline_window = AutoTimeline()
    
    # 直接在代码中生成测试事件
    current_time = datetime.datetime.now()
    
    # 创建一些测试事件
    event1 = TimelineEvent("事件1", "设备1", 
                         current_time - datetime.timedelta(minutes=30),
                         current_time - datetime.timedelta(minutes=20))
    event1.add_video("C:\\test\\video1.mp4")
    event1.add_video("C:\\test\\video2.mp4")
    
    event2 = TimelineEvent("事件1", "设备1", 
                         current_time - datetime.timedelta(minutes=15),
                         current_time - datetime.timedelta(minutes=5))
    event2.add_video("C:\\test\\video3.mp4")
    
    event3 = TimelineEvent("事件2", "设备2", 
                         current_time - datetime.timedelta(minutes=25),
                         current_time - datetime.timedelta(minutes=15))
    event3.add_video("C:\\test\\video4.mp4")
    event3.add_video("C:\\test\\video5.mp4")
    
    event4 = TimelineEvent("事件3", "设备1", 
                         current_time - datetime.timedelta(minutes=40),
                         current_time - datetime.timedelta(minutes=35))
    event4.add_video("C:\\test\\video6.mp4")
    
    # 将事件添加到时间轴
    timeline_window.events.extend([event1, event2, event3, event4])
    timeline_window.event_names.update(["事件1", "事件2", "事件3"])
    timeline_window.devices.update(["设备1", "设备2"])
    
    # 合并事件
    timeline_window.merge_events()
    
    # 添加调试信息：打印合并事件和视频文件
    print("\n=== 调试信息 ===")
    print(f"合并后事件数量: {len(timeline_window.merged_events)}")
    for i, event in enumerate(timeline_window.merged_events):
        print(f"\n事件 {i+1}:")
        print(f"  名称: {event.name}")
        print(f"  设备: {event.device}")
        print(f"  时间范围数量: {len(event.time_ranges)}")
        for j, (start_time, end_time) in enumerate(event.time_ranges):
            print(f"    范围 {j+1}: {start_time} 到 {end_time}")
        print(f"  视频数量: {len(event.videos)}")
        for video in event.videos:
            print(f"    视频: {video}")
    
    # 更新视图
    timeline_window.update_view()
    
    # 直接测试选中文件功能 - 添加一个测试范围
    current_time = datetime.datetime.now()
    test_start = current_time - datetime.timedelta(minutes=40)
    test_end = current_time - datetime.timedelta(minutes=5)
    
    # 设置测试选中范围
    timeline_window.timeline_widget.selected_ranges.append((test_start, test_end))
    
    # 调用选中文件功能并打印结果
    print("\n=== 测试选中文件功能 ===")
    print(f"测试时间范围: {test_start} 到 {test_end}")
    selected_videos = timeline_window.timeline_widget.get_videos_in_selected_ranges()
    print(f"获取到的视频数量: {len(selected_videos)}")
    for video in selected_videos:
        print(f"  {video}")
    
    timeline_window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()