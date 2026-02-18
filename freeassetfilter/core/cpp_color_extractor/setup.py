#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ 颜色提取器扩展模块编译配置

使用方法:
    python setup.py build_ext --inplace
    或
    pip install -e .
"""

import os
import sys
import platform
import subprocess
from pybind11.setup_helpers import Pybind11Extension, build_ext
from pybind11 import get_cmake_dir
from setuptools import setup, Extension

def detect_compiler():
    """检测可用的 C++ 编译器"""
    # 检查 MinGW g++
    try:
        result = subprocess.run(["g++", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return "mingw"
    except FileNotFoundError:
        pass
    
    # 检查 MSVC
    try:
        result = subprocess.run(["cl"], capture_output=True, text=True)
        if result.returncode == 0:
            return "msvc"
    except FileNotFoundError:
        pass
    
    return None

# 检测编译器
COMPILER = detect_compiler()
print(f"[Setup] 检测到编译器: {COMPILER}")

# 获取当前目录
HERE = os.path.dirname(os.path.abspath(__file__))

# 定义扩展模块
ext_modules = [
    Pybind11Extension(
        "color_extractor_cpp",
        sources=["color_extractor.cpp"],
        include_dirs=[],
        define_macros=[("VERSION_INFO", '"1.0.0"')],
        cxx_std=17,
    ),
]

# 根据平台和编译器添加编译选项
if platform.system() == "Windows":
    if COMPILER == "mingw":
        # MinGW 选项
        print("[Setup] 使用 MinGW 编译器")
        for ext in ext_modules:
            ext.extra_compile_args = [
                "-O3",           # 优化级别 3
                "-Wall",         # 显示所有警告
                "-Wextra",       # 显示额外警告
                "-fopenmp",      # OpenMP 支持
                "-std=c++17",    # C++17 标准
                "-ffast-math",   # 快速数学运算
                "-march=native", # 针对本地 CPU 优化
                "-DMS_WIN64",    # Windows 64位定义
            ]
            ext.extra_link_args = ["-fopenmp", "-static-libgcc", "-static-libstdc++"]
    else:
        # Windows MSVC 选项
        print("[Setup] 使用 MSVC 编译器")
        for ext in ext_modules:
            ext.extra_compile_args = [
                "/O2",           # 优化级别 2
                "/W3",           # 警告级别 3
                "/EHsc",         # 异常处理
                "/openmp",       # OpenMP 支持
                "/std:c++17",    # C++17 标准
            ]
            ext.extra_link_args = ["/openmp"]
        
elif platform.system() == "Darwin":
    # macOS 选项
    for ext in ext_modules:
        ext.extra_compile_args = [
            "-O3",           # 优化级别 3
            "-Wall",         # 显示所有警告
            "-Wextra",       # 显示额外警告
            "-std=c++17",    # C++17 标准
            # macOS 默认不包含 OpenMP，需要单独安装 libomp
            # "-Xpreprocessor", "-fopenmp",  # OpenMP 支持（可选）
        ]
        # ext.extra_link_args = ["-lomp"]
        
else:
    # Linux 和其他平台选项
    for ext in ext_modules:
        ext.extra_compile_args = [
            "-O3",           # 优化级别 3
            "-Wall",         # 显示所有警告
            "-Wextra",       # 显示额外警告
            "-fopenmp",      # OpenMP 支持
            "-std=c++17",    # C++17 标准
            "-ffast-math",   # 快速数学运算（可能牺牲一些精度换取速度）
            "-march=native", # 针对本地 CPU 优化
        ]
        ext.extra_link_args = ["-fopenmp"]


setup(
    name="color_extractor_cpp",
    version="1.0.0",
    author="FreeAssetFilter",
    description="C++ 实现的高性能封面颜色提取器",
    long_description="使用 K-Means 聚类和 CIEDE2000 色差算法的高性能颜色提取",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.8",
    install_requires=[
        "pybind11>=2.10.0",
    ],
)
