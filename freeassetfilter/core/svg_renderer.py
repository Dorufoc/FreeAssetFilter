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

# 导入设置管理器
from .settings_manager import SettingsManager


class SvgRenderer:
    """
    SVG图像渲染工具类
    提供高质量的SVG到QPixmap或QSvgWidget转换，确保正确处理RGBA通道
    参考了custom_file_selector.py中_set_file_icon方法的实现
    """
    
    @staticmethod
    def _get_accent_color():
        """
        获取应用设置中的强调色(accent_color)
        
        Returns:
            str: 强调色的十六进制值，如#FF0000
        """
        try:
            settings_manager = SettingsManager()
            return settings_manager.get_setting("appearance.colors.accent_color")
        except Exception as e:
            print(f"获取强调色失败: {e}")
            # 如果获取失败，返回默认强调色
            return "#007AFF"
    
    @staticmethod
    def _get_base_color():
        """
        获取应用设置中的底层色(base_color)
        
        Returns:
            str: 底层色的十六进制值，如#FFFFFF
        """
        try:
            settings_manager = SettingsManager()
            return settings_manager.get_setting("appearance.colors.base_color")
        except Exception as e:
            print(f"获取底层色失败: {e}")
            # 如果获取失败，返回默认底层色
            return "#f1f3f5"
    
    @staticmethod
    def _get_secondary_color():
        """
        获取应用设置中的次选色(secondary_color)
        
        Returns:
            str: 次选色的十六进制值，如#000000
        """
        try:
            settings_manager = SettingsManager()
            return settings_manager.get_setting("appearance.colors.secondary_color")
        except Exception as e:
            print(f"获取次选色失败: {e}")
            # 如果获取失败，返回默认次选色
            return "#333333"
    
    @staticmethod
    def _replace_svg_colors(svg_content):
        """
        预处理SVG内容，根据应用设置替换颜色值
        - 将所有#000000颜色值替换为应用设置中的secondary_color
        - 将所有#FFFFFF颜色值替换为应用设置中的base_color
        - 将所有#0a59f7颜色值替换为应用设置中的accent_color
        
        Args:
            svg_content (str): SVG内容字符串
            
        Returns:
            str: 预处理后的SVG内容字符串
        """
        try:
            import re
            # 获取颜色设置
            accent_color = SvgRenderer._get_accent_color()
            base_color = SvgRenderer._get_base_color()
            secondary_color = SvgRenderer._get_secondary_color()
            
            processed_svg = svg_content
            
            # 1. 为没有指定fill属性且没有class属性的path元素添加默认fill="#000000"
            # 这样可以确保默认颜色也能被替换，同时不影响已经通过class定义颜色的元素
            processed_svg = re.sub(r'<path\b(?!.*\bfill\s*=)(?!.*\bclass\s*=)', r'<path fill="#000000"', processed_svg, flags=re.IGNORECASE)
            
            # 2. 处理stroke属性中的颜色（如果有）
            processed_svg = re.sub(r'stroke="#FFFFFF"', f'stroke="{base_color}"', processed_svg, flags=re.IGNORECASE)
            processed_svg = re.sub(r'stroke="#FFF"', f'stroke="{base_color}"', processed_svg, flags=re.IGNORECASE)
            processed_svg = re.sub(r'stroke="#000000"', f'stroke="{secondary_color}"', processed_svg, flags=re.IGNORECASE)
            processed_svg = re.sub(r'stroke="#000"', f'stroke="{secondary_color}"', processed_svg, flags=re.IGNORECASE)
            
            # 3. 使用更精确的正则表达式处理fill属性中的颜色
            # 先处理#FFFFFF和#FFF，替换为base_color
            processed_svg = re.sub(r'fill="#FFFFFF"', f'fill="{base_color}"', processed_svg, flags=re.IGNORECASE)
            processed_svg = re.sub(r'fill="#FFF"', f'fill="{base_color}"', processed_svg, flags=re.IGNORECASE)
            
            # 再处理#000000和#000，替换为secondary_color
            processed_svg = re.sub(r'fill="#000000"', f'fill="{secondary_color}"', processed_svg, flags=re.IGNORECASE)
            processed_svg = re.sub(r'fill="#000"', f'fill="{secondary_color}"', processed_svg, flags=re.IGNORECASE)
            
            # 4. 将所有#0a59f7颜色值替换为accent_color
            # 考虑大小写不敏感的情况，如#0A59F7
            processed_svg = re.sub(r'#0a59f7', accent_color, processed_svg, flags=re.IGNORECASE)
            
            return processed_svg
        except Exception as e:
            print(f"替换SVG颜色失败: {e}")
            # 如果替换失败，返回原始SVG内容
            return svg_content
    
    @staticmethod
    def render_svg_to_widget(icon_path, icon_size=120, dpi_scale=1.0):
        """
        将SVG文件渲染为QSvgWidget，这是最可靠的方式
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认120x120
            dpi_scale (float): DPI缩放因子，默认1.0
            
        Returns:
            QWidget: 渲染后的QSvgWidget或QLabel对象，确保控件本身完全不可见
        """
        # 应用DPI缩放因子到图标大小
        scaled_icon_size = int(icon_size * dpi_scale)
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回完全透明的QLabel
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            label.setAttribute(Qt.WA_TranslucentBackground, True)
            pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
            return label
        
        try:
            # 读取SVG文件内容，预处理以确保兼容性
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 预处理SVG内容：替换颜色
            svg_content = SvgRenderer._replace_svg_colors(svg_content)
            
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
            # 确保QSvgWidget完全透明，没有任何可见样式
            svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
            return svg_widget
        except Exception as e:
            print(f"使用QSvgWidget加载SVG图标失败: {e}")
            # 如果QSvgWidget失败，回退到使用超分辨率渲染的位图
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, dpi_scale)
            
            # 将pixmap显示在完全透明的QLabel中
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setAlignment(Qt.AlignCenter)
            # 确保QLabel完全透明，没有任何可见样式
            label.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            label.setAttribute(Qt.WA_TranslucentBackground, True)
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
            
            # 读取SVG文件内容，预处理以确保兼容性
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 预处理SVG内容：替换颜色
            svg_content = SvgRenderer._replace_svg_colors(svg_content)
            
            # 使用QSvgRenderer渲染
            svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
            
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
            # 始终使用SVG渲染，不检查PNG文件
            
            # 读取SVG文件内容，预处理以确保兼容性
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 预处理SVG内容：替换颜色
            svg_content = SvgRenderer._replace_svg_colors(svg_content)
            
            # 使用QSvgRenderer创建一个足够大的pixmap（256x256），然后缩放
            # 这确保了在高DPI屏幕上的清晰度，实现超分辨率渲染
            svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
            
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
            
            # 设置设备像素比，确保高DPI屏幕上的清晰度
            final_pixmap.setDevicePixelRatio(dpi_scale)
            
            if not final_pixmap.isNull():
                return final_pixmap
            else:
                # 如果缩放失败，返回原始渲染结果
                return pixmap
        except Exception as e:
            print(f"渲染SVG到QPixmap失败: {icon_path}, 错误: {e}")
        
        # 如果所有方法都失败，返回透明像素图
        pixmap = QPixmap(scaled_width, scaled_height)
        pixmap.fill(Qt.transparent)
        return pixmap
    
    @staticmethod
    def render_unknown_file_icon(icon_path, text, icon_size=120, dpi_scale=1.0):
        """
        渲染带有文字的未知文件类型图标
        将SVG底板与文字组合渲染为一个QPixmap或QSvgWidget
        
        Args:
            icon_path (str): SVG底板文件路径
            text (str): 要显示的文字（文件后缀名）
            icon_size (int): 输出图标大小，默认120x120
            dpi_scale (float): DPI缩放因子，默认1.0
            
        Returns:
            QWidget: 渲染后的Widget对象，确保控件本身完全透明
        """
        # 应用DPI缩放因子到图标大小
        scaled_icon_size = int(icon_size * dpi_scale)
        
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回完全透明的QLabel
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            label.setAttribute(Qt.WA_TranslucentBackground, True)
            pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
            return label
        
        try:
            # 创建容器widget
            container = QWidget()
            container.setFixedSize(scaled_icon_size, scaled_icon_size)
            container.setStyleSheet('background: transparent; border: none;')
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            
            # 使用QSvgWidget渲染SVG底板
            svg_widget = QSvgWidget(container)
            svg_widget.load(icon_path)
            svg_widget.setFixedSize(scaled_icon_size, scaled_icon_size)
            svg_widget.setStyleSheet('background: transparent; border: none;')
            svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
            svg_widget.move(0, 0)
            
            # 如果有文字，创建文字标签
            if text:
                # 创建文字标签
                text_label = QLabel(text, container)
                text_label.setAlignment(Qt.AlignCenter)
                text_label.setFixedSize(scaled_icon_size, scaled_icon_size)
                text_label.setStyleSheet('background: transparent; border: none;')
                text_label.setAttribute(Qt.WA_TranslucentBackground, True)
                text_label.move(0, 0)
                
                # 加载字体
                from PyQt5.QtGui import QFont, QFontMetrics, QFontDatabase
                font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
                font = QFont()
                
                if os.path.exists(font_path):
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id != -1:
                        font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                        font.setFamily(font_family)
                
                # 计算合适的字体大小
                base_font_size = int(scaled_icon_size * 0.18)
                font.setPointSize(base_font_size)
                font.setBold(True)
                
                # 自适应调整字体大小，确保文字不超出图标边界
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.width(text)
                text_height = font_metrics.height()
                
                # 最小字体为容器大小的15%
                min_font_size = int(scaled_icon_size * 0.15)
                
                # 调整字体大小，确保文字完全显示在容器内
                while (text_width > scaled_icon_size * 0.8 or text_height > scaled_icon_size * 0.8) and base_font_size > min_font_size:
                    base_font_size -= 1
                    font.setPointSize(base_font_size)
                    font_metrics = QFontMetrics(font)
                    text_width = font_metrics.width(text)
                    text_height = font_metrics.height()
                
                # 设置文字颜色
                if icon_path.endswith("压缩文件.svg"):
                    text_label.setStyleSheet(f'color: white; font: {base_font_size}pt "{font.family()}"; font-weight: bold; background: transparent;')
                else:
                    text_label.setStyleSheet(f'color: black; font: {base_font_size}pt "{font.family()}"; font-weight: bold; background: transparent;')
            
            return container
        except Exception as e:
            print(f"渲染未知文件图标失败: {e}")
            # 如果渲染失败，回退到使用位图渲染
            
            # 首先渲染SVG底板
            base_pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, dpi_scale)
            
            # 创建一个透明的QPixmap用于绘制最终结果
            final_pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
            final_pixmap.fill(Qt.transparent)
            
            # 创建画家
            painter = QPainter(final_pixmap)
            
            # 设置最高质量的渲染提示
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.HighQualityAntialiasing, True)
            
            # 绘制SVG底板
            painter.drawPixmap(0, 0, base_pixmap)
            
            # 如果有文字，绘制文字
            if text:
                from PyQt5.QtGui import QFont, QFontMetrics, QFontDatabase, QColor
                
                # 加载字体
                font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
                font = QFont()
                
                if os.path.exists(font_path):
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id != -1:
                        font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                        font.setFamily(font_family)
                
                # 计算合适的字体大小
                base_font_size = int(scaled_icon_size * 0.35)
                font.setPointSize(base_font_size)
                font.setBold(True)
                
                # 自适应调整字体大小
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.width(text)
                text_height = font_metrics.height()
                
                min_font_size = int(scaled_icon_size * 0.15)
                
                while (text_width > scaled_icon_size * 0.8 or text_height > scaled_icon_size * 0.8) and base_font_size > min_font_size:
                    base_font_size -= 1
                    font.setPointSize(base_font_size)
                    font_metrics = QFontMetrics(font)
                    text_width = font_metrics.width(text)
                    text_height = font_metrics.height()
                
                # 设置文字颜色
                if icon_path.endswith("压缩文件.svg"):
                    text_color = QColor(255, 255, 255)
                else:
                    text_color = QColor(0, 0, 0)
                
                painter.setPen(text_color)
                painter.setFont(font)
                
                # 计算文字位置，居中显示
                text_x = (scaled_icon_size - text_width) // 2
                text_y = (scaled_icon_size + font_metrics.ascent()) // 2
                
                # 绘制文字
                painter.drawText(text_x, text_y, text)
            
            painter.end()
            
            # 将最终结果显示在QLabel中
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setPixmap(final_pixmap)
            label.setStyleSheet('background: transparent; border: none;')
            label.setAttribute(Qt.WA_TranslucentBackground, True)
            
            return label
    
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
            # 预处理SVG内容：替换颜色
            svg_string = SvgRenderer._replace_svg_colors(svg_string)
            
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
