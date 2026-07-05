#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复测试文件中的导入问题
"""
import os
import re
from pathlib import Path

# 类名映射：测试使用的类名 -> 实际的类名
CLASS_NAME_FIXES = {
    # core 模块
    'FixEncoding': 'EncodingFixer',
    'IconUtils': 'IconHelper',
    'LutPreviewGenerator': 'LUTPreviewGenerator',
    'LutUtils': 'LUTUtils',
    'MpvManager': 'MPVManager',
    'MpvPlayerCore': 'MPVPlayerCore',
    'Py7zCore': 'Py7zHandler',
    'TimelineGenerator': 'TimeLineGenerator',
    'UpdateManager': 'UpdateChecker',
    
    # widgets 模块  
    'InputWidgets': 'CustomInput',
    'ListWidgets': 'CustomListWidget',
    'MenuList': 'CustomMenuList',
    'ProgressWidgets': 'CustomProgressBar',
    'PsdProgressDialog': 'PSDProgressDialog',
    'SettingWidgets': 'SettingCard',
    'SwitchWidgets': 'CustomSwitch',
    'TableWidgets': 'CustomTableWidget',
    
    # components 模块
    'FileSelector': 'CustomFileSelector',
    'PdfPreviewer': 'PDFPreviewer',
    'SettingsWindow': 'CustomSettingsWindow',
}


def fix_test_file(filepath):
    """修复单个测试文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # 修复导入语句
    for wrong, correct in CLASS_NAME_FIXES.items():
        # 修复 from ... import WrongName
        pattern = rf'from freeassetfilter\.\w+\.\w+ import {wrong}'
        replacement = f'from freeassetfilter.{get_package(wrong)}.{get_module(wrong)} import {correct}'
        content = re.sub(pattern, replacement, content)
        
        # 简单的字符串替换作为备选
        content = content.replace(f'import {wrong}', f'import {correct}')
    
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  修复: {filepath}")
        return True
    return False


def get_package(class_name):
    """根据类名推断包名"""
    # 这里简化处理，实际需要根据项目结构调整
    return 'components'


def get_module(class_name):
    """根据类名推断模块名"""
    # 转换驼峰命名为下划线命名
    s = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', class_name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s).lower()


def main():
    """主函数"""
    test_dir = Path('tests/unit')
    fixed_count = 0
    
    print("=" * 60)
    print("修复测试文件导入")
    print("=" * 60)
    
    for test_file in test_dir.glob('test_*.py'):
        if fix_test_file(test_file):
            fixed_count += 1
    
    print(f"\n修复了 {fixed_count} 个文件")


if __name__ == '__main__':
    main()
