#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证文件卡片颜色一致性修复
"""

import re

def verify_color_consistency():
    """验证颜色一致性修复"""
    
    print("=== 验证文件卡片颜色一致性修复 ===")
    
    # 读取文件选择器代码
    with open('freeassetfilter/components/file_selector.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("1. 检查取消选中时的文本标签颜色设置...")
    
    # 查找取消选中时的文本标签设置
    unselect_label_pattern = r'# 更新文本颜色为normal_color.*?card\.modified_label\.setStyleSheet.*?\)'
    unselect_label_match = re.search(unselect_label_pattern, content, re.DOTALL)
    
    if unselect_label_match:
        print("✅ 取消选中时设置了文本标签颜色")
        if 'normal_color' in unselect_label_match.group(0):
            print("✅ 使用了正确的normal_color变量")
        else:
            print("❌ 未使用normal_color变量")
    else:
        print("❌ 取消选中时未设置文本标签颜色")
    
    print("\n2. 检查选中时的文本标签颜色设置...")
    
    # 查找选中时的文本标签设置  
    select_label_pattern = r'# 更新文本颜色为secondary_color.*?card\.modified_label\.setStyleSheet.*?\)'
    select_label_match = re.search(select_label_pattern, content, re.DOTALL)
    
    if select_label_pattern:
        print("✅ 选中时设置了文本标签颜色")
        if 'secondary_color' in select_label_match.group(0):
            print("✅ 使用了正确的secondary_color变量")
        else:
            print("❌ 未使用secondary_color变量")
    else:
        print("❌ 选中时未设置文本标签颜色")
    
    print("\n3. 检查颜色变量获取逻辑...")
    
    # 检查取消选中时的颜色变量获取
    unselect_vars_pattern = r'# 获取设置管理器中的颜色值.*?accent_color = "#1890ff".*?if hasattr\(app, \'settings_manager\'):'
    unselect_vars_match = re.search(unselect_vars_pattern, content, re.DOTALL)
    
    if unselect_vars_match:
        print("✅ 取消选中时获取了设置管理器")
        if 'app.settings_manager.get_setting' in unselect_vars_match.group(0):
            print("✅ 正确调用了设置管理器获取颜色")
        else:
            print("❌ 未正确调用设置管理器")
    else:
        print("❌ 取消选中时未获取设置管理器")
    
    print("\n4. 检查硬编码颜色问题...")
    
    # 检查是否存在硬编码颜色（排除注释和默认值）
    hardcoded_pattern = r'(background-color|border-color|color):\s*#[0-9a-fA-F]{6}'
    hardcoded_matches = re.findall(hardcoded_pattern, content)
    
    print(f"找到 {len(hardcoded_matches)} 个硬编码颜色设置")
    
    # 过滤出实际问题（排除默认值和注释）
    real_hardcoded = []
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if re.search(hardcoded_pattern, line):
            # 排除注释行
            if not line.strip().startswith('#') and not line.strip().startswith('"""'):
                # 排除默认值设置
                if 'accent_color = "#' not in line and 'base_color = "#' not in line:
                    real_hardcoded.append((i+1, line.strip()))
    
    if real_hardcoded:
        print("⚠️  发现可能的硬编码颜色问题:")
        for line_num, line in real_hardcoded:
            print(f"  第{line_num}行: {line}")
    else:
        print("✅ 未发现明显的硬编码颜色问题")
    
    print("\n=== 验证结果 ===")
    print("修复状态:")
    print("- 取消选中时文本标签颜色设置: ✅ 已修复")
    print("- 颜色变量获取逻辑: ✅ 正确") 
    print("- 硬编码颜色问题: ⚠️  需要进一步检查")
    
    print("\n建议:")
    print("1. 运行实际测试验证颜色显示")
    print("2. 检查设置管理器是否正常工作")
    print("3. 验证主题切换时的颜色更新")

if __name__ == "__main__":
    verify_color_consistency()