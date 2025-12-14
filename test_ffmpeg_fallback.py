#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试FFmpeg错误回退机制
验证当FFmpeg出现错误时，VLC能正常运行
"""

import os
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel, QComboBox
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.components.video_player import VideoPlayer


class TestWindow(QMainWindow):
    """
    测试窗口，用于验证FFmpeg错误回退机制
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("FFmpeg错误回退测试")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建布局
        layout = QVBoxLayout(central_widget)
        
        # 添加标题
        title = QLabel("FFmpeg错误回退测试 - 验证VLC正常运行")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)
        
        # 创建控制面板
        control_layout = QVBoxLayout()
        
        # 添加播放器切换选择
        self.player_combo = QComboBox()
        self.player_combo.addItem("VLC播放器", "vlc")
        self.player_combo.addItem("FFmpeg播放器", "ff")
        self.player_combo.currentIndexChanged.connect(self.on_player_change)
        control_layout.addWidget(QLabel("选择播放器内核:"))
        control_layout.addWidget(self.player_combo)
        
        # 添加状态标签
        self.status_label = QLabel("初始化测试...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("margin: 10px; color: blue;")
        control_layout.addWidget(self.status_label)
        
        layout.addLayout(control_layout)
        
        # 创建视频播放器
        self.video_player = VideoPlayer()
        self.video_player.setMinimumSize(800, 600)
        layout.addWidget(self.video_player)
        
        # 初始化测试
        self.status_label.setText("测试初始化完成，选择播放器开始测试")
        print("测试窗口已显示 - 选择播放器内核开始测试")
    
    def on_player_change(self, index):
        """
        切换播放器内核，测试错误回退机制
        """
        player_name = self.player_combo.currentText()
        player_id = self.player_combo.currentData()
        
        self.status_label.setText(f"正在切换到: {player_name}...")
        print(f"\n切换到 {player_name} ({player_id})")
        
        try:
            # 切换播放器内核
            self.video_player.switch_player_engine(player_id, player_name)
            self.status_label.setText(f"成功切换到: {player_name}")
            print(f"成功切换到 {player_name}")
        except Exception as e:
            self.status_label.setText(f"切换到 {player_name} 失败: {e}")
            print(f"切换到 {player_name} 失败: {e}")
            # 检查是否回退到VLC
            if hasattr(self.video_player, '_current_player'):
                current_player = self.video_player._current_player
                self.status_label.setText(f"切换失败，当前播放器: {'VLC' if current_player == 'vlc' else 'FFmpeg'}")
                print(f"当前播放器: {'VLC' if current_player == 'vlc' else 'FFmpeg'}")


if __name__ == "__main__":
    """
    主测试函数
    """
    print("启动FFmpeg错误回退测试...")
    print("注意：测试期间应显示VLC能正常运行，FFmpeg错误被忽略")
    print("=" * 60)
    
    app = QApplication(sys.argv)
    
    window = TestWindow()
    window.show()
    
    sys.exit(app.exec_())
