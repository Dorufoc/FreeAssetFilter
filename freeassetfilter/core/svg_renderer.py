#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

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
import re

from .settings_manager import SettingsManager

# 导入日志模块
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.utils.perf_metrics import increment_perf_counter, set_perf_metadata, track_perf


# ── 编译正则表达式（模块级，只编译一次） ──────────────────────────────
# 为 SVG 颜色替换优化：将 24 个 re.sub() 调用合并为模块级编译模式
_RE_PATH_NO_FILL = re.compile(
    r'<path\b(?!.*\bfill\s*=)(?!.*\bclass\s*=)',
    re.IGNORECASE,
)
_RE_STROKE_WHITE = re.compile(r'stroke="#FFFFFF"', re.IGNORECASE)
_RE_STROKE_WHITE_SHORT = re.compile(r'stroke="#FFF"', re.IGNORECASE)
_RE_STROKE_BLACK = re.compile(r'stroke="#000000"', re.IGNORECASE)
_RE_STROKE_BLACK_SHORT = re.compile(r'stroke="#000"', re.IGNORECASE)
_RE_FILL_WHITE = re.compile(r'fill="#FFFFFF"', re.IGNORECASE)
_RE_FILL_WHITE_SHORT = re.compile(r'fill="#FFF"', re.IGNORECASE)
_RE_FILL_BLACK = re.compile(r'fill="#000000"', re.IGNORECASE)
_RE_FILL_BLACK_SHORT = re.compile(r'fill="#000"', re.IGNORECASE)
_RE_CSS_FILL_WHITE = re.compile(r'(fill:\s*)#FFFFFF', re.IGNORECASE)
_RE_CSS_FILL_WHITE_SHORT = re.compile(r'(fill:\s*)#FFF', re.IGNORECASE)
_RE_CSS_FILL_BLACK = re.compile(r'(fill:\s*)#000000', re.IGNORECASE)
_RE_CSS_FILL_BLACK_SHORT = re.compile(r'(fill:\s*)#000\b', re.IGNORECASE)
_RE_ACCENT = re.compile(r'#0a59f7', re.IGNORECASE)
_RE_STROKE_NORMAL = re.compile(r'stroke="#cecece"', re.IGNORECASE)
_RE_FILL_NORMAL = re.compile(r'fill="#cecece"', re.IGNORECASE)
_RE_CSS_FILL_NORMAL = re.compile(r'(fill:\s*)#cecece', re.IGNORECASE)
_RE_CSS_STROKE_NORMAL = re.compile(r'(stroke:\s*)#cecece', re.IGNORECASE)


def _smart_render_size(target_width: int, target_height: int, dpr: float) -> int:
    """
    根据目标尺寸和设备像素比计算智能渲染尺寸。
    保证至少 64px 以避免小图标模糊，同时不超过必要大小以提升性能。
    """
    return max(max(target_width, target_height), 64) * dpr


class SvgRenderer:
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
                increment_perf_counter("svg.replace_colors", "invocations")
                settings_manager = SettingsManager()
                accent_color = settings_manager.get_setting("appearance.colors.accent_color", "#007AFF")
                base_color = settings_manager.get_setting("appearance.colors.base_color", "#f1f3f5")
                secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#333333")
                normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#CECECE")

                black_replacement_color = base_color if force_black_to_base else secondary_color
                processed_svg = svg_content

                # 使用模块级编译的正则表达式，避免重复编译
                processed_svg = _RE_PATH_NO_FILL.sub(r'<path fill="#000000"', processed_svg)

                if invert_white_to_black:
                    processed_svg = _RE_STROKE_WHITE.sub('stroke="#000000"', processed_svg)
                    processed_svg = _RE_STROKE_WHITE_SHORT.sub('stroke="#000000"', processed_svg)
                else:
                    processed_svg = _RE_STROKE_WHITE.sub(f'stroke="{base_color}"', processed_svg)
                    processed_svg = _RE_STROKE_WHITE_SHORT.sub(f'stroke="{base_color}"', processed_svg)
                    processed_svg = _RE_STROKE_BLACK.sub(f'stroke="{black_replacement_color}"', processed_svg)
                    processed_svg = _RE_STROKE_BLACK_SHORT.sub(f'stroke="{black_replacement_color}"', processed_svg)

                if invert_white_to_black:
                    processed_svg = _RE_FILL_WHITE.sub('fill="#000000"', processed_svg)
                    processed_svg = _RE_FILL_WHITE_SHORT.sub('fill="#000000"', processed_svg)
                else:
                    processed_svg = _RE_FILL_WHITE.sub(f'fill="{base_color}"', processed_svg)
                    processed_svg = _RE_FILL_WHITE_SHORT.sub(f'fill="{base_color}"', processed_svg)
                    processed_svg = _RE_FILL_BLACK.sub(f'fill="{black_replacement_color}"', processed_svg)
                    processed_svg = _RE_FILL_BLACK_SHORT.sub(f'fill="{black_replacement_color}"', processed_svg)

                if invert_white_to_black:
                    processed_svg = _RE_CSS_FILL_WHITE.sub(r'\1#000000', processed_svg)
                    processed_svg = _RE_CSS_FILL_WHITE_SHORT.sub(r'\1#000000', processed_svg)
                else:
                    processed_svg = _RE_CSS_FILL_WHITE.sub(f'fill: {base_color}', processed_svg)
                    processed_svg = _RE_CSS_FILL_WHITE_SHORT.sub(f'fill: {base_color}', processed_svg)
                    processed_svg = _RE_CSS_FILL_BLACK.sub(f'fill: {black_replacement_color}', processed_svg)
                    processed_svg = _RE_CSS_FILL_BLACK_SHORT.sub(f'fill: {black_replacement_color}', processed_svg)

                processed_svg = _RE_ACCENT.sub(accent_color, processed_svg)
                processed_svg = _RE_STROKE_NORMAL.sub(f'stroke="{normal_color}"', processed_svg)
                processed_svg = _RE_FILL_NORMAL.sub(f'fill="{normal_color}"', processed_svg)
                processed_svg = _RE_CSS_FILL_NORMAL.sub(f'fill: {normal_color}', processed_svg)
                processed_svg = _RE_CSS_STROKE_NORMAL.sub(f'stroke: {normal_color}', processed_svg)

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
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            if replace_colors:
                svg_content = SvgRenderer._replace_svg_colors(svg_content)
            
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
            
            svg_content = re.sub(r'rgba\(([^\)]+)\)', rgba_to_hex, svg_content)
            
            # 获取 SVG 原始尺寸
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
            
            svg_widget = QSvgWidget()
            svg_widget.load(svg_content.encode('utf-8'))
            svg_widget.setStyleSheet("background: transparent; border: none; padding: 0; margin: 0;")
            svg_widget.setAttribute(Qt.WA_TranslucentBackground, True)
            
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
            pixmap = SvgRenderer.render_svg_to_pixmap(icon_path, icon_size, dpi_scale, replace_colors=replace_colors)
            
            label = QLabel()
            label.setFixedSize(scaled_icon_size, scaled_icon_size)
            label.setAlignment(Qt.AlignCenter)
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
            label = QLabel()
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(icon_size, icon_size)
            
            with open(icon_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            
            svg_content = SvgRenderer._replace_svg_colors(svg_content)
            
            svg_renderer = QSvgRenderer(svg_content.encode('utf-8'))
            
            # 智能渲染尺寸，保证小图标清晰
            dpr = QGuiApplication.primaryScreen().devicePixelRatio()
            render_size = _smart_render_size(icon_size, icon_size, dpr)
            
            image = QImage(render_size, render_size, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            
            svg_renderer.render(painter)
            painter.end()
            
            pixmap = QPixmap.fromImage(image)
            
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                label.setPixmap(scaled_pixmap)
            else:
                pixmap = QPixmap(icon_size, icon_size)
                pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
                pixmap.fill(Qt.transparent)
                label.setPixmap(pixmap)
            
            return label
        except (OSError, ValueError) as renderer_e:
            warning(f"使用QSvgRenderer加载SVG图标失败: {renderer_e}")
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

                dpr = QGuiApplication.primaryScreen().devicePixelRatio()
                render_size = _smart_render_size(target_width, target_height, dpr)
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
                        base_color = SettingsManager().get_setting("appearance.colors.base_color", "#f1f3f5")
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
                    base_color = SettingsManager().get_setting("appearance.colors.base_color", "#f1f3f5")
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
            pixmap = QPixmap(icon_size, icon_size)
            pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
            pixmap.fill(Qt.transparent)
            return pixmap
        
        try:
            svg_string = SvgRenderer._replace_svg_colors(svg_string)
            
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
            
            processed_svg = re.sub(r'rgba\(([^\)]+)\)', rgba_to_hex, svg_string)
            
            svg_renderer = QSvgRenderer(processed_svg.encode('utf-8'))
            
            dpr = QGuiApplication.primaryScreen().devicePixelRatio()
            render_size = _smart_render_size(icon_size, icon_size, dpr)
            
            pixmap = QPixmap(render_size, render_size)
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.transparent)
            
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)

            svg_renderer.render(painter)
            painter.end()
            
            final_pixmap = pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            if not final_pixmap.isNull():
                return final_pixmap
        except (ValueError, TypeError) as e:
            warning(f"SVG字符串渲染失败: {e}")
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.setDevicePixelRatio(QGuiApplication.primaryScreen().devicePixelRatio())
        pixmap.fill(Qt.transparent)
        return pixmap
