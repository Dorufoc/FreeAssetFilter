#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileCardDelegate — 文件卡片委托，视觉风格精确匹配 StyledInfoCard。

两种模式：
- card (grid): 宽>高，icon 在上，文字在下
- list (horizontal): 高<宽，icon 在左，文字在右

所有颜色从 tm 获取，零硬编码。
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QStyleOptionViewItem

from theme import tm

from components.file_list_model import (
    FileNameRole,
    FilePathRole,
    IsDirRole,
    FileSizeRole,
    ModifiedRole,
    SuffixRole,
    IsSelectedRole,
    IsPreviewingRole,
    IconPixmapRole,
    CardWidthRole,
    GridOffsetRole,
)

# ── 文件类型映射 ──────────────────────────────────────────────────────────────

_FILE_TYPE_MAP: Dict[str, str] = {
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


def _get_file_type_display(suffix: str, is_dir: bool = False) -> str:
    if is_dir:
        return "文件夹"
    if not suffix:
        return "文件"
    suffix_lower = suffix.lower()
    if suffix_lower in _FILE_TYPE_MAP:
        return _FILE_TYPE_MAP[suffix_lower]
    return f"{suffix_lower.upper()} 文件"


def _get_colors() -> Dict[str, Any]:
    return {
        "bg": tm.alpha_of(tm.surface, 85),
        "bg_hover": tm.alpha_of(tm.surface, 90),
        "border": tm.alpha_of(tm.mid, 30),
        "media_bg": tm.alpha_of(tm.mid, 40),
        "title": tm.text,
        "subtitle": tm.mid,
        "desc": tm.alpha_of(tm.mid, 60),
        "icon": tm.mid,
        "accent": tm.accent,
        "selected_border": tm.accent,
        "shadow": QColor(0, 0, 0, 40),
    }


CARD_CONFIG: Dict[str, Any] = {
    "padding": 8,
    "gap": 6,
    "radius": 6,
    "media_size": 44,
    "icon_size": 20,
    "title_size": 10,
    "title_weight": 400,
    "subtitle_size": 9,
    "subtitle_weight": 400,
    "desc_size": 9,
    "desc_weight": 400,
}

LIST_CONFIG: Dict[str, Any] = {
    "padding": 12,
    "gap": 10,
    "radius": 6,
    "media_size": 40,
    "icon_size": 20,
    "title_size": 10,
    "title_weight": 700,
    "subtitle_size": 9,
    "subtitle_weight": 400,
    "desc_size": 9,
    "desc_weight": 400,
}


class FileCardDelegate(QStyledItemDelegate):
    """文件卡片委托，支持 card（网格）和 list（列表）两种模式。

    关键：QStyledItemDelegate 的 painter 不做坐标平移，option.rect 包含视口绝对坐标。
    所有绘制必须基于 option.rect 的 x/y 偏移，不能假设 (0, 0) 为原点。
    """

    def __init__(self, parent: Optional[object] = None) -> None:
        super().__init__(parent)
        self._layout_mode: str = "card"
        self._card_scale: float = 1.0

    def set_card_mode(self) -> None:
        self._layout_mode = "card"

    def set_list_mode(self) -> None:
        self._layout_mode = "list"

    def set_card_scale(self, scale: float) -> None:
        self._card_scale = scale

    # ── 图标绘制 ──────────────────────────────────────────────────────────

    @staticmethod
    def _draw_icon_pixmap(
        painter: QPainter,
        icon_pixmap: object,
        media_rect: QRectF,
    ) -> None:
        """在 media 区域中居中绘制图标，完整填充背景区。

        设计原则：
        - 图标在 media 区域中严格居中（考虑 DPR 转换逻辑尺寸）
        - 完整填充 media 背景区域，无额外内边距
        - 自适应缩放：超出 display 尺寸时等比缩放适配
        - DPR 感知：QPixmap.width() 返回物理像素，需除以 DPR 得到逻辑尺寸

        Args:
            painter: 已激活的 QPainter。
            icon_pixmap: 要绘制的 QPixmap。
            media_rect: media 背景区域的 QRectF（逻辑坐标）。
        """
        dpr = icon_pixmap.devicePixelRatio()
        logical_w = icon_pixmap.width() / dpr
        logical_h = icon_pixmap.height() / dpr

        # 图标显示尺寸 = media 区域全尺寸（无内边距）
        display_size = int(media_rect.width())

        # 自适应缩放：仅当图标逻辑尺寸超出显示尺寸时才缩放
        if logical_w > display_size or logical_h > display_size:
            icon_pixmap = icon_pixmap.scaled(
                display_size, display_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            # 缩放后的 pixmap 保持原 DPR，重新计算逻辑尺寸
            dpr = icon_pixmap.devicePixelRatio()
            logical_w = icon_pixmap.width() / dpr
            logical_h = icon_pixmap.height() / dpr

        # 在 media 区域中居中（使用逻辑尺寸）
        offset_x = int(media_rect.x() + (media_rect.width() - logical_w) / 2.0)
        offset_y = int(media_rect.y() + (media_rect.height() - logical_h) / 2.0)
        painter.drawPixmap(offset_x, offset_y, icon_pixmap)

    # ── 文件信息读取 ───────────────────────────────────────────────────────

    @staticmethod
    def _get_file_info(index: QModelIndex) -> Dict[str, Any]:
        model = index.model()
        if not model:
            return {}
        return {
            "name": model.data(index, FileNameRole) or "",
            "path": model.data(index, FilePathRole) or "",
            "is_dir": bool(model.data(index, IsDirRole)),
            "size": int(model.data(index, FileSizeRole) or 0),
            "modified": model.data(index, ModifiedRole) or "",
            "suffix": (model.data(index, SuffixRole) or "").lower(),
            "is_selected": bool(model.data(index, IsSelectedRole)),
            "is_previewing": bool(model.data(index, IsPreviewingRole)),
            "icon_pixmap": model.data(index, IconPixmapRole),
        }

    # ── sizeHint ────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_card_size(config: Dict[str, Any], scale: float = 1.0) -> tuple:
        """根据配置计算卡片默认宽度和高度（支持双行文件名）。"""
        padding = int(config["padding"] * scale)
        gap = int(config["gap"] * scale)
        media_size = int(config["media_size"] * scale)
        font_title = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
        line_height = QFontMetrics(font_title).height() + 2  # 行高 + 行间距
        text_height = line_height * 2  # 双行
        width = padding * 2 + media_size
        height = padding * 2 + media_size + gap + text_height
        return width, height

    @staticmethod
    def _calc_list_size(config: Dict[str, Any], scale: float = 1.0) -> tuple:
        """根据配置计算列表模式默认宽度和高度（仅一行文件名）。"""
        padding = int(config["padding"] * scale)
        media_size = int(config["media_size"] * scale)
        font_title = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
        text_height = QFontMetrics(font_title).height() + 4
        width = 200
        height = padding * 2 + max(media_size, text_height)
        return width, height

    def sizeHint(
        self,
        option: Optional[QStyleOptionViewItem],
        index: Optional[QModelIndex],
    ) -> QSize:
        if self._layout_mode == "card":
            config = CARD_CONFIG
            if index is not None and index.isValid():
                model = index.model()
                if model is not None:
                    card_width = model.data(index, CardWidthRole)
                    if card_width is not None and int(card_width) > 0:
                        _, height = self._calc_card_size(config, self._card_scale)
                        return QSize(int(card_width), height)
            width, height = self._calc_card_size(config, self._card_scale)
            return QSize(width, height)
        else:
            config = LIST_CONFIG
            if index is not None and index.isValid():
                model = index.model()
                if model is not None:
                    card_width = model.data(index, CardWidthRole)
                    if card_width is not None and int(card_width) > 0:
                        _, height = self._calc_list_size(config, self._card_scale)
                        return QSize(int(card_width), height)
            width, height = self._calc_list_size(config, self._card_scale)
            return QSize(width, height)

    # ── paint ────────────────────────────────────────────────────────────

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        # 将绘制严格限制在 item 的 grid cell 内，避免 hover 时阴影/背景
        # 因网格偏移溢出到相邻 item 区域而形成残影
        painter.setClipRect(option.rect)

        file_info = self._get_file_info(index)
        is_selected = file_info.get("is_selected", False)
        is_previewing = file_info.get("is_previewing", False)
        is_hovered = bool(option.state & QStyle.State_MouseOver)

        card_rect = self._resolve_card_rect(option, index)

        if self._layout_mode == "card":
            self._paint_card(painter, card_rect, file_info, is_hovered, is_selected, is_previewing)
        else:
            self._paint_list(painter, card_rect, file_info, is_hovered, is_selected, is_previewing)

        painter.restore()

    def _resolve_card_rect(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QRect:
        """解析卡片最终绘制矩形（在 grid cell 内居中）。"""
        rect = QRect(option.rect)
        target_size = self.sizeHint(option, index)
        if not target_size.isValid():
            return rect
        target_width = min(rect.width(), target_size.width())
        target_height = min(rect.height(), target_size.height())
        offset_x = max(0, (rect.width() - target_width + 1) // 2)
        offset_y = max(0, (rect.height() - target_height) // 2)

        return QRect(
            rect.x() + offset_x,
            rect.y() + offset_y,
            target_width,
            target_height,
        )

    def _get_scaled_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        scale = self._card_scale
        return {
            "padding": int(config["padding"] * scale),
            "gap": int(config["gap"] * scale),
            "radius": max(1, int(config["radius"] * scale)),
            "media_size": int(config["media_size"] * scale),
            "icon_size": max(1, int(config["icon_size"] * scale)),
            "title_size": config["title_size"],
            "title_weight": config["title_weight"],
            "subtitle_size": config["subtitle_size"],
            "subtitle_weight": config["subtitle_weight"],
            "desc_size": config["desc_size"],
            "desc_weight": config["desc_weight"],
        }

    def _paint_card(
        self,
        painter: QPainter,
        rect: QRect,
        file_info: Dict[str, Any],
        is_hovered: bool,
        is_selected: bool,
        is_previewing: bool,
    ) -> None:
        colors = _get_colors()
        config = self._get_scaled_config(CARD_CONFIG)
        padding = config["padding"]
        radius = config["radius"]
        gap = config["gap"]
        media_size = config["media_size"]

        rx = rect.x()
        ry = rect.y()
        w = rect.width()
        h = rect.height()
        card_rect = QRectF(rx, ry, w, h)

        # 背景
        bg_color = colors["bg_hover"] if (is_hovered or is_selected or is_previewing) else colors["bg"]
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(card_rect, radius, radius)

        # 边框
        painter.setBrush(Qt.NoBrush)
        if is_previewing and is_selected:
            painter.setPen(QPen(colors["accent"], 2))
            painter.drawRoundedRect(card_rect, radius, radius)
            painter.setPen(QPen(colors["selected_border"], 3))
            painter.drawLine(rx + radius, ry, rx + radius, ry + h)
        elif is_previewing:
            painter.setPen(QPen(colors["accent"], 2))
            painter.drawRoundedRect(card_rect, radius, radius)
        elif is_selected:
            painter.setPen(QPen(colors["border"], 1))
            painter.drawRoundedRect(card_rect, radius, radius)
            painter.setPen(QPen(colors["selected_border"], 3))
            painter.drawLine(rx + radius, ry, rx + radius, ry + h)
        else:
            painter.setPen(QPen(colors["border"], 1))
            painter.drawRoundedRect(card_rect, radius, radius)

        # 阴影
        if is_hovered and not is_selected and not is_previewing:
            painter.setPen(Qt.NoPen)
            painter.setBrush(colors["shadow"])
            painter.drawRoundedRect(QRectF(rx, ry + 2, w, h), radius, radius)

        # Media 区域
        media_x = rx + (w - media_size) / 2.0
        media_y = ry + padding
        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["media_bg"])
        painter.drawRoundedRect(QRectF(media_x, media_y, media_size, media_size), 4, 4)

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_icon_pixmap(
                painter,
                icon_pixmap,
                QRectF(media_x, media_y, media_size, media_size),
            )
        else:
            suffix = file_info.get("suffix", "")
            is_dir = file_info.get("is_dir", False)
            icon_char = "D" if is_dir else (suffix[0].upper() if suffix else "?")
            painter.setFont(QFont("Segoe UI", config["icon_size"], QFont.Bold))
            painter.setPen(colors["icon"])
            painter.drawText(QRectF(media_x, media_y, media_size, media_size), Qt.AlignCenter, icon_char)

        # 文字区域
        text_x = rx + padding
        text_y = media_y + media_size + gap
        text_w = w - padding * 2
        text_h = h - (text_y - ry) - padding
        self._draw_text(painter, QRectF(text_x, text_y, text_w, text_h), config, file_info, align=Qt.AlignCenter)

    def _paint_list(
        self,
        painter: QPainter,
        rect: Any,
        file_info: Dict[str, Any],
        is_hovered: bool,
        is_selected: bool,
        is_previewing: bool,
    ) -> None:
        colors = _get_colors()
        config = self._get_scaled_config(LIST_CONFIG)
        padding = config["padding"]
        radius = config["radius"]
        gap = config["gap"]
        media_size = config["media_size"]

        rx = rect.x()
        ry = rect.y()
        w = rect.width()
        h = rect.height()
        card_rect = QRectF(rx, ry, w, h)

        # 背景
        bg_color = colors["bg_hover"] if (is_hovered or is_selected or is_previewing) else colors["bg"]
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(card_rect, radius, radius)

        # 边框
        painter.setBrush(Qt.NoBrush)
        if is_previewing and is_selected:
            painter.setPen(QPen(colors["accent"], 2))
            painter.drawRoundedRect(card_rect, radius, radius)
            painter.setPen(QPen(colors["selected_border"], 3))
            painter.drawLine(rx + radius, ry, rx + radius, ry + h)
        elif is_previewing:
            painter.setPen(QPen(colors["accent"], 2))
            painter.drawRoundedRect(card_rect, radius, radius)
        elif is_selected:
            painter.setPen(QPen(colors["border"], 1))
            painter.drawRoundedRect(card_rect, radius, radius)
            painter.setPen(QPen(colors["selected_border"], 3))
            painter.drawLine(rx + radius, ry, rx + radius, ry + h)
        else:
            painter.setPen(QPen(colors["border"], 1))
            painter.drawRoundedRect(card_rect, radius, radius)

        # 阴影
        if is_hovered and not is_selected and not is_previewing:
            painter.setPen(Qt.NoPen)
            painter.setBrush(colors["shadow"])
            painter.drawRoundedRect(QRectF(rx, ry + 2, w, h), radius, radius)

        # Media 区域（左）
        media_x = rx + padding
        media_y = ry + (h - media_size) / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["media_bg"])
        painter.drawRoundedRect(QRectF(media_x, media_y, media_size, media_size), 4, 4)

        icon_pixmap = file_info.get("icon_pixmap")
        if icon_pixmap and not icon_pixmap.isNull():
            self._draw_icon_pixmap(
                painter,
                icon_pixmap,
                QRectF(media_x, media_y, media_size, media_size),
            )
        else:
            suffix = file_info.get("suffix", "")
            is_dir = file_info.get("is_dir", False)
            icon_char = "D" if is_dir else (suffix[0].upper() if suffix else "?")
            painter.setFont(QFont("Segoe UI", config["icon_size"], QFont.Bold))
            painter.setPen(colors["icon"])
            painter.drawText(QRectF(media_x, media_y, media_size, media_size), Qt.AlignCenter, icon_char)

        # 文字区域（右）
        text_x = media_x + media_size + gap
        text_y = ry + padding
        text_w = w - padding * 2 - media_size - gap
        text_h = h - padding * 2
        self._draw_text(painter, QRectF(text_x, text_y, text_w, text_h), config, file_info)

    # ── 文字绘制 ──────────────────────────────────────────────────────────

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        config: Dict[str, Any],
        file_info: Dict[str, Any],
        align: int = Qt.AlignLeft,
    ) -> None:
        colors = _get_colors()
        name = file_info.get("name", "")

        font = QFont("Microsoft YaHei UI", config["title_size"], config["title_weight"])
        painter.setFont(font)
        painter.setPen(colors["title"])
        fm = QFontMetrics(font)

        max_w = int(rect.width())
        line_height = fm.height()
        spacing = 2  # 行间距
        two_line_h = line_height * 2 + spacing

        # 单行能放下 → 在双行区域内垂直居中
        if fm.horizontalAdvance(name) <= max_w:
            y_offset = int((two_line_h - line_height) / 2)
            painter.drawText(
                QRectF(rect.x(), rect.y() + y_offset, max_w, line_height),
                align | Qt.AlignVCenter,
                name,
            )
            return

        # 双行：第一行尽量放满，第二行省略
        # 找出第一行能容纳的最大字符数
        first_line = ""
        for i in range(len(name), 0, -1):
            if fm.horizontalAdvance(name[:i]) <= max_w:
                first_line = name[:i]
                break

        painter.drawText(
            QRectF(rect.x(), rect.y(), max_w, line_height),
            align | Qt.AlignTop,
            first_line,
        )

        remaining = name[len(first_line):].strip()
        if remaining:
            second_line = fm.elidedText(remaining, Qt.ElideRight, max_w)
            painter.drawText(
                QRectF(rect.x(), rect.y() + line_height + spacing, max_w, line_height),
                align | Qt.AlignTop,
                second_line,
            )
