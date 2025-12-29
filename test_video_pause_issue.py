#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放器在暂停状态下切换视频的问题修复
"""

import os
import sys
import time

# 添加项目根目录到sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from freeassetfilter.core.mpv_player_core import MPVPlayerCore
except ImportError as e:
    print(f"导入MPVPlayerCore失败: {e}")
    sys.exit(1)

def test_pause_then_switch_video():
    """
    测试在暂停状态下切换视频是否正常工作
    """
    print("=== 测试视频播放器在暂停状态下切换视频 ===")
    
    # 创建MPVPlayerCore实例
    player = MPVPlayerCore()
    
    # 模拟一个视频文件路径
    test_video1 = "test_video1.mp4"
    test_video2 = "test_video2.mp4"
    
    print(f"\n1. 设置第一个视频: {test_video1}")
    player.set_media(test_video1)
    
    print("2. 开始播放第一个视频")
    player.play()
    print(f"   播放状态: is_playing={player.is_playing}")
    
    print("3. 暂停第一个视频")
    player.pause()
    print(f"   播放状态: is_playing={player.is_playing}")
    
    print("4. 停止第一个视频")
    player.stop()
    print(f"   播放状态: is_playing={player.is_playing}")
    
    print(f"\n5. 设置第二个视频: {test_video2}")
    player.set_media(test_video2)
    
    print("6. 开始播放第二个视频")
    result = player.play()
    print(f"   播放结果: {result}")
    print(f"   播放状态: is_playing={player.is_playing}")
    
    # 检查修复是否有效
    if player.is_playing:
        print("\n✅ 测试通过: 视频在暂停状态下切换后能正常播放")
    else:
        print("\n❌ 测试失败: 视频在暂停状态下切换后无法正常播放")
    
    # 清理资源
    player.stop()

def test_stop_method_pause_reset():
    """
    测试stop方法是否正确重置了pause属性
    """
    print("\n\n=== 测试stop方法是否正确重置pause属性 ===")
    
    # 创建MPVPlayerCore实例
    player = MPVPlayerCore()
    
    # 模拟一个视频文件路径
    test_video = "test_video.mp4"
    
    # 设置视频并播放
    player.set_media(test_video)
    player.play()
    
    # 暂停视频
    player.pause()
    print(f"1. 暂停后状态: is_playing={player.is_playing}")
    
    # 调用stop方法
    player.stop()
    print(f"2. 停止后状态: is_playing={player.is_playing}")
    
    # 再次设置视频并播放
    player.set_media(test_video)
    result = player.play()
    print(f"3. 重新播放结果: {result}")
    print(f"   重新播放状态: is_playing={player.is_playing}")
    
    # 检查结果
    if player.is_playing:
        print("\n✅ 测试通过: stop方法正确重置了pause属性")
    else:
        print("\n❌ 测试失败: stop方法未能正确重置pause属性")
    
    # 清理资源
    player.stop()

if __name__ == "__main__":
    test_pause_then_switch_video()
    test_stop_method_pause_reset()
    print("\n\n=== 所有测试完成 ===")
