#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

路径处理工具模块
提供资源文件路径、应用数据路径和配置文件路径的处理函数
"""

import sys
import os
from pathlib import Path

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发和打包环境"""
    try:
        # PyInstaller创建临时文件夹，存储于_MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # 开发环境：使用项目根目录
        base_path = os.path.abspath(".")
        # 向上找到项目根目录
        if not os.path.exists(os.path.join(base_path, relative_path)):
            # 如果当前目录没有，尝试向上查找
            base_path = os.path.dirname(os.path.abspath(__file__))
            for _ in range(3):  # 最多向上找3级
                if os.path.exists(os.path.join(base_path, relative_path)):
                    break
                base_path = os.path.dirname(base_path)
    
    return os.path.join(base_path, relative_path)


def get_app_data_path():
    """获取应用程序数据目录（用于存储配置、数据等）"""
    if getattr(sys, 'frozen', False):
        # 打包环境：使用exe所在目录下的data文件夹
        app_dir = os.path.dirname(sys.executable)
        data_dir = os.path.join(app_dir, 'data')
    else:
        # 开发环境：使用项目根目录下的data文件夹
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
    
    # 确保目录存在
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, 'thumbnails'), exist_ok=True)
    
    return data_dir


def get_config_path():
    """获取配置文件目录"""
    if getattr(sys, 'frozen', False):
        # 打包环境：使用exe所在目录下的config文件夹
        app_dir = os.path.dirname(sys.executable)
        config_dir = os.path.join(app_dir, 'config')
    else:
        # 开发环境：使用项目根目录下的config文件夹
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
    
    # 确保目录存在
    os.makedirs(config_dir, exist_ok=True)
    
    return config_dir
