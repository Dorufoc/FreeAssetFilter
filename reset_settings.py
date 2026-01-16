#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重置设置脚本
用于清除旧的颜色配置项，只保留5个基础颜色
"""

import os
import sys
import json

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

from freeassetfilter.core.settings_manager import SettingsManager

def reset_color_settings():
    """重置颜色设置，只保留5个基础颜色"""
    # 初始化设置管理器
    settings_manager = SettingsManager()
    
    # 获取当前设置
    settings = settings_manager.settings
    
    # 只保留5个基础颜色
    if "appearance" in settings and "colors" in settings["appearance"]:
        # 获取基础颜色
        colors = settings["appearance"]["colors"]
        base_colors = ["accent_color", "secondary_color", "normal_color", "auxiliary_color", "base_color"]
        
        # 过滤只保留基础颜色
        filtered_colors = {}
        for color_key in base_colors:
            if color_key in colors:
                filtered_colors[color_key] = colors[color_key]
        
        # 更新设置
        settings["appearance"]["colors"] = filtered_colors
        settings_manager.settings = settings
        
        # 保存设置
        settings_manager.save_settings()
        print("颜色设置已重置，只保留5个基础颜色")
        print("当前颜色设置:", filtered_colors)
    else:
        print("没有找到颜色设置")

if __name__ == "__main__":
    reset_color_settings()