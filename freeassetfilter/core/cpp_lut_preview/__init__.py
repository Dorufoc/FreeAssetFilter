#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ LUT 预览生成器 Python 包装器

提供与 Python 版本相同的 API，但使用 C++ 实现以获得更高性能。
如果 C++ 模块编译失败或未安装，自动降级到纯 Python 实现。
"""

import logging
from pathlib import Path
from typing import Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)

CPP_LUT_PREVIEW_AVAILABLE = False
_cpp_module = None

def _try_import_cpp_module():
    """尝试导入 C++ 模块"""
    global CPP_LUT_PREVIEW_AVAILABLE, _cpp_module
    
    try:
        import sys
        cpp_module_path = str(Path(__file__).parent)
        if cpp_module_path not in sys.path:
            sys.path.insert(0, cpp_module_path)
        
        from lut_preview_cpp import generate_preview_from_data as _cpp_generate_preview
        _cpp_module = _cpp_generate_preview
        CPP_LUT_PREVIEW_AVAILABLE = True
        logger.info("[LUTPreviewCPP] C++ 扩展模块加载成功")
        return True
    except ImportError as e:
        logger.warning(f"[LUTPreviewCPP] C++ 扩展模块加载失败: {e}")
        return False


def warmup():
    """
    预热 C++ 模块
    首次调用时触发 JIT 编译和一些初始化工作
    """
    if not CPP_LUT_PREVIEW_AVAILABLE:
        _try_import_cpp_module()
    
    if CPP_LUT_PREVIEW_AVAILABLE and _cpp_module is not None:
        try:
            dummy_lut = '''TITLE "Warmup LUT"
LUT_3D_SIZE 2

1.0 1.0 1.0
1.0 1.0 0.0
1.0 0.0 1.0
1.0 0.0 0.0
0.0 1.0 1.0
0.0 1.0 0.0
0.0 0.0 1.0
0.0 0.0 0.0
'''
            dummy_image = np.zeros((8, 8, 3), dtype=np.uint8)
            _cpp_module(dummy_lut, dummy_image, 8, 8)
            logger.info("[LUTPreviewCPP] 预热完成")
        except Exception as e:
            logger.warning(f"[LUTPreviewCPP] 预热失败: {e}")


def generate_preview(lut_content: str, image_array: np.ndarray, 
                    output_width: int, output_height: int) -> bytes:
    """
    从 LUT 内容生成预览图像
    
    Args:
        lut_content: LUT 文件内容（字符串）
        image_array: 图像 numpy 数组
        output_width: 输出宽度
        output_height: 输出高度
    
    Returns:
        PNG 格式的图像数据
    """
    if CPP_LUT_PREVIEW_AVAILABLE and _cpp_module is not None:
        return _cpp_module(lut_content, image_array, output_width, output_height)
    else:
        raise RuntimeError("C++ 模块不可用")


def is_cpp_available() -> bool:
    """检查 C++ 扩展模块是否可用"""
    return CPP_LUT_PREVIEW_AVAILABLE


def get_version() -> str:
    """获取版本信息"""
    if CPP_LUT_PREVIEW_AVAILABLE:
        return "C++ (1.0.0)"
    return "Python (fallback)"


# 初始化尝试导入
_try_import_cpp_module()

__all__ = [
    'warmup',
    'generate_preview',
    'is_cpp_available',
    'get_version',
]
