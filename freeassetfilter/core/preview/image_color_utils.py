#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像色彩处理辅助工具

统一处理：
1. RAW 文件解码与颜色后处理；
2. 普通图像的 ICC Profile -> sRGB 转换；
3. PIL 图像的 EXIF 方向校正。
"""

from __future__ import annotations

import functools
from typing import Optional

from freeassetfilter.utils.app_logger import debug, warning

# 惰性加载 PIL ImageOps（模块级）
ImageOps = None
_IMAGE_OPS_AVAILABLE = None

def _ensure_image_ops():
    global _IMAGE_OPS_AVAILABLE, ImageOps
    if _IMAGE_OPS_AVAILABLE is None:
        try:
            from PIL import ImageOps
            _IMAGE_OPS_AVAILABLE = True
        except ImportError:
            _IMAGE_OPS_AVAILABLE = False
    return _IMAGE_OPS_AVAILABLE


def apply_exif_orientation(image: "Image.Image") -> "Image.Image":
    """
    应用 EXIF 方向校正。
    """
    if image is None:
        return image

    if not _ensure_image_ops():
        return image

    try:
        return ImageOps.exif_transpose(image)
    except Exception as e:
        debug(f"EXIF方向校正失败: {e}")
        return image


@functools.lru_cache(maxsize=1)
def _get_srgb_profile():
    """获取缓存的 sRGB ICC Profile，避免反复创建。"""
    from PIL import ImageCms
    return ImageCms.createProfile("sRGB")


def convert_pil_to_srgb(image: "Image.Image") -> "Image.Image":
    """
    若图像带有 ICC Profile，则尽量转换到 sRGB。
    """
    try:
        from PIL import Image, ImageCms
    except ImportError:
        return image

    if image is None:
        return image

    try:
        icc_profile = image.info.get("icc_profile")
        if not icc_profile:
            return image

        src_profile = ImageCms.ImageCmsProfile(icc_profile)
        dst_profile = _get_srgb_profile()
        converted = ImageCms.profileToProfile(image, src_profile, dst_profile, outputMode=image.mode)
        debug("ICC配置转换为sRGB完成")
        return converted
    except Exception as e:
        warning(f"ICC转sRGB失败: {e}")
        return image


def normalize_pil_image(image: "Image.Image") -> "Image.Image":
    """
    对普通 PIL 图像执行方向与色彩空间标准化。
    """
    if image is None:
        return image

    normalized = apply_exif_orientation(image)
    normalized = convert_pil_to_srgb(normalized)
    return normalized


def load_raw_image(
    file_path: str,
    *,
    half_size: bool = False,
    use_camera_wb: bool = True,
    no_auto_bright: bool = True,
    output_bps: int = 8,
):
    """
    使用统一参数解码 RAW 图像，输出 PIL.Image(RGB)。

    说明：
    - 显式指定输出到 sRGB，避免依赖 rawpy/libraw 默认行为；
    - 默认关闭 auto bright，尽量保证不同入口颜色一致；
    - 默认使用相机白平衡，避免 Canon/Nikon 等机型 RAW 偏色。
    """
    debug(f"开始解码RAW图像: {file_path}")
    try:
        import rawpy
        import numpy as np
    except ImportError as e:
        raise ImportError(f"缺少 RAW 解码依赖 rawpy/numpy: {e}") from e

    with rawpy.imread(file_path) as raw:
        rgb = raw.postprocess(
            half_size=half_size,
            output_bps=output_bps,
            use_camera_wb=use_camera_wb,
            use_auto_wb=False,
            no_auto_bright=no_auto_bright,
            output_color=rawpy.ColorSpace.sRGB,
            gamma=(2.222, 4.5),
        )

    rgb = np.ascontiguousarray(rgb)

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("PIL 不可用，无法构建 RAW 图像对象") from None

    debug("RAW图像解码完成")
    return Image.fromarray(rgb, mode="RGB")


def load_raw_rgb_array(
    file_path: str,
    *,
    half_size: bool = False,
    use_camera_wb: bool = True,
    no_auto_bright: bool = True,
    output_bps: int = 8,
):
    """
    使用统一参数解码 RAW 图像，输出连续内存的 RGB numpy 数组。
    """
    debug(f"开始解码RAW图像为RGB数组: {file_path}")
    try:
        import rawpy
        import numpy as np
    except ImportError as e:
        raise ImportError(f"缺少 RAW 解码依赖 rawpy/numpy: {e}") from e

    with rawpy.imread(file_path) as raw:
        rgb = raw.postprocess(
            half_size=half_size,
            output_bps=output_bps,
            use_camera_wb=use_camera_wb,
            use_auto_wb=False,
            no_auto_bright=no_auto_bright,
            output_color=rawpy.ColorSpace.sRGB,
            gamma=(2.222, 4.5),
        )

    return np.ascontiguousarray(rgb)


__all__ = [
    "apply_exif_orientation",
    "convert_pil_to_srgb",
    "normalize_pil_image",
    "load_raw_image",
    "load_raw_rgb_array",
]
