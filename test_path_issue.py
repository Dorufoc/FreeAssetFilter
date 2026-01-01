#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import csv
import datetime
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator


def test_path_handling():
    """测试路径处理功能"""
    print("===== 测试路径处理 ====")
    
    # 测试文件夹路径
    test_folder = "E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    # 测试输出路径
    test_output = "E:\DFTP\飞院空镜头\test_output.csv"
    
    # 创建生成器实例
    generator = FolderTimelineGenerator()
    
    print(f"输入文件夹: {test_folder}")
    print(f"输出路径: {test_output}")
    print(f"输出目录: {os.path.dirname(test_output)}")
    
    # 测试文件夹存在性
    if os.path.exists(test_folder):
        print(f"✓ 输入文件夹存在")
        
        # 测试文件夹内容
        print("\n文件夹内容:")
        for item in os.listdir(test_folder):
            item_path = os.path.join(test_folder, item)
            if os.path.isdir(item_path):
                print(f"  📁 {item} (文件夹)")
            else:
                print(f"  📄 {item} (文件)")
    else:
        print(f"✗ 输入文件夹不存在")
        return
    
    # 测试_collect_timeline_data方法
    print("\n===== 测试_collect_timeline_data ====")
    try:
        data = generator._collect_timeline_data(test_folder)
        print(f"收集到 {len(data)} 条时间轴数据")
        
        if data:
            print("前3条数据:")
            for i, item in enumerate(data[:3]):
                print(f"  {i+1}. {item}")
    except Exception as e:
        print(f"错误: {str(e)}")
    
    # 测试_write_csv方法
    print("\n===== 测试_write_csv ====")
    try:
        # 创建测试数据
        test_data = [
            {
                'event_name': '测试事件',
                'device_name': '测试设备',
                'start_time': '2024-01-01 00:00:00',
                'end_time': '2024-01-01 00:01:00'
            }
        ]
        
        generator._write_csv(test_output, test_data)
        
        if os.path.exists(test_output):
            print(f"✓ 文件成功写入: {test_output}")
            print(f"文件大小: {os.path.getsize(test_output)} 字节")
            
            # 读取文件内容
            with open(test_output, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"文件内容:\n{content}")
        else:
            print(f"✗ 文件写入失败")
    except Exception as e:
        print(f"错误: {str(e)}")


def test_full_generation():
    """测试完整的生成流程"""
    print("\n\n===== 测试完整生成流程 ====")
    
    # 测试文件夹路径
    test_folder = "E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    # 测试输出路径
    test_output = "E:\DFTP\飞院空镜头\test_full_output.csv"
    
    # 创建生成器实例
    generator = FolderTimelineGenerator()
    
    print(f"输入文件夹: {test_folder}")
    print(f"输出路径: {test_output}")
    
    # 执行完整生成
    try:
        success, message = generator.generate_timeline_csv(test_folder, test_output)
        print(f"\n生成结果: {'成功' if success else '失败'}")
        print(f"消息: {message}")
        
        if success and os.path.exists(test_output):
            print(f"\n生成的文件: {test_output}")
            print(f"文件大小: {os.path.getsize(test_output)} 字节")
            
            # 读取文件内容
            with open(test_output, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                print(f"表头: {header}")
                
                rows = list(reader)
                print(f"数据行数: {len(rows)}")
                
                if rows:
                    print("前3行数据:")
                    for i, row in enumerate(rows[:3]):
                        print(f"  {i+1}. {row}")
    except Exception as e:
        print(f"错误: {str(e)}")


if __name__ == "__main__":
    test_path_handling()
    test_full_generation()
