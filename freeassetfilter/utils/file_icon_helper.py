#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件图标路径解析模块

产品只保留一套图标：多彩样式（v3，文件名为 ``X – 3.svg``）。
历史上存在 0=扁平（X.svg）/ 1=质感（X – 1）/ 2=统一（X – 2）/
3=多彩（X – 3）四套可切换样式，现已全部移除该能力与对应图标
（``appearance.icon_style`` 设置项不再存在，也不再读取）。
"""

import os


def _get_type_icon_path(icon_name: str, icon_dir: str) -> str:
    """返回类型图标路径：固定使用多彩 v3（``X – 3.svg``）。

    仅当 v3 图标缺失时回退到无后缀版本（防御性兜底，正常资源中不应触发）。

    Args:
        icon_name (str): 图标名称（如 "视频", "图像", "文件夹" 等）
        icon_dir (str): 图标目录路径

    Returns:
        str: SVG 文件的完整路径
    """
    styled_path = os.path.join(icon_dir, f"{icon_name} – 3.svg")
    if os.path.exists(styled_path):
        return styled_path
    fallback_path = os.path.join(icon_dir, f"{icon_name}.svg")
    if os.path.exists(fallback_path):
        return fallback_path
    return styled_path


def get_file_icon_path(file_info, icon_dir=None):
    """
    根据文件信息获取对应的 SVG 图标路径

    Args:
        file_info (dict): 文件信息字典，包含 is_dir, suffix 等字段
        icon_dir (str, optional): 图标目录路径，如果为None则自动计算

    Returns:
        str: SVG文件的完整路径
    """
    if icon_dir is None:
        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")

    if file_info.get("is_dir", False):
        return _get_type_icon_path("文件夹", icon_dir)

    suffix = file_info.get("suffix", "").lower()

    # 定义文件类型映射
    video_formats = ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf", "3gp", "vob", "m2ts", "ts", "mts"]
    image_formats = ["jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg", "avif", "cr2", "cr3", "nef", "arw", "dng", "orf"]
    audio_formats = ["mp3", "wav", "flac", "ogg", "wma", "aac", "m4a", "opus"]
    font_formats = ["ttf", "otf", "woff", "woff2", "eot"]
    archive_formats = ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "lzma", "iso", "cab", "arj"]

    if suffix in video_formats:
        return _get_type_icon_path("视频", icon_dir)
    elif suffix in image_formats:
        return _get_type_icon_path("图像", icon_dir)
    elif suffix == "pdf":
        return _get_type_icon_path("PDF", icon_dir)
    elif suffix in ["ppt", "pptx"]:
        return _get_type_icon_path("PPT", icon_dir)
    elif suffix in ["xls", "xlsx"]:
        return _get_type_icon_path("表格", icon_dir)
    elif suffix in ["doc", "docx"]:
        return _get_type_icon_path("Word文档", icon_dir)
    elif suffix in ["txt", "md", "rst", "rtf"]:
        return _get_type_icon_path("文档", icon_dir)
    elif suffix in font_formats:
        return _get_type_icon_path("字体", icon_dir)
    elif suffix in audio_formats:
        return _get_type_icon_path("音乐", icon_dir)
    elif suffix in archive_formats:
        return _get_type_icon_path("压缩文件", icon_dir)
    else:
        return _get_type_icon_path("未知底板", icon_dir)


__all__ = [
    "get_file_icon_path",
    "_get_type_icon_path",
]
