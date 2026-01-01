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


def test_path_handling_fixed():
    """测试修复后的路径处理功能"""
    print("===== 测试修复后的路径处理 ====")
    
    # 测试文件夹路径 - 使用原始字符串（r前缀）避免转义问题
    test_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    # 测试输出路径 - 使用原始字符串
    test_output = r"E:\DFTP\飞院空镜头\test_output.csv"
    
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
        import traceback
        traceback.print_exc()
    
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
        import traceback
        traceback.print_exc()


def test_collect_data_depth():
    """测试数据收集的深度问题"""
    print("\n\n===== 测试数据收集深度 ====")
    
    # 使用当前目录作为测试
    test_folder = os.path.dirname(os.path.abspath(__file__))
    
    # 创建生成器实例
    generator = FolderTimelineGenerator()
    
    print(f"测试文件夹: {test_folder}")
    
    # 测试_collect_timeline_data方法的逻辑
    print("\n_collect_timeline_data方法分析:")
    print("该方法当前只遍历直接子文件夹，不递归遍历嵌套子文件夹")
    print("这可能是导致只识别一个文件夹的原因")
    
    # 测试递归遍历逻辑
    print("\n递归遍历测试:")
    def recursive_list_folder(folder, depth=0):
        """递归列出文件夹内容"""
        try:
            items = os.listdir(folder)
            count = 0
            for item in items:
                item_path = os.path.join(folder, item)
                if os.path.isdir(item_path):
                    indent = "  " * depth
                    print(f"{indent}📁 {item}")
                    count += 1
                    recursive_list_folder(item_path, depth + 1)
            return count
        except Exception as e:
            print(f"错误: {str(e)}")
            return 0
    
    subfolder_count = recursive_list_folder(test_folder)
    print(f"\n总子文件夹数: {subfolder_count}")


if __name__ == "__main__":
    test_collect_data_depth()
    test_path_handling_fixed()
