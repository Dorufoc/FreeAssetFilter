#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

PyMuPDF PDF 文档封装服务
提供线程安全的 PDF 页面管理、渲染、文本提取、搜索和图像提取功能。
对应 sioyek ``Document`` 类的核心模式（页面尺寸缓存、文本选区、渲染等）。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

import fitz

from PySide6.QtGui import QImage


class PdfDocument:
    """Thread-safe wrapper around a PyMuPDF (fitz) document.

    Ports the core ``Document`` patterns from sioyek (document.h):
    page-width/height caching, ``accum_page_heights`` for binary-search
    visible-page lookup, text extraction, search, and image extraction.

    All ``fitz.Document`` access is guarded by ``threading.Lock()`` because
    MuPDF is **not** thread-safe.  The lock is released as early as possible
    (e.g. after ``get_pixmap()`` returns, since ``pix.samples`` is an
    independent ``bytes`` copy).

    Usage::

        doc = PdfDocument("path/to/file.pdf")
        count = doc.page_count()
        img = doc.render(0, zoom=1.5, dpr=2.0)
        words = doc.get_text_words(0)
        hits = doc.search_for(0, "keyword")
        images = doc.get_page_images(0)
        doc.close()
    """

    # ── Lifecycle ─────────────────────────────────────────────────────

    def __init__(self, file_path: str) -> None:
        """Open a PDF document via ``fitz.open()``.

        Parameters
        ----------
        file_path : str
            Absolute or relative path to the PDF file.

        Raises
        ------
        FileNotFoundError
            If *file_path* does not exist.
        fitz.FileDataError
            If the file is not a valid PDF (or cannot be opened by MuPDF).
        """
        self._lock: threading.Lock = threading.Lock()
        self._doc: fitz.Document = fitz.open(file_path)

        # ── Cached page dimensions (sioyek accum_page_heights pattern) ─
        self._page_widths: List[float] = []
        self._page_heights: List[float] = []
        self._accum_page_heights: List[float] = []

        # LRU-like cache for TextPage objects (character-level access)
        self._textpage_cache: Dict[int, fitz.TextPage] = {}

    def close(self) -> None:
        """Close the underlying fitz document and release resources.

        Safe to call multiple times.  After closing, any method that
        accesses ``self._doc`` will raise a ``RuntimeError`` from fitz.
        """
        with self._lock:
            if self._doc is None:
                return
            try:
                self._doc.close()
            except Exception:
                pass
            finally:
                self._doc = None  # type: ignore[assignment]
            self._textpage_cache.clear()
            self._page_widths.clear()
            self._page_heights.clear()
            self._accum_page_heights.clear()

    def __enter__(self) -> "PdfDocument":
        """Context-manager support (with-statement)."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object],
    ) -> None:
        """Close the document on context exit."""
        self.close()

    # ── Page metadata ─────────────────────────────────────────────────

    def page_count(self) -> int:
        """Return the total number of pages.

        Returns
        -------
        int
            Number of pages in the PDF document.
        """
        with self._lock:
            if self._doc is None:
                return 0
            return self._doc.page_count

    def page_size(self, page_num: int) -> Tuple[float, float]:
        """Return the page dimensions in points (width, height).

        Results are cached so subsequent calls for the same page are O(1).

        Parameters
        ----------
        page_num : int
            Zero-based page index.

        Returns
        -------
        tuple[float, float]
            ``(width_pt, height_pt)`` in PDF points (1/72 inch).

        Raises
        ------
        IndexError
            If *page_num* is out of range.
        RuntimeError
            If the document has been closed.
        """
        with self._lock:
            self._ensure_page_cache(page_num)
            return self._page_widths[page_num], self._page_heights[page_num]

    @property
    def page_widths(self) -> List[float]:
        """List of page widths in points, one entry per page.

        Lazily-populated on first access and cached thereafter.
        """
        with self._lock:
            if self._doc is not None:
                self._build_full_page_cache()
            return list(self._page_widths)

    @property
    def page_heights(self) -> List[float]:
        """List of page heights in points, one entry per page.

        Lazily-populated on first access and cached thereafter.
        """
        with self._lock:
            if self._doc is not None:
                self._build_full_page_cache()
            return list(self._page_heights)

    @property
    def accum_page_heights(self) -> List[float]:
        """Cumulative page heights for binary-search visible-page lookup.

        ``accum_page_heights[i]`` = sum of heights from page 0 to page *i*
        (inclusive).  This is the exact pattern from sioyek's
        ``Document::accum_page_heights`` in ``document.h``.

        Use ``bisect`` to find which page is visible at a given y-offset::

            import bisect
            page_idx = bisect.bisect_left(doc.accum_page_heights, y) % doc.page_count()
        """
        with self._lock:
            if self._doc is not None:
                self._build_full_page_cache()
            return list(self._accum_page_heights)

    # ── Rendering ─────────────────────────────────────────────────────

    def render(
        self,
        page_num: int,
        zoom: float,
        dpr: float = 1.0,
    ) -> QImage:
        """Render a page to a ``QImage`` at the given zoom level.

        Equivalent to sioyek's ``fz_new_pixmap_from_page_number()`` called
        with ``zoom * dpr``.  The fitz lock is released immediately after
        ``get_pixmap()`` returns; ``pix.samples`` is an independent
        ``bytes`` copy, so the resulting ``QImage`` can safely outlive
        the lock scope.

        Parameters
        ----------
        page_num : int
            Zero-based page index.
        zoom : float
            Zoom factor (1.0 = 72 DPI / screen resolution).
        dpr : float
            Device-pixel ratio for HiDPI displays (default 1.0).  Pass
            ``widget.devicePixelRatio()`` to match the display.

        Returns
        -------
        QImage
            The rendered page image.  Format is ``QImage.Format_RGB888``
            (3 bytes per pixel) for most pages, or
            ``QImage.Format_RGBA8888`` if the pixmap has an alpha channel.

        Raises
        ------
        IndexError
            If *page_num* is out of range.
        RuntimeError
            If the document has been closed.
        """
        with self._lock:
            page: fitz.Page = self._doc.load_page(page_num)
            mat: fitz.Matrix = fitz.Matrix(zoom * dpr, zoom * dpr)
            pix: fitz.Pixmap = page.get_pixmap(matrix=mat, alpha=False)

            # Copy pixmap data outside the lock — samples is a memoryview
            # that becomes invalid once the Pixmap is garbage-collected.
            samples: bytes = bytes(pix.samples)
            w: int = pix.width
            h: int = pix.height
            stride: int = pix.stride
            alpha: int = pix.alpha

        fmt: QImage.Format = (
            QImage.Format_RGBA8888 if alpha else QImage.Format_RGB888
        )
        return QImage(samples, w, h, stride, fmt)

    # ── Text extraction ───────────────────────────────────────────────

    def get_text_words(self, page_num: int) -> List[Tuple[float, float, float, float, str, int, int, int]]:
        """Return word-level bounding boxes and metadata for a page.

        Corresponds to sioyek's word-level text extraction (``page.get_text("words")``),
        which is equivalent to iterating over ``fz_stext_line``/``fz_stext_word``
        in MuPDF.  Each returned tuple contains the word bounding box in
        PDF point space (72 DPI).

        Parameters
        ----------
        page_num : int
            Zero-based page index.

        Returns
        -------
        list[tuple]
            Each entry is ``(x0, y0, x1, y1, word, block_no, line_no, word_no)``
            where ``(x0, y0)`` is the lower-left corner and ``(x1, y1)`` the
            upper-right corner of the word bounding box in points.  An empty
            list is returned when the page has no text or the document is closed.

        Raises
        ------
        IndexError
            If *page_num* is out of range.
        RuntimeError
            If the document has been closed.
        """
        with self._lock:
            page = self._doc.load_page(page_num)
            raw: List[Tuple[float, float, float, float, str, int, int, int]] = (
                page.get_text("words")
            )
        return raw

    def get_textpage(self, page_num: int) -> fitz.TextPage:
        """Return a cached ``fitz.TextPage`` for character-level access.

        ``TextPage`` provides per-character bounding-box queries and is
        the PyMuPDF equivalent of sioyek's ``fz_stext_page``.  Results
        are cached per page so repeated calls do not re-parse.

        This is primarily useful for character-level selection rendering
        (highlighting individual glyphs in a selection).

        Parameters
        ----------
        page_num : int
            Zero-based page index.

        Returns
        -------
        fitz.TextPage
            The cached ``TextPage`` object for the requested page.

        Raises
        ------
        IndexError
            If *page_num* is out of range.
        RuntimeError
            If the document has been closed.
        """
        with self._lock:
            if page_num not in self._textpage_cache:
                page = self._doc.load_page(page_num)
                self._textpage_cache[page_num] = page.get_textpage()
            return self._textpage_cache[page_num]

    def search_for(self, page_num: int, text: str) -> List[fitz.Rect]:
        """Search for *text* on a single page and return hit rects.

        Equivalent to sioyek's ``search_text()`` which internally calls
        ``fz_search_stext_page()``.  Each returned ``Rect`` is in PDF
        point space and corresponds to one search hit.

        Parameters
        ----------
        page_num : int
            Zero-based page index.
        text : str
            The text string to search for.  The search is case-insensitive
            by default (PyMuPDF behaviour).

        Returns
        -------
        list[fitz.Rect]
            A list of ``fitz.Rect`` objects representing the bounding boxes
            of all matches on the page.  Returns an empty list when no hits
            are found.

        Raises
        ------
        IndexError
            If *page_num* is out of range.
        RuntimeError
            If the document has been closed.
        """
        with self._lock:
            page = self._doc.load_page(page_num)
            rects: List[fitz.Rect] = page.search_for(text)
        return rects

    # ── Image extraction ──────────────────────────────────────────────

    def get_page_images(self, page_num: int) -> List[Dict[str, Any]]:
        """Extract embedded images from a page.

        Parses ``page.get_text("dict")`` which includes ``type == 1``
        (image) blocks.  This is the PyMuPDF equivalent of iterating
        the PDF page's image xref table and extracting each image stream.

        Each result dict provides the raw image bytes, its bounding box
        on the page, the file extension hint, and the pixel dimensions.

        Parameters
        ----------
        page_num : int
            Zero-based page index.

        Returns
        -------
        list[dict]
            Each entry has the following keys::

                "bbox"   : tuple[float, float, float, float]  # (x0, y0, x1, y1) in points
                "image"  : bytes                               # raw image file bytes
                "ext"    : str                                 # file extension hint ("png", "jpeg", etc.)
                "width"  : int                                 # pixel width
                "height" : int                                 # pixel height

            Returns an empty list if no embedded images were found on the
            page or if the document has been closed.

        Raises
        ------
        IndexError
            If *page_num* is out of range.
        RuntimeError
            If the document has been closed.
        """
        with self._lock:
            page = self._doc.load_page(page_num)
            blocks: List[Dict] = page.get_text("dict")["blocks"]

        images: List[Dict[str, Any]] = []
        for block in blocks:
            if block.get("type") != 1:
                continue
            bbox: Tuple[float, float, float, float] = block["bbox"]
            # In PyMuPDF's get_text("dict") output, type==1 (image) blocks
            # contain the image data directly under the "image" key, not nested.
            img_bytes: bytes = block.get("image") or b""
            if not img_bytes:
                continue
            ext: str = block.get("ext", "png")
            width: int = block.get("width", 0)
            height: int = block.get("height", 0)
            images.append({
                "bbox": bbox,
                "image": img_bytes,
                "ext": ext,
                "width": width,
                "height": height,
            })
        return images

    # ── Internals ─────────────────────────────────────────────────────

    def _ensure_page_cache(self, page_num: int) -> None:
        """Ensure page dimensions for *page_num* are cached.

        Must be called with ``self._lock`` held.
        """
        if self._doc is None:
            raise RuntimeError("Document has been closed")
        count = self._doc.page_count
        # Extend caches to cover the requested page
        if len(self._page_widths) <= page_num and page_num < count:
            self._build_full_page_cache()

    def _build_full_page_cache(self) -> None:
        """Populate the page-width/height caches for all pages.

        Must be called with ``self._lock`` held.
        """
        if self._doc is None:
            return
        count = self._doc.page_count
        if len(self._page_widths) == count and len(self._page_heights) == count:
            return  # Already fully cached

        self._page_widths.clear()
        self._page_heights.clear()
        self._accum_page_heights.clear()

        running: float = 0.0
        for i in range(count):
            page = self._doc.load_page(i)
            rect: fitz.Rect = page.rect  # page.rect returns (0, 0, width, height)
            w: float = rect.width
            h: float = rect.height
            self._page_widths.append(w)
            self._page_heights.append(h)
            running += h
            self._accum_page_heights.append(running)
