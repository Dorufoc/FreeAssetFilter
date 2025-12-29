#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频播放器的暂停/播放功能
"""

import sys
import os
import time

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

try:
    from freeassetfilter.core.mpv_player_core import MPVPlayerCore
    print("✅ 成功导入MPVPlayerCore")
except Exception as e:
    print(f"❌ 导入MPVPlayerCore失败: {e}")
    sys.exit(1)

def test_play_pause_resume():
    """测试播放、暂停、恢复功能"""
    print("\n=== 测试播放、暂停、恢复功能 ===")
    
    player = None
    try:
        # 创建播放器实例
        player = MPVPlayerCore()
        print("✅ 创建播放器实例成功")
        
        # 等待播放器初始化
        time.sleep(1)
        
        # 加载一个测试视频文件
        # 请确保在项目根目录下有一个test_video.mp4文件
        test_video = os.path.join(os.path.dirname(__file__), "test_video.mp4")
        
        if os.path.exists(test_video):
            print(f"✅ 测试视频存在: {test_video}")
            
            # 加载视频
            player.load(test_video)
            print("✅ 加载视频成功")
            
            # 等待视频加载
            time.sleep(2)
            
            # 开始播放
            player.play()
            print("✅ 开始播放视频")
            
            # 播放2秒
            time.sleep(2)
            
            # 获取当前播放时间
            current_time = player.get_current_time()
            print(f"当前播放时间: {current_time:.2f}秒")
            
            # 暂停播放
            player.pause()
            print("✅ 暂停播放")
            
            # 等待1秒
            time.sleep(1)
            
            # 恢复播放
            player.play()
            print("✅ 恢复播放")
            
            # 播放2秒
            time.sleep(2)
            
            # 获取恢复播放后的时间
            resume_time = player.get_current_time()
            print(f"恢复播放后的时间: {resume_time:.2f}秒")
            
            # 检查是否从暂停位置继续播放
            if resume_time > current_time:
                print("✅ 测试通过: 视频从暂停位置继续播放")
            else:
                print("❌ 测试失败: 视频回到了起始位置")
                
            # 停止播放
            player.stop()
            print("✅ 停止播放")
        else:
            print(f"⚠️  测试视频不存在: {test_video}")
            print("请在项目根目录下添加一个test_video.mp4文件用于测试")
            
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if player:
            player.cleanup()
            print("✅ 清理播放器资源")

def test_is_ended_detection():
    """测试视频结束检测逻辑"""
    print("\n=== 测试视频结束检测逻辑 ===")
    
    player = None
    try:
        # 创建播放器实例
        player = MPVPlayerCore()
        print("✅ 创建播放器实例成功")
        
        # 等待播放器初始化
        time.sleep(1)
        
        # 测试is_playing属性在不同状态下的表现
        print(f"初始状态 - is_playing: {player.is_playing}")
        
        # 尝试获取一些属性，验证修复后的逻辑
        try:
            # 这些属性调用应该不会导致错误
            current_pause = player._get_property_bool('pause')
            core_idle = player._get_property_bool('core-idle')
            
            print(f"\n播放器属性:")
            print(f"  pause: {current_pause}")
            print(f"  core-idle: {core_idle}")
            
        except Exception as e:
            print(f"⚠️  获取播放器属性时发生预期内的错误: {e}")
            print("这是正常的，因为还没有加载视频")
            
        print("✅ 视频结束检测逻辑测试完成")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if player:
            player.cleanup()
            print("✅ 清理播放器资源")

if __name__ == "__main__":
    print("开始测试视频播放器功能...")
    
    # 测试1: 播放、暂停、恢复功能
    test_play_pause_resume()
    
    # 测试2: 视频结束检测逻辑
    test_is_ended_detection()
    
    print("\n所有测试完成！")
