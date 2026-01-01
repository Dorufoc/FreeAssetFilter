#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路径问题分析测试脚本
模拟用户操作环境，测试文件夹路径处理和数据收集逻辑
"""

import os
import sys
import csv
import datetime
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_path_analysis():
    """测试路径分析和数据收集逻辑"""
    print("=== 路径问题分析测试脚本 ===")
    
    # 测试用户提供的路径
    test_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    test_output = r"E:\test_output.csv"
    
    print(f"\n测试文件夹路径: {test_folder}")
    print(f"测试输出路径: {test_output}")
    
    # 检查测试文件夹是否存在
    if not os.path.exists(test_folder):
        print(f"错误: 测试文件夹不存在: {test_folder}")
        return False
    
    if not os.path.isdir(test_folder):
        print(f"错误: 测试路径不是文件夹: {test_folder}")
        return False
    
    # 创建生成器实例
    generator = FolderTimelineGenerator()
    
    print("\n1. 测试路径转义处理:")
    print(f"原始路径: {test_folder}")
    print(f"os.path.normpath后: {os.path.normpath(test_folder)}")
    print(f"Path对象后: {Path(test_folder)}")
    
    print("\n2. 测试子文件夹识别:")
    try:
        subfolders = []
        for item in os.listdir(test_folder):
            item_path = os.path.join(test_folder, item)
            if os.path.isdir(item_path):
                subfolders.append(item)
        
        print(f"找到 {len(subfolders)} 个子文件夹:")
        for i, folder in enumerate(subfolders, 1):
            print(f"  {i}. {folder}")
    except Exception as e:
        print(f"错误: 获取子文件夹失败: {str(e)}")
        return False
    
    print("\n3. 测试数据收集逻辑:")
    try:
        timeline_data = generator._collect_timeline_data(test_folder)
        print(f"收集到 {len(timeline_data)} 条数据")
        
        if timeline_data:
            print("前3条数据示例:")
            for i, data in enumerate(timeline_data[:3], 1):
                print(f"  {i}. {data}")
    except Exception as e:
        print(f"错误: 收集数据失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n4. 测试CSV写入:")
    try:
        success, message = generator.generate_timeline_csv(test_folder, test_output)
        print(f"生成结果: {'成功' if success else '失败'}")
        print(f"消息: {message}")
        
        # 检查文件是否创建成功
        if success and os.path.exists(test_output):
            print(f"CSV文件已创建: {test_output}")
            print(f"文件大小: {os.path.getsize(test_output)} 字节")
        else:
            print("CSV文件创建失败")
    except Exception as e:
        print(f"错误: 生成CSV失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n=== 测试完成 ===")
    return True

def test_gui_path_handling():
    """模拟GUI路径处理逻辑"""
    print("\n=== 模拟GUI路径处理测试 ===")
    
    # 模拟用户选择的路径
    user_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    user_output = "timeline_generated.csv"  # 默认文件名，无路径
    
    print(f"用户选择的输入文件夹: {user_folder}")
    print(f"用户选择的输出文件名: {user_output}")
    
    # 模拟GUI中的路径处理
    # 当用户只输入文件名而没有路径时，QFileDialog会返回文件名
    # 此时程序会将文件保存在当前工作目录
    if not os.path.dirname(user_output):
        # 如果输出路径只包含文件名，没有目录，则使用当前工作目录
        current_dir = os.getcwd()
        full_output_path = os.path.join(current_dir, user_output)
        print(f"\n当前工作目录: {current_dir}")
        print(f"完整输出路径: {full_output_path}")
    
    # 检查是否为绝对路径
    if os.path.isabs(user_output):
        print(f"输出路径是绝对路径: {user_output}")
    else:
        print(f"输出路径是相对路径: {user_output}")

if __name__ == "__main__":
    test_gui_path_handling()
    test_path_analysis()
