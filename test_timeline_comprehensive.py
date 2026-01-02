#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动时间轴组件综合测试脚本
包含：
1. 自动加载测试数据
2. 实时显示选中的文件列表
3. 测试各种选择场景（单个范围、多个范围、交叉范围等）
"""

import sys
import os
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QSplitter, QLabel
from PyQt5.QtCore import Qt
from freeassetfilter.components.auto_timeline import AutoTimeline, TimelineEvent

class TimelineTestApp(QWidget):
    """时间轴测试应用"""
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_test_data()
        
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("时间轴组件综合测试")
        self.setMinimumSize(1200, 800)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        
        # 顶部说明
        self.info_label = QLabel("""
使用说明：
1. 使用鼠标左键在时间轴上框选区域
2. 多次框选可以创建多个选中区域
3. 右键点击可以清除所有选中区域
4. 选中的文件会实时显示在右侧面板
5. 可以通过顶部控制栏调整宽容度设置
""")
        self.info_label.setWordWrap(True)
        main_layout.addWidget(self.info_label)
        
        # 分割器
        splitter = QSplitter(Qt.Horizontal)
        
        # 时间轴组件
        self.timeline_window = AutoTimeline()
        splitter.addWidget(self.timeline_window)
        
        # 测试结果面板
        result_panel = QWidget()
        result_layout = QVBoxLayout(result_panel)
        
        # 测试文件显示
        result_layout.addWidget(QLabel("选中的视频文件列表："))
        self.selected_files_text = QTextEdit()
        self.selected_files_text.setReadOnly(True)
        self.selected_files_text.setMinimumHeight(400)
        result_layout.addWidget(self.selected_files_text)
        
        # 测试按钮
        test_buttons_layout = QHBoxLayout()
        
        # 重置按钮
        reset_btn = QPushButton("重置测试数据")
        reset_btn.clicked.connect(self.load_test_data)
        test_buttons_layout.addWidget(reset_btn)
        
        # 清空选中区域按钮
        clear_selections_btn = QPushButton("清空选中区域")
        clear_selections_btn.clicked.connect(self.clear_selections)
        test_buttons_layout.addWidget(clear_selections_btn)
        
        result_layout.addLayout(test_buttons_layout)
        
        splitter.addWidget(result_panel)
        splitter.setSizes([800, 400])
        
        main_layout.addWidget(splitter)
    
    def load_test_data(self):
        """加载测试数据"""
        # 清空之前的事件
        self.timeline_window.events.clear()
        self.timeline_window.merged_events.clear()
        self.timeline_window.event_names.clear()
        self.timeline_window.devices.clear()
        
        # 直接在代码中生成测试事件
        current_time = datetime.datetime.now()
        
        # 创建一些测试事件
        # 事件1 - 设备1
        event1 = TimelineEvent("事件1", "设备1", 
                             current_time - datetime.timedelta(minutes=30),
                             current_time - datetime.timedelta(minutes=20))
        event1.add_video("C:\\test\\video1.mp4")
        event1.add_video("C:\\test\\video2.mp4")
        
        event2 = TimelineEvent("事件1", "设备1", 
                             current_time - datetime.timedelta(minutes=15),
                             current_time - datetime.timedelta(minutes=5))
        event2.add_video("C:\\test\\video3.mp4")
        
        # 事件2 - 设备2
        event3 = TimelineEvent("事件2", "设备2", 
                             current_time - datetime.timedelta(minutes=25),
                             current_time - datetime.timedelta(minutes=15))
        event3.add_video("C:\\test\\video4.mp4")
        event3.add_video("C:\\test\\video5.mp4")
        
        # 事件3 - 设备1
        event4 = TimelineEvent("事件3", "设备1", 
                             current_time - datetime.timedelta(minutes=40),
                             current_time - datetime.timedelta(minutes=35))
        event4.add_video("C:\\test\\video6.mp4")
        
        # 事件4 - 设备3
        event5 = TimelineEvent("事件4", "设备3", 
                             current_time - datetime.timedelta(minutes=45),
                             current_time - datetime.timedelta(minutes=30))
        event5.add_video("C:\\test\\video7.mp4")
        event5.add_video("C:\\test\\video8.mp4")
        event5.add_video("C:\\test\\video9.mp4")
        
        # 事件5 - 设备2
        event6 = TimelineEvent("事件5", "设备2", 
                             current_time - datetime.timedelta(minutes=10),
                             current_time)
        event6.add_video("C:\\test\\video10.mp4")
        
        # 将事件添加到时间轴
        self.timeline_window.events.extend([event1, event2, event3, event4, event5, event6])
        self.timeline_window.event_names.update(["事件1", "事件2", "事件3", "事件4", "事件5"])
        self.timeline_window.devices.update(["设备1", "设备2", "设备3"])
        
        # 合并事件
        self.timeline_window.merge_events()
        
        # 更新视图
        self.timeline_window.update_view()
        
        # 更新测试面板
        self.selected_files_text.append("测试数据已加载完成！")
        self.selected_files_text.append(f"共加载 {len(self.timeline_window.events)} 个原始事件，合并后为 {len(self.timeline_window.merged_events)} 个事件")
        
        # 显示所有视频文件
        all_videos = set()
        for event in self.timeline_window.merged_events:
            for video in event.videos:
                all_videos.add(video)
        self.selected_files_text.append(f"总共有 {len(all_videos)} 个视频文件")
        self.selected_files_text.append("\n可用测试文件列表：")
        for i, video in enumerate(sorted(all_videos), 1):
            self.selected_files_text.append(f"{i}. {video}")
    
    def clear_selections(self):
        """清空所有选中区域"""
        self.timeline_window.timeline_widget.selected_ranges.clear()
        self.timeline_window.timeline_widget.update()
        self.selected_files_text.append("\n已清空所有选中区域")

def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 创建并显示测试应用窗口
    test_app = TimelineTestApp()
    test_app.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()