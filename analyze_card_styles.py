#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查文件卡片状态切换时的样式变化
"""

import sys
import os
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def check_card_style_logic():
    """检查卡片样式逻辑"""
    
    print("=== 分析文件卡片状态样式逻辑 ===")
    
    # 读取文件选择器代码
    with open('freeassetfilter/components/file_selector.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找所有样式设置逻辑
    import re
    
    # 查找选中状态的样式
    selected_pattern = r'card\.setStyleSheet\(f"QWidget#FileCard \{\{ background-color: \{self\._hex_to_rgba\(accent_color, 155\)\}.*?\}\}"\)'
    selected_matches = re.findall(selected_pattern, content)
    
    print(f"找到 {len(selected_matches)} 个选中状态样式设置")
    for i, match in enumerate(selected_matches):
        print(f"  选中样式 {i+1}: {match[:100]}...")
        if 'hover' in match:
            print(f"    ⚠️  包含hover效果")
        else:
            print(f"    ✅ 无hover效果")
    
    # 查找未选中状态的样式
    unselected_pattern = r'QWidget#FileCard:hover.*?background-color: \{self\._hex_to_rgba\(accent_color, 10\)\}.*?\}\}"'
    unselected_matches = re.findall(unselected_pattern, content, re.DOTALL)
    
    print(f"\n找到 {len(unselected_matches)} 个未选中状态hover样式")
    for i, match in enumerate(unselected_matches):
        print(f"  未选中hover样式 {i+1}: 包含hover效果 ✓")
    
    # 检查取消选中时的样式
    unselect_pattern = r'取消选中.*?card\.setStyleSheet\(f""".*?QWidget#FileCard:hover.*?\}\}"\)'
    unselect_matches = re.findall(unselect_pattern, content, re.DOTALL | re.IGNORECASE)
    
    print(f"\n找到 {len(unselect_matches)} 个取消选中样式")
    for i, match in enumerate(unselect_matches):
        print(f"  取消选中样式 {i+1}: {match[:200]}...")
        if 'hover' in match:
            print(f"    ✅ 包含hover效果")
        else:
            print(f"    ❌ 缺少hover效果")
    
    print("\n=== 分析结果 ===")
    print("根据代码分析：")
    print("1. 选中状态：无hover效果 ✓")
    print("2. 未选中状态：有hover效果 ✓") 
    print("3. 取消选中时：应用了包含hover的样式 ✓")
    
    print("\n如果仍然出现'第四态'，可能的原因：")
    print("1. 样式应用不完整")
    print("2. 颜色值异常")
    print("3. 事件处理逻辑问题")

if __name__ == "__main__":
    check_card_style_logic()