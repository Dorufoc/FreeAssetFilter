#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试文件夹时间轴生成器功能
"""

import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator


def create_test_structure(base_dir):
    """
    创建测试用的文件夹结构和视频文件
    """
    # 创建子文件夹
    subfolders = [
        "event1-device1",
        "event2-设备2",  # 包含中文
        "event3"
    ]
    
    for subfolder in subfolders:
        folder_path = os.path.join(base_dir, subfolder)
        os.makedirs(folder_path)
        
        # 创建测试视频文件
        video_path = os.path.join(folder_path, "test_video.mp4")
        # 创建一个空文件（实际测试时需要替换为真实视频文件）
        with open(video_path, 'w') as f:
            f.write("test video content")


def test_folder_timeline_generator():
    """
    测试文件夹时间轴生成器
    """
    print("开始测试文件夹时间轴生成器...")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    print(f"创建临时测试目录: {temp_dir}")
    
    try:
        # 创建测试结构
        create_test_structure(temp_dir)
        
        # 创建生成器实例
        generator = FolderTimelineGenerator()
        
        # 生成输出CSV路径
        output_csv = os.path.join(temp_dir, "test_timeline.csv")
        
        # 测试生成时间轴CSV
        success, message = generator.generate_timeline_csv(temp_dir, output_csv)
        
        if success:
            print(f"成功: 时间轴生成成功: {message}")
            
            # 验证生成的CSV文件
            if os.path.exists(output_csv):
                print(f"成功: CSV文件已生成: {output_csv}")
                
                # 读取CSV内容
                import csv
                with open(output_csv, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    header = next(reader)
                    rows = list(reader)
                    
                print(f"成功: CSV内容验证成功:")
                print(f"  表头: {header}")
                print(f"  行数: {len(rows)}")
                for i, row in enumerate(rows):
                    print(f"  第{i+1}行: {row}")
            else:
                print("失败: CSV文件未生成")
        else:
            print(f"失败: 时间轴生成失败: {message}")
            
    except Exception as e:
        print(f"失败: 测试过程中发生错误: {str(e)}")
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)
        print(f"\n清理临时测试目录: {temp_dir}")


if __name__ == "__main__":
    test_folder_timeline_generator()
