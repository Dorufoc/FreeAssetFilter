#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证视频播放器组件的控制条类型
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入必要的组件
from PyQt5.QtWidgets import QApplication
from freeassetfilter.components.video_player import VideoPlayer
from freeassetfilter.widgets.custom_widgets import CustomValueBar

def verify_controls():
    """
    验证视频播放器的控制条类型
    """
    # 创建Qt应用实例
    app = QApplication(sys.argv)
    
    try:
        # 创建视频播放器组件
        video_player = VideoPlayer()
        
        # 检查进度条类型
        progress_type = type(video_player.progress_slider).__name__
        volume_type = type(video_player.volume_slider).__name__
        
        print("=== 视频播放器控制条类型验证 ===")
        print(f"进度条类型: {progress_type}")
        print(f"音量条类型: {volume_type}")
        
        # 验证是否为CustomValueBar
        if progress_type == "CustomValueBar" and volume_type == "CustomValueBar":
            print("\n✓ 验证成功: 所有控制条都已成功使用CustomValueBar")
            return True
        else:
            print("\n✗ 验证失败: 控制条类型不正确")
            return False
            
    except Exception as e:
        print(f"\n✗ 验证失败: 发生错误 - {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 退出应用
        app.quit()

if __name__ == "__main__":
    success = verify_controls()
    sys.exit(0 if success else 1)
