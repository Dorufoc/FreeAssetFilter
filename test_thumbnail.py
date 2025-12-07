#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试缩略图生成功能，确保保持原始比例
"""

import os
import sys
from PIL import Image

# 添加src目录到路径，以便导入模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from components.custom_file_selector import CustomFileSelector
from PyQt5.QtWidgets import QApplication

# 创建应用程序实例
app = QApplication(sys.argv)

# 创建文件选择器实例
file_selector = CustomFileSelector()

# 测试图片路径（请替换为你实际的测试图片路径）
test_image_path = "test_image.jpg"  # 替换为实际图片路径
test_video_path = "test_video.mp4"  # 替换为实际视频路径

# 测试图片缩略图生成
if os.path.exists(test_image_path):
    print(f"测试图片: {test_image_path}")
    print(f"图片信息: {Image.open(test_image_path).size}")
    
    # 生成缩略图
    file_selector._create_thumbnail(test_image_path)
    
    # 获取缩略图路径
    thumbnail_path = file_selector._get_thumbnail_path(test_image_path)
    print(f"生成的缩略图路径: {thumbnail_path}")
    
    if os.path.exists(thumbnail_path):
        # 检查缩略图信息
        thumbnail = Image.open(thumbnail_path)
        print(f"缩略图尺寸: {thumbnail.size}")
        print(f"缩略图格式: {thumbnail.format}")
        print(f"缩略图模式: {thumbnail.mode}")
        print("图片缩略图生成成功!")
    else:
        print("图片缩略图生成失败!")
else:
    print(f"测试图片不存在: {test_image_path}")

print("-" * 50)

# 测试视频缩略图生成
if os.path.exists(test_video_path):
    print(f"测试视频: {test_video_path}")
    
    # 生成缩略图
    file_selector._create_thumbnail(test_video_path)
    
    # 获取缩略图路径
    thumbnail_path = file_selector._get_thumbnail_path(test_video_path)
    print(f"生成的缩略图路径: {thumbnail_path}")
    
    if os.path.exists(thumbnail_path):
        # 检查缩略图信息
        thumbnail = Image.open(thumbnail_path)
        print(f"缩略图尺寸: {thumbnail.size}")
        print(f"缩略图格式: {thumbnail.format}")
        print(f"缩略图模式: {thumbnail.mode}")
        print("视频缩略图生成成功!")
    else:
        print("视频缩略图生成失败!")
else:
    print(f"测试视频不存在: {test_video_path}")

print("测试完成!")
