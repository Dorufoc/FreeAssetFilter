"""
压缩包预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）

对齐旧版压缩包浏览器（freeassetfilter/components/archive_browser.py）的用户功能面：
- 列出压缩包内当前目录的文件与子目录（目录优先、图标 + 名称单列列表）
- 双击目录进入下一级；鼠标侧键（XButton1）与顶栏按钮返回上一级
- 单击选中 / 点击空白取消选中
- 文件名编码仅自动检测（7z 层"乱码 → GBK 重试"回退）；仍含替换符时
  在列表顶部展示不可选警示条

差异与改进：
- 目录列表在工作线程中异步读取（旧版在主线程整包同步重扫，大包会卡 UI）
- 视觉与交互基于新版 styled 组件体系（tm 主题、StyledScrollBar、自绘 delegate）
- 空目录 / 加载中 / 未选择状态均有占位提示

后续增强方案（解压、包内预览、加密、排序、搜索等）见
docs/压缩包预览器功能设计.md。
"""

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

from components.styled_button import StyledButton
from components.styled_dialog import ask_custom_dialog
from components.styled_lineedit import StyledLineEdit
from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from theme import tm

from freeassetfilter.core._paths import icons_dir
from freeassetfilter.core.native.bridges.py7z_core import get_7z_core
from freeassetfilter.services.file_icon_manager import FileIconManager
from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollArea,
    StyledScrollBar,
)
from freeassetfilter.utils.app_logger import error, info, warning

# 注：后台列表读取走 QThreadPool 全局池（QRunnable 用完即弃），面板仅持有
# 在途任务引用防 GC，无模块级保活集合。


# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

_ROW_HEIGHT: int = 32
_ICON_SIZE: int = 18
_TEXT_LEFT: int = 12  # 图标/文字距行左缘
_ICON_TEXT_GAP: int = 10  # 图标与文件名间距
_ROW_RADIUS: int = 6  # hover / 选中圆角背景

_PLACEHOLDER_NO_ARCHIVE: str = "选择压缩包文件开始预览"
_PLACEHOLDER_LOADING: str = "正在读取压缩包内容…"
_PLACEHOLDER_ROOT_EMPTY: str = "压缩包内无内容或无法读取"
_PLACEHOLDER_DIR_EMPTY: str = "此目录为空"

_WARNING_TEXT: str = "无法解析部分文件名：已自动尝试常用编码仍失败，部分名称可能不完整"
_WARNING_MARKER: str = "\ufffd"  # Unicode 替换符（解码失败标记）


def _contains_replacement(text: str) -> bool:
    """判断文本中是否含解码替换符（\ufffd）。"""
    return _WARNING_MARKER in text


def _show_custom_dialog(
    title: str,
    message: str,
    buttons: list,
    variants: Optional[list] = None,
    dialog_type: str = "default",
) -> None:
    """同步提示弹窗（委托公共同步助手 ``styled_dialog.ask_custom_dialog``）。

    压缩包预览器内的提示只关心展示，不关心返回值；统一不显示右上角
    关闭按钮。
    """
    ask_custom_dialog(
        title=title,
        message=message,
        buttons=list(buttons),
        variants=list(variants) if variants else None,
        dialog_type=dialog_type,
        show_close=False,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 条目模型
# ──────────────────────────────────────────────────────────────────────────────

class _ArchiveListModel(QAbstractListModel):
    """压缩包条目列表模型（只读）。

    行数据为 dict：{"kind": "dir"|"file"|"warning", "entry": dict|None}。
    警示行固定插在首位，不可选不可交互。
    """

    KindRole = Qt.ItemDataRole.UserRole + 1
    EntryRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []

    # ── Qt 模型接口 ────────────────────────────────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if row["kind"] == "warning":
                return _WARNING_TEXT
            entry = row.get("entry") or {}
            return entry.get("name", "")
        if role == self.KindRole:
            return row["kind"]
        if role == self.EntryRole:
            return row.get("entry")
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        flags = super().flags(index)
        row = self._rows[index.row()]
        if row["kind"] == "warning":
            flags &= ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled
        return flags

    # ── 数据装载 ────────────────────────────────────────────────────────

    def set_entries(self, entries: list) -> None:
        """以目录条目列表重建模型；含替换符时自动在顶部插入警示行。

        Args:
            entries: py7z list_archive 返回的条目 dict 列表。
        """
        has_encoding_error = any(
            _contains_replacement(entry.get("name") or "") for entry in entries
        )
        self.beginResetModel()
        rows: list[dict] = []
        if has_encoding_error:
            rows.append({"kind": "warning", "entry": None})
        for entry in entries:
            name = entry.get("name", "")
            if not name:
                continue
            kind = "dir" if entry.get("is_dir") else "file"
            rows.append({"kind": kind, "entry": entry})
        self._rows = rows
        self.endResetModel()

    def clear(self) -> None:
        """清空模型。"""
        if not self._rows:
            return
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def has_entries(self) -> bool:
        """是否存在条目（不含警示行）。"""
        return any(row["kind"] != "warning" for row in self._rows)

    def entry_at(self, row: int) -> Optional[dict]:
        """返回指定行的条目数据。"""
        if 0 <= row < len(self._rows):
            entry = self._rows[row].get("entry")
            if entry:
                return entry
        return None

    def kind_at(self, row: int) -> str:
        """返回指定行的类型（dir/file/warning）。"""
        if 0 <= row < len(self._rows):
            return self._rows[row].get("kind", "file")
        return "file"


# ──────────────────────────────────────────────────────────────────────────────
# 条目绘制委托
# ──────────────────────────────────────────────────────────────────────────────

class _ArchiveEntryDelegate(QStyledItemDelegate):
    """压缩包条目委托：自绘 hover / 选中圆角背景、图标与文件名。

    图标经 FileIconManager 获取（主题化 SVG + 缓存，与新版左栏文件选择器同源）。
    """

    def __init__(
        self,
        list_view: QListView,
        icon_manager: FileIconManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._list_view = list_view
        self._icon_manager = icon_manager
        self._icon_size: int = _ICON_SIZE
        # 主题/字号变化时按需重新取图标
        tm.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme_name: str) -> None:
        self._list_view.viewport().update()

    def _fetch_icon(self, entry: dict) -> object:
        """获取条目图标 pixmap（可能为空）。"""
        if not entry:
            return None
        try:
            pixmap = self._icon_manager.get_icon_pixmap(
                entry,
                self._icon_size,
                self._list_view.devicePixelRatioF(),
            )
            if pixmap is not None and not pixmap.isNull():
                return pixmap
        except Exception:
            pass
        return None

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: U100
        return QSize(0, _ROW_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """绘制单行条目。"""
        kind: str = index.data(_ArchiveListModel.KindRole) or "file"
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # ── 背景（hover / 选中圆角胶囊） ───────────────────────────────
        if is_selected:
            bg = tm.alpha_of(tm.accent, 35)
            border = tm.alpha_of(tm.accent, 90)
        elif is_hovered and kind != "warning":
            bg = tm.alpha_of(tm.text, 8)
            border = tm.transparent
        else:
            bg = tm.transparent
            border = tm.transparent

        if bg.alpha() > 0:
            bg_rect = QRectF(
                rect.left() + 4,
                rect.top() + 2,
                rect.width() - 8,
                rect.height() - 4,
            )
            path = QPainterPath()
            path.addRoundedRect(bg_rect, _ROW_RADIUS, _ROW_RADIUS)
            painter.setPen(QPen(border, 1.0))
            painter.setBrush(bg)
            painter.drawPath(path)

        # ── 警示行：仅红色文字，无图标 ────────────────────────────────
        if kind == "warning":
            painter.setPen(tm.danger)
            painter.setFont(QFont(option.font))
            fm = painter.fontMetrics()
            elided = fm.elidedText(
                _WARNING_TEXT,
                Qt.ElideRight,
                max(0, rect.width() - _TEXT_LEFT * 2),
            )
            baseline = int(
                rect.top() + (rect.height() - fm.height()) / 2 + fm.ascent()
            )
            painter.drawText(
                rect.left() + _TEXT_LEFT, baseline, elided
            )
            painter.restore()
            return

        # ── 图标 ───────────────────────────────────────────────────────
        entry = index.data(_ArchiveListModel.EntryRole) or {}
        pixmap = self._fetch_icon(entry)
        text_left = rect.left() + _TEXT_LEFT
        if pixmap is not None:
            pw = pixmap.width() / pixmap.devicePixelRatio()
            ph = pixmap.height() / pixmap.devicePixelRatio()
            pix_x = int(rect.left() + _TEXT_LEFT)
            pix_y = int(rect.top() + (rect.height() - ph) / 2)
            painter.drawPixmap(pix_x, pix_y, pixmap)
            text_left = pix_x + int(pw) + _ICON_TEXT_GAP

        # ── 文件名 ─────────────────────────────────────────────────────
        painter.setPen(tm.text)
        painter.setFont(QFont(option.font))
        fm = painter.fontMetrics()
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        avail_w = max(0, rect.right() - _TEXT_LEFT - text_left)
        elided = fm.elidedText(name, Qt.ElideRight, avail_w)
        baseline = int(
            rect.top() + (rect.height() - fm.height()) / 2 + fm.ascent()
        )
        painter.drawText(text_left, baseline, elided)

        painter.restore()

    def helpEvent(
        self,
        event: Any,
        view: QAbstractItemView,
        option: QStyleOptionViewItem,  # noqa: U100
        index: QModelIndex,
    ) -> bool:
        """警示行 / 超长名称行提供 tooltip 语义（透传默认行为即可）。"""
        return super().helpEvent(event, view, option, index)


# ──────────────────────────────────────────────────────────────────────────────
# 条目列表视图
# ──────────────────────────────────────────────────────────────────────────────

class _ArchiveListView(QListView):
    """压缩包条目列表视图。

    行为对齐旧版 ArchiveBrowser：
    - 单击条目选中，点击空白处取消全部选中
    - 鼠标侧键（XButton1，后退键）返回上一级
    - 仅左键双击目录进入；Enter 激活目录同理
    """

    back_requested = Signal()  # 请求返回上一级（鼠标侧键）
    dir_activated = Signal(str)  # 请求进入指定子目录（名称）

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBar(StyledScrollBar(orientation=Qt.Vertical))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        StyledScrollArea.apply_to(self)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet(
            "QListView { background: transparent; border: none; outline: none; }"
            "QListView::item { background: transparent; border: none; }"
        )

    def _index_kind(self, index: QModelIndex) -> str:
        return index.data(_ArchiveListModel.KindRole) or "file"

    def _index_entry(self, index: QModelIndex) -> Optional[dict]:
        return index.data(_ArchiveListModel.EntryRole)

    def _handle_mouse_press_select(self, pos: Any) -> None:
        """处理按下点选：空白处取消选中（含警示行不可选中）。"""
        index = self.indexAt(pos)
        if index.isValid() and self._index_kind(index) != "warning":
            self.setCurrentIndex(index)
        else:
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """鼠标按下：侧键返回 / 空白取消选中。"""
        if event.button() == Qt.XButton1:
            self.back_requested.emit()
            event.accept()
            return
        self._handle_mouse_press_select(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """仅响应左键双击：目录进入 / 文件无动作。"""
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and self._index_kind(index) == "dir":
                entry = self._index_entry(index) or {}
                name = entry.get("name", "")
                if name:
                    self.dir_activated.emit(name)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# 列表读取工作线程
# ──────────────────────────────────────────────────────────────────────────────

class _ArchiveListSignals(QObject):
    """压缩包列表读取完成信号中转（主线程持有 relay，跨线程队列投递）。"""

    list_finished = Signal(int, list)  # (token, entries)
    list_failed = Signal(int, str)  # (token, error_message)


class _ArchiveListWorker(QRunnable):
    """后台读取压缩包目录列表的池任务（每次导航新建，令牌守卫防覆盖）。

    ``run()`` 在 ``QThreadPool.globalInstance()`` 的池线程中执行；
    ``list_finished`` / ``list_failed`` 信号挂在 ``_ArchiveListSignals``
    中转对象上（以属性方式透出），调用方连接签名与旧 QThread 版一致。
    """

    def __init__(
        self,
        archive_path: str,
        current_path: str,
        token: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
        super().__init__()
        self.setAutoDelete(True)
        self._archive_path = archive_path
        self._current_path = current_path
        self._token = token
        self._signals = _ArchiveListSignals()

    @property
    def list_finished(self):
        """目录列表读取完成信号 ``(token, entries)``（经中转对象）。"""
        return self._signals.list_finished

    @property
    def list_failed(self):
        """目录列表读取失败信号 ``(token, error_message)``（经中转对象）。"""
        return self._signals.list_failed

    def start(self) -> None:
        """投递到全局线程池执行（替代旧 QThread.start()）。"""
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        try:
            core = get_7z_core()
            entries = core.list_archive(
                self._archive_path,
                current_path=self._current_path,
            )
            self._signals.list_finished.emit(self._token, list(entries or []))
        except Exception as exc:  # noqa: BLE001
            error(f"压缩包列表读取失败: {exc}")
            self._signals.list_failed.emit(self._token, str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# 压缩包预览器布局
# ──────────────────────────────────────────────────────────────────────────────

class ArchivePreviewerLayout(QWidget):
    """压缩包预览器布局（对应旧版 ArchiveBrowser 的新版实现）。

    顶栏固定 48px：返回按钮 + 只读路径显示；
    内容区 QStackedLayout 切换条目列表与占位/加载覆盖层。

    Signals:
        close_requested: 关闭预览请求信号（宿主规范占位）
    """

    close_requested = Signal()

    # 内容区页面索引
    _PAGE_LIST = 0
    _PAGE_OVERLAY = 1

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
        self._global_font = global_font or QFont("Microsoft YaHei UI", 10)
        self._settings_manager = settings_manager
        self._standalone = standalone

        # 状态
        self._archive_path: str = ""
        self._current_path: str = ""
        self._token: int = 0
        self._loading: bool = False
        self._load_worker: Optional[_ArchiveListWorker] = None

        self._icon_manager = FileIconManager()

        self._init_ui()
        self._connect_theme()
        self._apply_section_styles()

    # ── UI 初始化 ─────────────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        """初始化顶栏（路径行）+ 内容区布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶栏：返回按钮 + 只读路径（48px，透明背景）
        self._top_bar = QFrame()
        self._top_bar.setObjectName("ArchivePreviewerTopBar")
        self._top_bar.setFixedHeight(48)
        self._top_bar.setStyleSheet("background-color: transparent; border: none;")
        top_layout = QHBoxLayout(self._top_bar)
        top_layout.setContentsMargins(12, 0, 12, 0)
        top_layout.setSpacing(8)

        back_icon = str(icons_dir() / "unto.svg")
        self._back_btn = StyledButton(
            "", variant="ghost", size="sm", icon=back_icon
        )
        self._back_btn.setFixedSize(32, 32)
        self._back_btn.setToolTip("返回上一级目录")
        self._back_btn.clicked.connect(self.go_to_parent)
        top_layout.addWidget(self._back_btn)

        self._path_edit = StyledLineEdit(size="sm")
        self._path_edit.setReadOnly(True)
        self._path_edit.setText(_PLACEHOLDER_NO_ARCHIVE)
        self._path_edit.setToolTip("当前浏览路径")
        top_layout.addWidget(self._path_edit, stretch=1)

        # standalone 模式：右侧提供"打开压缩包"入口
        if self._standalone:
            self._open_btn = StyledButton("打开压缩包…", variant="secondary", size="sm")
            self._open_btn.setFixedHeight(30)
            self._open_btn.clicked.connect(self._on_browse_archive)
            top_layout.addWidget(self._open_btn)

        layout.addWidget(self._top_bar)

        # 内容区：index 0 = 条目列表；index 1 = 占位/加载覆盖层
        self._content_area = QFrame()
        self._content_area.setObjectName("ArchivePreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)
        self._content_stack.setSpacing(0)

        self._model = _ArchiveListModel(self)
        self._view = _ArchiveListView(self._content_area)
        self._view.setModel(self._model)
        self._view.setItemDelegate(
            _ArchiveEntryDelegate(self._view, self._icon_manager, self._view)
        )
        self._view.back_requested.connect(self.go_to_parent)
        self._view.dir_activated.connect(self._enter_dir)
        self._view.activated.connect(self._on_view_activated)
        self._content_stack.addWidget(self._view)

        self._overlay = QWidget()
        self._overlay.setObjectName("ArchivePreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        self._placeholder = QLabel(_PLACEHOLDER_NO_ARCHIVE)
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        )
        overlay_layout.addWidget(self._placeholder)

        # "选择压缩包"按钮（仅 standalone 模式显示在覆盖层中）
        self._overlay_open_btn: Optional[QPushButton] = None
        if self._standalone:
            self._overlay_open_btn = QPushButton("选择压缩包文件")
            self._overlay_open_btn.setFixedSize(160, 40)
            self._overlay_open_btn.setCursor(Qt.PointingHandCursor)
            self._overlay_open_btn.clicked.connect(self._on_browse_archive)
            self._style_browse_button()
            overlay_layout.addWidget(
                self._overlay_open_btn, alignment=Qt.AlignCenter
            )

        self._content_stack.addWidget(self._overlay)
        layout.addWidget(self._content_area, stretch=1)

        # 初始状态
        self._show_overlay(_PLACEHOLDER_NO_ARCHIVE)

    # ── 公共 API（新版预览器宿主约定） ───────────────────────────────────────

    def set_file(self, file_path: str) -> None:
        """设置要预览的压缩包路径（总是从压缩包根目录开始浏览）。

        Args:
            file_path: 压缩包文件的完整路径。
        """
        self._current_path = ""
        if not file_path:
            self.cleanup()
            return
        if not Path(file_path).is_file():
            self.cleanup()
            warning(f"无效的压缩包路径: {file_path}")
            _show_custom_dialog(
                "无法预览压缩包",
                f"无效的压缩包路径：{file_path}",
                ["知道了"],
                ["primary"],
                dialog_type="danger",
            )
            return
        self._archive_path = file_path
        self._refresh()

    def cleanup(self) -> None:
        """清理当前浏览状态（宿主切换/清除预览时调用）。"""
        self._token += 1
        self._loading = False
        self._load_worker = None
        self._archive_path = ""
        self._current_path = ""
        self._model.clear()
        self._view.scrollToTop()
        self._path_edit.setText(_PLACEHOLDER_NO_ARCHIVE)
        self._back_btn.setEnabled(False)
        self._show_overlay(_PLACEHOLDER_NO_ARCHIVE)
        info("压缩包预览器已清理")

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式（主题切换时由主窗口调用）。"""
        self._apply_section_styles()

    def update_theme(self) -> None:
        """主题切换时刷新静态样式并重绘列表。"""
        self._apply_section_styles()
        self._style_browse_button()
        # 图标颜色随主题着色：清缓存后重绘使新配色生效
        try:
            self._icon_manager.clear_cache()
        except Exception:
            pass
        self._view.viewport().update()

    # ── 主题 ─────────────────────────────────────────────────────────────────

    def _connect_theme(self) -> None:
        """连接主题切换信号。"""
        tm.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新样式。"""
        self.update_theme()

    def _apply_section_styles(self) -> None:
        """内容区与覆盖层透明（面板底色由宿主 PreviewerTop 承载）。"""
        self._content_area.setStyleSheet(
            "background-color: transparent;"
            "border: 1px solid transparent;"
            "border-radius: 8px;"
        )
        self._overlay.setStyleSheet("background-color: transparent;")
        self._placeholder.setStyleSheet(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        )
        for _w in (self._content_area, self._overlay):
            _w.style().unpolish(_w)
            _w.style().polish(_w)

    # ── 占位 / 覆盖层 ────────────────────────────────────────────────────────

    def _show_overlay(self, text: str) -> None:
        """显示覆盖层（占位 / 加载中 / 空态）。"""
        self._placeholder.setText(text)
        self._content_stack.setCurrentIndex(self._PAGE_OVERLAY)

    def _show_list(self) -> None:
        """切换到条目列表页。"""
        self._content_stack.setCurrentIndex(self._PAGE_LIST)

    # ── 状态刷新 ─────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """按当前（archive_path, current_path）异步重新读取目录列表。"""
        if not self._archive_path:
            return
        self._update_path_edit()
        self._loading = True
        self._token += 1
        token = self._token
        self._show_overlay(_PLACEHOLDER_LOADING)

        worker = _ArchiveListWorker(self._archive_path, self._current_path, token)
        self._load_worker = worker
        worker.list_finished.connect(self._on_list_finished)
        worker.list_failed.connect(self._on_list_failed)
        worker.start()
        info(
            f"读取压缩包目录: {self._archive_path} "
            f"[{self._current_path or '/'}]"
        )

    def _update_path_edit(self) -> None:
        """更新路径显示与返回按钮可用状态。"""
        base = Path(self._archive_path).name if self._archive_path else ""
        display = base if base else _PLACEHOLDER_NO_ARCHIVE
        if self._current_path:
            display = f"{display}/{self._current_path}"
        self._path_edit.setText(display)
        self._back_btn.setEnabled(bool(self._current_path))

    def _on_view_activated(self, index: QModelIndex) -> None:
        """视图激活（键盘 Enter / 鼠标）：目录进入。"""
        if self._loading or not index.isValid():
            return
        if index.data(_ArchiveListModel.KindRole) != "dir":
            return
        entry = index.data(_ArchiveListModel.EntryRole) or {}
        name = entry.get("name", "")
        if name and "/" not in name:
            self._enter_dir(name)

    def _on_list_finished(self, token: int, entries: list) -> None:
        """工作线程读取完成（令牌守卫防过期结果覆盖）。"""
        if token != self._token or not self._archive_path:
            return
        self._loading = False
        self._load_worker = None
        self._model.set_entries(entries)
        self._view.scrollToTop()
        self._view.clearSelection()

        if self._model.has_entries():
            self._show_list()
        else:
            if self._current_path:
                self._show_overlay(_PLACEHOLDER_DIR_EMPTY)
            else:
                self._show_overlay(_PLACEHOLDER_ROOT_EMPTY)
        self._update_path_edit()

    def _on_list_failed(self, token: int, message: str) -> None:
        """工作线程读取失败。"""
        if token != self._token or not self._archive_path:
            return
        self._loading = False
        self._load_worker = None
        self._model.clear()
        if self._current_path:
            self._show_overlay(_PLACEHOLDER_DIR_EMPTY)
        else:
            self._show_overlay(_PLACEHOLDER_ROOT_EMPTY)
        error(f"读取压缩包失败: {message}")
        _show_custom_dialog(
            "读取压缩包失败",
            f"无法读取压缩包内容：{message}",
            ["知道了"],
            ["primary"],
            dialog_type="danger",
        )

    # ── 导航 ─────────────────────────────────────────────────────────────────

    def go_to_parent(self) -> None:
        """返回上一级目录（无上级或加载中为空操作）。"""
        if self._loading or not self._current_path:
            return
        if "/" in self._current_path:
            self._current_path = self._current_path.rsplit("/", 1)[0]
        else:
            self._current_path = ""
        self._refresh()

    def _enter_dir(self, name: str) -> None:
        """进入指定子目录（仅当它是当前列表中的目录项）。"""
        if self._loading or not name or "/" in name:
            return
        if not self._is_dir_entry(name):
            return
        if self._current_path:
            self._current_path = f"{self._current_path}/{name}"
        else:
            self._current_path = name
        self._refresh()

    def _is_dir_entry(self, name: str) -> bool:
        """name 是否为当前列表中的目录项（警示行/文件不算）。"""
        for row in range(self._model.rowCount()):
            if self._model.kind_at(row) != "dir":
                continue
            entry = self._model.entry_at(row) or {}
            if entry.get("name") == name:
                return True
        return False

    # ── standalone 辅助 ──────────────────────────────────────────────────────

    def _style_browse_button(self) -> None:
        """刷新 standalone 模式覆盖层打开按钮样式。"""
        if self._overlay_open_btn is None:
            return
        self._overlay_open_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {tm.alpha_of(tm.surface, 85).name()};
                color: {tm.text.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 6px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.accent, 20).name()};
                border-color: {tm.accent.name()};
            }}
            """
        )

    def _on_browse_archive(self) -> None:
        """standalone 模式：文件对话框选择压缩包。"""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择压缩包文件",
            "",
            "压缩包文件 (*.zip *.rar *.7z *.tar *.gz *.tgz *.bz2 *.xz *.iso);;"
            "所有文件 (*.*)",
        )
        if path:
            self.set_file(path)


# ──────────────────────────────────────────────────────────────────────────────
# 独立测试入口
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)

    _default_font = QFont("Microsoft YaHei", 10, QFont.Normal)
    app.setFont(_default_font)
    app.global_font = QFont(_default_font)
    app.default_font_size = 10

    window = QWidget()
    window.setWindowTitle("压缩包预览器 (独立测试)")
    window.resize(960, 600)

    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    previewer = ArchivePreviewerLayout(standalone=True)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(previewer)

    if len(sys.argv) > 1:
        previewer.set_file(sys.argv[1])

    window.show()

    if app.platformName().lower() == "offscreen":

        def _exit_offscreen() -> None:
            window.close()
            app.quit()

        QTimer.singleShot(300, _exit_offscreen)

    sys.exit(app.exec())
