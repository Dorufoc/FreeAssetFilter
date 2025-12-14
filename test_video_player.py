#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放器核心功能
验证使用项目内置libvlc.dll的配置是否正常工作
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.core.player_core import PlayerCore

class TestVideoPlayer(QWidget):
    """测试视频播放器窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("测试视频播放器核心")
        self.setGeometry(100, 100, 400, 300)
        
        # 初始化播放器核心
        self.player_core = PlayerCore()
        
        # 创建UI
        self.init_ui()
    
    def init_ui(self):
        """初始化用户界面"""
        layout = QVBoxLayout()
        
        # 状态标签
        self.status_label = QLabel("播放器未初始化")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; color: #333;")
        layout.addWidget(self.status_label)
        
        # 测试初始化按钮
        self.test_init_button = QPushButton("测试初始化")
        self.test_init_button.clicked.connect(self.test_initialization)
        layout.addWidget(self.test_init_button)
        
        # 播放按钮
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.test_play)
        layout.addWidget(self.play_button)
        
        # 暂停按钮
        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(self.test_pause)
        layout.addWidget(self.pause_button)
        
        # 停止按钮
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.test_stop)
        layout.addWidget(self.stop_button)
        
        self.setLayout(layout)
        
    def test_initialization(self):
        """测试播放器初始化"""
        try:
            # 检查播放器核心是否初始化成功
            if self.player_core._instance and self.player_core._player:
                self.status_label.setText("播放器初始化成功")
                self.status_label.setStyleSheet("font-size: 16px; color: #008000;")
            else:
                self.status_label.setText("播放器初始化失败")
                self.status_label.setStyleSheet("font-size: 16px; color: #ff0000;")
        except Exception as e:
            self.status_label.setText(f"初始化测试错误: {str(e)}")
            self.status_label.setStyleSheet("font-size: 16px; color: #ff0000;")
    
    def test_play(self):
        """测试播放功能"""
        try:
            result = self.player_core.play()
            if result:
                self.status_label.setText("播放命令已发送")
            else:
                self.status_label.setText("播放命令失败，可能需要先设置媒体文件")
        except Exception as e:
            self.status_label.setText(f"播放测试错误: {str(e)}")
            self.status_label.setStyleSheet("font-size: 16px; color: #ff0000;")
    
    def test_pause(self):
        """测试暂停功能"""
        try:
            self.player_core.pause()
            self.status_label.setText("暂停命令已发送")
        except Exception as e:
            self.status_label.setText(f"暂停测试错误: {str(e)}")
            self.status_label.setStyleSheet("font-size: 16px; color: #ff0000;")
    
    def test_stop(self):
        """测试停止功能"""
        try:
            self.player_core.stop()
            self.status_label.setText("停止命令已发送")
        except Exception as e:
            self.status_label.setText(f"停止测试错误: {str(e)}")
            self.status_label.setStyleSheet("font-size: 16px; color: #ff0000;")
    
    def closeEvent(self, event):
        """窗口关闭事件，清理资源"""
        try:
            self.player_core.cleanup()
        except Exception as e:
            print(f"清理资源时出错: {str(e)}")
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    test_window = TestVideoPlayer()
    test_window.show()
    sys.exit(app.exec_())
