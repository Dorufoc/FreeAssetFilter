#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量修复Python文件编码错误脚本
"""

import os
import re

# 正确的协议信息模板
CORRECT_LICENSE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

'''

# 修复单个文件
def fix_file(file_path):
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        # 寻找文件中的文档字符串开始位置
        docstring_start = content.find('"""')
        if docstring_start == -1:
            # 如果没有文档字符串，直接在文件开头添加
            file_description = os.path.basename(file_path)[:-3]
            new_content = CORRECT_LICENSE + file_description + '\n"""\n' + content
        else:
            # 寻找文档字符串结束位置
            docstring_end = content.find('"""', docstring_start + 3)
            if docstring_end == -1:
                # 如果文档字符串不完整，直接替换整个文件
                file_description = os.path.basename(file_path)[:-3]
                new_content = CORRECT_LICENSE + file_description + '\n"""\n' + content
            else:
                # 提取现有文档字符串内容
                existing_docstring = content[docstring_start+3:docstring_end]
                
                # 提取文件描述（排除协议信息部分）
                # 简单处理：如果包含FreeAssetFilter，则替换整个文档字符串
                if 'FreeAssetFilter' in existing_docstring:
                    # 提取实际的文件描述
                    lines = existing_docstring.split('\n')
                    file_description = ''
                    in_license = True
                    for line in lines:
                        if in_license:
                            # 跳过协议信息行，直到找到第一个空行或实际描述
                            if line.strip() and 'FreeAssetFilter' not in line and 'Copyright' not in line and '协议说明' not in line and '项目地址' not in line and '许可协议' not in line:
                                file_description = line.strip()
                                in_license = False
                        else:
                            # 收集描述内容
                            if line.strip():
                                file_description += '\n' + line.strip()
                    
                    # 如果没有找到描述，使用默认值
                    if not file_description:
                        file_description = os.path.basename(file_path)[:-3]
                    
                    # 构建新的文档字符串
                    new_docstring = CORRECT_LICENSE + file_description + '\n"""'
                    
                    # 替换原有文档字符串
                    new_content = content[:docstring_start] + new_docstring + content[docstring_end+3:]
                else:
                    # 现有文档字符串不包含FreeAssetFilter，保留原有内容
                    new_content = content
        
        # 写入修复后的内容
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✓ 修复成功: {file_path}")
        return True
    except Exception as e:
        print(f"✗ 修复失败: {file_path} - {e}")
        return False

# 递归修复所有Python文件
def fix_all_files(directory):
    success_count = 0
    error_count = 0
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                if fix_file(file_path):
                    success_count += 1
                else:
                    error_count += 1
    
    print(f"\n修复完成！")
    print(f"成功修复: {success_count} 个文件")
    print(f"修复失败: {error_count} 个文件")

if __name__ == "__main__":
    project_dir = os.path.dirname(os.path.abspath(__file__))
    fix_all_files(project_dir)
