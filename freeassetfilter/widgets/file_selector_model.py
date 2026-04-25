#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2025 Dorufoc <qpdrfc123@gmail.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

文件选择器列表模型和视图组件
实现文件列表的数据管理和交互展示
"""

import os
import time
import weakref
from collections import OrderedDict
from typing import Optional, List, Dict, Any

from PySide6.QtCore import (
    Qt,
    Signal,
    QModelIndex,
    QAbstractListModel,
    QSize,
    QItemSelection,
    QItemSelectionModel,
    QTimer,
    QRect,
    QRectF,
    QUrl,
)
from PySide6.QtGui import (
    QBitmap,
    QPixmap,
    QPainter,
    QMouseEvent,
    QContextMenuEvent,
    QDesktopServices,
    QPalette,
    QRegion,
)
from PySide6.QtWidgets import (
    QListView,
    QApplication,
    QLabel,
    QStyle,
    QStyleOptionViewItem,
)

from freeassetfilter.core.settings_manager import SettingsManager
from freeassetfilter.core.svg_renderer import SvgRenderer
from freeassetfilter.core.thumbnail_manager import get_existing_thumbnail_path
from freeassetfilter.utils.async_icon_loader import AsyncIconLoader
from freeassetfilter.utils.file_icon_helper import get_file_icon_path
from freeassetfilter.utils.app_logger import debug


class FileSelectorListModel(QAbstractListModel):
    """
    文件选择器列表数据模型

    自定义角色：
    - FilePathRole: 文件完整路径
    - FileNameRole: 文件名
    - IsDirRole: 是否为目录
    - FileSizeRole: 文件大小
    - CreatedRole: 创建时间
    - SuffixRole: 文件后缀
    - IsSelectedRole: 是否选中
    - IsPreviewingRole: 是否预览中
    - IconPixmapRole: 图标像素图
    - CardWidthRole: 卡片宽度
    """

    FilePathRole = Qt.UserRole + 1
    FileNameRole = Qt.UserRole + 2
    IsDirRole = Qt.UserRole + 3
    FileSizeRole = Qt.UserRole + 4
    CreatedRole = Qt.UserRole + 5
    SuffixRole = Qt.UserRole + 6
    IsSelectedRole = Qt.UserRole + 7
    IsPreviewingRole = Qt.UserRole + 8
    IconPixmapRole = Qt.UserRole + 9
    CardWidthRole = Qt.UserRole + 10

    _ICON_CACHE_MAX_ENTRIES = 256
    _SYSTEM_ICON_RETRY_DELAY_MS = 1000
    _SYSTEM_ICON_SUFFIXES = frozenset({"lnk", "exe", "url"})
    _PHOTO_SUFFIXES = frozenset({
        "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg",
        "avif", "cr2", "cr3", "nef", "arw", "dng", "orf", "psd", "psb",
    })
    _VIDEO_SUFFIXES = frozenset({
        "mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v", "mpeg", "mpg", "mxf",
    })
    _icon_cache = OrderedDict()

    def __init__(self, dpi_scale=1.0, global_font=None, parent=None):
        super().__init__(parent)
        self._files: List[Dict[str, Any]] = []
        self._card_width: int = 150
        self._card_height: int = 75
        self._max_cols: int = 3
        self._dpi_scale = dpi_scale
        self._global_font = global_font
        self._path_to_row: Dict[str, int] = {}
        self._async_loader = AsyncIconLoader.instance()
        self._pending_async_icons: Dict[str, tuple] = {}
        self._system_icon_retry_until: Dict[tuple, float] = {}
        self._attached_view_ref = None

    def _normalize_path(self, file_path: str) -> str:
        return os.path.normpath(file_path) if file_path else ""

    def _rebuild_path_index(self) -> None:
        self._path_to_row.clear()
        for row, file_info in enumerate(self._files):
            normalized_path = self._normalize_path(file_info.get("path", ""))
            if normalized_path:
                self._path_to_row[normalized_path] = row

    def get_row(self, file_path: str) -> int:
        """获取指定文件路径的行号"""
        return self._path_to_row.get(self._normalize_path(file_path), -1)

    def is_selected(self, file_path: str) -> bool:
        """获取指定文件的选中状态"""
        row = self.get_row(file_path)
        if row < 0:
            return False
        return self._files[row].get("is_selected", False)

    def toggle_selected(self, file_path: str) -> bool:
        """切换指定文件的选中状态，返回新的选中状态"""
        row = self.get_row(file_path)
        if row < 0:
            return False

        new_state = not self._files[row].get("is_selected", False)
        self._files[row]["is_selected"] = new_state
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.IsSelectedRole])
        return new_state

    def select_all(self) -> None:
        """选中所有文件"""
        if not self._files:
            return

        changed_rows = []
        for row, file_info in enumerate(self._files):
            if not file_info.get("is_selected", False):
                file_info["is_selected"] = True
                changed_rows.append(row)

        for row in changed_rows:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [self.IsSelectedRole])

    def deselect_all(self) -> None:
        """取消选中所有文件"""
        if not self._files:
            return

        changed_rows = []
        for row, file_info in enumerate(self._files):
            if file_info.get("is_selected", False):
                file_info["is_selected"] = False
                changed_rows.append(row)

        for row in changed_rows:
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [self.IsSelectedRole])

    def set_previewing(self, file_path: str, is_previewing: bool = None) -> None:
        """设置指定文件为预览状态"""
        normalized_target = self._normalize_path(file_path)

        if is_previewing is None:
            for row, file_info in enumerate(self._files):
                current_path = self._normalize_path(file_info.get("path", ""))
                is_preview = current_path == normalized_target
                if file_info.get("is_previewing", False) != is_preview:
                    file_info["is_previewing"] = is_preview
                    idx = self.index(row, 0)
                    self.dataChanged.emit(idx, idx, [self.IsPreviewingRole])
            return

        row = self.get_row(normalized_target)
        if row < 0:
            return

        if self._files[row].get("is_previewing", False) != is_previewing:
            self._files[row]["is_previewing"] = is_previewing
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [self.IsPreviewingRole])

    def update_geometry(self, card_width: int, card_height: int, max_cols: int) -> None:
        """兼容接口：更新卡片几何信息"""
        self.set_card_width(card_width, card_height, max_cols)

    def attach_view(self, view) -> None:
        """关联视图，用于滚动期间的性能优化策略"""
        self._attached_view_ref = weakref.ref(view) if view is not None else None

    def _get_attached_view(self):
        return self._attached_view_ref() if self._attached_view_ref else None

    def _is_scroll_optimizing(self) -> bool:
        view = self._get_attached_view()
        if view is None or not hasattr(view, "is_scroll_optimizing"):
            return False
        try:
            return bool(view.is_scroll_optimizing())
        except Exception:
            return False

    def clear_caches(self, file_path: Optional[str] = None, emit_change: bool = False) -> None:
        """清空缓存，可按文件路径精确失效"""
        if file_path is None:
            self._icon_cache.clear()
            self._pending_async_icons.clear()
            self._system_icon_retry_until.clear()
            if emit_change and self.rowCount() > 0:
                top = self.index(0, 0)
                bottom = self.index(self.rowCount() - 1, 0)
                self.dataChanged.emit(top, bottom, [self.IconPixmapRole])
            return

        normalized_path = self._normalize_path(file_path)
        keys_to_remove = []

        for cache_key in list(self._icon_cache.keys()):
            if not isinstance(cache_key, tuple) or not cache_key:
                continue

            if (
                len(cache_key) == 4
                and cache_key[0] == "system_icon"
                and self._normalize_path(str(cache_key[1])) == normalized_path
            ):
                keys_to_remove.append(cache_key)
                continue

            cache_identity = cache_key[0]
            if not isinstance(cache_identity, tuple) or len(cache_identity) < 4:
                continue

            source_signature = cache_identity[-1]
            if not isinstance(source_signature, tuple) or len(source_signature) < 2:
                continue

            source_path = source_signature[1]
            if source_path and self._normalize_path(str(source_path)) == normalized_path:
                keys_to_remove.append(cache_key)

        for cache_key in keys_to_remove:
            self._icon_cache.pop(cache_key, None)

        self._pending_async_icons.pop(normalized_path, None)
        retry_keys_to_remove = [
            retry_key
            for retry_key in self._system_icon_retry_until.keys()
            if retry_key and self._normalize_path(str(retry_key[0])) == normalized_path
        ]
        for retry_key in retry_keys_to_remove:
            self._system_icon_retry_until.pop(retry_key, None)

        if emit_change:
            self.refresh_icon(file_path)

    def refresh_icon(self, file_path: str) -> bool:
        """按文件路径刷新图标/缩略图显示"""
        row = self.get_row(file_path)
        if row < 0:
            return False

        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.IconPixmapRole])
        return True

    def sizeHint(self) -> QSize:
        """获取模型的建议大小"""
        return QSize(self._card_width, self._card_height)

    def set_files(self, file_list: List[Dict[str, Any]]) -> None:
        """设置文件列表，不进行全量图标预加载，由可视区按需请求"""
        self.beginResetModel()
        self._files = file_list.copy()
        for file_info in self._files:
            file_info.setdefault("is_selected", False)
            file_info.setdefault("is_previewing", False)
        self._rebuild_path_index()
        self.endResetModel()

    def set_card_width(self, width: int, height: int, max_cols: int) -> None:
        """更新卡片尺寸和列数"""
        if self._card_width == width and self._card_height == height and self._max_cols == max_cols:
            return

        self._card_width = width
        self._card_height = height
        self._max_cols = max_cols

        if self.rowCount() > 0:
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, 0)
            self.dataChanged.emit(top, bottom, [self.CardWidthRole])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._files)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._files):
            return None

        file_info = self._files[index.row()]

        if role == Qt.DisplayRole:
            return file_info.get("name", "")
        if role == self.FilePathRole:
            return file_info.get("path", "")
        if role == self.FileNameRole:
            return file_info.get("name", "")
        if role == self.IsDirRole:
            return file_info.get("is_dir", False)
        if role == self.FileSizeRole:
            return file_info.get("size", 0)
        if role == self.CreatedRole:
            return file_info.get("created", "")
        if role == self.SuffixRole:
            return file_info.get("suffix", "").lower()
        if role == self.IsSelectedRole:
            return file_info.get("is_selected", False)
        if role == self.IsPreviewingRole:
            return file_info.get("is_previewing", False)
        if role == self.IconPixmapRole:
            return self._get_icon_pixmap(file_info)
        if role == self.CardWidthRole:
            return self._card_width

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or index.row() >= len(self._files):
            return False

        if role == self.IsSelectedRole:
            self._files[index.row()]["is_selected"] = value
            self.dataChanged.emit(index, index, [role])
            return True

        if role == self.IsPreviewingRole:
            self._files[index.row()]["is_previewing"] = value
            self.dataChanged.emit(index, index, [role])
            return True

        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

    def roleNames(self) -> Dict[int, bytes]:
        return {
            self.FilePathRole: b"filePath",
            self.FileNameRole: b"fileName",
            self.IsDirRole: b"isDir",
            self.FileSizeRole: b"fileSize",
            self.CreatedRole: b"created",
            self.SuffixRole: b"suffix",
            self.IsSelectedRole: b"isSelected",
            self.IsPreviewingRole: b"isPreviewing",
            self.IconPixmapRole: b"iconPixmap",
            self.CardWidthRole: b"cardWidth",
        }

    def set_selected(self, file_path: str, is_selected: bool) -> bool:
        """设置指定文件的选中状态"""
        row = self.get_row(file_path)
        if row < 0:
            return False

        if self._files[row].get("is_selected", False) != is_selected:
            self._files[row]["is_selected"] = is_selected
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [self.IsSelectedRole])
        return True

    def clear_previewing(self) -> None:
        """清除所有文件的预览状态"""
        for row, file_info in enumerate(self._files):
            if file_info.get("is_previewing", False):
                file_info["is_previewing"] = False
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.IsPreviewingRole])

    def clear(self) -> None:
        """清空文件列表"""
        self.beginResetModel()
        self._files.clear()
        self._path_to_row.clear()
        self._pending_async_icons.clear()
        self._system_icon_retry_until.clear()
        self.endResetModel()

    def get_file_info(self, index: QModelIndex) -> Dict[str, Any]:
        """获取索引对应的文件信息"""
        if not index.isValid() or index.row() >= len(self._files):
            return {}
        return self._files[index.row()].copy()

    def get_selected_files(self) -> List[str]:
        """获取所有选中文件的路径"""
        return [f["path"] for f in self._files if f.get("is_selected", False)]

    @classmethod
    def _get_cached_icon(cls, cache_key):
        """从缓存获取图标"""
        cached = cls._icon_cache.get(cache_key)
        if cached is None:
            return None
        cls._icon_cache.move_to_end(cache_key)
        return cached

    @classmethod
    def _store_cached_icon(cls, cache_key, pixmap) -> None:
        """存储图标到缓存"""
        if cache_key is None or pixmap is None or pixmap.isNull():
            return

        cls._icon_cache[cache_key] = pixmap
        cls._icon_cache.move_to_end(cache_key)

        while len(cls._icon_cache) > cls._ICON_CACHE_MAX_ENTRIES:
            oldest_key = next(iter(cls._icon_cache))
            source_type = None
            if isinstance(oldest_key, tuple) and len(oldest_key) > 0:
                source_type = oldest_key[0]
            if source_type == "system_icon":
                cls._icon_cache.move_to_end(oldest_key)
                continue
            cls._icon_cache.popitem(last=False)

    @classmethod
    def _discard_cached_icon(cls, cache_key) -> None:
        if cache_key is None:
            return
        cls._icon_cache.pop(cache_key, None)

    @staticmethod
    def _safe_get_mtime(path: str):
        if not path:
            return None
        try:
            return os.path.getmtime(path)
        except (OSError, PermissionError, RuntimeError, TypeError, ValueError):
            return None

    @staticmethod
    def _get_monotonic_time_ms() -> float:
        return time.monotonic() * 1000.0

    @staticmethod
    def _build_system_icon_cache_key(normalized_path: str, suffix: str, icon_size: int):
        return ("system_icon", normalized_path, suffix, icon_size)

    @staticmethod
    def _build_system_icon_retry_key(normalized_path: str, suffix: str, icon_size: int):
        return (normalized_path, suffix, icon_size)

    def _is_system_icon_retry_deferred(self, normalized_path: str, suffix: str, icon_size: int) -> bool:
        retry_key = self._build_system_icon_retry_key(normalized_path, suffix, icon_size)
        retry_until_ms = self._system_icon_retry_until.get(retry_key)
        if retry_until_ms is None:
            return False

        now_ms = self._get_monotonic_time_ms()
        if now_ms >= retry_until_ms:
            self._system_icon_retry_until.pop(retry_key, None)
            return False
        return True

    def _resolve_icon_source(self, file_info: Dict[str, Any]):
        file_path = file_info.get("path", "")
        is_dir = file_info.get("is_dir", False)
        suffix = file_info.get("suffix", "").lower()

        if not file_path:
            return {
                "source_type": "empty",
                "normalized_path": "",
                "mtime": None,
                "icon_path": "",
                "thumbnail_path": "",
                "suffix": suffix,
                "is_dir": is_dir,
            }

        normalized_path = self._normalize_path(file_path)

        if not is_dir and suffix in self._SYSTEM_ICON_SUFFIXES:
            return {
                "source_type": "system_icon",
                "normalized_path": normalized_path,
                "mtime": self._safe_get_mtime(file_path),
                "icon_path": "",
                "thumbnail_path": "",
                "suffix": suffix,
                "is_dir": is_dir,
            }

        thumbnail_path = ""
        if suffix in self._PHOTO_SUFFIXES or suffix in self._VIDEO_SUFFIXES:
            thumbnail_path = get_existing_thumbnail_path(file_path) or ""
            if thumbnail_path:
                return {
                    "source_type": "thumbnail",
                    "normalized_path": self._normalize_path(thumbnail_path),
                    "mtime": self._safe_get_mtime(thumbnail_path),
                    "icon_path": "",
                    "thumbnail_path": thumbnail_path,
                    "suffix": suffix,
                    "is_dir": is_dir,
                }

        icon_path = get_file_icon_path(file_info) or ""
        if icon_path and os.path.exists(icon_path):
            return {
                "source_type": "file_icon",
                "normalized_path": self._normalize_path(icon_path),
                "mtime": self._safe_get_mtime(icon_path),
                "icon_path": icon_path,
                "thumbnail_path": thumbnail_path,
                "suffix": suffix,
                "is_dir": is_dir,
            }

        return {
            "source_type": "file_icon",
            "normalized_path": "",
            "mtime": None,
            "icon_path": icon_path,
            "thumbnail_path": thumbnail_path,
            "suffix": suffix,
            "is_dir": is_dir,
        }

    def _build_icon_source_signature(self, file_info: Dict[str, Any]):
        resolved_source = self._resolve_icon_source(file_info)
        return (
            resolved_source["source_type"],
            resolved_source["normalized_path"],
            resolved_source["mtime"],
        )

    def _get_theme_color_tuple(self):
        app = QApplication.instance()
        settings_manager = getattr(app, "settings_manager", None) if app else None
        if settings_manager is None:
            settings_manager = SettingsManager()

        base_color = settings_manager.get_setting("appearance.colors.base_color", "#212121")
        auxiliary_color = settings_manager.get_setting("appearance.colors.auxiliary_color", "#3D3D3D")
        normal_color = settings_manager.get_setting("appearance.colors.normal_color", "#717171")
        accent_color = settings_manager.get_setting("appearance.colors.accent_color", "#B036EE")
        secondary_color = settings_manager.get_setting("appearance.colors.secondary_color", "#FFFFFF")
        return base_color, auxiliary_color, normal_color, accent_color, secondary_color

    def _get_device_pixel_ratio(self) -> float:
        try:
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    ratio = float(screen.devicePixelRatio())
                    if ratio > 0:
                        return ratio
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass
        return 1.0

    def _normalize_icon_pixmap(self, pixmap: QPixmap, icon_size: int) -> QPixmap:
        if pixmap.isNull():
            fallback = QPixmap(icon_size, icon_size)
            fallback.fill(Qt.transparent)
            return fallback

        try:
            clean_pixmap = QPixmap.fromImage(pixmap.toImage())
            clean_pixmap.setDevicePixelRatio(1.0)

            dpr = self._get_device_pixel_ratio()
            physical_canvas_size = max(1, int(round(icon_size * dpr)))

            image = clean_pixmap.toImage()
            source_rect = QRect(0, 0, image.width(), image.height())

            bounded_rect = self._find_non_transparent_bounds(image)
            if bounded_rect is not None:
                source_rect = bounded_rect

            target_size = QSize(source_rect.width(), source_rect.height()).scaled(
                physical_canvas_size,
                physical_canvas_size,
                Qt.KeepAspectRatio,
            )

            normalized = QPixmap(physical_canvas_size, physical_canvas_size)
            normalized.fill(Qt.transparent)

            painter = QPainter(normalized)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(
                QRectF(
                    (physical_canvas_size - target_size.width()) / 2.0,
                    (physical_canvas_size - target_size.height()) / 2.0,
                    float(target_size.width()),
                    float(target_size.height()),
                ),
                clean_pixmap,
                QRectF(source_rect),
            )
            painter.end()

            normalized.setDevicePixelRatio(dpr)
            return normalized
        except (RuntimeError, TypeError, ValueError) as error:
            debug(f"规范化图标 Pixmap 失败: {error}")
            fallback = QPixmap(icon_size, icon_size)
            fallback.fill(Qt.transparent)
            return fallback

    @staticmethod
    def _find_non_transparent_bounds(image) -> Optional[QRect]:
        try:
            alpha_mask = image.createAlphaMask()
            if alpha_mask.isNull():
                return None

            bounds = QRegion(QBitmap.fromImage(alpha_mask)).boundingRect()
            if bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
                return None
            return bounds
        except (RuntimeError, TypeError, ValueError):
            return None

    @classmethod
    def _build_unknown_icon_pixmap_static(
        cls,
        icon_path: str,
        text: str,
        icon_size: int,
        dpr: float = 1.0,
        base_color: str = "#212121",
    ) -> QPixmap:
        """构建未知类型文件的图标（带文字叠加）"""
        from PySide6.QtGui import QFont, QFontMetrics, QColor

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

    def _emit_icon_changed_for_path(self, normalized_path: str) -> None:
        if self._is_scroll_optimizing():
            return
        row = self._path_to_row.get(normalized_path, -1)
        if row < 0:
            return
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [self.IconPixmapRole])

    def _handle_async_system_icon_loaded(self, file_path: str, expected_suffix: str, icon_size: int, pixmap):
        normalized_path = self._normalize_path(file_path)
        pending_info = self._pending_async_icons.get(normalized_path)

        if not pending_info:
            return

        pending_suffix, pending_icon_size = pending_info
        if pending_suffix != expected_suffix or pending_icon_size != icon_size:
            return

        cache_key = self._build_system_icon_cache_key(normalized_path, expected_suffix, icon_size)
        retry_key = self._build_system_icon_retry_key(normalized_path, expected_suffix, icon_size)
        if pixmap and not pixmap.isNull():
            normalized_pixmap = self._normalize_icon_pixmap(pixmap, icon_size)
            self._store_cached_icon(cache_key, normalized_pixmap)
            self._system_icon_retry_until.pop(retry_key, None)
        else:
            self._discard_cached_icon(cache_key)
            self._system_icon_retry_until[retry_key] = (
                self._get_monotonic_time_ms() + self._SYSTEM_ICON_RETRY_DELAY_MS
            )

        self._pending_async_icons.pop(normalized_path, None)
        self._emit_icon_changed_for_path(normalized_path)

    def _request_async_system_icon(self, file_info: Dict[str, Any], icon_size: int) -> None:
        file_path = file_info.get("path", "")
        suffix = file_info.get("suffix", "").lower()
        normalized_path = self._normalize_path(file_path)
        if not normalized_path:
            return

        if self._is_system_icon_retry_deferred(normalized_path, suffix, icon_size):
            return

        pending_info = self._pending_async_icons.get(normalized_path)
        if pending_info == (suffix, icon_size):
            return

        self._pending_async_icons[normalized_path] = (suffix, icon_size)

        self_ref = weakref.ref(self)

        def _on_loaded(loaded_path, pixmap):
            model = self_ref()
            if model is None:
                return
            model._handle_async_system_icon_loaded(loaded_path, suffix, icon_size, pixmap)

        self._async_loader.load_icon(file_path, _on_loaded, icon_size=icon_size)

    def _build_lightweight_placeholder(
        self,
        file_info: Dict[str, Any],
        icon_size: int,
        dpr: float,
        base_color: str,
    ) -> QPixmap:
        icon_path = get_file_icon_path(file_info) or ""
        suffix = str(file_info.get("suffix", "")).lower()

        if icon_path and os.path.exists(icon_path):
            if icon_path.endswith("未知底板.svg") or icon_path.endswith("未知底板 – 1.svg"):
                display_suffix = suffix.upper() if suffix else ""
                if not display_suffix or len(display_suffix) >= 5:
                    display_suffix = "FILE"
                pixmap = self._build_unknown_icon_pixmap_static(icon_path, display_suffix, icon_size, dpr, base_color)
            elif icon_path.endswith("压缩文件.svg") or icon_path.endswith("压缩文件 – 1.svg"):
                display_suffix = "." + suffix if suffix else ""
                if not display_suffix or len(display_suffix) >= 5:
                    display_suffix = "FILE"
                pixmap = self._build_unknown_icon_pixmap_static(icon_path, display_suffix, icon_size, dpr, base_color)
            else:
                pixmap = SvgRenderer.render_svg_to_exact_pixmap(
                    icon_path,
                    icon_width=icon_size,
                    icon_height=icon_size,
                    replace_colors=True,
                    device_pixel_ratio=dpr,
                )

            if pixmap and not pixmap.isNull():
                return self._normalize_icon_pixmap(pixmap, icon_size)

        placeholder = QPixmap(icon_size, icon_size)
        placeholder.fill(Qt.transparent)
        return placeholder

    def _get_icon_pixmap(self, file_info: Dict[str, Any]) -> QPixmap:
        """
        获取文件图标像素图
        按需计算并缓存，不进行全量预加载。
        """
        file_path = file_info.get("path", "")
        if not file_path:
            return QPixmap()

        icon_size = int(38 * self._dpi_scale)
        dpr = round(self._get_device_pixel_ratio(), 4)
        base_color, auxiliary_color, normal_color, accent_color, secondary_color = self._get_theme_color_tuple()
        resolved_source = self._resolve_icon_source(file_info)
        source_type = resolved_source["source_type"]
        suffix = resolved_source["suffix"]
        is_dir = resolved_source["is_dir"]
        icon_source_signature = (
            source_type,
            resolved_source["normalized_path"],
            resolved_source["mtime"],
        )
        cache_identity = (
            source_type,
            is_dir,
            suffix,
            icon_source_signature,
        )
        cache_key = (
            cache_identity,
            icon_size,
            self._dpi_scale,
            dpr,
            base_color,
            auxiliary_color,
            normal_color,
            accent_color,
            secondary_color,
        )

        cached = self._get_cached_icon(cache_key)
        if cached is not None and not cached.isNull():
            return cached

        normalized_path = self._normalize_path(file_path)
        is_scroll_optimizing = self._is_scroll_optimizing()
        if source_type == "system_icon":
            system_cache_key = self._build_system_icon_cache_key(normalized_path, suffix, icon_size)
            system_cached = self._get_cached_icon(system_cache_key)
            if system_cached is not None and not system_cached.isNull():
                return system_cached

            placeholder = self._build_lightweight_placeholder(file_info, icon_size, dpr, base_color)
            if not is_scroll_optimizing and not self._is_system_icon_retry_deferred(normalized_path, suffix, icon_size):
                self._request_async_system_icon(file_info, icon_size)
            return placeholder

        if source_type == "thumbnail":
            if is_scroll_optimizing:
                return self._build_lightweight_placeholder(file_info, icon_size, dpr, base_color)
            pixmap = QPixmap(resolved_source["thumbnail_path"])
            if pixmap and not pixmap.isNull():
                normalized_pixmap = self._normalize_icon_pixmap(pixmap, icon_size)
                self._store_cached_icon(cache_key, normalized_pixmap)
                return normalized_pixmap

        icon_path = resolved_source["icon_path"]
        if icon_path:
            if icon_path.endswith("未知底板.svg") or icon_path.endswith("未知底板 – 1.svg"):
                display_suffix = suffix.upper() if suffix else ""
                if not display_suffix or len(display_suffix) >= 5:
                    display_suffix = "FILE"
                pixmap = self._build_unknown_icon_pixmap_static(icon_path, display_suffix, icon_size, dpr, base_color)
            elif icon_path.endswith("压缩文件.svg") or icon_path.endswith("压缩文件 – 1.svg"):
                display_suffix = "." + suffix if suffix else ""
                if not display_suffix or len(display_suffix) >= 5:
                    display_suffix = "FILE"
                pixmap = self._build_unknown_icon_pixmap_static(icon_path, display_suffix, icon_size, dpr, base_color)
            else:
                pixmap = SvgRenderer.render_svg_to_exact_pixmap(
                    icon_path,
                    icon_width=icon_size,
                    icon_height=icon_size,
                    replace_colors=True,
                    device_pixel_ratio=dpr,
                )

            if pixmap and not pixmap.isNull():
                normalized_pixmap = self._normalize_icon_pixmap(pixmap, icon_size)
                self._store_cached_icon(cache_key, normalized_pixmap)
                return normalized_pixmap

        placeholder = QPixmap(icon_size, icon_size)
        placeholder.fill(Qt.transparent)
        return placeholder


class FileListView(QListView):
    """
    文件选择器列表视图

    信号：
    - file_clicked: 文件点击信号，传递 file_info
    - file_double_clicked: 文件双击信号，传递 file_info
    - file_right_clicked: 文件右键信号，传递 file_info
    - file_selection_changed: 文件选择变化信号，传递(file_info, is_selected)
    - file_drag_started: 文件拖拽开始信号，传递 file_info
    - file_drag_ended: 文件拖拽结束信号，传递(file_info, drop_target)
    """

    file_clicked = Signal(dict)
    file_double_clicked = Signal(dict)
    file_right_clicked = Signal(dict)
    file_selection_changed = Signal(dict, bool)
    file_drag_started = Signal(dict)
    file_drag_ended = Signal(dict, str)
    navigate_parent_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed_index = QModelIndex()
        self._press_pos = None
        self._press_global_pos = None
        self._drag_index = QModelIndex()
        self._dragging = False
        self._drag_card = None
        self._touch_drag_threshold = 10
        self._long_press_duration = 500
        self._touch_optimization_enabled = True
        self._mouse_buttons_swapped = False
        self._pending_click_file_info = None
        self._connected_vertical_scrollbar = None
        self._connected_horizontal_scrollbar = None
        self._scrollbar_drag_active = False
        self._defer_icon_loading = False
        self._last_slider_value = None
        self._last_slider_value_timestamp = 0.0
        self._defer_icon_loading_enter_velocity = 2600.0
        self._defer_icon_loading_exit_velocity = 1200.0
        self._defer_icon_loading_resume_delay_ms = 120
        self._path_transition_enabled = True
        self._path_transition_direction = 0
        self._path_transition_duration_ms = 100
        self._path_transition_progress = 1.0
        self._path_transition_start_ms = 0.0
        self._path_transition_outgoing_pixmap = QPixmap()
        self._path_transition_incoming_pixmap = QPixmap()
        self._path_transition_waiting_for_incoming = False
        self._path_transition_active = False
        self._path_transition_capturing_base = False

        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._start_long_press_drag)

        self._defer_icon_loading_timer = QTimer(self)
        self._defer_icon_loading_timer.setSingleShot(True)
        self._defer_icon_loading_timer.timeout.connect(self._resume_icon_loading)

        self._path_transition_timer = QTimer(self)
        self._path_transition_timer.setInterval(16)
        self._path_transition_timer.timeout.connect(self._advance_path_transition)

        self._setup_view()
        self._load_interaction_settings()
        self.configure_scrollbar_tracking()

    def _setup_view(self) -> None:
        """配置视图属性"""
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QListView.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched)
        self.setWrapping(True)
        self.setFlow(QListView.LeftToRight)
        self.setSpacing(8)
        self.setEditTriggers(QListView.NoEditTriggers)
        self.setSelectionRectVisible(False)
        self.setSelectionBehavior(QListView.SelectRows)
        self.setMouseTracking(True)

    def _load_interaction_settings(self) -> None:
        app = QApplication.instance()
        settings_manager = getattr(app, "settings_manager", None) if app else None
        if settings_manager is None:
            settings_manager = SettingsManager()

        try:
            self._touch_optimization_enabled = bool(
                settings_manager.get_setting("file_selector.touch_optimization", True)
            )
            self._mouse_buttons_swapped = bool(
                settings_manager.get_setting("file_selector.mouse_buttons_swap", False)
            )
        except (RuntimeError, TypeError, ValueError) as error:
            debug(f"加载文件选择器交互设置失败: {error}")
            self._touch_optimization_enabled = True
            self._mouse_buttons_swapped = False

        dpi_scale = getattr(app, "dpi_scale_factor", 1.0) if app else 1.0
        self._touch_drag_threshold = int(10 * dpi_scale)
        self._long_press_duration = 500

    def refresh_interaction_settings(self) -> None:
        self._load_interaction_settings()

    def is_scroll_optimizing(self) -> bool:
        return self._defer_icon_loading

    def _get_monotonic_time_ms(self) -> float:
        return time.monotonic() * 1000.0

    def _capture_viewport_snapshot(self) -> QPixmap:
        viewport = self.viewport()
        if viewport is None:
            return QPixmap()

        size = viewport.size()
        if not size.isValid() or size.width() <= 0 or size.height() <= 0:
            return QPixmap()

        dpr = max(1.0, float(viewport.devicePixelRatioF()))
        pixmap = QPixmap(max(1, int(size.width() * dpr)), max(1, int(size.height() * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)

        self._path_transition_capturing_base = True
        try:
            viewport.render(pixmap)
        finally:
            self._path_transition_capturing_base = False

        return pixmap

    def _normalize_path_transition_direction(self, direction: int) -> int:
        if direction > 0:
            return 1
        if direction < 0:
            return -1
        return 0

    def begin_path_transition(self, direction: int) -> bool:
        """
        捕获当前卡片矩阵，等待新目录加载后执行整体平移/渐隐渐现。

        该动画只缓存 viewport 快照并由单个计时器驱动，避免在每张卡片上创建动画对象。
        """
        if not self._path_transition_enabled or not self.isVisible():
            return False

        outgoing_pixmap = self._capture_viewport_snapshot()
        if outgoing_pixmap.isNull():
            return False

        self.cancel_path_transition(update=False)
        self._path_transition_direction = self._normalize_path_transition_direction(direction)
        self._path_transition_outgoing_pixmap = outgoing_pixmap
        self._path_transition_incoming_pixmap = QPixmap()
        self._path_transition_waiting_for_incoming = True
        self._path_transition_active = False
        self._path_transition_progress = 0.0
        self.viewport().update()
        return True

    def finish_path_transition(self, direction: int = None) -> bool:
        if not self._path_transition_enabled:
            self.cancel_path_transition()
            return False

        if direction is not None:
            self._path_transition_direction = self._normalize_path_transition_direction(direction)

        incoming_pixmap = self._capture_viewport_snapshot()
        if incoming_pixmap.isNull():
            self.cancel_path_transition()
            return False

        if self._path_transition_outgoing_pixmap.isNull():
            self._path_transition_outgoing_pixmap = incoming_pixmap

        self._path_transition_incoming_pixmap = incoming_pixmap
        self._path_transition_waiting_for_incoming = False
        self._path_transition_active = True
        self._path_transition_progress = 0.0
        self._path_transition_start_ms = self._get_monotonic_time_ms()
        self._path_transition_timer.start()
        self.viewport().update()
        return True

    def cancel_path_transition(self, update: bool = True) -> None:
        self._path_transition_timer.stop()
        self._path_transition_active = False
        self._path_transition_waiting_for_incoming = False
        self._path_transition_progress = 1.0
        self._path_transition_outgoing_pixmap = QPixmap()
        self._path_transition_incoming_pixmap = QPixmap()
        if update:
            self.viewport().update()

    def _advance_path_transition(self, now_ms: float = None) -> None:
        if not self._path_transition_active:
            self._path_transition_timer.stop()
            return

        current_time_ms = self._get_monotonic_time_ms() if now_ms is None else float(now_ms)
        elapsed_ms = max(0.0, current_time_ms - self._path_transition_start_ms)
        progress = elapsed_ms / max(1.0, float(self._path_transition_duration_ms))

        if progress >= 1.0:
            self.cancel_path_transition()
            return

        self._path_transition_progress = max(0.0, min(1.0, progress))
        self.viewport().update()

    def _ease_path_transition(self, progress: float) -> float:
        progress = max(0.0, min(1.0, float(progress)))
        return 1.0 - pow(1.0 - progress, 3)

    def _path_transition_offset(self) -> int:
        width = self.viewport().width()
        if width <= 0:
            return 0
        return max(24, min(96, int(width * 0.08)))

    def _draw_transition_pixmap(self, painter: QPainter, pixmap: QPixmap, dx: int, opacity: float) -> None:
        if pixmap.isNull() or opacity <= 0.0:
            return

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, float(opacity))))
        painter.drawPixmap(int(dx), 0, pixmap)
        painter.restore()

    def _paint_path_transition(self) -> None:
        painter = QPainter(self.viewport())
        try:
            painter.fillRect(self.viewport().rect(), self.viewport().palette().color(QPalette.Base))

            if self._path_transition_waiting_for_incoming:
                self._draw_transition_pixmap(painter, self._path_transition_outgoing_pixmap, 0, 1.0)
                return

            direction = self._path_transition_direction
            progress = max(0.0, min(1.0, self._path_transition_progress))
            eased = self._ease_path_transition(progress)
            offset = self._path_transition_offset()

            outgoing_dx = int(-direction * offset * eased) if direction else 0
            incoming_dx = int(direction * offset * (1.0 - eased)) if direction else 0
            outgoing_opacity = max(0.0, 1.0 - progress * 1.12)
            incoming_opacity = min(1.0, progress * 1.18)

            self._draw_transition_pixmap(painter, self._path_transition_outgoing_pixmap, outgoing_dx, outgoing_opacity)
            self._draw_transition_pixmap(painter, self._path_transition_incoming_pixmap, incoming_dx, incoming_opacity)
        finally:
            painter.end()

    def _set_deferred_icon_loading(self, active: bool) -> None:
        active = bool(active)
        if self._defer_icon_loading == active:
            return
        self._defer_icon_loading = active
        self.viewport().update()

    def _resume_icon_loading(self) -> None:
        self._set_deferred_icon_loading(False)

    def _schedule_icon_loading_resume(self) -> None:
        self._defer_icon_loading_timer.start(self._defer_icon_loading_resume_delay_ms)

    def _connect_scrollbar(self, scrollbar, orientation: str) -> None:
        if scrollbar is None:
            return

        current_attr = f"_connected_{orientation}_scrollbar"
        previous_scrollbar = getattr(self, current_attr, None)
        if previous_scrollbar is scrollbar:
            return

        if previous_scrollbar is not None:
            for signal, slot in (
                (previous_scrollbar.sliderPressed, self._on_scrollbar_slider_pressed),
                (previous_scrollbar.sliderMoved, self._on_scrollbar_slider_moved),
                (previous_scrollbar.sliderReleased, self._on_scrollbar_slider_released),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass

        scrollbar.sliderPressed.connect(self._on_scrollbar_slider_pressed)
        scrollbar.sliderMoved.connect(self._on_scrollbar_slider_moved)
        scrollbar.sliderReleased.connect(self._on_scrollbar_slider_released)
        setattr(self, current_attr, scrollbar)

    def configure_scrollbar_tracking(self) -> None:
        self._connect_scrollbar(self.verticalScrollBar(), "vertical")
        self._connect_scrollbar(self.horizontalScrollBar(), "horizontal")

    def setModel(self, model) -> None:
        super().setModel(model)
        if isinstance(model, FileSelectorListModel):
            model.attach_view(self)

    def setVerticalScrollBar(self, scrollbar) -> None:
        super().setVerticalScrollBar(scrollbar)
        self.configure_scrollbar_tracking()

    def setHorizontalScrollBar(self, scrollbar) -> None:
        super().setHorizontalScrollBar(scrollbar)
        self.configure_scrollbar_tracking()

    def paintEvent(self, event) -> None:
        if self._path_transition_capturing_base:
            super().paintEvent(event)
            return

        if self._path_transition_active or self._path_transition_waiting_for_incoming:
            self._paint_path_transition()
            event.accept()
            return

        super().paintEvent(event)

    def resizeEvent(self, event) -> None:
        if self._path_transition_active:
            self.cancel_path_transition(update=False)
        super().resizeEvent(event)

    def _on_scrollbar_slider_pressed(self) -> None:
        scrollbar = self.sender()
        self._scrollbar_drag_active = True
        self._last_slider_value = scrollbar.value() if scrollbar is not None else None
        self._last_slider_value_timestamp = self._get_monotonic_time_ms()
        self._defer_icon_loading_timer.stop()

    def _on_scrollbar_slider_moved(self, value: int, now_ms: float = None) -> None:
        if not self._scrollbar_drag_active:
            return

        current_time_ms = self._get_monotonic_time_ms() if now_ms is None else float(now_ms)
        previous_value = self._last_slider_value
        previous_time_ms = self._last_slider_value_timestamp

        self._last_slider_value = value
        self._last_slider_value_timestamp = current_time_ms

        if previous_value is None or previous_time_ms <= 0:
            return

        delta_value = abs(int(value) - int(previous_value))
        delta_time_ms = max(1.0, current_time_ms - previous_time_ms)
        velocity = (delta_value * 1000.0) / delta_time_ms

        if velocity >= self._defer_icon_loading_enter_velocity:
            self._defer_icon_loading_timer.stop()
            self._set_deferred_icon_loading(True)
        elif self._defer_icon_loading and velocity <= self._defer_icon_loading_exit_velocity:
            self._schedule_icon_loading_resume()

    def _on_scrollbar_slider_released(self) -> None:
        self._scrollbar_drag_active = False
        self._last_slider_value = None
        self._last_slider_value_timestamp = 0.0
        self._schedule_icon_loading_resume()

    def _get_file_info_from_index(self, index: QModelIndex) -> Dict[str, Any]:
        model = self.model()
        if isinstance(model, FileSelectorListModel):
            return model.get_file_info(index)
        return {}

    def _current_action_button(self, button):
        if button == Qt.LeftButton:
            return Qt.RightButton if self._mouse_buttons_swapped else Qt.LeftButton
        if button == Qt.RightButton:
            return Qt.LeftButton if self._mouse_buttons_swapped else Qt.RightButton
        return button

    @staticmethod
    def _is_back_navigation_button(button) -> bool:
        for button_name in ("BackButton", "XButton1", "ExtraButton1"):
            back_button = getattr(Qt, button_name, None)
            if back_button is not None and button == back_button:
                return True
        return False

    def _sync_single_selection(self, index: QModelIndex, file_info: Dict[str, Any]) -> None:
        model = self.model()
        if not isinstance(model, FileSelectorListModel):
            return

        self.selectionModel().clearSelection()
        self.selectionModel().select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)

        for row, row_file_info in enumerate(model._files):
            normalized_path = row_file_info.get("path", "")
            should_select = row == index.row()
            model.set_selected(normalized_path, should_select)

    def _sync_range_selection(self, anchor_index: QModelIndex, current_index: QModelIndex) -> None:
        model = self.model()
        selection_model = self.selectionModel()

        if not isinstance(model, FileSelectorListModel) or selection_model is None:
            return

        top_row = min(anchor_index.row(), current_index.row())
        bottom_row = max(anchor_index.row(), current_index.row())

        selection_model.clearSelection()
        selection = QItemSelection()
        top_index = model.index(top_row, 0)
        bottom_index = model.index(bottom_row, 0)
        selection.select(top_index, bottom_index)
        selection_model.select(selection, QItemSelectionModel.Select | QItemSelectionModel.Rows)

        selected_paths = set()
        for row in range(top_row, bottom_row + 1):
            row_info = model._files[row]
            selected_paths.add(os.path.normpath(row_info.get("path", "")))

        for row, row_info in enumerate(model._files):
            file_path = row_info.get("path", "")
            normalized_path = os.path.normpath(file_path)
            should_select = normalized_path in selected_paths
            old_state = row_info.get("is_selected", False)
            model.set_selected(file_path, should_select)
            if old_state != should_select:
                self.file_selection_changed.emit(model.get_file_info(model.index(row, 0)), should_select)

    def _toggle_ctrl_selection(self, index: QModelIndex, file_info: Dict[str, Any]) -> None:
        selection_model = self.selectionModel()
        model = self.model()
        if selection_model is None or not isinstance(model, FileSelectorListModel):
            return

        is_selected = selection_model.isSelected(index)
        if is_selected:
            selection_model.select(index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
        else:
            selection_model.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)

        new_state = not is_selected
        model.set_selected(file_info.get("path", ""), new_state)
        self.file_selection_changed.emit(file_info, new_state)

    def _build_drag_pixmap(self, index: QModelIndex) -> QPixmap:
        delegate = self.itemDelegateForIndex(index) or self.itemDelegate()
        if delegate is None:
            return QPixmap()

        # 注意：
        # - gridSize() 表示单元格尺寸，包含矩阵外边距预留
        # - 拖拽预览需要的是“真实卡片尺寸”
        # 因此这里优先使用 delegate.sizeHint()，保证拖拽卡片与列表中的卡片本体一致。
        try:
            option = QStyleOptionViewItem()
            option.initFrom(self.viewport())
            preview_size = delegate.sizeHint(option, index)
        except Exception:
            preview_size = QSize()

        if not preview_size.isValid() or preview_size.width() <= 0 or preview_size.height() <= 0:
            preview_size = self.gridSize()

        preview_size = QSize(
            max(1, preview_size.width()),
            max(1, preview_size.height()),
        )

        if hasattr(delegate, "build_drag_pixmap"):
            try:
                return delegate.build_drag_pixmap(index, preview_size, self.palette())
            except Exception as error:
                debug(f"构建拖拽预览卡片失败，回退默认绘制逻辑: {error}")

        option = QStyleOptionViewItem()
        option.initFrom(self.viewport())
        option.rect = QRect(0, 0, preview_size.width(), preview_size.height())
        option.palette = self.palette()
        option.state |= QStyle.State_Enabled

        pixmap = QPixmap(option.rect.size())
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        delegate.paint(painter, option, index)
        painter.end()
        return pixmap

    def _create_drag_card(self, pixmap: QPixmap) -> None:
        if self._drag_card is not None:
            self._drag_card.hide()
            self._drag_card.deleteLater()
            self._drag_card = None

        if pixmap.isNull():
            return

        self._drag_card = QLabel(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self._drag_card.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_card.setStyleSheet("background: transparent; border: none;")
        self._drag_card.setPixmap(pixmap)
        self._drag_card.resize(pixmap.size())

        cursor_pos = self._press_global_pos or self.mapToGlobal(self.rect().center())
        self._drag_card.move(
            cursor_pos.x() - self._drag_card.width() // 2,
            cursor_pos.y() - self._drag_card.height() // 2,
        )
        self._drag_card.show()

    def _update_drag_card_position(self, global_pos) -> None:
        if self._drag_card is None:
            return

        self._drag_card.move(
            global_pos.x() - self._drag_card.width() // 2,
            global_pos.y() - self._drag_card.height() // 2,
        )

    def _start_long_press_drag(self) -> None:
        if not self._pressed_index.isValid():
            return

        file_info = self._get_file_info_from_index(self._pressed_index)
        if not file_info:
            return

        delegate = self.itemDelegateForIndex(self._pressed_index) or self.itemDelegate()
        if delegate and hasattr(delegate, "set_dragging_file_path"):
            try:
                delegate.set_dragging_file_path(file_info.get("path", ""))
            except Exception as error:
                debug(f"设置拖拽源卡片状态失败: {error}")

        self._pending_click_file_info = None
        self._drag_index = self._pressed_index
        self._dragging = True
        self._create_drag_card(self._build_drag_pixmap(self._drag_index))
        self.setCursor(Qt.ClosedHandCursor)
        self.viewport().update()
        self.file_drag_started.emit(file_info)

    def _detect_drop_target(self, global_pos) -> str:
        main_window = self.window()
        if not main_window:
            return "none"

        if hasattr(main_window, "file_staging_pool"):
            staging_pool = main_window.file_staging_pool
            if staging_pool and staging_pool.isVisible():
                global_rect = QRect(staging_pool.mapToGlobal(staging_pool.rect().topLeft()), staging_pool.rect().size())
                if global_rect.contains(global_pos):
                    return "staging_pool"

        if hasattr(main_window, "unified_previewer"):
            previewer = main_window.unified_previewer
            if previewer and previewer.isVisible():
                global_rect = QRect(previewer.mapToGlobal(previewer.rect().topLeft()), previewer.rect().size())
                if global_rect.contains(global_pos):
                    return "previewer"

        return "none"

    def _cleanup_press_state(self) -> None:
        self._long_press_timer.stop()
        self._press_pos = None
        self._press_global_pos = None
        self._pressed_index = QModelIndex()
        self._pending_click_file_info = None

    def _cleanup_drag_state(self) -> None:
        previous_drag_index = self._drag_index

        self._long_press_timer.stop()
        self._dragging = False
        self._drag_index = QModelIndex()

        if self._drag_card is not None:
            self._drag_card.hide()
            self._drag_card.deleteLater()
            self._drag_card = None

        if previous_drag_index.isValid():
            delegate = self.itemDelegateForIndex(previous_drag_index) or self.itemDelegate()
            if delegate and hasattr(delegate, "set_dragging_file_path"):
                try:
                    delegate.set_dragging_file_path(None)
                except Exception as error:
                    debug(f"清理拖拽源卡片状态失败: {error}")

        self.unsetCursor()
        self.viewport().update()
        self._cleanup_press_state()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._is_back_navigation_button(event.button()):
            self._cleanup_press_state()
            self.navigate_parent_requested.emit()
            event.accept()
            return

        index = self.indexAt(event.pos())
        logical_button = self._current_action_button(event.button())

        if not index.isValid():
            if logical_button == Qt.LeftButton:
                self.clearSelection()
                model = self.model()
                if isinstance(model, FileSelectorListModel):
                    model.deselect_all()
            self._cleanup_press_state()
            super().mousePressEvent(event)
            return

        self._pressed_index = index
        self._press_pos = event.pos()
        self._press_global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()

        file_info = self._get_file_info_from_index(index)
        modifiers = QApplication.keyboardModifiers()
        selection_model = self.selectionModel()

        if logical_button == Qt.LeftButton:
            if modifiers & Qt.ControlModifier:
                self._toggle_ctrl_selection(index, file_info)
                self._cleanup_press_state()
                return

            if modifiers & Qt.ShiftModifier and selection_model is not None:
                anchor_index = selection_model.currentIndex()
                if not anchor_index.isValid():
                    anchor_index = index
                self._sync_range_selection(anchor_index, index)
                self._cleanup_press_state()
                return

            # 普通左键按下：
            # - 不切换选中态
            # - 仅记录当前项，供后续 release 触发 click 或长按触发 drag
            # 旧 FileBlockCard 语义中，左键单击/长按都不会把卡片切成选中样式，
            # 选中态只由右键/多选逻辑控制。
            if selection_model is not None:
                selection_model.setCurrentIndex(index, QItemSelectionModel.Current)

            self._pending_click_file_info = file_info

            if self._touch_optimization_enabled:
                self._long_press_timer.start(self._long_press_duration)
            return

        if logical_button == Qt.RightButton:
            model = self.model()
            if isinstance(model, FileSelectorListModel):
                new_state = not file_info.get("is_selected", False)
                model.set_selected(file_info.get("path", ""), new_state)
                if selection_model is not None:
                    if new_state:
                        selection_model.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                    else:
                        selection_model.select(index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
                self.file_selection_changed.emit(file_info, new_state)

            self.file_right_clicked.emit(file_info)
            self._cleanup_press_state()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._drag_card is not None:
            global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            self._update_drag_card_position(global_pos)
            event.accept()
            return

        if self._press_pos is not None and self._pressed_index.isValid():
            delta = event.pos() - self._press_pos
            if abs(delta.x()) > self._touch_drag_threshold or abs(delta.y()) > self._touch_drag_threshold:
                self._long_press_timer.stop()
                self._pending_click_file_info = None

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        logical_button = self._current_action_button(event.button())

        if self._dragging and logical_button == Qt.LeftButton:
            global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            file_info = self._get_file_info_from_index(self._drag_index)
            drop_target = self._detect_drop_target(global_pos)
            if file_info:
                self.file_drag_ended.emit(file_info, drop_target)
            self._cleanup_drag_state()
            event.accept()
            return

        pending_click_file_info = self._pending_click_file_info

        if logical_button == Qt.LeftButton and pending_click_file_info:
            self.file_clicked.emit(pending_click_file_info)
            self._cleanup_press_state()
            event.accept()
            return

        self._cleanup_press_state()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return

        logical_button = self._current_action_button(event.button())
        if logical_button != Qt.LeftButton:
            event.ignore()
            return

        self._long_press_timer.stop()
        file_info = self._get_file_info_from_index(index)
        if file_info:
            self.file_double_clicked.emit(file_info)
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """右键菜单行为由 mousePressEvent 统一转发，避免与旧逻辑冲突。"""
        event.accept()

    def hideEvent(self, event) -> None:
        self.cancel_path_transition(update=False)
        self._cleanup_drag_state()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.cancel_path_transition(update=False)
        self._cleanup_drag_state()
        super().closeEvent(event)

    def _open_file(self, file_info: Dict[str, Any]) -> None:
        """打开文件"""
        file_path = file_info.get("path", "")
        if file_path and os.path.exists(file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))

    def _open_folder_location(self, file_info: Dict[str, Any]) -> None:
        """打开文件夹位置"""
        file_path = file_info.get("path", "")
        if file_path:
            if file_info.get("is_dir", False):
                QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
            else:
                folder_path = os.path.dirname(file_path)
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

    def _show_in_folder(self, file_info: Dict[str, Any]) -> None:
        """在文件夹中显示文件"""
        file_path = file_info.get("path", "")
        if file_path and not file_info.get("is_dir", False):
            folder_path = os.path.dirname(file_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder_path))

    def _copy_file_path(self, file_info: Dict[str, Any]) -> None:
        """复制文件路径到剪贴板"""
        file_path = file_info.get("path", "")
        if file_path:
            clipboard = QApplication.clipboard()
            clipboard.setText(file_path)

    def _delete_file(self, file_info: Dict[str, Any]) -> None:
        """删除文件（预留接口）"""
        pass
