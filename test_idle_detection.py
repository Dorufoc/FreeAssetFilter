#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试MPVPlayerCore的idle事件异常检测功能
"""

import sys
import os
import time
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtCore import QTimer, QThread

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 导入需要的模块
from freeassetfilter.components.unified_previewer import UnifiedPreviewer
from freeassetfilter.components.video_player import VideoPlayer
from freeassetfilter.core.mpv_player_core import MPVPlayerCore

class TestIdleDetection(QMainWindow):
    """
    测试idle事件异常检测的主窗口类
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("MPV Idle事件异常检测测试")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        
        # 创建统一预览器实例
        self.unified_previewer = UnifiedPreviewer()
        layout.addWidget(self.unified_previewer)
        
        # 创建测试按钮
        from PyQt5.QtWidgets import QPushButton
        self.test_button = QPushButton("测试Idle事件异常检测")
        self.test_button.clicked.connect(self.test_idle_detection)
        layout.addWidget(self.test_button)
        
        # 初始化应用程序的dpi_scale_factor属性
        app = QApplication.instance()
        if not hasattr(app, 'dpi_scale_factor'):
            app.dpi_scale_factor = 1.0
        if not hasattr(app, 'global_font'):
            from PyQt5.QtGui import QFont
            app.global_font = QFont()
        
    def test_idle_detection(self):
        """
        测试idle事件异常检测功能
        """
        print("=== 开始测试Idle事件异常检测功能 ===")
        
        # 首先加载一个视频文件
        # 请将这里的路径替换为实际的测试视频路径
        test_video_path = r"E:/DFTP/挑战杯视频/test_video.mp4"
        
        if not os.path.exists(test_video_path):
            print(f"错误: 测试视频文件不存在: {test_video_path}")
            print("请将test_video_path变量设置为实际存在的视频文件路径")
            return
        
        # 模拟文件信息
        file_info = {
            "path": test_video_path,
            "suffix": "mp4",
            "is_dir": False,
            "name": "test_video.mp4",
            "size": os.path.getsize(test_video_path)
        }
        
        # 设置文件进行预览
        print(f"加载测试视频: {test_video_path}")
        self.unified_previewer.set_file(file_info)
        
        # 等待视频加载完成
        time.sleep(2)
        
        # 模拟多个idle事件，测试异常检测
        print("模拟快速连续的idle事件...")
        
        # 直接调用统一预览器的_on_video_idle_event方法，模拟idle事件
        for i in range(10):
            print(f"模拟第{i+1}个idle事件")
            self.unified_previewer._on_video_idle_event()
            time.sleep(0.1)  # 100ms间隔
        
        print("=== 测试完成 ===")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestIdleDetection()
    window.show()
    sys.exit(app.exec_())
