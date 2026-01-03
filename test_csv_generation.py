#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试CSV生成功能
验证是否正确包含视频路径字段
"""

import os
import sys
import tempfile
import shutil
import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_csv_generation():
    """测试CSV生成功能"""
    print("=== 测试CSV生成功能 ===")
    
    try:
        # 创建临时目录结构
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建测试子文件夹
            test_folder = os.path.join(temp_dir, "20251230机关元旦晚会")
            os.makedirs(test_folder)
            
            # 创建视频设备子文件夹
            device_folder1 = os.path.join(test_folder, "A7S3-24105")
            device_folder2 = os.path.join(test_folder, "FX6-70200")
            os.makedirs(device_folder1)
            os.makedirs(device_folder2)
            
            # 创建测试视频文件（空文件即可）
            test_video1 = os.path.join(device_folder1, "test_video1.mp4")
            test_video2 = os.path.join(device_folder2, "test_video2.mp4")
            
            with open(test_video1, 'w') as f:
                f.write("test")
            
            with open(test_video2, 'w') as f:
                f.write("test")
            
            # 设置文件修改时间（模拟实际视频文件的创建时间）
            test_time1 = datetime.datetime(2025, 12, 30, 14, 36, 15)
            test_time2 = datetime.datetime(2025, 12, 30, 14, 37, 53)
            
            os.utime(test_video1, (test_time1.timestamp(), test_time1.timestamp()))
            os.utime(test_video2, (test_time2.timestamp(), test_time2.timestamp()))
            
            print("创建测试文件完成")
            print(f"测试文件夹: {test_folder}")
            print(f"设备文件夹1: {device_folder1}")
            print(f"设备文件夹2: {device_folder2}")
            print(f"测试视频1: {test_video1}")
            print(f"测试视频2: {test_video2}")
            
            # 创建生成器实例
            generator = FolderTimelineGenerator()
            
            # 进度回调函数
            def progress_callback(current, total):
                print(f"进度: {current}/{total} ({(current/total)*100:.1f}%)")
            
            # 生成CSV
            print("\n开始生成CSV...")
            success, message = generator.generate_timeline_csv(test_folder, None, progress_callback)
            
            if success:
                print(f"\nCSV生成成功: {message}")
                
                # 从消息中提取CSV路径
                csv_path = message.split("：")[-1].strip()
                print(f"CSV路径: {csv_path}")
                
                # 检查CSV文件是否存在
                if os.path.exists(csv_path):
                    print(f"\nCSV文件已创建: {csv_path}")
                    
                    # 读取CSV文件内容
                    print("\nCSV文件内容：")
                    with open(csv_path, 'r', encoding='utf-8-sig') as f:
                        for i, line in enumerate(f):
                            if i < 10:  # 只显示前10行
                                print(f"{i+1}: {line.strip()}")
                        print(f"... 共 {i+1} 行")
                else:
                    print(f"\n错误: CSV文件不存在：{csv_path}")
            else:
                print(f"\nCSV生成失败: {message}")
            
            return success
            
    except Exception as e:
        print(f"\n测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_csv_generation()
    if success:
        print("\n🎉 测试通过！CSV生成功能正常工作")
    else:
        print("\n❌ 测试失败！CSV生成功能存在问题")
        sys.exit(1)
