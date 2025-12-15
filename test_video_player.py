#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放器组件
验证进度条和音量控制条是否正常使用CustomValueBar
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QFileDialog
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入视频播放器组件
from freeassetfilter.components.video_player import VideoPlayer


class TestVideoPlayerApp(QMainWindow):
    """
    测试视频播放器应用
    """
    
    def __init__(self):
        super().__init__()
        
        # 设置窗口标题和大小
        self.setWindowTitle("测试视频播放器")
        self.setGeometry(100, 100, 1200, 800)
        
        # 初始化UI
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 创建主布局
        main_layout = QVBoxLayout()
        
        # 创建视频播放器组件
        self.video_player = VideoPlayer()
        main_layout.addWidget(self.video_player, 1)
        
        # 创建控制按钮
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        # 添加文件按钮
        self.open_file_button = QPushButton("打开视频文件")
        self.open_file_button.clicked.connect(self.open_file)
        control_layout.addWidget(self.open_file_button)
        
        # 添加测试按钮
        self.test_controls_button = QPushButton("测试控件类型")
        self.test_controls_button.clicked.connect(self.test_controls)
        control_layout.addWidget(self.test_controls_button)
        
        main_layout.addWidget(control_widget)
        
        # 设置中心部件
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def open_file(self):
        """
        打开视频文件
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", ".", "视频文件 (*.mp4 *.avi *.mov *.wmv *.flv *.mkv);;音频文件 (*.mp3 *.wav *.ogg *.flac *.m4a)"
        )
        
        if file_path:
            # 加载并播放媒体文件
            self.video_player.load_media(file_path)
            self.video_player.play()
    
    def test_controls(self):
        """
        测试控件类型，验证是否使用了正确的CustomValueBar
        """
        from freeassetfilter.widgets.custom_widgets import CustomValueBar
        
        # 检查进度条类型
        progress_type = type(self.video_player.progress_slider).__name__
        volume_type = type(self.video_player.volume_slider).__name__
        
        print(f"进度条类型: {progress_type}")
        print(f"音量条类型: {volume_type}")
        
        # 验证是否为CustomValueBar
        if progress_type == "CustomValueBar" and volume_type == "CustomValueBar":
            print("✓ 所有控制条都已成功使用CustomValueBar")
        else:
            print("✗ 控制条类型不正确")


if __name__ == "__main__":
    # 处理高DPI缩放
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    window = TestVideoPlayerApp()
    window.show()
    sys.exit(app.exec_())
