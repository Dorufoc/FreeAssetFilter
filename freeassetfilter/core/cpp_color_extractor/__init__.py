#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ 封面颜色提取器 Python 包装器

提供与 Python 版本相同的 API，但使用 C++ 实现以获得更高性能。
如果 C++ 模块编译失败或未安装，自动降级到纯 Python 实现。
"""

import time
import logging
from typing import List, Tuple, Optional

# 配置日志
logger = logging.getLogger(__name__)

# 尝试导入 C++ 模块
_CPP_AVAILABLE = False
_cpp_module = None

try:
    from . import color_extractor_cpp
    _CPP_AVAILABLE = True
    _cpp_module = color_extractor_cpp
    logger.info("[ColorExtractorCPP] C++ 扩展模块加载成功")
except ImportError as e:
    logger.warning(f"[ColorExtractorCPP] C++ 扩展模块加载失败: {e}")
    logger.warning("[ColorExtractorCPP] 将使用纯 Python 实现（性能较低）")

# 如果 C++ 模块不可用，导入 Python 实现作为 fallback
if not _CPP_AVAILABLE:
    try:
        from ..color_extractor import extract_cover_colors as _py_extract_cover_colors
        _PY_FALLBACK = True
    except ImportError:
        _PY_FALLBACK = False
        logger.error("[ColorExtractorCPP] Python fallback 也无法导入")


def is_cpp_available() -> bool:
    """检查 C++ 扩展模块是否可用"""
    return _CPP_AVAILABLE


def extract_colors(cover_data: bytes, num_colors: int = 5, 
                   min_distance: float = 20.0, max_image_size: int = 150,
                   use_cpp: bool = True) -> List[Tuple[int, int, int]]:
    """
    从封面图像数据中提取主色调
    
    Args:
        cover_data: 封面图像的二进制数据
        num_colors: 要提取的颜色数量（默认 5）
        min_distance: 颜色之间的最小 CIEDE2000 距离（默认 20.0）
        max_image_size: 内部处理时的最大图像尺寸（默认 150）
        use_cpp: 是否尝试使用 C++ 实现（默认 True）
    
    Returns:
        提取的颜色列表，每个颜色为 (r, g, b) 元组
    
    Raises:
        ValueError: 图像数据无效
        RuntimeError: 颜色提取失败
    """
    # 优先使用 C++ 实现
    if use_cpp and _CPP_AVAILABLE:
        try:
            start_time = time.time()
            colors = _cpp_module.extract_colors(cover_data, num_colors, min_distance, max_image_size)
            elapsed = (time.time() - start_time) * 1000
            logger.debug(f"[ColorExtractorCPP] C++ 提取完成，耗时 {elapsed:.2f}ms")
            return colors
        except Exception as e:
            logger.warning(f"[ColorExtractorCPP] C++ 提取失败: {e}，尝试 Python fallback")
    
    # 降级到 Python 实现
    if _PY_FALLBACK:
        from PySide6.QtGui import QColor
        py_colors = _py_extract_cover_colors(cover_data, num_colors, min_distance)
        # 转换为 (r, g, b) 元组列表
        return [(c.red(), c.green(), c.blue()) for c in py_colors]
    
    raise RuntimeError("没有可用的颜色提取实现")


def get_version() -> str:
    """获取版本信息"""
    if _CPP_AVAILABLE:
        return f"C++ ({_cpp_module.__version__})"
    return "Python (fallback)"


# 导出公共 API
__all__ = [
    'extract_colors',
    'is_cpp_available',
    'get_version',
]
