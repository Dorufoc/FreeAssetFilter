#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放器中的滚动文本控件 - 使用真实音频文件
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer

# 导入视频播放器组件
from freeassetfilter.components.video_player import VideoPlayer


class TestWindow(QWidget):
    """测试窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频播放器滚动文本测试 - 真实音频")
        self.setGeometry(100, 100, 800, 600)
        
        # 初始化UI
        self._init_ui()
    
    def _init_ui(self):
        """初始化测试界面"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建视频播放器组件
        self.video_player = VideoPlayer(self)
        layout.addWidget(self.video_player)
        
        # 使用真实音频文件路径（用于测试SVG图标显示）
        # 这个文件没有封面图片，会显示SVG耳机图标
        audio_file = r"E:\Temps\Desktop\1月25日.MP3"
        
        if os.path.exists(audio_file):
            print(f"找到音频文件: {audio_file}")
            # 延迟播放，确保UI已完全初始化
            QTimer.singleShot(500, lambda: self.play_audio(audio_file))
        else:
            print(f"音频文件不存在: {audio_file}")
            # 使用模拟文件名测试
            QTimer.singleShot(500, self.test_with_mock_file)
    
    def play_audio(self, audio_file):
        """播放音频文件"""
        print(f"\n开始播放: {audio_file}")
        self.video_player.load_media(audio_file)
        self.video_player.play()
        
        # 延迟检查滚动文本状态
        QTimer.singleShot(1000, self.check_scrolling_text)
    
    def test_with_mock_file(self):
        """使用模拟文件测试"""
        print("\n使用模拟文件测试...")
        
        # 设置一个很长的文件名
        long_name = "这是一个非常非常长的音频文件名，用于测试滚动文本控件的自动滚动功能是否正常工作"
        self.video_player._current_file_path = long_name + ".mp3"
        self.video_player._audio_cover_data = None
        
        # 触发更新
        self.video_player._update_audio_icon()
        
        # 显示音频界面
        self.video_player.audio_stacked_widget.show()
        
        # 延迟检查
        QTimer.singleShot(500, self.check_scrolling_text)
    
    def check_scrolling_text(self):
        """检查滚动文本状态"""
        print("\n=== 滚动文本状态 ===")
        
        vp = self.video_player
        
        # 检查 scrolling_text 控件
        if hasattr(vp, 'scrolling_text') and vp.scrolling_text:
            st = vp.scrolling_text
            print(f"scrolling_text:")
            print(f"  - 文本: {st.get_text()}")
            print(f"  - 宽度: {st.width()}")
            print(f"  - 高度: {st.height()}")
            print(f"  - 可见性: {st.isVisible()}")
            print(f"  - 是否滚动: {st._is_scrolling}")
            print(f"  - 是否滚动中: {st.is_scrolling_active()}")
        else:
            print("scrolling_text 不存在!")
        
        # 检查父容器
        if vp.audio_file_scroll_area:
            print(f"\naudio_file_scroll_area:")
            print(f"  - 宽度: {vp.audio_file_scroll_area.width()}")
            print(f"  - 高度: {vp.audio_file_scroll_area.height()}")
            print(f"  - 可见性: {vp.audio_file_scroll_area.isVisible()}")


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置全局字体
    from PyQt5.QtGui import QFont
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    app.default_font_size = 14
    app.dpi_scale_factor = 1.0
    
    # 创建测试窗口
    window = TestWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
