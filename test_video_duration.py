#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频时长获取功能
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.core.timeline_generator import get_video_duration


def test_video_duration():
    """测试视频时长获取功能"""
    print("=== 测试视频时长获取功能 ===")
    
    # 测试不同的视频文件（如果有的话）
    # 这里可以替换为你实际的视频文件路径
    test_videos = [
        # 添加你的测试视频文件路径
        # 例如: "c:\\path\\to\\your\\video.mp4"
    ]
    
    # 如果没有提供测试视频，使用一些示例
    if not test_videos:
        print("没有提供测试视频文件，使用模拟测试...")
        
        # 测试函数本身是否能正常导入和执行
        print(f"测试默认返回值: {get_video_duration('nonexistent_file.mp4')}")
        return
    
    for video_path in test_videos:
        if os.path.exists(video_path):
            print(f"\n测试视频: {os.path.basename(video_path)}")
            print(f"路径: {video_path}")
            
            try:
                duration = get_video_duration(video_path)
                print(f"获取的时长: {duration:.2f} 秒")
            except Exception as e:
                print(f"获取时长失败: {e}")
        else:
            print(f"\n视频不存在: {video_path}")


if __name__ == "__main__":
    test_video_duration()
