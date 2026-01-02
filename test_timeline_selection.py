#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间轴选择功能测试脚本
实现时间范围选择、交集检查、模糊选中功能
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QTextEdit, QHBoxLayout, QLabel, QComboBox, QSpinBox
from PyQt5.QtCore import QPoint, Qt
from freeassetfilter.components.auto_timeline import AutoTimeline, TimelineEvent, MergedEvent


class TimelineSelectionTest(QMainWindow):
    """时间轴选择功能测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("时间轴选择功能测试")
        self.setGeometry(100, 100, 1000, 600)
        
        # 创建主控件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 创建布局
        self.main_layout = QVBoxLayout(self.central_widget)
        
        # 创建测试数据
        self.test_videos = self.create_test_videos()
        
        # 创建选择范围列表
        self.selected_ranges = []
        
        # 创建模糊选中设置
        self.fuzzy_enabled = False
        self.fuzzy_tolerance = 5  # 默认5秒
        self.fuzzy_unit = "秒"
        
        # 创建UI组件
        self.create_ui()
        
        # 显示初始视频列表
        self.update_video_list()
        
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
        
        # 视频6: 38-50秒（与视频5重叠）
        video6 = TimelineEvent("视频6", "设备A", 
                              base_time + timedelta(seconds=38), 
                              base_time + timedelta(seconds=50))
        video6.add_video("D:\\videos\\video6.mp4")
        videos.append(video6)
        
        # 视频7: 55-65秒（间隔）
        video7 = TimelineEvent("视频7", "设备B", 
                              base_time + timedelta(seconds=55), 
                              base_time + timedelta(seconds=65))
        video7.add_video("D:\\videos\\video7.mp4")
        videos.append(video7)
        
        # 视频8: 62-70秒（与视频7重叠）
        video8 = TimelineEvent("视频8", "设备A", 
                              base_time + timedelta(seconds=62), 
                              base_time + timedelta(seconds=70))
        video8.add_video("D:\\videos\\video8.mp4")
        videos.append(video8)
        
        # 视频9: 72-80秒（间隔）
        video9 = TimelineEvent("视频9", "设备B", 
                              base_time + timedelta(seconds=72), 
                              base_time + timedelta(seconds=80))
        video9.add_video("D:\\videos\\video9.mp4")
        videos.append(video9)
        
        # 视频10: 78-90秒（与视频9重叠）
        video10 = TimelineEvent("视频10", "设备A", 
                               base_time + timedelta(seconds=78), 
                               base_time + timedelta(seconds=90))
        video10.add_video("D:\\videos\\video10.mp4")
        videos.append(video10)
        
        return videos
    
    def create_ui(self):
        """创建UI组件"""
        # 控制面板
        control_layout = QHBoxLayout()
        
        # 添加选择按钮
        add_range_btn = QPushButton("添加选择范围")
        add_range_btn.clicked.connect(self.add_test_range)
        control_layout.addWidget(add_range_btn)
        
        clear_btn = QPushButton("清空选择范围")
        clear_btn.clicked.connect(self.clear_ranges)
        control_layout.addWidget(clear_btn)
        
        # 模糊选中设置
        fuzzy_layout = QHBoxLayout()
        fuzzy_label = QLabel("模糊选中:")
        fuzzy_layout.addWidget(fuzzy_label)
        
        fuzzy_checkbox = QPushButton("启用")
        fuzzy_checkbox.setCheckable(True)
        fuzzy_checkbox.clicked.connect(self.toggle_fuzzy)
        fuzzy_layout.addWidget(fuzzy_checkbox)
        
        fuzzy_spin = QSpinBox()
        fuzzy_spin.setRange(1, 300)
        fuzzy_spin.setValue(self.fuzzy_tolerance)
        fuzzy_spin.valueChanged.connect(self.set_fuzzy_tolerance)
        fuzzy_layout.addWidget(fuzzy_spin)
        
        fuzzy_unit_combo = QComboBox()
        fuzzy_unit_combo.addItems(["秒", "分钟"])
        fuzzy_unit_combo.currentTextChanged.connect(self.set_fuzzy_unit)
        fuzzy_layout.addWidget(fuzzy_unit_combo)
        
        control_layout.addLayout(fuzzy_layout)
        
        self.main_layout.addLayout(control_layout)
        
        # 视频列表显示
        self.video_text = QTextEdit()
        self.video_text.setReadOnly(True)
        self.main_layout.addWidget(self.video_text)
        
        # 选择范围显示
        self.range_text = QTextEdit()
        self.range_text.setReadOnly(True)
        self.range_text.setMaximumHeight(150)
        self.main_layout.addWidget(self.range_text)
    
    def add_test_range(self):
        """添加测试选择范围"""
        base_time = datetime.now()
        
        # 根据当前选择范围数量添加不同的范围
        if len(self.selected_ranges) == 0:
            # 添加第一个范围: 8-18秒（与视频1、2、3重叠）
            start = base_time + timedelta(seconds=8)
            end = base_time + timedelta(seconds=18)
        elif len(self.selected_ranges) == 1:
            # 添加第二个范围: 32-45秒（与视频4、5、6重叠）
            start = base_time + timedelta(seconds=32)
            end = base_time + timedelta(seconds=45)
        elif len(self.selected_ranges) == 2:
            # 添加第三个范围: 60-75秒（与视频7、8重叠）
            start = base_time + timedelta(seconds=60)
            end = base_time + timedelta(seconds=75)
        elif len(self.selected_ranges) == 3:
            # 添加第四个范围: 75-85秒（与视频9、10重叠）
            start = base_time + timedelta(seconds=75)
            end = base_time + timedelta(seconds=85)
        else:
            # 循环回第一个范围
            self.selected_ranges = []
            return
        
        # 添加选择范围
        self.selected_ranges.append((start, end))
        
        # 合并重叠的范围
        self.selected_ranges = self.merge_overlapping_ranges(self.selected_ranges)
        
        # 更新显示
        self.update_range_list()
        self.update_video_list()
    
    def clear_ranges(self):
        """清空所有选择范围"""
        self.selected_ranges = []
        self.update_range_list()
        self.update_video_list()
    
    def toggle_fuzzy(self, checked):
        """切换模糊选中功能"""
        self.fuzzy_enabled = checked
        self.update_video_list()
    
    def set_fuzzy_tolerance(self, value):
        """设置模糊选中公差"""
        self.fuzzy_tolerance = value
        self.update_video_list()
    
    def set_fuzzy_unit(self, unit):
        """设置模糊选中单位"""
        self.fuzzy_unit = unit
        self.update_video_list()
    
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
    
    def update_video_list(self):
        """更新视频列表显示"""
        self.video_text.clear()
        
        # 显示所有视频
        self.video_text.append("=== 所有视频列表 ===")
        for i, video in enumerate(self.test_videos):
            duration = (video.end_time - video.start_time).total_seconds()
            self.video_text.append(f"视频 {i+1}: {video.name} (设备: {video.device})")
            self.video_text.append(f"  时间范围: {video.start_time.strftime('%H:%M:%S.%f')[:-3]} - {video.end_time.strftime('%H:%M:%S.%f')[:-3]} (时长: {duration:.1f}秒)")
            self.video_text.append(f"  视频路径: {', '.join(video.videos)}")
        
        # 显示选中的视频
        selected_videos = self.get_videos_in_selected_ranges()
        
        self.video_text.append("\n" + "="*50)
        self.video_text.append("=== 选中的视频 ===")
        if selected_videos:
            self.video_text.append(f"共选中 {len(selected_videos)} 个视频:")
            for i, video in enumerate(selected_videos):
                duration = (video.end_time - video.start_time).total_seconds()
                self.video_text.append(f"{i+1}. {video.name} (设备: {video.device})")
                self.video_text.append(f"   时间范围: {video.start_time.strftime('%H:%M:%S.%f')[:-3]} - {video.end_time.strftime('%H:%M:%S.%f')[:-3]}")
                self.video_text.append(f"   视频路径: {', '.join(video.videos)}")
        else:
            self.video_text.append("没有选中任何视频")
    
    def update_range_list(self):
        """更新选择范围显示"""
        self.range_text.clear()
        self.range_text.append("=== 选择范围 ===")
        
        for i, (start, end) in enumerate(self.selected_ranges):
            duration = (end - start).total_seconds()
            self.range_text.append(f"范围 {i+1}:")
            self.range_text.append(f"  开始时间: {start.strftime('%H:%M:%S.%f')[:-3]}")
            self.range_text.append(f"  结束时间: {end.strftime('%H:%M:%S.%f')[:-3]}")
            self.range_text.append(f"  时长: {duration:.1f}秒")
        
        # 显示模糊选中设置
        if self.fuzzy_enabled:
            self.range_text.append(f"\n模糊选中: 已启用 ({self.fuzzy_tolerance} {self.fuzzy_unit})")
        else:
            self.range_text.append("\n模糊选中: 已禁用")


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建并显示测试窗口
    test_window = TimelineSelectionTest()
    test_window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()