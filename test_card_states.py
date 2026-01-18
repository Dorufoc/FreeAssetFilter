#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件卡片状态管理
验证只有未选中状态才能触发hover效果
"""

import sys
import os
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from freeassetfilter.components.file_selector import CustomFileSelector

def test_card_states():
    """测试卡片状态切换"""
    app = QApplication(sys.argv)
    
    # 创建文件选择器
    selector = CustomFileSelector()
    selector.show()
    
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
    from freeassetfilter.components.file_selector import FileCard
    card = FileCard(test_file_info, selector.dpi_scale, selector)
    
    print("=== 测试卡片状态 ===")
    print(f"初始状态 - is_selected: {card.is_selected}")
    
    # 获取卡片样式
    initial_style = card.styleSheet()
    print(f"初始样式包含hover: {'hover' in initial_style}")
    
    # 模拟选中卡片
    card.is_selected = True
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
    
    print("\n=== 测试结果 ===")
    # 验证逻辑
    if card.is_selected == False and 'hover' in unselected_style:
        print("✅ 测试通过：未选中状态有hover效果")
    else:
        print("❌ 测试失败：未选中状态应该有hover效果")
    
    # 临时选中用于测试
    card.is_selected = True
    selector._toggle_selection(card)
    selected_style = card.styleSheet()
    
    if card.is_selected == True and 'hover' not in selected_style:
        print("✅ 测试通过：选中状态无hover效果")
    else:
        print("❌ 测试失败：选中状态应该无hover效果")
    
    print("\n测试完成！")
    
    # 注意：由于QApplication事件循环问题，这里不执行app.exec_()
    # 实际测试需要在GUI环境中进行

if __name__ == "__main__":
    test_card_states()