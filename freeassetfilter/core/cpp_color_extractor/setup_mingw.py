#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ 颜色提取器扩展模块编译配置 - MinGW 专用版本

使用方法:
    python setup_mingw.py build_ext --inplace --compiler=mingw32
"""

import os
import sys
import platform
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

# 强制使用 MinGW 编译器
os.environ['CC'] = 'gcc'
os.environ['CXX'] = 'g++'

# 定义扩展模块
ext_modules = [
    Extension(
        "color_extractor_cpp",
        sources=["color_extractor.cpp"],
        include_dirs=[],
        define_macros=[("VERSION_INFO", '"1.0.0"')],
        language='c++',
    ),
]

# MinGW 编译选项
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
        "-D_hypot=hypot", # 解决 MinGW 的 hypot 冲突
    ]
    ext.extra_link_args = [
        "-fopenmp", 
        "-static-libgcc", 
        "-static-libstdc++",
        "-lpython39",  # 链接 Python 库
    ]


class BuildExt(build_ext):
    """自定义编译命令，强制使用 MinGW"""
    def build_extensions(self):
        # 设置编译器
        self.compiler.set_executable('compiler_so', 'g++')
        self.compiler.set_executable('compiler_cxx', 'g++')
        self.compiler.set_executable('linker_so', 'g++')
        
        # 调用父类方法
        super().build_extensions()


setup(
    name="color_extractor_cpp",
    version="1.0.0",
    author="FreeAssetFilter",
    description="C++ 实现的高性能封面颜色提取器",
    long_description="使用 K-Means 聚类和 CIEDE2000 色差算法的高性能颜色提取",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildExt},
    zip_safe=False,
    python_requires=">=3.8",
)
