#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放组件自动播放功能
"""

import sys
import os
import time
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from freeassetfilter.components.video_player import VideoPlayer

# 创建一个简单的测试来验证视频自动播放功能
def test_video_autoplay():
    print("=== 测试视频自动播放功能 ===")
    
    # 检查是否提供了视频文件路径
    if len(sys.argv) < 2:
        print("错误: 请提供视频文件路径作为参数")
        print("使用示例: python test_video_autoplay.py test_video.mp4")
        return False
    
    video_path = sys.argv[1]
    
    # 检查视频文件是否存在
    if not os.path.exists(video_path):
        print(f"错误: 视频文件不存在: {video_path}")
        return False
    
    print(f"正在测试视频: {video_path}")
    
    # 创建应用程序实例
    app = QApplication([])
    
    # 创建视频播放器实例
    player = VideoPlayer()
    
    # 设置视频播放器窗口
    player.setWindowTitle("视频自动播放测试")
    player.resize(800, 600)
    player.show()
    
    # 加载视频
    print("正在加载视频...")
    player.load_media(video_path)
    
    # 等待一小段时间让视频加载和播放
    time.sleep(2)
    
    # 检查视频是否正在播放
    print("\n检查视频播放状态...")
    is_playing = player.player_core.is_playing
    print(f"视频播放状态: {'正在播放' if is_playing else '未播放'}")
    
    # 验证测试结果
    if is_playing:
        print("✅ 测试通过：视频在加载后自动播放")
        result = True
    else:
        print("❌ 测试失败：视频在加载后没有自动播放")
        result = False
    
    print("\n=== 测试完成 ===")
    
    # 关闭应用程序
    app.quit()
    
    return result

if __name__ == "__main__":
    test_video_autoplay()
