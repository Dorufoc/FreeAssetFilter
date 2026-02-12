#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter 安装脚本
"""

from setuptools import setup, find_packages
import os

def read_file(filename):
    """读取文件内容"""
    with open(os.path.join(os.path.dirname(__file__), filename), 'r', encoding='utf-8') as f:
        return f.read()

setup(
    name="freeassetfilter",
    version="1.0.0",
    author="Dorufoc | renmoren",
    author_email="qpdrfc123@gmail.com | renmoren@foxmail.com",
    description="FreeAssetFilter - 免费资产筛选器",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/Dorufoc/FreeAssetFilter",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "freeassetfilter": [
            "icons/*",
            "libs/PPTX2HTML/*",
        ],
    },
    install_requires=read_file("requirements.txt").splitlines(),
    entry_points={
        "console_scripts": [
            "freeassetfilter = freeassetfilter.app.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia",
        "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
    ],
    python_requires=">=3.7",
)
