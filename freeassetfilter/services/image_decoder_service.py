#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

统一图像解码服务
纯解码层，内部逻辑无 Qt 依赖（仅 _pil_to_qimage 使用 PySide6.QtGui.QImage）。
支持格式：RAW、HEIF/AVIF、PSD，及常见标准格式的快速判定。
"""

from __future__ import annotations

import os
from typing import Tuple, Union

from freeassetfilter.utils.app_logger import debug, warning, error


# ── 异常类 ─────────────────────────────────────────────────────────────


class DecodeError(Exception):
    """图像解码基础异常。"""


class DependencyError(DecodeError):
    """缺少依赖库异常（ImportError 的封装）。"""


class CorruptFileError(DecodeError):
    """文件损坏或不可读异常。"""


# ── 对齐常量 ────────────────────────────────────────────────────────────

# 7z --help 检查核心库
# rawpy 用于解码 RAW
# psd-tools 用于合成 PSD
# pillow_heif 用于 HEIF/HEIC
# pillow_avif 用于 AVIF


class ImageDecoderService:
    """
    统一图像解码服务。

    功能：
    - 按扩展名分类格式（标准 / RAW / HEIF-AVIF / PSD）
    - 将各类复杂图像格式解码为 PIL Image，最终转换为 QImage
    - 文件过大时自动降采样以节省内存

    使用方式：:

        success, result = ImageDecoderService.decode_to_qimage("photo.cr2")
        if success:
            # result 是 QImage
            pixmap = QPixmap.fromImage(result)
        else:
            # result 是错误字符串
            print(result)
    """

    # ── 格式分类 ─────────────────────────────────────────────────────

    STANDARD_FORMATS: frozenset[str] = frozenset({
        '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif',
        '.webp', '.svg', '.ico', '.icon',
    })
    """标准格式（PIL / QImageReader 可直接解码，无需额外依赖）。"""

    RAW_FORMATS: frozenset[str] = frozenset({
        '.cr2', '.cr3', '.crw', '.nef', '.nrw', '.arw',
        '.srf', '.sr2', '.srw', '.dng', '.orf', '.raf',
        '.rw2', '.pef', '.ptx', '.x3f', '.3fr', '.ari',
        '.bay', '.bmq', '.cap', '.cs1', '.dcr', '.dcs',
        '.drf', '.eip', '.erf', '.fff', '.iiq', '.k25',
        '.kc2', '.kdc', '.mdc', '.mef', '.mos', '.mrw',
        '.obm', '.pxn', '.r3d', '.raw', '.rwl', '.rwz',
        '.sti',
    })
    """RAW 格式（需 rawpy 解码）。"""

    HEIF_AVIF_FORMATS: frozenset[str] = frozenset({
        '.heic', '.heif', '.avif',
    })
    """HEIF / AVIF 格式（需 pillow_heif / pillow_avif 插件）。"""

    PSD_FORMATS: frozenset[str] = frozenset({
        '.psd',
    })
    """PSD 格式（需 psd-tools 合成）。"""

    # ── 内存阈值 ────────────────────────────────────────────────────

    _RAW_LARGE_THRESHOLD: int = 10 * 1024 * 1024   # 10 MB
    _HEIF_LARGE_THRESHOLD: int = 20 * 1024 * 1024  # 20 MB
    _MAX_HEIF_DIMENSION: int = 2048

    # ── 公共 API ─────────────────────────────────────────────────────

    @classmethod
    def is_complex_format(cls, suffix: str) -> bool:
        """
        判断 *suffix* 是否为复杂格式（RAW / HEIF-AVIF / PSD）。

        Parameters
        ----------
        suffix : str
            文件扩展名（可带前导点，如 ``'.cr2'`` 或 ``'cr2'``）。

        Returns
        -------
        bool
            属于复杂格式返回 ``True``，标准格式或 ``.gif`` 返回 ``False``。
        """
        suffix = suffix.lower()
        if not suffix.startswith('.'):
            suffix = '.' + suffix

        return (
            suffix in cls.RAW_FORMATS
            or suffix in cls.HEIF_AVIF_FORMATS
            or suffix in cls.PSD_FORMATS
        )

    @classmethod
    def decode_to_qimage(
        cls,
        file_path: str,
    ) -> Tuple[bool, Union[object, str]]:
        """
        将 *file_path* 解码为 QImage。

        此方法为唯一公共入口。根据扩展名自动分派到对应的解码方法，
        并捕获所有异常（含 MemoryError），确保绝不向上传播。

        Parameters
        ----------
        file_path : str
            图像文件路径。

        Returns
        -------
        tuple[bool, QImage | str]
            ``(True, QImage)`` 解码成功；
            ``(False, "错误消息")`` 解码失败。
        """
        try:
            suffix = cls._get_suffix(file_path)
            if not suffix:
                return False, f"无法识别的文件格式: {file_path}"

            # ── 按扩展名分派 ────────────────────────────────────────
            if suffix in cls.RAW_FORMATS:
                pil_image = cls._decode_raw(file_path)
            elif suffix in cls.HEIF_AVIF_FORMATS:
                pil_image = cls._decode_heif_avif(file_path)
            elif suffix in cls.PSD_FORMATS:
                pil_image = cls._decode_psd(file_path)
            else:
                return False, f"ImageDecoderService 不支持的格式: {suffix}"

            if pil_image is None:
                return False, "解码后图像为空"

            qimage = cls._pil_to_qimage(pil_image)
            if qimage is None or qimage.isNull():
                return False, "转换 QImage 失败"

            return True, qimage

        except MemoryError:
            error(f"[ImageDecoderService] 内存不足，无法解码超大图片: {file_path}")
            return False, "内存不足，无法解码超大图片"
        except DependencyError as e:
            error(f"[ImageDecoderService] 缺少依赖: {e}")
            return False, str(e)
        except CorruptFileError as e:
            error(f"[ImageDecoderService] 文件损坏: {e}")
            return False, str(e)
        except BaseException as e:
            error(f"[ImageDecoderService] 解码未知异常: {e}")
            return False, str(e)

    # ── RAW 解码 ────────────────────────────────────────────────────

    @classmethod
    def _decode_raw(cls, file_path: str) -> object:
        """
        解码 RAW 图像文件。

        委托给 ``freeassetfilter.core.preview.image_color_utils.load_raw_image``。
        超过 10 MB 的文件自动启用 ``half_size=True`` 以降低内存占用。

        Parameters
        ----------
        file_path : str
            RAW 文件路径。

        Returns
        -------
        PIL.Image
            解码后的 PIL Image。

        Raises
        ------
        DependencyError
            缺少 rawpy 或 numpy。
        CorruptFileError
            文件损坏或无法读取。
        """
        try:
            from freeassetfilter.core.preview.image_color_utils import load_raw_image
        except ImportError as e:
            raise DependencyError(f"缺少 RAW 解码依赖 (rawpy/numpy): {e}") from e

        try:
            file_size = os.path.getsize(file_path)
            half_size = file_size > cls._RAW_LARGE_THRESHOLD

            debug(f"[ImageDecoderService] 解码 RAW ({'half' if half_size else 'full'}): {file_path}")
            return load_raw_image(
                file_path,
                half_size=half_size,
                use_camera_wb=True,
                no_auto_bright=True,
                output_bps=8,
            )
        except ImportError as e:
            raise DependencyError(f"缺少 RAW 解码依赖: {e}") from e
        except (OSError, IOError, ValueError) as e:
            raise CorruptFileError(f"RAW 文件损坏或不可读: {e}") from e
        except Exception as e:
            raise DecodeError(f"RAW 解码失败: {e}") from e

    # ── HEIF / AVIF 解码 ────────────────────────────────────────────

    @classmethod
    def _decode_heif_avif(cls, file_path: str) -> object:
        """
        解码 HEIC / HEIF / AVIF 图像文件。

        自动注册 ``pillow_heif`` 及可选的 ``pillow_avif`` 插件。
        超过 20 MB 的文件自动缩放到最长边不超过 2048 像素。
        输出模式：含透明通道的图像转为 RGBA，其余转为 RGB。

        Parameters
        ----------
        file_path : str
            HEIF/AVIF 文件路径。

        Returns
        -------
        PIL.Image
            解码后的 PIL Image。

        Raises
        ------
        DependencyError
            缺少 pillow_heif。
        CorruptFileError
            文件损坏或无法读取。
        """
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError as e:
            raise DependencyError(f"缺少 HEIF 解码依赖 (pillow_heif): {e}") from e

        # pillow_avif 为可选依赖
        try:
            import pillow_avif  # noqa: F401
        except ImportError:
            debug("[ImageDecoderService] pillow_avif 未安装，Pillow 可能无法解码 AVIF")

        try:
            from PIL import Image as PILImage
        except ImportError as e:
            raise DependencyError(f"缺少 PIL: {e}") from e

        try:
            debug(f"[ImageDecoderService] 解码 HEIF/AVIF: {file_path}")
            with PILImage.open(file_path) as img:
                # ── 色彩模式转换 ─────────────────────────────────────
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGBA')
                elif img.mode == 'L':
                    img = img.convert('RGB')
                elif img.mode in ('RGBX', 'RGBa'):
                    img = img.convert('RGBA')
                elif img.mode == '1':
                    img = img.convert('RGB')
                else:
                    img = img.convert('RGB')

                # ── 大文件降采样 ─────────────────────────────────────
                file_size = os.path.getsize(file_path)
                if file_size > cls._HEIF_LARGE_THRESHOLD:
                    if (img.width > cls._MAX_HEIF_DIMENSION
                            or img.height > cls._MAX_HEIF_DIMENSION):
                        ratio = min(
                            cls._MAX_HEIF_DIMENSION / img.width,
                            cls._MAX_HEIF_DIMENSION / img.height,
                        )
                        new_width = int(img.width * ratio)
                        new_height = int(img.height * ratio)
                        img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)

                return img
        except (OSError, IOError, ValueError) as e:
            raise CorruptFileError(f"HEIF/AVIF 文件损坏或不可读: {e}") from e

    # ── PSD 解码 ─────────────────────────────────────────────────────

    @classmethod
    def _decode_psd(cls, file_path: str) -> object:
        """
        解码 PSD 图像文件。

        使用 ``psd_tools.PSDImage.open`` 打开并调用 ``composite()``
        合成所有可见图层。最终输出模式转为 RGBA。

        Parameters
        ----------
        file_path : str
            PSD 文件路径。

        Returns
        -------
        PIL.Image
            合成后的 PIL Image (RGBA)。

        Raises
        ------
        DependencyError
            缺少 psd-tools。
        CorruptFileError
            文件损坏或无法读取。
        """
        try:
            from psd_tools import PSDImage
        except ImportError as e:
            raise DependencyError(f"缺少 PSD 解码依赖 (psd-tools): {e}") from e

        try:
            debug(f"[ImageDecoderService] 解码 PSD: {file_path}")
            psd = PSDImage.open(file_path)
            composited = psd.composite()

            if composited is None:
                raise CorruptFileError("PSD 合成结果为空")

            if composited.mode != 'RGBA':
                composited = composited.convert('RGBA')

            return composited
        except CorruptFileError:
            raise
        except ImportError as e:
            raise DependencyError(f"缺少 PSD 解码依赖: {e}") from e
        except (OSError, IOError, ValueError) as e:
            raise CorruptFileError(f"PSD 文件损坏或不可读: {e}") from e
        except Exception as e:
            raise DecodeError(f"PSD 解码失败: {e}") from e

    # ── PIL → QImage ────────────────────────────────────────────────

    @classmethod
    def _pil_to_qimage(cls, pil_image: object) -> object:
        """
        将 PIL Image 转换为 QImage。

        **此方法是本服务中唯一导入 PySide6 的方法**，因此即使
        PySide6 不可用，类的其他方法仍可正常导入和运行（适用于
        无头测试或批量处理场景）。

        .. important::
            返回值包含对底层数据的一份 ``.copy()``，确保 PIL / numpy
            数组被垃圾回收后 QImage 不会访问悬空内存。这是从代码审查
            验证的强制性要求。

        Parameters
        ----------
        pil_image : PIL.Image
            输入 PIL Image。

        Returns
        -------
        QImage | None
            转换后的 QImage，失败时返回 ``None``。
        """
        try:
            from PIL import Image as PILImage
            import numpy as np
            from PySide6.QtGui import QImage
        except ImportError as e:
            warning(f"[ImageDecoderService] 转换 QImage 缺少依赖: {e}")
            return None

        try:
            # 确保是 PIL Image 对象
            if not isinstance(pil_image, PILImage.Image):
                warning("[ImageDecoderService] _pil_to_qimage 输入不是 PIL Image")
                return None

            # 统一到 RGBA 或 RGB
            has_alpha = pil_image.mode in ('RGBA', 'LA', 'PA')
            if pil_image.mode not in ('RGB', 'RGBA'):
                pil_image = pil_image.convert('RGBA' if has_alpha else 'RGB')

            img_array = np.array(pil_image)
            height, width = img_array.shape[:2]

            if pil_image.mode == 'RGBA':
                bytes_per_line = width * 4
                qimage = QImage(
                    img_array.tobytes(),
                    width, height,
                    bytes_per_line,
                    QImage.Format.Format_RGBA8888,
                ).copy()
            else:
                bytes_per_line = width * 3
                qimage = QImage(
                    img_array.tobytes(),
                    width, height,
                    bytes_per_line,
                    QImage.Format.Format_RGB888,
                ).copy()

            if qimage.isNull():
                warning("[ImageDecoderService] _pil_to_qimage 返回空 QImage")
                return None

            return qimage
        except Exception as e:
            error(f"[ImageDecoderService] PIL→QImage 转换失败: {e}")
            return None

    # ── 内部工具 ─────────────────────────────────────────────────────

    @staticmethod
    def _get_suffix(file_path: str) -> str:
        """
        从文件路径提取小写扩展名（含前导点）。

        Parameters
        ----------
        file_path : str
            文件路径。

        Returns
        -------
        str
            小写扩展名（如 ``'.cr2'``），无法识别时返回 ``''``。
        """
        if not file_path or not isinstance(file_path, str):
            return ''
        _, ext = os.path.splitext(file_path)
        return ext.lower()


__all__ = [
    "DecodeError",
    "DependencyError",
    "CorruptFileError",
    "ImageDecoderService",
]
