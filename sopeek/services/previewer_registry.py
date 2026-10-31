#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sopeek v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/Sopeek
许可协议：https://github.com/Dorufoc/Sopeek/blob/main/LICENSE

预览器注册服务
根据文件扩展名映射到对应的预览器组件类（纯映射逻辑，不含 UI 创建）。
"""

from __future__ import annotations

import importlib
from typing import Dict, Optional


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
        "jpg":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "jpeg": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "png":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "gif":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "bmp":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "tiff": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "webp": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "svg":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "avif": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "heic": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "heif": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "cr2":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "cr3":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "crw":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "nef":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "nrw":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "arw":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "dng":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "orf":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "srf":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "sr2":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "srw":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "raf":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "rw2":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "pef":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "ptx":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "x3f":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "ico":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "icon": ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        "psd":  ("sopeek.ui.layout.preview.image_previewer_layout", "ImagePreviewerLayout"),
        # ── Videos ──────────────────────────────────────────────────────
        "mp4":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "avi":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mov":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mkv":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "m4v":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mxf":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "3gp":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mpg":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "wmv":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "webm": ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "vob":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ogv":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "rmvb": ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "m2ts": ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ts":   ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "mts":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        # ── Audio (also uses VideoPlayerLayout in audio mode) ───────────────
        "mp3":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "wav":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "flac": ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ogg":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "wma":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "m4a":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "aiff": ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "ape":  ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        "opus": ("sopeek.ui.layout.preview.video_player_layout", "VideoPlayerLayout"),
        # ── PDF ─────────────────────────────────────────────────────────
        "pdf":  ("sopeek.ui.layout.preview.pdf_previewer_layout", "PdfPreviewerLayout"),
        # ── Text / Code ─────────────────────────────────────────────────
        "txt":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "md":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "rst":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "py":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "java":  ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "cpp":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "js":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "html":  ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "css":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "php":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "c":     ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "h":     ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "cs":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "go":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "rb":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "swift": ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "kt":    ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "yml":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "yaml":  ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "json":  ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        "xml":   ("sopeek.ui.layout.preview.text_previewer_layout", "TextPreviewerLayout"),
        # ── Archives ────────────────────────────────────────────────────
        "zip":  ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "rar":  ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "tar":  ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "gz":   ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "tgz":  ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "bz2":  ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "xz":   ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "7z":   ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        "iso":  ("sopeek.ui.layout.preview.archive_previewer_layout", "ArchivePreviewerLayout"),
        # ── Fonts ───────────────────────────────────────────────────────
        "ttf":   ("sopeek.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "otf":   ("sopeek.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "woff":  ("sopeek.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "woff2": ("sopeek.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        "eot":   ("sopeek.ui.layout.preview.font_previewer_layout", "FontPreviewerLayout"),
        # ── Office ──────────────────────────────────────────────────────
        "doc":   ("sopeek.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "docx":  ("sopeek.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "xls":   ("sopeek.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "xlsx":  ("sopeek.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "ppt":   ("sopeek.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
        "pptx":  ("sopeek.ui.layout.preview.office_previewer_layout", "OfficePreviewerLayout"),
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
        # Directory → FolderPreviewerLayout
        if file_info.get("is_dir", False):
            return cls._import_class(
                "sopeek.ui.layout.preview.folder_previewer_layout",
                "FolderPreviewerLayout",
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
            Dotted module path (e.g. ``"sopeek.components.photo_viewer"``).
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
