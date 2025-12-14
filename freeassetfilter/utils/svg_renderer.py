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
    def render_svg_to_widget(icon_path, icon_size=120):
        """
        将SVG文件渲染为QSvgWidget，这是最可靠的方式
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认120x120
            
        Returns:
            QWidget: 渲染后的QSvgWidget或QLabel对象，确保透明度正确
        """
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回透明QLabel
            label = QLabel()
            label.setFixedSize(icon_size, icon_size)
            pixmap = QPixmap(icon_size, icon_size)
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
            svg_widget = QSvgWidget()
            svg_widget.load(svg_content.encode('utf-8'))
            svg_widget.setFixedSize(icon_size, icon_size)
            svg_widget.setStyleSheet("background: transparent;")
            return svg_widget
        except Exception as e:
            print(f"使用QSvgWidget加载SVG图标失败: {e}")
            # 如果QSvgWidget失败，回退到QSvgRenderer
            return SvgRenderer._render_svg_to_label(icon_path, icon_size)
    
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
            
            # 创建一个QImage，使用ARGB32_Premultiplied格式以支持正确的透明度
            image = QImage(icon_size, icon_size, QImage.Format_ARGB32_Premultiplied)
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
                label.setPixmap(pixmap)
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
    def render_svg_to_pixmap(icon_path, icon_size=24):
        """
        将SVG文件渲染为QPixmap，支持透明背景和高质量渲染
        
        注意：对于需要高质量渲染的场景，建议使用render_svg_to_widget方法返回QSvgWidget
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认24x24
            
        Returns:
            QPixmap: 渲染后的QPixmap对象，如果渲染失败返回透明像素图
        """
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回透明像素图
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.fill(Qt.transparent)
            return pixmap
        
        try:
            # 对于小尺寸图标（如24x24），可以直接使用QPixmap渲染
            # 这是因为小尺寸图标通常不包含复杂的半透明效果
            if icon_size <= 32:
                # 使用QSvgRenderer直接渲染到QPixmap
                svg_renderer = QSvgRenderer(icon_path)
                pixmap = QPixmap(icon_size, icon_size)
                pixmap.fill(Qt.transparent)
                
                from PyQt5.QtGui import QPainter
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                svg_renderer.render(painter)
                painter.end()
                
                if not pixmap.isNull():
                    return pixmap
            else:
                # 对于大尺寸图标，先使用QSvgWidget渲染，然后将其转换为QPixmap
                # 这是确保半透明效果正确的关键
                svg_widget = SvgRenderer.render_svg_to_widget(icon_path, icon_size)
                
                # 将QSvgWidget转换为QPixmap
                pixmap = QPixmap(icon_size, icon_size)
                pixmap.fill(Qt.transparent)
                
                # 渲染QSvgWidget到QPixmap
                svg_widget.render(pixmap)
                
                if not pixmap.isNull():
                    return pixmap
        except Exception as e:
            print(f"渲染SVG到QPixmap失败: {icon_path}, 错误: {e}")
        
        # 如果所有方法都失败，返回透明像素图
        pixmap = QPixmap(icon_size, icon_size)
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
            
            # 创建一个透明背景的QPixmap
            pixmap = QPixmap(icon_size, icon_size)
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
            
            if not pixmap.isNull():
                return pixmap
        except Exception as e:
            print(f"渲染SVG字符串失败, 错误: {e}")
        
        # 如果所有方法都失败，返回透明像素图
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.transparent)
        return pixmap
