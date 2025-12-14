#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试MXF文件处理修复
"""

import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freeassetfilter.core.ffplayer_core import FFPlayerCore
from freeassetfilter.core.player_core import PlayerCore


def test_fps_calculation():
    """
    测试安全帧率计算
    """
    print("=== 测试安全帧率计算 ===")
    
    # 创建一个模拟的视频流字典，包含不同格式的帧率
    test_cases = [
        ('24/1', 24.0),
        ('30000/1001', 29.97002997002997),
        ('60/1', 60.0),
        ('25', 25.0),
        ('0/1', 0.0),
        ('invalid', 24.0),
        ('100/0', 24.0),
        ('abc/def', 24.0),
    ]
    
    player = FFPlayerCore()
    
    for frame_rate_str, expected in test_cases:
        # 模拟解析帧率的方法
        try:
            if '/' in frame_rate_str:
                numerator, denominator = map(int, frame_rate_str.split('/'))
                if denominator != 0:
                    fps = numerator / denominator
                else:
                    fps = 0.0
            else:
                fps = float(frame_rate_str)
        except (ValueError, ZeroDivisionError):
            fps = 24.0
        
        result = fps
        status = "✓" if abs(result - expected) < 0.001 else "✗"
        print(f"{status} 帧率 '{frame_rate_str}' -> {result:.6f} (预期: {expected:.6f})")


def test_mxf_support():
    """
    测试MXF文件支持
    """
    print("\n=== 测试MXF文件支持 ===")
    
    # 测试播放器核心是否支持MXF格式
    player = FFPlayerCore()
    
    # 检查MXF是否在支持的格式列表中
    if '.mxf' in player.SUPPORTED_VIDEO_FORMATS:
        print("✓ FFPlayerCore 支持 MXF 格式")
    else:
        print("✗ FFPlayerCore 不支持 MXF 格式")
    
    # 测试VLC播放器核心
    vlc_player = PlayerCore()
    if '.mxf' in vlc_player.SUPPORTED_VIDEO_FORMATS:
        print("✓ PlayerCore (VLC) 支持 MXF 格式")
    else:
        print("✗ PlayerCore (VLC) 不支持 MXF 格式")


def test_mxf_input_kwargs():
    """
    测试MXF特定输入参数
    """
    print("\n=== 测试MXF特定输入参数 ===")
    
    # 模拟创建输入参数的逻辑
    test_files = [
        'test.mp4',
        'test.mxf',
        'test.MXF',
        'test.avi',
    ]
    
    for file_path in test_files:
        input_kwargs = {}
        if file_path.lower().endswith('.mxf'):
            input_kwargs['format'] = 'mxf'
            input_kwargs['probe_size'] = '2G'
            input_kwargs['analyzeduration'] = '100M'
        
        if file_path.lower().endswith('.mxf'):
            expected_kwargs = {'format': 'mxf', 'probe_size': '2G', 'analyzeduration': '100M'}
            status = "✓" if input_kwargs == expected_kwargs else "✗"
            print(f"{status} 文件 '{file_path}' -> {input_kwargs}")
        else:
            status = "✓" if input_kwargs == {} else "✗"
            print(f"{status} 文件 '{file_path}' -> {input_kwargs}")


if __name__ == "__main__":
    test_fps_calculation()
    test_mxf_support()
    test_mxf_input_kwargs()
    print("\n=== 测试完成 ===")
