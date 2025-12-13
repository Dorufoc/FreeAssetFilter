#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
创建大文件脚本，用于测试大文件预览功能
"""

import os

def create_large_text_file(file_path, size_mb=100):
    """
    创建指定大小的文本文件
    
    Args:
        file_path (str): 文件路径
        size_mb (int): 文件大小（MB）
    """
    # 计算需要写入的字节数
    target_size = size_mb * 1024 * 1024
    
    # 写入的内容
    line = 'This is a test line. ' * 10 + '\n'
    line_size = len(line.encode('utf-8'))
    
    # 计算需要写入的行数
    lines_needed = target_size // line_size
    
    print(f"创建 {size_mb}MB 的文本文件: {file_path}")
    print(f"每行大小: {line_size} 字节")
    print(f"需要写入 {lines_needed} 行")
    
    with open(file_path, 'w', encoding='utf-8') as f:
        for i in range(lines_needed):
            if i % 100000 == 0:
                print(f"已写入 {i} 行")
            f.write(line)
    
    # 检查文件大小
    actual_size = os.path.getsize(file_path)
    print(f"文件创建完成，实际大小: {actual_size / (1024 * 1024):.2f}MB")

if __name__ == "__main__":
    create_large_text_file('test_large_file.txt', size_mb=50)
