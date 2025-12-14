#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

测试基于ffmpeg的视频播放核心功能
"""

import sys
import os
import time
from PyQt5.QtWidgets import QApplication
from freeassetfilter.core.ffplayer_core import FFPlayerCore


def test_ffplayer_core():
    """
    测试基于ffmpeg的视频播放核心功能
    """
    print("=== 测试FFPlayerCore功能 ===")
    
    # 初始化Qt应用程序
    app = QApplication(sys.argv)
    
    # 创建FFPlayerCore实例
    player = FFPlayerCore()
    
    # 测试视频文件路径
    # 请替换为您本地的测试视频文件路径
    test_video_path = "C:\\Users\\Dorufoc\\Desktop\\001logo动画_1.mp4"
    
    if not os.path.exists(test_video_path):
        print(f"错误：测试视频文件不存在: {test_video_path}")
        return False
    
    print(f"使用测试视频文件: {test_video_path}")
    
    # 测试1：加载媒体文件
    print("\n1. 测试加载媒体文件...")
    if player.load_media(test_video_path):
        print("✅ 媒体文件加载成功")
    else:
        print("❌ 媒体文件加载失败")
        return False
    
    # 测试2：播放控制
    print("\n2. 测试播放控制...")
    
    # 测试播放
    if player.play():
        print("✅ 播放成功")
    else:
        print("❌ 播放失败")
        return False
    
    # 播放5秒
    print("播放5秒...")
    time.sleep(5)
    
    # 测试暂停
    if player.pause():
        print("✅ 暂停成功")
    else:
        print("❌ 暂停失败")
        return False
    
    # 暂停2秒
    time.sleep(2)
    
    # 测试继续播放
    if player.play():
        print("✅ 继续播放成功")
    else:
        print("❌ 继续播放失败")
        return False
    
    # 播放3秒
    print("继续播放3秒...")
    time.sleep(3)
    
    # 测试停止
    if player.stop():
        print("✅ 停止成功")
    else:
        print("❌ 停止失败")
        return False
    
    # 测试3：进度调整
    print("\n3. 测试进度调整...")
    
    # 重新加载媒体文件，确保视频从头开始
    if not player.load_media(test_video_path):
        print("❌ 重新加载媒体文件失败")
        return False
    
    # 开始播放
    if not player.play():
        print("❌ 播放失败")
        return False
    
    # 播放1秒，确保解码线程正常运行
    time.sleep(1)
    
    # 设置进度为50%
    if player.set_position(0.5):
        print("✅ 进度调整到50%成功")
    else:
        print("❌ 进度调整失败")
        return False
    
    # 继续播放3秒
    time.sleep(3)
    
    # 测试4：音量控制
    print("\n4. 测试音量控制...")
    
    # 设置音量为80%
    if player.set_volume(80):
        print("✅ 音量设置为80%成功")
    else:
        print("❌ 音量设置失败")
        return False
    
    # 播放2秒
    time.sleep(2)
    
    # 测试5：播放速度控制
    print("\n5. 测试播放速度控制...")
    
    # 设置播放速度为1.5倍
    if player.set_rate(1.5):
        print("✅ 播放速度设置为1.5x成功")
    else:
        print("❌ 播放速度设置失败")
        return False
    
    # 播放3秒
    time.sleep(3)
    
    # 测试6：LUT色彩映射
    print("\n6. 测试LUT色彩映射...")
    
    # 停止播放
    player.stop()
    
    # 这里可以添加LUT测试代码
    print("LUT测试功能待完善")
    
    # 测试7：获取播放状态
    print("\n7. 测试获取播放状态...")
    
    print(f"当前播放状态: {player.is_playing}")
    print(f"当前播放时间: {player.time} 毫秒")
    print(f"媒体总时长: {player.duration} 毫秒")
    print(f"当前播放位置: {player.position:.2f}")
    print(f"当前音量: {player.volume}%")
    print(f"当前播放速度: {player.rate}x")
    
    # 停止播放并清理资源（避免在Qt应用程序关闭后调用）
    try:
        player.stop()
    except Exception as e:
        print(f"忽略停止失败错误: {e}")
    
    print("\n=== FFPlayerCore功能测试完成 ===")
    return True


if __name__ == "__main__":
    success = test_ffplayer_core()
    if success:
        print("✅ 所有测试通过")
        sys.exit(0)
    else:
        print("❌ 测试失败")
        sys.exit(1)
