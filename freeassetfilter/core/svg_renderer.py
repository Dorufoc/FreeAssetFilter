#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 MIT 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

独立的SVG图像渲染工具
提供高质量的SVG到QPixmap或QSvgWidget转换，确保正确处理RGBA通道
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPixmap, QImage
from PyQt5.QtSvg import QSvgRenderer, QSvgWidget
from PyQt5.QtWidgets import QWidget, QLabel
import os


class SvgRenderer:
    """
    SVG图像渲染工具类
    提供高质量的SVG到QPixmap或QSvgWidget转换，确保正确处理RGBA通道
    参考了custom_file_selector.py中_set_file_icon方法的实现
    """
    
    @staticmethod
    def render_svg_to_widget(icon_path, icon_size=120, dpi_scale=1.0):
        """
        将SVG文件渲染为QSvgWidget，这是最可靠的方式
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认120x120
            dpi_scale (float): DPI缩放因子，默认1.0
            
        Returns:
            QWidget: 渲染后的QSvgWidget或QLabel对象，确保透明度正确
        """
        # 应用DPI缩放因子到图标大小
        scaled_icon_size = int(icon_size * dpi_scale)
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回透明QLabel
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
            return label
        
        # 检查是否存在同名PNG图片
        png_path = os.path.splitext(icon_path)[0] + '.png'
        if os.path.exists(png_path):
            # 如果存在同名PNG，直接使用QLabel加载PNG
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setAlignment(Qt.AlignCenter)
            pixmap = QPixmap(png_path)
            if not pixmap.isNull():
                # 缩放PNG到合适大小
                scaled_pixmap = pixmap.scaled(scaled_icon_size, scaled_icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                # 如果PNG加载失败，返回透明背景
                pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
            return label
        
        # 检查icons文件夹内是否有同名PNG图片
        # 获取图标文件名（不包括路径和扩展名）
        icon_filename = os.path.basename(icon_path)
        icon_name = os.path.splitext(icon_filename)[0]
        
        # 构造icons文件夹路径
        # 确定当前文件所在目录，然后向上两级找到icons文件夹
        current_dir = os.path.dirname(__file__)
        icons_dir = os.path.join(current_dir, '..', 'icons')
        icons_dir = os.path.abspath(icons_dir)
        
        # 构造icons文件夹内的PNG路径
        icons_png_path = os.path.join(icons_dir, f'{icon_name}.png')
        if os.path.exists(icons_png_path):
            # 如果icons文件夹内存在同名PNG，直接加载PNG
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setAlignment(Qt.AlignCenter)
            pixmap = QPixmap(icons_png_path)
            if not pixmap.isNull():
                # 缩放PNG到合适大小
                scaled_pixmap = pixmap.scaled(scaled_icon_size, scaled_icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                # 如果PNG加载失败，返回透明背景
                pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
            return label
        
        try:
            # 读取SVG文件内容，预处理以确保兼容性
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 预处理SVG内容：将rgba颜色转换为十六进制格式
            import re
            
            def rgba_to_hex(match):
                rgba_values = match.group(1).split(',')
                # 去除空格并处理不同格式的rgba值
                r = rgba_values[0].strip()
                g = rgba_values[1].strip()
                b = rgba_values[2].strip()
                a = rgba_values[3].strip()
                
                # 处理百分比值
                if '%' in r:
                    r = float(r.replace('%', '')) * 2.55
                else:
                    r = float(r)
                
                if '%' in g:
                    g = float(g.replace('%', '')) * 2.55
                else:
                    g = float(g)
                
                if '%' in b:
                    b = float(b.replace('%', '')) * 2.55
                else:
                    b = float(b)
                
                # 处理alpha值（可能是0-1范围或0-100%范围）
                if '%' in a:
                    a = float(a.replace('%', '')) / 100
                else:
                    a = float(a)
                
                # 确保RGB值在0-255范围内
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                
                # 确保alpha值在0-1范围内
                a = max(0, min(1, a))
                
                # 将alpha值转换为十六进制（0-255）
                a = int(a * 255)
                
                # 转换为十六进制格式，使用小写字母，不足两位补零
                return f'#{int(r):02x}{int(g):02x}{int(b):02x}{a:02x}'
            
            # 替换CSS rgba格式为十六进制格式
            svg_content = re.sub(r'rgba\(([^\)]+)\)', rgba_to_hex, svg_content)
            
            # 使用QSvgWidget直接渲染SVG，这对透明度支持更好
            # 直接将SVG渲染在前端上，而不是使用转换的位图
            svg_widget = QSvgWidget()
            svg_widget.load(svg_content.encode('utf-8'))
            svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
            svg_widget.setStyleSheet("background: transparent;")
            return svg_widget
        except Exception as e:
            print(f"使用QSvgWidget加载SVG图标失败: {e}")
            # 如果QSvgWidget失败，回退到使用超分辨率渲染的位图
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, dpi_scale)
            
            # 将pixmap显示在QLabel中
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setAlignment(Qt.AlignCenter)
            label.setPixmap(pixmap)
            return label
    
    @staticmethod
    def _render_svg_to_label(icon_path, icon_size=120):
        """
        使用QSvgRenderer渲染SVG到QLabel，作为备选方案
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认120x120
            
        Returns:
            QLabel: 渲染后的QLabel对象，确保透明度正确
        """
        try:
            # 创建一个透明的QLabel
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(icon_size, icon_size)
            
            # 使用QSvgRenderer渲染
            svg_renderer = QSvgRenderer(icon_path)
            
            # 使用256x256的超分辨率进行渲染，确保图标清晰
            render_size = 256
            
            # 创建一个QImage，使用ARGB32_Premultiplied格式以支持正确的透明度
            image = QImage(render_size, render_size, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)  # 使用透明背景
            
            # 创建画家
            painter = QPainter(image)
            
            # 设置最高质量的渲染提示
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
            
            # 渲染SVG图标
            svg_renderer.render(painter)
            
            painter.end()
            
            # 将QImage转换为QPixmap，确保透明度正确
            pixmap = QPixmap.fromImage(image)
            
            if not pixmap.isNull():
                # 缩放PNG到合适大小，使用高质量缩放算法
                scaled_pixmap = pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                # 如果加载失败，创建一个默认的透明图标
                pixmap = QPixmap(icon_size, icon_size)
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
            
            return label
        except Exception as renderer_e:
            print(f"使用QSvgRenderer加载SVG图标失败: {renderer_e}")
            # 如果加载失败，创建一个默认的透明图标
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(icon_size, icon_size)
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
            return label
    
    @staticmethod
    def render_svg_to_pixmap(icon_path, icon_size=24, dpi_scale=1.0, icon_width=None, icon_height=None):
        """
        将SVG文件渲染为QPixmap，支持透明背景和高质量渲染
        
        注意：对于需要高质量渲染的场景，建议使用render_svg_to_widget方法返回QSvgWidget
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认24x24（当未指定width和height时使用）
            dpi_scale (float): DPI缩放因子，默认1.0
            icon_width (int, optional): 输出图标宽度，指定后按比例渲染
            icon_height (int, optional): 输出图标高度，指定后按比例渲染
            
        Returns:
            QPixmap: 渲染后的QPixmap对象，如果渲染失败返回透明像素图
        """
        # 应用DPI缩放因子到图标大小
        if icon_width is not None and icon_height is not None:
            # 如果同时指定了宽度和高度，按照指定尺寸渲染
            scaled_width = int(icon_width * dpi_scale)
            scaled_height = int(icon_height * dpi_scale)
        else:
            # 否则使用1:1比例
            scaled_size = int(icon_size * dpi_scale)
            scaled_width = scaled_size
            scaled_height = scaled_size
        
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回透明像素图
            pixmap = QPixmap(scaled_width, scaled_height)
            pixmap.fill(Qt.transparent)
            return pixmap
        
        try:
            # 优先使用SVG渲染，只有在SVG渲染失败时才考虑使用PNG
            # 对于所有尺寸的图标，都使用高质量渲染
            # 先使用QSvgRenderer创建一个足够大的pixmap（256x256），然后缩放
            # 这确保了在高DPI屏幕上的清晰度，实现超分辨率渲染
            svg_renderer = QSvgRenderer(icon_path)
            
            # 使用256x256的超分辨率进行渲染，确保图标清晰
            render_size = 256
            pixmap = QPixmap(render_size, render_size)
            pixmap.fill(Qt.transparent)
            
            painter = QPainter(pixmap)
            # 设置最高质量的渲染提示
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
            
            # 获取SVG的原始尺寸，确保正确渲染
            svg_size = svg_renderer.defaultSize()
            
            # 计算缩放因子，确保SVG在256x256的画布上居中显示且保持比例
            scale_factor = min(render_size / svg_size.width(), render_size / svg_size.height())
            
            # 计算居中位置
            x = (render_size - svg_size.width() * scale_factor) / 2
            y = (render_size - svg_size.height() * scale_factor) / 2
            
            # 保存当前坐标系
            painter.save()
            
            # 平移到居中位置并缩放
            painter.translate(x, y)
            painter.scale(scale_factor, scale_factor)
            
            # 渲染SVG到临时pixmap
            svg_renderer.render(painter)
            
            # 恢复坐标系
            painter.restore()
            painter.end()
            
            # 然后缩放回目标大小，使用高质量缩放算法
            # 如果指定了宽度和高度，按指定比例缩放；否则保持1:1比例
            final_pixmap = pixmap.scaled(scaled_width, scaled_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            if not final_pixmap.isNull():
                return final_pixmap
            else:
                # 如果缩放失败，返回原始渲染结果
                return pixmap
        except Exception as e:
            print(f"渲染SVG到QPixmap失败: {icon_path}, 错误: {e}")
        
        # 如果SVG渲染失败，再尝试使用PNG图片
        # 检查是否存在同名PNG图片
        png_path = os.path.splitext(icon_path)[0] + '.png'
        if os.path.exists(png_path):
            # 如果存在同名PNG，直接加载PNG
            pixmap = QPixmap(png_path)
            if not pixmap.isNull():
                # 缩放PNG到合适大小，使用高质量缩放算法
                scaled_pixmap = pixmap.scaled(scaled_width, scaled_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                return scaled_pixmap
        
        # 检查icons文件夹内是否有同名PNG图片
        # 获取图标文件名（不包括路径和扩展名）
        icon_filename = os.path.basename(icon_path)
        icon_name = os.path.splitext(icon_filename)[0]
        
        # 构造icons文件夹路径
        # 确定当前文件所在目录，然后向上两级找到icons文件夹
        current_dir = os.path.dirname(__file__)
        icons_dir = os.path.join(current_dir, '..', 'icons')
        icons_dir = os.path.abspath(icons_dir)
        
        # 构造icons文件夹内的PNG路径
        icons_png_path = os.path.join(icons_dir, f'{icon_name}.png')
        if os.path.exists(icons_png_path):
            # 如果icons文件夹内存在同名PNG，直接加载PNG
            pixmap = QPixmap(icons_png_path)
            if not pixmap.isNull():
                # 缩放PNG到合适大小，使用高质量缩放算法
                scaled_pixmap = pixmap.scaled(scaled_width, scaled_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                return scaled_pixmap
        
        # 如果所有方法都失败，返回透明像素图
        pixmap = QPixmap(scaled_width, scaled_height)
        pixmap.fill(Qt.transparent)
        return pixmap
    
    @staticmethod
    def render_svg_string_to_pixmap(svg_string, icon_size=24):
        """
        将SVG字符串渲染为QPixmap，支持透明背景和高质量渲染
        
        Args:
            svg_string (str): SVG内容字符串
            icon_size (int): 输出图标大小，默认24x24
            
        Returns:
            QPixmap: 渲染后的QPixmap对象，如果渲染失败返回透明像素图
        """
        if not svg_string:
            # 如果SVG字符串为空，返回透明像素图
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.fill(Qt.transparent)
            return pixmap
        
        try:
            # 预处理SVG内容：将rgba颜色转换为十六进制格式
            import re
            
            def rgba_to_hex(match):
                rgba_values = match.group(1).split(',')
                # 去除空格并处理不同格式的rgba值
                r = rgba_values[0].strip()
                g = rgba_values[1].strip()
                b = rgba_values[2].strip()
                a = rgba_values[3].strip()
                
                # 处理百分比值
                if '%' in r:
                    r = float(r.replace('%', '')) * 2.55
                else:
                    r = float(r)
                
                if '%' in g:
                    g = float(g.replace('%', '')) * 2.55
                else:
                    g = float(g)
                
                if '%' in b:
                    b = float(b.replace('%', '')) * 2.55
                else:
                    b = float(b)
                
                # 处理alpha值（可能是0-1范围或0-100%范围）
                if '%' in a:
                    a = float(a.replace('%', '')) / 100
                else:
                    a = float(a)
                
                # 确保RGB值在0-255范围内
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                
                # 确保alpha值在0-1范围内
                a = max(0, min(1, a))
                
                # 将alpha值转换为十六进制（0-255）
                a = int(a * 255)
                
                # 转换为十六进制格式，使用小写字母，不足两位补零
                return f'#{int(r):02x}{int(g):02x}{int(b):02x}{a:02x}'
            
            # 替换CSS rgba格式为十六进制格式
            processed_svg = re.sub(r'rgba\(([^\)]+)\)', rgba_to_hex, svg_string)
            
            # 使用预处理后的SVG内容创建渲染器
            svg_renderer = QSvgRenderer(processed_svg.encode('utf-8'))
            
            # 使用256x256的超分辨率进行渲染，确保图标清晰
            render_size = 256
            
            # 创建一个透明背景的QPixmap
            pixmap = QPixmap(render_size, render_size)
            pixmap.fill(Qt.transparent)
            
            # 创建画家，设置透明背景和高质量渲染
            painter = QPainter(pixmap)
            
            # 设置最高质量的渲染提示
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
            
            # 渲染SVG
            svg_renderer.render(painter)
            
            painter.end()
            
            # 然后缩放回目标大小，使用高质量缩放算法
            final_pixmap = pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            if not final_pixmap.isNull():
                return final_pixmap
        except Exception as e:
            print(f"渲染SVG字符串失败, 错误: {e}")
        
        # 如果所有方法都失败，返回透明像素图
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.transparent)
        return pixmap
