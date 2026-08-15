#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

预览器注册服务
根据文件扩展名映射到对应的预览器组件类（纯映射逻辑，不含 UI 创建）。
"""

from __future__ import annotations

import importlib
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class PreviewerRegistry:
    """
    Maps file extensions to previewer widget classes.

    Stateless service — provides pure extension-to-class resolution
    without any UI creation logic.  Previewer classes are lazily imported
    and cached, so importing this module does not trigger QtWidgets loading.

    Usage::

        cls = PreviewerRegistry.get_previewer_class({"suffix": "jpg", "path": "..."})
        if cls is not None:
            widget = cls()
            widget.set_file(...)
    """

    # Extension → (module_path, class_name) for lazy import
    _EXTENSION_MAP: Dict[str, tuple[str, str]] = {
        # ── Images ──────────────────────────────────────────────────────
        "jpg":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "jpeg": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "png":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "gif":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "bmp":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "tiff": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "webp": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "svg":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "avif": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "heic": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "heif": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "cr2":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "cr3":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "crw":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "nef":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "nrw":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "arw":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "dng":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "orf":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "srf":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "sr2":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "srw":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "raf":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "rw2":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "pef":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "ptx":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "x3f":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "ico":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "icon": ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "psd":  ("freeassetfilter.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        # ── Videos ──────────────────────────────────────────────────────
        "mp4":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "avi":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mov":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mkv":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "m4v":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mxf":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "3gp":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mpg":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "wmv":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "webm": ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "vob":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ogv":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "rmvb": ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "m2ts": ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ts":   ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mts":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        # ── Audio (also uses VideoPlayerLayout in audio mode) ───────────────
        "mp3":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "wav":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "flac": ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ogg":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "wma":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "m4a":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "aiff": ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ape":  ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "opus": ("freeassetfilter.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        # ── PDF ─────────────────────────────────────────────────────────
        "pdf":  ("freeassetfilter.ui.layout.preview.pdf_previewer_layout", "PdfPreviewerLayout"),
        # ── Text / Code ─────────────────────────────────────────────────
        "txt":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "md":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "rst":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "py":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "java":  ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "cpp":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "js":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "html":  ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "css":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "php":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "c":     ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "h":     ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "cs":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "go":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "rb":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "swift": ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "kt":    ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "yml":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "yaml":  ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "json":  ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "xml":   ("freeassetfilter.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        # ── Archives ────────────────────────────────────────────────────
        "zip":  ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "rar":  ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "tar":  ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "gz":   ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "tgz":  ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "bz2":  ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "xz":   ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "7z":   ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        "iso":  ("freeassetfilter.components.archive_browser", "ArchiveBrowser"),
        # ── Fonts ───────────────────────────────────────────────────────
        "ttf":   ("freeassetfilter.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "otf":   ("freeassetfilter.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "woff":  ("freeassetfilter.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "woff2": ("freeassetfilter.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "eot":   ("freeassetfilter.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        # ── Office ──────────────────────────────────────────────────────
        "doc":   ("freeassetfilter.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "docx":  ("freeassetfilter.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "xls":   ("freeassetfilter.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "xlsx":  ("freeassetfilter.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "ppt":   ("freeassetfilter.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "pptx":  ("freeassetfilter.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
    }

    # Cache of imported classes keyed by "module_path.ClassName"
    _CLASS_CACHE: Dict[str, type] = {}
    _CLASS_CACHE.clear()  # Ensure clean state after map changes

    # ── Public API ─────────────────────────────────────────────────────

    @classmethod
    def get_previewer_class(cls, file_info: Dict) -> Optional[type]:
        """
        Resolve *file_info* to a previewer widget class.

        Parameters
        ----------
        file_info : dict
            Must contain at least ``"suffix"`` (file extension without dot,
            e.g. ``"jpg"``).  May also contain ``"is_dir": True`` to select
            the folder-content previewer.

        Returns
        -------
        type | None
            The previewer widget class, or ``None`` when no previewer is
            registered for the given file type.
        """
        # Directory → FolderContentList
        if file_info.get("is_dir", False):
            return cls._import_class(
                "freeassetfilter.components.folder_content_list",
                "FolderContentList",
            )

        suffix = file_info.get("suffix", "")
        if not suffix:
            return None

        suffix = suffix.lower().lstrip(".")
        entry = cls._EXTENSION_MAP.get(suffix)
        if entry is None:
            return None

        module_path, class_name = entry
        return cls._import_class(module_path, class_name)

    @classmethod
    def register(cls, extension: str, module_path: str, class_name: str) -> None:
        """
        Register a previewer class for *extension*.

        Parameters
        ----------
        extension : str
            File extension (e.g. ``"jpg"``, ``"pdf"``).  Leading dot is
            stripped automatically.
        module_path : str
            Dotted module path (e.g. ``"freeassetfilter.components.photo_viewer"``).
        class_name : str
            Name of the widget class inside the module (e.g. ``"PhotoViewer"``).
        """
        ext = extension.lower().lstrip(".")
        cls._EXTENSION_MAP[ext] = (module_path, class_name)
        # Remove any stale cache entry
        cls._CLASS_CACHE.pop(f"{module_path}.{class_name}", None)

    @classmethod
    def unregister(cls, extension: str) -> None:
        """
        Remove the previewer registration for *extension*.

        Parameters
        ----------
        extension : str
            File extension to unregister.  Leading dot is stripped
            automatically.
        """
        ext = extension.lower().lstrip(".")
        entry = cls._EXTENSION_MAP.pop(ext, None)
        if entry is not None:
            cls._CLASS_CACHE.pop(f"{entry[0]}.{entry[1]}", None)

    # ── Internals ──────────────────────────────────────────────────────

    @classmethod
    def _import_class(cls, module_path: str, class_name: str) -> type:
        """Lazily import and cache a previewer class."""
        cache_key = f"{module_path}.{class_name}"
        if cache_key not in cls._CLASS_CACHE:
            module = importlib.import_module(module_path)
            cls._CLASS_CACHE[cache_key] = getattr(module, class_name)
        return cls._CLASS_CACHE[cache_key]
