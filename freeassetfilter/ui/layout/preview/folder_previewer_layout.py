"""
文件夹预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）

功能：
- 以单列列表（图标 + 名称）展示文件夹内容，目录优先、名称不区分大小写排序
- 双击 / Enter 进入子文件夹；顶栏返回按钮与鼠标侧键（XButton1）返回上级；
  以 set_file 传入的文件夹为根边界，不能越出根目录向上浏览
- 单击条目仅选中高亮，点击空白取消选中；双击文件无动作
- 每次进入 / 返回目录时在后台线程重新扫描（无手动刷新、无自动监听）

触发方式：文件夹被加入文件储存池后，左键点击文件池中的文件夹卡片时，
由统一预览器宿主路由到本组件；与文件选择器的常规文件夹导航相互独立。

后续增强方案（自动监听刷新、内层文件预览、信息面板联动等）见
docs/文件夹预览器功能设计.md。
"""

import os
import sys
from datetime import datetime
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
from freeassetfilter.services.file_icon_manager import FileIconManager
from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollArea,
    StyledScrollBar,
)
from freeassetfilter.utils.app_logger import info, warning
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

# 注：后台目录扫描走 QThreadPool 全局池（QRunnable 用完即弃），面板仅持有
# 在途任务引用防 GC，无模块级保活集合。


# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

_ROW_HEIGHT: int = 32
_ICON_SIZE: int = 18
_TEXT_LEFT: int = 12  # 图标/文字距行左缘
_ICON_TEXT_GAP: int = 10  # 图标与文件名间距
_ROW_RADIUS: int = 6  # hover / 选中圆角背景

_PLACEHOLDER_NO_FOLDER: str = "选择文件夹开始预览"
_PLACEHOLDER_LOADING: str = "正在读取文件夹内容…"
_PLACEHOLDER_EMPTY: str = "此目录为空"
_PLACEHOLDER_UNAVAILABLE: str = "无法访问该文件夹"


def _collect_directory_entries(path: str) -> Optional[list]:
    """纯 IO 收集目录条目（listdir + 逐文件 stat）。

    与文件选择器（file_selector_layout._collect_directory_entries）语义一致：
    - 条目字段同构（含后缀/大小/修改与创建时间），隐藏文件不过滤
    - 单项 stat 权限异常跳过，目录整体不可读时返回 None

    Args:
        path: 要扫描的目录绝对路径。

    Returns:
        条目 dict 列表；目录不可读/不存在时返回 None。
    """
    try:
        entries: list = []
        for name in os.listdir(path):
            full_path = os.path.join(path, name)
            try:
                st = os.stat(full_path)
                is_dir = os.path.isdir(full_path)
                suffix = (
                    os.path.splitext(name)[1].lower().lstrip(".")
                    if not is_dir
                    else ""
                )
                modified = datetime.fromtimestamp(st.st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                )
                created = datetime.fromtimestamp(st.st_ctime).strftime(
                    "%Y-%m-%d %H:%M"
                )
                entries.append(
                    {
                        "name": name,
                        "path": full_path,
                        "is_dir": is_dir,
                        "size": st.st_size,
                        "modified": modified,
                        "created": created,
                        "suffix": suffix,
                    }
                )
            except (PermissionError, OSError):
                continue
        return entries
    except (PermissionError, FileNotFoundError, OSError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 条目模型
# ──────────────────────────────────────────────────────────────────────────────

class _FolderListModel(QAbstractListModel):
    """文件夹条目列表模型（只读），行数据 kind = dir / file。"""

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
            entry = row.get("entry") or {}
            return entry.get("name", "")
        if role == self.KindRole:
            return row["kind"]
        if role == self.EntryRole:
            return row.get("entry")
        return None

    # ── 数据装载 ────────────────────────────────────────────────────────

    def set_entries(self, entries: list) -> None:
        """以目录条目重建模型（空白名条目跳过）。"""
        self.beginResetModel()
        rows: list[dict] = []
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

    def entry_at(self, row: int) -> Optional[dict]:
        """返回指定行的条目数据。"""
        if 0 <= row < len(self._rows):
            entry = self._rows[row].get("entry")
            if entry:
                return entry
        return None

    def kind_at(self, row: int) -> str:
        """返回指定行的类型（dir/file）。"""
        if 0 <= row < len(self._rows):
            return self._rows[row].get("kind", "file")
        return "file"


# ──────────────────────────────────────────────────────────────────────────────
# 条目绘制委托
# ──────────────────────────────────────────────────────────────────────────────

class _FolderEntryDelegate(QStyledItemDelegate):
    """文件夹条目委托：自绘 hover / 选中圆角背景、图标与文件名。

    图标经 FileIconManager 获取（与新版文件选择器/压缩包预览器同源）；
    条目为真实磁盘路径，图片/视频类型可直接命中缩略图。
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
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hovered = bool(option.state & QStyle.State_MouseOver)
        rect = option.rect

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # ── 背景（hover / 选中圆角胶囊） ───────────────────────────────
        if is_selected:
            bg = tm.alpha_of(tm.accent, 35)
            border = tm.alpha_of(tm.accent, 90)
        elif is_hovered:
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

        # ── 图标 ───────────────────────────────────────────────────────
        entry = index.data(_FolderListModel.EntryRole) or {}
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


# ──────────────────────────────────────────────────────────────────────────────
# 条目列表视图
# ──────────────────────────────────────────────────────────────────────────────

class _FolderListView(QListView):
    """文件夹条目列表视图。

    - 单击条目选中，点击空白处取消全部选中
    - 鼠标侧键（XButton1，后退键）返回上一级
    - 仅左键双击 / Enter 激活目录条目进入
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
        register_widget_qss(self,(
            "QListView { background: transparent; border: none; outline: none; }"
            "QListView::item { background: transparent; border: none; }"
        ))

    def _index_kind(self, index: QModelIndex) -> str:
        return index.data(_FolderListModel.KindRole) or "file"

    def _index_entry(self, index: QModelIndex) -> Optional[dict]:
        return index.data(_FolderListModel.EntryRole)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """鼠标按下：侧键返回 / 单击条目选中 / 空白取消选中。"""
        if event.button() == Qt.XButton1:
            self.back_requested.emit()
            event.accept()
            return
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self.setCurrentIndex(index)
        else:
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())
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
# 目录扫描工作线程
# ──────────────────────────────────────────────────────────────────────────────

class _FolderScanSignals(QObject):
    """目录扫描完成信号中转（主线程持有 relay，跨线程队列投递）。"""

    scan_finished = Signal(int, list)  # (token, entries)
    scan_failed = Signal(int)  # (token)


class _FolderScanWorker(QRunnable):
    """后台扫描磁盘目录的池任务（每次导航新建，令牌守卫防覆盖）。

    ``run()`` 在 ``QThreadPool.globalInstance()`` 的池线程中执行；
    ``scan_finished`` / ``scan_failed`` 信号挂在 ``_FolderScanSignals``
    中转对象上（以属性方式透出），调用方连接签名与旧 QThread 版一致。
    """

    def __init__(
        self,
        directory_path: str,
        token: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
        super().__init__()
        self.setAutoDelete(True)
        self._directory_path = directory_path
        self._token = token
        self._signals = _FolderScanSignals()

    @property
    def scan_finished(self):
        """目录扫描完成信号 ``(token, entries)``（经中转对象）。"""
        return self._signals.scan_finished

    @property
    def scan_failed(self):
        """目录扫描失败信号 ``(token)``（经中转对象）。"""
        return self._signals.scan_failed

    def start(self) -> None:
        """投递到全局线程池执行（替代旧 QThread.start()）。"""
        QThreadPool.globalInstance().start(self)

    def run(self) -> None:
        entries = _collect_directory_entries(self._directory_path)
        if entries is None:
            self._signals.scan_failed.emit(self._token)
            return
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        self._signals.scan_finished.emit(self._token, entries)


# ──────────────────────────────────────────────────────────────────────────────
# 文件夹预览器布局
# ──────────────────────────────────────────────────────────────────────────────

class FolderPreviewerLayout(QWidget):
    """文件夹预览器布局（新版，配合文件池文件夹卡片预览使用）。

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

        # 状态：根文件夹（set_file 传入）与当前浏览到的相对路径
        self._root_path: str = ""
        self._current_rel: str = ""
        self._token: int = 0
        self._loading: bool = False
        self._scan_worker: Optional[_FolderScanWorker] = None

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
        self._top_bar.setObjectName("FolderPreviewerTopBar")
        self._top_bar.setFixedHeight(48)
        register_widget_qss(self._top_bar,("background-color: transparent; border: none;"))
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
        self._path_edit.setText(_PLACEHOLDER_NO_FOLDER)
        self._path_edit.setToolTip("当前浏览路径")
        top_layout.addWidget(self._path_edit, stretch=1)

        # standalone 模式：右侧提供"选择文件夹"入口
        if self._standalone:
            self._open_btn = StyledButton("选择文件夹…", variant="secondary", size="sm")
            self._open_btn.setFixedHeight(30)
            self._open_btn.clicked.connect(self._on_browse_folder)
            top_layout.addWidget(self._open_btn)

        layout.addWidget(self._top_bar)

        # 内容区：index 0 = 条目列表；index 1 = 占位/加载覆盖层
        self._content_area = QFrame()
        self._content_area.setObjectName("FolderPreviewerContent")
        self._content_stack = QStackedLayout(self._content_area)
        self._content_stack.setContentsMargins(0, 0, 0, 0)
        self._content_stack.setSpacing(0)

        self._model = _FolderListModel(self)
        self._view = _FolderListView(self._content_area)
        self._view.setModel(self._model)
        self._view.setItemDelegate(
            _FolderEntryDelegate(self._view, self._icon_manager, self._view)
        )
        self._view.back_requested.connect(self.go_to_parent)
        self._view.dir_activated.connect(self._enter_dir)
        self._view.activated.connect(self._on_view_activated)
        self._content_stack.addWidget(self._view)

        self._overlay = QWidget()
        self._overlay.setObjectName("FolderPreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        self._placeholder = QLabel(_PLACEHOLDER_NO_FOLDER)
        self._placeholder.setAlignment(Qt.AlignCenter)
        register_widget_qss(self._placeholder,(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        ))
        overlay_layout.addWidget(self._placeholder)

        # "选择文件夹"按钮（仅 standalone 模式显示在覆盖层中）
        self._overlay_open_btn: Optional[QPushButton] = None
        if self._standalone:
            self._overlay_open_btn = QPushButton("选择文件夹")
            self._overlay_open_btn.setFixedSize(160, 40)
            self._overlay_open_btn.setCursor(Qt.PointingHandCursor)
            self._overlay_open_btn.clicked.connect(self._on_browse_folder)
            self._style_browse_button()
            overlay_layout.addWidget(
                self._overlay_open_btn, alignment=Qt.AlignCenter
            )

        self._content_stack.addWidget(self._overlay)
        layout.addWidget(self._content_area, stretch=1)

        # 初始状态
        self._show_overlay(_PLACEHOLDER_NO_FOLDER)

    # ── 公共 API（新版预览器宿主约定） ───────────────────────────────────────

    def set_file(self, file_path: str) -> None:
        """设置要预览的文件夹路径（总是从该文件夹开始浏览）。

        Args:
            file_path: 文件夹的完整路径。
        """
        self._current_rel = ""
        if not file_path or not os.path.isdir(file_path):
            self.cleanup()
            return
        self._root_path = file_path
        self._refresh()

    def cleanup(self) -> None:
        """清理当前浏览状态（宿主切换/清除预览时调用）。"""
        self._token += 1
        self._loading = False
        self._scan_worker = None
        self._root_path = ""
        self._current_rel = ""
        self._model.clear()
        self._view.scrollToTop()
        self._path_edit.setText(_PLACEHOLDER_NO_FOLDER)
        self._back_btn.setEnabled(False)
        self._show_overlay(_PLACEHOLDER_NO_FOLDER)
        info("文件夹预览器已清理")

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
        register_widget_qss(self._content_area,(
            "background-color: transparent;"
            "border: 1px solid transparent;"
            "border-radius: 8px;"
        ))
        register_widget_qss(self._overlay,("background-color: transparent;"))
        register_widget_qss(self._placeholder,(
            f"color: {tm.mid.name()}; font-size: 14px; background: transparent;"
        ))
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

    def _current_directory(self) -> str:
        """当前浏览目录的真实绝对路径。"""
        if self._current_rel:
            return os.path.join(self._root_path, *self._current_rel.split("/"))
        return self._root_path

    def _refresh(self) -> None:
        """按当前浏览目录异步重新扫描（每次进入/返回都会触发）。"""
        if not self._root_path:
            return
        self._update_path_edit()
        self._loading = True
        self._token += 1
        token = self._token
        self._show_overlay(_PLACEHOLDER_LOADING)

        worker = _FolderScanWorker(self._current_directory(), token)
        self._scan_worker = worker
        worker.scan_finished.connect(self._on_scan_finished)
        worker.scan_failed.connect(self._on_scan_failed)
        worker.start()
        info(f"读取文件夹内容: {self._current_directory()}")

    def _update_path_edit(self) -> None:
        """更新路径显示与返回按钮可用状态。"""
        if self._current_rel:
            display = os.path.join(self._root_path, *self._current_rel.split("/"))
        else:
            display = self._root_path if self._root_path else _PLACEHOLDER_NO_FOLDER
        self._path_edit.setText(display.replace("\\", "/"))
        self._back_btn.setEnabled(bool(self._current_rel))

    def _on_scan_finished(self, token: int, entries: list) -> None:
        """工作线程扫描完成（令牌守卫防过期结果覆盖）。"""
        if token != self._token or not self._root_path:
            return
        self._loading = False
        self._scan_worker = None
        self._model.set_entries(entries)
        self._view.scrollToTop()
        self._view.clearSelection()

        if self._model.rowCount() > 0:
            self._show_list()
        else:
            self._show_overlay(_PLACEHOLDER_EMPTY)
        self._update_path_edit()

    def _on_scan_failed(self, token: int) -> None:
        """工作线程扫描失败（目录不可读/已被删除）。"""
        if token != self._token or not self._root_path:
            return
        self._loading = False
        self._scan_worker = None
        self._model.clear()
        self._show_overlay(_PLACEHOLDER_UNAVAILABLE)
        self._update_path_edit()
        warning(f"无法访问文件夹: {self._current_directory()}")

    # ── 导航 ─────────────────────────────────────────────────────────────────

    def go_to_parent(self) -> None:
        """返回上一级目录（根目录或加载中为空操作，不越出根文件夹）。"""
        if self._loading or not self._current_rel:
            return
        if "/" in self._current_rel:
            self._current_rel = self._current_rel.rsplit("/", 1)[0]
        else:
            self._current_rel = ""
        self._refresh()

    def _enter_dir(self, name: str) -> None:
        """进入指定子目录（仅当它是当前列表中的目录项）。"""
        if self._loading or not name or "/" in name:
            return
        if not self._is_dir_entry(name):
            return
        if self._current_rel:
            self._current_rel = f"{self._current_rel}/{name}"
        else:
            self._current_rel = name
        self._refresh()

    def _is_dir_entry(self, name: str) -> bool:
        """name 是否为当前列表中的目录项（文件不算）。"""
        for row in range(self._model.rowCount()):
            if self._model.kind_at(row) != "dir":
                continue
            entry = self._model.entry_at(row) or {}
            if entry.get("name") == name:
                return True
        return False

    def _on_view_activated(self, index: QModelIndex) -> None:
        """视图激活（键盘 Enter / 鼠标）：目录进入。"""
        if self._loading or not index.isValid():
            return
        if index.data(_FolderListModel.KindRole) != "dir":
            return
        entry = index.data(_FolderListModel.EntryRole) or {}
        name = entry.get("name", "")
        if name and "/" not in name:
            self._enter_dir(name)

    # ── standalone 辅助 ──────────────────────────────────────────────────────

    def _style_browse_button(self) -> None:
        """刷新 standalone 模式覆盖层选择按钮样式。"""
        if self._overlay_open_btn is None:
            return
        register_widget_qss(self._overlay_open_btn,(
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
        ))

    def _on_browse_folder(self) -> None:
        """standalone 模式：目录对话框选择文件夹。"""
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
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
    window.setWindowTitle("文件夹预览器 (独立测试)")
    window.resize(960, 600)

    screen = app.primaryScreen().geometry()
    x = (screen.width() - 960) // 2 + screen.x()
    y = (screen.height() - 600) // 2 + screen.y()
    window.move(x, y)

    previewer = FolderPreviewerLayout(standalone=True)
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
