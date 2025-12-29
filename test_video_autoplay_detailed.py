import sys
import os
import time
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

# 添加项目路径到系统路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'freeassetfilter'))

from components.video_player import VideoPlayer
from core.mpv_player_core import MPVPlayerCore

# 测试视频路径 - 请替换为实际的视频文件路径
TEST_VIDEO_PATH = r"D:\素材\1.mov"

class TestVideoPlayer(VideoPlayer):
    """用于测试的视频播放器子类，重写方法以添加调试日志"""
    def __init__(self):
        super().__init__()
        self.player_core._mpv_event_callback = self.custom_event_callback
        
    def custom_event_callback(self, ctx):
        """自定义事件回调，用于记录所有事件"""
        print(f"[DEBUG] 自定义事件回调被调用")
        
    def load_media(self, file_path):
        """重写加载媒体方法，添加详细日志"""
        print(f"\n[DEBUG] 开始加载媒体: {file_path}")
        start_time = time.time()
        
        # 调用父类方法
        result = super().load_media(file_path)
        
        load_time = time.time() - start_time
        print(f"[DEBUG] 媒体加载完成，耗时: {load_time:.3f}秒")
        print(f"[DEBUG] 加载结果: {result}")
        print(f"[DEBUG] 加载后播放器状态 - pause: {self.player_core._get_property_bool('pause')}, is_playing: {self.player_core._is_playing}")
        
        return result

# 测试MPVPlayerCore的详细状态
def test_mpv_core_directly():
    print("\n" + "="*60)
    print("直接测试MPVPlayerCore")
    print("="*60)
    
    # 创建MPVPlayerCore实例
    mpv_core = MPVPlayerCore()
    
    if not mpv_core.initialize():
        print("[ERROR] MPVPlayerCore初始化失败")
        return False
    
    print("MPVPlayerCore初始化成功")
    
    # 设置媒体
    print(f"设置媒体: {TEST_VIDEO_PATH}")
    mpv_core.set_media(TEST_VIDEO_PATH)
    
    # 等待媒体加载
    time.sleep(0.5)
    
    # 检查初始状态
    print(f"初始状态 - pause: {mpv_core._get_property_bool('pause')}, is_playing: {mpv_core._is_playing}")
    
    # 开始播放
    print("\n开始播放...")
    play_result = mpv_core.play()
    print(f"播放调用结果: {play_result}")
    
    # 检查播放后的状态
    print(f"播放后状态 - pause: {mpv_core._get_property_bool('pause')}, is_playing: {mpv_core._is_playing}")
    
    # 持续检查状态变化
    print("\n开始监控状态变化 (持续5秒):")
    for i in range(25):  # 5秒，每0.2秒检查一次
        time.sleep(0.2)
        pause = mpv_core._get_property_bool('pause')
        is_playing = mpv_core._is_playing
        print(f"时间点 {i*0.2:.1f}s - pause: {pause}, is_playing: {is_playing}")
        
        if pause and is_playing:
            print("[WARNING] 状态不一致: pause=True但is_playing=True")
        elif not pause and not is_playing:
            print("[WARNING] 状态不一致: pause=False但is_playing=False")
    
    # 清理
    mpv_core.terminate()
    return True

def main():
    print("视频自动播放测试")
    print(f"测试视频: {TEST_VIDEO_PATH}")
    
    if not os.path.exists(TEST_VIDEO_PATH):
        print(f"[ERROR] 测试视频不存在: {TEST_VIDEO_PATH}")
        return
    
    # 直接测试MPVPlayerCore
    test_mpv_core_directly()
    
    # 测试完整的VideoPlayer组件
    print("\n" + "="*60)
    print("测试完整的VideoPlayer组件")
    print("="*60)
    
    app = QApplication(sys.argv)
    player = TestVideoPlayer()
    
    # 显示播放器
    player.show()
    
    # 延迟加载视频，确保UI初始化完成
    QApplication.processEvents()
    time.sleep(1)
    
    # 加载并播放视频
    print("\n加载并播放视频...")
    player.load_media(TEST_VIDEO_PATH)
    
    # 持续运行并监控状态
    print("\n开始监控播放器状态 (持续10秒):")
    start_time = time.time()
    while time.time() - start_time < 10:
        QApplication.processEvents()
        time.sleep(0.5)
        pause = player.player_core._get_property_bool('pause')
        is_playing = player.player_core._is_playing
        print(f"时间点 {time.time() - start_time:.1f}s - pause: {pause}, is_playing: {is_playing}")
    
    print("\n测试结束")
    player.close()

if __name__ == "__main__":
    main()