#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试LibreOffice路径处理
"""

import os
import subprocess
import tempfile

test_file = "D:/桌面/新建 PPTX 演示文稿.pptx"
temp_dir = tempfile.mkdtemp()
print(f"临时目录: {temp_dir}")

try:
    # 获取基础文件名
    file_name = os.path.basename(test_file)
    base_name = os.path.splitext(file_name)[0]
    print(f"基础文件名: {base_name}")
    
    # 测试1: 使用英文临时目录
    print("\n测试1: 使用英文临时目录")
    cmd1 = [
        "d:\文档\Trae Project\FreeAssetFilter\data\LibreOfficePortable\App\LibreOffice\program\soffice.exe",
        "--headless",
        "--convert-to", "pdf:writer_pdf_Export",
        "--outdir", temp_dir,
        "--nofirststartwizard",
        "--norestore",
        "--minimized",
        test_file
    ]
    
    print(f"执行命令: {' '.join(cmd1)}")
    result1 = subprocess.run(cmd1, capture_output=True, text=True)
    print(f"返回码: {result1.returncode}")
    print(f"输出: {result1.stdout}")
    print(f"错误: {result1.stderr}")
    
    # 检查生成的文件
    pdf_files = os.listdir(temp_dir)
    print(f"临时目录中的文件: {pdf_files}")
    
    # 测试2: 使用中文临时目录
    print("\n测试2: 使用中文临时目录")
    chinese_temp_dir = os.path.join(temp_dir, "中文目录")
    os.makedirs(chinese_temp_dir)
    
    cmd2 = [
        "d:\文档\Trae Project\FreeAssetFilter\data\LibreOfficePortable\App\LibreOffice\program\soffice.exe",
        "--headless",
        "--convert-to", "pdf:writer_pdf_Export",
        "--outdir", chinese_temp_dir,
        "--nofirststartwizard",
        "--norestore",
        "--minimized",
        test_file
    ]
    
    print(f"执行命令: {' '.join(cmd2)}")
    result2 = subprocess.run(cmd2, capture_output=True, text=True)
    print(f"返回码: {result2.returncode}")
    print(f"输出: {result2.stdout}")
    print(f"错误: {result2.stderr}")
    
    # 检查生成的文件
    if os.path.exists(chinese_temp_dir):
        pdf_files2 = os.listdir(chinese_temp_dir)
        print(f"中文临时目录中的文件: {pdf_files2}")
        
finally:
    # 清理临时目录
    import shutil
    shutil.rmtree(temp_dir)
    print(f"\n已删除临时目录: {temp_dir}")
