#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试音量保存和加载功能
"""

from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.components.video_player import VideoPlayer
from PyQt5.QtWidgets import QApplication

# 测试音量保存和加载功能
def test_volume_save_load():
    # 创建SettingsManager实例
    settings_manager = SettingsManager()
    
    print("=== 测试音量保存和加载功能 ===")
    
    # 1. 测试初始音量设置
    initial_volume = settings_manager.get_setting('player.volume', 50)
    print(f"1. 初始音量: {initial_volume}")
    
    # 2. 测试设置音量
    test_volume = 75
    print(f"2. 设置音量为: {test_volume}")
    settings_manager.set_setting('player.volume', test_volume)
    settings_manager.save_settings()
    
    # 3. 测试重新加载音量
    new_settings_manager = SettingsManager()
    loaded_volume = new_settings_manager.get_setting('player.volume', 50)
    print(f"3. 重新加载后音量: {loaded_volume}")
    
    # 4. 验证音量是否保存成功
    assert loaded_volume == test_volume, f"音量保存失败，预期: {test_volume}，实际: {loaded_volume}"
    print("4. 音量保存验证成功！")
    
    # 5. 恢复默认音量
    settings_manager.set_setting('player.volume', 50)
    settings_manager.save_settings()
    print("5. 已恢复默认音量为50")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    # 创建QApplication实例，因为VideoPlayer需要它
    app = QApplication([])
    
    # 运行测试
    test_volume_save_load()
    
    # 退出应用
    app.quit()