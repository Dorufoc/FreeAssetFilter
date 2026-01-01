#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进度条功能测试脚本
用于验证FolderTimelineGenerator的进度回调功能
"""

import os
import sys
import time
from freeassetfilter.core.folder_timeline_generator import FolderTimelineGenerator

def test_progress_callback():
    """测试进度回调功能"""
    print("=== 进度回调功能测试 ===")
    
    # 使用测试文件夹路径
    test_folder = r"C:\Users\Dorufoc\Desktop\code\FreeAssetFilter\test_timeline_folder"
    output_csv = r"C:\Users\Dorufoc\Desktop\code\FreeAssetFilter\test_output.csv"
    
    # 验证测试文件夹是否存在
    if not os.path.exists(test_folder):
        print(f"测试文件夹不存在: {test_folder}")
        print("请修改test_folder变量为实际存在的文件夹路径")
        return False
    
    # 进度回调函数
    def progress_callback(current, total):
        percentage = (current / total) * 100 if total > 0 else 0
        print(f"进度: {current}/{total} ({percentage:.1f}%)", end="\r")
        time.sleep(0.01)  # 模拟处理延迟
    
    try:
        generator = FolderTimelineGenerator()
        start_time = time.time()
        
        print(f"开始处理文件夹: {test_folder}")
        success, message = generator.generate_timeline_csv(test_folder, output_csv, progress_callback)
        
        print("\n" + "="*50)
        end_time = time.time()
        
        if success:
            print(f"✅ 成功: {message}")
            print(f"处理时间: {end_time - start_time:.2f} 秒")
            
            # 验证生成的CSV文件
            if os.path.exists(output_csv):
                file_size = os.path.getsize(output_csv)
                print(f"生成的CSV文件大小: {file_size} 字节")
                return True
            else:
                print("❌ 生成的CSV文件不存在")
                return False
        else:
            print(f"❌ 失败: {message}")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_progress_callback()
    sys.exit(0 if success else 1)
