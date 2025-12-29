#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
详细测试视频播放器在暂停状态下切换视频的问题修复
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

def test_pause_switch_detailed():
    """
    详细测试在暂停状态下切换视频的完整流程
    """
    print("=== 详细测试视频播放器在暂停状态下切换视频 ===")
    
    # 创建MPVPlayerCore实例
    player = MPVPlayerCore()
    
    # 模拟视频文件路径
    test_video1 = "test_video1.mp4"
    test_video2 = "test_video2.mp4"
    
    print(f"\n1. 设置第一个视频: {test_video1}")
    player.set_media(test_video1)
    
    print("2. 开始播放第一个视频")
    result = player.play()
    print(f"   播放结果: {result}")
    
    # 直接检查内部状态
    print(f"   内部状态: _is_playing={player._is_playing}")
    
    # 检查MPV的pause属性
    pause_state = player._get_property_bool('pause')
    print(f"   MPV pause属性: {pause_state}")
    
    print("\n3. 暂停第一个视频")
    player.pause()
    
    # 检查内部状态
    print(f"   内部状态: _is_playing={player._is_playing}")
    
    # 检查MPV的pause属性
    pause_state = player._get_property_bool('pause')
    print(f"   MPV pause属性: {pause_state}")
    
    print("\n4. 停止第一个视频")
    player.stop()
    
    # 检查内部状态
    print(f"   内部状态: _is_playing={player._is_playing}")
    
    # 检查MPV的pause属性
    pause_state = player._get_property_bool('pause')
    print(f"   MPV pause属性: {pause_state}")
    
    print(f"\n5. 设置第二个视频: {test_video2}")
    player.set_media(test_video2)
    
    print("\n6. 开始播放第二个视频")
    
    # 在调用play之前再次检查MPV的pause属性
    pause_state_before = player._get_property_bool('pause')
    print(f"   play前的MPV pause属性: {pause_state_before}")
    
    result = player.play()
    print(f"   播放结果: {result}")
    
    # 检查内部状态
    print(f"   内部状态: _is_playing={player._is_playing}")
    
    # 检查MPV的pause属性
    pause_state_after = player._get_property_bool('pause')
    print(f"   play后的MPV pause属性: {pause_state_after}")
    
    # 分析play方法的日志输出
    print("\n=== 分析play方法的日志输出 ===")
    print("play方法会根据MPV的pause属性决定执行哪个分支:")
    print("- 如果pause=True: 执行恢复播放的分支，调用self._set_property_bool('pause', False)")
    print("- 如果pause=False: 执行新媒体加载的分支，调用['loadfile', self._media, 'replace']")
    
    if pause_state_before is False:
        print(f"✅ 修复成功: play方法将执行新媒体加载的分支，正确加载第二个视频")
    else:
        print(f"❌ 修复失败: play方法将执行恢复播放的分支，无法正确加载第二个视频")
    
    # 清理资源
    player.stop()

if __name__ == "__main__":
    test_pause_switch_detailed()
    print("\n\n=== 所有测试完成 ===")
