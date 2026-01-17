#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件夹.svg文件的颜色处理
验证#61CFBE颜色不会被错误替换
"""

import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入所需模块
from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.settings_manager import SettingsManager

def test_folder_svg_color():
    """
    测试文件夹.svg文件的颜色处理
    """
    print("开始测试文件夹.svg颜色处理...")
    
    # 文件夹SVG文件路径
    svg_path = os.path.join(os.path.dirname(__file__), "freeassetfilter", "icons", "文件夹.svg")
    print(f"测试SVG文件: {svg_path}")
    
    # 检查文件是否存在
    if not os.path.exists(svg_path):
        print("✗ 文件不存在")
        return
    
    # 读取原始SVG内容
    with open(svg_path, 'r', encoding='utf-8') as f:
        original_svg = f.read()
    
    print("\n原始SVG内容:")
    print(original_svg)
    
    # 获取当前设置的颜色
    settings_manager = SettingsManager()
    base_color = settings_manager.get_setting("appearance.colors.base_color")
    secondary_color = settings_manager.get_setting("appearance.colors.secondary_color")
    accent_color = settings_manager.get_setting("appearance.colors.accent_color")
    
    print(f"\n当前设置的颜色:")
    print(f"base_color: {base_color}")
    print(f"secondary_color: {secondary_color}")
    print(f"accent_color: {accent_color}")
    
    # 使用SvgRenderer预处理SVG内容
    print("\n预处理SVG内容...")
    with open(svg_path, 'r', encoding='utf-8') as f:
        svg_content = f.read()
    
    processed_svg = SvgRenderer._replace_svg_colors(svg_content)
    
    print("\n预处理后的SVG内容:")
    print(processed_svg)
    
    # 验证颜色处理是否正确
    print("\n验证颜色处理:")
    
    # 检查#61CFBE颜色是否被错误替换（不区分大小写）
    if '#61cfbe' in processed_svg.lower():
        print("✓ #61CFBE颜色未被错误替换")
    else:
        print("✗ #61CFBE颜色被错误替换了")
    
    # 检查默认颜色是否被正确替换
    if 'fill="#000000"' not in processed_svg:
        print("✓ 没有显式颜色的path元素已添加fill属性并替换颜色")
    else:
        print("✗ 没有显式颜色的path元素未正确处理")

if __name__ == "__main__":
    test_folder_svg_color()
