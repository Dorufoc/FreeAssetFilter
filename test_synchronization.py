#!/usr/bin/env python3
"""
测试视频播放器对比预览的同步功能
"""

import sys
import os
import time
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel, QHBoxLayout
from PyQt5.QtCore import QTimer

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.components.video_player import VideoPlayer

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频播放器同步测试")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建主布局
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        
        # 创建视频播放器
        self.video_player = VideoPlayer()
        main_layout.addWidget(self.video_player)
        
        # 创建控制按钮
        control_layout = QHBoxLayout()
        
        # 打开文件按钮
        self.open_button = QPushButton("打开视频文件")
        self.open_button.clicked.connect(self.open_file)
        control_layout.addWidget(self.open_button)
        
        # 切换对比模式按钮
        self.compare_button = QPushButton("切换对比模式")
        self.compare_button.clicked.connect(self.toggle_comparison)
        control_layout.addWidget(self.compare_button)
        
        # 播放/暂停按钮
        self.play_button = QPushButton("播放/暂停")
        self.play_button.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_button)
        
        # 同步状态标签
        self.status_label = QLabel("同步状态: 准备就绪")
        control_layout.addWidget(self.status_label)
        
        main_layout.addLayout(control_layout)
        
        self.setCentralWidget(main_widget)
        
        # 创建定时器定期检查同步状态
        self.sync_timer = QTimer()
        self.sync_timer.timeout.connect(self.check_synchronization)
        self.sync_timer.start(1000)  # 每秒检查一次
        
        # 记录最后一次同步时间
        self.last_sync_time = time.time()
        
    def open_file(self):
        """打开视频文件"""
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", "/", 
            "视频文件 (*.mp4 *.mov *.mkv *.avi *.wmv *.flv *.webm);;所有文件 (*.*)"
        )
        if file_path:
            self.video_player.open_file(file_path)
            self.status_label.setText(f"已打开文件: {os.path.basename(file_path)}")
    
    def toggle_comparison(self):
        """切换对比模式"""
        self.video_player.toggle_comparison()
        mode = "对比预览" if self.video_player.comparison_mode else "普通模式"
        self.status_label.setText(f"当前模式: {mode}")
    
    def toggle_play(self):
        """切换播放/暂停"""
        if self.video_player.player_core:
            if self.video_player.player_core.is_playing:
                self.video_player.player_core.pause()
            else:
                self.video_player.player_core.play()
    
    def check_synchronization(self):
        """检查两个播放器的同步状态"""
        if not hasattr(self.video_player, 'comparison_mode') or not self.video_player.comparison_mode:
            return
            
        if hasattr(self.video_player, 'player_core') and hasattr(self.video_player, 'original_player_core'):
            main_core = self.video_player.player_core
            original_core = self.video_player.original_player_core
            
            if main_core and original_core:
                # 获取两个播放器的时间
                main_time = main_core.time
                original_time = original_core.time
                
                # 获取播放状态
                main_playing = main_core.is_playing
                original_playing = original_core.is_playing
                
                # 计算时间差
                time_diff = abs(main_time - original_time)
                
                # 更新状态标签
                status_text = f"同步状态: 主播放器={main_time/1000:.2f}s, 原始播放器={original_time/1000:.2f}s, 差异={time_diff/1000:.2f}s"
                status_text += f" | 主播放={main_playing}, 原始播放={original_playing}"
                
                # 如果差异大于2秒，显示警告
                if time_diff > 2000:
                    status_text += " ⚠️ 差异较大"
                else:
                    status_text += " ✓ 同步正常"
                    
                self.status_label.setText(status_text)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec_())
