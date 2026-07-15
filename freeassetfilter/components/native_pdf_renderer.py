#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FreeAssetFilter v1.0

Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

协议说明：本软件基于 AGPL-3.0 协议开源
1. 个人非商业使用：需保留本注释及开发者署名；

项目地址：https://github.com/Dorufoc/FreeAssetFilter
许可协议：https://github.com/Dorufoc/FreeAssetFilter/blob/main/LICENSE

NativePdfRenderer — 基于 QPainter 的完整 PDF 交互式渲染组件

移植自 sioyek 的 PdfViewOpenGLWidget (pdf_view_opengl_widget.h/cpp)，
使用 QPainter 替代 OpenGL 进行页面渲染合成。
集成三个服务层：
  - PdfDocument (PyMuPDF 文档管理)
  - PdfDocumentView (坐标系统和视图变换)
  - PdfBackgroundRenderer (多线程后台渲染 + LRU 缓存)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
)

from freeassetfilter.services.pdf_document import PdfDocument
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.services.pdf_document_view import PdfDocumentView
from freeassetfilter.services.pdf_renderer import PdfBackgroundRenderer
from freeassetfilter.ui.theme import tm


class NativePdfRenderer(QWidget):
    """Interactive PDF viewer widget built on QPainter.

    Ports the core rendering and interaction patterns from sioyek's
    ``PdfViewOpenGLWidget`` (see ``pdf_view_opengl_widget.h``).  The
    three PDF service layers are integrated as follows:

    1. **PdfDocument**  — holds the PyMuPDF ``fitz.Document``, provides
       page dimensions, text extraction, and image extraction.
    2. **PdfDocumentView** — manages the coordinate system (5 spaces),
       zoom level, scroll offset, and text-selection state.  Pure math
       layer — no Qt widgets.
    3. **PdfBackgroundRenderer** — background-thread page rendering via
       ``QThreadPool`` + ``QRunnable``.  Results are cached in an LRU
       ``OrderedDict`` with closest-zoom fallback.

    Signals
    -------
    page_changed : Signal(int)
        Emitted when the current page changes (0-based index).
    total_pages_changed : Signal(int)
        Emitted when the document is loaded with its page count.
    zoom_changed : Signal(float)
        Emitted when the zoom level changes.

    Usage
    -----
    >>> w = NativePdfRenderer()
    >>> w.load_document("path/to/doc.pdf")
    >>> w.page_count()
    42
    >>> w.current_page()
    0
    >>> w.go_to_page(5)
    >>> w.fit_to_page()
    """

    # ── Signals (sioyek PdfViewOpenGLWidget pattern) ───────────────────

    page_changed = Signal(int)           # 0-based page number
    total_pages_changed = Signal(int)    # total page count
    zoom_changed = Signal(float)         # current zoom level

    # ── Lifecycle ─────────────────────────────────────────────────────

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        settings_manager: Any = None,
        dpi_scale: Optional[float] = None,
        global_font: Optional[QFont] = None,
    ) -> None:
        """Initialize the renderer widget.

        Parameters
        ----------
        parent : QWidget | None
            Parent widget (default ``None``).
        settings_manager : object | None
            Application settings manager (unused, reserved for theme
            integration; default ``None``).
        dpi_scale : float | None
            DPI scaling factor (defaults to QApplication attribute).
        global_font : QFont | None
            Global application font (defaults to QApplication attribute).
        """
        super().__init__(parent)

        # ── Store config (matching project convention) ─────────────────
        self._settings_manager = settings_manager
        self._dpi_scale: float = (
            dpi_scale
            if dpi_scale is not None
            else getattr(QApplication.instance(), "dpi_scale_factor", 1.0)
        )
        self._global_font: QFont = (
            global_font
            if global_font is not None
            else getattr(QApplication.instance(), "global_font", QFont())
        )

        # ── Widget behaviour ───────────────────────────────────────────
        # Accept keyboard focus (for Ctrl detection) and enable mouse
        # tracking so we receive mouse-move events even without a button
        # held (useful for cursor feedback).
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

        # ── Service layers ─────────────────────────────────────────────
        self._doc: Optional[PdfDocument] = None
        self._view: Optional[PdfDocumentView] = None
        self._renderer: PdfBackgroundRenderer = PdfBackgroundRenderer(max_cache=10)
        self._renderer.render_ready.connect(self._on_page_rendered)
        self._file_path: Optional[str] = None

        # ── Cached page dimensions (set in load_document) ──────────────
        self._page_widths: List[float] = []
        self._page_heights: List[float] = []
        self._accum_heights: List[float] = []

        # ── Interaction state ──────────────────────────────────────────
        # 文本选择
        self._selecting: bool = False
        self._sel_begin_abs: Tuple[float, float] = (0.0, 0.0)
        self._sel_end_abs: Tuple[float, float] = (0.0, 0.0)
        self._selected_text: str = ""

        # 点击非选区时隐藏高亮但保留剪贴板文字
        self._selection_hidden: bool = False
        # 追踪鼠标是否在 press 后有实质移动（区分"点击"与"拖拽"）
        self._mouse_dragged: bool = False

        # 中键拖拽滚动
        self._dragging: bool = False
        self._drag_start: QPointF = QPointF()

        # 需要重新 fit（首次真实 resize 时触发，解决 QStackedLayout 中隐藏时的尺寸 0 问题）
        self._resize_need_fit: bool = False



        # Ctrl 键追踪
        self._ctrl_pressed: bool = False

        # 滚轮由 _WheelSmoothScrollFilter 处理（安装在 layout 中）

    def _clamp_offset(self, zoom: float) -> None:
        """限制 offset_x/offset_y：页面超出视口时允许 ±30px 摆动，否则居中。"""
        margin_abs = 30.0 / max(zoom, 0.01)
        if self._page_widths and self._view is not None:
            pw = self._page_widths[0]
            half_vw = self._view.view_width / (2.0 * zoom)
            if pw * zoom < self._view.view_width - 60.0:
                # 页面窄于视口 → 居中
                self._view.offset_x = pw / 2.0
            else:
                # 页面宽于视口 → ±30px 边界
                self._view.offset_x = max(half_vw - margin_abs, min(pw - half_vw + margin_abs, self._view.offset_x))
        if self._accum_heights and self._view is not None:
            total = self._accum_heights[-1]
            half_vh = self._view.view_height / (2.0 * zoom)
            if total * zoom < self._view.view_height - 60.0:
                # 文档矮于视口 → 居中（文档中间对齐视口中间）
                self._view.offset_y = total / 2.0
            else:
                # 文档高于视口 → ±30px 边界
                self._view.offset_y = max(half_vh - margin_abs, min(total - half_vh + margin_abs, self._view.offset_y))

    # ── Public API ────────────────────────────────────────────────────

    def load_document(self, file_path: str) -> bool:
        """Open a PDF and set up the view for interactive rendering.

        Workflow (matching sioyek's document-open behaviour):
        1. Clean up any previously loaded document.
        2. Open ``PdfDocument(path)``.
        3. Create ``PdfDocumentView`` with the page dimensions cached.
        4. Fit to page width and initialise the scroll offset.
        5. Emit ``page_changed(0)`` and ``total_pages_changed(count)``.
        6. Submit initial render requests for the first visible pages.

        Parameters
        ----------
        file_path : str
            Path to the PDF file to open.

        Returns
        -------
        bool
            ``True`` if the document was successfully loaded.
        """
        # Clean up previous document.
        self._renderer.cancel_all()
        if self._doc is not None:
            self._doc.close()
            self._doc = None
            self._view = None

        if not os.path.exists(file_path):
            return False

        try:
            self._doc = PdfDocument(file_path)
        except Exception:
            self._doc = None
            self._file_path = None
            return False

        self._file_path = file_path

        # Cache page dimensions locally for fast paintEvent access.
        self._page_widths = list(self._doc.page_widths)
        self._page_heights = list(self._doc.page_heights)
        self._accum_heights = list(self._doc.accum_page_heights)

        # Create the view with the current widget size.
        w: int = self.width()
        h: int = self.height()
        self._view = PdfDocumentView(
            doc=self._doc,
            zoom_level=1.0,
            offset_x=0.0,
            offset_y=0.0,
            view_width=w,
            view_height=h,
        )

        # sioyek: fit-to-width as initial zoom.
        # 如果 widget 尺寸为 0（隐藏在 QStackedLayout 中），zoom 会错误地极小，
        # 此时暂不 fit，等 resizeEvent 由 _resize_need_fit 标志触发。
        if w > 0 and h > 0:
            self._view.fit_to_page_width(w, h)
            # Center-based 模型：offset_x 是视口中心对应的绝对坐标。
            # 设为页面宽度的一半使页面左边缘对齐视口左边缘，避免页面被挤到右侧。
            if self._page_widths:
                self._view.offset_x = self._page_widths[0] / 2.0
        else:
            self._resize_need_fit = True

        # Scroll to the top of the document.
        self._view.offset_y = self._view.view_height / (2 * max(self._view.zoom_level, 0.01))

        # Emit initial signals.
        total: int = self._doc.page_count()
        self.page_changed.emit(0)
        self.total_pages_changed.emit(total)
        # 发射 zoom_changed 通知 layout 设置滚动条范围
        self.zoom_changed.emit(self._view.zoom_level)

        # Submit render requests for visible pages.
        self._submit_render_for_visible_pages()
        self.update()

        return True

    def go_to_page(self, page: int) -> None:
        """Navigate to a specific page (0-based).

        Parameters
        ----------
        page : int
            Zero-based page index.
        """
        if self._view is None:
            return
        self._view.goto_page(page)
        self._view.clear_selection()
        self._selected_text = ""
        self._submit_render_for_visible_pages()
        self.page_changed.emit(page)
        self.update()

    def set_zoom(self, zoom: float) -> None:
        """Set the zoom level directly.

        Parameters
        ----------
        zoom : float
            Desired zoom level (clamped to [0.1, 10.0]).
        """
        if self._view is None:
            return
        self._view.set_zoom_level(zoom)
        self._clamp_offset(self._view.zoom_level)
        self._submit_render_for_visible_pages()
        self.zoom_changed.emit(self._view.zoom_level)
        self.update()

    def fit_to_page(self) -> None:
        """Zoom so that the page width fills the viewport."""
        if self._view is None:
            return
        target = self._view.fit_to_page_width(self.width(), self.height())
        self._view.zoom_level = target
        # 重置水平偏移使页面左边缘对齐视口左边缘
        if self._page_widths:
            self._view.offset_x = self._page_widths[0] / 2.0
        self._clamp_offset(target)
        self._submit_render_for_visible_pages()
        self.zoom_changed.emit(target)
        self.update()

    def page_count(self) -> int:
        """Return the total number of pages.

        Returns
        -------
        int
            Page count, or 0 if no document is loaded.
        """
        if self._doc is None:
            return 0
        return self._doc.page_count()

    def current_page(self) -> int:
        """Return the current (centre-of-viewport) page number, 0-based.

        Returns
        -------
        int
            Page index at the viewport centre.
        """
        if self._view is None or not self._accum_heights:
            return 0
        page, _ = self._view.absolute_to_page(self._view.offset_y)
        return page

    # ── Qt event overrides (sioyek mouse/wheel patterns) ──────────────

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        """Render the PDF pages and interaction overlays.

        Ported from sioyek's ``PdfViewOpenGLWidget::paintGL()`` which:
        1. Clears the viewport.
        2. Iterates visible pages, drawing each rendered texture.
        3. Overlays selection highlights.
        4. Draws a page-number HUD.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. 背景使用主题表面色，使卡片式白色页面凸显
        painter.fillRect(self.rect(), QColor(tm.surface.name()))

        # 2. 无文档时显示提示文字
        if self._doc is None or self._view is None:
            painter.setPen(QColor(160, 160, 160))
            font = painter.font()
            font.setPointSize(14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "未加载文档")
            painter.end()
            return

        zoom: float = self._view.zoom_level
        visible: List[int] = self._view.get_visible_pages()

        # 3. 渲染所有可见页面
        for page_num in visible:
            if page_num >= len(self._page_widths):
                continue

            pw: float = self._page_widths[page_num]
            ph: float = self._page_heights[page_num]

            # 计算页面在绝对空间中的顶部 Y 坐标
            page_top_abs: float = (
                self._accum_heights[page_num] - self._page_heights[page_num]
            )

            # 绝对空间 → 窗口空间 (中心模型)
            # offset_x 已设为 page_width/2，使页面左边缘对齐视口左边缘：
            # win_x = (0 - pw/2) * zoom + vw/2 = (vw - pw*zoom)/2
            # zoom-in 时 win_x 为负（页面左边缘在视口左侧），zoom-out 时为正（居中）。
            win_x: float = (
                (0.0 - self._view.offset_x) * zoom + self._view.view_width / 2
            )
            win_y: float = (
                (page_top_abs - self._view.offset_y) * zoom + self._view.view_height / 2
            )

            log_w: float = pw * zoom
            log_h: float = ph * zoom

            # 从 LRU 缓存中查找渲染结果
            response = self._renderer.find_cached(page_num, zoom)
            if response is not None and response.image is not None:
                # 卡片式页面：用 6px 内边距的白色底色 + 1px G4 色边框，
                # 使页面即使在 fit-to-width 模式下也有可见的卡片分隔。
                card_margin: float = 6.0
                card_x: float = win_x + card_margin
                card_y: float = win_y + card_margin
                card_w: float = log_w - 2 * card_margin
                card_h: float = log_h - 2 * card_margin

                # 卡片白色背景（填满边框内部）
                painter.setPen(Qt.NoPen)
                painter.setBrush(Qt.white)
                painter.drawRect(QRectF(card_x, card_y, card_w, card_h))

                # 页面图像
                painter.drawImage(
                    QRectF(card_x, card_y, card_w, card_h),
                    response.image,
                    QRectF(0, 0, response.image.width(), response.image.height()),
                )

                # 卡片外边框 (G4 色，1.5px 粗)
                painter.setPen(QPen(QColor(tm.text.name()), 1.5))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(QRectF(card_x, card_y, card_w, card_h))
            else:
                # 页面尚未渲染完成：显示 "渲染中..." 占位
                painter.setPen(QColor(180, 180, 180))
                font = painter.font()
                font.setPointSize(10)
                painter.setFont(font)
                painter.drawText(
                    QRectF(win_x, win_y, log_w, log_h),
                    Qt.AlignCenter,
                    "渲染中...",
                )

        # 4. 绘制选区高亮 (sioyek render_text_highlights)
        # 选区在非选中区域点击时隐藏，但剪贴板文字保留；拖拽新选区时重新显示。
        if not self._selection_hidden and self._view is not None:
            # 选区内存在绝对文档空间缓存中，每次绘制前刷新为窗口坐标
            if self._view._cached_sel_words:
                self._view._refresh_selection_rects()
            painter.setPen(Qt.NoPen)
            selection_color = QColor(0, 120, 215, 60)  # 蓝色半透明
            for rect in self._view.selected_character_rects:
                painter.fillRect(rect, selection_color)

        painter.end()

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        """Handle mouse-press for selection and drag-scroll.

        Ported from sioyek's ``PdfViewOpenGLWidget::mousePressEvent()``:
        - Left button   → begin text selection.
        - Middle button → begin drag-scroll.
        """
        if self._view is None:
            super().mousePressEvent(event)
            return

        pos = event.position()
        if event.button() == Qt.LeftButton:
            # 左键：记录起点，但不清除已有选择文本（点击非选区时只是隐藏高亮，不丢失剪贴板）
            self._selecting = True
            self._mouse_dragged = False
            self._sel_begin_abs = self._view.window_to_absolute_document_pos(
                pos.x(), pos.y()
            )
            self._sel_end_abs = self._sel_begin_abs
        elif event.button() == Qt.MiddleButton:
            # 中键：拖拽滚动
            self._dragging = True
            self._drag_start = pos
            self.setCursor(Qt.ClosedHandCursor)
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        """Handle mouse-move for selection updates and drag-scroll.

        Ported from sioyek's ``PdfViewOpenGLWidget::mouseMoveEvent()``:
        - Selecting → update selection end, query text, queue repaint.
        - Dragging  → move the document offset, queue repaint.
        """
        if self._view is None:
            super().mouseMoveEvent(event)
            return

        pos = event.position()

        if self._selecting:
            self._mouse_dragged = True
            # 更新选区终点
            self._sel_end_abs = self._view.window_to_absolute_document_pos(
                pos.x(), pos.y()
            )
            # 首次实质拖拽时清除旧选区，开始新选择
            if self._selection_hidden or not self._selected_text:
                self._selection_hidden = False
                self._view.clear_selection()
            # 执行文本选区查询（同时填充 selected_character_rects）
            self._selected_text = self._view.get_text_selection(
                self._sel_begin_abs[0],
                self._sel_begin_abs[1],
                self._sel_end_abs[0],
                self._sel_end_abs[1],
            )
            self.update()
        elif self._dragging:
            # 中键拖拽：驱动对应方向的滚动条，由滚动条信号更新 offset
            delta = pos - self._drag_start
            from PySide6.QtWidgets import QScrollBar
            parent = self.parentWidget()
            if parent is not None:
                vbar = parent.findChild(QScrollBar)
                if vbar is not None and vbar.maximum() > vbar.minimum():
                    vbar.setValue(vbar.value() - int(delta.y()))
            # 横向滚动条可能不存在（页面窄于视口时 range=0）
            hbar = None
            if parent is not None:
                for ch in parent.children():
                    if isinstance(ch, QScrollBar) and ch.orientation() == Qt.Horizontal and ch.maximum() > ch.minimum():
                        hbar = ch
                        break
            if hbar is not None:
                hbar.setValue(hbar.value() - int(delta.x()))
            self._drag_start = pos
            self._submit_render_for_visible_pages()
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        """Handle mouse-release — copy selected text on left release.

        Ported from sioyek's ``PdfViewOpenGLWidget::mouseReleaseEvent()``:
        - Left button   → end selection, copy text to clipboard.
        - Middle button → end drag-scroll, restore cursor.
        """
        if event.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            if self._mouse_dragged:
                # 拖拽选择完成：复制文字到剪贴板，保持高亮可见
                if self._selected_text:
                    QApplication.clipboard().setText(self._selected_text)
                self._selection_hidden = False
            else:
                # 单纯点击（无拖拽）：隐藏高亮，但剪贴板文字保留
                if self._view is not None and self._view._cached_sel_words:
                    self._selection_hidden = True
                    self.update()
        elif event.button() == Qt.MiddleButton and self._dragging:
            self._dragging = False
            self.unsetCursor()

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        """双击中键 → 重置缩放到自适应大小。"""
        if event.button() == Qt.MiddleButton:
            self.fit_to_page()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: Any) -> None:  # noqa: N802
        """Handle mouse-wheel for zoom and scroll.

        Ported from sioyek's ``PdfViewOpenGLWidget::wheelEvent()``:
        - ``Ctrl + Wheel`` → zoom in / out.
        - Plain wheel      → scroll vertically in document space.
        """
        if self._view is None:
            super().wheelEvent(event)
            return

        # Ctrl+滚轮：缩放
        if event.modifiers() == Qt.ControlModifier or self._ctrl_pressed:
            factor: float = 1.1 if event.angleDelta().y() > 0 else 0.9
            if factor > 1:
                self._view.zoom_in(factor)
            else:
                self._view.zoom_out(1.0 / factor)
            self._clamp_offset(self._view.zoom_level)
            self._submit_render_for_visible_pages()
            self.zoom_changed.emit(self._view.zoom_level)
            self.update()
            event.accept()
            return

        # 普通滚轮由 _WheelSmoothScrollFilter 处理（StyledScrollArea 完全一致的行为）
        super().wheelEvent(event)

    def contextMenuEvent(self, event: Any) -> None:  # noqa: N802
        """Build the right-click context menu.

        Menu actions (to be extended in Task 6):
        - 复制选中文字  (if text is selected)
        - 复制图片      (if click falls inside an image block)
        - 全选
        """
        if self._view is None:
            super().contextMenuEvent(event)
            return

        menu = StyledContextMenu(parent=self)

        # 文字选区操作
        if self._view.selected_character_rects:
            menu.add_item("复制选中文字", callback=self._copy_selected_text)

        # 图片检测：右键点击位置是否落在图片块上
        abs_pos: Tuple[float, float] = self._view.window_to_absolute_document_pos(
            event.x(), event.y()
        )
        img_info: Optional[Dict[str, Any]] = self._find_image_at(abs_pos)
        if img_info is not None:
            menu.add_item(
                "复制图片",
                callback=lambda checked, info=img_info: self._copy_image(info),
            )

        menu.add_separator()
        menu.add_item("全选", callback=self._select_all)

        if menu.actions():
            menu.exec(event.globalPos())
        else:
            super().contextMenuEvent(event)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        """Update the viewport dimensions on widget resize.

        Keeping ``PdfDocumentView.view_width``/``view_height`` in sync
        ensures coordinate transforms remain correct.
        Also triggers a deferred ``fit_to_page`` when the widget was
        hidden (size 0) at document-load time — common when the widget
        sits inside a ``QStackedLayout``.
        """
        super().resizeEvent(event)
        if self._view is not None:
            self._view.view_width = self.width()
            self._view.view_height = self.height()
            if self._resize_need_fit and self.width() > 100 and self.height() > 50:
                self._resize_need_fit = False
                self.fit_to_page()
            else:
                self._submit_render_for_visible_pages()
            self.update()

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        """Track Ctrl key state."""
        if event.key() == Qt.Key_Control:
            self._ctrl_pressed = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: Any) -> None:  # noqa: N802
        """Track Ctrl key state."""
        if event.key() == Qt.Key_Control:
            self._ctrl_pressed = False
        super().keyReleaseEvent(event)

    # ── Internal helpers ─────────────────────────────────────────────

    def _on_page_rendered(self, page: int, request_id: int) -> None:
        """Slot connected to ``PdfBackgroundRenderer.render_ready``.

        Simply triggers a repaint; the ``paintEvent`` will pick up the
        newly cached image from the renderer's LRU cache.
        """
        self.update()

    def _submit_render_for_visible_pages(self) -> None:
        """Submit background render requests for all visible pages.

        Skips pages that are already cached at the current zoom level.
        The renderer handles deduplication internally (cancels stale
        requests for the same ``(path, page)``).

        Render resolution follows sioyek's approach:
        ``display_scale = logical_dpi / 72.0`` — ensures crisp text on
        standard-DPI screens (not just HiDPI).
        """
        if self._doc is None or self._view is None or self._file_path is None:
            return
        visible: List[int] = self._view.get_visible_pages()
        zoom: float = self._view.zoom_level
        # sioyek: DISPLAY_RESOLUTION_SCALE = logical_dpi / 72
        logical_dpi: float = self.logicalDpiX() if self.logicalDpiX() > 0 else 96
        display_scale: float = logical_dpi / 72.0
        dpr: float = self.devicePixelRatio() * display_scale
        for page_num in visible:
            cached = self._renderer.find_cached(page_num, zoom)
            if cached is None:
                self._renderer.submit(self._file_path, page_num, zoom, dpr)

    def _find_image_at(
        self, abs_pos: Tuple[float, float]
    ) -> Optional[Dict[str, Any]]:
        """Find an image block at the given absolute-document position.

        Parameters
        ----------
        abs_pos : tuple[float, float]
            ``(abs_x, abs_y)`` in absolute document space (PDF points).

        Returns
        -------
        dict | None
            The image info dict from ``PdfDocument.get_page_images()``
            if the click point is inside an image bounding box, or
            ``None`` otherwise.
        """
        if self._doc is None or self._view is None:
            return None
        abs_x, abs_y = abs_pos
        page, y_in_page = self._view.absolute_to_page(abs_y)
        images: List[Dict[str, Any]] = self._doc.get_page_images(page)
        for img in images:
            bbox = img["bbox"]  # (x0, y0, x1, y1) in page coordinates
            if bbox[0] <= abs_x <= bbox[2] and bbox[1] <= y_in_page <= bbox[3]:
                return img
        return None

    def _copy_selected_text(self) -> None:
        """Copy the currently selected text to the system clipboard."""
        if self._selected_text:
            QApplication.clipboard().setText(self._selected_text)

    def _copy_image(self, img_info: Dict[str, Any]) -> None:
        """Copy an embedded image to the system clipboard as a pixmap.

        Parameters
        ----------
        img_info : dict
            Image info dict as returned by
            ``PdfDocument.get_page_images()``.  Must contain an
            ``"image"`` key with raw image bytes.
        """
        img_bytes: bytes = img_info.get("image", b"")
        if not img_bytes:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(img_bytes):
            QApplication.clipboard().setPixmap(pixmap)

    def _select_all(self) -> None:
        """Select all text on the current page.

        Uses the full page bounding box as the selection rectangle in
        absolute document space.
        """
        if self._doc is None or self._view is None:
            return
        page: int = self.current_page()
        page_top_abs: float = (
            self._accum_heights[page] - self._page_heights[page]
        )
        pw: float = self._page_widths[page]
        ph: float = self._page_heights[page]

        # 全选：选区覆盖整个页面
        self._selected_text = self._view.get_text_selection(
            0.0,
            page_top_abs,
            pw,
            page_top_abs + ph,
        )
        if self._selected_text:
            QApplication.clipboard().setText(self._selected_text)
        self.update()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        """Clean up resources on widget close."""
        self._renderer.cancel_all()
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._view = None
        super().closeEvent(event)
