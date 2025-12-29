import sys
import os
import time

# 添加项目路径到系统路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'freeassetfilter'))

from core.mpv_player_core import MPVPlayerCore

def main():
    """简单的视频自动播放测试脚本"""
    print("视频自动播放测试")
    print("="*50)
    
    # 检查是否提供了视频路径参数
    if len(sys.argv) < 2:
        print("使用方法: python test_video_autoplay_simple.py <视频文件路径>")
        return
    
    video_path = sys.argv[1]
    
    # 检查视频文件是否存在
    if not os.path.exists(video_path):
        print(f"错误: 视频文件不存在 - {video_path}")
        return
    
    print(f"测试视频: {video_path}")
    
    # 创建MPVPlayerCore实例
    mpv_core = MPVPlayerCore()
    
    if not mpv_core.initialize():
        print("初始化MPVPlayerCore失败")
        return
    
    print("MPVPlayerCore初始化成功")
    
    # 设置媒体
    print("设置媒体...")
    mpv_core.set_media(video_path)
    
    # 等待媒体加载
    time.sleep(0.5)
    
    # 开始播放
    print("开始播放...")
    play_result = mpv_core.play()
    print(f"播放调用结果: {play_result}")
    
    # 持续检查状态变化
    print("\n开始监控状态变化 (持续10秒):")
    print("时间点 | pause | is_playing | 备注")
    print("-" * 50)
    
    for i in range(20):  # 10秒，每0.5秒检查一次
        time.sleep(0.5)
        try:
            pause = mpv_core._get_property_bool('pause')
            is_playing = mpv_core._is_playing
            time_pos = mpv_core._get_property_double('playback-time')
            
            remark = ""
            if not pause and is_playing:
                remark = "正常播放"
            elif pause and not is_playing:
                remark = "已暂停"
            else:
                remark = "状态不一致"
            
            print(f"{i*0.5:5.1f}s | {pause!r:6} | {is_playing!r:11} | {remark}")
            
            # 如果视频被错误地暂停了，尝试恢复播放
            if pause and is_playing:
                print("发现状态不一致，尝试恢复播放...")
                mpv_core._set_property_bool('pause', False)
        except Exception as e:
            print(f"{i*0.5:5.1f}s | 错误: {e}")
    
    # 清理
    print("\n测试结束，清理资源...")
    mpv_core.terminate()
    print("测试完成")

if __name__ == "__main__":
    main()