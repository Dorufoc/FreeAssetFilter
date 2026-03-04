#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；
2. 商业使用：需联系 qpdrfc123@gmail.com 获取书面授权；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

缩略图生成管理模块
统一处理文件选择器和文件储存池的缩略图生成需求
"""

import os
import hashlib
from typing import Optional, Tuple, Callable
from pathlib import Path

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.utils.path_utils import get_app_data_path

# 尝试导入PIL库
PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    warning("PIL库未安装，缩略图功能将受限")

# 尝试导入OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    warning("OpenCV库未安装，视频缩略图功能将不可用")


class ThumbnailManager:
    """
    缩略图管理器
    统一管理缩略图的生成、缓存和清理
    """
    
    # 支持的图片格式
    IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg', '.avif', '.heic']
    # 支持的RAW格式
    RAW_FORMATS = ['.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf']
    # 支持的PSD格式
    PSD_FORMATS = ['.psd', '.psb']
    # 支持的视频格式
    VIDEO_FORMATS = ['.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpeg', '.mpg', '.mxf']
    
    # 缩略图基础尺寸
    BASE_SIZE = 128
    
    # 缩略图质量
    QUALITY = 85
    
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, dpi_scale: float = 1.0):
        """
        初始化缩略图管理器
        
        Args:
            dpi_scale: DPI缩放因子，默认为1.0
        """
        if ThumbnailManager._initialized:
            # 更新DPI缩放因子
            self.dpi_scale = dpi_scale
            return
        
        ThumbnailManager._initialized = True
        self.dpi_scale = dpi_scale
        
        # 缩略图缓存目录
        self._thumb_dir = os.path.join(get_app_data_path(), 'thumbnails')
        os.makedirs(self._thumb_dir, exist_ok=True)
        
        debug(f"[ThumbnailManager] 初始化完成，缩略图目录: {self._thumb_dir}")
    
    def set_dpi_scale(self, dpi_scale: float):
        """
        设置DPI缩放因子
        
        Args:
            dpi_scale: DPI缩放因子
        """
        self.dpi_scale = dpi_scale
    
    def get_thumbnail_dir(self) -> str:
        """
        获取缩略图缓存目录路径
        
        Returns:
            str: 缩略图目录路径
        """
        return self._thumb_dir
    
    def get_thumbnail_path(self, file_path: str) -> str:
        """
        获取文件的缩略图路径
        
        Args:
            file_path: 原始文件路径
            
        Returns:
            str: 缩略图文件路径
        """
        # 使用文件路径的MD5哈希作为缩略图文件名
        md5_hash = hashlib.md5(file_path.encode('utf-8'))
        file_hash = md5_hash.hexdigest()[:16]
        return os.path.join(self._thumb_dir, f"{file_hash}.png")
    
    def has_thumbnail(self, file_path: str) -> bool:
        """
        检查文件是否已有缩略图
        
        Args:
            file_path: 原始文件路径
            
        Returns:
            bool: 是否存在缩略图
        """
        thumbnail_path = self.get_thumbnail_path(file_path)
        return os.path.exists(thumbnail_path)
    
    def is_media_file(self, file_path: str) -> bool:
        """
        判断文件是否为媒体文件（图片或视频）
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为媒体文件
        """
        suffix = os.path.splitext(file_path)[1].lower()
        return (suffix in self.IMAGE_FORMATS or 
                suffix in self.RAW_FORMATS or 
                suffix in self.PSD_FORMATS or 
                suffix in self.VIDEO_FORMATS)
    
    def is_image_file(self, file_path: str) -> bool:
        """
        判断文件是否为图片文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为图片文件
        """
        suffix = os.path.splitext(file_path)[1].lower()
        return suffix in self.IMAGE_FORMATS or suffix in self.RAW_FORMATS or suffix in self.PSD_FORMATS
    
    def is_video_file(self, file_path: str) -> bool:
        """
        判断文件是否为视频文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否为视频文件
        """
        suffix = os.path.splitext(file_path)[1].lower()
        return suffix in self.VIDEO_FORMATS
    
    def create_thumbnail(self, file_path: str, force_regenerate: bool = False) -> Optional[str]:
        """
        为文件创建缩略图
        
        Args:
            file_path: 文件路径
            force_regenerate: 是否强制重新生成，即使缩略图已存在
            
        Returns:
            Optional[str]: 缩略图路径，生成失败返回None
        """
        if not os.path.exists(file_path):
            warning(f"[ThumbnailManager] 文件不存在: {file_path}")
            return None
        
        thumbnail_path = self.get_thumbnail_path(file_path)
        
        # 如果缩略图已存在且不强制重新生成，直接返回
        if not force_regenerate and os.path.exists(thumbnail_path):
            return thumbnail_path
        
        # 检查是否为媒体文件
        if not self.is_media_file(file_path):
            return None
        
        # 生成缩略图
        try:
            if self.is_image_file(file_path):
                return self._create_image_thumbnail(file_path, thumbnail_path)
            elif self.is_video_file(file_path):
                return self._create_video_thumbnail(file_path, thumbnail_path)
        except Exception as e:
            error(f"[ThumbnailManager] 生成缩略图失败: {file_path}, 错误: {e}")
        
        return None
    
    def _create_image_thumbnail(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """
        为图片文件创建缩略图
        
        Args:
            file_path: 图片文件路径
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 缩略图路径，失败返回None
        """
        if not PIL_AVAILABLE:
            warning("[ThumbnailManager] PIL库未安装，无法生成图片缩略图")
            return None
        
        try:
            suffix = os.path.splitext(file_path)[1].lower()
            
            # 加载图像
            img, success = self._load_image(file_path, suffix)
            if not success or img is None:
                return None
            
            # 计算缩略图尺寸
            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
            
            # 使用thumbnail方法生成缩略图，保持宽高比
            img.thumbnail((dpi_scaled_size, dpi_scaled_size), Image.Resampling.LANCZOS)
            new_width, new_height = img.size
            
            # 创建透明背景
            dpi_scaled_background_size = int(self.BASE_SIZE * self.dpi_scale)
            thumbnail = Image.new("RGBA", (dpi_scaled_background_size, dpi_scaled_background_size), (0, 0, 0, 0))
            
            # 居中绘制
            x_offset = (dpi_scaled_background_size - new_width) // 2
            y_offset = (dpi_scaled_background_size - new_height) // 2
            
            # 处理不同模式的图像
            if img.mode == 'RGBA':
                thumbnail.paste(img, (x_offset, y_offset), img)
            elif img.mode == 'P':
                img = img.convert('RGBA')
                thumbnail.paste(img, (x_offset, y_offset), img)
            else:
                img = img.convert('RGBA')
                thumbnail.paste(img, (x_offset, y_offset))
            
            # 释放原始图像内存
            img.close()
            
            # 保存缩略图
            thumbnail.save(thumbnail_path, format='PNG', quality=self.QUALITY)
            thumbnail.close()
            
            debug(f"[ThumbnailManager] 图片缩略图生成成功: {thumbnail_path}")
            return thumbnail_path
            
        except Exception as e:
            warning(f"[ThumbnailManager] 生成图片缩略图失败: {file_path}, 错误: {e}")
            return None
    
    def _create_video_thumbnail(self, file_path: str, thumbnail_path: str) -> Optional[str]:
        """
        为视频文件创建缩略图
        
        Args:
            file_path: 视频文件路径
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 缩略图路径，失败返回None
        """
        if not CV2_AVAILABLE:
            warning("[ThumbnailManager] OpenCV库未安装，无法生成视频缩略图")
            return None
        
        if not PIL_AVAILABLE:
            warning("[ThumbnailManager] PIL库未安装，无法生成视频缩略图")
            return None
        
        cap = None
        try:
            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                warning(f"[ThumbnailManager] 无法打开视频文件: {file_path}")
                return None
            
            # 获取视频信息
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            frame = None
            
            # 策略1: 优先读取第240帧（跳过可能损坏的开头）
            if total_frames > 240:
                frame = self._read_frame_at_position(cap, 240)
            
            # 策略2: 读取50%相对位置
            if frame is None and total_frames > 0:
                cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 0.5)
                ret, frame = cap.read()
                if not ret or frame is None:
                    frame = None
            
            # 策略3: 读取第2帧
            if frame is None:
                frame = self._read_frame_at_position(cap, 2)
            
            # 策略4: 读取第1帧
            if frame is None:
                frame = self._read_frame_at_position(cap, 1)
            
            # 策略5: 尝试其他相对位置
            if frame is None:
                for ratio in [0.03, 0.1, 0.7, 0.9]:
                    cap.set(cv2.CAP_PROP_POS_AVI_RATIO, ratio)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        break
                    frame = None
            
            if frame is None:
                warning(f"[ThumbnailManager] 无法从视频中读取有效帧: {file_path}")
                return None
            
            # 处理并保存帧
            return self._process_and_save_video_frame(frame, thumbnail_path)
            
        except Exception as e:
            error(f"[ThumbnailManager] 生成视频缩略图失败: {file_path}, 错误: {e}")
            return None
        finally:
            if cap is not None:
                cap.release()
    
    def _read_frame_at_position(self, cap, frame_pos: int) -> Optional:
        """
        在指定位置读取视频帧
        
        Args:
            cap: OpenCV视频捕获对象
            frame_pos: 帧位置
            
        Returns:
            Optional: 视频帧，失败返回None
        """
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
            ret, frame = cap.read()
            if ret and frame is not None and frame.shape[0] > 0 and frame.shape[1] > 0:
                return frame
            return None
        except Exception as e:
            debug(f"读取视频帧失败 (位置: {frame_pos}): {e}")
            return None
    
    def _process_and_save_video_frame(self, frame, thumbnail_path: str) -> Optional[str]:
        """
        处理视频帧并保存为缩略图
        
        Args:
            frame: 视频帧
            thumbnail_path: 缩略图保存路径
            
        Returns:
            Optional[str]: 缩略图路径，失败返回None
        """
        try:
            # 计算原始宽高比
            original_height, original_width = frame.shape[:2]
            aspect_ratio = original_width / original_height
            
            # 计算新尺寸
            dpi_scaled_size = int(self.BASE_SIZE * self.dpi_scale)
            
            if aspect_ratio > 1:
                new_width = dpi_scaled_size
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = dpi_scaled_size
                new_width = int(new_height * aspect_ratio)
            
            # 对于超大视频帧，先进行适度下采样
            total_pixels = original_width * original_height
            if total_pixels > 10000000:
                min_downsample_width = max(new_width * 2, 1024)
                min_downsample_height = max(new_height * 2, 1024)
                
                downsample_ratio = min(
                    original_width / min_downsample_width,
                    original_height / min_downsample_height
                )
                
                if downsample_ratio > 1:
                    downsampled_width = int(original_width / downsample_ratio)
                    downsampled_height = int(original_height / downsample_ratio)
                    downsampled_frame = cv2.resize(
                        frame,
                        (downsampled_width, downsampled_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )
                    resized_frame = cv2.resize(
                        downsampled_frame,
                        (new_width, new_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )
                else:
                    resized_frame = cv2.resize(
                        frame,
                        (new_width, new_height),
                        interpolation=cv2.INTER_LANCZOS4
                    )
            else:
                resized_frame = cv2.resize(
                    frame,
                    (new_width, new_height),
                    interpolation=cv2.INTER_LANCZOS4
                )
            
            # 转换为PIL图像
            frame_pil = Image.fromarray(cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB))
            
            # 创建透明背景
            dpi_scaled_background_size = int(self.BASE_SIZE * self.dpi_scale)
            thumbnail = Image.new(
                "RGBA",
                (dpi_scaled_background_size, dpi_scaled_background_size),
                (0, 0, 0, 0)
            )
            
            # 居中绘制
            x_offset = (dpi_scaled_background_size - new_width) // 2
            y_offset = (dpi_scaled_background_size - new_height) // 2
            thumbnail.paste(frame_pil, (x_offset, y_offset))
            
            # 保存缩略图
            thumbnail.save(thumbnail_path, format='PNG', quality=self.QUALITY)
            
            debug(f"[ThumbnailManager] 视频缩略图生成成功: {thumbnail_path}")
            return thumbnail_path
            
        except Exception as e:
            error(f"[ThumbnailManager] 处理视频帧失败: {e}")
            return None
    
    def _load_image(self, file_path: str, suffix: str) -> Tuple[Optional[Image.Image], bool]:
        """
        加载图像文件
        
        Args:
            file_path: 图像文件路径
            suffix: 文件后缀名
            
        Returns:
            Tuple[Optional[Image.Image], bool]: (图像对象, 是否成功)
        """
        if not PIL_AVAILABLE:
            return None, False
        
        try:
            if suffix in self.RAW_FORMATS:
                # RAW格式
                try:
                    import rawpy
                    with rawpy.imread(file_path) as raw:
                        rgb = raw.postprocess()
                    img = Image.fromarray(rgb)
                except ImportError:
                    warning(f"[ThumbnailManager] rawpy库未安装，无法加载RAW文件: {file_path}")
                    return None, False
            elif suffix in ['.avif', '.heic']:
                # AVIF和HEIC格式
                try:
                    import pillow_avif
                except ImportError:
                    pass
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except ImportError:
                    pass
                img = Image.open(file_path)
            elif suffix in self.PSD_FORMATS:
                # PSD格式
                try:
                    from psd_tools import PSDImage
                    psd = PSDImage.open(file_path)
                    img = psd.composite()
                except ImportError:
                    warning(f"[ThumbnailManager] psd-tools库未安装，无法加载PSD文件: {file_path}")
                    return None, False
            elif suffix == '.svg':
                # SVG格式
                return self._load_svg_image(file_path)
            else:
                # 普通图像格式
                img = Image.open(file_path)
            
            return img, True
            
        except Exception as e:
            warning(f"[ThumbnailManager] 加载图像失败: {file_path}, 错误: {e}")
            return None, False
    
    def _load_svg_image(self, file_path: str) -> Tuple[Optional[Image.Image], bool]:
        """
        加载SVG图像
        
        Args:
            file_path: SVG文件路径
            
        Returns:
            Tuple[Optional[Image.Image], bool]: (图像对象, 是否成功)
        """
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QImage, QPainter
            from PySide6.QtCore import Qt
            
            # 直接使用QSvgRenderer渲染SVG，不经过SvgRenderer的复杂处理
            renderer = QSvgRenderer(file_path)
            
            if not renderer.isValid():
                warning(f"[ThumbnailManager] 无效的SVG文件: {file_path}")
                return None, False
            
            # 获取SVG的默认尺寸
            default_size = renderer.defaultSize()
            
            # 如果SVG没有设置尺寸，使用默认尺寸 256x256
            if default_size.width() <= 0 or default_size.height() <= 0:
                render_width, render_height = 256, 256
            else:
                # 保持原始比例，最大边为256
                max_size = 256
                scale = min(max_size / default_size.width(), max_size / default_size.height())
                render_width = int(default_size.width() * scale)
                render_height = int(default_size.height() * scale)
                
                # 确保最小尺寸为1
                render_width = max(1, render_width)
                render_height = max(1, render_height)
            
            # 创建QImage用于渲染 - 直接使用计算好的保持比例的尺寸
            qimage = QImage(render_width, render_height, QImage.Format_ARGB32_Premultiplied)
            qimage.fill(Qt.transparent)
            
            # 创建画家并渲染
            painter = QPainter(qimage)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            
            # 计算缩放因子 - 保持原始宽高比
            if default_size.width() > 0 and default_size.height() > 0:
                scale_x = render_width / default_size.width()
                scale_y = render_height / default_size.height()
                painter.scale(scale_x, scale_y)
            
            renderer.render(painter)
            painter.end()
            
            # 转换为RGBA8888格式
            if qimage.format() != QImage.Format_RGBA8888:
                qimage = qimage.convertToFormat(QImage.Format_RGBA8888)
            
            # 获取图像数据
            width = qimage.width()
            height = qimage.height()
            ptr = qimage.constBits()
            
            # 处理不同版本的PySide6
            if hasattr(ptr, 'tobytes'):
                img_data = ptr.tobytes()
            elif hasattr(ptr, 'asstring'):
                img_data = ptr.asstring()
            else:
                img_data = bytes(ptr)
            
            # 验证数据长度
            expected_len = width * height * 4  # RGBA = 4 bytes per pixel
            if len(img_data) < expected_len:
                warning(f"[ThumbnailManager] SVG图像数据长度不足: {len(img_data)} < {expected_len}")
                return None, False
            
            # 创建PIL图像
            img = Image.frombytes("RGBA", (width, height), img_data)
            
            return img, True
            
        except Exception as e:
            warning(f"[ThumbnailManager] 加载SVG失败: {file_path}, 错误: {e}")
            return None, False
    
    def clear_all_thumbnails(self) -> int:
        """
        清理所有缩略图缓存
        
        Returns:
            int: 删除的文件数量
        """
        try:
            import glob
            
            if not os.path.exists(self._thumb_dir):
                return 0
            
            thumbnail_files = glob.glob(os.path.join(self._thumb_dir, "*.png"))
            deleted_count = 0
            
            for file_path in thumbnail_files:
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except (OSError, IOError) as e:
                        debug(f"[ThumbnailManager] 删除缩略图文件失败 {file_path}: {e}")
            
            info(f"[ThumbnailManager] 已清理 {deleted_count} 个缩略图缓存文件")
            return deleted_count
            
        except Exception as e:
            error(f"[ThumbnailManager] 清理缩略图缓存失败: {e}")
            return 0
    
    def get_thumbnail_count(self) -> int:
        """
        获取当前缩略图数量
        
        Returns:
            int: 缩略图文件数量
        """
        try:
            import glob

            if not os.path.exists(self._thumb_dir):
                return 0

            thumbnail_files = glob.glob(os.path.join(self._thumb_dir, "*.png"))
            return len(thumbnail_files)

        except Exception as e:
            debug(f"获取缩略图数量失败: {e}")
            return 0


# 全局缩略图管理器实例
_thumbnail_manager = None


def get_thumbnail_manager(dpi_scale: float = 1.0) -> ThumbnailManager:
    """
    获取全局缩略图管理器实例
    
    Args:
        dpi_scale: DPI缩放因子
        
    Returns:
        ThumbnailManager: 缩略图管理器实例
    """
    global _thumbnail_manager
    if _thumbnail_manager is None:
        _thumbnail_manager = ThumbnailManager(dpi_scale)
    else:
        _thumbnail_manager.set_dpi_scale(dpi_scale)
    return _thumbnail_manager


def create_thumbnail(file_path: str, dpi_scale: float = 1.0, force_regenerate: bool = False) -> Optional[str]:
    """
    便捷函数：为文件创建缩略图
    
    Args:
        file_path: 文件路径
        dpi_scale: DPI缩放因子
        force_regenerate: 是否强制重新生成
        
    Returns:
        Optional[str]: 缩略图路径，失败返回None
    """
    manager = get_thumbnail_manager(dpi_scale)
    return manager.create_thumbnail(file_path, force_regenerate)


def get_thumbnail_path(file_path: str) -> str:
    """
    便捷函数：获取文件缩略图路径
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: 缩略图路径
    """
    manager = get_thumbnail_manager()
    return manager.get_thumbnail_path(file_path)


def has_thumbnail(file_path: str) -> bool:
    """
    便捷函数：检查文件是否已有缩略图
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否存在缩略图
    """
    manager = get_thumbnail_manager()
    return manager.has_thumbnail(file_path)


def is_media_file(file_path: str) -> bool:
    """
    便捷函数：判断文件是否为媒体文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        bool: 是否为媒体文件
    """
    manager = get_thumbnail_manager()
    return manager.is_media_file(file_path)


def clear_all_thumbnails() -> int:
    """
    便捷函数：清理所有缩略图缓存
    
    Returns:
        int: 删除的文件数量
    """
    manager = get_thumbnail_manager()
    return manager.clear_all_thumbnails()


# 模块导出
__all__ = [
    'ThumbnailManager',
    'get_thumbnail_manager',
    'create_thumbnail',
    'get_thumbnail_path',
    'has_thumbnail',
    'is_media_file',
    'clear_all_thumbnails',
]