#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件卡片状态管理
验证只有未选中状态才能触发hover效果
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

def test_card_states():
    """测试卡片样式逻辑"""
    app = QApplication(sys.argv)
    
    # 创建文件选择器
    from freeassetfilter.components.file_selector import CustomFileSelector
    selector = CustomFileSelector()
    
    print("=== 测试文件卡片状态逻辑 ===")
    
    # 测试文件信息
    test_file_info = {
        "name": "test_file.txt",
        "path": "C:\\test\\test_file.txt",
        "size": 1024,
        "modified": "2024-01-01 12:00:00",
        "is_dir": False,
        "suffix": "txt",
        "type": "文本文件"
    }
    
    # 创建测试卡片
    card = selector._create_file_card(test_file_info)
    
    print(f"初始卡片状态 - is_selected: {card.is_selected}")
    
    # 获取初始样式
    initial_style = card.styleSheet()
    print(f"初始样式包含hover: {'hover' in initial_style}")
    
    # 模拟选中卡片
    card.is_selected = True
    # 重新应用样式（模拟选中状态）
    selector._toggle_selection(card)
    
    selected_style = card.styleSheet()
    print(f"选中状态 - is_selected: {card.is_selected}")
    print(f"选中样式包含hover: {'hover' in selected_style}")
    
    # 模拟取消选中
    card.is_selected = False
    selector._toggle_selection(card)
    
    unselected_style = card.styleSheet()
    print(f"取消选中状态 - is_selected: {card.is_selected}")
    print(f"取消选中样式包含hover: {'hover' in unselected_style}")
    
    print("\n=== 测试结果验证 ===")
    
    # 验证逻辑
    success = True
    
    # 检查未选中状态是否有hover
    if 'hover' in unselected_style:
        print("✅ 未选中状态有hover效果 - 正确")
    else:
        print("❌ 未选中状态应该有hover效果")
        success = False
    
    # 检查选中状态是否无hover
    if 'hover' not in selected_style:
        print("✅ 选中状态无hover效果 - 正确")
    else:
        print("❌ 选中状态应该无hover效果")
        success = False
    
    if success:
        print("\n🎉 所有测试通过！文件卡片状态管理已修复")
    else:
        print("\n⚠️  测试未通过，需要进一步修复")
    
    print("\n测试完成！")

if __name__ == "__main__":
    test_card_states()