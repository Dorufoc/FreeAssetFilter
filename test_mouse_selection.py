#!/usr/bin/env python3
"""
模拟鼠标框选操作测试脚本
用于测试TimelineWidget的鼠标框选功能是否能正确返回选中的视频文件
"""

import sys
from PyQt5.QtWidgets import QApplication, QWidget, QMainWindow
from PyQt5.QtCore import QPoint
import json
import datetime

# 添加项目路径以便导入模块
sys.path.append('.')

# 导入所需的类和函数
from freeassetfilter.components.auto_timeline import (
    TimelineEvent, MergedEvent, TimelineWidget, AutoTimeline
)


def test_mouse_selection():
    """测试鼠标框选功能"""
    print("===== 鼠标框选功能测试 =====\n")
    
    # 创建应用程序实例
    app = QApplication(sys.argv)
    
    # 创建一个父窗口
    parent = QWidget()
    
    # 创建TimelineWidget实例
    timeline_widget = TimelineWidget(parent)
    
    # 读取测试CSV数据
    csv_file = "test_video_timeline.csv"
    print(f"正在读取测试数据文件: {csv_file}")
    
    try:
        # 识别CSV列
        column_indices = identify_csv_columns(csv_file)
        print(f"CSV列索引: {column_indices}")
        
        # 读取并解析CSV数据
        events = read_csv(csv_file, column_indices)
        print(f"成功解析 {len(events)} 个事件")
        
        # 显示解析的事件
        for i, event in enumerate(events):
            print(f"  事件 {i+1}: {event.name} - {event.device}, 开始: {event.start_time}, 结束: {event.end_time}, 视频: {event.videos}")
        
    except Exception as e:
        print(f"读取CSV文件时出错: {e}")
        return
    
    # 合并事件（模仿AutoTimeline中的合并逻辑）
    print("\n正在合并事件...")
    event_groups = {}
    
    for event in events:
        key = (event.name, event.device)
        if key not in event_groups:
            event_groups[key] = []
        event_groups[key].append(event)
    
    merged_events = []
    for (name, device), group_events in event_groups.items():
        merged_event = MergedEvent(name, device)
        
        # 收集所有视频文件信息
        for event in group_events:
            merged_event.add_videos(event.videos)
        
        # 按起始时间排序
        group_events.sort(key=lambda x: x.start_time)
        
        # 简单合并所有连续的时间范围
        current_start = group_events[0].start_time
        current_end = group_events[0].end_time
        
        for event in group_events[1:]:
            # 如果时间连续或重叠，合并
            if event.start_time <= current_end:
                current_end = max(current_end, event.end_time)
            else:
                # 不连续，保存当前范围并开始新范围
                merged_event.add_range(current_start, current_end)
                current_start = event.start_time
                current_end = event.end_time
        
        # 添加最后一个范围
        merged_event.add_range(current_start, current_end)
        merged_events.append(merged_event)
    
    # 显示合并后的事件
    print(f"合并后得到 {len(merged_events)} 个事件")
    for i, event in enumerate(merged_events):
        print(f"  合并事件 {i+1}: {event.name} - {event.device}")
        print(f"    时间范围数量: {len(event.time_ranges)}")
        for j, (start, end) in enumerate(event.time_ranges):
            print(f"      范围 {j+1}: {start} 到 {end}")
        print(f"    视频数量: {len(event.videos)}")
        for video in event.videos:
            print(f"      视频路径: {video}")
    
    # 收集所有唯一的事件名称和设备
    event_names = set()
    devices = set()
    for event in merged_events:
        event_names.add(event.name)
        devices.add(event.device)
    
    print(f"\n唯一事件名称: {event_names}")
    print(f"唯一设备: {devices}")
    
    # 设置TimelineWidget的数据
    print("\n正在设置TimelineWidget数据...")
    timeline_widget.set_data(merged_events, event_names, devices)
    
    # 设置TimelineWidget的参数
    timeline_widget.set_settings(
        pixels_per_unit=10,
        unit_multiplier=60,  # 分钟
        time_margin=10,
        name_column_width=200,
        device_column_width=100,
        event_block_height=30,
        row_spacing=10
    )
    
    # 计算布局（确保min_time和max_time被设置）
    timeline_widget.calculate_layout()
    
    print(f"\nTimelineWidget布局信息:")
    print(f"  min_time: {timeline_widget.min_time}")
    print(f"  max_time: {timeline_widget.max_time}")
    print(f"  total_time: {timeline_widget.total_time}")
    print(f"  content_width: {timeline_widget.content_width}")
    
    # 模拟鼠标框选操作
    print("\n正在模拟鼠标框选操作...")
    
    # 计算框选的起始和结束位置
    # 选择整个时间范围的大致中间部分
    select_start_x = timeline_widget.name_column_width + timeline_widget.device_column_width + timeline_widget.time_margin + 50
    select_end_x = select_start_x + 200
    
    # 确保选择范围在时间轴内
    select_start_x = max(select_start_x, timeline_widget.time_margin)
    select_end_x = min(select_end_x, timeline_widget.content_width)
    
    print(f"模拟框选像素范围: {select_start_x} 到 {select_end_x}")
    
    # 将像素位置转换为时间
    start_time = timeline_widget.get_time_at_position(select_start_x)
    end_time = timeline_widget.get_time_at_position(select_end_x)
    
    print(f"对应的时间范围: {start_time} 到 {end_time}")
    
    # 模拟鼠标按下事件
    timeline_widget.is_selecting = True
    timeline_widget.selection_start = QPoint(select_start_x, 50)
    timeline_widget.selection_end = QPoint(select_end_x, 50)
    
    # 模拟鼠标释放事件
    print("\n模拟鼠标释放事件...")
    timeline_widget.mouseReleaseEvent(None)
    
    # 检查选中的视频文件
    print("\n检查选中的视频文件...")
    selected_videos = timeline_widget.get_videos_in_selected_ranges()
    
    print(f"\n===== 测试结果 ====\n")
    print(f"选中的视频文件数量: {len(selected_videos)}")
    if selected_videos:
        for i, video in enumerate(selected_videos):
            print(f"  {i+1}. {video}")
    else:
        print("没有选中任何视频文件！")
    
    print("\n===== 测试完成 =====")
    
    return selected_videos


if __name__ == "__main__":
    test_mouse_selection()