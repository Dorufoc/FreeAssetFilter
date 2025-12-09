#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试依赖检查功能
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入依赖检查函数
from main import check_dependencies, show_dependency_error

# 测试依赖检查功能
def test_dependency_check():
    print("开始测试依赖检查功能...")
    success, missing_deps, version_issues = check_dependencies()
    
    print(f"检查结果: {'成功' if success else '失败'}")
    print(f"缺失的依赖: {missing_deps}")
    print(f"版本问题: {version_issues}")
    
    if not success:
        print("\n显示错误信息...")
        show_dependency_error(missing_deps, version_issues)
    
    return success

if __name__ == "__main__":
    test_dependency_check()
