#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试主题设置是否能被正确保存
"""

import os
import sys
import time
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath('.'))

from freeassetfilter.core.settings_manager import SettingsManager


def test_theme_settings():
    """测试主题设置是否能被正确保存"""
    print("=== 测试主题设置是否能被正确保存 ===")
    
    settings_file = os.path.join(os.path.dirname(__file__), "data", "settings.json")
    
    # 步骤1: 初始化设置管理器
    settings_manager = SettingsManager()
    
    # 步骤2: 设置主题和各种颜色
    print("\n2. 设置主题和各种颜色...")
    
    # 设置主题模式
    settings_manager.set_setting("appearance.theme", "dark")
    
    # 设置各种颜色，包括基础颜色和非基础颜色
    all_colors = {
        # 基础颜色（之前被允许保存的）
        "accent_color": "#0A59F7",
        "secondary_color": "#FFFFFF",
        "normal_color": "#333333",
        "auxiliary_color": "#1E1E1E",
        "base_color": "#212121",
        
        # 非基础颜色（之前被跳过保存的）
        "button_primary_normal": "#0A59F7",
        "button_primary_hover": "#0957f2",
        "button_primary_pressed": "#0954ea",
        "button_primary_text": "#ffffff",
        "button_primary_border": "#0A59F7",
        "button_normal_normal": "#2D2D2D",
        "button_normal_hover": "#333333",
        "button_normal_pressed": "#3C3C3C",
        "button_normal_text": "#FFFFFF",
        "button_normal_border": "#3C3C3C",
        "button_secondary_normal": "#2D2D2D",
        "button_secondary_hover": "#333333",
        "button_secondary_pressed": "#3C3C3C",
        "button_secondary_text": "#0A59F7",
        "button_secondary_border": "#0A59F7",
        "text_normal": "#FFFFFF",
        "text_disabled": "#666666",
        "text_highlight": "#0A59F7",
        "text_placeholder": "#666666",
        "input_background": "#3C3C3C",
        "input_border": "#444444",
        "input_focus_border": "#0A59F7",
        "input_text": "#FFFFFF",
        "list_background": "#1E1E1E",
        "list_item_normal": "#333333",
        "list_item_hover": "#3C3C3C",
        "list_item_selected": "#0A59F7",
        "list_item_text": "#FFFFFF",
        "slider_track": "#3C3C3C",
        "slider_handle": "#0A59F7",
        "slider_handle_hover": "#0957f2",
        "progress_bar_bg": "#3C3C3C",
        "progress_bar_fg": "#0A59F7",
        "window_background": "#2D2D2D",
        "window_border": "#3C3C3C"
    }
    
    # 设置所有颜色
    for color_key, color_value in all_colors.items():
        settings_manager.set_setting(f"appearance.colors.{color_key}", color_value)
    
    # 保存设置
    settings_manager.save_settings()
    print(f"✅ 设置了 {len(all_colors)} 种颜色")
    
    # 验证设置是否保存成功
    time.sleep(0.1)
    
    # 步骤3: 读取保存的设置文件
    print("\n3. 读取保存的设置文件...")
    
    with open(settings_file, "r", encoding="utf-8") as f:
        saved_settings = json.load(f)
    
    saved_colors = saved_settings.get("appearance", {}).get("colors", {})
    print(f"保存的颜色数量: {len(saved_colors)}")
    
    # 检查是否所有颜色都被保存
    missing_colors = []
    for color_key in all_colors:
        if color_key not in saved_colors:
            missing_colors.append(color_key)
    
    if missing_colors:
        print(f"❌ 以下颜色未被保存: {missing_colors}")
        return False
    else:
        print("✅ 所有颜色都被保存成功")
    
    # 检查颜色值是否正确
    wrong_colors = []
    for color_key, color_value in all_colors.items():
        if saved_colors.get(color_key) != color_value:
            wrong_colors.append((color_key, saved_colors.get(color_key), color_value))
    
    if wrong_colors:
        print("❌ 以下颜色值不正确:")
        for color_key, saved_value, expected_value in wrong_colors:
            print(f"   {color_key}: 保存值='{saved_value}', 期望值='{expected_value}'")
        return False
    else:
        print("✅ 所有颜色值都正确")
    
    # 步骤4: 重新加载设置，验证是否能正确加载
    print("\n4. 重新加载设置，验证是否能正确加载...")
    
    settings_manager2 = SettingsManager()
    
    # 检查主题模式
    loaded_theme = settings_manager2.get_setting("appearance.theme", "default")
    print(f"主题模式: 保存值='{loaded_theme}', 期望值='dark'")
    
    if loaded_theme != "dark":
        print("❌ 主题模式加载失败")
        return False
    
    # 检查所有颜色
    loaded_missing_colors = []
    loaded_wrong_colors = []
    
    for color_key, expected_value in all_colors.items():
        loaded_value = settings_manager2.get_setting(f"appearance.colors.{color_key}", None)
        
        if loaded_value is None:
            loaded_missing_colors.append(color_key)
        elif loaded_value != expected_value:
            loaded_wrong_colors.append((color_key, loaded_value, expected_value))
    
    if loaded_missing_colors:
        print(f"❌ 以下颜色加载失败: {loaded_missing_colors}")
        return False
    
    if loaded_wrong_colors:
        print("❌ 以下颜色值加载不正确:")
        for color_key, loaded_value, expected_value in loaded_wrong_colors:
            print(f"   {color_key}: 加载值='{loaded_value}', 期望值='{expected_value}'")
        return False
    
    print("✅ 所有颜色都加载成功")
    
    # 步骤5: 恢复默认设置
    print("\n5. 恢复默认设置...")
    settings_manager2.reset_to_defaults()
    settings_manager2.save_settings()
    
    print("✅ 测试完成")
    return True


if __name__ == "__main__":
    success = test_theme_settings()
    
    if success:
        print("\n🎉 所有测试通过! 主题设置现在可以被正确保存和加载了")
        sys.exit(0)
    else:
        print("\n❌ 测试失败! 主题设置仍然存在问题")
        sys.exit(1)
