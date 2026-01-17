#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试SVG默认颜色替换功能
验证没有显式颜色定义的SVG文件是否能被正确处理
"""

import os
import sys
import tempfile

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入所需模块
from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.settings_manager import SettingsManager

def create_test_svg_with_default_color():
    """
    创建一个没有显式颜色定义的测试SVG文件（使用默认颜色）
    这模拟了file_selector.py中按钮使用的SVG图标格式
    
    Returns:
        str: 临时SVG文件的路径
    """
    # 测试SVG内容，没有显式定义fill属性（使用默认黑色）
    svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
    <!-- 没有显式fill属性的path元素（默认黑色） -->
    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
</svg>'''
    
    # 创建临时文件
    temp_file = tempfile.NamedTemporaryFile(suffix='.svg', delete=False, mode='w', encoding='utf-8')
    temp_file.write(svg_content)
    temp_file.close()
    
    return temp_file.name

def test_svg_default_color_replacement():
    """
    测试没有显式颜色定义的SVG文件的颜色替换功能
    """
    print("开始测试SVG默认颜色替换功能...")
    
    # 创建测试SVG文件
    svg_path = create_test_svg_with_default_color()
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
    
    # 检查是否为没有显式颜色的path元素添加了fill属性
    if 'fill="' in processed_svg:
        print("✓ 已为没有显式颜色的path元素添加了fill属性")
        
        # 检查添加的fill属性是否为secondary_color
        if secondary_color in processed_svg:
            print(f"✓ fill属性已正确设置为secondary_color: {secondary_color}")
        else:
            print(f"✗ fill属性未设置为secondary_color")
    else:
        print("✗ 未为没有显式颜色的path元素添加fill属性")
    
    # 清理临时文件
    os.unlink(svg_path)
    print("\n测试完成，临时文件已清理")

if __name__ == "__main__":
    test_svg_default_color_replacement()
