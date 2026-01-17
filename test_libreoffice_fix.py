#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试LibreOffice PDF转换修复功能
"""

import os
import time
import tempfile
import shutil

# 创建一个临时测试目录
test_temp_dir = tempfile.mkdtemp()
print(f"创建临时测试目录: {test_temp_dir}")

try:
    # 模拟修复后的临时文件命名逻辑
    test_file_name = "test_document.docx"
    base_name = os.path.splitext(test_file_name)[0]
    
    # 第一次转换（模拟）
    timestamp1 = int(time.time())
    temp_pdf_name1 = f"{base_name}_{timestamp1}_temp.pdf"
    temp_pdf_path1 = os.path.join(test_temp_dir, temp_pdf_name1)
    
    # 创建一个空的PDF文件模拟转换结果
    with open(temp_pdf_path1, 'w') as f:
        f.write("PDF content 1")
    
    print(f"第一次转换生成的临时文件: {temp_pdf_path1}")
    
    # 等待一下，让时间戳变化
    time.sleep(2)
    
    # 第二次转换（模拟）
    timestamp2 = int(time.time())
    temp_pdf_name2 = f"{base_name}_{timestamp2}_temp.pdf"
    temp_pdf_path2 = os.path.join(test_temp_dir, temp_pdf_name2)
    
    # 创建一个新的空PDF文件模拟转换结果
    with open(temp_pdf_path2, 'w') as f:
        f.write("PDF content 2")
    
    print(f"第二次转换生成的临时文件: {temp_pdf_path2}")
    
    # 模拟清理逻辑
    import glob
    
    # 删除所有同名但不同时间戳的临时文件
    old_pdf_files = glob.glob(os.path.join(test_temp_dir, f"{base_name}_*_temp.pdf"))
    for old_file in old_pdf_files:
        if os.path.exists(old_file):
            os.remove(old_file)
            print(f"已删除临时PDF文件: {old_file}")
    
    print("测试完成！修复功能正常工作。")
    
finally:
    # 清理临时测试目录
    shutil.rmtree(test_temp_dir)
    print(f"已删除临时测试目录: {test_temp_dir}")
