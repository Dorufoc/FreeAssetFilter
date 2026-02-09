#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

独立的照片查看器组件
提供图片查看、像素信息显示和缩放功能
"""

import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QLabel, QScrollArea, QGroupBox, QGridLayout,
    QMessageBox, QSizePolicy
)

from freeassetfilter.widgets.D_more_menu import D_MoreMenu
from PyQt5.QtGui import (
    QImage, QPixmap, QPainter, QPen, QColor, QCursor,
    QFont, QIcon
)
from PyQt5.QtCore import (
    Qt, QPoint, QRect, QSize, QTimer, pyqtSignal, QMimeData, QUrl,
    QThread
)

# PIL支持已移除以提高性能

from freeassetfilter.widgets.smooth_scroller import SmoothScroller


class RawProcessor(QThread):
    """
    RAW文件异步处理器
    """
    processing_complete = pyqtSignal(QImage, str)  # 处理完成信号
    processing_failed = pyqtSignal(str)  # 处理失败信号
    
    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path
    
    def run(self):
        try:
            import rawpy
            import numpy as np
            
            file_size = os.path.getsize(self.image_path)
            large_file_threshold = 10 * 1024 * 1024
            
            if file_size > large_file_threshold:
                with rawpy.imread(self.image_path) as raw:
                    rgb = raw.postprocess(
                        half_size=True,
                        output_bps=8,
                        no_auto_bright=True,
                        use_camera_wb=True,
                        gamma=(2.222, 4.5)
                    )
            else:
                with rawpy.imread(self.image_path) as raw:
                    rgb = raw.postprocess(
                        output_bps=8,
                        use_camera_wb=True
                    )
            
            from PyQt5.QtGui import QGuiApplication
            device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
            
            height, width, channel = rgb.shape
            bytes_per_line = 3 * width
            bgr = np.zeros((height, width, 3), dtype=np.uint8)
            bgr[:, :, 0] = rgb[:, :, 2]
            bgr[:, :, 1] = rgb[:, :, 1]
            bgr[:, :, 2] = rgb[:, :, 0]
            
            qimage = QImage(bgr.data, width, height, bytes_per_line, QImage.Format_RGB888)
            self.processing_complete.emit(qimage, self.image_path)
        except Exception as e:
            print(f"加载RAW图片时出错: {e}")
            self.processing_failed.emit(f"加载RAW图片时出错: {e}")


class IcoProcessor(QThread):
    """
    ICO文件异步处理器
    将ICO格式转换为位图进行预览
    """
    processing_complete = pyqtSignal(QImage, str)
    processing_failed = pyqtSignal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path

    def run(self):
        """
        处理ICO文件，提取最高分辨率的图标并转换为QImage
        优先使用PIL库解析，如不可用则使用Windows API
        """
        try:
            # 首先尝试使用PIL库解析ICO文件
            try:
                image = self._load_with_pil()
                if image and not image.isNull():
                    self.processing_complete.emit(image, self.image_path)
                    return
            except ImportError:
                pass  # PIL不可用，使用备用方案

            # 使用Windows API加载ICO文件
            image = self._load_with_windows_api()
            if image and not image.isNull():
                self.processing_complete.emit(image, self.image_path)
                return

            raise Exception("无法从ICO文件创建图像")

        except Exception as e:
            print(f"加载ICO文件时出错: {e}")
            import traceback
            traceback.print_exc()
            self.processing_failed.emit(f"加载ICO文件时出错: {e}")

    def _load_with_pil(self):
        """
        使用PIL库加载ICO文件
        返回QImage对象
        """
        from PIL import Image

        # 打开ICO文件
        img = Image.open(self.image_path)

        # ICO文件可能包含多个尺寸，选择最大的那个
        if hasattr(img, 'info') and 'sizes' in img.info:
            sizes = img.info['sizes']
            if sizes:
                # 选择最大尺寸
                max_size = max(sizes, key=lambda s: s[0] * s[1])
                img.size = max_size
                img.load()

        # 转换为RGBA模式以支持透明通道
        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        # 获取图像尺寸
        width, height = img.size

        # 将图像数据转换为字节
        img_bytes = img.tobytes()

        # 创建QImage
        bytes_per_line = width * 4
        qimage = QImage(img_bytes, width, height, bytes_per_line, QImage.Format_RGBA8888)

        # 复制数据以确保内存安全
        return qimage.copy()

    def _load_with_windows_api(self):
        """
        使用Windows API加载ICO文件
        返回QImage对象
        """
        import ctypes
        from ctypes import windll, byref, sizeof
        from ctypes.wintypes import DWORD, UINT, HANDLE, LPCWSTR, HICON

        # 定义Windows API函数
        ExtractIconExW = windll.shell32.ExtractIconExW
        ExtractIconExW.argtypes = [LPCWSTR, ctypes.c_int, ctypes.POINTER(HICON), ctypes.POINTER(HICON), UINT]
        ExtractIconExW.restype = UINT

        DestroyIcon = windll.user32.DestroyIcon
        DestroyIcon.argtypes = [HICON]
        DestroyIcon.restype = ctypes.c_bool

        # 获取图标数量
        icon_count = ExtractIconExW(self.image_path, -1, None, None, 0)

        if icon_count == 0:
            raise Exception("ICO文件中未找到图标")

        # 提取第一个图标（通常是最高分辨率的）
        large_icon = HICON()
        small_icon = HICON()

        extracted = ExtractIconExW(self.image_path, 0, byref(large_icon), byref(small_icon), 1)

        if extracted == 0 or not large_icon:
            raise Exception("无法提取ICO图标")

        try:
            # 使用icon_utils中的函数将HICON转换为QPixmap
            from freeassetfilter.utils.icon_utils import hicon_to_pixmap

            # 获取图标信息以确定尺寸
            class ICONINFO(ctypes.Structure):
                _fields_ = [
                    ("fIcon", ctypes.c_bool),
                    ("xHotspot", ctypes.c_uint),
                    ("yHotspot", ctypes.c_uint),
                    ("hbmMask", ctypes.c_void_p),
                    ("hbmColor", ctypes.c_void_p)
                ]

            class BITMAP(ctypes.Structure):
                _fields_ = [
                    ("bmType", DWORD),
                    ("bmWidth", DWORD),
                    ("bmHeight", DWORD),
                    ("bmWidthBytes", DWORD),
                    ("bmPlanes", ctypes.c_ushort),
                    ("bmBitsPixel", ctypes.c_ushort),
                    ("bmBits", ctypes.c_void_p)
                ]

            GetIconInfo = windll.user32.GetIconInfo
            GetIconInfo.argtypes = [HICON, ctypes.POINTER(ICONINFO)]
            GetIconInfo.restype = ctypes.c_bool

            GetObjectW = windll.gdi32.GetObjectW
            GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            GetObjectW.restype = ctypes.c_int

            DeleteObject = windll.gdi32.DeleteObject
            DeleteObject.argtypes = [ctypes.c_void_p]
            DeleteObject.restype = ctypes.c_bool

            icon_info = ICONINFO()
            if GetIconInfo(large_icon, byref(icon_info)):
                bmp = BITMAP()
                if GetObjectW(icon_info.hbmColor, sizeof(bmp), byref(bmp)) > 0:
                    icon_size = bmp.bmWidth
                else:
                    icon_size = 256

                # 释放位图资源
                if icon_info.hbmMask:
                    DeleteObject(icon_info.hbmMask)
                if icon_info.hbmColor:
                    DeleteObject(icon_info.hbmColor)
            else:
                icon_size = 256

            # 转换为QPixmap
            pixmap = hicon_to_pixmap(large_icon, icon_size, None, 1.0)

            if pixmap and not pixmap.isNull():
                image = pixmap.toImage()
                # 确保图像格式为ARGB32
                if image.format() != QImage.Format_ARGB32:
                    image = image.convertToFormat(QImage.Format_ARGB32)
                return image
            else:
                raise Exception("HICON转换为QPixmap失败")

        finally:
            # 释放图标资源
            if large_icon:
                DestroyIcon(large_icon)
            if small_icon:
                DestroyIcon(small_icon)


class HeifAvifProcessor(QThread):
    """
    HEIC/AVIF文件异步处理器
    """
    processing_complete = pyqtSignal(QImage, str)
    processing_failed = pyqtSignal(str)

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path
    
    def run(self):
        try:
            from PIL import Image
            import numpy as np
            
            try:
                import pillow_avif
            except ImportError:
                pass
            
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass
            
            img = Image.open(self.image_path)
            
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
            
            file_size = os.path.getsize(self.image_path)
            large_file_threshold = 20 * 1024 * 1024
            
            if file_size > large_file_threshold:
                max_dimension = 2048
                if img.width > max_dimension or img.height > max_dimension:
                    ratio = min(max_dimension / img.width, max_dimension / img.height)
                    new_width = int(img.width * ratio)
                    new_height = int(img.height * ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            img_array = np.array(img)
            height, width = img_array.shape[:2]
            
            img_bytes = img_array.tobytes()
            
            if img.mode == 'RGBA':
                qimage = QImage(
                    img_bytes, width, height,
                    width * 4, QImage.Format_RGBA8888
                )
            else:
                qimage = QImage(
                    img_bytes, width, height,
                    width * 3, QImage.Format_RGB888
                )
            
            if qimage.isNull():
                raise Exception("QImage创建失败")
            
            self.processing_complete.emit(qimage, self.image_path)
        except Exception as e:
            print(f"加载HEIC/AVIF图片时出错: {e}")
            import traceback
            traceback.print_exc()
            self.processing_failed.emit(f"加载HEIC/AVIF图片时出错: {e}")


class ImageWidget(QWidget):
    """
    图片显示部件，支持缩放、像素信息显示等功能
    """
    pixel_info_changed = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        
        # 不再需要获取设备像素比，Qt会自动处理
        
        # 初始化所有属性，确保在使用前都被定义
        self.original_image = None
        self.scaled_image = None
        self.pixmap = None
        self._physical_image_width = 0  # 保存缩放后的物理像素宽度
        self._physical_image_height = 0  # 保存缩放后的物理像素高度
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.is_panning = False
        self.last_mouse_pos = QPoint()
        self.pan_offset = QPoint()
        self.mouse_pos = QPoint()
        self.current_file_path = ""
        
        # RAW处理器
        self.raw_processor = None
        self.heif_avif_processor = None
        self.ico_processor = None

        # 像素信息
        self.pixel_info = {
            'x': 0, 'y': 0,
            'r': 0, 'g': 0, 'b': 0,
            'hex': '#000000'
        }
    
    def _on_ico_processing_complete(self, qimage, image_path):
        """
        ICO文件处理完成槽函数
        """
        if not qimage.isNull():
            self.current_file_path = image_path
            self.original_image = qimage
            self.pan_offset = QPoint()
            QTimer.singleShot(100, self._delayed_fit_scale)

        self.ico_processor = None

    def _on_ico_processing_failed(self, error_msg):
        """
        ICO文件处理失败槽函数
        """
        print(error_msg)
        self.ico_processor = None

    def _on_heif_avif_processing_complete(self, qimage, image_path):
        """
        HEIC/AVIF文件处理完成槽函数
        """
        if not qimage.isNull():
            self.current_file_path = image_path
            self.original_image = qimage
            self.pan_offset = QPoint()
            QTimer.singleShot(100, self._delayed_fit_scale)

        self.heif_avif_processor = None

    def _on_heif_avif_processing_failed(self, error_msg):
        """
        HEIC/AVIF文件处理失败槽函数
        """
        print(error_msg)
        self.heif_avif_processor = None
    
    def _on_raw_processing_complete(self, qimage, image_path):
        """
        RAW文件处理完成槽函数
        """
        if not qimage.isNull():
            # 保存当前文件路径和图像
            self.current_file_path = image_path
            self.original_image = qimage
            
            # 重置平移参数
            self.pan_offset = QPoint()
            
            # 使用QTimer延迟执行自适应缩放，确保图片渲染完成且布局稳定
            QTimer.singleShot(100, self._delayed_fit_scale)
        
        # 清理处理器
        self.raw_processor = None
    
    def _on_raw_processing_failed(self, error_msg):
        """
        RAW文件处理失败槽函数
        """
        print(error_msg)
        self.raw_processor = None
    
    def set_image(self, image_path):
        """
        设置要显示的图片
        
        Args:
            image_path (str): 图片文件路径
        
        Returns:
            bool: 是否成功启动加载
        """
        try:
            if not os.path.exists(image_path):
                return False
            
            file_ext = os.path.splitext(image_path)[1].lower()
            raw_formats = ['.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf']
            heif_avif_formats = ['.heic', '.heif', '.avif']
            ico_formats = ['.ico', '.icon']

            if file_ext in raw_formats:
                if self.raw_processor is not None and self.raw_processor.isRunning():
                    self.raw_processor.quit()
                    self.raw_processor.wait()

                self.raw_processor = RawProcessor(image_path)
                self.raw_processor.processing_complete.connect(self._on_raw_processing_complete)
                self.raw_processor.processing_failed.connect(self._on_raw_processing_failed)
                self.raw_processor.start()

                return True
            elif file_ext in heif_avif_formats:
                if self.heif_avif_processor is not None and self.heif_avif_processor.isRunning():
                    self.heif_avif_processor.quit()
                    self.heif_avif_processor.wait()

                self.heif_avif_processor = HeifAvifProcessor(image_path)
                self.heif_avif_processor.processing_complete.connect(self._on_heif_avif_processing_complete)
                self.heif_avif_processor.processing_failed.connect(self._on_heif_avif_processing_failed)
                self.heif_avif_processor.start()

                return True
            elif file_ext in ico_formats:
                if self.ico_processor is not None and self.ico_processor.isRunning():
                    self.ico_processor.quit()
                    self.ico_processor.wait()

                self.ico_processor = IcoProcessor(image_path)
                self.ico_processor.processing_complete.connect(self._on_ico_processing_complete)
                self.ico_processor.processing_failed.connect(self._on_ico_processing_failed)
                self.ico_processor.start()

                return True
            else:
                self.original_image = QImage(image_path)
            
            if not self.original_image.isNull():
                self.current_file_path = image_path
                self.pan_offset = QPoint()
                
                QTimer.singleShot(100, self._delayed_fit_scale)
                return True
            return False
        except Exception as e:
            print(f"加载图片时出错: {e}")
            return False
    
    def _delayed_fit_scale(self):
        """
        延迟执行自适应缩放，确保图片渲染完成且布局稳定
        """
        try:
            # 计算自适应缩放因子
            self.calculate_fit_scale()
            self.update_image()
            self.update()
        except Exception as e:
            print(f"延迟自适应缩放时出错: {e}")
    
    def calculate_fit_scale(self):
        """
        计算自适应缩放因子，使图片完全显示在控件区域内
        使用"适应"模式：图片完整显示，可能留白
        """
        try:
            if self.original_image:
                from PyQt5.QtGui import QGuiApplication
                device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
                
                if hasattr(self.parent(), 'viewport') and self.parent().viewport():
                    viewport_size = self.parent().viewport().size()
                else:
                    viewport_size = self.size()
                
                available_logical_width = viewport_size.width()
                available_logical_height = viewport_size.height()
                
                image_width = self.original_image.width()
                image_height = self.original_image.height()
                
                if image_width > 0 and image_height > 0:
                    width_ratio = available_logical_width / image_width
                    height_ratio = available_logical_height / image_height
                    
                    self.scale_factor = min(width_ratio, height_ratio)
                    
                    self.scale_factor = max(self.scale_factor, self.min_scale)
        except Exception as e:
            print(f"计算自适应缩放时出错: {e}")
            self.scale_factor = 1.0
    
    def update_image(self):
        """
        更新缩放后的图片，使用高DPI优化处理
        """
        try:
            if self.original_image:
                from PyQt5.QtGui import QGuiApplication
                device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
                
                if hasattr(self.parent(), 'viewport') and self.parent().viewport():
                    viewport_size = self.parent().viewport().size()
                else:
                    viewport_size = self.size()
                
                available_logical_width = viewport_size.width()
                available_logical_height = viewport_size.height()
                
                original_width = self.original_image.width()
                original_height = self.original_image.height()
                
                logical_width = int(original_width * self.scale_factor)
                logical_height = int(original_height * self.scale_factor)
                physical_width = int(logical_width * device_pixel_ratio)
                physical_height = int(logical_height * device_pixel_ratio)
                
                self.scaled_image = self.original_image.scaled(
                    physical_width, physical_height, 
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                
                self.pixmap = QPixmap.fromImage(self.scaled_image)
                self.pixmap.setDevicePixelRatio(device_pixel_ratio)
                
                self._physical_image_width = physical_width
                self._physical_image_height = physical_height
                
                self.setMinimumSize(0, 0)
        except Exception as e:
            print(f"更新图片时出错: {e}")
    
    def paintEvent(self, event):
        """
        绘制图片
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        app = QApplication.instance()
        base_color = "#212121"
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
        
        if base_color.startswith('#'):
            r = int(base_color[1:3], 16)
            g = int(base_color[3:5], 16)
            b = int(base_color[5:7], 16)
            painter.fillRect(self.rect(), QColor(r, g, b))
        else:
            painter.fillRect(self.rect(), QColor(40, 40, 40))
        
        if self.pixmap and self.scaled_image:
            try:
                # 获取设备像素比
                from PyQt5.QtGui import QGuiApplication
                device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
                
                # 计算图片的逻辑像素尺寸
                logical_image_width = self._physical_image_width // device_pixel_ratio
                logical_image_height = self._physical_image_height // device_pixel_ratio
                
                # pan_offset 表示图片中心相对于视口中心的偏移
                # 图片左上角 = 视口中心 - 图片尺寸/2 + pan_offset
                rect = self.rect()
                image_left = rect.center().x() - logical_image_width // 2 + self.pan_offset.x()
                image_top = rect.center().y() - logical_image_height // 2 + self.pan_offset.y()
                
                image_rect = QRect(image_left, image_top, logical_image_width, logical_image_height)
                
                # 绘制图片
                painter.drawPixmap(image_rect, self.pixmap)
                
                # 绘制当前鼠标位置的十字线
                if self.is_valid_pixel_position(self.mouse_pos):
                    pen = QPen(QColor(255, 255, 255), 1, Qt.DotLine)
                    pen.setWidth(1)
                    painter.setPen(pen)
                    
                    # 十字线
                    painter.drawLine(
                        image_rect.left(), self.mouse_pos.y(),
                        image_rect.right(), self.mouse_pos.y()
                    )
                    painter.drawLine(
                        self.mouse_pos.x(), image_rect.top(),
                        self.mouse_pos.x(), image_rect.bottom()
                    )
            except Exception as e:
                print(f"绘制图片时出错: {e}")
        painter.end()
    
    def mousePressEvent(self, event):
        """
        鼠标按下事件
        """
        try:
            if event.button() == Qt.LeftButton:
                # 左键拖动图片
                self.is_panning = True
                self.last_mouse_pos = event.pos()
                self.setCursor(QCursor(Qt.ClosedHandCursor))
                # 如果点击在有效像素位置，更新像素信息
                if self.is_valid_pixel_position(event.pos()):
                    self.update_pixel_info(event.pos())
        except Exception as e:
            print(f"处理鼠标按下事件时出错: {e}")
    
    def mouseReleaseEvent(self, event):
        """
        鼠标释放事件
        """
        try:
            if event.button() == Qt.LeftButton:
                self.is_panning = False
                self.setCursor(QCursor(Qt.ArrowCursor))
        except Exception as e:
            print(f"处理鼠标释放事件时出错: {e}")
    
    def mouseMoveEvent(self, event):
        """
        鼠标移动事件
        """
        try:
            self.mouse_pos = event.pos()
            
            if self.is_panning:
                # 处理平移
                delta = event.pos() - self.last_mouse_pos
                self.pan_offset += delta
                self.last_mouse_pos = event.pos()
            else:
                # 更新像素信息
                if self.is_valid_pixel_position(self.mouse_pos):
                    self.update_pixel_info(self.mouse_pos)
            
            # 实时刷新界面，确保十字线跟随鼠标移动
            self.update()
        except Exception as e:
            print(f"处理鼠标移动事件时出错: {e}")
    
    def wheelEvent(self, event):
        """
        鼠标滚轮事件（缩放）
        """
        try:
            # 无论鼠标是否在图片上，都可以进行缩放
            if self.original_image and self.scaled_image:
                # 获取设备像素比
                from PyQt5.QtGui import QGuiApplication
                device_pixel_ratio = QGuiApplication.primaryScreen().devicePixelRatio()
                
                # 计算图片的逻辑像素尺寸
                rect = self.rect()
                logical_image_width = self._physical_image_width // device_pixel_ratio
                logical_image_height = self._physical_image_height // device_pixel_ratio
                
                # 计算图片区域（与paintEvent一致）
                image_left = rect.center().x() - logical_image_width // 2 + self.pan_offset.x()
                image_top = rect.center().y() - logical_image_height // 2 + self.pan_offset.y()
                image_rect = QRect(image_left, image_top, logical_image_width, logical_image_height)
                
                # 计算鼠标在图片中的位置（如果鼠标在图片外，使用图片中心）
                if image_rect.contains(event.pos()):
                    mouse_in_image = event.pos() - image_rect.topLeft()
                    # 转换为原始图片坐标
                    mouse_in_original_x = mouse_in_image.x() / logical_image_width * self.original_image.width()
                    mouse_in_original_y = mouse_in_image.y() / logical_image_height * self.original_image.height()
                    mouse_in_original = QPoint(int(mouse_in_original_x), int(mouse_in_original_y))
                else:
                    # 鼠标在图片外，使用图片中心作为缩放点
                    mouse_in_original = QPoint(self.original_image.width() // 2, self.original_image.height() // 2)
                    
                # 缩放
                delta = 1.1 if event.angleDelta().y() > 0 else 0.9
                new_scale = self.scale_factor * delta
                
                # 限制缩放范围
                if self.min_scale <= new_scale <= self.max_scale:
                    self.scale_factor = new_scale
                    self.update_image()
                    
                    # 重新计算缩放后的图片尺寸
                    new_logical_width = int(self.original_image.width() * self.scale_factor)
                    new_logical_height = int(self.original_image.height() * self.scale_factor)
                    
                    # 计算新的图片左上角位置
                    new_image_left = rect.center().x() - new_logical_width // 2 + self.pan_offset.x()
                    new_image_top = rect.center().y() - new_logical_height // 2 + self.pan_offset.y()
                    new_image_rect = QRect(new_image_left, new_image_top, new_logical_width, new_logical_height)
                    
                    # 计算缩放后鼠标在图片中的位置
                    new_mouse_in_image_x = mouse_in_original_x / self.original_image.width() * new_logical_width
                    new_mouse_in_image_y = mouse_in_original_y / self.original_image.height() * new_logical_height
                    new_mouse_in_image = QPoint(int(new_mouse_in_image_x), int(new_mouse_in_image_y))
                    
                    # 调整pan_offset，使鼠标指向的点保持不变
                    self.pan_offset += (event.pos() - new_image_rect.topLeft()) - new_mouse_in_image
                    
                    self.update()
        except Exception as e:
            print(f"处理鼠标滚轮事件时出错: {e}")
        
        # 阻止滚轮事件传递给滚动条
        event.accept()
    
    def mouseDoubleClickEvent(self, event):
        """
        鼠标双击事件（重置缩放）
        """
        try:
            if event.button() == Qt.LeftButton:
                self.reset_view()
        except Exception as e:
            print(f"处理鼠标双击事件时出错: {e}")
    
    def resizeEvent(self, event):
        """
        窗口大小改变事件，重新计算缩放
        """
        super().resizeEvent(event)
        if self.original_image:
            self.calculate_fit_scale()
            self.update_image()
            self.update()
    
    def contextMenuEvent(self, event):
        """
        右键菜单事件
        """
        try:
            if not hasattr(self, '_context_menu'):
                self._context_menu = D_MoreMenu(parent=None)
                self._context_menu.itemClicked.connect(self._on_context_menu_clicked)

            # 构建菜单项
            items = [{"text": "复制色度值", "data": "copy_color"}]

            if self.current_file_path:
                items.extend([
                    {"text": "复制文件路径", "data": "copy_path"},
                    {"text": "复制文件名", "data": "copy_name"},
                    {"text": "复制文件", "data": "copy_file"},
                ])

            self._context_menu.set_items(items)
            self._context_menu.popup(event.globalPos())
        except Exception as e:
            print(f"显示右键菜单时出错: {e}")

    def _on_context_menu_clicked(self, data):
        """
        右键菜单项点击事件处理

        Args:
            data: 菜单项数据
        """
        if data == "copy_color":
            self.copy_color_value()
        elif data == "copy_path":
            self.copy_file_path()
        elif data == "copy_name":
            self.copy_file_name()
        elif data == "copy_file":
            self.copy_file()
    
    def copy_color_value(self):
        """
        复制当前像素的色度值
        """
        try:
            clipboard = QApplication.clipboard()
            color_value = f"RGB({self.pixel_info['r']}, {self.pixel_info['g']}, {self.pixel_info['b']})\n"
            color_value += f"HEX: {self.pixel_info['hex']}\n"
            color_value += f"坐标: ({self.pixel_info['x']}, {self.pixel_info['y']})"
            clipboard.setText(color_value)
        except Exception as e:
            print(f"复制色度值时出错: {e}")
    
    def copy_file_path(self):
        """
        复制当前文件的完整路径
        """
        try:
            if self.current_file_path:
                clipboard = QApplication.clipboard()
                clipboard.setText(self.current_file_path)
        except Exception as e:
            print(f"复制文件路径时出错: {e}")
    
    def copy_file_name(self):
        """
        复制当前文件的文件名
        """
        try:
            if self.current_file_path:
                clipboard = QApplication.clipboard()
                clipboard.setText(os.path.basename(self.current_file_path))
        except Exception as e:
            print(f"复制文件名时出错: {e}")
    
    def copy_file(self):
        """
        复制文件本身
        """
        try:
            if self.current_file_path and os.path.exists(self.current_file_path):
                # 这里只是复制文件路径到剪贴板
                # 实际复制文件需要使用 QMimeData 和 QClipboard.setMimeData
                clipboard = QApplication.clipboard()
                mime_data = QMimeData()
                url = QUrl.fromLocalFile(self.current_file_path)
                mime_data.setUrls([url])
                clipboard.setMimeData(mime_data)
        except Exception as e:
            print(f"复制文件时出错: {e}")
    
    def is_valid_pixel_position(self, pos):
        """
        检查给定位置是否在有效像素范围内
        """
        try:
            if not self.original_image or not self.scaled_image:
                return False
            
            # 计算图片显示区域（使用逻辑像素）
            rect = self.rect()
            
            # 直接使用逻辑像素尺寸，不再需要考虑设备像素比
            logical_image_width = self.scaled_image.width()
            logical_image_height = self.scaled_image.height()
            
            image_rect = QRect(
                rect.center().x() - logical_image_width // 2 + self.pan_offset.x(),
                rect.center().y() - logical_image_height // 2 + self.pan_offset.y(),
                logical_image_width,
                logical_image_height
            )
            
            return image_rect.contains(pos)
        except Exception as e:
            print(f"检查像素位置时出错: {e}")
            return False
    
    def update_pixel_info(self, pos):
        """
        更新鼠标位置的像素信息
        """
        try:
            if self.original_image and self.scaled_image and self.is_valid_pixel_position(pos):
                # 计算图片显示区域（使用逻辑像素）
                rect = self.rect()
                
                # 直接使用逻辑像素尺寸，不再需要考虑设备像素比
                logical_image_width = self.scaled_image.width()
                logical_image_height = self.scaled_image.height()
                
                image_rect = QRect(
                    rect.center().x() - logical_image_width // 2 + self.pan_offset.x(),
                    rect.center().y() - logical_image_height // 2 + self.pan_offset.y(),
                    logical_image_width,
                    logical_image_height
                )
                
                # 计算鼠标在逻辑像素图片中的位置
                mouse_in_logical_image = pos - image_rect.topLeft()
                
                # 转换为原始图片坐标
                mouse_in_original = mouse_in_logical_image / self.scale_factor
                
                # 获取像素颜色
                x = int(mouse_in_original.x())
                y = int(mouse_in_original.y())
                
                if 0 <= x < self.original_image.width() and 0 <= y < self.original_image.height():
                    color = self.original_image.pixelColor(x, y)
                    
                    # 更新像素信息
                    self.pixel_info = {
                        'x': x,
                        'y': y,
                        'r': color.red(),
                        'g': color.green(),
                        'b': color.blue(),
                        'hex': color.name()
                    }
                    
                    # 发送信号
                    self.pixel_info_changed.emit(self.pixel_info)
        except Exception as e:
            print(f"更新像素信息时出错: {e}")
    
    def reset_view(self):
        """
        重置视图（恢复自适应缩放状态）
        """
        try:
            self.pan_offset = QPoint()
            self.calculate_fit_scale()
            self.update_image()
            self.update()
        except Exception as e:
            print(f"重置视图时出错: {e}")
    
    def get_pixel_info(self):
        """
        获取当前像素信息
        """
        return self.pixel_info


class PhotoViewer(QWidget):
    """
    照片查看器组件
    提供图片查看、缩放、平移等功能
    """
    
    def __init__(self, parent=None):
        """
        初始化照片查看器
        
        Args:
            parent: 父窗口部件
        """
        super().__init__(parent)
        
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QFont
        app = QApplication.instance()
        
        self.global_font = getattr(app, 'global_font', QFont())
        self.dpi_scale = getattr(app, 'dpi_scale_factor', 1.0)
        
        self.setFont(self.global_font)
        
        self.image_widget = None
        self.scroll_area = None
        
        self.setWindowTitle("照片查看器")
        
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        scaled_min_width = int(100 * self.dpi_scale)
        scaled_min_height = int(100 * self.dpi_scale)
        self.setMinimumSize(scaled_min_width, scaled_min_height)
        
        self.init_ui()
    
    def init_ui(self):
        """
        初始化用户界面
        """
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # 设置整体背景色
        app = QApplication.instance()
        base_color = "#212121"
        if hasattr(app, 'settings_manager'):
            base_color = app.settings_manager.get_setting("appearance.colors.base_color", "#212121")
        self.setStyleSheet(f"background-color: {base_color};")
        
        # 1. 图片显示区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"background-color: {base_color};")
        
        self.image_widget = ImageWidget()
        self.scroll_area.setWidget(self.image_widget)
        
        SmoothScroller.apply_to_scroll_area(self.scroll_area)
        
        main_layout.addWidget(self.scroll_area, 1)
    
    def open_file(self):
        """
        打开图片文件
        """
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "打开图片文件", "", 
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;所有文件 (*)"
            )
            
            if file_path:
                if self.image_widget.set_image(file_path):
                    # 更新窗口标题
                    self.setWindowTitle(f"照片查看器 - {os.path.basename(file_path)}")
                else:
                    # 图片加载失败
                    QMessageBox.warning(self, "错误", "无法加载图片文件")
        except Exception as e:
            print(f"打开文件时出错: {e}")
            QMessageBox.warning(self, "错误", f"打开文件时出错: {str(e)}")
    
    def reset_view(self):
        """
        重置视图
        """
        try:
            self.image_widget.reset_view()
        except Exception as e:
            print(f"重置视图时出错: {e}")
    
    def load_image_from_path(self, image_path):
        """
        从外部路径加载图片
        
        Args:
            image_path (str): 图片文件路径
        
        Returns:
            bool: 是否成功加载图片
        """
        try:
            if self.image_widget.set_image(image_path):
                # 更新窗口标题
                self.setWindowTitle(f"照片查看器 - {os.path.basename(image_path)}")
                return True
            return False
        except Exception as e:
            print(f"从路径加载图片时出错: {e}")
            return False
    
    def set_file(self, file_path):
        """
        设置要显示的图片文件
        
        Args:
            file_path (str): 图片文件路径
        
        Returns:
            bool: 是否成功加载图片
        """
        return self.load_image_from_path(file_path)


# 命令行参数支持
if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PhotoViewer()
    
    # 如果提供了图片路径参数，直接加载
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        viewer.load_image_from_path(image_path)
    
    viewer.show()
    sys.exit(app.exec_())