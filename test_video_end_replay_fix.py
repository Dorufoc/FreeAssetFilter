#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试MP视频播放组件在播放到最后时的重播功能修复
"""

import os
import sys
import time
import threading

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.core.mpv_player_core import MPVPlayerCore
from ctypes import CDLL, c_void_p, c_int


def mock_end_file_event(player):
    """
    模拟MPV播放结束事件
    """
    # 直接设置_is_playing为False，模拟播放结束
    player._is_playing = False
    # 设置pause属性为True
    player._set_property_bool('pause', True)
    print(f"[测试] 已模拟播放结束事件: is_playing={player._is_playing}, pause={player._get_property_bool('pause')}")


def mock_idle_event(player):
    """
    模拟MPV idle事件
    """
    # 设置pause属性为True
    player._set_property_bool('pause', True)
    print(f"[测试] 已模拟idle事件: pause={player._get_property_bool('pause')}")


def test_replay_after_end():
    """
    测试1: 播放结束后点击播放按钮能否重新播放
    """
    print("=== 测试1: 播放结束后点击播放按钮能否重新播放 ===")
    
    player = MPVPlayerCore()
    
    # 使用一个实际的视频文件路径进行测试
    test_video = "E:/DFTP/挑战杯视频/DSC_1808.MOV"  # 替换为你的测试视频路径
    
    if not os.path.exists(test_video):
        print(f"[测试] 警告: 测试视频不存在，请替换为实际存在的视频文件路径: {test_video}")
        # 使用一个不存在的视频文件进行模拟测试
        test_video = "test_video.mp4"
    
    # 设置媒体
    result = player.set_media(test_video)
    print(f"[测试] 设置媒体结果: {result}")
    
    # 模拟播放结束
    mock_end_file_event(player)
    
    # 模拟点击播放按钮
    print("[测试] 模拟点击播放按钮...")
    result = player.play()
    
    # 检查播放状态
    is_playing = player.is_playing
    print(f"[测试] 播放结果: {result}, 播放状态: is_playing={is_playing}")
    
    if result and is_playing:
        print("✅ 测试1通过: 播放结束后点击播放按钮可以重新播放")
    else:
        print("❌ 测试1失败: 播放结束后点击播放按钮无法重新播放")
    
    return result and is_playing


def test_replay_after_idle():
    """
    测试2: idle状态下点击播放按钮能否重新播放
    """
    print("\n\n=== 测试2: idle状态下点击播放按钮能否重新播放 ===")
    
    player = MPVPlayerCore()
    
    # 使用一个实际的视频文件路径进行测试
    test_video = "E:/DFTP/挑战杯视频/DSC_1808.MOV"  # 替换为你的测试视频路径
    
    if not os.path.exists(test_video):
        print(f"[测试] 警告: 测试视频不存在，请替换为实际存在的视频文件路径: {test_video}")
        # 使用一个不存在的视频文件进行模拟测试
        test_video = "test_video.mp4"
    
    # 设置媒体
    result = player.set_media(test_video)
    print(f"[测试] 设置媒体结果: {result}")
    
    # 模拟idle事件
    mock_idle_event(player)
    
    # 模拟点击播放按钮
    print("[测试] 模拟点击播放按钮...")
    result = player.play()
    
    # 检查播放状态
    is_playing = player.is_playing
    print(f"[测试] 播放结果: {result}, 播放状态: is_playing={is_playing}")
    
    if result and is_playing:
        print("✅ 测试2通过: idle状态下点击播放按钮可以重新播放")
    else:
        print("❌ 测试2失败: idle状态下点击播放按钮无法重新播放")
    
    return result and is_playing


def test_seek_to_end_then_replay():
    """
    测试3: 手动将进度条拖到最后再点击播放按钮能否重新播放
    """
    print("\n\n=== 测试3: 手动将进度条拖到最后再点击播放按钮能否重新播放 ===")
    
    player = MPVPlayerCore()
    
    # 使用一个实际的视频文件路径进行测试
    test_video = "E:/DFTP/挑战杯视频/DSC_1808.MOV"  # 替换为你的测试视频路径
    
    if not os.path.exists(test_video):
        print(f"[测试] 警告: 测试视频不存在，请替换为实际存在的视频文件路径: {test_video}")
        # 使用一个不存在的视频文件进行模拟测试
        test_video = "test_video.mp4"
    
    # 设置媒体
    result = player.set_media(test_video)
    print(f"[测试] 设置媒体结果: {result}")
    
    # 模拟进度条拖到最后
    player._is_playing = False
    player._set_property_bool('pause', True)
    print(f"[测试] 已模拟进度条拖到最后: is_playing={player._is_playing}, pause={player._get_property_bool('pause')}")
    
    # 模拟点击播放按钮
    print("[测试] 模拟点击播放按钮...")
    result = player.play()
    
    # 检查播放状态
    is_playing = player.is_playing
    print(f"[测试] 播放结果: {result}, 播放状态: is_playing={is_playing}")
    
    if result and is_playing:
        print("✅ 测试3通过: 手动将进度条拖到最后再点击播放按钮可以重新播放")
    else:
        print("❌ 测试3失败: 手动将进度条拖到最后再点击播放按钮无法重新播放")
    
    return result and is_playing


if __name__ == "__main__":
    print("开始测试MP视频播放组件重播功能修复...")
    print("=" * 70)
    
    # 运行所有测试
    test_results = []
    
    # 测试1: 播放结束后点击播放按钮能否重新播放
    test_results.append(test_replay_after_end())
    
    # 测试2: idle状态下点击播放按钮能否重新播放
    test_results.append(test_replay_after_idle())
    
    # 测试3: 手动将进度条拖到最后再点击播放按钮能否重新播放
    test_results.append(test_seek_to_end_then_replay())
    
    print("\n" + "=" * 70)
    print("测试总结:")
    print(f"通过测试数: {sum(test_results)}/{len(test_results)}")
    
    if all(test_results):
        print("✅ 所有测试通过! 修复成功!")
    else:
        print("❌ 部分测试失败! 修复可能不完全!")
    
    print("测试结束!")
