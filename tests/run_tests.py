#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 测试运行器
用于程序化运行 pytest 测试
"""

import sys
import os
import argparse


def main():
    """运行测试的主函数"""
    # 获取项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 将项目根目录添加到 Python 路径
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="FreeAssetFilter 测试运行器")
    parser.add_argument(
        "tests",
        nargs="*",
        default=["tests/"],
        help="要运行的测试目录或文件（默认: tests/）"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细输出"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="显示精简输出"
    )
    parser.add_argument(
        "-k",
        help="只运行匹配指定表达式的测试"
    )
    parser.add_argument(
        "--tb",
        choices=["auto", "long", "short", "no", "line", "native"],
        default="short",
        help="回溯信息显示模式"
    )
    parser.add_argument(
        "--cov",
        action="store_true",
        help="生成覆盖率报告"
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        help="生成 HTML 报告"
    )
    
    args = parser.parse_args()
    
    # 构建 pytest 参数
    pytest_args = []
    
    if args.verbose:
        pytest_args.append("-v")
    elif args.quiet:
        pytest_args.append("-q")
    
    if args.k:
        pytest_args.extend(["-k", args.k])
    
    pytest_args.extend(["--tb", args.tb])
    
    if args.cov:
        pytest_args.append("--cov=freeassetfilter")
    
    if args.html:
        pytest_args.extend(["--html", args.html])
    
    # 添加测试路径
    pytest_args.extend(args.tests)
    
    # 运行 pytest
    import pytest
    exit_code = pytest.main(pytest_args)
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
