#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
颜色提取工具模块

从音乐封面图像中提取主色调，用于流体渐变背景渲染
"""

import io
import math
from collections import Counter
from typing import List, Optional

from PyQt5.QtGui import QColor
from PIL import Image


def extract_cover_colors(cover_data: bytes, num_colors: int = 5, 
                         min_distance: float = 50.0) -> List[QColor]:
    """
    从封面图像数据中提取主色调
    
    Args:
        cover_data: 封面图像的二进制数据
        num_colors: 要提取的颜色数量
        min_distance: 颜色之间的最小欧氏距离（用于去重）
    Returns:
        提取的主色调列表（QColor对象）
    """
    if not cover_data:
        print("[ColorExtractor] 封面数据为空")
        return []
    
    try:
        image = Image.open(io.BytesIO(cover_data))
    except Exception as e:
        print(f"[ColorExtractor] 打开封面图像失败: {e}")
        return []
    
    try:
        image = image.convert('RGB')
        image = image.resize((100, 100), Image.Resampling.LANCZOS)
        
        pixels = list(image.getdata())
        
        pixel_counts = Counter(pixels)
        most_common = pixel_counts.most_common(500)
        
        colors = []
        for color_tuple, _ in most_common:
            color = QColor(*color_tuple)
            if _is_valid_color(color):
                if _is_color_different(color, colors, min_distance):
                    colors.append(color)
                    if len(colors) >= num_colors:
                        break
        
        if len(colors) < num_colors:
            for color_tuple, _ in most_common:
                if len(colors) >= num_colors:
                    break
                color = QColor(*color_tuple)
                if _is_valid_color(color) and color not in colors:
                    colors.append(color)
        
        while len(colors) < num_colors:
            colors.append(QColor(128, 128, 128))
        
        result = colors[:num_colors]
        print(f"[ColorExtractor] 提取到 {len(result)} 个颜色")
        for i, c in enumerate(result):
            print(f"  颜色{i+1}: RGB({c.red()}, {c.green()}, {c.blue()})")
        
        return result
        
    except Exception as e:
        print(f"[ColorExtractor] 处理封面图像失败: {e}")
        return []


def extract_cover_colors_from_path(image_path: str, num_colors: int = 5,
                                   min_distance: float = 50.0) -> List[QColor]:
    """
    从封面图像文件路径中提取主色调
    
    Args:
        image_path: 封面图像文件路径
        num_colors: 要提取的颜色数量
        min_distance: 颜色之间的最小欧氏距离
    
    Returns:
        提取的主色调列表（QColor对象）
    """
    try:
        with open(image_path, 'rb') as f:
            cover_data = f.read()
        return extract_cover_colors(cover_data, num_colors, min_distance)
    except Exception as e:
        print(f"[ColorExtractor] 从文件读取封面失败: {e}")
        return []


def _is_valid_color(color: QColor) -> bool:
    """检查颜色是否有效（非全黑或全白）"""
    r, g, b = color.red(), color.green(), color.blue()
    total = r + g + b
    return 50 < total < 700 and not (r > 250 and g > 250 and b > 250)


def _is_color_different(color: QColor, existing_colors: List[QColor], 
                        min_distance: float) -> bool:
    """检查颜色是否与已有颜色差异足够大"""
    for existing in existing_colors:
        if color_distance(color, existing) < min_distance:
            return False
    return True


def color_distance(color1: QColor, color2: QColor) -> float:
    """计算两个颜色之间的欧氏距离"""
    r1, g1, b1 = color1.red(), color1.green(), color1.blue()
    r2, g2, b2 = color2.red(), color2.green(), color2.blue()
    
    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2
    
    return math.sqrt(dr * dr + dg * dg + db * db)


def rgb_to_hex(color: QColor) -> str:
    """将QColor转换为十六进制颜色字符串"""
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


def hex_to_qcolor(hex_str: str) -> Optional[QColor]:
    """将十六进制颜色字符串转换为QColor"""
    if not hex_str.startswith('#') or len(hex_str) != 7:
        return None
    
    try:
        r = int(hex_str[1:3], 16)
        g = int(hex_str[3:5], 16)
        b = int(hex_str[5:7], 16)
        return QColor(r, g, b)
    except ValueError:
        return None


def sort_colors_by_brightness(colors: List[QColor], 
                               ascending: bool = False) -> List[QColor]:
    """按亮度排序颜色"""
    return sorted(colors, key=lambda c: c.red() * 0.299 + c.green() * 0.587 + c.blue() * 0.114,
                  reverse=not ascending)


def adjust_colors_for_gradient(colors: List[QColor]) -> List[QColor]:
    """
    调整颜色以确保渐变效果协调
    
    Args:
        colors: 原始颜色列表
    
    Returns:
        调整后的颜色列表
    """
    if len(colors) < 5:
        return colors
    
    sorted_colors = sort_colors_by_brightness(colors, ascending=True)
    
    result = []
    indices = [0, 1, 2, 3, 4]
    
    step = (len(sorted_colors) - 1) / 4
    for i in range(5):
        idx = min(int(i * step), len(sorted_colors) - 1)
        result.append(sorted_colors[idx])
    
    return result
