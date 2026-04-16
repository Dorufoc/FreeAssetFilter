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

from typing import Optional

from freeassetfilter.utils.app_logger import debug, info, warning

try:
    from PIL import Image, ImageCms, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    ImageCms = None
    ImageOps = None
    PIL_AVAILABLE = False


def apply_exif_orientation(image: "Image.Image") -> "Image.Image":
    """
    应用 EXIF 方向校正。
    """
    if not PIL_AVAILABLE or image is None:
        return image

    try:
        return ImageOps.exif_transpose(image)
    except Exception as e:
        debug(f"EXIF方向校正失败: {e}")
        return image


def convert_pil_to_srgb(image: "Image.Image") -> "Image.Image":
    """
    若图像带有 ICC Profile，则尽量转换到 sRGB。
    """
    if not PIL_AVAILABLE or image is None or ImageCms is None:
        return image

    try:
        icc_profile = image.info.get("icc_profile")
        if not icc_profile:
            return image

        src_profile = ImageCms.ImageCmsProfile(icc_profile)
        dst_profile = ImageCms.createProfile("sRGB")
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
    if not PIL_AVAILABLE or image is None:
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

    if not PIL_AVAILABLE:
        raise RuntimeError("PIL 不可用，无法构建 RAW 图像对象")

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
    "PIL_AVAILABLE",
    "apply_exif_orientation",
    "convert_pil_to_srgb",
    "normalize_pil_image",
    "load_raw_image",
    "load_raw_rgb_array",
]
