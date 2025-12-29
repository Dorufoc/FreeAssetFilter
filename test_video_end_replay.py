#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放结束后重新播放的功能修复
"""

import os
import sys
import time
import threading

# 添加项目根目录到sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from freeassetfilter.core.mpv_player_core import MPVPlayerCore
except ImportError as e:
    print(f"导入MPVPlayerCore失败: {e}")
    sys.exit(1)

def mock_end_file_event(player):
    """
    模拟MPV_EVENT_END_FILE事件
    """
    print("\n--- 模拟播放结束事件 ---")
    # 手动设置播放结束状态
    player._is_playing = False
    player._set_property_bool('pause', True)
    
    # 模拟播放时间接近总时长
    # 注意：实际MPV API无法直接模拟这个，所以我们直接设置状态
    print("   播放结束状态已设置: is_playing=False, pause=True")
    return True

def test_replay_after_end():
    """
    测试视频播放结束后重新播放的功能
    """
    print("=== 测试视频播放结束后重新播放 ===")
    
    # 创建MPVPlayerCore实例
    player = MPVPlayerCore()
    
    # 模拟一个视频文件路径
    test_video = "test_video.mp4"
    
    print(f"\n1. 设置视频: {test_video}")
    player.set_media(test_video)
    
    print("2. 模拟视频播放结束")
    mock_end_file_event(player)
    print(f"   当前状态: is_playing={player.is_playing}")
    
    print("3. 尝试重新播放视频")
    result = player.play()
    print(f"   播放结果: {result}")
    print(f"   播放状态: is_playing={player.is_playing}")
    
    # 检查修复是否有效
    if player.is_playing:
        print("\n✅ 测试通过: 视频播放结束后可以重新播放")
    else:
        print("\n❌ 测试失败: 视频播放结束后无法重新播放")
    
    # 清理资源
    player.stop()
    
    return player.is_playing

def test_seek_to_end_then_replay():
    """
    测试手动将视频进度拖到末尾后重新播放
    """
    print("\n\n=== 测试将视频进度拖到末尾后重新播放 ===")
    
    # 创建MPVPlayerCore实例
    player = MPVPlayerCore()
    
    # 模拟一个视频文件路径
    test_video = "test_video.mp4"
    
    print(f"\n1. 设置视频: {test_video}")
    player.set_media(test_video)
    
    print("2. 模拟将视频进度拖到末尾")
    # 模拟播放结束状态
    player._is_playing = False
    player._set_property_bool('pause', True)
    
    # 手动调用play方法，应该会检测到播放结束并重置
    print("3. 尝试重新播放视频")
    result = player.play()
    print(f"   播放结果: {result}")
    print(f"   播放状态: is_playing={player.is_playing}")
    
    # 检查修复是否有效
    if player.is_playing:
        print("\n✅ 测试通过: 视频拖到末尾后可以重新播放")
    else:
        print("\n❌ 测试失败: 视频拖到末尾后无法重新播放")
    
    # 清理资源
    player.stop()
    
    return player.is_playing

if __name__ == "__main__":
    # 运行测试
    test1_passed = test_replay_after_end()
    test2_passed = test_seek_to_end_then_replay()
    
    print("\n" + "="*50)
    if test1_passed and test2_passed:
        print("🎉 所有测试通过！视频播放结束后重新播放功能修复成功。")
        sys.exit(0)
    else:
        print("❌ 部分或全部测试失败，需要进一步修复。")
        sys.exit(1)