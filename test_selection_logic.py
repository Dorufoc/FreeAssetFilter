#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间轴选择功能的命令行测试脚本
直接验证核心逻辑，不依赖GUI
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.components.auto_timeline import TimelineEvent

class TimelineSelectionLogicTest:
    """时间轴选择逻辑测试类"""
    
    def __init__(self):
        # 创建测试视频数据
        self.test_videos = self.create_test_videos()
        # 选择范围列表
        self.selected_ranges = []
        # 模糊选中设置
        self.fuzzy_enabled = False
        self.fuzzy_tolerance = 5  # 默认5秒
        self.fuzzy_unit = "秒"
        
    def create_test_videos(self):
        """创建测试用视频数据"""
        videos = []
        
        # 创建10个测试视频，时间范围有重叠和间隔
        base_time = datetime.now()
        
        # 视频1: 0-10秒
        video1 = TimelineEvent("视频1", "设备A", 
                              base_time, 
                              base_time + timedelta(seconds=10))
        video1.add_video("D:\\videos\\video1.mp4")
        videos.append(video1)
        
        # 视频2: 5-15秒（与视频1重叠）
        video2 = TimelineEvent("视频2", "设备A", 
                              base_time + timedelta(seconds=5), 
                              base_time + timedelta(seconds=15))
        video2.add_video("D:\\videos\\video2.mp4")
        videos.append(video2)
        
        # 视频3: 12-20秒（与视频2重叠）
        video3 = TimelineEvent("视频3", "设备B", 
                              base_time + timedelta(seconds=12), 
                              base_time + timedelta(seconds=20))
        video3.add_video("D:\\videos\\video3.mp4")
        videos.append(video3)
        
        # 视频4: 25-35秒（与前面的视频间隔）
        video4 = TimelineEvent("视频4", "设备B", 
                              base_time + timedelta(seconds=25), 
                              base_time + timedelta(seconds=35))
        video4.add_video("D:\\videos\\video4.mp4")
        videos.append(video4)
        
        # 视频5: 30-40秒（与视频4重叠）
        video5 = TimelineEvent("视频5", "设备A", 
                              base_time + timedelta(seconds=30), 
                              base_time + timedelta(seconds=40))
        video5.add_video("D:\\videos\\video5.mp4")
        videos.append(video5)
        
        return videos
    
    def get_fuzzy_seconds(self):
        """将模糊选中设置转换为秒数"""
        if self.fuzzy_unit == "秒":
            return self.fuzzy_tolerance
        elif self.fuzzy_unit == "分钟":
            return self.fuzzy_tolerance * 60
        return 0
    
    def merge_overlapping_ranges(self, ranges):
        """合并重叠的时间范围"""
        if not ranges:
            return []
        
        # 按开始时间排序
        sorted_ranges = sorted(ranges, key=lambda x: x[0])
        merged = [sorted_ranges[0]]
        
        for current in sorted_ranges[1:]:
            last = merged[-1]
            
            # 如果当前范围与上一个范围有重叠，合并它们
            if current[0] <= last[1]:
                new_start = last[0]
                new_end = max(last[1], current[1])
                merged[-1] = (new_start, new_end)
            else:
                merged.append(current)
        
        return merged
    
    def get_videos_in_selected_ranges(self):
        """获取所有选中区域内的视频文件"""
        selected_videos = []
        fuzzy_seconds = self.get_fuzzy_seconds() if self.fuzzy_enabled else 0
        
        # 遍历所有选择范围
        for range_start, range_end in self.selected_ranges:
            # 应用模糊选中（扩展范围）
            fuzzy_start = range_start - timedelta(seconds=fuzzy_seconds)
            fuzzy_end = range_end + timedelta(seconds=fuzzy_seconds)
            
            # 遍历所有视频
            for video in self.test_videos:
                # 检查视频时间范围是否与选择范围有交集
                if (video.end_time >= fuzzy_start) and (video.start_time <= fuzzy_end):
                    # 如果视频尚未被选中，添加到列表中
                    if video not in selected_videos:
                        selected_videos.append(video)
        
        return selected_videos
    
    def run_test(self):
        """运行完整测试"""
        print("="*60)
        print("时间轴选择功能测试")
        print("="*60)
        
        # 显示所有测试视频
        print("\n=== 所有测试视频 ===")
        for i, video in enumerate(self.test_videos):
            duration = (video.end_time - video.start_time).total_seconds()
            print(f"视频 {i+1}: {video.name}")
            print(f"  设备: {video.device}")
            print(f"  时间: {video.start_time.strftime('%H:%M:%S')} - {video.end_time.strftime('%H:%M:%S')}")
            print(f"  时长: {duration:.1f}秒")
            print(f"  路径: {', '.join(video.videos)}")
        
        base_time = datetime.now()
        
        # 测试1: 单范围选择
        print("\n" + "="*40)
        print("测试1: 单范围选择")
        print("="*40)
        self.selected_ranges = [(base_time + timedelta(seconds=8), base_time + timedelta(seconds=18))]
        self.fuzzy_enabled = False
        
        selected = self.get_videos_in_selected_ranges()
        print(f"选择范围: {self.selected_ranges[0][0].strftime('%H:%M:%S')} - {self.selected_ranges[0][1].strftime('%H:%M:%S')}")
        print(f"模糊选中: 禁用")
        print(f"选中视频数: {len(selected)}")
        for video in selected:
            print(f"- {video.name}")
        
        # 测试2: 模糊选中功能
        print("\n" + "="*40)
        print("测试2: 模糊选中功能")
        print("="*40)
        self.fuzzy_enabled = True
        self.fuzzy_tolerance = 3
        self.fuzzy_unit = "秒"
        
        selected = self.get_videos_in_selected_ranges()
        print(f"选择范围: {self.selected_ranges[0][0].strftime('%H:%M:%S')} - {self.selected_ranges[0][1].strftime('%H:%M:%S')}")
        print(f"模糊选中: 启用 ({self.fuzzy_tolerance} {self.fuzzy_unit})")
        print(f"选中视频数: {len(selected)}")
        for video in selected:
            print(f"- {video.name}")
        
        # 测试3: 多范围选择
        print("\n" + "="*40)
        print("测试3: 多范围选择")
        print("="*40)
        self.fuzzy_enabled = False
        self.selected_ranges = [
            (base_time + timedelta(seconds=8), base_time + timedelta(seconds=18)),
            (base_time + timedelta(seconds=32), base_time + timedelta(seconds=42))
        ]
        
        selected = self.get_videos_in_selected_ranges()
        print(f"选择范围数: {len(self.selected_ranges)}")
        for i, (start, end) in enumerate(self.selected_ranges):
            print(f"  范围 {i+1}: {start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')}")
        print(f"模糊选中: 禁用")
        print(f"选中视频数: {len(selected)}")
        for video in selected:
            print(f"- {video.name}")
        
        # 测试4: 范围合并
        print("\n" + "="*40)
        print("测试4: 范围合并")
        print("="*40)
        overlapping_ranges = [
            (base_time + timedelta(seconds=8), base_time + timedelta(seconds=18)),
            (base_time + timedelta(seconds=15), base_time + timedelta(seconds=25)),
            (base_time + timedelta(seconds=30), base_time + timedelta(seconds=40))
        ]
        
        merged = self.merge_overlapping_ranges(overlapping_ranges)
        print(f"合并前范围数: {len(overlapping_ranges)}")
        for start, end in overlapping_ranges:
            print(f"  {start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')}")
        
        print(f"合并后范围数: {len(merged)}")
        for start, end in merged:
            print(f"  {start.strftime('%H:%M:%S')} - {end.strftime('%H:%M:%S')}")
        
        # 使用合并后的范围进行选择
        self.selected_ranges = merged
        selected = self.get_videos_in_selected_ranges()
        print(f"选中视频数: {len(selected)}")
        for video in selected:
            print(f"- {video.name}")
        
        print("\n" + "="*60)
        print("测试完成")
        print("="*60)


def main():
    """主函数"""
    test = TimelineSelectionLogicTest()
    test.run_test()


if __name__ == "__main__":
    main()
