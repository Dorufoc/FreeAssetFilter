#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

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

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("警告: PIL/Pillow未安装，LUT预览功能将受限")

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
            base_dir = Path(__file__).parent.parent.parent
            reference_image_path = base_dir / "data" / "reference.png"
        
        self.reference_image_path = str(reference_image_path)
        self._reference_image = None
        self._reference_image_scaled = {}
    
    def preload(self):
        """预加载参考图像和相关资源"""
        self.load_reference_image()
        if self._reference_image is not None:
            for size in [(160, 160), (320, 320)]:
                self._reference_image_scaled[size] = np.array(
                    self._reference_image.resize(size, Image.Resampling.LANCZOS)
                )
    
    def load_reference_image(self) -> bool:
        """
        加载参考图像
        
        Returns:
            bool: 加载是否成功
        """
        if not os.path.exists(self.reference_image_path):
            print(f"参考图像不存在: {self.reference_image_path}")
            return False
        
        try:
            if PIL_AVAILABLE:
                self._reference_image = Image.open(self.reference_image_path)
                # 转换为RGB模式
                if self._reference_image.mode != 'RGB':
                    self._reference_image = self._reference_image.convert('RGB')
            return True
        except Exception as e:
            print(f"加载参考图像失败: {e}")
            return False
    
    def generate_preview(self, lut_file_path: str, 
                        output_size: Tuple[int, int] = (160, 160),
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
        import time
        _t0 = time.perf_counter()
        
        try:
            # 加载参考图像
            if self._reference_image is None:
                _t1 = time.perf_counter()
                print(f"[LUT生成] {(_t1-_t0)*1000:.1f}ms - 参考图像未加载，开始加载")
                if not self.load_reference_image():
                    return None
                _t2 = time.perf_counter()
                print(f"[LUT生成] {(_t2-_t1)*1000:.1f}ms - 参考图像加载完成")
            
            # 使用预缩放的图像缓存
            size_key = output_size
            if size_key not in self._reference_image_scaled:
                _t1 = time.perf_counter()
                print(f"[LUT生成] {(_t1-_t0)*1000:.1f}ms - 创建缩放缓存 {size_key}")
                self._reference_image_scaled[size_key] = np.array(
                    self._reference_image.resize(size_key, Image.Resampling.LANCZOS)
                )
            img_array = self._reference_image_scaled[size_key]
            _t1 = time.perf_counter()
            print(f"[LUT生成] {(_t1-_t0)*1000:.1f}ms - 图像准备完成")
            
            # 读取 LUT 文件内容（解决中文路径问题）
            with open(lut_file_path, 'r', encoding='utf-8') as f:
                lut_content = f.read()
            _t2 = time.perf_counter()
            print(f"[LUT生成] {(_t2-_t0)*1000:.1f}ms - LUT文件读取完成，大小={len(lut_content)}")
            
            # 调用 C++ 模块生成预览
            png_data = cpp_generate_preview(
                lut_content,
                img_array,
                output_size[0],
                output_size[1]
            )
            _t3 = time.perf_counter()
            print(f"[LUT生成] {(_t3-_t0)*1000:.1f}ms - C++ 处理完成，PNG大小={len(png_data)}")
            
            # 将 PNG 数据转换为 QPixmap
            from io import BytesIO
            qimage = QImage.fromData(png_data)
            pixmap = QPixmap.fromImage(qimage)
            
            # 保存缓存
            if cache_path and not pixmap.isNull():
                pixmap.save(cache_path, 'PNG')
            
            _t4 = time.perf_counter()
            print(f"[LUT生成] {(_t4-_t0)*1000:.1f}ms - 全部完成")
            
            return pixmap
            
        except Exception as e:
            print(f"C++ 预览生成失败，回退到Python: {e}")
            return self._generate_preview_python(lut_file_path, output_size, cache_path)
    
    def _generate_preview_python(self, lut_file_path: str, 
                                output_size: Tuple[int, int],
                                cache_path: Optional[str]) -> Optional[QPixmap]:
        """使用 Python 实现生成预览"""
        # 加载参考图像
        if self._reference_image is None:
            if not self.load_reference_image():
                return None
        
        # 解析LUT文件
        parser = CubeLUTParser(lut_file_path)
        if not parser.parse():
            return None
        
        try:
            # 调整参考图像大小
            preview_image = self._reference_image.copy()
            preview_image = preview_image.resize(output_size, Image.Resampling.LANCZOS)
            
            # 应用LUT
            pixels = preview_image.load()
            width, height = preview_image.size
            
            for y in range(height):
                for x in range(width):
                    r, g, b = pixels[x, y]
                    
                    # 归一化到0-1范围
                    r_norm = r / 255.0
                    g_norm = g / 255.0
                    b_norm = b / 255.0
                    
                    # 应用LUT
                    r_out, g_out, b_out = parser.apply_to_pixel(r_norm, g_norm, b_norm)
                    
                    # 转换回0-255范围
                    r_out = max(0, min(255, int(r_out * 255)))
                    g_out = max(0, min(255, int(g_out * 255)))
                    b_out = max(0, min(255, int(b_out * 255)))
                    
                    pixels[x, y] = (r_out, g_out, b_out)
            
            # 保存缓存
            if cache_path:
                preview_image.save(cache_path, 'PNG')
            
            # 转换为QPixmap
            return self._pil_image_to_qpixmap(preview_image)
            
        except Exception as e:
            print(f"生成LUT预览失败: {e}")
            return None
    
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
                except Exception as e:
                    print(f"清除缓存失败: {e}")
        else:
            # 清除所有缓存
            try:
                for file in Path(preview_dir).glob("*_preview.png"):
                    file.unlink()
            except Exception as e:
                print(f"清除所有缓存失败: {e}")


# 全局预览生成器实例
_preview_generator: Optional[LUTPreviewGenerator] = None


def get_preview_generator() -> LUTPreviewGenerator:
    """获取全局预览生成器实例"""
    global _preview_generator
    if _preview_generator is None:
        _preview_generator = LUTPreviewGenerator()
        _preview_generator.preload()
    return _preview_generator


def generate_lut_preview(lut_file_path: str, lut_id: str,
                        output_size: Tuple[int, int] = (160, 160)) -> Optional[QPixmap]:
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
            base_dir = Path(__file__).parent.parent.parent
            output_path = base_dir / "data" / "reference.png"
        
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
        
    except Exception as e:
        print(f"创建默认参考图像失败: {e}")
        return False
