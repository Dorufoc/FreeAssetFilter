#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

FileIconManager — SVG 图标管线 + L1/L2 缓存 + 未知文件文字叠加
四层架构的服务层，负责所有文件类型图标的统一生成、缓存和分发。
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Dict, Optional

from PySide6.QtCore import QObject, Qt, QRectF, Signal
from PySide6.QtGui import (
    QPixmap,
    QPixmapCache,
    QPainter,
    QFont,
    QFontMetrics,
    QColor,
    QFontDatabase,
)
from PySide6.QtSvg import QSvgRenderer

from freeassetfilter.core.managers.settings_manager import SettingsManager
from freeassetfilter.core.managers.thumbnail_manager import get_existing_thumbnail_path
from freeassetfilter.core.preview.svg_renderer import SvgRenderer
from freeassetfilter.utils.async_icon_loader import AsyncIconLoader
from freeassetfilter.utils.file_icon_helper import get_file_icon_path


class FileIconManager(QObject):
    """SVG 图标管线管理器（线程安全单例）。

    提供完整的 SVG 图标生成管线：
    - 基于文件信息（suffix、is_dir）获取对应图标 SVG 路径
    - 通过 SvgRenderer 渲染为 QPixmap（含主题色替换）
    - 未知文件/压缩包自动叠加文字标识
    - 双层缓存：L1 OrderedDict(256) + L2 QPixmapCache
    - 缓存键包含 5 个主题色，主题变更时自动失效

    Signals:
        system_icon_loaded(str): 系统图标异步加载完成通知（预留 Todo 2）
    """

    _instance: Optional[FileIconManager] = None
    _lock = threading.Lock()
    _initialized = False
    _ICON_CACHE_MAX_ENTRIES: int = 256

    system_icon_loaded = Signal(str)  # 系统图标异步加载完成通知

    # 文件后缀常量集合
    _PHOTO_SUFFIXES = frozenset({
        "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg",
        "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb",
    })
    _VIDEO_SUFFIXES = frozenset({
        "mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf",
    })
    _SYSTEM_ICON_SUFFIXES = frozenset({"lnk", "exe", "url"})

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    def __new__(cls, *args, parent=None) -> FileIconManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls, *args)
            return cls._instance

    def __init__(self, parent=None) -> None:
        with self._lock:
            if self._initialized:
                return
            super().__init__(parent)
            self._initialized = True
            self._icon_cache: OrderedDict = OrderedDict()
            self._cache_lock = threading.Lock()
            self._system_icon_cache: Dict[str, QPixmap] = {}
            self._system_icon_cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_icon_pixmap(self, file_info: dict, icon_size: int, dpr: float) -> QPixmap:
        """获取文件图标 QPixmap（完整的 SVG 解析 → 缩略图 → 缓存管线）。

        优先级：
        1. 目录 → 文件夹 SVG 图标
        2. 照片/视频 → 优先返回已存在的缩略图
        3. 系统图标（exe/lnk/url）→ SVG 占位符 + 触发异步加载
        4. 其他 → SVG 图标（含未知文件文字叠加）

        Args:
            file_info: 文件信息字典（必须含 ``suffix``、``is_dir`` 等字段）。
            icon_size: 图标逻辑尺寸（物理像素 = icon_size × dpr）。
            dpr: 设备像素比。

        Returns:
            渲染完成的 QPixmap；失败时返回空 QPixmap。
        """
        return self._get_icon_pixmap_impl(file_info, icon_size, dpr, _trigger_async=True)

    def _get_icon_pixmap_impl(
        self,
        file_info: dict,
        icon_size: int,
        dpr: float,
        _trigger_async: bool = True,
    ) -> QPixmap:
        """``get_icon_pixmap`` 的内部实现，支持控制是否触发异步加载。

        Args:
            file_info: 文件信息字典。
            icon_size: 图标逻辑尺寸。
            dpr: 设备像素比。
            _trigger_async: 是否触发系统图标的异步加载（预加载时设为 False）。

        Returns:
            渲染完成的 QPixmap。
        """
        # 1. 确定 suffix
        is_dir = file_info.get("is_dir", False)
        if is_dir:
            suffix = "dir"
        else:
            suffix = str(file_info.get("suffix", "")).lower()

        file_path = file_info.get("path", "")

        # 2. 获取 SVG 路径
        icon_path = get_file_icon_path(file_info)
        if not icon_path or not os.path.exists(icon_path):
            return QPixmap()

        # 3. 读取主题色
        base_color, auxiliary_color, normal_color, accent_color, secondary_color = (
            self._get_theme_colors()
        )

        # 4. 构建缓存键（含全部 5 个主题色 → 主题变更自动失效）
        cache_key = (
            "svg",
            suffix,
            icon_size,
            dpr,
            base_color,
            auxiliary_color,
            normal_color,
            accent_color,
            secondary_color,
        )

        # 5. L1 缓存查询（OrderedDict，线程安全）
        with self._cache_lock:
            cached = self._icon_cache.get(cache_key)
            if cached is not None and not cached.isNull():
                self._icon_cache.move_to_end(cache_key)
                return cached

        # 6. L2 缓存查询（QPixmapCache）
        qp_cache_key = f"faf_fim_{hash(cache_key)}"
        qp_cached = QPixmap()
        if QPixmapCache.find(qp_cache_key, qp_cached) and not qp_cached.isNull():
            with self._cache_lock:
                self._icon_cache[cache_key] = qp_cached
                self._icon_cache.move_to_end(cache_key)
                self._trim_cache()
            return qp_cached

        # ── 缩略图回退 ──────────────────────────────────────────────────
        # 照片 / 视频优先使用已存在的磁盘缩略图
        if not is_dir and (suffix in self._PHOTO_SUFFIXES or suffix in self._VIDEO_SUFFIXES):
            thumb_path = get_existing_thumbnail_path(file_path)
            if thumb_path and os.path.exists(thumb_path):
                pixmap = QPixmap(thumb_path)
                if pixmap and not pixmap.isNull():
                    with self._cache_lock:
                        self._icon_cache[cache_key] = pixmap
                        self._icon_cache.move_to_end(cache_key)
                        self._trim_cache()
                    QPixmapCache.insert(qp_cache_key, pixmap)
                    return pixmap

        # ── 系统图标缓存（exe / lnk / url） ────────────────────────────
        is_system_type = not is_dir and suffix in self._SYSTEM_ICON_SUFFIXES
        if is_system_type:
            with self._system_icon_cache_lock:
                sys_cached = self._system_icon_cache.get(file_path)
                if sys_cached is not None and not sys_cached.isNull():
                    return sys_cached

        # 7. 计算图标（SVG 管线）
        icon_path_lower = icon_path.replace("\\", "/")
        is_unknown = "未知底板" in icon_path_lower
        is_archive = "压缩文件" in icon_path_lower

        if is_dir:
            pixmap = SvgRenderer.render_svg_to_exact_pixmap(
                icon_path,
                icon_width=icon_size,
                icon_height=icon_size,
                replace_colors=True,
                device_pixel_ratio=dpr,
            )
        elif is_unknown or is_archive:
            if is_unknown:
                display_text = suffix.upper() if suffix else ""
                if not display_text or len(display_text) >= 5:
                    display_text = "FILE"
            else:
                display_text = f".{suffix}" if suffix else ""
                if not display_text or len(display_text) >= 5:
                    display_text = "FILE"
            pixmap = self._build_unknown_icon_pixmap(
                icon_path, display_text, icon_size, dpr, base_color,
            )
        else:
            pixmap = SvgRenderer.render_svg_to_exact_pixmap(
                icon_path,
                icon_width=icon_size,
                icon_height=icon_size,
                replace_colors=True,
                device_pixel_ratio=dpr,
            )

        # ── 系统图标：缓存占位符 + 触发异步加载 ──────────────────────
        if is_system_type and pixmap and not pixmap.isNull():
            with self._system_icon_cache_lock:
                self._system_icon_cache[file_path] = pixmap
            if _trigger_async:
                self._request_async_system_icon(file_path, icon_size, dpr)

        # 8. 存入双层缓存
        if pixmap and not pixmap.isNull():
            with self._cache_lock:
                self._icon_cache[cache_key] = pixmap
                self._icon_cache.move_to_end(cache_key)
                self._trim_cache()
            QPixmapCache.insert(qp_cache_key, pixmap)
            return pixmap

        return QPixmap()

    def get_icon_path(self, file_info: dict) -> str:
        """获取文件对应的 SVG 图标路径（委托给 file_icon_helper）。"""
        return get_file_icon_path(file_info)

    def clear_cache(self, file_path: str = None) -> None:
        """清除缓存。

        Args:
            file_path: 如果为 ``None``，清除全部缓存（L1 + L2 + 系统图标）；
                       如果提供，仅清除 L1 缓存。
        """
        with self._cache_lock:
            if file_path is None:
                self._icon_cache.clear()
                with self._system_icon_cache_lock:
                    self._system_icon_cache.clear()
                QPixmapCache.clear()
            else:
                self._icon_cache.clear()

    def preload_icons(self, file_infos: list, icon_size: int, dpr: float) -> None:
        """预加载图标到缓存。

        遍历文件列表：
        - 系统图标（exe/lnk/url）：生成 SVG 占位符，分批（每 10 个）触发异步加载
        - 其他类型：直接调用 ``get_icon_pixmap`` 预热缓存

        Args:
            file_infos: 文件信息字典列表。
            icon_size: 图标尺寸。
            dpr: 设备像素比。
        """
        system_icon_batch: list[tuple[str, int, float]] = []

        for file_info in file_infos:
            suffix = str(file_info.get("suffix", "")).lower()
            is_dir = file_info.get("is_dir", False)

            if not is_dir and suffix in self._SYSTEM_ICON_SUFFIXES:
                file_path = file_info.get("path", "")
                with self._system_icon_cache_lock:
                    cached = self._system_icon_cache.get(file_path)
                if cached is not None and not cached.isNull():
                    continue

                # 生成 SVG 占位符（不触发单个异步）
                self._get_icon_pixmap_impl(
                    file_info, icon_size, dpr, _trigger_async=False,
                )
                system_icon_batch.append((file_path, icon_size, dpr))
            else:
                self._get_icon_pixmap_impl(
                    file_info, icon_size, dpr, _trigger_async=True,
                )

        # 分批提交异步加载请求（每批 10 个）
        for i in range(0, len(system_icon_batch), 10):
            batch = system_icon_batch[i:i + 10]
            for file_path, sz, dp in batch:
                self._request_async_system_icon(file_path, sz, dp)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_theme_colors(self) -> tuple:
        """从 SettingsManager 读取 5 个主题色。"""
        sm = SettingsManager()
        base_color = sm.get_setting("appearance.colors.base_color", "#FFFFFF")
        auxiliary_color = sm.get_setting("appearance.colors.auxiliary_color", "#f1f3f5")
        normal_color = sm.get_setting("appearance.colors.normal_color", "#e0e0e0")
        accent_color = sm.get_setting("appearance.colors.accent_color", "#007AFF")
        secondary_color = sm.get_setting("appearance.colors.secondary_color", "#333333")
        return base_color, auxiliary_color, normal_color, accent_color, secondary_color

    @staticmethod
    def _get_icon_style() -> int:
        """从 SettingsManager 读取图标样式索引。"""
        sm = SettingsManager()
        return sm.get_setting("appearance.icon_style", 3)

    # ------------------------------------------------------------------
    # System icon async loading
    # ------------------------------------------------------------------

    def _request_async_system_icon(
        self, file_path: str, icon_size: int, dpr: float
    ) -> None:
        """触发系统图标异步加载（用于 exe/lnk/url）。

        通过 ``AsyncIconLoader`` 在后台线程中提取 Windows 系统图标，
        加载完成后存入 ``_system_icon_cache`` 并发射 ``system_icon_loaded`` 信号。

        Args:
            file_path: 文件路径。
            icon_size: 图标尺寸。
            dpr: 设备像素比（当前仅用于信号载荷，加载器以 icon_size 为准）。
        """
        loader = AsyncIconLoader.instance()
        loader.load_icon(file_path, self._on_system_icon_loaded, icon_size=icon_size)

    def _on_system_icon_loaded(self, file_path: str, pixmap) -> None:
        """系统图标异步加载完成回调。

        Args:
            file_path: 文件路径。
            pixmap: 加载完成的 QPixmap（失败时可能为 None）。
        """
        if pixmap is None or pixmap.isNull():
            return

        with self._system_icon_cache_lock:
            self._system_icon_cache[file_path] = pixmap

        self.system_icon_loaded.emit(file_path)

    def _trim_cache(self) -> None:
        """裁剪 L1 缓存至最大条目数（LRU 淘汰）。"""
        while len(self._icon_cache) > self._ICON_CACHE_MAX_ENTRIES:
            self._icon_cache.popitem(last=False)

    def _build_unknown_icon_pixmap(
        self,
        icon_path: str,
        text: str,
        icon_size: int,
        dpr: float = 1.0,
        base_color: str = "#212121",
    ) -> QPixmap:
        """构建未知类型文件/压缩包的图标（SVG 底板 + 中央粗体文字叠加）。

        此方法从 ``FileBlockCard._build_unknown_icon_pixmap_static()`` 提取。
        # NOTE: extracted from FileBlockCard

        Args:
            icon_path: SVG 底板文件路径。
            text: 要叠加的文本（例如 "MP4"、".zip"）。
            icon_size: 逻辑尺寸。
            dpr: 设备像素比。
            base_color: 主题基础色（用于统一样式的文字颜色）。

        Returns:
            合成完成的 QPixmap。
        """
        # NOTE: extracted from FileBlockCard._build_unknown_icon_pixmap_static()
        physical_canvas_size = max(1, int(round(icon_size * dpr)))
        base_pixmap = SvgRenderer.render_svg_to_exact_pixmap(
            icon_path,
            icon_width=icon_size,
            icon_height=icon_size,
            replace_colors=True,
            device_pixel_ratio=dpr,
        )

        final_pixmap = QPixmap(physical_canvas_size, physical_canvas_size)
        final_pixmap.fill(Qt.transparent)

        painter = QPainter(final_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawPixmap(
            QRectF(0.0, 0.0, float(physical_canvas_size), float(physical_canvas_size)),
            base_pixmap,
            QRectF(0.0, 0.0, float(base_pixmap.width()), float(base_pixmap.height())),
        )

        if text:
            font = QFont()
            font.setBold(True)
            base_font_pixel_size = max(1, int(physical_canvas_size * 0.234))
            min_font_pixel_size = max(1, int(physical_canvas_size * 0.15))
            font.setPixelSize(base_font_pixel_size)

            font_metrics = QFontMetrics(font)
            text_width = font_metrics.horizontalAdvance(text)
            text_height = font_metrics.height()

            while (
                (text_width > physical_canvas_size * 0.8 or text_height > physical_canvas_size * 0.8)
                and base_font_pixel_size > min_font_pixel_size
            ):
                base_font_pixel_size -= 1
                font.setPixelSize(base_font_pixel_size)
                font_metrics = QFontMetrics(font)
                text_width = font_metrics.horizontalAdvance(text)
                text_height = font_metrics.height()

            is_unified_style = " – 2.svg" in icon_path
            is_textured_archive = "压缩文件 – 1.svg" in icon_path
            if is_unified_style:
                text_color = QColor(base_color)
            elif icon_path.endswith("压缩文件.svg") or is_textured_archive:
                text_color = QColor(255, 255, 255)
            else:
                text_color = QColor(0, 0, 0)

            painter.setPen(text_color)
            painter.setFont(font)
            painter.drawText(
                QRectF(0.0, 0.0, float(physical_canvas_size), float(physical_canvas_size)),
                Qt.AlignCenter,
                text,
            )

        painter.end()
        final_pixmap.setDevicePixelRatio(dpr)
        return final_pixmap


__all__ = [
    "FileIconManager",
]
