#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试视频文件信息提取功能
"""

import sys
import os
from PyQt5.QtWidgets import QApplication
from src.core.file_info_browser import FileInfoBrowser
from datetime import datetime

if __name__ == "__main__":
    # 创建应用程序实例（PyQt5需要）
    app = QApplication(sys.argv)
    
    # 创建文件信息浏览组件
    file_info_browser = FileInfoBrowser()
    
    # 检查ffprobe是否可用
    print(f"ffprobe是否可用: {file_info_browser._is_ffprobe_available()}")
    
    # 找一个测试视频文件
    test_file = None
    # 检查当前目录是否有视频文件
    for file in os.listdir("."):
        if file.endswith((".mp4", ".avi", ".mov", ".mkv")):
            test_file = file
            break
    
    if test_file:
        print(f"找到测试视频文件: {test_file}")
        
        # 准备测试文件信息
        test_file_info = {
            "name": test_file,
            "path": os.path.abspath(test_file),
            "is_dir": False,
            "size": os.path.getsize(test_file),
            "modified": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "suffix": os.path.splitext(test_file)[1][1:].lower()
        }
        
        # 提取文件信息
        file_info_browser.current_file = test_file_info
        file_info_browser.extract_file_info()
        
        # 打印提取的视频信息
        print("\n=== 视频基本信息 ===")
        if "extra" in file_info_browser.file_info:
            for key, value in file_info_browser.file_info["extra"].items():
                print(f"{key}: {value}")
        
        print("\n=== 视频高级信息 ===")
        if "advanced" in file_info_browser.file_info:
            for key, value in file_info_browser.file_info["advanced"].items():
                if isinstance(value, dict):
                    print(f"{key}:")
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, dict):
                            print(f"  {sub_key}:")
                            for sub_sub_key, sub_sub_value in sub_value.items():
                                print(f"    {sub_sub_key}: {sub_sub_value}")
                        else:
                            print(f"  {sub_key}: {sub_sub_value}")
                else:
                    print(f"{key}: {value}")
    else:
        print("未找到测试视频文件，创建一个简单的测试")
        
        # 创建一个简单的文本文件作为测试
        test_txt_file = "test_video.txt"
        with open(test_txt_file, "w") as f:
            f.write("这是一个测试文件")
        
        # 准备测试文件信息，假装是视频文件
        test_file_info = {
            "name": "test_video.mp4",
            "path": os.path.abspath(test_txt_file),
            "is_dir": False,
            "size": os.path.getsize(test_txt_file),
            "modified": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "created": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "suffix": "mp4"
        }
        
        # 提取文件信息
        file_info_browser.current_file = test_file_info
        file_info_browser.extract_file_info()
        
        # 打印提取的视频信息
        print("\n=== 视频基本信息 ===")
        if "extra" in file_info_browser.file_info:
            for key, value in file_info_browser.file_info["extra"].items():
                print(f"{key}: {value}")
        
        # 删除测试文件
        os.remove(test_txt_file)
    
    print("\n测试完成")
    sys.exit(0)