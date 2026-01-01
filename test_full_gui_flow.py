#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import csv
import datetime
import tempfile
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator


def test_complete_generation():
    """测试完整的生成流程"""
    print("===== 测试完整生成流程 ====")
    
    # 输入文件夹（使用用户报告的路径）
    input_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    # 测试1：使用完整绝对路径作为输出
    print("\n测试1：使用完整绝对路径作为输出")
    output_path1 = r"E:\DFTP\飞院空镜头\test_output_absolute.csv"
    
    generator = FolderTimelineGenerator()
    success, message = generator.generate_timeline_csv(input_folder, output_path1)
    
    print(f"生成结果: {'成功' if success else '失败'}")
    print(f"消息: {message}")
    
    if success:
        if os.path.exists(output_path1):
            print(f"✓ 文件成功保存到指定路径: {output_path1}")
            print(f"文件大小: {os.path.getsize(output_path1)} 字节")
        else:
            print(f"✗ 文件未保存到指定路径")
            
            # 检查是否保存到了其他位置
            default_path = os.path.join(os.getcwd(), "timeline_generated.csv")
            if os.path.exists(default_path):
                print(f"✗ 文件被保存到了默认位置: {default_path}")
    
    # 测试2：使用相对路径作为输出
    print("\n测试2：使用相对路径作为输出")
    output_path2 = "test_output_relative.csv"
    
    success, message = generator.generate_timeline_csv(input_folder, output_path2)
    
    print(f"生成结果: {'成功' if success else '失败'}")
    print(f"消息: {message}")
    
    if success:
        expected_path = os.path.abspath(output_path2)
        if os.path.exists(expected_path):
            print(f"✓ 文件成功保存到预期路径: {expected_path}")
            print(f"文件大小: {os.path.getsize(expected_path)} 字节")
        else:
            print(f"✗ 文件未保存到预期路径")
            
            # 检查是否保存到了其他位置
            default_path = os.path.join(os.getcwd(), "timeline_generated.csv")
            if os.path.exists(default_path):
                print(f"✗ 文件被保存到了默认位置: {default_path}")
    
    # 测试3：模拟GUI调用流程
    print("\n测试3：模拟GUI调用流程")
    
    # 模拟QFileDialog.getExistingDirectory返回的路径
    gui_input_folder = input_folder
    
    # 模拟QFileDialog.getSaveFileName返回的路径
    gui_output_path, _ = (r"E:\DFTP\飞院空镜头\gui_test_output.csv", "*.csv")
    
    print(f"模拟GUI选择的输入路径: {gui_input_folder}")
    print(f"模拟GUI选择的输出路径: {gui_output_path}")
    
    success, message = generator.generate_timeline_csv(gui_input_folder, gui_output_path)
    
    print(f"生成结果: {'成功' if success else '失败'}")
    print(f"消息: {message}")
    
    if success:
        if os.path.exists(gui_output_path):
            print(f"✓ 文件成功保存到GUI指定路径: {gui_output_path}")
            print(f"文件大小: {os.path.getsize(gui_output_path)} 字节")
            
            # 读取并显示CSV内容
            with open(gui_output_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                print(f"表头: {header}")
                
                rows = list(reader)
                print(f"数据行数: {len(rows)}")
                
                # 统计每个事件的数量
                event_counts = {}
                for row in rows:
                    event = row[0]
                    event_counts[event] = event_counts.get(event, 0) + 1
                
                print("各事件数量:")
                for event, count in event_counts.items():
                    print(f"  {event}: {count} 条")
        else:
            print(f"✗ 文件未保存到GUI指定路径")
            
            # 检查是否保存到了默认位置
            default_path = os.path.join(os.getcwd(), "timeline_generated.csv")
            if os.path.exists(default_path):
                print(f"✗ 文件被保存到了默认位置: {default_path}")


def test_path_manipulation():
    """测试路径处理逻辑"""
    print("\n\n===== 测试路径处理逻辑 ====")
    
    # 测试os.path.dirname的行为
    test_paths = [
        r"E:\DFTP\飞院空镜头\test.csv",
        r"E:\DFTP\飞院空镜头\subfolder\test.csv",
        r"test.csv",
        r"subfolder\test.csv"
    ]
    
    for path in test_paths:
        dir_name = os.path.dirname(path)
        print(f"路径: {path}")
        print(f"目录名: {dir_name}")
        print(f"目录是否存在: {os.path.exists(dir_name) if dir_name else '空'}")
        print()


if __name__ == "__main__":
    test_complete_generation()
    test_path_manipulation()
