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

from freeassetfilter.utils.app_logger import info
from freeassetfilter.utils.subprocess_utils import run_with_limited_output

def detect_compiler():
    """检测可用的 C++ 编译器"""
    try:
        result = run_with_limited_output(
            ["g++", "--version"],
            text=True,
            timeout=5,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=64 * 1024,
        )
        if result.returncode == 0:
            return "mingw"
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        pass
    
    try:
        result = run_with_limited_output(
            ["cl"],
            text=True,
            timeout=5,
            max_stdout_bytes=64 * 1024,
            max_stderr_bytes=64 * 1024,
        )
        if result.returncode == 0:
            return "msvc"
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        pass
    
    return None

COMPILER = detect_compiler()
info(f"[Setup] 检测到编译器: {COMPILER}")

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

# ── 后续改进（审查 3.1#20，本轮不涉及；均需重新编译 .pyd 后验证）────────────
# * -march=native：产物绑定构建机指令集，老 CPU 上执行存在非法指令风险，
#   建议移除（退回通用 x86-64 基线）；
# * -ffast-math：改变浮点结果，建议先用 C++ vs numpy 输出对比基准决定去留；
# * MSVC /MT 与 CPython 扩展 /MD 惯例不符（跨模块堆分配风险），建议改 /MD
#   并随包解决 msvcp140.dll 分发。
if platform.system() == "Windows":
    if COMPILER == "mingw":
        info("[Setup] 使用 MinGW 编译器")
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
        info("[Setup] 使用 MSVC 编译器")
        for ext in ext_modules:
            ext.extra_compile_args = [
                "/O2",
                "/W3",
                "/EHsc",
                "/openmp",
                "/std:c++17",
                "/utf-8",
                "/MT",
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
