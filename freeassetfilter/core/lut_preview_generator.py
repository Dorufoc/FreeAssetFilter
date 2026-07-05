#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

LUT预览生成器模块
生成应用LUT效果后的参考图像预览
"""

import os
import time
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt

# 导入日志模块
from freeassetfilter.utils.app_logger import debug, warning, error

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    warning("PIL/Pillow未安装，LUT预览功能将受限")

from freeassetfilter.utils.lut_utils import CubeLUTParser, get_lut_preview_dir

from freeassetfilter.core.cpp_lut_preview import warmup as cpp_warmup, generate_preview as cpp_generate_preview, is_cpp_available as _cpp_available


class LUTPreviewGenerator:
    """
    LUT预览生成器
    使用参考图像生成应用LUT后的预览图
    """
    
    def __init__(self, reference_image_path: Optional[str] = None):
        """
        初始化预览生成器
        
        Args:
            reference_image_path: 参考图像路径，如不提供则使用默认路径
        """
        if reference_image_path is None:
            # 使用默认参考图像路径
            base_dir = Path(__file__).parent.parent
            reference_image_path = base_dir / "icons" / "lut_reference.png"
        
        self.reference_image_path = str(reference_image_path)
        self._reference_image = None
        self._reference_image_scaled = {}
    
    def preload(self):
        """预加载参考图像和相关资源"""
        import numpy as np
        debug("预加载参考图像")
        self.load_reference_image()
        if self._reference_image is not None:
            for size in [(256, 256), (512, 512)]:
                self._reference_image_scaled[size] = np.array(
                    self._reference_image.resize(size, Image.Resampling.LANCZOS)
                )
            debug(f"参考图像预缩放完成，尺寸: {list(self._reference_image_scaled.keys())}")
    
    def load_reference_image(self) -> bool:
        """
        import numpy as np
        加载参考图像
        
        Returns:
            bool: 加载是否成功
        """
        if not os.path.exists(self.reference_image_path):
            warning(f"参考图像不存在: {self.reference_image_path}")
            return False
        
        try:
            if PIL_AVAILABLE:
                with Image.open(self.reference_image_path) as _ref_img:
                    _ref_img.load()  # ensure pixels loaded before file closed
                    if _ref_img.mode != 'RGB':
                        self._reference_image = _ref_img.convert('RGB')
                    else:
                        self._reference_image = _ref_img
            return True
        except (IOError, OSError) as e:
            error(f"加载参考图像失败: {e}")
            return False
        except Exception as e:
            error(f"加载参考图像失败: {e}")
            return False
    
    def generate_preview(self, lut_file_path: str,
                        output_size: Tuple[int, int] = (256, 256),
                        cache_path: Optional[str] = None) -> Optional[QPixmap]:
        """
        生成LUT预览图

        Args:
            lut_file_path: LUT文件路径
            output_size: 输出图像尺寸 (宽, 高)
            cache_path: 缓存文件路径，如提供则保存到该路径

        Returns:
            Optional[QPixmap]: 预览图像，失败返回None
        """
        if not PIL_AVAILABLE:
            warning("PIL不可用，无法生成LUT预览")
            return None
        
        # 检查缓存
        if cache_path and os.path.exists(cache_path):
            pixmap = QPixmap(cache_path)
            if not pixmap.isNull():
                return pixmap.scaled(output_size[0], output_size[1], 
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        # 优先使用 C++ 实现
        if _cpp_available():
            return self._generate_preview_cpp(lut_file_path, output_size, cache_path)
        
        # 回退到 Python 实现
        return self._generate_preview_python(lut_file_path, output_size, cache_path)
    
    def _generate_preview_cpp(self, lut_file_path: str,
                             output_size: Tuple[int, int],
                             cache_path: Optional[str]) -> Optional[QPixmap]:
        """使用 C++ 实现生成预览"""
        # _t0 = time.perf_counter()

        try:
            # 加载参考图像
            if self._reference_image is None:
                # _t1 = time.perf_counter()
                # debug(f"[LUT生成] {(_t1-_t0)*1000:.1f}ms - 参考图像未加载，开始加载")
                if not self.load_reference_image():
                    return None
                # _t2 = time.perf_counter()
                # debug(f"[LUT生成] {(_t2-_t1)*1000:.1f}ms - 参考图像加载完成")

            # 使用预缩放的图像缓存
            size_key = output_size
            if size_key not in self._reference_image_scaled:
                # _t1 = time.perf_counter()
                # debug(f"[LUT生成] {(_t1-_t0)*1000:.1f}ms - 创建缩放缓存 {size_key}")
                self._reference_image_scaled[size_key] = np.array(
                    self._reference_image.resize(size_key, Image.Resampling.LANCZOS)
                )
            img_array = self._reference_image_scaled[size_key]
            # _t1 = time.perf_counter()
            # debug(f"[LUT生成] {(_t1-_t0)*1000:.1f}ms - 图像准备完成")

            # 读取 LUT 文件内容（解决中文路径问题）
            with open(lut_file_path, 'r', encoding='utf-8') as f:
                lut_content = f.read()
            # _t2 = time.perf_counter()
            # debug(f"[LUT生成] {(_t2-_t0)*1000:.1f}ms - LUT文件读取完成，大小={len(lut_content)}")

            # 调用 C++ 模块生成预览
            png_data = cpp_generate_preview(
                lut_content,
                img_array,
                output_size[0],
                output_size[1]
            )
            # _t3 = time.perf_counter()
            # debug(f"[LUT生成] {(_t3-_t0)*1000:.1f}ms - C++ 处理完成，PNG大小={len(png_data)}")

            # 将 PNG 数据转换为 QPixmap
            qimage = QImage.fromData(png_data)
            pixmap = QPixmap.fromImage(qimage)

            # 保存缓存
            if cache_path and not pixmap.isNull():
                pixmap.save(cache_path, 'PNG')

            # _t4 = time.perf_counter()
            # debug(f"[LUT生成] {(_t4-_t0)*1000:.1f}ms - 全部完成")

            return pixmap

        except (IOError, OSError) as e:
            warning(f"C++预览生成失败，回退Python: {e}")
            return self._generate_preview_python(lut_file_path, output_size, cache_path)
        except ValueError as e:
            warning(f"C++预览生成失败，回退Python: {e}")
            return self._generate_preview_python(lut_file_path, output_size, cache_path)
        except Exception as e:
            warning(f"C++预览生成失败，回退Python: {e}")
            return self._generate_preview_python(lut_file_path, output_size, cache_path)
    
    def _generate_preview_python(self, lut_file_path: str,
                                output_size: Tuple[int, int],
                                cache_path: Optional[str]) -> Optional[QPixmap]:
        """使用 Python 实现生成预览"""
        debug("使用Python生成LUT预览")

        # 加载参考图像
        if self._reference_image is None:
            if not self.load_reference_image():
                return None

        # 解析LUT文件
        parser = CubeLUTParser(lut_file_path)
        if not parser.parse():
            warning(f"LUT文件解析失败: {lut_file_path}")
            return None
        
        try:
            # 调整参考图像大小
            preview_image = self._reference_image.copy()
            preview_image = preview_image.resize(output_size, Image.Resampling.LANCZOS)
            
            # 使用 numpy 向量化操作加速 LUT 应用（替代逐像素循环）
            img_array = np.asarray(preview_image, dtype=np.float32) / 255.0  # (H, W, 3), [0, 1]
            
            if parser.is_3d:
                result = self._apply_3d_lut_numpy(img_array, parser)
            else:
                result = self._apply_1d_lut_numpy(img_array, parser)
            
            # 转换回 PIL，确保像素值合法
            result = np.clip(result, 0.0, 1.0)
            preview_image = Image.fromarray((result * 255).astype(np.uint8), mode="RGB")
            
            # 保存缓存
            if cache_path:
                preview_image.save(cache_path, 'PNG')
            
            # 转换为QPixmap
            return self._pil_image_to_qpixmap(preview_image)
            
        except (IOError, OSError) as e:
            error(f"生成LUT预览失败: {e}")
            return None
        except ValueError as e:
            error(f"生成LUT预览失败: {e}")
            return None
        except MemoryError as e:
            error(f"生成LUT预览失败: {e}")
            return None
        except Exception as e:
            error(f"生成LUT预览失败: {e}")
            return None
    
    def _apply_1d_lut_numpy(self, img_array: np.ndarray, parser) -> np.ndarray:
        """
        使用 numpy.interp 向量化应用 1D LUT。
        
        Args:
            img_array: 输入图像数组 (H, W, 3), float32, [0, 1]
            parser: CubeLUTParser 实例
        
        Returns:
            输出图像数组 (H, W, 3), float32, [0, 1]
        """
        size = parser.lut_size
        data = np.array(parser.data, dtype=np.float32)  # (size*3, 3)

        # 1D LUT 数据排布：R0..Rn, G0..Gn, B0..Bn，每个三元组的 [0] 分量是实际值
        r_lut = data[0:size, 0]
        g_lut = data[size:2*size, 0]
        b_lut = data[2*size:3*size, 0]

        xp = np.linspace(0.0, 1.0, size, dtype=np.float32)

        r_out = np.interp(img_array[:, :, 0], xp, r_lut)
        g_out = np.interp(img_array[:, :, 1], xp, g_lut)
        b_out = np.interp(img_array[:, :, 2], xp, b_lut)

        return np.stack([r_out, g_out, b_out], axis=-1)

    def _apply_3d_lut_numpy(self, img_array: np.ndarray, parser) -> np.ndarray:
        """
        使用 numpy 向量化三线性插值应用 3D LUT。
        
        Args:
            img_array: 输入图像数组 (H, W, 3), float32, [0, 1]
            parser: CubeLUTParser 实例
        
        Returns:
            输出图像数组 (H, W, 3), float32, [0, 1]
        """
        size = parser.lut_size
        lut_data = np.array(parser.data, dtype=np.float32)  # (size^3, 3)

        # 映射到 LUT 网格坐标
        coords = img_array * (size - 1)  # (H, W, 3)
        r_coord = coords[:, :, 0]
        g_coord = coords[:, :, 1]
        b_coord = coords[:, :, 2]

        # 整数部分（低索引）
        r0 = np.floor(r_coord).astype(np.intp)
        g0 = np.floor(g_coord).astype(np.intp)
        b0 = np.floor(b_coord).astype(np.intp)
        # 高索引（防止越界）
        r1 = np.clip(r0 + 1, 0, size - 1)
        g1 = np.clip(g0 + 1, 0, size - 1)
        b1 = np.clip(b0 + 1, 0, size - 1)

        # 小数部分（插值权重）
        fr = r_coord - r0
        fg = g_coord - g0
        fb = b_coord - b0

        # 计算 8 个角点在 lut_data 中的索引: idx = (z * size + y) * size + x
        def _idx(x, y, z):
            return (z * size + y) * size + x

        idx000 = _idx(r0, g0, b0)
        idx001 = _idx(r0, g0, b1)
        idx010 = _idx(r0, g1, b0)
        idx011 = _idx(r0, g1, b1)
        idx100 = _idx(r1, g0, b0)
        idx101 = _idx(r1, g0, b1)
        idx110 = _idx(r1, g1, b0)
        idx111 = _idx(r1, g1, b1)

        # 批量查表：lut_data[idx] -> (H, W, 3)
        c000 = lut_data[idx000]
        c001 = lut_data[idx001]
        c010 = lut_data[idx010]
        c011 = lut_data[idx011]
        c100 = lut_data[idx100]
        c101 = lut_data[idx101]
        c110 = lut_data[idx110]
        c111 = lut_data[idx111]

        # 三线性插值（广播权重到 3 通道）
        w000 = (1 - fr) * (1 - fg) * (1 - fb)
        w001 = (1 - fr) * (1 - fg) * fb
        w010 = (1 - fr) * fg * (1 - fb)
        w011 = (1 - fr) * fg * fb
        w100 = fr * (1 - fg) * (1 - fb)
        w101 = fr * (1 - fg) * fb
        w110 = fr * fg * (1 - fb)
        w111 = fr * fg * fb

        result = (
            c000 * w000[:, :, None] +
            c001 * w001[:, :, None] +
            c010 * w010[:, :, None] +
            c011 * w011[:, :, None] +
            c100 * w100[:, :, None] +
            c101 * w101[:, :, None] +
            c110 * w110[:, :, None] +
            c111 * w111[:, :, None]
        )

        return result

    def _pil_image_to_qpixmap(self, pil_image) -> QPixmap:
        """
        将PIL图像转换为QPixmap
        
        Args:
            pil_image: PIL图像对象
            
        Returns:
            QPixmap: Qt图像对象
        """
        # 转换为RGBA模式
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')
        
        width, height = pil_image.size
        data = pil_image.tobytes('raw', 'RGBA')
        
        # 创建QImage
        qimage = QImage(data, width, height, QImage.Format_RGBA8888)
        
        # 转换为QPixmap
        return QPixmap.fromImage(qimage)
    
    def get_preview_path(self, lut_id: str) -> str:
        """
        获取预览图缓存路径
        
        Args:
            lut_id: LUT唯一标识
            
        Returns:
            str: 预览图路径
        """
        preview_dir = get_lut_preview_dir()
        return os.path.join(preview_dir, f"{lut_id}_preview.png")
    
    def clear_cache(self, lut_id: Optional[str] = None):
        """
        清除预览图缓存
        
        Args:
            lut_id: LUT唯一标识，如不提供则清除所有缓存
        """
        preview_dir = get_lut_preview_dir()
        
        if lut_id:
            # 清除指定LUT的缓存
            cache_path = self.get_preview_path(lut_id)
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except (IOError, OSError) as e:
                    error(f"清除缓存失败: {e}")
                except PermissionError as e:
                    error(f"清除缓存失败: {e}")
                except Exception as e:
                    error(f"清除缓存失败: {e}")
        else:
            # 清除所有缓存
            try:
                for file in Path(preview_dir).glob("*_preview.png"):
                    file.unlink()
            except (IOError, OSError) as e:
                error(f"清除所有缓存失败: {e}")
            except PermissionError as e:
                error(f"清除所有缓存失败: {e}")
            except Exception as e:
                error(f"清除所有缓存失败: {e}")


# 全局预览生成器实例
_preview_generator: Optional[LUTPreviewGenerator] = None


def get_preview_generator() -> LUTPreviewGenerator:
    """获取全局预览生成器实例"""
    global _preview_generator
    if _preview_generator is None:
        debug("创建LUT预览生成器实例")
        _preview_generator = LUTPreviewGenerator()
        _preview_generator.preload()
    return _preview_generator


def generate_lut_preview(lut_file_path: str, lut_id: str,
                        output_size: Tuple[int, int] = (256, 256)) -> Optional[QPixmap]:
    """
    生成LUT预览图的便捷函数
    
    Args:
        lut_file_path: LUT文件路径
        lut_id: LUT唯一标识
        output_size: 输出图像尺寸
        
    Returns:
        Optional[QPixmap]: 预览图像
    """
    generator = get_preview_generator()
    cache_path = generator.get_preview_path(lut_id)
    return generator.generate_preview(lut_file_path, output_size, cache_path)


def create_default_reference_image(output_path: Optional[str] = None) -> bool:
    """
    创建默认参考图像
    当参考图像不存在时，创建一个标准色彩测试图
    
    Args:
        output_path: 输出路径
        
    Returns:
        bool: 是否成功
    """
    if not PIL_AVAILABLE:
        return False
    
    try:
        if output_path is None:
            base_dir = Path(__file__).parent.parent
            output_path = base_dir / "icons" / "lut_reference.png"
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 创建一个标准色彩测试图 (400x400)
        size = 400
        image = Image.new('RGB', (size, size))
        pixels = image.load()
        
        # 创建色彩渐变
        for y in range(size):
            for x in range(size):
                # 红色渐变 - 从左到右
                r = int((x / size) * 255)
                # 绿色渐变 - 从上到下
                g = int((y / size) * 255)
                # 蓝色 - 基于位置
                b = int(((x + y) / (2 * size)) * 255)
                
                pixels[x, y] = (r, g, b)
        
        # 添加一些测试色块
        block_size = 80
        colors = [
            (255, 0, 0),    # 红
            (0, 255, 0),    # 绿
            (0, 0, 255),    # 蓝
            (255, 255, 0),  # 黄
            (255, 0, 255),  # 品红
            (0, 255, 255),  # 青
            (255, 255, 255),# 白
            (0, 0, 0),      # 黑
        ]
        
        for i, color in enumerate(colors):
            x = (i % 4) * block_size
            y = (i // 4) * block_size
            for dy in range(block_size):
                for dx in range(block_size):
                    if x + dx < size and y + dy < size:
                        pixels[x + dx, y + dy] = color
        
        image.save(output_path, 'PNG')
        return True
        
    except (IOError, OSError) as e:
        error(f"创建默认参考图像失败: {e}")
        return False
    except MemoryError as e:
        error(f"创建默认参考图像失败: {e}")
        return False
    except Exception as e:
        error(f"创建默认参考图像失败: {e}")
        return False