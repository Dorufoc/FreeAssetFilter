#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试分离窗口布局修改
验证视频窗口控制栏的浮动布局效果
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QColor, QPainter, QBrush


class TestStackedLayout(QWidget):
    """测试堆叠布局"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("分离窗口布局测试")
        self.setGeometry(100, 100, 800, 600)
        self.setStyleSheet("background-color: #000000;")
        
        # 创建堆叠容器
        self.stack_container = QWidget(self)
        self.stack_container.setGeometry(self.rect())
        self.stack_container.setStyleSheet("background-color: transparent;")
        
        # 第0层：视频区域（黑色背景模拟）
        self.video_frame = QWidget(self.stack_container)
        self.video_frame.setStyleSheet("background-color: #1a1a1a;")
        self.video_frame.setGeometry(self.stack_container.rect())
        
        # 添加视频标签
        video_label = QLabel("视频内容区域 (第0层 - 填满整个显示区域)", self.video_frame)
        video_label.setStyleSheet("color: white; font-size: 16px; background-color: transparent;")
        video_label.setAlignment(Qt.AlignCenter)
        video_layout = QVBoxLayout(self.video_frame)
        video_layout.addWidget(video_label)
        
        # 第1层：控制栏（半透明浮动）
        self.control_bar = QWidget(self.stack_container)
        self.control_bar.setStyleSheet("""
            background-color: #2D2D2DCC;
            border: none;
            border-radius: 8px;
        """)
        self.control_bar.setFixedHeight(60)
        
        # 添加控制按钮模拟
        control_layout = QHBoxLayout(self.control_bar)
        control_layout.setContentsMargins(10, 5, 10, 5)
        
        play_btn = QPushButton("播放/暂停")
        play_btn.setStyleSheet("color: white; background-color: #444;")
        control_layout.addWidget(play_btn)
        
        progress_label = QLabel("进度条区域")
        progress_label.setStyleSheet("color: white; background-color: transparent;")
        control_layout.addWidget(progress_label, 1)
        
        volume_btn = QPushButton("音量")
        volume_btn.setStyleSheet("color: white; background-color: #444;")
        control_layout.addWidget(volume_btn)
        
        # 初始位置
        self.update_control_position()
    
    def resizeEvent(self, event):
        """窗口大小变化时更新布局"""
        super().resizeEvent(event)
        self.stack_container.setGeometry(self.rect())
        self.video_frame.setGeometry(self.stack_container.rect())
        self.update_control_position()
    
    def update_control_position(self):
        """更新控制栏位置 - 固定在底部浮动显示"""
        container_width = self.stack_container.width()
        container_height = self.stack_container.height()
        control_height = self.control_bar.height()
        
        # 边距
        margin = 20
        bottom_margin = 30
        
        # 控制栏宽度 = 容器宽度 - 左右边距
        control_width = container_width - 2 * margin
        
        # 控制栏位置：水平居中，底部对齐带边距
        x = margin
        y = container_height - control_height - bottom_margin
        
        self.control_bar.setGeometry(x, y, control_width, control_height)


def main():
    app = QApplication(sys.argv)
    
    # 测试窗口
    window = TestStackedLayout()
    window.show()
    
    print("=" * 60)
    print("分离窗口布局测试")
    print("=" * 60)
    print("布局结构：")
    print("  - 第0层：视频内容区域（深灰色）- 填满整个显示区域")
    print("  - 第1层：控制栏（半透明深灰色）- 固定在底部浮动显示")
    print("=" * 60)
    print("验证要点：")
    print("  1. 视频区域是否填满整个窗口？")
    print("  2. 控制栏是否在底部浮动显示？")
    print("  3. 调整窗口大小时布局是否正确更新？")
    print("  4. 控制栏是否有半透明效果？")
    print("=" * 60)
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
