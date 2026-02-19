#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ LUT 预览生成器扩展模块编译配置

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
from setuptools import setup

def detect_compiler():
    """检测可用的 C++ 编译器"""
    try:
        result = subprocess.run(["g++", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            return "mingw"
    except FileNotFoundError:
        pass
    
    try:
        result = subprocess.run(["cl"], capture_output=True, text=True)
        if result.returncode == 0:
            return "msvc"
    except FileNotFoundError:
        pass
    
    return None

COMPILER = detect_compiler()
print(f"[Setup] 检测到编译器: {COMPILER}")

HERE = os.path.dirname(os.path.abspath(__file__))

ext_modules = [
    Pybind11Extension(
        "lut_preview_cpp",
        sources=["lut_preview.cpp"],
        include_dirs=[],
        define_macros=[("VERSION_INFO", '"1.0.0"')],
        cxx_std=17,
    ),
]

if platform.system() == "Windows":
    if COMPILER == "mingw":
        print("[Setup] 使用 MinGW 编译器")
        for ext in ext_modules:
            ext.extra_compile_args = [
                "-O3",
                "-Wall",
                "-Wextra",
                "-fopenmp",
                "-std=c++17",
                "-ffast-math",
                "-march=native",
                "-DMS_WIN64",
            ]
            ext.extra_link_args = ["-fopenmp", "-static-libgcc", "-static-libstdc++"]
    else:
        print("[Setup] 使用 MSVC 编译器")
        for ext in ext_modules:
            ext.extra_compile_args = [
                "/O2",
                "/W3",
                "/EHsc",
                "/openmp",
                "/std:c++17",
            ]
            ext.extra_link_args = ["/openmp"]
        
elif platform.system() == "Darwin":
    for ext in ext_modules:
        ext.extra_compile_args = [
            "-O3",
            "-Wall",
            "-Wextra",
            "-std=c++17",
        ]
        
else:
    for ext in ext_modules:
        ext.extra_compile_args = [
            "-O3",
            "-Wall",
            "-Wextra",
            "-fopenmp",
            "-std=c++17",
            "-ffast-math",
            "-march=native",
        ]
        ext.extra_link_args = ["-fopenmp"]


setup(
    name="lut_preview_cpp",
    version="1.0.0",
    author="FreeAssetFilter",
    description="C++ 实现的高性能 LUT 预览生成器",
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.8",
    install_requires=[
        "pybind11>=2.10.0",
    ],
)
