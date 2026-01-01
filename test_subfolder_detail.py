#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
子文件夹详细分析测试脚本
检查每个子文件夹的内容和视频文件识别情况
"""

import os
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_subfolder_details():
    """详细检查每个子文件夹的内容"""
    print("=== 子文件夹详细分析测试 ===")
    
    # 测试文件夹
    test_folder = r"E:\DFTP\飞院空镜头\20251230机关元旦晚会"
    
    print(f"测试文件夹: {test_folder}")
    
    # 检查子文件夹
    try:
        subfolders = []
        for item in os.listdir(test_folder):
            item_path = os.path.join(test_folder, item)
            if os.path.isdir(item_path):
                subfolders.append((item, item_path))
        
        print(f"\n找到 {len(subfolders)} 个子文件夹:")
        
        for folder_name, folder_path in subfolders:
            print(f"\n--- {folder_name} ---")
            print(f"路径: {folder_path}")
            
            # 检查子文件夹中的文件
            files = []
            for file in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file)
                if os.path.isfile(file_path):
                    files.append(file)
            
            print(f"文件数量: {len(files)}")
            
            # 检查视频文件
            generator = FolderTimelineGenerator()
            video_files = generator._get_video_files(folder_path)
            print(f"视频文件数量: {len(video_files)}")
            
            if video_files:
                print(f"前5个视频文件:")
                for i, video in enumerate(video_files[:5], 1):
                    print(f"  {i}. {os.path.basename(video)}")
                    
                # 尝试获取第一个视频的信息
                print(f"\n尝试获取第一个视频的信息:")
                try:
                    creation_time, duration = generator._get_video_info(video_files[0])
                    print(f"创建时间: {creation_time}")
                    print(f"时长: {duration} 秒")
                except Exception as e:
                    print(f"获取视频信息失败: {str(e)}")
            else:
                print("无视频文件")
                
                # 列出所有文件
                if files:
                    print(f"\n所有文件:")
                    for file in files[:10]:  # 最多显示10个
                        print(f"  {file}")
                    if len(files) > 10:
                        print(f"  ... 还有 {len(files) - 10} 个文件")
    
    except Exception as e:
        print(f"错误: 检查子文件夹失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n=== 测试完成 ===")
    return True

def test_file_extensions():
    """测试视频文件扩展名识别"""
    print("\n=== 视频文件扩展名测试 ===")
    
    generator = FolderTimelineGenerator()
    print(f"支持的视频扩展名: {generator.video_extensions}")
    
    # 测试文件识别
    test_files = [
        "video.mp4",
        "video.MP4",  # 大写扩展名
        "video.avi",
        "video.mov",
        "video.mkv",
        "video.txt",  # 非视频文件
        "video.jpg",  # 非视频文件
    ]
    
    print("\n文件识别测试:")
    for file in test_files:
        ext = os.path.splitext(file)[1].lower()
        is_video = ext in generator.video_extensions
        print(f"  {file}: {'视频文件' if is_video else '非视频文件'}")

if __name__ == "__main__":
    print("开始子文件夹详细分析...")
    test_subfolder_details()
    test_file_extensions()
