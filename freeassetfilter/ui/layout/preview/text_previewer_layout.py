"""
文本预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）

支持：
- Markdown 渲染视图（.md / .markdown）
- 纯文本视图（.txt / .log / .csv / .rst 等）
- 代码语法高亮视图（.py / .json / .xml / .html / .css / .js / .ts / .cpp / .c / .h / .java / .cs / .go / .rs 等）
- 默认回退到纯文本视图

控件使用 StyledButton / QTextEdit / QTextBrowser / QLabel / QPushButton，不使用旧的 D_* 或 Custom* 控件。
"""

import re
import sys
from dataclasses import dataclass, field
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

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QFrame,
    QLabel,
    QApplication,
    QStackedLayout,
    QTextBrowser,
    QTextEdit,
    QFileDialog,
    QPushButton,
    QScroller,
    QListView,
    QAbstractItemView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
)
from PySide6.QtCore import (
    Qt,
    Signal,
    QTimer,
    QPoint,
    QPointF,
    QSize,
    QRect,
    QRectF,
    QEvent,
    QPropertyAnimation,
    QEasingCurve,
    QUrl,
    QAbstractListModel,
    QModelIndex,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QTextCharFormat,
    QTextCursor,
    QSyntaxHighlighter,
    QPainter,
    QPainterPath,
    QPen,
    QHelpEvent,
    QMouseEvent,
    QContextMenuEvent,
    QDesktopServices,
    QTransform,
    QPaintEvent,
)

from theme import tm
from components.styled_button import StyledButton
from components.styled_checkbox import StyledCheckbox
from components.styled_lineedit import StyledLineEdit
from components.styled_slider import StyledSlider
from components.styled_combobox import StyledComboBox
from components.styled_drawer import StyledDrawer
from components.styled_tooltip import (
    StyledTooltip,
    GAP,
    FONT_SIZE,
    PADDING_H,
    PADDING_V,
    BORDER_RADIUS,
)
from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollBar,
    StyledScrollArea,
    _WheelSmoothScrollFilter,
)
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.core._paths import icons_dir
from freeassetfilter.utils.syntax_highlighter import create_highlighter


from freeassetfilter.utils.markdown_renderer import (
    MARKDOWN_AVAILABLE,
    MarkdownRenderer,
)

_MarkdownRenderer = MarkdownRenderer


# ──────────────────────────────────────────────────────────────────────────────
# 文件扩展名常量（重新声明，避免引入旧的 text_previewer.py 及其旧控件）
# ──────────────────────────────────────────────────────────────────────────────

MARKDOWN_EXTENSIONS = {".md", ".markdown"}

ENCODING_LIST = ["UTF-8", "GBK", "GB2312", "BIG5", "LATIN1", "UTF-16", "ASCII"]

CODE_EXTENSIONS = {
    # Python
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    # C/C++
    ".c": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    # Java
    ".java": "java",
    # JavaScript / TypeScript
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    # C#
    ".cs": "csharp",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rust",
    # SQL
    ".sql": "sql",
    # PHP
    ".php": "php",
    ".phtml": "php",
    # R
    ".r": "r",
    ".R": "r",
    # Lua
    ".lua": "lua",
    # VB / VBA
    ".vb": "vb",
    ".vbs": "vb",
    ".vba": "vb",
    # HTML / CSS
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    # JSON / XML
    ".json": "json",
    ".xml": "xml",
    ".xhtml": "xml",
    ".svg": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    # 其他脚本 / 配置
    ".sh": "bash",
    ".bat": "batch",
    ".ps1": "powershell",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".toml": "toml",
    ".md": "markdown",
    ".rst": "rst",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".vue": "vue",
    ".svelte": "svelte",
}

TEXT_EXTENSIONS = {
    ".txt",
    ".log",
    ".csv",
    ".rst",
    ".env",
    ".gitignore",
    ".gitconfig",
    ".properties",
    ".tex",
    ".latex",
    ".asciidoc",
    ".adoc",
    ".styl",
}


# ──────────────────────────────────────────────────────────────────────────────
# 顶栏框架（从 pdf_previewer_layout.py 原样复制）
# ──────────────────────────────────────────────────────────────────────────────

class _ToolbarFrame(QFrame):
    """顶栏框架 —— 页面标签通过布局居中，操作按钮在 resizeEvent 中绝对定位到两侧。

    这样页码标签是在整个顶栏宽度上真正居中，不会被两侧按钮挤偏。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._left_buttons: list[QWidget] = []
        self._right_buttons: list[QWidget] = []

    def add_left_button(self, btn: QWidget) -> None:
        """注册一个左侧按钮，将其父对象设为此顶栏并在下次布局时自动定位。"""
        self._left_buttons.append(btn)
        btn.setParent(self)

    def add_right_button(self, btn: QWidget) -> None:
        """注册一个右侧按钮，将其父对象设为此顶栏并在下次布局时自动定位。"""
        self._right_buttons.append(btn)
        btn.setParent(self)

    def fixedHeight(self) -> int:
        """Return current fixed height (convenience for tests)."""
        return self.height()

    def _layout_buttons(self) -> None:
        """将已注册的可见按钮固定到顶栏两侧，跳过隐藏按钮。"""
        # 左侧按钮（从左往右排列）
        left = 8  # 左侧内边距 8px
        for btn in self._left_buttons:
            if not btn.isVisible():
                continue
            btn.move(left, (self.height() - btn.height()) // 2)
            left = btn.geometry().right() + 6  # 按钮间距 6px
        # 右侧按钮（从右往左排列）
        right = self.width() - 8  # 右侧内边距 8px
        for btn in reversed(self._right_buttons):
            if not btn.isVisible():
                continue
            btn.move(right - btn.width(), (self.height() - btn.height()) // 2)
            right = btn.geometry().left() - 6  # 按钮间距 6px

    def resizeEvent(self, event) -> None:
        """每次大小变化时重新定位可见按钮，不影响中间布局的居中计算。"""
        super().resizeEvent(event)
        self._layout_buttons()

    def showEvent(self, event) -> None:
        """首次显示时立即布局按钮（某些平台下初始 resizeEvent 可能不触发）。"""
        super().showEvent(event)
        self._layout_buttons()

    def _get_colors(self) -> dict[str, QColor]:
        """获取当前主题下的顶栏颜色（paintEvent 中动态读取，确保主题切换生效）。"""
        return {
            "bg": tm.fill,
            "border": tm.alpha_of(tm.mid, 25),
        }

    def paintEvent(self, event: QPaintEvent) -> None:
        """自绘顶栏圆角背景与边框，颜色跟随当前主题。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        colors = self._get_colors()
        rect = QRectF(self.rect())
        radius = 8.0

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["bg"])
        painter.drawPath(path)

        painter.setPen(QPen(colors["border"], 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


# ──────────────────────────────────────────────────────────────────────────────
# 带自定义滚动条的预览内容包装基类
# ──────────────────────────────────────────────────────────────────────────────

class _StyledPreviewScrollArea(QWidget):
    """带自定义 StyledScrollBar 的内容包装基类。

    子类在调用 ``super().__init__()`` 之前必须设置 ``self._content_widget``
    （例如 ``QTextEdit`` 或 ``QTextBrowser``）。基类负责创建包含该
    内容控件、两个 ``StyledScrollBar`` 以及右下角占位格的 ``QGridLayout``，
    并提供内部滚动条与自定义滚动条之间的双向同步、平滑滚轮事件过滤以及
    ``reset_scrollbars`` 清理逻辑。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._updating: bool = False
        self._wheel_step_scale: float = 1.0

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        grid.addWidget(self._content_widget, 0, 0)

        self._vbar = StyledScrollBar(orientation=Qt.Vertical)
        self._vbar.setRange(0, 0)
        self._vbar.setMaximumWidth(12)
        grid.addWidget(self._vbar, 0, 1)

        self._hbar = StyledScrollBar(orientation=Qt.Horizontal)
        self._hbar.setRange(0, 0)
        self._hbar.setMaximumHeight(12)
        grid.addWidget(self._hbar, 1, 0)

        corner = QWidget()
        corner.setFixedSize(self._hbar.height(), self._vbar.width())
        grid.addWidget(corner, 1, 1)

        self._sync_from_internal()
        self._connect_scrollbars()

        self.verticalScrollBar = lambda: self._vbar  # type: ignore[attr-defined]
        self.horizontalScrollBar = lambda: self._hbar  # type: ignore[attr-defined]
        self._apply_smooth_scroll()

    def _apply_smooth_scroll(self) -> None:
        """安装统一的平滑滚动配置：QScroller 手势/惯性与自定义滚轮过滤。

        使用与 ``FileSelectorLayout`` / ``FilePoolLayout`` 完全一致的
        ``StyledScrollArea.DEFAULT_PROFILE`` 作为 touch/drag 惯性配置，
        并使用 ``_WheelSmoothScrollFilter`` 处理滚轮事件。host widget
        为当前包装器，以便滚轮过滤解析到自定义 ``StyledScrollBar``。
        """
        target = self._content_widget.viewport()
        scroller = QScroller.scroller(target)
        QScroller.grabGesture(target, QScroller.TouchGesture)
        StyledScrollArea._apply_scroller_profile(
            scroller, StyledScrollArea.DEFAULT_PROFILE
        )

        self._wheel_filter = _WheelSmoothScrollFilter(
            self, self._content_widget, wheel_step_scale=self._wheel_step_scale
        )
        self._content_widget.installEventFilter(self._wheel_filter)
        target.installEventFilter(self._wheel_filter)

    def _connect_scrollbars(self) -> None:
        """连接内部滚动条与自定义滚动条的双向同步信号。"""
        v_internal = self._content_widget.verticalScrollBar()
        h_internal = self._content_widget.horizontalScrollBar()

        v_internal.rangeChanged.connect(self._on_vrange_changed)
        v_internal.valueChanged.connect(self._on_vvalue_changed)
        self._vbar.valueChanged.connect(self._on_vbar_changed)

        h_internal.rangeChanged.connect(self._on_hrange_changed)
        h_internal.valueChanged.connect(self._on_hvalue_changed)
        self._hbar.valueChanged.connect(self._on_hbar_changed)

    def _sync_from_internal(self) -> None:
        """从内部滚动条同步范围、步长和当前值到自定义滚动条。"""
        v_internal = self._content_widget.verticalScrollBar()
        h_internal = self._content_widget.horizontalScrollBar()

        self._vbar.setRange(v_internal.minimum(), v_internal.maximum())
        self._vbar.setPageStep(v_internal.pageStep())
        self._vbar.setSingleStep(v_internal.singleStep())
        self._vbar.setValue(v_internal.value())

        self._hbar.setRange(h_internal.minimum(), h_internal.maximum())
        self._hbar.setPageStep(h_internal.pageStep())
        self._hbar.setSingleStep(h_internal.singleStep())
        self._hbar.setValue(h_internal.value())

    def _on_vrange_changed(self, min_val: int, max_val: int) -> None:
        """垂直范围变化时更新自定义滚动条。"""
        self._vbar.setRange(min_val, max_val)
        self._vbar.setPageStep(
            self._content_widget.verticalScrollBar().pageStep()
        )
        self._vbar.setSingleStep(
            self._content_widget.verticalScrollBar().singleStep()
        )

    def _on_hrange_changed(self, min_val: int, max_val: int) -> None:
        """水平范围变化时更新自定义滚动条。"""
        self._hbar.setRange(min_val, max_val)
        self._hbar.setPageStep(
            self._content_widget.horizontalScrollBar().pageStep()
        )
        self._hbar.setSingleStep(
            self._content_widget.horizontalScrollBar().singleStep()
        )

    def _on_vvalue_changed(self, value: int) -> None:
        """内部垂直滚动条值变化 -> 同步到自定义滚动条。"""
        if self._updating:
            return
        self._updating = True
        try:
            self._vbar.setValue(value)
        finally:
            self._updating = False

    def _on_hvalue_changed(self, value: int) -> None:
        """内部水平滚动条值变化 -> 同步到自定义滚动条。"""
        if self._updating:
            return
        self._updating = True
        try:
            self._hbar.setValue(value)
        finally:
            self._updating = False

    def _on_vbar_changed(self, value: int) -> None:
        """自定义垂直滚动条值变化 -> 同步到内部滚动条。"""
        if self._updating:
            return
        self._updating = True
        try:
            self._content_widget.verticalScrollBar().setValue(value)
        finally:
            self._updating = False

    def _on_hbar_changed(self, value: int) -> None:
        """自定义水平滚动条值变化 -> 同步到内部滚动条。"""
        if self._updating:
            return
        self._updating = True
        try:
            self._content_widget.horizontalScrollBar().setValue(value)
        finally:
            self._updating = False

    def reset_scrollbars(self) -> None:
        """重置滚动条状态（用于 cleanup）。"""
        self._vbar.setRange(0, 0)
        self._vbar.setValue(0)
        self._hbar.setRange(0, 0)
        self._hbar.setValue(0)
        if self._wheel_filter is not None:
            self._wheel_filter._content_overscroll.reset()


# ──────────────────────────────────────────────────────────────────────────────
# 源码预览视图（使用无输入框样式的 QTextEdit）
# ──────────────────────────────────────────────────────────────────────────────

class _SourceView(_StyledPreviewScrollArea):
    """源码预览包装器：只读 QTextEdit + 自定义 StyledScrollBar + 平滑滚轮。

    使用 ``QTextEdit`` 而非 ``QPlainTextEdit``，使其垂直滚动单位为像素，与
    Markdown 渲染视图（``QTextBrowser``）的滚动行为一致；StyledScrollBar
    与滚轮平滑动画仍由基类提供。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._text_edit = QTextEdit()
        self._text_edit.setObjectName("TextPreviewerSourceEdit")
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self._text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setViewportMargins(16, 0, 16, 0)
        # 禁止富文本，防止 Markdown 源码被解析为 HTML。
        self._text_edit.setAcceptRichText(False)
        self._content_widget = self._text_edit
        # 与 Markdown 渲染视图保持一致的像素级滚轮步长比例。
        self._wheel_step_scale = 1.0
        super().__init__(parent)

    def update_wheel_step_scale(self) -> None:
        """源码视图已改为像素滚动，保持与 Markdown 视图一致的 1.0 比例。"""
        self._wheel_step_scale = 1.0
        if self._wheel_filter is not None:
            self._wheel_filter.set_wheel_step_scale(self._wheel_step_scale)


# ──────────────────────────────────────────────────────────────────────────────
# 支持右键上下文菜单的 QTextBrowser（用于 Markdown 视图中的超链接）
# ──────────────────────────────────────────────────────────────────────────────

class _LinkTextBrowser(QTextBrowser):
    """QTextBrowser 子类：为超链接提供右键上下文菜单。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_file: str = ""
        self.anchorClicked.connect(self._on_anchor_clicked)

    def _on_anchor_clicked(self, url: QUrl) -> None:
        """处理点击的超链接：#锚点 滚动到对应位置，外部链接用系统打开。"""
        anchor = url.toString()
        if anchor.startswith("#"):
            self.scrollToAnchor(anchor[1:])
        else:
            self._open_anchor(anchor)

    def set_current_file(self, file_path: str) -> None:
        """设置当前 Markdown 文件路径，用于解析相对链接。"""
        self._current_file = file_path

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """右键点击时构建 StyledContextMenu：命中链接显示链接操作，有选区显示复制选区，始终显示全选。"""
        menu = StyledContextMenu(parent=self)

        anchor = self.anchorAt(event.pos())
        if anchor:
            menu.add_item("在浏览器中打开", callback=lambda: self._open_anchor(anchor))
            menu.add_item("复制链接", callback=lambda: self._copy_anchor(anchor))

        if self.textCursor().hasSelection():
            menu.add_item("复制选中文字", callback=self._copy_selected_text)

        if menu.actions():
            menu.add_separator()
        menu.add_item("全选", callback=self._select_all)

        menu.exec(event.globalPos())

    def _copy_selected_text(self) -> None:
        """将当前选中的文本复制到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.textCursor().selectedText())

    def _select_all(self) -> None:
        """选中 QTextBrowser 中所有文本。"""
        self.selectAll()

    def _open_anchor(self, anchor: str) -> None:
        """在浏览器/系统中打开链接；相对路径基于当前文件目录解析。"""
        url = QUrl(anchor)
        if url.isRelative() and self._current_file:
            base_dir = Path(self._current_file).parent
            resolved = (base_dir / anchor).resolve()
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved)))
        else:
            QDesktopServices.openUrl(url)

    def _copy_anchor(self, anchor: str) -> None:
        """将原始 href 文本复制到剪贴板。"""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(anchor)


# ──────────────────────────────────────────────────────────────────────────────
# Markdown 渲染包装器
# ──────────────────────────────────────────────────────────────────────────────

class _MarkdownView(_StyledPreviewScrollArea):
    """Markdown 渲染包装器：隐藏 QTextBrowser 默认滚动条，使用 StyledScrollBar。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._text_browser = _LinkTextBrowser()
        self._text_browser.setObjectName("TextPreviewerMarkdownView")
        self._text_browser.setOpenExternalLinks(False)
        self._text_browser.setOpenLinks(False)
        self._text_browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_browser.setViewportMargins(16, 0, 16, 0)
        self._content_widget = self._text_browser
        super().__init__(parent)

    def set_current_file(self, file_path: str) -> None:
        """向内部 QTextBrowser 传递当前 Markdown 文件路径。"""
        self._text_browser.set_current_file(file_path)

    def toPlainText(self) -> str:
        """兼容测试的代理方法。"""
        return self._text_browser.toPlainText()


# ──────────────────────────────────────────────────────────────────────────────
# 缩放弹出面板（从 pdf/image previewer_layout 复制并改造为控制源码字号）
# ──────────────────────────────────────────────────────────────────────────────

class _ZoomPopup(QWidget):
    """字号缩放弹出面板：含横向滑动条 + 百分比按钮。"""

    FONT_SIZE_MIN = 8
    FONT_SIZE_MAX = 32

    def __init__(self, parent: Optional["TextPreviewerLayout"] = None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._parent_layout = parent
        self._radius = 8
        self._padding = 8
        self._closing = False

        self._base_font_size = (
            int(parent._base_font_size)
            if parent and hasattr(parent, "_base_font_size")
            else 10
        )
        self._zoom_value = self._base_font_size

        # 动画
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        layout.setSpacing(8)

        # 百分比按钮（点击重置为 100%）
        self._pct_btn = StyledButton("100%", variant="ghost", size="sm")
        self._pct_btn.setFixedHeight(28)
        self._pct_btn.clicked.connect(self._reset_zoom)
        layout.addWidget(self._pct_btn)

        # 横向滑动条
        self._slider = StyledSlider(
            value=self._font_size_to_value(self._base_font_size),
            size="sm",
            orientation=Qt.Horizontal,
        )
        self._slider.setFixedWidth(140)
        self._slider.value_changed.connect(self._on_slider_changed)
        layout.addWidget(self._slider)

    def _font_size_to_value(self, font_size: int) -> float:
        """将字号映射为滑动条 0.0~1.0。"""
        size = max(self.FONT_SIZE_MIN, min(self.FONT_SIZE_MAX, font_size))
        return (size - self.FONT_SIZE_MIN) / max(
            1, self.FONT_SIZE_MAX - self.FONT_SIZE_MIN
        )

    def _value_to_font_size(self, value: float) -> int:
        """将滑动条 0.0~1.0 映射为字号。"""
        return self.FONT_SIZE_MIN + int(value * (self.FONT_SIZE_MAX - self.FONT_SIZE_MIN))

    def paintEvent(self, event) -> None:
        """绘制半透明圆角背景 + 边框。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        p.setPen(Qt.NoPen)
        p.setBrush(tm.alpha_of(tm.surface, 85))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        p.setPen(QPen(tm.alpha_of(tm.mid, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def show_animated(self, anchor_br: QPoint) -> None:
        """从按钮右下角向下展开，弹窗右对齐。"""
        pw = 220
        ph = 48
        margin_r = 5
        x = anchor_br.x() - pw - margin_r
        y = anchor_br.y() + 7

        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.x() + 8, min(x, sg.right() - pw - 8))

        start_h = 10
        self.setGeometry(x, y, pw, start_h)
        self.setWindowOpacity(0.0)
        super().show()
        self.raise_()
        self.activateWindow()

        self._fade.stop()
        self._fade.setDuration(180)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

        self._slide.stop()
        self._slide.setDuration(200)
        self._slide.setStartValue(self.geometry())
        self._slide.setEndValue(QRectF(x, y, pw, ph))

        self._fade.start()
        self._slide.start()

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._fade.stop()
        self._fade.setDuration(120)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)

        self._slide.stop()
        self._slide.setDuration(120)
        self._slide.setStartValue(self.geometry())
        end = QRectF(self.geometry())
        end.setHeight(8)
        self._slide.setEndValue(end.toRect())

        self._slide.finished.connect(self._close_and_reset)
        self._fade.start()
        self._slide.start()

    def _close_and_reset(self) -> None:
        self._slide.finished.disconnect(self._close_and_reset)
        self.close()
        self._closing = False

    def _on_slider_changed(self, val: float) -> None:
        """滑动条变化时同步字号到父布局。"""
        font_size = self._value_to_font_size(val)
        self._zoom_value = font_size
        pct = 100
        if self._base_font_size > 0:
            pct = int(round(font_size / self._base_font_size * 100))
        self._pct_btn.setText(f"{pct}%")
        if self._parent_layout and hasattr(self._parent_layout, "_apply_font_size_from_zoom"):
            self._parent_layout._apply_font_size_from_zoom(font_size)

    def _reset_zoom(self) -> None:
        """重置为基准字号（100%）。"""
        self._zoom_value = self._base_font_size
        self._pct_btn.setText("100%")
        self._slider.value = self._font_size_to_value(self._base_font_size)
        if self._parent_layout and hasattr(self._parent_layout, "_apply_font_size_from_zoom"):
            self._parent_layout._apply_font_size_from_zoom(self._base_font_size)

    def sync_from_parent(self) -> None:
        """从父布局当前字号同步滑条和百分比显示。"""
        layout = self._parent_layout
        if layout is None:
            return
        font_size = max(
            self.FONT_SIZE_MIN,
            min(self.FONT_SIZE_MAX, getattr(layout, "_font_size", self._base_font_size)),
        )
        self._zoom_value = font_size
        pct = 100
        if self._base_font_size > 0:
            pct = int(round(font_size / self._base_font_size * 100))
        self._pct_btn.setText(f"{pct}%")
        self._slider.value = self._font_size_to_value(font_size)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._closing = False


# ──────────────────────────────────────────────────────────────────────────────
# QSyntaxHighlighter 适配器（包装 create_highlighter("auto"））
# ──────────────────────────────────────────────────────────────────────────────

class _TextHighlighter(QSyntaxHighlighter):
    """基于 freeassetfilter.utils.syntax_highlighter 的 QSyntaxHighlighter 适配器。

    逐文本块调用高亮器的 tokenize(text, language) 方法，并将返回的 Token
    通过 get_qtextformat(token_type) 应用到 QTextDocument。
    """

    def __init__(
        self,
        parent=None,
        file_path: Optional[str] = None,
        language: Optional[str] = None,
        dark_mode: Optional[bool] = None,
    ) -> None:
        super().__init__(parent)
        self.language = language or self._detect_language(file_path)
        self.faf_highlighter = create_highlighter("auto", dark_mode=dark_mode)
        self.color_scheme = self.faf_highlighter.color_scheme

    def _detect_language(self, file_path: Optional[str]) -> str:
        """根据文件路径检测语言标识。"""
        if not file_path:
            return "text"
        ext = Path(file_path).suffix.lower()
        return CODE_EXTENSIONS.get(ext, "text")

    def highlightBlock(self, text: str) -> None:
        """实现 QSyntaxHighlighter 接口：逐块高亮。"""
        if not text or self.language == "text":
            return
        try:
            tokens = self.faf_highlighter.tokenize(text, self.language)
            for token in tokens:
                fmt = self.faf_highlighter.get_qtextformat(token.token_type)
                self.setFormat(token.start_pos, len(token.text), fmt)
        except (ValueError, KeyError, AttributeError, RuntimeError):
            # 解析失败时保持默认样式，不影响文本显示
            pass


# ──────────────────────────────────────────────────────────────────────────────
# 搜索侧边栏模型 / 委托 / 工具提示
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _SearchMatch:
    """单次匹配结果的数据容器。"""

    start: int
    end: int
    keyword: str
    before: str
    after: str
    context: str
    line: int
    progress: int
    view: str
    tooltip_before: str
    tooltip_after: str
    line_progress: int


class _SearchResultModel(QAbstractListModel):
    """为 QListView 提供懒加载搜索结果的只读模型。"""

    StartRole = Qt.UserRole + 1
    EndRole = Qt.UserRole + 2
    KeywordRole = Qt.UserRole + 3
    BeforeRole = Qt.UserRole + 4
    AfterRole = Qt.UserRole + 5
    ContextRole = Qt.UserRole + 6
    LineRole = Qt.UserRole + 7
    ProgressRole = Qt.UserRole + 8
    MatchRole = Qt.UserRole + 10

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._matches: list[_SearchMatch] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._matches)

    @staticmethod
    def _compose_context(match: _SearchMatch, max_total: int = 120) -> str:
        """组合 tooltip 上下文：优先保留 keyword，超长时先截右侧再截左侧。"""
        keyword = match.keyword
        if len(keyword) > max_total:
            return keyword

        budget = max_total - len(keyword)
        before = match.tooltip_before
        after = match.tooltip_after

        if len(before) + len(after) > budget:
            after = after[: max(0, budget - len(before))]
            if len(before) + len(after) > budget:
                before = before[-max(0, budget - len(after)) :]

        return f"{before}{keyword}{after}"

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._matches):
            return None
        match = self._matches[index.row()]
        if role == Qt.DisplayRole:
            return f"{match.before}{match.keyword}{match.after}"
        if role == self.StartRole:
            return match.start
        if role == self.EndRole:
            return match.end
        if role == self.KeywordRole:
            return match.keyword
        if role == self.BeforeRole:
            return match.before
        if role == self.AfterRole:
            return match.after
        if role == self.ContextRole:
            return self._compose_context(match)
        if role == self.LineRole:
            return match.line
        if role == self.ProgressRole:
            return match.progress
        if role == self.MatchRole:
            return match
        return None

    def add_results(self, matches: list[_SearchMatch]) -> None:
        """追加匹配结果并通知视图增量更新。"""
        if not matches:
            return
        start = len(self._matches)
        self.beginInsertRows(QModelIndex(), start, start + len(matches) - 1)
        self._matches.extend(matches)
        self.endInsertRows()

    def clear(self) -> None:
        """清空模型。"""
        if not self._matches:
            return
        self.beginResetModel()
        self._matches.clear()
        self.endResetModel()

    def match_at(self, row: int) -> Optional[_SearchMatch]:
        """返回指定行的匹配数据。"""
        if 0 <= row < len(self._matches):
            return self._matches[row]
        return None


class _SearchResultTooltip(StyledTooltip):
    """为搜索结果项提供的手动控制版 StyledTooltip。

    屏蔽父控件 hover 自动显示逻辑，改由 delegate 的 helpEvent 驱动。
    支持多行自动换行与自适应宽高，字号跟随应用默认字体，不显示箭头指示器。
    """

    MAX_CONTENT_WIDTH = 320

    def __init__(self, parent_widget: QWidget) -> None:
        super().__init__(parent_widget, "", placement="right")

    def _base_font(self) -> QFont:
        """返回跟随应用默认字号的字体，并统一为常规字重。"""
        font = super()._base_font()
        font.setWeight(QFont.Normal)
        return font

    def set_tooltip_text(self, text: str) -> None:
        """更新提示内容并重新计算尺寸。"""
        self._text = text
        self._compute_sizes()
        self.setFixedSize(self._total_w, self._total_h)
        self.update()

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:  # type: ignore[override]
        """仅在鼠标离开父控件时隐藏，其余事件全部透传。"""
        if obj is self._parent and event.type() == QEvent.Leave:
            self.hide()
        return False

    def _compute_sizes(self) -> None:
        """按最大宽度自动换行计算纯气泡内容尺寸。"""
        font = self._base_font()
        fm = QFontMetrics(font)
        if self._text:
            wrap_rect = fm.boundingRect(
                QRect(0, 0, self.MAX_CONTENT_WIDTH, 0),
                Qt.TextWrapAnywhere | Qt.AlignLeft,
                self._text,
            )
            text_w = wrap_rect.width()
            text_h = wrap_rect.height()
        else:
            text_w = 0
            text_h = fm.height()

        self._content_w = max(text_w + PADDING_H * 2, 30)
        self._content_h = text_h + PADDING_V * 2
        self._font = font
        self._total_w = self._content_w
        self._total_h = self._content_h
        self.setFixedSize(int(self._total_w), int(self._total_h))

    def position_for(self, item_global_rect: QRect) -> QPoint:
        """根据列表项全局矩形计算 tooltip 左上角位置，优先右侧，超出屏幕则翻转到左侧。"""
        screen = QApplication.primaryScreen().availableGeometry()
        placements = ["right", "left"]

        for placement in placements:
            if placement == "right":
                x = item_global_rect.right() + GAP
                y = item_global_rect.center().y() - self._total_h / 2
            else:
                x = item_global_rect.left() - GAP - self._total_w
                y = item_global_rect.center().y() - self._total_h / 2

            tr = QRectF(float(x), float(y), float(self._total_w), float(self._total_h))
            if screen.contains(tr.toRect()):
                self._actual = placement
                return QPoint(int(x), int(y))

        self._actual = "right"
        return QPoint(
            int(item_global_rect.right() + GAP),
            int(item_global_rect.center().y() - self._total_h / 2),
        )

    def paintEvent(self, event: QEvent) -> None:  # type: ignore[override]
        """自绘圆角气泡（无箭头），并支持多行文本。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bubble_bg = tm.alpha_of(tm.surface, 90)
        bubble_border = tm.alpha_of(tm.mid, 40)
        text_color = tm.text

        cw = self._content_w
        ch = self._content_h
        bubble = QRectF(0.0, 0.0, float(cw), float(ch))

        path = QPainterPath()
        path.addRoundedRect(bubble, float(BORDER_RADIUS), float(BORDER_RADIUS))

        painter.setPen(QPen(bubble_border, 1.0))
        painter.setBrush(bubble_bg)
        painter.drawPath(path)

        if self._text:
            painter.setPen(text_color)
            painter.setFont(self._font)
            text_rect = QRectF(
                bubble.x() + PADDING_H,
                bubble.y() + PADDING_V,
                cw - PADDING_H * 2,
                ch - PADDING_V * 2,
            )
            painter.drawText(
                text_rect,
                Qt.AlignLeft | Qt.AlignTop | Qt.TextWrapAnywhere,
                self._text,
            )


class _SearchResultDelegate(QStyledItemDelegate):
    """搜索结果项委托：绘制“前5字 + 加粗关键字 + 后5字”，并处理 hover 提示。"""

    def __init__(self, list_view: QListView, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._list_view = list_view
        self._tooltip = _SearchResultTooltip(list_view)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: U100
        return QSize(0, 32)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        rect = option.rect
        is_selected = bool(option.state & QStyle.State_Selected)
        is_focused = bool(option.state & QStyle.State_HasFocus)
        if is_selected and is_focused:
            bg = tm.accent
            text_color = tm.white
            keyword_color = tm.white
        elif is_selected:
            bg = tm.accent
            text_color = tm.white
            keyword_color = tm.white
        elif option.state & QStyle.State_MouseOver:
            bg = tm.alpha_of(tm.text, 10)
            text_color = tm.text
            keyword_color = tm.accent
        else:
            bg = tm.transparent
            text_color = tm.text
            keyword_color = tm.accent

        painter.fillRect(rect, bg)

        before = index.data(_SearchResultModel.BeforeRole) or ""
        keyword = index.data(_SearchResultModel.KeywordRole) or ""
        after = index.data(_SearchResultModel.AfterRole) or ""

        left_margin = 12
        right_margin = 12
        max_width = max(0, rect.width() - left_margin - right_margin)

        normal_font = QFont(option.font)
        bold_font = QFont(option.font)
        bold_font.setBold(True)

        fm_normal = QFontMetrics(normal_font)
        fm_bold = QFontMetrics(bold_font)

        prefix_w = fm_normal.horizontalAdvance(before)
        keyword_w = fm_bold.horizontalAdvance(keyword)
        suffix_w = fm_normal.horizontalAdvance(after)

        # 如果总宽度超过可用空间，从上下文两侧等比例截断。
        total_w = prefix_w + keyword_w + suffix_w
        if total_w > max_width and total_w > 0:
            ratio = max_width / total_w
            before = _elide_to_width(before, fm_normal, int(prefix_w * ratio))
            keyword = _elide_to_width(keyword, fm_bold, int(keyword_w * ratio))
            after = _elide_to_width(after, fm_normal, int(suffix_w * ratio))
            prefix_w = fm_normal.horizontalAdvance(before)
            keyword_w = fm_bold.horizontalAdvance(keyword)
            suffix_w = fm_normal.horizontalAdvance(after)

        baseline = int(rect.top() + (rect.height() - fm_normal.height()) / 2 + fm_normal.ascent())
        x = int(rect.left() + left_margin)

        painter.setFont(normal_font)
        painter.setPen(text_color)
        painter.drawText(x, baseline, before)
        x += prefix_w

        painter.setFont(bold_font)
        painter.setPen(keyword_color)
        painter.drawText(x, baseline, keyword)
        x += keyword_w

        painter.setFont(normal_font)
        painter.setPen(text_color)
        painter.drawText(x, baseline, after)

    def helpEvent(
        self,
        event: QHelpEvent,
        view: QAbstractItemView,
        option: QStyleOptionViewItem,  # noqa: U100
        index: QModelIndex,
    ) -> bool:
        if event.type() == QEvent.ToolTip and index.isValid():
            match_obj = index.data(_SearchResultModel.MatchRole)
            if not isinstance(match_obj, _SearchMatch):
                return False

            context = index.data(_SearchResultModel.ContextRole) or ""
            text = (
                f"{context}\n"
                f"字符进度 {match_obj.progress}%  ·  "
                f"行号进度 {match_obj.line_progress}%  ·  "
                f"第 {match_obj.line} 行"
            )
            self._tooltip.set_tooltip_text(text)

            rect = view.visualRect(index)
            global_top_left = view.viewport().mapToGlobal(rect.topLeft())
            item_global_rect = QRect(global_top_left, rect.size())
            self._tooltip.move(self._tooltip.position_for(item_global_rect))
            self._tooltip.setWindowOpacity(1.0)
            self._tooltip.show()
            self._tooltip.raise_()
            return True

        if event.type() == QEvent.Leave:
            self._tooltip.hide()
            return True

        return super().helpEvent(event, view, option, index)


def _elide_to_width(text: str, fm: QFontMetrics, max_width: int) -> str:
    """按给定 QFontMetrics 截断文本，保留末尾允许放不下时裁剪。"""
    if not text:
        return ""
    if fm.horizontalAdvance(text) <= max_width:
        return text
    # 二分查找最长可容纳长度
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if fm.horizontalAdvance(text[:mid]) <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low]


@dataclass
class _SearchState:
    """当前搜索会话状态。"""

    pattern: str
    flags: int
    text: str
    resume_pos: int = 0
    has_more: bool = False
    regex_enabled: bool = False
    case_sensitive: bool = False
    view: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# 文本预览器布局
# ──────────────────────────────────────────────────────────────────────────────

class TextPreviewerLayout(QWidget):
    """文本预览器布局。

    顶栏固定 48px，包含文件名/编码标签与常用操作按钮；
    内容区域使用 QStackedLayout 切换源码、Markdown 渲染与未加载覆盖层。

    Signals:
        close_requested: 关闭预览请求信号
    """

    close_requested = Signal()

    FONT_SIZE_MIN = 8
    FONT_SIZE_MAX = 32
    FONT_SIZE_STEP = 1
    DEFAULT_FONT_SIZE = 14
    _SEARCH_BATCH_SIZE = 100

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        dpi_scale: Optional[float] = None,
        global_font: Optional[QFont] = None,
        settings_manager: Optional[Any] = None,
        standalone: bool = False,
    ) -> None:
        super().__init__(parent)
        self._dpi_scale = dpi_scale or 1.0
        self._global_font = global_font or QFont("Segoe UI", self.DEFAULT_FONT_SIZE)
        self._settings_manager = settings_manager
        self._standalone = standalone

        self._current_file: str = ""
        self._current_text: str = ""
        self._current_raw: Optional[bytes] = None
        self._current_encoding: str = ""
        self._current_mode: str = "plain"
        self._highlighter: Optional[_TextHighlighter] = None
        self._fullscreen: bool = False
        self._saved_geometry = None

        self._word_wrap: bool = True
        # 预览器正文字号固定为 14px，独立于全局控件字号，确保代码/文本/Markdown 可读。
        self._base_font_size: int = self.DEFAULT_FONT_SIZE
        self._font_size: int = self._base_font_size
        self._zoom_popup: Optional[_ZoomPopup] = None
        self._markdown_renderer: Optional[_MarkdownRenderer] = (
            _MarkdownRenderer(font_size=self._font_size)
            if _MarkdownRenderer.is_available()
            else None
        )

        self._init_ui()
        self._connect_theme()
        self._apply_stylesheet()

        # 默认面板样式（独立运行与主窗口调用保持一致）
        mid = tm.mid
        txt = tm.text
        fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
        border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"
        self.set_section_styles(fill_color, border_color)

        # 安装应用级事件过滤，用于缩放弹窗外部点击/窗口移动关闭
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ── UI 初始化 ─────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        """初始化顶栏 + 内容区布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏（48px 固定高度，与 PDF / 图片预览器一致）
        self._top_bar = _ToolbarFrame()
        self._top_bar.setObjectName("TextPreviewerTopBar")
        self._top_bar.setFixedHeight(48)
        self._build_top_bar()
        layout.addWidget(self._top_bar)

        # 内容区（自适应拉伸）
        # index 0 = 源码视图（_SourceView 内部 _text_edit）
        # index 1 = Markdown 渲染视图（带自定义 StyledScrollBar）
        # index 2 = 未加载覆盖层（QLabel 提示）
        self._content_area = QFrame()
        self._content_area.setObjectName("TextPreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)

        # index 0：源码视图
        self._source_view = _SourceView(self._content_area)
        self._content_stack.addWidget(self._source_view)

        # index 1：Markdown 渲染视图
        self._markdown_view = _MarkdownView(self._content_area)
        self._content_stack.addWidget(self._markdown_view)

        # 字号初始化需要在源码视图和 Markdown 视图都创建完成后执行
        self._apply_font_size()

        # index 2：未加载覆盖层
        self._overlay = QWidget()
        self._overlay.setObjectName("TextPreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        self._placeholder = QLabel("选择文本文件开始预览")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        )
        overlay_layout.addWidget(self._placeholder)

        # "选择文件"按钮（仅 standalone 模式）
        self._browse_btn: Optional[QPushButton] = None
        if self._standalone:
            self._browse_btn = QPushButton("选择文本文件")
            self._browse_btn.setFixedSize(160, 40)
            self._browse_btn.setCursor(Qt.PointingHandCursor)
            self._browse_btn.clicked.connect(self._on_browse_file)
            self._style_browse_button()
            overlay_layout.addWidget(self._browse_btn, alignment=Qt.AlignCenter)

        self._content_stack.addWidget(self._overlay)

        # 初始显示覆盖层
        self._content_stack.setCurrentIndex(2)

        layout.addWidget(self._content_area, stretch=1)

        # 左右侧边栏抽屉（内容区创建后才能初始化）
        self._init_search_drawer()
        self._search_drawer.hide()
        self._init_ai_drawer()
        self._ai_drawer.hide()

    def _build_top_bar(self) -> None:
        """构建顶栏：左侧 搜索/换行/编码，中间字符统计，右侧 AI/缩放/渲染/最大化。"""
        top_layout = QHBoxLayout(self._top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        top_layout.setSpacing(6)

        # 中间：字符统计标签
        self._title_label = QLabel("文本预览")
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        top_layout.addStretch(1)
        top_layout.addWidget(self._title_label)
        top_layout.addStretch(1)

        # 左侧：搜索按钮（打开左侧搜索抽屉）
        search_icon = str(icons_dir() / "search.svg")
        self._search_btn = StyledButton("", variant="ghost", size="sm", icon=search_icon)
        self._search_btn.setFixedSize(32, 32)
        self._search_btn.setToolTip("搜索")
        self._search_btn.clicked.connect(self._toggle_search_drawer)
        self._top_bar.add_left_button(self._search_btn)

        # 左侧：换行切换按钮
        self._wrap_btn = StyledButton("换行", variant="ghost", size="sm")
        self._wrap_btn.setFixedSize(40, 32)
        self._wrap_btn.setToolTip("切换自动换行")
        self._wrap_btn.clicked.connect(self._on_word_wrap_toggle)
        self._top_bar.add_left_button(self._wrap_btn)

        # 左侧：编码选择下拉框
        self._encoding_combo = StyledComboBox(
            items=["自动识别"] + ENCODING_LIST, size="sm"
        )
        self._encoding_combo.setCurrentIndex(0)
        self._encoding_combo.setFixedWidth(110)
        self._encoding_combo.setToolTip("选择解码编码")
        self._encoding_combo.selection_made.connect(self._on_encoding_selected)
        self._top_bar.add_left_button(self._encoding_combo)

        # 右侧：AI 图标按钮（打开右侧 AI 抽屉）
        ai_icon = str(icons_dir() / "ai.svg")
        self._ai_btn = StyledButton("", variant="ghost", size="sm", icon=ai_icon)
        self._ai_btn.setFixedSize(32, 32)
        self._ai_btn.setToolTip("AI 功能")
        self._ai_btn.clicked.connect(self._toggle_ai_drawer)
        self._top_bar.add_right_button(self._ai_btn)

        # 右侧：缩放图标按钮（打开字号弹窗）
        zoom_icon = str(icons_dir() / "zoom.svg")
        self._zoom_btn = StyledButton("", variant="ghost", size="sm", icon=zoom_icon)
        self._zoom_btn.setFixedSize(32, 32)
        self._zoom_btn.setToolTip("缩放")
        self._zoom_btn.clicked.connect(self._on_zoom_clicked)
        self._top_bar.add_right_button(self._zoom_btn)

        # 右侧：源码 / 渲染切换按钮（仅 Markdown 可见）
        self._render_toggle_btn = StyledButton("源码", variant="ghost", size="sm")
        self._render_toggle_btn.setFixedSize(48, 32)
        self._render_toggle_btn.setToolTip("切换源码 / 渲染视图")
        self._render_toggle_btn.setVisible(False)
        self._render_toggle_btn.clicked.connect(self._on_render_toggle)
        self._render_toggle_btn.installEventFilter(self)
        self._top_bar.add_right_button(self._render_toggle_btn)

        # 右侧：最大化 / 还原窗口按钮
        self._maxsize_icon_path = str(icons_dir() / "maxsize.svg")
        self._minisize_icon_path = str(icons_dir() / "minisize.svg")
        self._maxsize_btn = StyledButton(
            "", variant="ghost", size="sm", icon=self._maxsize_icon_path
        )
        self._maxsize_btn.setFixedSize(32, 32)
        self._maxsize_btn.setToolTip("最大化")
        self._maxsize_btn.clicked.connect(self._on_maxsize_toggle)
        self._top_bar.add_right_button(self._maxsize_btn)

    # ── 公共接口 ────────────────────────────────────────────────────────────

    def set_text_content(
        self,
        text: str,
        file_path: str = "",
        encoding: str = "",
    ) -> None:
        """设置文本内容并选择正确的预览模式（无原始字节，不可切换编码）。

        Args:
            text: 文件文本内容。
            file_path: 文件路径（用于判断视图模式和高亮语言）。
            encoding: 文件编码名称。
        """
        self._current_raw = None
        if hasattr(self, "_encoding_combo") and self._encoding_combo is not None:
            self._encoding_combo.setCurrentIndex(0)
        self._set_decoded_text(text, file_path, encoding)

    def set_file(self, file_path: str) -> None:
        """读取文件并设置预览内容。

        Args:
            file_path: 要预览的文件路径。
        """
        if hasattr(self, "_encoding_combo") and self._encoding_combo is not None:
            self._encoding_combo.setCurrentIndex(0)

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            self._current_raw = None
            self._set_decoded_text(f"无法读取文件: {file_path}", str(path), "unknown")
            return

        try:
            raw = path.read_bytes()
            self._current_raw = raw
            text, encoding = self._decode_bytes(raw, "auto")
        except Exception as exc:
            self._current_raw = None
            text = f"读取文件失败: {exc}"
            encoding = "unknown"

        self._set_decoded_text(text, str(path), encoding)

    def _decode_bytes(self, raw: bytes, encoding: str) -> tuple[str, str]:
        """将原始字节按指定编码解码。

        Args:
            raw: 文件原始字节。
            encoding: "auto"/"自动识别" 时使用 chardet 检测，否则按名称解码。

        Returns:
            (解码后的文本, 实际使用的编码名称)
        """
        if encoding in ("auto", "自动识别"):
            detected = "utf-8"
            try:
                import chardet

                result = chardet.detect(raw)
                if result and result.get("encoding"):
                    detected = result["encoding"]
            except Exception:
                pass
            return raw.decode(detected, errors="replace"), detected

        return raw.decode(encoding, errors="replace"), encoding

    def _set_decoded_text(self, text: str, file_path: str, encoding: str) -> None:
        """设置已解码的文本内容并选择正确的预览模式。

        Args:
            text: 文件文本内容。
            file_path: 文件路径（用于判断视图模式和高亮语言）。
            encoding: 文件编码名称。
        """
        self._current_text = text
        self._current_file = file_path
        self._current_encoding = encoding
        self._current_mode = self._detect_view_mode(file_path)

        self._clear_search_results()
        self._update_stats(text)

        # 重置渲染/源码按钮可见性
        self._render_toggle_btn.setVisible(False)

        # 总是先把文本写入源码视图
        self._source_view._text_edit.setPlainText(text)
        self._source_view._text_edit.setReadOnly(True)
        self._source_view._sync_from_internal()

        if self._current_mode == "markdown" and MARKDOWN_AVAILABLE:
            self._render_toggle_btn.setVisible(True)
            if self._render_markdown():
                self._content_stack.setCurrentIndex(1)
                self._render_toggle_btn.setText("源码")
            else:
                # 渲染失败时回退为带语法高亮的源码视图
                self._render_toggle_btn.setVisible(False)
                self._apply_highlighter(language=self._get_language(file_path))
                self._content_stack.setCurrentIndex(0)
        elif self._current_mode == "markdown":
            # markdown 包不可用时当作带语法高亮的源码处理，并隐藏渲染切换按钮
            self._render_toggle_btn.setVisible(False)
            self._apply_highlighter(language=self._get_language(file_path))
            self._content_stack.setCurrentIndex(0)
        elif self._current_mode == "code":
            self._apply_highlighter(language=self._get_language(file_path))
            self._content_stack.setCurrentIndex(0)
        else:
            self._content_stack.setCurrentIndex(0)

    def _on_encoding_selected(self, text: str) -> None:
        """编码下拉框选择变化：使用内存中的原始字节重新解码。"""
        if self._current_raw is None:
            return
        encoding = text if text != "自动识别" else "auto"
        decoded, effective = self._decode_bytes(self._current_raw, encoding)
        self._set_decoded_text(decoded, self._current_file, effective)

    def _update_stats(self, text: Optional[str] = None) -> None:
        """更新顶栏字符统计标签。xxx字 · xxx行"""
        if text is None:
            text = self._current_text
        if not text:
            self._title_label.setText("文本预览")
            return
        chars = len(text.replace("\n", "").replace("\r", ""))
        lines = text.count("\n") + 1
        self._title_label.setText(f"{chars}字 · {lines}行")
        self._top_bar._layout_buttons()

    def _init_search_drawer(self) -> None:
        """初始化左侧搜索抽屉面板：搜索框、选项、懒加载结果列表。"""
        self._search_drawer = StyledDrawer(
            orientation="left",
            size="sm",
            bare=True,
            parent=self._content_area,
        )
        self._search_drawer._panel.setStyleSheet(
            f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
        )
        _orig_get_panel_size = self._search_drawer._get_panel_size

        def _constrained_panel_size() -> tuple[int, int]:
            pw, ph = _orig_get_panel_size()
            available_w = self._content_area.width()
            max_pw = max(available_w - 4, 60)
            return min(pw, max_pw), ph

        self._search_drawer._get_panel_size = _constrained_panel_size

        self._init_search_drawer_content()

    def _init_search_drawer_content(self) -> None:
        """构建搜索抽屉内部控件。"""
        panel_layout = self._search_drawer._panel.layout()
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)

        # 标题
        title = QLabel("搜索")
        title.setStyleSheet(
            f"color: {tm.text.name()}; font-size: 16px; font-weight: 600; background: transparent;"
        )
        panel_layout.addWidget(title)

        # 搜索输入行
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.setContentsMargins(0, 0, 0, 0)

        self._search_input = StyledLineEdit(size="sm")
        self._search_input.setPlaceholderText("输入关键词…")
        self._search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self._search_input, stretch=1)

        self._search_action_btn = StyledButton("搜索", variant="primary", size="sm")
        self._search_action_btn.setFixedHeight(30)
        self._search_action_btn.clicked.connect(self._do_search)
        search_row.addWidget(self._search_action_btn)

        panel_layout.addLayout(search_row)

        # 选项行
        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        options_row.setContentsMargins(0, 0, 0, 0)

        self._regex_checkbox = StyledCheckbox(text="使用正则表达式", size="sm")
        self._case_checkbox = StyledCheckbox(text="区分大小写", size="sm")

        options_row.addWidget(self._regex_checkbox)
        options_row.addWidget(self._case_checkbox)
        options_row.addStretch()

        panel_layout.addLayout(options_row)

        # 状态标签
        self._search_status = QLabel("")
        self._search_status.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 12px; background: transparent;"
        )
        self._search_status.setWordWrap(True)
        panel_layout.addWidget(self._search_status)

        # 结果列表（QListView + model + delegate 懒加载，使用 styled 滚动条 + 丝滑滚动）
        self._search_model = _SearchResultModel(self)
        self._search_list = QListView()
        self._search_list.setModel(self._search_model)
        self._search_list.setItemDelegate(_SearchResultDelegate(self._search_list, self))
        self._search_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._search_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._search_list.setVerticalScrollBar(StyledScrollBar(orientation=Qt.Vertical))
        self._search_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        StyledScrollArea.apply_to(self._search_list)
        self._search_list.setStyleSheet(
            "QListView { background: transparent; border: none; outline: none; }"
            "QListView::item { background: transparent; border: none; }"
        )
        self._search_list.clicked.connect(self._on_search_result_clicked)
        panel_layout.addWidget(self._search_list, stretch=1)

        # 加载更多
        self._load_more_btn = StyledButton("加载更多", variant="secondary", size="sm", block=True)
        self._load_more_btn.setFixedHeight(32)
        self._load_more_btn.clicked.connect(self._load_more_results)
        self._load_more_btn.hide()
        panel_layout.addWidget(self._load_more_btn)

        self._search_state: Optional[_SearchState] = None

    def _init_ai_drawer(self) -> None:
        """初始化右侧 AI 抽屉面板（bare 模式，内容留空）。"""
        self._ai_drawer = StyledDrawer(
            orientation="right",
            size="sm",
            bare=True,
            parent=self._content_area,
        )
        self._ai_drawer._panel.setStyleSheet(
            f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
        )
        _orig_get_panel_size = self._ai_drawer._get_panel_size

        def _constrained_panel_size() -> tuple[int, int]:
            pw, ph = _orig_get_panel_size()
            available_w = self._content_area.width()
            max_pw = max(available_w - 4, 60)
            return min(pw, max_pw), ph

        self._ai_drawer._get_panel_size = _constrained_panel_size

        # 占位文本提示
        self._ai_placeholder = QLabel("敬请期待")
        self._ai_placeholder.setAlignment(Qt.AlignCenter)
        self._ai_placeholder.setWordWrap(True)
        self._ai_placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
            " padding: 24px;"
        )
        panel_layout = self._ai_drawer._panel.layout()
        panel_layout.addStretch()
        panel_layout.addWidget(self._ai_placeholder, alignment=Qt.AlignCenter)
        panel_layout.addStretch()

    def _toggle_search_drawer(self) -> None:
        """切换搜索侧边面板的展开/收起。"""
        if self._search_drawer._is_open:
            self._search_drawer.close_drawer()
        else:
            self._search_drawer.open_drawer()

    def _toggle_ai_drawer(self) -> None:
        """切换 AI 侧边面板的展开/收起。"""
        if self._ai_drawer._is_open:
            self._ai_drawer.close_drawer()
        else:
            self._ai_drawer.open_drawer()

    def _get_search_corpus(self) -> tuple[str, str]:
        """返回当前可见视图的可搜索文本及其来源标识。

        Returns:
            (text, view)，其中 ``view`` 为 ``"rendered"`` 当 Markdown 渲染视图
            处于激活状态，否则为 ``"source"``。
        """
        if self._content_stack.currentWidget() is self._markdown_view:
            return self._markdown_view._text_browser.toPlainText(), "rendered"
        return self._source_view._text_edit.toPlainText(), "source"

    def _generate_search_matches(
        self,
        text: str,
        pattern: str,
        regex_enabled: bool,
        case_sensitive: bool,
        view: str,
        start: int = 0,
        batch_size: int = _SEARCH_BATCH_SIZE,
    ) -> tuple[list[_SearchMatch], int, bool]:
        """从 ``start`` 开始搜索下一批匹配并生成 ``_SearchMatch``。

        Args:
            text: 被搜索的全文本。
            pattern: 原始关键词或正则表达式。
            regex_enabled: 是否按正则解析 ``pattern``。
            case_sensitive: 是否区分大小写。
            view: 当前搜索的视图来源标识（"source" 或 "rendered"）。
            start: 搜索起始位置。
            batch_size: 本批最多返回的匹配数。

        Returns:
            (匹配列表, 下一批起始位置, 是否还有更多结果)

        Raises:
            re.error: 正则表达式无效时抛出。
        """
        flags = 0 if case_sensitive else re.IGNORECASE
        raw_pattern = pattern if regex_enabled else re.escape(pattern)
        compiled = re.compile(raw_pattern, flags)

        matches: list[_SearchMatch] = []
        resume_pos = start
        has_more = False
        text_len = len(text)
        if text_len == 0:
            return matches, resume_pos, has_more

        total_lines = text.count("\n") + 1

        for m in compiled.finditer(text, pos=start):
            match_start = m.start()
            match_end = m.end()
            matched = m.group(0)
            before = text[max(0, match_start - 5) : match_start]
            after = text[match_end : min(text_len, match_end + 5)]
            tooltip_before = text[max(0, match_start - 20) : match_start]
            tooltip_after = text[match_end : min(text_len, match_end + 20)]

            line_start = text.rfind("\n", 0, match_start) + 1
            line_end = text.find("\n", match_start)
            if line_end == -1:
                line_end = text_len
            context = text[line_start:line_end]
            if len(context) > 80:
                context = context[:77] + "..."

            line = text[:match_start].count("\n") + 1
            progress = int(match_start / text_len * 100)
            line_progress = 0 if total_lines <= 1 else int((line - 1) / total_lines * 100)

            matches.append(
                _SearchMatch(
                    start=match_start,
                    end=match_end,
                    keyword=matched,
                    before=before,
                    after=after,
                    context=context,
                    line=line,
                    progress=progress,
                    view=view,
                    tooltip_before=tooltip_before,
                    tooltip_after=tooltip_after,
                    line_progress=line_progress,
                )
            )
            resume_pos = match_end + 1 if match_start == match_end else match_end
            if len(matches) >= batch_size:
                has_more = True
                break

        return matches, resume_pos, has_more

    def _do_search(self) -> None:
        """执行搜索：读取输入并按选项在当前可见视图语料中匹配。"""
        keyword = self._search_input.text().strip()
        self._clear_search_results()

        if not keyword:
            self._load_more_btn.hide()
            self._search_status.setText("请输入搜索关键词")
            return

        text, view = self._get_search_corpus()
        if not text:
            self._load_more_btn.hide()
            self._search_status.setText("当前没有可搜索的文本")
            return

        regex_enabled = self._regex_checkbox.checked
        case_sensitive = self._case_checkbox.checked
        regex_fallback = False

        try:
            matches, resume_pos, has_more = self._generate_search_matches(
                text=text,
                pattern=keyword,
                regex_enabled=regex_enabled,
                case_sensitive=case_sensitive,
                view=view,
                start=0,
                batch_size=self._SEARCH_BATCH_SIZE,
            )
        except re.error:
            regex_fallback = True
            regex_enabled = False
            self._search_status.setText("正则语法错误，已按普通文本搜索")
            matches, resume_pos, has_more = self._generate_search_matches(
                text=text,
                pattern=keyword,
                regex_enabled=False,
                case_sensitive=case_sensitive,
                view=view,
                start=0,
                batch_size=self._SEARCH_BATCH_SIZE,
            )

        if not matches:
            self._load_more_btn.hide()
            self._search_status.setText("未找到匹配")
            return

        self._search_model.add_results(matches)
        self._search_state = _SearchState(
            pattern=keyword,
            flags=0 if case_sensitive else re.IGNORECASE,
            text=text,
            view=view,
            resume_pos=resume_pos,
            has_more=has_more,
            regex_enabled=regex_enabled,
            case_sensitive=case_sensitive,
        )

        if has_more:
            self._load_more_btn.show()
        else:
            self._load_more_btn.hide()

        total_label = f"{len(matches)}+" if has_more else str(len(matches))
        if regex_fallback:
            self._search_status.setText(
                f"正则语法错误，已按普通文本搜索（找到 {total_label} 项匹配）"
            )
        else:
            self._search_status.setText(f"找到 {total_label} 项匹配")

    def _load_more_results(self) -> None:
        """继续搜索并追加下一批结果。"""
        if self._search_state is None or not self._search_state.has_more:
            self._load_more_btn.hide()
            return

        state = self._search_state
        try:
            matches, resume_pos, has_more = self._generate_search_matches(
                text=state.text,
                pattern=state.pattern,
                regex_enabled=state.regex_enabled,
                case_sensitive=state.case_sensitive,
                view=state.view,
                start=state.resume_pos,
                batch_size=self._SEARCH_BATCH_SIZE,
            )
        except re.error:
            state.has_more = False
            self._load_more_btn.hide()
            return

        if not matches:
            state.has_more = False
            self._load_more_btn.hide()
            self._search_status.setText("没有更多结果")
            return

        self._search_model.add_results(matches)
        state.resume_pos = resume_pos
        state.has_more = has_more

        if len(matches) < self._SEARCH_BATCH_SIZE or not has_more:
            self._load_more_btn.hide()

        total = self._search_model.rowCount()
        self._search_status.setText(f"共找到 {total} 项匹配")

    def _on_search_result_clicked(self, index: QModelIndex) -> None:
        """点击搜索结果：仅在当前可见视图内选中对应字符范围。

        如果当前视图与 ``match.view`` 不一致，或者匹配位置已超出目标文本
        范围，则给出状态提示并放弃跳转。
        """
        if not index.isValid():
            return

        match = self._search_model.match_at(index.row())
        if match is None:
            return

        if match.view == "rendered":
            expected_view = self._markdown_view
            target = self._markdown_view._text_browser
        else:
            expected_view = self._source_view
            target = self._source_view._text_edit

        if self._content_stack.currentWidget() is not expected_view:
            self._search_status.setText("请切换回对应视图以跳转")
            return

        if match.end > len(target.toPlainText()):
            self._search_status.setText("搜索结果已过期，请重新搜索")
            return

        cursor = target.textCursor()
        cursor.setPosition(match.start)
        cursor.setPosition(match.end, QTextCursor.KeepAnchor)
        target.setTextCursor(cursor)
        target.ensureCursorVisible()

        if match.view == "rendered":
            target.setFocus()

    def _clear_search_results(self) -> None:
        """清空搜索模型、状态并隐藏加载更多按钮。"""
        if hasattr(self, "_search_model") and self._search_model is not None:
            self._search_model.clear()
        if hasattr(self, "_load_more_btn") and self._load_more_btn is not None:
            self._load_more_btn.hide()
        if hasattr(self, "_search_status") and self._search_status is not None:
            self._search_status.setText("")
        self._search_state = None

    def cleanup(self) -> None:
        """清理预览内容并重置为覆盖层。"""
        if hasattr(self, "_search_drawer") and self._search_drawer is not None:
            self._search_drawer.close_drawer()
        if hasattr(self, "_ai_drawer") and self._ai_drawer is not None:
            self._ai_drawer.close_drawer()
        self._clear_search_results()
        self._source_view._text_edit.clear()
        self._source_view.reset_scrollbars()
        self._markdown_view._text_browser.clear()
        self._markdown_view.reset_scrollbars()
        self._content_stack.setCurrentIndex(2)
        self._title_label.setText("文本预览")
        self._current_file = ""
        self._current_text = ""
        self._current_raw = None
        self._current_encoding = ""
        self._current_mode = "plain"
        self._highlighter = None
        self._render_toggle_btn.setVisible(False)
        if hasattr(self, "_encoding_combo") and self._encoding_combo is not None:
            self._encoding_combo.setCurrentIndex(0)

    def update_theme(self) -> None:
        """主题切换时刷新样式、高亮器和 Markdown 渲染颜色。"""
        self._apply_stylesheet()
        self._style_browse_button()
        self._source_view._vbar.update()
        self._source_view._hbar.update()

        if self._current_mode in ("code", "markdown") and self._current_text:
            self._apply_highlighter(language=self._get_language(self._current_file))

        if self._current_mode == "markdown" and MARKDOWN_AVAILABLE and self._current_text:
            self._render_markdown()

        # 刷新抽屉面板背景与 AI 占位文本颜色
        if hasattr(self, "_search_drawer") and self._search_drawer is not None:
            self._search_drawer._panel.setStyleSheet(
                f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
            )
        if hasattr(self, "_ai_drawer") and self._ai_drawer is not None:
            self._ai_drawer._panel.setStyleSheet(
                f"#DrawerPanel {{ background-color: {tm.surface.name()}; border: none; }}"
            )
            self._ai_placeholder.setStyleSheet(
                f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
                " padding: 24px;"
            )

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式（主题切换时由主窗口调用）。"""
        self._top_bar.setStyleSheet("border-radius: 8px;")
        self._content_area.setStyleSheet(f"""
            background-color: {tm.surface.name()};
            border: 1px solid transparent;
            border-radius: 8px;
        """)
        self._overlay.setStyleSheet(f"""
            background-color: {tm.surface.name()};
        """)

    # ── 内部辅助 ────────────────────────────────────────────────────────────

    def _detect_view_mode(self, file_path: str) -> str:
        """根据文件后缀判断视图模式。

        Returns:
            "markdown" | "code" | "plain"
        """
        ext = Path(file_path).suffix.lower()
        if ext in MARKDOWN_EXTENSIONS:
            return "markdown"
        if ext in CODE_EXTENSIONS:
            return "code"
        return "plain"

    def _get_language(self, file_path: str) -> str:
        """获取文件路径对应的语法高亮语言标识。"""
        ext = Path(file_path).suffix.lower()
        return CODE_EXTENSIONS.get(ext, "text")

    def _apply_highlighter(self, language: Optional[str] = None) -> None:
        """为源码视图应用语法高亮器（按需创建）。"""
        if not language or language == "text":
            self._highlighter = None
            return
        self._highlighter = _TextHighlighter(
            self._source_view._text_edit.document(),
            file_path=self._current_file,
            language=language,
            dark_mode=tm.is_dark_theme(),
        )

    def _render_markdown(self) -> bool:
        """使用 _MarkdownRenderer 渲染当前文本到 QTextBrowser。

        Returns:
            渲染成功时返回 True，Markdown 不可用或渲染失败时返回 False。
        """
        if not MARKDOWN_AVAILABLE or self._markdown_renderer is None:
            return False
        self._markdown_view._text_browser.clear()
        try:
            html = self._markdown_renderer.render(
                self._current_text, self._current_file
            )
            self._markdown_view._text_browser.setHtml(html)
        except Exception:
            # 渲染失败时回退到源码视图，避免崩溃
            self._content_stack.setCurrentIndex(0)
            return False

        # 设置搜索路径，使 Markdown 中的相对图片/链接可解析
        if self._current_file:
            base_dir = str(Path(self._current_file).parent)
            self._markdown_view._text_browser.setSearchPaths([base_dir])

        self._markdown_view.set_current_file(self._current_file)

        return True


    def _apply_stylesheet(self) -> None:
        """应用标题和 Markdown 视图的主题样式。"""
        text_color = tm.text.name()

        self._title_label.setStyleSheet(
            f"""
            color: {text_color};
            font-size: 13px;
            font-weight: 500;
            background: transparent;
            padding-left: 8px;
            padding-right: 8px;
        """
        )
        self._markdown_view._text_browser.setStyleSheet(
            f"""
            QTextBrowser#TextPreviewerMarkdownView {{
                background-color: {tm.surface.name()};
                color: {text_color};
                border: none;
                border-radius: 0px;
            }}
        """
        )
        self._source_view._text_edit.setStyleSheet(
            f"""
            QTextEdit#TextPreviewerSourceEdit {{
                background: transparent;
                color: {text_color};
                border: none;
                padding: 16px;
                font-family: "Fira Code", Consolas, monospace;
            }}
        """
        )

    def _apply_font_size(self) -> None:
        """将当前字号应用到源码视图和 Markdown 视图。"""
        family = self._global_font.family()
        source_font = QFont(family, self._font_size)
        self._source_view._text_edit.setFont(source_font)
        self._source_view.update_wheel_step_scale()

        md_font = QFont("Microsoft YaHei UI", self._font_size)
        self._markdown_view._text_browser.setFont(md_font)

        if self._markdown_renderer is not None:
            self._markdown_renderer.set_font_size(self._font_size)
            if self._current_mode == "markdown":
                self._render_markdown()

    def _style_browse_button(self) -> None:
        """应用主题色到"选择文本文件"按钮（与 PDF / 图片预览器一致）。"""
        if self._browse_btn is None:
            return
        btn_text = tm.mid.name()
        btn_hover_text = tm.text.name()
        btn_bg = tm.fill.name()
        btn_border = tm.alpha_of(tm.mid, 30).name()
        self._browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {btn_border};
                border-radius: 8px;
                color: {btn_text};
                font-size: 13px;
                font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: {btn_bg};
                color: {btn_hover_text};
                border: 1px solid {tm.mid.name()};
            }}
            QPushButton:pressed {{
                background: {btn_bg};
            }}
        """)

    # ── 事件槽 ───────────────────────────────────────────────────────────────

    def _on_zoom_clicked(self) -> None:
        """缩放按钮点击：展开/收起字号缩放弹窗。"""
        if self._zoom_popup is not None and self._zoom_popup.isVisible():
            self._zoom_popup.close_animated()
            return
        if self._zoom_popup is None:
            self._zoom_popup = _ZoomPopup(parent=self)
        self._zoom_popup.sync_from_parent()
        tb_br = self._top_bar.mapToGlobal(QPoint(self._top_bar.width(), self._top_bar.height()))
        self._zoom_popup.show_animated(tb_br)

    def _apply_font_size_from_zoom(self, font_size: int) -> None:
        """由缩放弹窗驱动，设置新的源码/渲染字号。"""
        self._font_size = max(
            self.FONT_SIZE_MIN, min(self.FONT_SIZE_MAX, int(font_size))
        )
        self._apply_font_size()

    def _on_browse_file(self) -> None:
        """独立模式下打开文件选择对话框（仅文本文件）。"""
        filters = "文本文件 (*.txt *.log *.csv *.md *.markdown *.rst *.json *.xml *.html *.css *.js *.ts *.py *.cpp *.c *.h *.java *.cs *.go *.rs);;所有文件 (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择文本文件", "", filters
        )
        if file_path:
            self.set_file(file_path)

    def _on_word_wrap_toggle(self) -> None:
        """切换源码视图自动换行。"""
        self._word_wrap = not self._word_wrap
        mode = (
            QTextEdit.WidgetWidth
            if self._word_wrap
            else QTextEdit.NoWrap
        )
        self._source_view._text_edit.setLineWrapMode(mode)
        self._source_view._sync_from_internal()
        self._wrap_btn.setText("换行" if self._word_wrap else "不换行")

    def _on_render_toggle(self) -> None:
        """在源码与渲染视图之间切换（仅 Markdown 模式）。"""
        self._clear_search_results()
        if self._content_stack.currentIndex() == 0:
            # 当前是源码视图，切换到渲染视图
            if self._render_markdown():
                self._content_stack.setCurrentIndex(1)
                self._render_toggle_btn.setText("源码")
        else:
            # 当前是渲染视图，切换回源码视图
            self._apply_highlighter(language=self._get_language(self._current_file))
            self._content_stack.setCurrentIndex(0)
            self._render_toggle_btn.setText("渲染")

    def _on_maxsize_toggle(self) -> None:
        """切换全屏 / 还原窗口（参考其他 previewer_layout 的现有实现）。"""
        win = self.window()
        if win is None:
            return
        if not self._fullscreen:
            self._saved_geometry = win.geometry()
            win.showFullScreen()
            self._maxsize_btn.set_svg_icon(self._minisize_icon_path)
            self._maxsize_btn.setToolTip("还原")
            self._fullscreen = True
        else:
            win.showNormal()
            if self._saved_geometry:
                win.setGeometry(self._saved_geometry)
            self._maxsize_btn.set_svg_icon(self._maxsize_icon_path)
            self._maxsize_btn.setToolTip("最大化")
            self._fullscreen = False

    def resizeEvent(self, event) -> None:
        """窗口尺寸变化时同步更新左右侧边栏的遮罩和面板尺寸。"""
        super().resizeEvent(event)
        for drawer_attr in ("_search_drawer", "_ai_drawer"):
            drawer = getattr(self, drawer_attr, None)
            if drawer is not None and drawer._is_open:
                drawer._update_container_geom()
                cw, ch = drawer._cw, drawer._ch
                drawer.setGeometry(0, 0, cw, ch)
                drawer._backdrop.setGeometry(0, 0, cw, ch)
                pw, _ = drawer._get_panel_size()
                drawer._panel.resize(pw, ch)
                if drawer._orientation == "right":
                    drawer._panel.move(cw - pw, 0)
                else:
                    drawer._panel.move(0, 0)

    def eventFilter(self, obj: Any, event: QEvent) -> bool:
        """应用级事件过滤：缩放弹窗在窗口移动/缩放或点击外部时关闭；
        渲染切换按钮显隐变化时重新排列顶栏按钮。
        """
        if event.type() in (QEvent.Move, QEvent.Resize):
            if obj is self.window() or obj is self:
                if self._zoom_popup is not None and self._zoom_popup.isVisible():
                    self._zoom_popup.close_animated()
        if event.type() == QEvent.MouseButtonPress:
            me = event if isinstance(event, QMouseEvent) else None
            if me is not None and self._zoom_popup is not None and self._zoom_popup.isVisible():
                click_global = me.globalPosition().toPoint()
                pr = QRect(self._zoom_popup.pos(), self._zoom_popup.size())
                if not pr.contains(click_global):
                    self._zoom_popup.close_animated()
        if obj is self._render_toggle_btn and event.type() in (QEvent.Show, QEvent.Hide):
            self._top_bar._layout_buttons()
        return super().eventFilter(obj, event)

    def _connect_theme(self) -> None:
        """连接主题切换信号。"""
        tm.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新样式。"""
        self.update_theme()
        self._style_browse_button()
        self._top_bar.update()


# ──────────────────────────────────────────────────────────────────────────────
# 独立测试入口
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = QWidget()
    window.setWindowTitle("文本预览器 (独立测试)")
    window.resize(960, 600)

    # 居中显示
    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    previewer = TextPreviewerLayout(standalone=True)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(previewer)

    # 独立窗口下主动应用面板圆角背景样式
    mid = tm.mid
    txt = tm.text
    fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
    border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"
    previewer.set_section_styles(fill_color, border_color)

    if len(sys.argv) > 1:
        previewer.set_file(sys.argv[1])

    window.show()

    # 在 offscreen 平台下自动退出，方便 CI / 冒烟测试
    if app.platformName().lower() == "offscreen":
        def _exit_offscreen() -> None:
            window.close()
            app.quit()
        QTimer.singleShot(300, _exit_offscreen)

    sys.exit(app.exec())
