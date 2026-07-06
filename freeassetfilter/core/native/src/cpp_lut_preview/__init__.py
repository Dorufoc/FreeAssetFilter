#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C++ LUT 预览生成器 Python 包装器

提供与 Python 版本相同的 API，但使用 C++ 实现以获得更高性能。
如果 C++ 模块编译失败或未安装，自动降级到纯 Python 实现。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Tuple
from freeassetfilter.utils.app_logger import info, warning

CPP_LUT_PREVIEW_AVAILABLE = False
_cpp_module = None
_CACHE_LOCK = threading.Lock()

def _try_import_cpp_module():
    """尝试导入 C++ 模块（线程安全）"""
    global CPP_LUT_PREVIEW_AVAILABLE, _cpp_module
    
    with _CACHE_LOCK:
        if _cpp_module is not None:
            return CPP_LUT_PREVIEW_AVAILABLE
    
    try:
        # 尝试相对导入（打包后的标准方式）
        from . import lut_preview_cpp
        with _CACHE_LOCK:
            _cpp_module = lut_preview_cpp.generate_preview_from_data
            CPP_LUT_PREVIEW_AVAILABLE = True
        info("[LUTPreviewCPP] C++ 扩展模块加载成功（相对导入）")
        return True
    except ImportError as e1:
        # 回退到绝对导入（开发环境）
        try:
            import sys
            cpp_module_path = str(Path(__file__).parent)
            if cpp_module_path not in sys.path:
                sys.path.insert(0, cpp_module_path)
            
            from lut_preview_cpp import generate_preview_from_data as _cpp_generate_preview
            with _CACHE_LOCK:
                _cpp_module = _cpp_generate_preview
                CPP_LUT_PREVIEW_AVAILABLE = True
            info("[LUTPreviewCPP] C++ 扩展模块加载成功（绝对导入）")
            return True
        except ImportError as e2:
            warning(f"[LUTPreviewCPP] C++ 扩展模块加载失败: {e1}, {e2}")
            return False


def warmup():
    """
    预热 C++ 模块（线程安全）
    首次调用时触发 JIT 编译和一些初始化工作
    """
    import numpy as np
    with _CACHE_LOCK:
        available = CPP_LUT_PREVIEW_AVAILABLE
        cpp_module = _cpp_module
    if not available:
        _try_import_cpp_module()
        with _CACHE_LOCK:
            available = CPP_LUT_PREVIEW_AVAILABLE
            cpp_module = _cpp_module
    
    if available and cpp_module is not None:
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
            cpp_module(dummy_lut, dummy_image, 8, 8)
            info("[LUTPreviewCPP] 预热完成")
        except Exception as e:
            warning(f"[LUTPreviewCPP] 预热失败: {e}")


def generate_preview(lut_content: str, image_array: np.ndarray, 
                    output_width: int, output_height: int) -> bytes:
    """
    从 LUT 内容生成预览图像（线程安全）
    
    Args:
        lut_content: LUT 文件内容（字符串）
        image_array: 图像 numpy 数组
        output_width: 输出宽度
        output_height: 输出高度
    
    Returns:
        PNG 格式的图像数据
    """
    with _CACHE_LOCK:
        if not CPP_LUT_PREVIEW_AVAILABLE or _cpp_module is None:
            raise RuntimeError("C++ 模块不可用")
        cpp_module = _cpp_module
    return cpp_module(lut_content, image_array, output_width, output_height)


def is_cpp_available() -> bool:
    """检查 C++ 扩展模块是否可用（线程安全）"""
    with _CACHE_LOCK:
        return CPP_LUT_PREVIEW_AVAILABLE


def get_version() -> str:
    """获取版本信息（线程安全）"""
    with _CACHE_LOCK:
        if CPP_LUT_PREVIEW_AVAILABLE:
            return "C++ (1.0.0)"
        return "Python (fallback)"


__all__ = [
    'warmup',
    'generate_preview',
    'is_cpp_available',
    'get_version',
]