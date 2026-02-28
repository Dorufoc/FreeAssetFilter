#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件图标路径处理工具模块
根据设置的图标样式返回对应的SVG图标路径
"""

import os
from freeassetfilter.core.settings_manager import SettingsManager

# 支持样式切换的图标名称列表
STYLEABLE_ICONS = [
    "表格",
    "视频",
    "图像",
    "未知底板",
    "文档",
    "文件夹",
    "压缩文件",
    "音乐",
    "字体",
    "PDF",
    "PPT",
    "Word文档"
]

# 图标样式映射：0=扁平(默认), 1=质感, 2=统一
ICON_STYLE_SUFFIX = {
    0: "",           # 默认样式，不加后缀
    1: " – 1",       # 质感样式，加 " – 1" 后缀
    2: " – 2"        # 统一样式，加 " – 2" 后缀
}


def get_icon_path(icon_name, icon_dir=None):
    """
    根据当前设置的图标样式获取对应的SVG图标路径
    
    Args:
        icon_name (str): 图标名称（如 "视频", "图像", "文件夹" 等）
        icon_dir (str, optional): 图标目录路径，如果为None则自动计算
    
    Returns:
        str: SVG文件的完整路径，如果找不到对应图标则返回默认路径
    """
    # 获取图标目录
    if icon_dir is None:
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
    
    # 获取当前图标样式设置（0=扁平, 1=质感）
    try:
        settings_manager = SettingsManager()
        icon_style = settings_manager.get_setting("appearance.icon_style", 0)
    except Exception:
        icon_style = 0
    
    # 确保样式值有效
    if icon_style not in ICON_STYLE_SUFFIX:
        icon_style = 0
    
    # 检查该图标是否支持样式切换
    if icon_name in STYLEABLE_ICONS:
        # 构建带样式的图标文件名
        suffix = ICON_STYLE_SUFFIX[icon_style]
        styled_icon_name = f"{icon_name}{suffix}.svg"
        styled_icon_path = os.path.join(icon_dir, styled_icon_name)
        
        # 如果带样式的图标存在，返回它
        if os.path.exists(styled_icon_path):
            return styled_icon_path
        
        # 如果带样式的图标不存在，回退到默认图标（样式0）
        default_icon_path = os.path.join(icon_dir, f"{icon_name}.svg")
        if os.path.exists(default_icon_path):
            return default_icon_path
    
    # 对于不支持样式切换的图标，直接返回默认路径
    default_icon_path = os.path.join(icon_dir, f"{icon_name}.svg")
    return default_icon_path


def get_file_icon_path(file_info, icon_dir=None):
    """
    根据文件信息获取对应的图标路径
    
    Args:
        file_info (dict): 文件信息字典，包含 is_dir, suffix 等字段
        icon_dir (str, optional): 图标目录路径，如果为None则自动计算
    
    Returns:
        str: SVG文件的完整路径
    """
    # 获取图标目录
    if icon_dir is None:
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")
    
    # 检查是否是文件夹
    if file_info.get("is_dir", False):
        return get_icon_path("文件夹", icon_dir)
    
    # 获取文件后缀
    suffix = file_info.get("suffix", "").lower()
    
    # 定义文件类型映射
    video_formats = ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf", "3gp", "vob", "m2ts", "ts", "mts"]
    image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "avif", "cr2", "cr3", "nef", "arw", "dng", "orf"]
    audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
    font_formats = ["ttf", "otf", "woff", "woff2", "eot"]
    archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "iso", "cab", "arj"]
    
    # 根据后缀返回对应的图标
    if suffix in video_formats:
        return get_icon_path("视频", icon_dir)
    elif suffix in image_formats:
        return get_icon_path("图像", icon_dir)
    elif suffix == "pdf":
        return get_icon_path("PDF", icon_dir)
    elif suffix in ["ppt", "pptx"]:
        return get_icon_path("PPT", icon_dir)
    elif suffix in ["xls", "xlsx"]:
        return get_icon_path("表格", icon_dir)
    elif suffix in ["doc", "docx"]:
        return get_icon_path("Word文档", icon_dir)
    elif suffix in ["txt", "md", "rst", "rtf"]:
        return get_icon_path("文档", icon_dir)
    elif suffix in font_formats:
        return get_icon_path("字体", icon_dir)
    elif suffix in audio_formats:
        return get_icon_path("音乐", icon_dir)
    elif suffix in archive_formats:
        return get_icon_path("压缩文件", icon_dir)
    else:
        return get_icon_path("未知底板", icon_dir)


# 模块导出
__all__ = [
    "get_icon_path",
    "get_file_icon_path",
    "STYLEABLE_ICONS"
]
