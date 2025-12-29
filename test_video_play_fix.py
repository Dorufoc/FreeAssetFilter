#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放功能修复
验证视频能否正确开始播放
"""

import os
import sys
import time

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.core.mpv_player_core import MPVPlayerCore

def test_video_play_fix():
    """
    测试视频播放功能修复
    """
    print("=== 测试视频播放功能修复 ===")
    
    player = MPVPlayerCore()
    
    # 测试中文路径处理
    test_path = "C:/Users/Dorufoc/Desktop/测试视频.mp4"
    processed_path = player.process_chinese_path(test_path)
    print(f"\n[测试] 中文路径处理测试:")
    print(f"  原始路径: {test_path}")
    print(f"  处理后: {processed_path}")
    
    # 检查是否有测试视频
    test_videos = [
        "test_video.mp4",  # 假设当前目录有测试视频
        "C:/Users/Dorufoc/Desktop/test_video.mp4"  # 假设桌面有测试视频
    ]
    
    actual_video = None
    for video_path in test_videos:
        if os.path.exists(video_path):
            actual_video = video_path
            break
    
    if not actual_video:
        print(f"\n[测试] 警告: 未找到实际测试视频，使用模拟测试")
        actual_video = "test_video.mp4"
    
    print(f"\n[测试] 使用测试视频: {actual_video}")
    
    # 测试1: 设置媒体
    print("\n=== 测试1: 设置媒体 ===")
    result = player.set_media(actual_video)
    print(f"[测试] 设置媒体结果: {result}")
    
    if result:
        print("✅ 测试1通过: 媒体设置成功")
    else:
        print("❌ 测试1失败: 媒体设置失败")
    
    # 测试2: 开始播放
    print("\n=== 测试2: 开始播放 ===")
    result = player.play()
    is_playing = player.is_playing
    print(f"[测试] 播放结果: {result}")
    print(f"[测试] 播放状态: is_playing={is_playing}")
    
    if result and is_playing:
        print("✅ 测试2通过: 视频可以正确开始播放")
    else:
        print("❌ 测试2失败: 视频无法正确开始播放")
    
    # 测试3: 检查播放状态同步
    print("\n=== 测试3: 播放状态同步 ===")
    try:
        current_pause = player._get_property_bool('pause')
        print(f"[测试] MPV pause属性: {current_pause}")
        print(f"[测试] 应用is_playing状态: {player._is_playing}")
        
        if not current_pause and player._is_playing:
            print("✅ 测试3通过: 播放状态同步正确")
        else:
            print("❌ 测试3失败: 播放状态不同步")
    except Exception as e:
        print(f"❌ 测试3失败: 获取播放状态异常 - {e}")
    
    # 测试4: 停止播放并清理
    print("\n=== 测试4: 停止播放并清理 ===")
    try:
        player.stop()
        time.sleep(0.5)  # 等待停止完成
        current_pause = player._get_property_bool('pause')
        print(f"[测试] 停止后pause属性: {current_pause}")
        print(f"[测试] 停止后is_playing状态: {player._is_playing}")
        
        if current_pause and not player._is_playing:
            print("✅ 测试4通过: 停止播放和清理成功")
        else:
            print("❌ 测试4失败: 停止播放或清理失败")
    except Exception as e:
        print(f"❌ 测试4失败: 停止播放异常 - {e}")
    
    # 测试5: 重新播放测试
    print("\n=== 测试5: 重新播放测试 ===")
    try:
        # 重新设置媒体（模拟重新加载）
        player.set_media(actual_video)
        result = player.play()
        is_playing = player.is_playing
        print(f"[测试] 重新播放结果: {result}")
        print(f"[测试] 重新播放状态: is_playing={is_playing}")
        
        if result and is_playing:
            print("✅ 测试5通过: 可以重新播放")
        else:
            print("❌ 测试5失败: 无法重新播放")
    except Exception as e:
        print(f"❌ 测试5失败: 重新播放异常 - {e}")
    
    # 清理资源
    player.cleanup()
    print("\n[测试] 资源已清理")

if __name__ == "__main__":
    test_video_play_fix()