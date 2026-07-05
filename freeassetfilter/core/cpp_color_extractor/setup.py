#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ 颜色提取器扩展模块编译配置
"""
# ╔══════════════════════════════════════════════════════════════════╗
# ║  注意: 本模块已被 Rust 颜色提取实现取代 (native/rust_color_   ║
# ║  extractor)。预编译的 .pyd 保留在此目录中以备兼容性参考。     ║
# ║  当前的 color_extractor.py 默认使用 Rust DLL，仅在 Rust 模块  ║
# ║  不可用时降级到纯 Python 实现，不再加载此 C++ .pyd。           ║
# ╚══════════════════════════════════════════════════════════════════╝
#
# 预编译 .pyd 目标:
#   Python: 3.9 (cp39)
#   架构:   x64 (AMD64)
#   文件:   color_extractor_cpp.cp39-win_amd64.pyd
#
# 当前运行环境: see runtime output of "python --version" and platform.machine()
#
# 使用方法:
#   python setup.py build_ext --inplace
#   或
#   pip install -e .

import os
import sys
import platform
import subprocess
from typing import Optional
from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup

__all__ = []

# ─── 构建目标说明 ───────────────────────────────────────────────
#
# 当前预编译的 .pyd 目标:
#   color_extractor_cpp.cp39-win_amd64.pyd  →  Python 3.9, Windows x64
#
# 如果需要为不同 Python 版本重建:
#   1. 安装所需版本的 Python
#   2. 安装构建依赖:
#      pip install pybind11 setuptools
#   3. (Windows MinGW) 安装 MinGW-w64 并确保 g++ 在 PATH 中
#   4. 运行:
#      cd freeassetfilter/core/cpp_color_extractor
#      python setup.py build_ext --inplace
#
# 生成的 .pyd 文件名将自动匹配当前 Python 版本，例如:
#   Python 3.11 x64 → color_extractor_cpp.cp311-win_amd64.pyd
#   Python 3.10 x64 → color_extractor_cpp.cp310-win_amd64.pyd
#
# 注意: 构建产物应提交到仓库中，以便其他开发者无需本地编译即可运行。


def detect_compiler() -> Optional[str]:
    """检测可用的 C++ 编译器"""
    try:
        result = subprocess.run(
            ["g++", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return "mingw"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        result = subprocess.run(
            ["cl"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return "msvc"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


COMPILER = detect_compiler()
print(f"[Setup] 检测到编译器: {COMPILER}")
print(f"[Setup] 当前 Python: {sys.version_info.major}.{sys.version_info.minor} "
      f"({platform.machine()})")

HERE = os.path.dirname(os.path.abspath(__file__))

ext_modules = [
    Pybind11Extension(
        "color_extractor_cpp",
        sources=["color_extractor.cpp"],
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
    name="color_extractor_cpp",
    version="1.0.0",
    author="FreeAssetFilter",
    description="C++ 实现的高性能封面颜色提取器",
    long_description=(
        "使用 K-Means 聚类和 CIEDE2000 色差算法的高性能颜色提取。\n\n"
        "预编译 .pyd 目标: cp39-x64 (Python 3.9, Windows x64)。\n"
        "如需为其他 Python 版本重建，请参阅本文件开头的说明。"
    ),
    ext_modules=ext_modules,
    cmdclass={"build_ext": build_ext},
    zip_safe=False,
    python_requires=">=3.8",
    install_requires=[
        "pybind11>=2.10.0",
    ],
)
