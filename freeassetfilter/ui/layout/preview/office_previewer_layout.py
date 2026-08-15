"""
Office 预览器布局 — 统一预览 6 种 Office 格式（doc/docx/xls/xlsx/ppt/pptx）

通过 ``OfficeConverterWorker``（T9）在后台线程执行转换，并按信号负载路由到
对应视图：

- PDF 负载（纯路径字符串）→ 懒内嵌 ``PdfPreviewerLayout`` 渲染；
- XLSX 双视图：顶栏标签切换「PDF / 表格」，表格为只读 ``QTableWidget``，
  单元格禁编辑；>5000 行 / >200 列时按约定截断并显示「已截断」提示（T7）；
- 降级视图：HTML（``QTextBrowser.setHtml``）、大纲（纯文本）、错误提示。

同实例重分派（Metis B5）：6 个后缀映射到同一个类，docx→xlsx 点击复用同一实例。
每次 ``set_file`` 取消+等待在途 worker、清空旧视图，并用 generation counter
守卫过期异步结果（迟到的 ``converted``/``failed`` 一律丢弃）。

``cleanup()`` 契约（Metis B4）：(a) cancel+wait 在途 worker，(b) 调用内嵌
``pdf.cleanup()``（退出全屏，避免 dangling pointer），(c) 然后才允许 deleteLater。
镜像 ``video_player_layout.cleanup()``（仓库金标准），且可安全调用两次。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

# 独立运行时的 sys.path 引导（在模块级导入前执行）
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent.parent)  # freeassetfilter/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)
_project_root = str(_this_file.parent.parent.parent.parent.parent)  # 项目根
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QLabel,
    QStackedLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from theme import tm
from freeassetfilter.services.office_converter_worker import OfficeConverterWorker


class _XlsxTableView(QTabWidget):
    """XLSX 双视图面板：顶栏标签「PDF / 表格」切换 + 只读表格。

    - 标签 0 = PDF 页（懒内嵌 ``PdfPreviewerLayout``）；
    - 标签 1 = 表格页（只读 ``QTableWidget`` + 截断提示标签）。

    表格内容遵循 T7 TSV 约定：行以 ``\\n`` 分隔、单元格以 ``\\t`` 分隔；
    行 / 列上限分别 ``_XLSX_MAX_ROWS``（5000）与 ``_XLSX_MAX_COLS``（200），
    命中上限时显示「已截断」提示。
    """

    _XLSX_MAX_ROWS: int = 5000
    _XLSX_MAX_COLS: int = 200

    def __init__(self, parent: Optional[QWidget] = None, settings_manager: Optional[Any] = None) -> None:
        """初始化双视图标签页。

        Parameters
        ----------
        parent : Optional[QWidget]
            父控件（可选）。
        settings_manager : Optional[Any]
            注入的设置管理器；``None`` 时懒解析（Metis B9）。
        """
        super().__init__(parent)
        self._settings_manager: Optional[Any] = settings_manager
        self._pdf: Optional[Any] = None
        self._pdf_tab_layout: Optional[QVBoxLayout] = None

        # ── 标签 0：PDF 页（懒内嵌 PdfPreviewerLayout）──
        self._pdf_tab = QWidget()
        self._pdf_tab_layout = QVBoxLayout(self._pdf_tab)
        self._pdf_tab_layout.setContentsMargins(0, 0, 0, 0)
        self._pdf_tab_layout.setSpacing(0)
        self.addTab(self._pdf_tab, "PDF")

        # ── 标签 1：表格页（只读表格 + 截断提示）──
        self._table_tab = QWidget()
        table_layout = QVBoxLayout(self._table_tab)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)

        self._truncated_label = QLabel("")
        self._truncated_label.setVisible(False)
        self._truncated_label.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 12px; background: transparent; padding: 4px;"
        )
        table_layout.addWidget(self._truncated_label)

        self._table_widget = QTableWidget()
        self._table_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table_widget.setAlternatingRowColors(True)
        table_layout.addWidget(self._table_widget)

        self.addTab(self._table_tab, "表格")

    # ── 公共 API ─────────────────────────────────────────────────────────

    def populate(self, rows: list[list[str]], truncated: bool) -> None:
        """用解析后的行数据填充只读表格，并按需显示截断提示。

        Parameters
        ----------
        rows : list[list[str]]
            行数据（每行是单元格字符串列表）。
        truncated : bool
            是否因行 / 列上限被截断。
        """
        self._table_widget.clear()
        max_cols = max((len(row) for row in rows), default=0)
        self._table_widget.setRowCount(len(rows))
        self._table_widget.setColumnCount(max_cols)
        for row_idx, cells in enumerate(rows):
            for col_idx, value in enumerate(cells):
                item = QTableWidgetItem(value)
                # 只读：禁止编辑（配合 NoEditTriggers 双重保障）
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table_widget.setItem(row_idx, col_idx, item)
        if truncated:
            self._truncated_label.setText(
                f"已截断：仅显示前 {self._XLSX_MAX_ROWS} 行 / "
                f"前 {self._XLSX_MAX_COLS} 列"
            )
            self._truncated_label.setVisible(True)
        else:
            self._truncated_label.clear()
            self._truncated_label.setVisible(False)
        self._switch_to_table()

    def set_pdf_file(self, path: str) -> None:
        """懒内嵌 ``PdfPreviewerLayout`` 并加载 *path*，切换到 PDF 标签。

        Parameters
        ----------
        path : str
            转换产物 PDF 文件路径。
        """
        if self._pdf is None:
            if self._settings_manager is None:
                from freeassetfilter.core.managers.settings_manager import SettingsManager
                self._settings_manager = SettingsManager()
            from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
            self._pdf = PdfPreviewerLayout(self._pdf_tab, settings_manager=self._settings_manager)
            self._pdf_tab_layout.addWidget(self._pdf)  # type: ignore[union-attr]
        self._pdf.set_file(path)
        self.setCurrentIndex(0)

    def reset(self) -> None:
        """清空表格与截断提示，回到 PDF 标签（同实例重分派时调用）。"""
        self._table_widget.clear()
        self._table_widget.setRowCount(0)
        self._table_widget.setColumnCount(0)
        self._truncated_label.clear()
        self._truncated_label.setVisible(False)
        self.setCurrentIndex(0)

    def _switch_to_table(self) -> None:
        """切换到「表格」标签（对外暴露供测试 / 交互复用）。"""
        self.setCurrentIndex(1)


class OfficePreviewerLayout(QWidget):
    """Office 统一预览器布局。

    无独立顶栏；内容区使用 ``QStackedLayout`` 切换 PDF / HTML / 大纲 /
    XLSX 表格 / 错误 / 覆盖层视图，PDF 视图懒内嵌 ``PdfPreviewerLayout``
    并由其自带顶栏（页码/缩放/最大化/AI/索引）接管顶部。

    宿主以 ``OfficePreviewerLayout(parent)`` 单参数构造（``unified_previewer_layout.py:329``）；
    ``set_file(file_info: dict)`` 是宿主调用的唯一入口。

    Signals:
        close_requested: 关闭预览请求信号
    """

    close_requested = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        dpi_scale: Optional[float] = None,
        global_font: Optional[Any] = None,
        settings_manager: Optional[Any] = None,
    ) -> None:
        """初始化布局与视图栈。

        Parameters
        ----------
        parent : Optional[QWidget]
            父控件（可选）。
        dpi_scale : Optional[float]
            DPI 缩放系数（透传给内嵌 PdfPreviewerLayout）。
        global_font : Optional[Any]
            全局字体（透传给内嵌 PdfPreviewerLayout）。
        settings_manager : Optional[Any]
            注入的设置管理器；``None`` 时仅在需要时懒解析（Metis B9）。
        """
        super().__init__(parent)
        self._dpi_scale: Optional[float] = dpi_scale
        self._global_font: Optional[Any] = global_font
        # 不立即解析：仅在懒内嵌 PdfPreviewerLayout 时才需要（镜像 hover_tooltip）。
        self._settings_manager: Optional[Any] = settings_manager

        self._generation: int = 0
        self._current_worker: Optional[OfficeConverterWorker] = None
        self._current_suffix: str = ""
        self._cleaned_up: bool = False
        self._pdf: Optional[Any] = None
        self._pdf_holder_layout: Optional[QVBoxLayout] = None

        self._init_ui()

    # ── UI 初始化 ─────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        """构建内容视图栈（无独立顶栏，PDF 视图由内嵌 PdfPreviewerLayout 自带顶栏接管）。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("OfficePreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)

        # index 0：覆盖层（加载中占位）
        self._overlay = QWidget()
        self._overlay.setObjectName("OfficePreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        self._placeholder = QLabel("正在转换 Office 文档…")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        )
        overlay_layout.addWidget(self._placeholder)
        self._content_stack.addWidget(self._overlay)

        # index 1：HTML 降级视图
        self._html_view = QTextBrowser()
        self._html_view.setObjectName("OfficePreviewerHtmlView")
        self._html_view.setOpenExternalLinks(False)
        self._html_view.setOpenLinks(False)
        self._content_stack.addWidget(self._html_view)

        # index 2：大纲降级视图（纯文本）
        self._outline_view = QTextBrowser()
        self._outline_view.setObjectName("OfficePreviewerOutlineView")
        self._content_stack.addWidget(self._outline_view)

        # index 3：XLSX 双视图（PDF / 表格）
        self._table_view = _XlsxTableView(
            self._content_area, settings_manager=self._settings_manager
        )
        self._content_stack.addWidget(self._table_view)

        # index 4：错误视图
        self._error_view = QLabel("")
        self._error_view.setObjectName("OfficePreviewerErrorView")
        self._error_view.setAlignment(Qt.AlignCenter)
        self._error_view.setWordWrap(True)
        self._error_view.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 13px; background: transparent; padding: 24px;"
        )
        self._content_stack.addWidget(self._error_view)

        # index 5：PDF 视图（懒内嵌 PdfPreviewerLayout）
        self._pdf_holder = QWidget()
        self._pdf_holder_layout = QVBoxLayout(self._pdf_holder)
        self._pdf_holder_layout.setContentsMargins(0, 0, 0, 0)
        self._pdf_holder_layout.setSpacing(0)
        self._content_stack.addWidget(self._pdf_holder)

        self._content_stack.setCurrentWidget(self._overlay)
        layout.addWidget(self._content_area, stretch=1)

    # ── 宿主入口 ───────────────────────────────────────────────────────────

    def set_file(self, file_info: dict | str) -> None:
        """为指定 Office 文件启动后台转换并准备预览视图。

        宿主 ``unified_previewer_layout._load_preview`` 对非音频分支以
        ``set_file(file_path)`` 调用（file_path 为纯路径字符串，
        ``unified_previewer_layout.py:312/:363``）；本方法对 dict / str
        双容归一化（镜像 ``components/pdf_previewer.py:412``）：str 形态以
        路径推导 suffix 转为符合 worker 契约的 dict。其它类型（None）走
        安全路径：suffix 为空、worker 收空 dict——不给宿主留下再抛异常
        的机会（宿主仅捕获 RuntimeError/AttributeError/TypeError）。

        同实例重分派（Metis B5）：先取消+等待在途 worker、清空旧视图，再用
        generation counter 守卫本轮的异步结果；上一轮迟到的信号一律丢弃。

        Parameters
        ----------
        file_info : dict | str
            ``{"path": str, "suffix": str}`` 字典，或纯文件路径字符串
            （suffix 由路径扩展名推导，小写）。
        """
        if isinstance(file_info, dict):
            normalized: dict = dict(file_info or {})
        elif isinstance(file_info, str):
            path = str(file_info)
            normalized = {
                "path": path,
                "suffix": str(Path(path).suffix.lstrip(".")).lower(),
            }
        else:
            normalized = {}

        self._generation += 1
        gen = self._generation
        self._cancel_worker()
        self._reset_views()

        suffix = str(normalized.get("suffix", "") or "").lower().lstrip(".")
        self._current_suffix = suffix

        worker = OfficeConverterWorker(dict(normalized or {}))
        worker.converted.connect(
            lambda payload, g=gen: self._on_converted(payload, g)
        )
        worker.failed.connect(
            lambda message, g=gen: self._on_failed(message, g)
        )
        self._current_worker = worker
        worker.start()

    def cleanup(self) -> None:
        """清理资源（Metis B4）：cancel+wait 在途 worker → 内嵌 pdf.cleanup()。

        可安全调用两次：首次后置 ``_cleaned_up``，二次直接返回。镜像
        ``video_player_layout.cleanup()`` 金标准——先停工作线程再回收内嵌
        全屏组件，避免 dangling pointer 与「信号发射到已销毁对象」。
        """
        if self._cleaned_up:
            return
        self._cleaned_up = True
        # 使在途 worker 的信号全部过期（即使它们仍被排队投递）
        self._generation += 1
        self._cancel_worker()
        # 退出内嵌 PdfPreviewerLayout 的全屏状态，避免 dangling pointer
        if self._pdf is not None:
            try:
                self._pdf.cleanup()
            except (RuntimeError, TypeError):
                pass
        if self._table_view._pdf is not None:
            try:
                self._table_view._pdf.cleanup()
            except (RuntimeError, TypeError):
                pass

    # ── 内部：worker 生命周期 ───────────────────────────────────────────────

    def _cancel_worker(self) -> None:
        """取消并回收在途 worker（cancel + wait + deleteLater）。

        使用 worker 自带的 ``cleanup()``（内部完成 ``request_cancel()`` +
        ``wait()`` + ``deleteLater()``），确保信号不会发射到已销毁对象。
        """
        worker = self._current_worker
        self._current_worker = None
        if worker is not None:
            try:
                worker.cleanup()
            except (RuntimeError, TypeError):
                pass

    def _reset_views(self) -> None:
        """清空旧视图内容，回到覆盖层（同实例重分派时调用）。"""
        self._html_view.clear()
        self._outline_view.clear()
        self._error_view.clear()
        self._table_view.reset()
        self._content_stack.setCurrentWidget(self._overlay)

    # ── 内部：信号路由 ─────────────────────────────────────────────────────

    def _on_converted(self, payload: str, gen: int) -> None:
        """``converted`` 负载路由：PDF 路径 / html / outline / table。

        Parameters
        ----------
        payload : str
            PDF 路径字符串，或 ``"{content_type}:{content}"`` 标记。
        gen : int
            信号发射时捕获的 generation；与当前不符即过期，直接丢弃。
        """
        if gen != self._generation:
            return
        if payload.startswith("html:"):
            self._show_html(payload[len("html:") :])
        elif payload.startswith("outline:"):
            self._show_outline(payload[len("outline:") :])
        elif payload.startswith("table:"):
            self._show_table(payload[len("table:") :])
        else:
            self._route_pdf(payload)

    def _on_failed(self, message: str, gen: int) -> None:
        """``failed`` 路由：显示错误视图。

        Parameters
        ----------
        message : str
            错误 / 取消 / 超时提示文案。
        gen : int
            信号发射时捕获的 generation；与当前不符即过期，直接丢弃。
        """
        if gen != self._generation:
            return
        self._show_error(message)

    # ── 内部：视图切换 ─────────────────────────────────────────────────────

    def _show_html(self, content: str) -> None:
        """显示 HTML 降级视图。"""
        self._html_view.setHtml(content)
        self._content_stack.setCurrentWidget(self._html_view)

    def _show_outline(self, content: str) -> None:
        """显示大纲（纯文本）降级视图。"""
        self._outline_view.setPlainText(content)
        self._content_stack.setCurrentWidget(self._outline_view)

    def _show_error(self, message: str) -> None:
        """显示错误提示视图。"""
        self._error_view.setText(message)
        self._content_stack.setCurrentWidget(self._error_view)

    def _show_table(self, content: str) -> None:
        """解析 TSV 并按约定截断后填充 XLSX 表格视图。"""
        rows, truncated = self._parse_table(content)
        self._table_view.populate(rows, truncated)
        self._content_stack.setCurrentWidget(self._table_view)

    def _route_pdf(self, path: str) -> None:
        """PDF 负载路由：xlsx 进双视图的 PDF 标签，其余进独立 PDF 视图。

        Parameters
        ----------
        path : str
            转换产物 PDF 文件路径。
        """
        if self._current_suffix == "xlsx":
            self._table_view.set_pdf_file(path)
            self._content_stack.setCurrentWidget(self._table_view)
        else:
            pdf = self._ensure_pdf()
            pdf.set_file(path)
            self._content_stack.setCurrentWidget(self._pdf_holder)

    def _ensure_pdf(self) -> Any:
        """懒创建非 xlsx 场景的 ``PdfPreviewerLayout`` 实例。

        Returns
        -------
        Any
            内嵌的 PdfPreviewerLayout（首次调用时创建）。
        """
        if self._pdf is None:
            if self._settings_manager is None:
                from freeassetfilter.core.managers.settings_manager import SettingsManager
                self._settings_manager = SettingsManager()
            from freeassetfilter.ui.layout.preview.pdf_previewer_layout import PdfPreviewerLayout
            self._pdf = PdfPreviewerLayout(
                self._pdf_holder,
                dpi_scale=self._dpi_scale,
                global_font=self._global_font,
                settings_manager=self._settings_manager,
            )
            self._pdf_holder_layout.addWidget(self._pdf)  # type: ignore[union-attr]
        return self._pdf

    @staticmethod
    def _parse_table(content: str) -> tuple[list[list[str]], bool]:
        """把 TSV 内容按 T7 约定解析为行数据，并检测是否命中上限。

        Parameters
        ----------
        content : str
            TSV 字符串（行 ``\\n``、单元格 ``\\t``）。

        Returns
        -------
        tuple[list[list[str]], bool]
            ``(rows, truncated)``——解析后的行数据与是否被截断。
        """
        lines = content.split("\n")
        truncated = len(lines) >= _XlsxTableView._XLSX_MAX_ROWS
        rows: list[list[str]] = []
        for line in lines[:_XlsxTableView._XLSX_MAX_ROWS]:
            cells = line.split("\t")[:_XlsxTableView._XLSX_MAX_COLS]
            if len(cells) >= _XlsxTableView._XLSX_MAX_COLS:
                truncated = True
            rows.append(cells)
        return rows, truncated


__all__ = [
    "OfficePreviewerLayout",
]
