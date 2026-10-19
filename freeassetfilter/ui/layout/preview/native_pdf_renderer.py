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

from PySide6.QtCore import Qt, QRectF, QPointF, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QWidget,
)

from freeassetfilter.services.pdf_document import PdfDocument
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.ui.components.styled_dialog import ask_custom_dialog
from freeassetfilter.services.pdf_document_view import PdfDocumentView
from freeassetfilter.services.pdf_renderer import PdfBackgroundRenderer
from freeassetfilter.ui.theme import tm
from freeassetfilter.utils.app_logger import warning


# ── 异步文档打开任务（fitz.open + 页尺寸缓存移出 UI 线程）──────────────

class _PdfOpenSignals(QObject):
    """PDF 异步打开完成信号中转（任务持有，跨线程队列投递到 UI 线程）。"""

    opened = Signal(int, object, str, list, list, list)
    # (token, PdfDocument, file_path, page_widths, page_heights, accum_heights)
    failed = Signal(int, str)  # (token, error_message)


class _PdfOpenTask(QRunnable):
    """后台打开 PDF 并读取全部页尺寸的池任务。

    PyMuPDF 的 ``fitz.open`` 与逐页 ``page.rect`` 在超大 PDF 上可能耗时
    秒级；本任务把这段工作移出 UI 线程。``PdfDocument`` 自身带
    ``threading.Lock``，渲染任务仍按既有模式各自打开独立文档。
    """

    def __init__(self, file_path: str, token: int) -> None:
        """初始化任务。

        Args:
            file_path: PDF 文件路径。
            token: 加载令牌（布局/渲染器据此丢弃陈旧结果）。
        """
        super().__init__()
        self.setAutoDelete(True)
        self._file_path = file_path
        self._token = token
        self._signals = _PdfOpenSignals()

    @property
    def opened(self):
        """打开成功信号 ``(token, doc, path, widths, heights, accums)``。"""
        return self._signals.opened

    @property
    def failed(self):
        """打开失败信号 ``(token, message)``。"""
        return self._signals.failed

    def start(self) -> None:
        """投递到全局线程池执行。"""
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        """打开文档并读取页尺寸；异常统一经 ``failed`` 上报。"""
        doc: Optional[PdfDocument] = None
        try:
            doc = PdfDocument(self._file_path)
            widths = list(doc.page_widths)
            heights = list(doc.page_heights)
            accums = list(doc.accum_page_heights)
            self._signals.opened.emit(
                self._token, doc, self._file_path, widths, heights, accums
            )
        except Exception as exc:  # noqa: BLE001  # 打开边界：统一失败上报
            if doc is not None:
                try:
                    doc.close()
                except Exception:  # noqa: BLE001
                    pass
            self._signals.failed.emit(self._token, str(exc))


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
    #: 异步/同步加载完成（success, error_message）
    document_load_finished = Signal(bool, str)
    #: 某页后台渲染完成（0-based page number）
    page_rendered = Signal(int)

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
            else 1.0
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

        # 异步打开状态：令牌递增使旧任务结果失效；在途任务强引用防 GC。
        self._load_token: int = 0
        self._load_task: Optional[_PdfOpenTask] = None

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

        # 右侧被宿主布局预留的滚动条列宽度（px）：内容画布以「视口 + 该列」
        # 的整体水平中心为基准居中，使页面左右边距对称。默认为 0（经典中心）。
        self._right_reserved_px: float = 0.0

        # 点击非选区时隐藏高亮但保留剪贴板文字
        self._selection_hidden: bool = False
        # 追踪鼠标是否在 press 后有实质移动（区分"点击"与"拖拽"）
        self._mouse_dragged: bool = False

        # 中键拖拽滚动
        self._dragging: bool = False
        self._drag_start: QPointF = QPointF()

        # 需要重新 fit（首次真实 resize 时触发，解决 QStackedLayout 中隐藏时的尺寸 0 问题）
        self._resize_need_fit: bool = False
        # P0 节流：渲染提交合并序号，拖拽每帧提交改为 32ms 合并一次。
        self._render_seq: int = 0



        # Ctrl 键追踪
        self._ctrl_pressed: bool = False

        # 滚轮由 _WheelSmoothScrollFilter 处理（安装在 layout 中）

    def _clamp_offset(self, zoom: float) -> None:
        """限制 offset_x/offset_y：页面超出视口时允许 ±30px 摆动，否则居中。"""
        margin_abs = 30.0 / max(zoom, 0.01)
        if self._page_widths and self._view is not None:
            pw = self._page_widths[0]
            # 水平以「视口 + 右侧预留滚动条列」的整体画布中心为基准，
            # 保证缩放/拖动时左右边距相对预览器保持对称。
            half_vw = self._view.frame_center_x() / zoom
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

    def _close_current_document(self) -> None:
        """取消后台渲染并关闭当前文档（不改变加载令牌）。"""
        self._renderer.cancel_all()
        if self._doc is not None:
            try:
                self._doc.close()
            except Exception as exc:  # noqa: BLE001
                warning(f"关闭 PDF 文档失败：{exc}")
            finally:
                self._doc = None
        self._view = None
        self._file_path = None
        self._page_widths = []
        self._page_heights = []
        self._accum_heights = []

    def _install_document(
        self,
        doc: PdfDocument,
        file_path: str,
        page_widths: List[float],
        page_heights: List[float],
        accum_heights: List[float],
    ) -> None:
        """把已打开的文档安装到视图并提交首屏渲染（UI 线程）。

        Args:
            doc: 已打开的 PDF 文档（后台任务创建，带内部锁）。
            file_path: 文档路径。
            page_widths: 全部页宽（pt）。
            page_heights: 全部页高（pt）。
            accum_heights: 页高累计和。
        """
        self._doc = doc
        self._file_path = file_path

        # Cache page dimensions locally for fast paintEvent access.
        self._page_widths = list(page_widths)
        self._page_heights = list(page_heights)
        self._accum_heights = list(accum_heights)

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
            right_reserved_px=self._right_reserved_px,
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

    def load_document(self, file_path: str) -> bool:
        """同步打开 PDF 并完成视图初始化（保留给独立组件/测试）。

        预览器交互路径使用 :meth:`load_document_async`；本方法保留原签名与
        返回值，供 ``test_native_pdf_renderer`` 等同步用例使用。

        Parameters
        ----------
        file_path : str
            Path to the PDF file to open.

        Returns
        -------
        bool
            ``True`` if the document was successfully loaded.
        """
        self._load_token += 1
        self._load_task = None
        self._close_current_document()

        if not os.path.exists(file_path):
            self.document_load_finished.emit(False, f"文件不存在: {file_path}")
            return False

        doc: Optional[PdfDocument] = None
        try:
            doc = PdfDocument(file_path)
            widths = list(doc.page_widths)
            heights = list(doc.page_heights)
            accums = list(doc.accum_page_heights)
        except Exception as exc:  # noqa: BLE001
            if doc is not None:
                try:
                    doc.close()
                except Exception:  # noqa: BLE001
                    pass
            self.document_load_finished.emit(False, str(exc))
            return False

        self._install_document(doc, file_path, widths, heights, accums)
        self.document_load_finished.emit(True, "")
        return True

    def load_document_async(self, file_path: str) -> bool:
        """异步打开 PDF（fitz.open + 页尺寸缓存移出 UI 线程）。

        路径不存在时同步返回 ``False``；其余情况立即返回 ``True``（请求已
        受理），结果经 ``document_load_finished(success, message)`` 通知。

        Args:
            file_path: PDF 文件路径。

        Returns:
            bool: 是否受理打开请求。
        """
        self._load_token += 1
        token = self._load_token
        self._load_task = None
        self._close_current_document()

        if not os.path.exists(file_path):
            return False

        task = _PdfOpenTask(file_path, token)
        task.opened.connect(self._on_document_opened)
        task.failed.connect(self._on_document_open_failed)
        self._load_task = task
        task.start()
        return True

    def _on_document_opened(
        self,
        token: int,
        doc: object,
        file_path: str,
        widths: list,
        heights: list,
        accums: list,
    ) -> None:
        """异步打开成功回调（令牌守卫：陈旧结果关闭文档并丢弃）。"""
        if token != self._load_token or not isinstance(doc, PdfDocument):
            try:
                if isinstance(doc, PdfDocument):
                    doc.close()
            except Exception:  # noqa: BLE001
                pass
            return
        self._load_task = None
        self._install_document(doc, file_path, widths, heights, accums)
        self.document_load_finished.emit(True, "")

    def _on_document_open_failed(self, token: int, message: str) -> None:
        """异步打开失败回调（令牌守卫）。"""
        if token != self._load_token:
            return
        self._load_task = None
        self.document_load_finished.emit(False, message)

    def close_document(self) -> None:
        """取消在途打开/渲染并关闭当前文档（幂等，不阻塞）。"""
        self._load_token += 1
        self._load_task = None
        self._close_current_document()
        self.update()

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

    def set_right_reserved_px(self, px: float) -> None:
        """配置视口右侧被预留的滚动条列宽度（px）。

        内容画布中心 = (视口宽度 + 预留宽度) / 2，页面因此在**整个预览器**
        中水平居中，右边缘不需要扣除滚动条宽度。布局侧应在加载文档前调用
        一次；已加载文档时同步到现有视图。
        """
        self._right_reserved_px = max(0.0, px)
        if self._view is not None:
            self._view.right_reserved_px = self._right_reserved_px

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
        """缩放到自适应宽度，仅影响缩放而保持当前阅读位置。

        中心模型下 ``offset_y`` 为视口中心对应的文档绝对 Y，与缩放无关；
        因此回归默认尺寸时只需重设 zoom 与水平居中，保留原有 offset_y，
        不跳回文档开头。缩放后仍由 ``_clamp_offset`` 保证垂直偏移合法。
        """
        if self._view is None:
            return
        # 记住缩放前视口中心的文档绝对 Y，缩放前后保持一致
        prev_offset_y = self._view.offset_y
        target = self._view.fit_to_page_width(self.width(), self.height())
        self._view.zoom_level = target
        # 重置水平偏移使页面水平居中
        if self._page_widths:
            self._view.offset_x = self._page_widths[0] / 2.0
        # 保持阅读位置，不重置回文档顶部
        self._view.offset_y = prev_offset_y
        self._clamp_offset(target)
        self._submit_render_for_visible_pages()
        self.zoom_changed.emit(target)
        self.update()

    def fit_to_page_bounds(self) -> None:
        """缩放到「适应整页」：当前页宽高同时放入视口，保留阅读位置。

        取「适应页宽」与「高度适配」两种缩放的较小值；行为与
        :meth:`fit_to_page` 一致（保持 offset_y、水平居中、提交渲染）。
        """
        if self._view is None or not self._page_widths:
            return
        page: int = self.current_page()
        pw: float = float(self._page_widths[page])
        ph: float = float(self._page_heights[page])
        w: int = max(self.width(), 1)
        h: int = max(self.height(), 1)
        width_zoom: float = self._view.fit_to_page_width(w, h)
        height_zoom: float = h / max(ph, 1.0)
        target: float = max(0.1, min(width_zoom, height_zoom))
        prev_offset_y = self._view.offset_y
        self._view.set_zoom_level(target)
        self._view.offset_x = pw / 2.0
        self._view.offset_y = prev_offset_y
        self._clamp_offset(self._view.zoom_level)
        self._submit_render_for_visible_pages()
        self.zoom_changed.emit(self._view.zoom_level)
        self.update()

    def zoom_in(self) -> None:
        """放大一级（与 Ctrl+滚轮一致，1.1 倍）。"""
        if self._view is None:
            return
        self._view.zoom_in(1.1)
        self._clamp_offset(self._view.zoom_level)
        self._submit_render_for_visible_pages()
        self.zoom_changed.emit(self._view.zoom_level)
        self.update()

    def zoom_out(self) -> None:
        """缩小一级（与 Ctrl+滚轮一致，1.1 倍）。"""
        if self._view is None:
            return
        self._view.zoom_out(1.1)
        self._clamp_offset(self._view.zoom_level)
        self._submit_render_for_visible_pages()
        self.zoom_changed.emit(self._view.zoom_level)
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
        1. Clears the viewport (transparent canvas; host paints the panel).
        2. Iterates visible pages, drawing each rendered texture.
        3. Overlays selection highlights.
        4. Draws a page-number HUD.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 1. 不自绘背景：与文本预览器一致，画布保持透明，
        #    透出内容区/宿主面板底色（由外层容器负责填充）。
        # 2. 无文档时显示提示文字
        if self._doc is None or self._view is None:
            painter.setPen(QColor(160, 160, 160))
            font = painter.font()
            font.setPointSize(14)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "未加载文档")
            painter.end()
            return

        # 2. 渲染所有可见页面
        zoom: float = self._view.zoom_level
        visible: List[int] = self._view.get_visible_pages()
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
            # offset_x 已设为 page_width/2，使页面在「视口 + 右侧预留滚动条列」
            # 的整体画布中居中（frame_center_x = (view_width + reserved)/2）：
            # win_x = (0 - pw/2) * zoom + frame_center_x
            # zoom-in 时 win_x 为负（页面左边缘在视口左侧），zoom-out 时为正（居中）。
            win_x: float = (
                (0.0 - self._view.offset_x) * zoom + self._view.frame_center_x()
            )
            win_y: float = (
                (page_top_abs - self._view.offset_y) * zoom + self._view.view_height / 2
            )

            log_w: float = pw * zoom
            log_h: float = ph * zoom

            # 从 LRU 缓存中查找渲染结果
            response = self._renderer.find_cached(page_num, zoom)
            if response is not None and response.image is not None:
                # 卡片式页面：用 6px 内边距的白色底色，使页面即使在
                # fit-to-width 模式下也有可见的卡片分隔。
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

                # 卡片外边框：仅深色模式描边（G4 近白细线勾勒白页）；
                # 浅色模式下 G4 为近黑，会在预览区边缘形成黑边，故不描边，
                # 改由白卡底色与浅色画布自然区分。
                if tm.is_dark_theme():
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
        """显示右键菜单（构建逻辑见 :meth:`_build_context_menu`）。"""
        if self._view is None:
            super().contextMenuEvent(event)
            return
        menu = self._build_context_menu(event.pos())
        if menu.actions():
            menu.exec(event.globalPos())
        else:
            super().contextMenuEvent(event)

    def _build_context_menu(self, pos: Any) -> StyledContextMenu:
        """构建右键菜单（与 contextMenuEvent 分离，便于测试断言）。

        菜单结构：
        - 文字/图片操作（按命中情况出现）：复制选中文字、复制图片、图片另存为…
        - 缩放：放大 / 缩小 / 适应页宽 / 适应整页
        - 全选

        Args:
            pos: 控件坐标下的右键位置（``event.pos()``）。

        Returns:
            StyledContextMenu: 已注册动作的菜单对象（调用方决定 exec）。
        """
        menu = StyledContextMenu(parent=self)

        if self._view is not None:
            # 文字选区操作
            if self._view.selected_character_rects:
                menu.add_item("复制选中文字", callback=self._copy_selected_text)

            # 图片检测：右键点击位置是否落在图片块上
            abs_pos: Tuple[float, float] = (
                self._view.window_to_absolute_document_pos(pos.x(), pos.y())
            )
            img_info: Optional[Dict[str, Any]] = self._find_image_at(abs_pos)
            if img_info is not None:
                menu.add_item(
                    "复制图片",
                    callback=lambda checked=False, info=img_info: self._copy_image(info),
                )
                menu.add_item(
                    "图片另存为…",
                    callback=lambda checked=False, info=img_info: self._save_image(info),
                )

        # 缩放组（无文档时也保留入口：调用即空操作，不产生副作用）
        menu.add_separator()
        menu.add_item("放大", callback=self.zoom_in)
        menu.add_item("缩小", callback=self.zoom_out)
        menu.add_item("适应页宽", callback=self.fit_to_page)
        menu.add_item("适应整页", callback=self.fit_to_page_bounds)

        menu.add_separator()
        menu.add_item("全选", callback=self._select_all)
        return menu

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        """Update the viewport dimensions on widget resize.

        Keeping ``PdfDocumentView.view_width``/``view_height`` in sync
        ensures coordinate transforms remain correct.
        Also triggers a deferred ``fit_to_page`` when the widget was
        hidden (size 0) at document-load time — common when the widget
        sits inside a ``QStackedLayout``.
        P0 节流：视图尺寸同步 + ``update()`` 保留（坐标正确性必需，
        开销极低）；渲染提交合并到 32ms 后一次，避免拖拽每帧提交。
        """
        super().resizeEvent(event)
        if self._view is not None:
            self._view.view_width = self.width()
            self._view.view_height = self.height()
            if self._resize_need_fit and self.width() > 100 and self.height() > 50:
                self._resize_need_fit = False
                self.fit_to_page()
            else:
                self._queue_render_for_visible_pages()
            self.update()

    def _queue_render_for_visible_pages(self) -> None:
        """合并请求可见页渲染（P0：32ms 可取消，替代 resize 直调提交）。

        拖拽中每帧 ``_submit_render_for_visible_pages`` 会向后台渲染
        队列压入大量过期任务；合并到静止后一次提交，后台去重压力骤降。
        """
        from PySide6.QtCore import QTimer as _QTimer

        self._render_seq += 1
        seq = self._render_seq
        _QTimer.singleShot(32, lambda: self._flush_queued_render(seq))

    def _flush_queued_render(self, seq: int) -> None:
        """执行合并后的渲染提交；过期序号直接丢弃。"""
        if seq != self._render_seq:
            return
        self._submit_render_for_visible_pages()

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
        newly cached image from the renderer's LRU cache. 同时转发
        ``page_rendered`` 供预览器结束加载遮罩（仅成功缓存的结果；取消/
        失败任务虽也会发 render_ready，但缓存中无图像，不应提前撤遮罩）。
        """
        self.update()
        if self._view is None:
            return
        cached = self._renderer.find_cached(page, self._view.zoom_level)
        if cached is not None and cached.image is not None:
            self.page_rendered.emit(page)

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

    def _save_image(self, img_info: Dict[str, Any]) -> None:
        """将内嵌图片另存为文件（扩展名取自图片元数据）。

        Args:
            img_info: ``PdfDocument.get_page_images()`` 返回的图片信息，
                需含 ``"image"``（原始字节）与可选 ``"ext"``（扩展名提示）。
        """
        img_bytes: bytes = img_info.get("image", b"")
        if not img_bytes:
            return
        ext: str = str(img_info.get("ext", "png")).lower().lstrip(".") or "png"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "保存图片",
            f"pdf_image.{ext}",
            f"{ext.upper()} 图片 (*.{ext});;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(img_bytes)
        except OSError as exc:
            warning(f"保存 PDF 图片失败: {exc}")
            ask_custom_dialog(
                "保存失败",
                f"无法保存图片：{exc}",
                ["知道了"],
                ["primary"],
                dialog_type="danger",
            )

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
        self.close_document()
        super().closeEvent(event)
