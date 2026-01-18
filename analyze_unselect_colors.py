#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查文件卡片取消选中时的颜色获取问题
"""

import re

def analyze_unselect_color_logic():
    """分析取消选中时的颜色逻辑"""
    
    print("=== 分析取消选中时的颜色获取逻辑 ===")
    
    # 读取文件选择器代码
    with open('freeassetfilter/components/file_selector.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找取消选中时的样式设置
    unselect_pattern = r'# 取消选中.*?card\.setStyleSheet\(f""".*?\}\}"\)'
    unselect_match = re.search(unselect_pattern, content, re.DOTALL)
    
    if unselect_match:
        print("找到取消选中样式设置:")
        print(unselect_match.group(0))
        
        # 检查是否获取设置管理器
        if 'settings_manager' in unselect_match.group(0):
            print("✅ 取消选中时获取了设置管理器")
        else:
            print("❌ 取消选中时未获取设置管理器")
        
        # 检查文本标签样式
        if 'name_label.setStyleSheet' in unselect_match.group(0):
            print("✅ 取消选中时设置了文本标签样式")
        else:
            print("❌ 取消选中时未设置文本标签样式")
    
    # 对比选中时的样式设置
    select_pattern = r'# 选中文件.*?card\.setStyleSheet\(f"QWidget#FileCard.*?\}\}"\)'
    select_match = re.search(select_pattern, content, re.DOTALL)
    
    if select_match:
        print("\n找到选中样式设置:")
        print(select_match.group(0))
        
        # 检查文本标签样式
        if 'name_label.setStyleSheet' in select_match.group(0):
            print("✅ 选中时设置了文本标签样式")
        else:
            print("❌ 选中时未设置文本标签样式")
    
    # 检查颜色变量设置
    print("\n=== 颜色变量设置分析 ===")
    
    # 取消选中时的颜色变量
    unselect_vars_pattern = r'# 取消选中.*?auxiliary_color = "#ffffff".*?accent_color = "#1890ff"'
    unselect_vars_match = re.search(unselect_vars_pattern, content, re.DOTALL)
    
    if unselect_vars_match:
        print("取消选中时颜色变量设置:")
        print(unselect_vars_match.group(0))
        
        if 'app.settings_manager.get_setting' in unselect_vars_match.group(0):
            print("✅ 取消选中时正确获取了设置颜色")
        else:
            print("❌ 取消选中时未正确获取设置颜色")
    
    # 选中时的颜色变量  
    select_vars_pattern = r'# 选中文件.*?accent_color = "#1890ff".*?secondary_color = "#333333"'
    select_vars_match = re.search(select_vars_pattern, content, re.DOTALL)
    
    if select_vars_match:
        print("\n选中时颜色变量设置:")
        print(select_vars_match.group(0))
        
        if 'app.settings_manager.get_setting' in select_vars_match.group(0):
            print("✅ 选中时正确获取了设置颜色")
        else:
            print("❌ 选中时未正确获取设置颜色")

if __name__ == "__main__":
    analyze_unselect_color_logic()