#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ LUT 预览生成器扩展模块编译配置 - MinGW 专用版本

使用方法:
    python setup_mingw.py build_ext --inplace
"""

import os
import sys
import platform
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

os.environ['CC'] = 'gcc'
os.environ['CXX'] = 'g++'

ext_modules = [
    Extension(
        "lut_preview_cpp",
        sources=["lut_preview.cpp"],
        include_dirs=[],
        define_macros=[("VERSION_INFO", '"1.0.0"')],
        language='c++',
    ),
]

# 构建参数基线（审查 3.1#20 修复）：已移除 -march=native（回退通用 x86-64
# 基线，防老 CPU 非法指令）与 -ffast-math（保持 IEEE 浮点语义；MSVC 侧
# 变更前后样例对拍 0 差异）。
for ext in ext_modules:
    ext.extra_compile_args = [
        "-O3",
        "-Wall",
        "-Wextra",
        "-fopenmp",
        "-std=c++17",
        "-DMS_WIN64",
    ]
    ext.extra_link_args = [
        "-fopenmp",
        "-static-libgcc",
        "-static-libstdc++",
    ]


class BuildExt(build_ext):
    def build_extensions(self):
        self.compiler.set_executable('compiler_so', 'g++')
        self.compiler.set_executable('compiler_cxx', 'g++')
        self.compiler.set_executable('linker_so', 'g++')
        super().build_extensions()


setup(
    name="lut_preview_cpp",
    version="1.0.0",
    author="FreeAssetFilter",
    description="C++ 实现的高性能 LUT 预览生成器",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildExt},
    zip_safe=False,
    python_requires=">=3.8",
)
