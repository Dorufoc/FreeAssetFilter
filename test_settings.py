#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试设置管理功能
"""

import os
import sys

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from freeassetfilter.core.settings_manager import SettingsManager

def test_settings_manager():
    """
    测试设置管理器功能
    """
    print("=== 测试设置管理器 ===")
    
    # 初始化设置管理器
    settings_manager = SettingsManager()
    print(f"设置文件路径: {settings_manager.settings_file}")
    
    # 测试获取默认设置
    print("\n1. 测试获取默认设置:")
    dpi_scale = settings_manager.get_setting("dpi.global_scale_factor")
    print(f"全局DPI系数: {dpi_scale}")
    
    # 测试修改设置
    print("\n2. 测试修改设置:")
    new_dpi_scale = 1.5
    settings_manager.set_setting("dpi.global_scale_factor", new_dpi_scale)
    print(f"修改后的全局DPI系数: {settings_manager.get_setting('dpi.global_scale_factor')}")
    
    # 测试保存设置
    print("\n3. 测试保存设置:")
    settings_manager.save_settings()
    print(f"设置已保存到: {settings_manager.settings_file}")
    
    # 测试重新加载设置
    print("\n4. 测试重新加载设置:")
    new_settings_manager = SettingsManager()
    loaded_dpi_scale = new_settings_manager.get_setting("dpi.global_scale_factor")
    print(f"重新加载后的全局DPI系数: {loaded_dpi_scale}")
    
    # 验证设置是否正确保存和加载
    print("\n5. 验证设置是否正确保存和加载:")
    if loaded_dpi_scale == new_dpi_scale:
        print("✓ 设置保存和加载成功!")
    else:
        print("✗ 设置保存和加载失败!")
        print(f"预期: {new_dpi_scale}, 实际: {loaded_dpi_scale}")
    
    # 测试其他设置项
    print("\n6. 测试其他设置项:")
    # 设置字体大小
    settings_manager.set_setting("font.size", 22)
    # 设置主题
    settings_manager.set_setting("appearance.theme", "dark")
    # 保存设置
    settings_manager.save_settings()
    # 重新加载
    new_settings_manager2 = SettingsManager()
    print(f"字体大小: {new_settings_manager2.get_setting('font.size')}")
    print(f"主题: {new_settings_manager2.get_setting('appearance.theme')}")
    
    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    test_settings_manager()