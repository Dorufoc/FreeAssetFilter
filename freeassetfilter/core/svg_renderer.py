#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

独立的SVG图像渲染工具
提供高质量的SVG到QPixmap或QSvgWidget转换，确保正确处理RGBA通道
"""

from PySide6.QtCore import Qt, QSize, QThread, QRectF
from PySide6.QtGui import QPainter, QPixmap, QImage, QColor
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QApplication
from PySide6.QtGui import QGuiApplication
import os
import threading

from .settings_manager import SettingsManager

# 导入日志模块
from freeassetfilter.utils.app_logger import info, debug, warning, error
from freeassetfilter.utils.perf_metrics import increment_perf_counter, set_perf_metadata, track_perf


class SvgRenderer:
    _cached_colors = {}
    _color_cache_valid = False
    _cache_lock = threading.Lock()

    @staticmethod
    def _invalidate_color_cache():
        with SvgRenderer._cache_lock:
            SvgRenderer._color_cache_valid = False
            SvgRenderer._cached_colors.clear()

    @staticmethod
    def _ensure_color_cache():
        with SvgRenderer._cache_lock:
            if SvgRenderer._color_cache_valid:
                return

            try:
                settings_manager = SettingsManager()
                SvgRenderer._cached_colors = {
                    "accent_color": settings_manager.get_setting("appearance.colors.accent_color", "#007AFF"),
                    "base_color": settings_manager.get_setting("appearance.colors.base_color", "#f1f3f5"),
                    "secondary_color": settings_manager.get_setting("appearance.colors.secondary_color", "#333333"),
                    "normal_color": settings_manager.get_setting("appearance.colors.normal_color", "#CECECE")
                }
                SvgRenderer._color_cache_valid = True
            except (OSError, ValueError, TypeError) as e:
                warning(f"颜色设置获取失败: {e}")
                SvgRenderer._cached_colors = {
                    "accent_color": "#007AFF",
                    "base_color": "#f1f3f5",
                    "secondary_color": "#333333",
                    "normal_color": "#CECECE"
                }
                SvgRenderer._color_cache_valid = True

    @staticmethod
    def _get_accent_color():
        SvgRenderer._ensure_color_cache()
        return SvgRenderer._cached_colors.get("accent_color", "#007AFF")

    @staticmethod
    def _get_base_color():
        SvgRenderer._ensure_color_cache()
        return SvgRenderer._cached_colors.get("base_color", "#f1f3f5")

    @staticmethod
    def _get_secondary_color():
        SvgRenderer._ensure_color_cache()
        return SvgRenderer._cached_colors.get("secondary_color", "#333333")

    @staticmethod
    def _get_normal_color():
        SvgRenderer._ensure_color_cache()
        return SvgRenderer._cached_colors.get("normal_color", "#CECECE")

    @staticmethod
    def _replace_svg_colors(svg_content, invert_white_to_black=False, force_black_to_base=False):
        """
        预处理SVG内容，根据应用设置替换颜色值
        - 将所有#000000颜色值替换为应用设置中的secondary_color（或base_color当force_black_to_base=True时）
        - 将所有#FFFFFF颜色值替换为应用设置中的base_color，或在invert_white_to_black=True时替换为#000000
        - 将所有#0a59f7颜色值替换为应用设置中的accent_color
        - 将所有#cecece颜色值替换为应用设置中的normal_color

        Args:
            svg_content (str): SVG内容字符串
            invert_white_to_black (bool): 是否将#FFFFFF转换为#000000（用于某些深色模式场景），默认False
            force_black_to_base (bool): 是否强制将#000000替换为base_color（用于强调样式按钮），默认False

        Returns:
            str: 预处理后的SVG内容字符串
        """
        with track_perf("svg.replace_colors"):
            try:
                import re

                increment_perf_counter("svg.replace_colors", "invocations")
                accent_color = SvgRenderer._get_accent_color()
                base_color = SvgRenderer._get_base_color()
                secondary_color = SvgRenderer._get_secondary_color()
                normal_color = SvgRenderer._get_normal_color()

                black_replacement_color = base_color if force_black_to_base else secondary_color
                processed_svg = svg_content

                processed_svg = re.sub(
                    r'<path\b(?!.*\bfill\s*=)(?!.*\bclass\s*=)',
                    r'<path fill="#000000"',
                    processed_svg,
                    flags=re.IGNORECASE,
                )

                if invert_white_to_black:
                    processed_svg = re.sub(r'stroke="#FFFFFF"', 'stroke="#000000"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'stroke="#FFF"', 'stroke="#000000"', processed_svg, flags=re.IGNORECASE)
                else:
                    processed_svg = re.sub(r'stroke="#FFFFFF"', f'stroke="{base_color}"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'stroke="#FFF"', f'stroke="{base_color}"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'stroke="#000000"', f'stroke="{black_replacement_color}"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'stroke="#000"', f'stroke="{black_replacement_color}"', processed_svg, flags=re.IGNORECASE)

                if invert_white_to_black:
                    processed_svg = re.sub(r'fill="#FFFFFF"', 'fill="#000000"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'fill="#FFF"', 'fill="#000000"', processed_svg, flags=re.IGNORECASE)
                else:
                    processed_svg = re.sub(r'fill="#FFFFFF"', f'fill="{base_color}"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'fill="#FFF"', f'fill="{base_color}"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'fill="#000000"', f'fill="{black_replacement_color}"', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'fill="#000"', f'fill="{black_replacement_color}"', processed_svg, flags=re.IGNORECASE)

                if invert_white_to_black:
                    processed_svg = re.sub(r'(fill:\s*)#FFFFFF', r'\1#000000', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'(fill:\s*)#FFF', r'\1#000000', processed_svg, flags=re.IGNORECASE)
                else:
                    processed_svg = re.sub(r'(fill:\s*)#FFFFFF', f'fill: {base_color}', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'(fill:\s*)#FFF', f'fill: {base_color}', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'(fill:\s*)#000000', f'fill: {black_replacement_color}', processed_svg, flags=re.IGNORECASE)
                    processed_svg = re.sub(r'(fill:\s*)#000\b', f'fill: {black_replacement_color}', processed_svg, flags=re.IGNORECASE)

                processed_svg = re.sub(r'#0a59f7', accent_color, processed_svg, flags=re.IGNORECASE)
                processed_svg = re.sub(r'stroke="#cecece"', f'stroke="{normal_color}"', processed_svg, flags=re.IGNORECASE)
                processed_svg = re.sub(r'fill="#cecece"', f'fill="{normal_color}"', processed_svg, flags=re.IGNORECASE)
                processed_svg = re.sub(r'(fill:\s*)#cecece', f'fill: {normal_color}', processed_svg, flags=re.IGNORECASE)
                processed_svg = re.sub(r'(stroke:\s*)#cecece', f'stroke: {normal_color}', processed_svg, flags=re.IGNORECASE)

                return processed_svg
            except (OSError, ValueError) as e:
                increment_perf_counter("svg.replace_colors", "failure")
                warning(f"SVG颜色替换失败: {e}")
                return svg_content

    @staticmethod
    def _get_device_pixel_ratio(device_pixel_ratio=None):
        if device_pixel_ratio is not None:
            try:
                resolved_dpr = float(device_pixel_ratio)
                if resolved_dpr > 0:
                    return resolved_dpr
            except (ValueError, TypeError):
                pass

        try:
            app = QGuiApplication.instance()
            screen = app.primaryScreen() if app else None
            if screen is not None:
                resolved_dpr = float(screen.devicePixelRatio())
                if resolved_dpr > 0:
                    return resolved_dpr
        except RuntimeError:
            pass

        return 1.0

    @staticmethod
    def _create_transparent_pixmap(width, height, device_pixel_ratio=None):
        target_width = max(1, int(width))
        target_height = max(1, int(height))
        resolved_dpr = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio)

        physical_width = max(1, int(round(target_width * resolved_dpr)))
        physical_height = max(1, int(round(target_height * resolved_dpr)))

        pixmap = QPixmap(physical_width, physical_height)
        pixmap.fill(Qt.transparent)
        pixmap.setDevicePixelRatio(resolved_dpr)
        return pixmap

    @staticmethod
    def _convert_rgba_to_hex(svg_content):
        import re

        def rgba_to_hex(match):
            rgba_values = match.group(1).split(',')
            r = rgba_values[0].strip()
            g = rgba_values[1].strip()
            b = rgba_values[2].strip()
            a = rgba_values[3].strip()

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

            if '%' in a:
                a = float(a.replace('%', '')) / 100
            else:
                a = float(a)

            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            a = max(0, min(1, a))
            a = int(a * 255)

            return f'#{int(r):02x}{int(g):02x}{int(b):02x}{a:02x}'

        return re.sub(r'rgba\(([^\)]+)\)', rgba_to_hex, svg_content)

    @staticmethod
    def _prepare_svg_content(svg_content, replace_colors=True):
        processed_svg = svg_content
        if replace_colors:
            processed_svg = SvgRenderer._replace_svg_colors(processed_svg)
        return SvgRenderer._convert_rgba_to_hex(processed_svg)

    @staticmethod
    def render_svg_to_exact_pixmap(
        icon_path,
        icon_width=24,
        icon_height=24,
        replace_colors=True,
        device_pixel_ratio=None,
    ):
        #debug(f"渲染SVG到Pixmap: {icon_path}, 尺寸: {icon_width}x{icon_height}")
        with track_perf("svg.render_exact_pixmap"):
            target_width = max(1, int(icon_width))
            target_height = max(1, int(icon_height))
            resolved_dpr = SvgRenderer._get_device_pixel_ratio(device_pixel_ratio)
            set_perf_metadata("svg.render_exact_pixmap", "last_dpr", resolved_dpr)
            set_perf_metadata("svg.render_exact_pixmap", "last_icon_width", target_width)
            set_perf_metadata("svg.render_exact_pixmap", "last_icon_height", target_height)

            if not icon_path or not os.path.exists(icon_path):
                increment_perf_counter("svg.render_exact_pixmap", "missing_source")
                return SvgRenderer._create_transparent_pixmap(target_width, target_height, resolved_dpr)

            try:
                with open(icon_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()

                processed_svg = SvgRenderer._prepare_svg_content(svg_content, replace_colors=replace_colors)
                svg_renderer = QSvgRenderer(processed_svg.encode('utf-8'))

                physical_width = max(1, int(round(target_width * resolved_dpr)))
                physical_height = max(1, int(round(target_height * resolved_dpr)))

                image = QImage(physical_width, physical_height, QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)

                painter = QPainter(image)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setRenderHint(QPainter.TextAntialiasing, True)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

                svg_size = svg_renderer.defaultSize()
                if svg_size.width() > 0 and svg_size.height() > 0:
                    target_size = QSize(svg_size.width(), svg_size.height()).scaled(
                        physical_width,
                        physical_height,
                        Qt.KeepAspectRatio,
                    )
                    target_rect = QRectF(
                        (physical_width - target_size.width()) / 2.0,
                        (physical_height - target_size.height()) / 2.0,
                        float(target_size.width()),
                        float(target_size.height()),
                    )
                else:
                    target_rect = QRectF(0.0, 0.0, float(physical_width), float(physical_height))

                svg_renderer.render(painter, target_rect)
                painter.end()

                pixmap = QPixmap.fromImage(image)
                if pixmap.isNull():
                    increment_perf_counter("svg.render_exact_pixmap", "null_pixmap")
                    return SvgRenderer._create_transparent_pixmap(target_width, target_height, resolved_dpr)

                increment_perf_counter("svg.render_exact_pixmap", "success")
                pixmap.setDevicePixelRatio(resolved_dpr)
                return pixmap
            except (OSError, ValueError, TypeError, RuntimeError) as e:
                increment_perf_counter("svg.render_exact_pixmap", "failure")
                warning(f"SVG渲染失败: {icon_path}, {e}")
                return SvgRenderer._create_transparent_pixmap(target_width, target_height, resolved_dpr)

    @staticmethod
    def render_svg_to_widget(icon_path, icon_size=120, dpi_scale=1.0, replace_colors=True):
        """
        将SVG文件渲染为QSvgWidget，这是最可靠的方式

        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认120x120（当SVG不是1:1比例时，按原始比例缩放）
            dpi_scale (float): DPI缩放因子，默认1.0
            replace_colors (bool): 是否启用颜色替换功能，默认True

        Returns:
            QWidget: 渲染后的QSvgWidget或QLabel对象，确保控件本身完全不可见
        """
        debug(f"渲染SVG到Widget: {icon_path}, 尺寸: {icon_size}")
        # 使用逻辑像素大小，不再应用DPI缩放因子
        scaled_icon_size = icon_size
        if not icon_path or not os.path.exists(icon_path):
            # 如果路径无效，返回完全透明的QLabel
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            label.setAttribute(Qt.WA_TranslucentBackground, True)
            pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
            pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
            return label
        
        try:
            # 读取SVG文件内容，预处理以确保兼容性
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            # 预处理SVG内容：根据参数决定是否替换颜色
            if replace_colors:
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
            
            # 创建临时渲染器获取SVG原始尺寸
            temp_renderer = QSvgRenderer(svg_content.encode('utf-8'))
            svg_default_size = temp_renderer.defaultSize()
            
            # 计算保持原始比例的尺寸
            if svg_default_size.width() > 0 and svg_default_size.height() > 0:
                svg_aspect_ratio = svg_default_size.width() / svg_default_size.height()
                if svg_aspect_ratio >= 1:
                    # 宽度大于等于高度，以宽度为基准
                    render_width = scaled_icon_size
                    render_height = int(scaled_icon_size / svg_aspect_ratio)
                else:
                    # 高度大于宽度，以高度为基准
                    render_height = scaled_icon_size
                    render_width = int(scaled_icon_size * svg_aspect_ratio)
            else:
                # 如果无法获取原始尺寸，使用正方形
                render_width = scaled_icon_size
                render_height = scaled_icon_size
            
            svg_widget = QSvgWidget()
            svg_widget.load(svg_content.encode('utf-8'))
            svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
            
            # 使用保持比例的尺寸，而不是强制正方形
            svg_widget.setFixedSize(render_width, render_height)
            
            container = QWidget()
            container.setFixedSize(scaled_icon_size, scaled_icon_size)
            container.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            container.setAttribute(Qt.WA_TranslucentBackground, True)
            
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(svg_widget, 0, Qt.AlignCenter)
            
            return container
        except (OSError, ValueError, TypeError) as e:
            warning(f"SVG加载失败: {e}")
            # QSvgWidget失败，回退到超分辨率渲染
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, dpi_scale, replace_colors=replace_colors)
            
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
            painter.setRenderHint(QPainter.Antialiasing, True)
            
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
                pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
            
            return label
        except (OSError, ValueError) as renderer_e:
            warning(f"使用QSvgRenderer加载SVG图标失败: {renderer_e}")
            # 如果加载失败，创建一个默认的透明图标
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(icon_size, icon_size)
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
            pixmap.fill(Qt.transparent)
            label.setPixmap(pixmap)
            return label
    
    @staticmethod
    def render_svg_to_pixmap(icon_path, icon_size=24, dpi_scale=1.0, icon_width=None, icon_height=None, replace_colors=True):
        """
        将SVG文件渲染为QPixmap，支持透明背景和高质量渲染
        
        注意：对于需要高质量渲染的场景，建议使用render_svg_to_widget方法返回QSvgWidget
        
        Args:
            icon_path (str): SVG文件路径
            icon_size (int): 输出图标大小，默认24x24（当未指定width和height时使用，会根据SVG原始比例自动调整）
            dpi_scale (float): DPI缩放因子，默认1.0
            icon_width (int, optional): 输出图标宽度，指定后按比例渲染
            icon_height (int, optional): 输出图标高度，指定后按比例渲染
            replace_colors (bool): 是否启用色彩替换功能，默认True
            
        Returns:
            QPixmap: 渲染后的QPixmap对象，如果渲染失败返回透明像素图
        """
        with track_perf("svg.render_pixmap"):
            set_perf_metadata("svg.render_pixmap", "last_icon_size", icon_size)
            set_perf_metadata("svg.render_pixmap", "last_icon_width", icon_width)
            set_perf_metadata("svg.render_pixmap", "last_icon_height", icon_height)

            if not icon_path or not os.path.exists(icon_path):
                increment_perf_counter("svg.render_pixmap", "missing_source")
                if icon_width is not None and icon_height is not None:
                    scaled_width = icon_width
                    scaled_height = icon_height
                else:
                    scaled_width = icon_size
                    scaled_height = icon_size
                pixmap = QPixmap(scaled_width, scaled_height)
                pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                pixmap.fill(Qt.transparent)
                return pixmap

            try:
                with open(icon_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()

                if replace_colors:
                    svg_content = SvgRenderer._replace_svg_colors(svg_content)

                svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
                svg_size = svg_renderer.defaultSize()

                if icon_width is not None and icon_height is not None:
                    target_width = icon_width
                    target_height = icon_height
                elif svg_size.width() > 0 and svg_size.height() > 0:
                    svg_aspect_ratio = svg_size.width() / svg_size.height()
                    if svg_aspect_ratio >= 1:
                        target_width = icon_size
                        target_height = int(icon_size / svg_aspect_ratio)
                    else:
                        target_height = icon_size
                        target_width = int(icon_size * svg_aspect_ratio)
                else:
                    target_width = icon_size
                    target_height = icon_size

                render_size = 256
                is_main_thread = QThread.currentThread() == QApplication.instance().thread()
                increment_perf_counter(
                    "svg.render_pixmap",
                    "main_thread" if is_main_thread else "worker_thread",
                )

                if is_main_thread:
                    pixmap = QPixmap(render_size, render_size)
                    pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                    pixmap.fill(Qt.transparent)

                    painter = QPainter(pixmap)
                    painter.setRenderHint(QPainter.Antialiasing, True)
                    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    painter.setRenderHint(QPainter.TextAntialiasing, True)

                    scale_factor = min(render_size / svg_size.width(), render_size / svg_size.height())
                    x = (render_size - svg_size.width() * scale_factor) / 2
                    y = (render_size - svg_size.height() * scale_factor) / 2

                    painter.save()
                    painter.translate(x, y)
                    painter.scale(scale_factor, scale_factor)
                    svg_renderer.render(painter)
                    painter.restore()
                    painter.end()
                else:
                    image = QImage(render_size, render_size, QImage.Format_ARGB32_Premultiplied)
                    image.fill(Qt.transparent)

                    painter = QPainter(image)
                    painter.setRenderHint(QPainter.Antialiasing, True)
                    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    painter.setRenderHint(QPainter.TextAntialiasing, True)

                    scale_factor = min(render_size / svg_size.width(), render_size / svg_size.height())
                    x = (render_size - svg_size.width() * scale_factor) / 2
                    y = (render_size - svg_size.height() * scale_factor) / 2

                    painter.save()
                    painter.translate(x, y)
                    painter.scale(scale_factor, scale_factor)
                    svg_renderer.render(painter)
                    painter.restore()
                    painter.end()

                    pixmap = QPixmap.fromImage(image)

                final_pixmap = pixmap.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                if is_main_thread:
                    final_pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())

                if not final_pixmap.isNull():
                    increment_perf_counter("svg.render_pixmap", "success")
                    return final_pixmap

                increment_perf_counter("svg.render_pixmap", "fallback_original_pixmap")
                return pixmap
            except (OSError, ValueError, TypeError) as e:
                increment_perf_counter("svg.render_pixmap", "failure")
                warning(f"渲染SVG到QPixmap失败: {icon_path}, 错误: {e}")

            if icon_width is not None and icon_height is not None:
                target_width = icon_width
                target_height = icon_height
            else:
                target_width = icon_size
                target_height = icon_size
            pixmap = QPixmap(target_width, target_height)
            pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
            pixmap.fill(Qt.transparent)
            return pixmap
    
    @staticmethod
    def render_unknown_file_icon(icon_path, text, icon_size=120, dpi_scale=1.0, replace_colors=True):
        """
        渲染带有文字的未知文件类型图标
        将SVG底板与文字组合渲染为一个QPixmap或QSvgWidget
        
        Args:
            icon_path (str): SVG底板文件路径
            text (str): 要显示的文字（文件后缀名）
            icon_size (int): 输出图标大小，默认120x120（当SVG不是1:1比例时，按原始比例缩放）
            dpi_scale (float): DPI缩放因子，默认1.0
            replace_colors (bool): 是否启用颜色替换功能，默认True
            
        Returns:
            QWidget: 渲染后的Widget对象，确保控件本身完全透明
        """
        with track_perf("svg.render_unknown_file_icon"):
            scaled_icon_size = icon_size
            set_perf_metadata("svg.render_unknown_file_icon", "last_icon_size", scaled_icon_size)

            if not text or len(text) >= 5:
                text = "FILE"

            if not icon_path or not os.path.exists(icon_path):
                increment_perf_counter("svg.render_unknown_file_icon", "missing_source")
                label = QLabel()
                label.setFixedSize(scaled_icon_size, scaled_icon_size)
                label.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
                label.setAttribute(Qt.WA_TranslucentBackground, True)
                pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
                pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
                return label

            try:
                container = QWidget()
                container.setFixedSize(scaled_icon_size, scaled_icon_size)
                container.setStyleSheet('background: transparent; border: none;')
                container.setAttribute(Qt.WA_TranslucentBackground, True)

                with open(icon_path, 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                if replace_colors:
                    svg_content = SvgRenderer._replace_svg_colors(svg_content)

                temp_renderer = QSvgRenderer(svg_content.encode('utf-8'))
                svg_default_size = temp_renderer.defaultSize()

                if svg_default_size.width() > 0 and svg_default_size.height() > 0:
                    svg_aspect_ratio = svg_default_size.width() / svg_default_size.height()
                    if svg_aspect_ratio >= 1:
                        render_width = scaled_icon_size
                        render_height = int(scaled_icon_size / svg_aspect_ratio)
                    else:
                        render_height = scaled_icon_size
                        render_width = int(scaled_icon_size * svg_aspect_ratio)
                else:
                    render_width = scaled_icon_size
                    render_height = scaled_icon_size

                svg_widget = QSvgWidget(container)
                svg_widget.load(svg_content.encode('utf-8'))
                svg_widget.setFixedSize(render_width, render_height)
                svg_widget.setStyleSheet('background: transparent; border: none;')
                svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                x = (scaled_icon_size - render_width) // 2
                y = (scaled_icon_size - render_height) // 2
                svg_widget.move(x, y)

                if text:
                    text_label = QLabel(text, container)
                    text_label.setAlignment(Qt.AlignCenter)
                    text_label.setFixedSize(scaled_icon_size, scaled_icon_size)
                    text_label.setStyleSheet('background: transparent; border: none;')
                    text_label.setAttribute(Qt.WA_TranslucentBackground, True)
                    text_label.move(0, 0)

                    from PySide6.QtGui import QFont, QFontMetrics, QFontDatabase

                    font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
                    font = QFont()

                    if os.path.exists(font_path):
                        font_id = QFontDatabase.addApplicationFont(font_path)
                        if font_id != -1:
                            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                            font.setFamily(font_family)

                    base_font_size = int(scaled_icon_size * 0.234)
                    font.setPointSize(base_font_size)
                    font.setBold(True)

                    font_metrics = QFontMetrics(font)
                    text_width = font_metrics.horizontalAdvance(text)
                    text_height = font_metrics.height()
                    min_font_size = int(scaled_icon_size * 0.15)

                    while (text_width > scaled_icon_size * 0.8 or text_height > scaled_icon_size * 0.8) and base_font_size > min_font_size:
                        base_font_size -= 1
                        font.setPointSize(base_font_size)
                        font_metrics = QFontMetrics(font)
                        text_width = font_metrics.horizontalAdvance(text)
                        text_height = font_metrics.height()

                    is_unified_style = " – 2.svg" in icon_path
                    is_textured_archive = "压缩文件 – 1.svg" in icon_path
                    if is_unified_style:
                        base_color = SvgRenderer._get_base_color()
                        text_label.setStyleSheet(
                            f'color: {base_color}; font: {base_font_size}pt "{font.family()}"; '
                            'font-weight: bold; background: transparent;'
                        )
                    elif icon_path.endswith("压缩文件.svg") or is_textured_archive:
                        text_label.setStyleSheet(
                            f'color: white; font: {base_font_size}pt "{font.family()}"; '
                            'font-weight: bold; background: transparent;'
                        )
                    else:
                        text_label.setStyleSheet(
                            f'color: black; font: {base_font_size}pt "{font.family()}"; '
                            'font-weight: bold; background: transparent;'
                        )

                increment_perf_counter("svg.render_unknown_file_icon", "success")
                return container
            except (OSError, ValueError, TypeError) as e:
                increment_perf_counter("svg.render_unknown_file_icon", "failure")
                warning(f"渲染未知文件图标失败: {e}")

            base_pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, dpi_scale)

            final_pixmap = QPixmap(scaled_icon_size, scaled_icon_size)
            final_pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
            final_pixmap.fill(Qt.transparent)

            painter = QPainter(final_pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.drawPixmap(0, 0, base_pixmap)

            if text:
                from PySide6.QtGui import QFont, QFontMetrics, QFontDatabase, QColor

                font_path = os.path.join(os.path.dirname(__file__), "..", "icons", "庞门正道标题体.ttf")
                font = QFont()

                if os.path.exists(font_path):
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    if font_id != -1:
                        font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
                        font.setFamily(font_family)

                base_font_size = int(scaled_icon_size * 0.455)
                font.setPointSize(base_font_size)
                font.setBold(True)

                font_metrics = QFontMetrics(font)
                text_width = font_metrics.horizontalAdvance(text)
                text_height = font_metrics.height()
                min_font_size = int(scaled_icon_size * 0.15)

                while (text_width > scaled_icon_size * 0.8 or text_height > scaled_icon_size * 0.8) and base_font_size > min_font_size:
                    base_font_size -= 1
                    font.setPointSize(base_font_size)
                    font_metrics = QFontMetrics(font)
                    text_width = font_metrics.horizontalAdvance(text)
                    text_height = font_metrics.height()

                is_unified_style = " – 2.svg" in icon_path
                is_textured_archive = "压缩文件 – 1.svg" in icon_path
                if is_unified_style:
                    base_color = SvgRenderer._get_base_color()
                    text_color = QColor(base_color)
                elif icon_path.endswith("压缩文件.svg") or is_textured_archive:
                    text_color = QColor(255, 255, 255)
                else:
                    text_color = QColor(0, 0, 0)

                painter.setPen(text_color)
                painter.setFont(font)
                text_x = (scaled_icon_size - text_width) // 2
                text_y = (scaled_icon_size + font_metrics.ascent()) // 2
                painter.drawText(text_x, text_y, text)

            painter.end()

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
        debug(f"渲染SVG字符串到Pixmap, 尺寸: {icon_size}")
        if not svg_string:
            # 如果SVG字符串为空，返回透明像素图
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
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
            pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
            pixmap.fill(Qt.transparent)
            
            # 创建画家，设置透明背景和高质量渲染
            painter = QPainter(pixmap)
            
            # 设置最高质量的渲染提示
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)

            # 渲染SVG
            svg_renderer.render(painter)
            
            painter.end()
            
            # 然后缩放回目标大小，使用高质量缩放算法
            final_pixmap = pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            if not final_pixmap.isNull():
                return final_pixmap
        except (ValueError, TypeError) as e:
            warning(f"SVG字符串渲染失败: {e}")
            # 渲染失败，返回透明像素图
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
        pixmap.fill(Qt.transparent)
        return pixmap
