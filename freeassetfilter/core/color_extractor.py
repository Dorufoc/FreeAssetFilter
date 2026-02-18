#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
颜色提取工具模块

从音乐封面图像中提取主色调，用于流体渐变背景渲染

本模块优先使用 C++ 实现以获得更高性能，如果 C++ 模块不可用则自动降级到纯 Python 实现。
"""

import io
import math
import os
import time
import struct
from collections import Counter
from typing import List, Optional, Tuple

from PySide6.QtGui import QColor
from PIL import Image

# 尝试导入 C++ 扩展模块
_CPP_AVAILABLE = False
_CPP_MODULE = None

try:
    from .cpp_color_extractor import color_extractor_cpp
    _CPP_AVAILABLE = True
    _CPP_MODULE = color_extractor_cpp
    print("[ColorExtractor] C++ 扩展模块加载成功，将使用高性能实现")
except ImportError as e:
    print(f"[ColorExtractor] C++ 扩展模块加载失败: {e}")
    print("[ColorExtractor] 将使用纯 Python 实现（性能较低）")

# 用于处理音频文件元数据
try:
    from mutagen import File as mutagen_file
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.mp4 import MP4
except ImportError:
    mutagen_file = None
    MP3 = None
    FLAC = None
    OggVorbis = None
    MP4 = None


def _prepare_image_data_for_cpp(cover_data: bytes) -> bytes:
    """
    将图像数据转换为 C++ 模块可用的格式
    
    格式：前4字节宽度 + 4字节高度 + RGB像素数据
    """
    try:
        image = Image.open(io.BytesIO(cover_data))
        
        # 转换为 RGBA 模式
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        width, height = image.size
        pixels = image.tobytes()
        
        # 打包数据：宽度(4字节) + 高度(4字节) + 像素数据
        header = struct.pack('ii', width, height)
        return header + pixels
    except Exception as e:
        raise ValueError(f"图像解码失败: {e}")


def extract_cover_colors(cover_data: bytes, num_colors: int = 5, 
                         min_distance: float = 50.0) -> List[QColor]:
    """
    从封面图像数据中提取主色调
    
    优先使用 C++ 实现以获得更高性能，如果失败则降级到 Python 实现。
    
    Args:
        cover_data: 封面图像的二进制数据
        num_colors: 要提取的颜色数量
        min_distance: 颜色之间的最小距离（用于去重）
    Returns:
        提取的主色调列表（QColor对象）
    """
    if not cover_data:
        print("[ColorExtractor] 封面数据为空")
        return []
    
    # 优先使用 C++ 实现
    if _CPP_AVAILABLE:
        try:
            start_time = time.time()
            
            # 准备图像数据
            cpp_data = _prepare_image_data_for_cpp(cover_data)
            
            # 调用 C++ 函数（CIEDE2000 距离默认 20.0）
            cpp_min_distance = min_distance / 2.5  # 转换欧氏距离到近似 CIEDE2000 距离
            colors_rgb = _CPP_MODULE.extract_colors(
                cpp_data, 
                num_colors=num_colors, 
                min_distance=cpp_min_distance,
                max_image_size=150
            )
            
            elapsed = (time.time() - start_time) * 1000
            
            # 转换为 QColor 列表
            result = [QColor(r, g, b) for r, g, b in colors_rgb]
            
            print(f"[ColorExtractor] C++ 提取到 {len(result)} 个颜色，耗时 {elapsed:.2f}ms")
            for i, c in enumerate(result):
                print(f"  颜色{i+1}: RGB({c.red()}, {c.green()}, {c.blue()})")
            
            return result
            
        except Exception as e:
            print(f"[ColorExtractor] C++ 提取失败: {e}，降级到 Python 实现")
    
    # 降级到 Python 实现
    return _extract_cover_colors_python(cover_data, num_colors, min_distance)


def _extract_cover_colors_python(cover_data: bytes, num_colors: int = 5, 
                                 min_distance: float = 50.0) -> List[QColor]:
    """
    Python 实现的颜色提取（作为 fallback）
    """
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
        print(f"[ColorExtractor] Python 提取到 {len(result)} 个颜色")
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


def extract_cover_from_audio(file_path: str) -> Optional[bytes]:
    """
    从音频文件中提取封面图像数据
    
    支持的格式：MP3(ID3)、FLAC、OGG、M4A/AAC
    
    Args:
        file_path: 音频文件路径
    
    Returns:
        封面图像的二进制数据，如果没有封面则返回None
    """
    if not mutagen_file:
        print("[ColorExtractor] mutagen库未安装，无法提取封面")
        return None
    
    try:
        audio = mutagen_file(file_path)
        if not audio:
            return None
        
        # MP3文件 (ID3标签)
        if isinstance(audio, MP3):
            if audio.tags:
                for tag in audio.tags.values():
                    if tag.FrameID == 'APIC':  # 附件图片帧
                        return tag.data
        
        # FLAC文件
        elif isinstance(audio, FLAC):
            if audio.pictures:
                return audio.pictures[0].data
        
        # OGG文件
        elif isinstance(audio, OggVorbis):
            if 'metadata_block_picture' in audio:
                import base64
                picture_data = base64.b64decode(audio['metadata_block_picture'][0])
                # 跳过Ogg FLAC picture block header (4 bytes type + 4 bytes mime length + ...)
                # 简化处理：尝试直接作为图片数据
                try:
                    Image.open(io.BytesIO(picture_data))
                    return picture_data
                except:
                    pass
        
        # MP4/M4A文件
        elif isinstance(audio, MP4):
            # MP4封面通常在 'covr' 原子中
            if 'covr' in audio:
                cover_data = audio['covr'][0]
                if isinstance(cover_data, bytes):
                    return cover_data
        
        # 通用方式：尝试查找附件图片
        if hasattr(audio, 'tags') and audio.tags:
            # 常见的封面标签名
            cover_tags = ['APIC:', 'APIC', 'COVER', 'cover', 'Cover',
                         'METADATA_BLOCK_PICTURE', 'metadata_block_picture']
            for tag_name in cover_tags:
                if tag_name in audio.tags:
                    data = audio.tags[tag_name]
                    if isinstance(data, list) and data:
                        data = data[0]
                    if hasattr(data, 'data'):
                        return data.data
                    elif isinstance(data, bytes):
                        return data
        
        return None
        
    except Exception as e:
        print(f"[ColorExtractor] 提取封面失败: {e}")
        return None


def generate_colors_from_accent(accent_hex: str = "#B036EE") -> List[QColor]:
    """
    基于强调色生成5种协调的主题色
    
    使用HSL色彩空间进行色相偏移，生成协调的颜色组合
    
    Args:
        accent_hex: 强调色的十六进制字符串，默认为紫色
    
    Returns:
        5种QColor对象的列表
    """
    try:
        accent_color = QColor(accent_hex)
        if not accent_color.isValid():
            accent_color = QColor("#B036EE")
    except:
        accent_color = QColor("#B036EE")
    
    h, s, v, a = accent_color.getHsv()
    
    colors = []
    
    # 生成5种颜色：基准色 + 4种变体
    # 使用色相偏移和饱和度/明度调整来创建协调的配色
    variations = [
        (0, 1.0, 1.0),           # 基准色
        (30, 0.9, 1.05),         # 色相+30，饱和度90%，明度105%
        (-30, 0.95, 0.95),       # 色相-30，饱和度95%，明度95%
        (60, 0.85, 1.1),         # 色相+60，饱和度85%，明度110%
        (-60, 0.8, 0.9),         # 色相-60，饱和度80%，明度90%
    ]
    
    for hue_offset, sat_factor, val_factor in variations:
        new_h = (h + hue_offset) % 360
        new_s = max(0, min(255, int(s * sat_factor)))
        new_v = max(0, min(255, int(v * val_factor)))
        
        color = QColor.fromHsv(new_h, new_s, new_v, a)
        colors.append(color)
    
    return colors


def get_theme_colors_for_audio(file_path: str, accent_hex: str = "#B036EE") -> List[QColor]:
    """
    为音频文件获取主题色
    
    优先从封面提取颜色，如果没有封面则基于强调色生成
    
    Args:
        file_path: 音频文件路径
        accent_hex: 强调色（当无封面时使用）
    
    Returns:
        5种QColor对象的列表
    """
    # 验证文件路径
    if not file_path or not os.path.exists(file_path):
        print(f"[ColorExtractor] 音频文件不存在: {file_path}")
        return generate_colors_from_accent(accent_hex)
    
    # 检查文件大小（避免处理过大的文件）
    try:
        file_size = os.path.getsize(file_path)
        if file_size > 100 * 1024 * 1024:  # 100MB
            print(f"[ColorExtractor] 音频文件过大，跳过封面提取: {file_size / 1024 / 1024:.1f}MB")
            return generate_colors_from_accent(accent_hex)
    except Exception as e:
        print(f"[ColorExtractor] 检查文件大小失败: {e}")
    
    try:
        # 尝试从音频文件提取封面
        cover_data = extract_cover_from_audio(file_path)
        
        if cover_data:
            # 检查封面数据大小
            if len(cover_data) > 10 * 1024 * 1024:  # 10MB
                print(f"[ColorExtractor] 封面图像过大，跳过: {len(cover_data) / 1024 / 1024:.1f}MB")
                return generate_colors_from_accent(accent_hex)
            
            # 从封面提取颜色（增大min_distance确保颜色区分度）
            colors = extract_cover_colors(cover_data, num_colors=5, min_distance=70.0)
            
            # 验证提取的颜色数量和质量
            if colors and len(colors) >= 5:
                # 检查颜色之间的平均距离，确保区分度
                total_distance = 0
                count = 0
                for i in range(len(colors)):
                    for j in range(i + 1, len(colors)):
                        total_distance += color_distance(colors[i], colors[j])
                        count += 1
                
                avg_distance = total_distance / count if count > 0 else 0
                
                if avg_distance >= 40.0:  # 平均距离阈值
                    print(f"[ColorExtractor] 从封面提取到 {len(colors)} 种颜色，平均距离: {avg_distance:.1f}")
                    return colors
                else:
                    print(f"[ColorExtractor] 封面颜色区分度不足({avg_distance:.1f})，使用强调色")
            else:
                print(f"[ColorExtractor] 封面提取颜色数量不足: {len(colors) if colors else 0}")
        else:
            print(f"[ColorExtractor] 音频文件无封面: {os.path.basename(file_path)}")
    
    except Exception as e:
        print(f"[ColorExtractor] 提取主题色时发生异常: {e}")
    
    # 降级：基于强调色生成
    print(f"[ColorExtractor] 使用强调色生成主题色: {accent_hex}")
    return generate_colors_from_accent(accent_hex)


def is_cpp_available() -> bool:
    """检查 C++ 扩展模块是否可用"""
    return _CPP_AVAILABLE


def get_extractor_version() -> str:
    """获取当前使用的提取器版本信息"""
    if _CPP_AVAILABLE:
        return f"C++ ({_CPP_MODULE.__version__})"
    return "Python (fallback)"
