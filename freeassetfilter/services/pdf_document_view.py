#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

PdfDocumentView — 坐标系统和视图变换模块
纯数学层，对应 sioyek ``DocumentView`` + ``coordinates.h``。

提供 Document（页面局部）、Absolute Document（纵向拼接）、
Virtual（缩放+偏移）和 Window（像素）共 5 层坐标空间的相互变换，
以及缩放管理、文本选区计算和可见页查找。
"""

from __future__ import annotations

import bisect
from collections import deque
from typing import List, Tuple

from PySide6.QtCore import QRectF

from freeassetfilter.services.pdf_document import PdfDocument


class PdfDocumentView:
    """Coordinate system and view transform for PDF rendering.

    Ports sioyek's ``DocumentView`` (``document_view.h``) and
    ``coordinates.h`` to Python.  This is a **pure math layer** — no Qt
    widgets, no ``QPainter``, no display/rendering logic.

    Five coordinate spaces are supported:

    =============== ========== ====== =====================================
    Space           Coord       Unit   Description
    =============== ========== ====== =====================================
    Document        ``x_pt``,  pt     Position within a single page
                             ``y_pt``       (top-left origin, PDF points)
    Absolute        ``abs_x``, pt     Pages stacked vertically
    Document        ``abs_y``         (Y increases downward)
    Virtual         ``virt_x``, zoomed  After ``(abs - offset) * zoom``
                             ``virt_y``    space
    Window          ``win_x``, px     Widget pixel coordinates
    (screen)        ``win_y``         (0,0 = top-left of viewport)
    =============== ========== ====== =====================================

    Ported coordinate formulas (center-based model):

    - Forward::

        win_x = (abs_x - offset_x) * zoom_level + view_width / 2
        win_y = (abs_y - offset_y) * zoom_level + view_height / 2

    - Backward::

        abs_x = (win_x - view_width / 2) / zoom_level + offset_x
        abs_y = (win_y - view_height / 2) / zoom_level + offset_y

    Parameters
    ----------
    doc : PdfDocument
        The PDF document to view.
    zoom_level : float, optional
        Initial zoom factor (default ``1.0``).
    offset_x : float, optional
        Initial absolute-X at viewport centre (default ``0.0``).
    offset_y : float, optional
        Initial absolute-Y at viewport centre (default ``0.0``).
    view_width : int, optional
        Viewport width in pixels (default ``800``).
    view_height : int, optional
        Viewport height in pixels (default ``600``).
    page_space_x : float, optional
        Horizontal gap between rendered pages in pixels (default ``10.0``).
    page_space_y : float, optional
        Vertical gap between rendered pages in pixels (default ``10.0``).
    """

    # ── Lifecycle ─────────────────────────────────────────────────────

    def __init__(
        self,
        doc: PdfDocument,
        zoom_level: float = 1.0,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        view_width: int = 800,
        view_height: int = 600,
        page_space_x: float = 10.0,
        page_space_y: float = 10.0,
    ) -> None:
        self.doc: PdfDocument = doc

        # ── Core view state ────────────────────────────────────────────
        # zoom_level: 1.0 = fit-to-width baseline (not necessarily 100%).
        self.zoom_level: float = zoom_level

        # offset_x / offset_y: the absolute-document-space coordinate that
        # sits at the **centre** of the viewport (centre-based scroll model).
        self.offset_x: float = offset_x
        self.offset_y: float = offset_y

        # Viewport dimensions in device-independent pixels.
        self.view_width: int = view_width
        self.view_height: int = view_height

        # Gap between rendered page images in pixels.
        self.page_space_x: float = page_space_x
        self.page_space_y: float = page_space_y

        # Selection highlight rects (in widget-window coordinates).
        # Populated by ``get_text_selection()``; consumed by a renderer.
        self.selected_character_rects: deque[QRectF] = deque()

        # Cached selection word data in absolute document space.
        # Used by ``refresh_selection_rects()`` to recompute window rects
        # after scroll/zoom without re-querying the PDF.
        # Each entry: (page, block, line, wno, word, abs_x0, abs_y0, abs_x1, abs_y1)
        self._cached_sel_words: List[Tuple[int, int, int, int, str, float, float, float, float]] = []  # noqa: E501

        # ── Cached page dimensions (populated from doc on first access) ─
        self._page_widths: List[float] = []
        self._page_heights: List[float] = []
        self._accum_page_heights: List[float] = []

    # ── Internal cache helpers ─────────────────────────────────────────

    def _ensure_cached(self) -> None:
        """Lazily populate page-dimension caches from the document.

        Delegates to ``PdfDocument.page_widths``, ``page_heights``, and
        ``accum_page_heights`` which are themselves lazily populated.
        Safe to call repeatedly.
        """
        if self._page_widths:
            return  # Already cached.
        self._page_widths = list(self.doc.page_widths)
        self._page_heights = list(self.doc.page_heights)
        self._accum_page_heights = list(self.doc.accum_page_heights)

    # ── Coordinate transforms ─────────────────────────────────────────

    def document_to_window_pos(
        self, page: int, x_pt: float, y_pt: float
    ) -> Tuple[float, float]:
        """Convert **document** space → **window** space (pixels).

        The page is additionally centred horizontally within the viewport
        so that narrow pages do not hug the left edge.

        Parameters
        ----------
        page : int
            Zero-based page index.
        x_pt : float
            X coordinate on the page in PDF points.
        y_pt : float
            Y coordinate on the page in PDF points.

        Returns
        -------
        tuple[float, float]
            ``(win_x, win_y)`` in widget pixel coordinates.
        """
        self._ensure_cached()
        # Document → Absolute (pages stacked vertically).
        page_top = (
            self._accum_page_heights[page - 1] if page > 0 else 0.0
        )
        abs_x: float = x_pt
        abs_y: float = page_top + y_pt

        # Absolute → Window (centre-based viewport model).
        win_x: float = (
            (abs_x - self.offset_x) * self.zoom_level + self.view_width / 2
        )
        win_y: float = (
            (abs_y - self.offset_y) * self.zoom_level + self.view_height / 2
        )

        # Per-page horizontal centering so the page sits in the middle of
        # the viewport regardless of its width.
        page_width_pt: float = self._page_widths[page]
        win_x += (
            self.view_width - page_width_pt * self.zoom_level
        ) / 2

        return (win_x, win_y)

    def window_to_document_pos(
        self, win_x: float, win_y: float
    ) -> Tuple[int, float, float]:
        """Convert **window** space → **document** space.

        Parameters
        ----------
        win_x : float
            X coordinate in widget pixels.
        win_y : float
            Y coordinate in widget pixels.

        Returns
        -------
        tuple[int, float, float]
            ``(page, x_pt, y_pt)`` where *page* is the zero-based page
            index and ``(x_pt, y_pt)`` are the coordinates within that
            page in PDF points.
        """
        self._ensure_cached()
        # Window → Absolute (inverse of centre-based viewport model).
        abs_x: float = (
            win_x - self.view_width / 2
        ) / self.zoom_level + self.offset_x
        abs_y: float = (
            win_y - self.view_height / 2
        ) / self.zoom_level + self.offset_y

        # Absolute → Document.
        page, y_pt = self.absolute_to_page(abs_y)
        x_pt: float = abs_x
        return (page, x_pt, y_pt)

    def window_to_absolute_document_pos(
        self, win_x: float, win_y: float
    ) -> Tuple[float, float]:
        """Convert **window** space → **absolute document** space.

        Parameters
        ----------
        win_x : float
            X coordinate in widget pixels.
        win_y : float
            Y coordinate in widget pixels.

        Returns
        -------
        tuple[float, float]
            ``(abs_x, abs_y)`` in the concatenated-Y absolute space.
        """
        abs_x: float = (
            win_x - self.view_width / 2
        ) / self.zoom_level + self.offset_x
        abs_y: float = (
            win_y - self.view_height / 2
        ) / self.zoom_level + self.offset_y
        return (abs_x, abs_y)

    def absolute_to_window_pos(
        self, abs_x: float, abs_y: float
    ) -> Tuple[float, float]:
        """Convert **absolute document** space → **window** space.

        Parameters
        ----------
        abs_x : float
            X in absolute document space (PDF points).
        abs_y : float
            Y in absolute document space (PDF points).

        Returns
        -------
        tuple[float, float]
            ``(win_x, win_y)`` in widget pixel coordinates.
        """
        win_x: float = (
            abs_x - self.offset_x
        ) * self.zoom_level + self.view_width / 2
        win_y: float = (
            abs_y - self.offset_y
        ) * self.zoom_level + self.view_height / 2
        return (win_x, win_y)

    def absolute_to_window_rect(
        self,
        abs_x0: float,
        abs_y0: float,
        abs_x1: float,
        abs_y1: float,
    ) -> QRectF:
        """Convert an absolute-document **rectangle** → widget ``QRectF``.

        Parameters
        ----------
        abs_x0 : float
            Left edge in absolute document space.
        abs_y0 : float
            Top edge in absolute document space.
        abs_x1 : float
            Right edge in absolute document space.
        abs_y1 : float
            Bottom edge in absolute document space.

        Returns
        -------
        QRectF
            The rectangle in widget pixel coordinates (normalised so that
            width and height are non-negative).
        """
        x0, y0 = self.absolute_to_window_pos(abs_x0, abs_y0)
        x1, y1 = self.absolute_to_window_pos(abs_x1, abs_y1)
        left: float = min(x0, x1)
        top: float = min(y0, y1)
        width: float = abs(x1 - x0)
        height: float = abs(y1 - y0)
        return QRectF(left, top, width, height)

    def absolute_to_page(self, abs_y: float) -> Tuple[int, float]:
        """Resolve an absolute-document Y coordinate to a page + in-page Y.

        Uses binary search on ``_accum_page_heights`` — O(log N).

        Parameters
        ----------
        abs_y : float
            Y coordinate in absolute document space (PDF points).

        Returns
        -------
        tuple[int, float]
            ``(page, y_within_page)`` where *page* is the zero-based page
            index and *y_within_page* is clamped to ``[0, page_height]``.
        """
        self._ensure_cached()
        if not self._accum_page_heights:
            return (0, max(0.0, abs_y))

        i: int = bisect.bisect_left(self._accum_page_heights, abs_y)
        i = min(i, len(self._accum_page_heights) - 1)

        page_top: float = (
            self._accum_page_heights[i] - self._page_heights[i]
        )
        y_within_page: float = abs_y - page_top
        y_within_page = max(0.0, min(y_within_page, self._page_heights[i]))

        return (i, y_within_page)

    # ── Zoom management ───────────────────────────────────────────────

    def set_zoom_level(self, zl: float, exit_auto_resize: bool = True) -> float:
        """Set the zoom level, clamped to ``[0.1, 10.0]``.

        Parameters
        ----------
        zl : float
            Desired zoom level.
        exit_auto_resize : bool, optional
            Reserved for future use (e.g. disabling auto-resize on manual
            zoom).  Currently unused.

        Returns
        -------
        float
            The actual zoom level after clamping.
        """
        del exit_auto_resize  # Reserved for future use.
        self.zoom_level = max(0.1, min(10.0, zl))
        return self.zoom_level

    def zoom_in(self, factor: float = 1.2) -> float:
        """Multiply the current zoom by *factor*.

        Parameters
        ----------
        factor : float, optional
            Zoom multiplication factor (default ``1.2``).

        Returns
        -------
        float
            The new zoom level after clamping.
        """
        return self.set_zoom_level(self.zoom_level * factor)

    def zoom_out(self, factor: float = 1.2) -> float:
        """Divide the current zoom by *factor*.

        Parameters
        ----------
        factor : float, optional
            Zoom division factor (default ``1.2``).

        Returns
        -------
        float
            The new zoom level after clamping.
        """
        return self.set_zoom_level(self.zoom_level / factor)

    def fit_to_page_width(self, view_width: int, view_height: int) -> float:
        """Calculate the zoom level so the first page fills the viewport width.

        The zoom is computed as::

            win_page_width = view_width - 2 * margin
            zoom = win_page_width / page_width_pt

        with a 20-pixel margin on each side.

        Parameters
        ----------
        view_width : int
            Viewport width in pixels (also stored as ``self.view_width``).
        view_height : int
            Viewport height in pixels (also stored as ``self.view_height``).

        Returns
        -------
        float
            The new zoom level (clamped to ``[0.1, 10.0]``).
        """
        self._ensure_cached()
        self.view_width = view_width
        self.view_height = view_height

        if not self._page_widths:
            return self.zoom_level

        margin: float = 20.0
        page_width_pt: float = self._page_widths[0]
        win_page_width: float = view_width - 2 * margin
        if page_width_pt > 0:
            new_zoom: float = win_page_width / page_width_pt
        else:
            new_zoom = 1.0

        return self.set_zoom_level(new_zoom)

    def get_zoom_for_scale(self, percent: int) -> float:
        """Convert a percentage scale to an absolute zoom factor.

        A value of ``100`` corresponds to fit-to-page-width zoom level,
        so larger percentages zoom in further.

        Parameters
        ----------
        percent : int
            Scale percentage (e.g. ``50``, ``100``, ``200``).

        Returns
        -------
        float
            The absolute zoom factor.
        """
        self._ensure_cached()
        if not self._page_widths:
            return self.zoom_level

        margin: float = 20.0
        page_width_pt: float = self._page_widths[0]
        fit_to_width_zoom: float = (
            (self.view_width - 2 * margin) / page_width_pt
            if page_width_pt > 0
            else 1.0
        )
        return fit_to_width_zoom * percent / 100.0

    # ── Scroll / offset ───────────────────────────────────────────────

    def move(self, dx: float, dy: float) -> bool:
        """Pan the view by *dx* and *dy* in absolute document space.

        Parameters
        ----------
        dx : float
            Delta X in absolute document space (positive = right).
        dy : float
            Delta Y in absolute document space (positive = down).

        Returns
        -------
        bool
            ``True`` if the offset actually changed (delta was
            non-negligible).
        """
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return False
        self.offset_x += dx
        self.offset_y += dy
        return True

    def get_visible_pages(self) -> List[int]:
        """Return the list of pages currently visible in the viewport.

        Uses binary search on ``_accum_page_heights`` to narrow the
        candidate range, then checks exact overlap for each candidate.
        Ported from sioyek ``DocumentView::get_visible_pages()``.

        Returns
        -------
        list[int]
            Zero-based page indices that intersect the current viewport.
            Empty list if the document has no pages.
        """
        self._ensure_cached()
        if not self._accum_page_heights:
            return []

        # Viewport top / bottom in absolute document space (centre-based).
        half_view_abs: float = self.view_height / 2 / self.zoom_level
        visible_top: float = self.offset_y - half_view_abs
        visible_bottom: float = self.offset_y + half_view_abs

        # Binary search to narrow the page range.
        first: int = bisect.bisect_left(
            self._accum_page_heights, visible_top
        )
        last: int = bisect.bisect_left(
            self._accum_page_heights, visible_bottom
        )

        # Clamp to valid page indices.
        first = max(0, first)
        last = min(last, len(self._accum_page_heights) - 1)

        # Linear overlap check within the candidate range.
        visible: List[int] = []
        for i in range(first, last + 1):
            page_top: float = (
                self._accum_page_heights[i] - self._page_heights[i]
            )
            page_bottom: float = self._accum_page_heights[i]
            if page_top < visible_bottom and page_bottom > visible_top:
                visible.append(i)

        return visible

    def goto_page(self, page: int) -> None:
        """Scroll so that page *page* is at the top of the viewport.

        Parameters
        ----------
        page : int
            Zero-based page index.
        """
        self._ensure_cached()
        if not self._accum_page_heights or page < 0:
            return
        if page >= len(self._page_heights):
            page = len(self._page_heights) - 1

        # Page top Y in absolute document space.
        page_top: float = (
            self._accum_page_heights[page] - self._page_heights[page]
        )

        # Centre-based model: for the page top to be at viewport pixel Y=0:
        #   0 = (page_top - offset_y) * zoom + view_height / 2
        #   offset_y = page_top + view_height / (2 * zoom)
        self.offset_y = page_top + self.view_height / (2 * self.zoom_level)

    def move_pages(self, num_pages: int) -> None:
        """Scroll by *num_pages* (positive = forward / downward).

        Parameters
        ----------
        num_pages : int
            Number of pages to scroll.  Positive values move forward
            (to later pages); negative values move backward.
        """
        if num_pages == 0 or not self._accum_page_heights:
            return

        # Identify the current page from the centre Y.
        page_idx: int = bisect.bisect_left(
            self._accum_page_heights, self.offset_y
        )
        page_idx = min(page_idx, len(self._accum_page_heights) - 1)

        target: int = page_idx + num_pages
        target = max(0, min(target, len(self._accum_page_heights) - 1))
        self.goto_page(target)

    # ── Text selection ─────────────────────────────────────────────────

    def get_text_selection(
        self,
        begin_abs_x: float,
        begin_abs_y: float,
        end_abs_x: float,
        end_abs_y: float,
    ) -> str:
        """Extract text within a selection rectangle in absolute-document space.

        Workflow:
        1. Normalise the selection rectangle (min/max bounds).
        2. Determine the range of affected pages via ``absolute_to_page``.
        3. For each page, call ``PdfDocument.get_text_words(page)``.
        4. Filter words whose bounding-box intersects the selection rect.
        5. Sort by ``(page, block_no, line_no, word_no)``.
        6. Store the window-space rects in ``selected_character_rects``.
        7. Return the joined text string (space-separated).

        Parameters
        ----------
        begin_abs_x : float
            Start X in absolute document space.
        begin_abs_y : float
            Start Y in absolute document space.
        end_abs_x : float
            End X in absolute document space.
        end_abs_y : float
            End Y in absolute document space.

        Returns
        -------
        str
            The selected text, with words separated by spaces.
        """
        self._ensure_cached()
        if not self._accum_page_heights:
            return ""

        # Normalise the selection rectangle.
        x0: float = min(begin_abs_x, end_abs_x)
        x1: float = max(begin_abs_x, end_abs_x)
        y0: float = min(begin_abs_y, end_abs_y)
        y1: float = max(begin_abs_y, end_abs_y)

        start_page, _ = self.absolute_to_page(y0)
        end_page, _ = self.absolute_to_page(y1)

        # Determine drag direction for smart x-bound filtering.
        dragging_down: bool = begin_abs_y <= end_abs_y

        # Collect matching words across affected pages.
        # Each entry: (page, block_no, line_no, word_no, word_text, x0, y0, x1, y1)
        selected_words: List[Tuple[int, int, int, int, str, float, float, float, float]] = []  # noqa: E501

        for p in range(start_page, end_page + 1):
            page_top: float = (
                self._accum_page_heights[p] - self._page_heights[p]
            )

            # Clip the selection rect to this page's bounds.
            sel_y0: float = max(y0 - page_top, 0.0)
            sel_y1: float = min(y1 - page_top, self._page_heights[p])

            words = self.doc.get_text_words(p)
            for w in words:
                wx0, wy0, wx1, wy1, word, block, line, wno = w

                # Y overlap is always required.
                if not (wy0 < sel_y1 and wy1 > sel_y0):
                    continue

                # ── Smart x-bound filtering ──────────────────────────
                # For middle lines (fully inside the vertical selection),
                # expand x to full width so all words on those lines are
                # included.  Only the first/last line respect the drag
                # start/end x-coordinate.
                #
                #   dragging down: first line = top (y0), last = bottom (y1)
                #   dragging up:   first line = bottom (y1), last = top (y0)
                word_abs_y0: float = wy0 + page_top
                word_abs_y1: float = wy1 + page_top

                touches_top: bool = word_abs_y0 < y0 < word_abs_y1
                touches_bottom: bool = word_abs_y0 < y1 < word_abs_y1
                strictly_inside: bool = (
                    word_abs_y0 >= y0 and word_abs_y1 <= y1
                )

                if strictly_inside and not touches_top and not touches_bottom:
                    # Middle region — accept regardless of x.
                    pass
                elif touches_top and not touches_bottom:
                    # Overlaps the selection top boundary.
                    if dragging_down:
                        # Top is the start line — from begin_x to right.
                        if not (wx1 > begin_abs_x):
                            continue
                    else:
                        # Top is the end line — from left to end_x.
                        if not (wx0 < end_abs_x):
                            continue
                elif touches_bottom and not touches_top:
                    # Overlaps the selection bottom boundary.
                    if dragging_down:
                        # Bottom is the end line — from left to end_x.
                        if not (wx0 < end_abs_x):
                            continue
                    else:
                        # Bottom is the start line — from begin_x to right.
                        if not (wx1 > begin_abs_x):
                            continue
                # else: word spans both boundaries (rare) — use normalised
                # rect which is already applied via the y-overlap check.

                selected_words.append(
                    (p, block, line, wno, word, wx0, wy0, wx1, wy1)
                )

        # Sort by (page, block, line, word_no).
        selected_words.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

        # Cache in absolute document space so rects can be refreshed
        # after scroll/zoom without re-querying the PDF.
        self._cached_sel_words = list(selected_words)

        # Populate selection highlight rects in window space.
        self._refresh_selection_rects()

        # Join text.
        return " ".join(entry[4] for entry in selected_words)

    def _refresh_selection_rects(self) -> None:
        """Recompute ``selected_character_rects`` from cached selection words
        using the current ``zoom_level``, ``offset_x`` and ``offset_y``.

        Called after ``get_text_selection()`` and also whenever the view
        scrolls or zooms so highlight rects stay aligned with the page.
        """
        self.selected_character_rects.clear()
        for entry in self._cached_sel_words:
            _p, _block, _line, _wno, _word, wx0, wy0, wx1, wy1 = entry
            page_top: float = (
                self._accum_page_heights[_p] - self._page_heights[_p]
            )
            abs_x0_f: float = wx0
            abs_y0_f: float = wy0 + page_top
            abs_x1_f: float = wx1
            abs_y1_f: float = wy1 + page_top
            win_rect: QRectF = self.absolute_to_window_rect(
                abs_x0_f, abs_y0_f, abs_x1_f, abs_y1_f
            )
            self.selected_character_rects.append(win_rect)

    def clear_selection(self) -> None:
        """Clear the current text selection."""
        self.selected_character_rects.clear()
        self._cached_sel_words.clear()
