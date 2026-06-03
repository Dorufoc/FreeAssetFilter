#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileSelectorDelegate - 文件选择器列表视图的自定义委托

基于 FileBlockCard._paint_card() 的视觉与动画语义实现，
为 QListView 提供与 FileBlockCard 接近一致的卡片渲染效果。
"""

from PySide6.QtCore import Qt, QSize, QRect, QRectF
from PySide6.QtGui import QPen, QPainter
from PySide6.QtWidgets import QStyle

from freeassetfilter.widgets.file_selector_model import FileSelectorListModel
from freeassetfilter.widgets.base_card_delegate import BaseCardDelegate

_FILE_TYPE_MAP = {
    "py": "Python 源文件", "js": "JavaScript 源文件",
    "ts": "TypeScript 源文件", "jsx": "JSX 源文件", "tsx": "TSX 源文件",
    "html": "HTML 文档", "css": "CSS 样式表", "scss": "SCSS 样式表",
    "less": "LESS 样式表", "json": "JSON 文件",
    "xml": "XML 文件", "yaml": "YAML 文件", "yml": "YAML 文件",
    "sh": "Shell 脚本", "bat": "批处理文件", "cmd": "批处理文件",
    "ps1": "PowerShell 脚本", "psm1": "PowerShell 模块",
    "cpp": "C++ 源文件", "c": "C 源文件", "h": "C 头文件",
    "hpp": "C++ 头文件", "java": "Java 源文件",
    "rs": "Rust 源文件", "go": "Go 源文件",
    "rb": "Ruby 源文件", "php": "PHP 源文件",
    "swift": "Swift 源文件", "kt": "Kotlin 源文件",
    "kts": "Kotlin 脚本", "cs": "C# 源文件", "lua": "Lua 源文件",
    "dart": "Dart 源文件", "r": "R 源文件",
    "m": "Objective-C 源文件", "mm": "Objective-C++ 源文件",
    "pl": "Perl 脚本", "pm": "Perl 模块",
    "sql": "SQL 文件", "vue": "Vue 组件",
    "svelte": "Svelte 组件", "astro": "Astro 组件",
    "txt": "文本文档", "md": "MD 源文件",
    "rst": "reStructuredText 文件", "tex": "LaTeX 文档",
    "pdf": "PDF 文档",
    "doc": "Word 文档", "docx": "Word 文档", "docm": "Word 文档",
    "dotx": "Word 模板",
    "xls": "Excel 表格", "xlsx": "Excel 表格", "xlsm": "Excel 表格",
    "xlsb": "Excel 二进制工作簿", "csv": "CSV 表格",
    "ppt": "PowerPoint 演示文稿", "pptx": "PowerPoint 演示文稿",
    "pptm": "PowerPoint 启用宏的演示文稿", "potx": "PowerPoint 模板",
    "rtf": "RTF 文档", "odt": "ODT 文本文档",
    "ods": "ODS 电子表格", "odp": "ODP 演示文稿",
    "jpg": "JPEG 图像", "jpeg": "JPEG 图像", "jpe": "JPEG 图像",
    "png": "PNG 图像", "gif": "GIF 图像", "bmp": "BMP 图像",
    "webp": "WebP 图像", "tiff": "TIFF 图像", "tif": "TIFF 图像",
    "svg": "SVG 图像", "avif": "AVIF 图像",
    "ico": "图标", "cur": "光标",
    "heic": "HEIC 图像", "heif": "HEIF 图像",
    "cr2": "CR2 图像", "cr3": "CR3 图像",
    "nef": "NEF 图像", "nrw": "NRW 图像",
    "arw": "ARW 图像", "srf": "SRF 图像",
    "dng": "DNG 图像", "orf": "ORF 图像",
    "raf": "RAF 图像", "rw2": "RW2 图像",
    "pef": "PEF 图像", "x3f": "X3F 图像",
    "psd": "PSD 图像", "psb": "PSB 图像",
    "ai": "Adobe Illustrator 文档",
    "eps": "EPS 文件",
    "mp4": "MP4 视频", "mov": "MOV 视频", "avi": "AVI 视频",
    "mkv": "MKV 视频", "wmv": "WMV 视频", "flv": "FLV 视频",
    "webm": "WebM 视频", "m4v": "M4V 视频",
    "mpeg": "MPEG 视频", "mpg": "MPG 视频",
    "mxf": "MXF 视频", "3gp": "3GP 视频",
    "vob": "VOB 视频", "m2ts": "M2TS 视频",
    "ts": "TS 视频", "mts": "MTS 视频", "divx": "DivX 视频",
    "mp3": "MP3 音频", "wav": "WAV 音频",
    "flac": "FLAC 音频", "ogg": "OGG 音频",
    "wma": "WMA 音频", "aac": "AAC 音频",
    "m4a": "M4A 音频", "opus": "Opus 音频",
    "mid": "MIDI 序列", "midi": "MIDI 序列",
    "ape": "APE 音频", "ac3": "AC3 音频",
    "tta": "TTA 音频", "dts": "DTS 音频",
    "aiff": "AIFF 音频",
    "zip": "Zip 压缩文件", "rar": "RAR 压缩文件",
    "7z": "7z 压缩文件", "tar": "TAR 压缩文件",
    "gz": "GZip 压缩文件", "bz2": "BZip2 压缩文件",
    "xz": "XZ 压缩文件", "lzma": "LZMA 压缩文件",
    "zst": "Zstd 压缩文件", "lz4": "LZ4 压缩文件",
    "iso": "ISO 镜像", "cab": "CAB 压缩文件",
    "arj": "ARJ 压缩文件", "tgz": "TGZ 压缩文件",
    "ttf": "TTF 字体", "otf": "OTF 字体",
    "woff": "WOFF 字体", "woff2": "WOFF2 字体",
    "eot": "EOT 字体",
    "exe": "应用程序", "dll": "应用程序扩展",
    "msi": "Windows Installer 包",
    "lnk": "快捷方式", "url": "Internet 快捷方式",
    "torrent": "BitTorrent 文件",
    "apk": "APK 安装包",
    "dmg": "DMG 磁盘映像",
    "deb": "DEB 安装包", "rpm": "RPM 安装包",
    "appimage": "AppImage 映像",
    "db": "数据库文件", "sqlite": "SQLite 数据库",
    "srt": "SRT 字幕", "ass": "ASS 字幕", "ssa": "SSA 字幕",
    "vtt": "WebVTT 字幕",
    "log": "日志文件", "ini": "INI 配置",
    "cfg": "配置文件", "conf": "配置文件",
    "reg": "注册表项",
}


def _get_file_type_display(suffix, is_dir=False):
    if is_dir:
        return "文件夹"
    if not suffix:
        return "文件"
    suffix_lower = suffix.lower()
    if suffix_lower in _FILE_TYPE_MAP:
        return _FILE_TYPE_MAP[suffix_lower]
    return f"{suffix_lower.upper()} 文件"


def _format_file_size_compact(size_bytes):
    if size_bytes < 0:
        size_bytes = 0
    if size_bytes < 1024:
        return f"{int(size_bytes)} B"
    if size_bytes < 1024 * 1024:
        import math
        return f"{int(math.ceil(size_bytes / 1024))} KB"
    if size_bytes < 1024 * 1024 * 1024:
        import math
        return f"{int(math.ceil(size_bytes / (1024 * 1024)))} MB"
    import math
    value = int(math.ceil(size_bytes / (1024 * 1024 * 1024)))
    if value >= 10000:
        return f"{value // 1024} TB"
    return f"{value} GB"


class FileBlockCardDelegate(BaseCardDelegate):
    """
    文件块卡片委托

    特性：
    - 复现 FileBlockCard 的 hover / selected / preview 颜色与切换节奏
    - 动画状态以 file path 为 key，避免排序/筛选/刷新导致串状态
    - 动画定时器仅在存在活动动画时运行，空闲时自动停止
    """

    def _format_file_size(self, size_bytes):
        if size_bytes < 0:
            size_bytes = 0
        if size_bytes < 1024:
            return f"{int(size_bytes)} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def _get_file_info(self, index):
        model = index.model()
        if not model:
            return {}
        if not isinstance(model, FileSelectorListModel):
            return {}
        info = model.get_file_info(index)
        if not info:
            return {}
        info["suffix"] = (str(info.get("suffix", "")) or "").lower()
        info["icon_pixmap"] = model.data(index, model.IconPixmapRole)
        return info

    def _calculate_geometry(self, rect):
        dpi_scale = self._dpi_scale

        border_width = max(1, int(1 * dpi_scale))
        preview_border_width = border_width * 2
        radius = max(1, int(8 * dpi_scale))
        icon_size = int(38 * dpi_scale)
        spacing = int(2 * dpi_scale)
        margins = int(4 * dpi_scale)

        content_rect = rect.adjusted(margins, margins, -margins, -margins)

        icon_rect = QRect(
            content_rect.x() + max(0, (content_rect.width() - icon_size) // 2),
            content_rect.y(),
            min(icon_size, max(0, content_rect.width())),
            icon_size,
        )

        name_h = self.name_font_metrics.height()
        small_h = self.small_font_metrics.height()

        name_rect = QRect(
            content_rect.x(),
            icon_rect.bottom() + 1 + spacing,
            content_rect.width(),
            name_h,
        )
        size_rect = QRect(
            content_rect.x(),
            name_rect.bottom() + 1 + spacing,
            content_rect.width(),
            small_h,
        )
        time_rect = QRect(
            content_rect.x(),
            size_rect.bottom() + 1 + spacing,
            content_rect.width(),
            small_h,
        )

        return {
            "border_width": border_width,
            "preview_border_width": preview_border_width,
            "radius": radius,
            "icon_rect": icon_rect,
            "name_rect": name_rect,
            "size_rect": size_rect,
            "time_rect": time_rect,
        }

    def _paint_card(self, painter, option, index, for_drag_preview=False):
        view = option.widget
        if view and view is not self._view:
            self.set_view(view)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        rect = self._resolve_card_rect(option, index, for_drag_preview=for_drag_preview)
        geometry = self._calculate_geometry(rect)
        file_info = self._get_file_info(index)

        is_selected = file_info.get("is_selected", False)
        is_previewing = file_info.get("is_previewing", False)
        is_hovered = bool(option.state & QStyle.State_MouseOver) and not is_selected and not is_previewing and not for_drag_preview

        anim_key = self._get_animation_key(file_info)
        anim_state = self._sync_animation_state(
            anim_key,
            file_info,
            is_hovered,
            is_selected,
            is_previewing,
        )

        file_path = self._normalize_path(file_info.get("path", ""))
        is_dragging_source = bool(self._dragging_file_path and file_path == self._dragging_file_path and not for_drag_preview)

        bg_color, border_color, shadow_color, shadow_blur, border_width, content_opacity = self._get_paint_colors(
            geometry,
            is_selected,
            is_previewing,
            anim_state,
            is_dragging_source=is_dragging_source,
            for_drag_preview=for_drag_preview,
        )

        self._draw_shadow(painter, rect, geometry["radius"], shadow_color, shadow_blur)

        draw_rect = QRectF(rect).adjusted(
            border_width / 2.0,
            border_width / 2.0,
            -border_width / 2.0,
            -border_width / 2.0,
        )

        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(bg_color)
        painter.drawRoundedRect(draw_rect, geometry["radius"], geometry["radius"])

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_scaled_pixmap(painter, geometry["icon_rect"], icon_pixmap, content_opacity)

        painter.setPen(self._text_color)
        painter.setOpacity(content_opacity)
        painter.setFont(self.name_font)

        name_text = file_info.get("name", "")
        elided_name = self.name_font_metrics.elidedText(
            name_text,
            Qt.ElideRight,
            geometry["name_rect"].width(),
        )
        painter.drawText(
            geometry["name_rect"],
            Qt.AlignCenter | Qt.TextSingleLine,
            elided_name,
        )

        painter.setFont(self.small_font)

        if file_info.get("is_dir", False):
            size_text = "文件夹"
        else:
            size_text = self._format_file_size(file_info.get("size", 0))
        painter.drawText(
            geometry["size_rect"],
            Qt.AlignCenter | Qt.TextSingleLine,
            size_text,
        )

        created_time = self._format_created_text(file_info.get("created", ""))
        painter.drawText(
            geometry["time_rect"],
            Qt.AlignCenter | Qt.TextSingleLine,
            created_time,
        )

        painter.restore()

    def sizeHint(self, option, index):
        dpi_scale = self._dpi_scale

        min_height = int(75 * dpi_scale)
        icon_size = int(38 * dpi_scale)
        name_font_height = self.name_font_metrics.height()
        small_font_height = self.small_font_metrics.height()

        labels_height = name_font_height + (small_font_height * 2)
        spacing = int(2 * dpi_scale)
        total_spacing = spacing * 3
        vertical_margins = int(4 * dpi_scale) * 2
        border_width = int(1 * dpi_scale) * 2

        required_height = icon_size + labels_height + total_spacing + vertical_margins + border_width
        height = max(required_height, min_height)

        model = index.model()
        card_width = model.data(index, Qt.UserRole + 10) if model else None
        if card_width and card_width > 0:
            width = card_width
        else:
            base_min_width = int(50 * dpi_scale)
            date_text_width = self.small_font_metrics.horizontalAdvance("2024-12-31")
            char_width = self.small_font_metrics.horizontalAdvance("W")
            horizontal_margins = int(4 * dpi_scale) * 2
            border_w = int(1 * dpi_scale) * 2
            required_width = date_text_width + char_width + horizontal_margins + border_w
            width = max(required_width, base_min_width)

        return QSize(width, height)
