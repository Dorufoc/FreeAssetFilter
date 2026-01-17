#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试SVG颜色替换功能
验证是否正确将#000000替换为secondary_color，将#FFFFFF替换为base_color
"""

import os
import sys
import tempfile

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入所需模块
from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.settings_manager import SettingsManager

def create_test_svg():
    """
    创建一个包含#000000和#FFFFFF颜色的测试SVG文件
    
    Returns:
        str: 临时SVG文件的路径
    """
    # 测试SVG内容，包含黑色(#000000)和白色(#FFFFFF)元素
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
    <!-- 黑色矩形 -->
    <rect x="10" y="10" width="80" height="40" fill="#000000" />
    <!-- 白色矩形 -->
    <rect x="10" y="50" width="80" height="40" fill="#FFFFFF" />
    <!-- 黑色文本 -->
    <text x="50" y="35" font-size="12" fill="#000" text-anchor="middle">黑色文本</text>
    <!-- 白色文本 -->
    <text x="50" y="85" font-size="12" fill="#FFF" text-anchor="middle">白色文本</text>
</svg>'''
    
    # 创建临时文件
    temp_file = tempfile.NamedTemporaryFile(suffix='.svg', delete=False, mode='w', encoding='utf-8')
    temp_file.write(svg_content)
    temp_file.close()
    
    return temp_file.name

def test_svg_color_replacement():
    """
    测试SVG颜色替换功能
    """
    print("开始测试SVG颜色替换功能...")
    
    # 创建测试SVG文件
    svg_path = create_test_svg()
    print(f"创建测试SVG文件: {svg_path}")
    
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
    
    # 验证颜色替换是否正确
    print("\n验证颜色替换:")
    
    # 检查黑色(#000000, #000)是否被替换为secondary_color
    if '#000000' not in processed_svg and '#000' not in processed_svg:
        print("✓ 所有#000000和#000颜色已被替换")
        if secondary_color in processed_svg:
            print(f"✓ secondary_color {secondary_color}已应用")
        else:
            print(f"✗ secondary_color {secondary_color}未在处理后的SVG中找到")
    else:
        print("✗ 存在未被替换的黑色(#000000或#000)")
    
    # 检查白色(#FFFFFF, #FFF)是否被替换为base_color
    if '#FFFFFF' not in processed_svg and '#FFF' not in processed_svg:
        print("✓ 所有#FFFFFF和#FFF颜色已被替换")
        if base_color in processed_svg:
            print(f"✓ base_color {base_color}已应用")
        else:
            print(f"✗ base_color {base_color}未在处理后的SVG中找到")
    else:
        print("✗ 存在未被替换的白色(#FFFFFF或#FFF)")
    
    # 清理临时文件
    os.unlink(svg_path)
    print("\n测试完成，临时文件已清理")

if __name__ == "__main__":
    test_svg_color_replacement()
