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

已实现增强（review 3.3）：
- 解压：选中项/全部解压到目标文件夹（-aou 同名自动改名、不覆盖、
  可取消；完成后汇总成功与失败数）；
- 加密：列表需要密码时弹输入框（仅内存缓存、按压缩包路径记忆），
  解压与搜索透传密码；
- 排序：名称/大小/修改时间/类型，升/降序（目录优先固定）；
- 搜索：按关键词在整个压缩包内递归查找（结果显示完整相对路径，
  双击目录可直接跳转）。

明确不计划：应用内「包内文件预览」（双击文件保持无动作）。
"""

import sys
import threading
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
from components.styled_context_menu import StyledContextMenu
from components.styled_dialog import ask_custom_dialog, create_input_dialog
from components.styled_lineedit import StyledLineEdit
from components.styled_loading import StyledLoading
from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QEventLoop,
    QModelIndex,
    QObject,
    QPoint,
    QRectF,
    QRunnable,
    QSize,
    Qt,
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
    QLineEdit,
    QListView,
    QProgressDialog,
    QPushButton,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from freeassetfilter.core import pools as thread_pools
from theme import tm

from freeassetfilter.core._paths import icons_dir
from freeassetfilter.core.native.bridges.py7z_core import get_7z_core
from freeassetfilter.services.file_icon_manager import FileIconManager
from freeassetfilter.ui.components.styled_scroll_area import (
    StyledScrollArea,
    StyledScrollBar,
)
from freeassetfilter.utils.app_logger import debug, error, info, warning
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

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
_PLACEHOLDER_SEARCHING: str = "正在搜索压缩包…"
_PLACEHOLDER_ROOT_EMPTY: str = "压缩包内无内容或无法读取"
_PLACEHOLDER_DIR_EMPTY: str = "此目录为空"
_PLACEHOLDER_PASSWORD_REQUIRED: str = "需要密码才能浏览此压缩包"
_PLACEHOLDER_SEARCH_EMPTY: str = "未找到匹配的文件"

#: 搜索输入防抖时长（毫秒）
_SEARCH_DEBOUNCE_MS: int = 250

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
) -> int:
    """同步提示/确认弹窗（委托 ``styled_dialog.ask_custom_dialog``）。

    Returns:
        int: 被点击按钮的索引（0-based）；关闭路径兜底返回 0。
    """
    return ask_custom_dialog(
        title=title,
        message=message,
        buttons=list(buttons),
        variants=list(variants) if variants else None,
        dialog_type=dialog_type,
        show_close=False,
    )


def _ask_password(title: str, message: str) -> Optional[str]:
    """密码输入对话框（StyledDialog 输入框 + 密码回显）。

    Args:
        title: 对话框标题。
        message: 说明文字。

    Returns:
        Optional[str]: 用户输入的密码；取消/空输入返回 ``None``。
    """
    dialog = create_input_dialog(
        title=title,
        message=message,
        placeholder="输入密码…",
        cancel_text="取消",
        confirm_text="确定",
        show_close=False,
    )
    field = getattr(dialog, "_input_field", None)
    if field is not None:
        field.setEchoMode(QLineEdit.Password)
        field.setFocus()
    result: dict = {"value": None}
    loop = QEventLoop()

    def _on_finished(idx: int) -> None:
        if idx == 1 and field is not None:
            result["value"] = field.text()
        loop.quit()

    dialog.finished.connect(_on_finished)
    dialog.destroyed.connect(loop.quit)
    loop.exec()
    value = result["value"]
    return value if value else None


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

    #: 排序键与展示名（目录优先固定，仅对两组内部排序）
    SORT_KEYS: tuple = (("name", "名称"), ("size", "大小"),
                        ("modified", "修改时间"), ("type", "类型"))

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._entries: list[dict] = []
        self._has_warning: bool = False
        self._sort_key: str = "name"
        self._sort_desc: bool = False

    @property
    def sort_key(self) -> str:
        """当前排序键。"""
        return self._sort_key

    @property
    def sort_desc(self) -> bool:
        """是否降序。"""
        return self._sort_desc

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
            # 搜索结果带 display（完整相对路径），目录视图回退为文件名
            return entry.get("display") or entry.get("name", "")
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
        self._entries = [
            dict(entry) for entry in entries if entry.get("name")
        ]
        self._has_warning = any(
            _contains_replacement(entry.get("name") or "")
            for entry in self._entries
        )
        self._rebuild_rows()

    def set_sort(self, key: str, desc: bool) -> None:
        """更新排序键/方向并重建行（目录优先固定，不触发重扫）。

        Args:
            key: 排序键（name/size/modified/type）；非法值回退 name。
            desc: True 降序。
        """
        key = key if key in {k for k, _ in self.SORT_KEYS} else "name"
        desc = bool(desc)
        if (key, desc) == (self._sort_key, self._sort_desc):
            return
        self._sort_key = key
        self._sort_desc = desc
        self._rebuild_rows()

    def _entry_sort_value(self, entry: dict) -> Any:
        """按当前排序键取条目排序值（同键类型一致）。"""
        if self._sort_key == "size":
            try:
                return int(entry.get("size", 0) or 0)
            except (TypeError, ValueError):
                return 0
        if self._sort_key == "modified":
            return str(entry.get("modified", "") or "")
        if self._sort_key == "type":
            return str(entry.get("suffix", "") or "").lower()
        return str(entry.get("name", "") or "").lower()

    def _sorted_entries(self) -> list:
        """按当前排序返回条目（目录组恒在前，两组内部各自排序）。"""
        dirs = [e for e in self._entries if e.get("is_dir")]
        files = [e for e in self._entries if not e.get("is_dir")]
        dirs.sort(key=self._entry_sort_value, reverse=self._sort_desc)
        files.sort(key=self._entry_sort_value, reverse=self._sort_desc)
        return dirs + files

    def _rebuild_rows(self) -> None:
        """按当前排序重建行（含可选警示行）。"""
        self.beginResetModel()
        rows: list[dict] = []
        if self._has_warning:
            rows.append({"kind": "warning", "entry": None})
        for entry in self._sorted_entries():
            kind = "dir" if entry.get("is_dir") else "file"
            rows.append({"kind": kind, "entry": entry})
        self._rows = rows
        self.endResetModel()

    def clear(self) -> None:
        """清空模型。"""
        self._entries = []
        self._has_warning = False
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
        except Exception as exc:
            debug(f"压缩包条目图标生成失败（回退占位）：{exc}")
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
            bg = tm.alpha_of(tm.mid if tm.is_dark_theme() else tm.text, 25)
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
    dir_entry_activated = Signal(dict)  # 请求进入搜索结果中的目录（完整条目）

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 多选：支持 Ctrl/Shift 选中多个条目（解压选中项用）
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
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

    def _handle_mouse_press_select(self, pos: Any) -> None:
        """按下点选：空白处/警示行取消选中（测试与内部共用入口）。"""
        index = self.indexAt(pos)
        if not index.isValid() or self._index_kind(index) == "warning":
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """鼠标按下：侧键返回 / 空白或警示行取消选中 / 其余走 Qt 多选语义。"""
        if event.button() == Qt.XButton1:
            self.back_requested.emit()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if not index.isValid() or self._index_kind(index) == "warning":
                self._handle_mouse_press_select(event.position().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """仅响应左键双击：目录进入 / 文件无动作。

        搜索结果的目录条目带 ``display``（完整相对路径），经
        ``dir_entry_activated`` 交由宿主按路径跳转。
        """
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and self._index_kind(index) == "dir":
                entry = self._index_entry(index) or {}
                if entry.get("display"):
                    self.dir_entry_activated.emit(entry)
                    event.accept()
                    return
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

    list_finished = Signal(int, list, str, str)  # (token, entries, status, message)
    list_failed = Signal(int, str)  # (token, error_message)


class _ArchiveListWorker(QRunnable):
    """后台读取压缩包目录列表的池任务（每次导航新建，令牌守卫防覆盖）。

    ``list_finished`` 携带 py7z 状态（ok/password_required/password_invalid/
    error），加密流程据此弹密码框；异常经 ``list_failed`` 上报。
    """

    def __init__(
        self,
        archive_path: str,
        current_path: str,
        token: int,
        password: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        # parent 参数仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
        super().__init__()
        self.setAutoDelete(True)
        self._archive_path = archive_path
        self._current_path = current_path
        self._token = token
        self._password = password
        self._signals = _ArchiveListSignals()

    @property
    def list_finished(self):
        """列表读取完成信号 ``(token, entries, status, message)``（经中转对象）。"""
        return self._signals.list_finished

    @property
    def list_failed(self):
        """目录列表读取失败信号 ``(token, error_message)``（经中转对象）。"""
        return self._signals.list_failed

    def start(self) -> None:
        """投递到全局线程池执行（替代旧 QThread.start()）。"""
        thread_pools.pool("interactive").start(self)

    def run(self) -> None:
        try:
            core = get_7z_core()
            entries, status, message = core.list_archive_with_status(
                self._archive_path,
                current_path=self._current_path,
                password=self._password,
            )
            self._signals.list_finished.emit(
                self._token, list(entries or []), status, message
            )
        except Exception as exc:  # noqa: BLE001
            error(f"压缩包列表读取失败: {exc}")
            self._signals.list_failed.emit(self._token, str(exc))


class _ArchiveSearchSignals(QObject):
    """压缩包全包搜索完成信号中转。"""

    search_finished = Signal(int, str, list)  # (token, keyword, entries)
    search_failed = Signal(int, str)  # (token, error_message)


class _ArchiveSearchWorker(QRunnable):
    """后台全包搜索任务（递归过滤完整相对路径，令牌守卫防覆盖）。"""

    def __init__(
        self,
        archive_path: str,
        keyword: str,
        token: int,
        password: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._archive_path = archive_path
        self._keyword = keyword
        self._token = token
        self._password = password
        self._signals = _ArchiveSearchSignals()

    @property
    def search_finished(self):
        """搜索完成信号 ``(token, keyword, entries)``。"""
        return self._signals.search_finished

    @property
    def search_failed(self):
        """搜索失败信号 ``(token, error_message)``。"""
        return self._signals.search_failed

    def start(self) -> None:
        """投递到全局线程池执行。"""
        thread_pools.pool("interactive").start(self)

    def run(self) -> None:
        try:
            core = get_7z_core()
            entries = core.search_archive(
                self._archive_path,
                self._keyword,
                password=self._password,
            )
            self._signals.search_finished.emit(
                self._token, self._keyword, list(entries or [])
            )
        except Exception as exc:  # noqa: BLE001
            error(f"压缩包搜索失败: {exc}")
            self._signals.search_failed.emit(self._token, str(exc))


class _ArchiveExtractSignals(QObject):
    """压缩包解压完成信号中转。"""

    extract_finished = Signal(dict)  # result dict


class _ArchiveExtractWorker(QRunnable):
    """后台解压任务（协作式取消：cancel_event 置位后 kill 7z 进程）。"""

    def __init__(
        self,
        archive_path: str,
        output_dir: str,
        entries: Optional[list],
        password: Optional[str],
        cancel_event: threading.Event,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._archive_path = archive_path
        self._output_dir = output_dir
        self._entries = list(entries) if entries else None
        self._password = password
        self._cancel_event = cancel_event
        self._signals = _ArchiveExtractSignals()

    @property
    def extract_finished(self):
        """解压完成信号 ``(result_dict)``。"""
        return self._signals.extract_finished

    def start(self) -> None:
        """投递到全局线程池执行。"""
        thread_pools.pool("interactive").start(self)

    def run(self) -> None:
        try:
            core = get_7z_core()
            result = core.extract_archive(
                self._archive_path,
                self._output_dir,
                entries=self._entries,
                password=self._password,
                should_stop=self._cancel_event.is_set,
            )
            result["output_dir"] = self._output_dir
            self._signals.extract_finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            error(f"解压失败: {exc}")
            self._signals.extract_finished.emit({
                "success": 0,
                "failed": 1,
                "errors": [str(exc)],
                "cancelled": False,
                "output_dir": self._output_dir,
            })


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
        # 加密：按压缩包路径仅内存缓存密码（set_file 换包/cleanup 清空）
        self._passwords: dict = {}
        # 搜索：模式开关、关键词、目录列表缓存（退出搜索时无重扫恢复）
        self._search_mode: bool = False
        self._search_keyword: str = ""
        self._search_token: int = 0
        self._search_worker: Optional[_ArchiveSearchWorker] = None
        self._dir_entries_cache: list = []
        # 解压：在途 worker 与取消事件
        self._extract_worker: Optional[_ArchiveExtractWorker] = None
        self._extract_cancel_event: Optional[threading.Event] = None
        self._extract_progress: Optional[QProgressDialog] = None

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
        self._path_edit.setText(_PLACEHOLDER_NO_ARCHIVE)
        self._path_edit.setToolTip("当前浏览路径")
        top_layout.addWidget(self._path_edit, stretch=1)

        # 搜索输入（默认隐藏；搜索按钮把路径框位置切换为搜索框）
        self._search_edit = StyledLineEdit(size="sm")
        self._search_edit.setPlaceholderText("搜索压缩包内文件…")
        self._search_edit.setToolTip("按文件名搜索（整个压缩包）")
        self._search_edit.installEventFilter(self)
        self._search_edit.textChanged.connect(self._on_search_text_changed)
        self._search_edit.hide()
        top_layout.addWidget(self._search_edit, stretch=1)

        # 搜索防抖定时器：输入静止后才发起全包搜索
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._flush_search)

        # 搜索切换按钮
        search_icon = str(icons_dir() / "search.svg")
        self._search_btn = StyledButton(
            "", variant="ghost", size="sm", icon=search_icon
        )
        self._search_btn.setFixedSize(32, 32)
        self._search_btn.setToolTip("搜索压缩包内文件")
        self._search_btn.clicked.connect(self._toggle_search)
        top_layout.addWidget(self._search_btn)

        # 排序按钮（弹出排序菜单）
        self._sort_btn = StyledButton("排序", variant="ghost", size="sm")
        self._sort_btn.setFixedHeight(30)
        self._sort_btn.setToolTip("排序方式")
        self._sort_btn.clicked.connect(self._on_sort_clicked)
        top_layout.addWidget(self._sort_btn)

        # 解压按钮（有选中项→选中；无→全部）
        self._extract_btn = StyledButton("解压", variant="secondary", size="sm")
        self._extract_btn.setFixedHeight(30)
        self._extract_btn.setToolTip("解压选中项或全部文件")
        self._extract_btn.clicked.connect(self._on_extract_clicked)
        top_layout.addWidget(self._extract_btn)

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
        self._view.dir_entry_activated.connect(self._enter_search_dir)
        self._view.activated.connect(self._on_view_activated)
        self._content_stack.addWidget(self._view)

        self._overlay = QWidget()
        self._overlay.setObjectName("ArchivePreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 加载圆环（仅读取/搜索等进行中状态显示）
        self._loading_spinner = StyledLoading(size="lg")
        self._loading_spinner.setVisible(False)
        overlay_layout.addWidget(self._loading_spinner, 0, Qt.AlignCenter)

        self._placeholder = QLabel(_PLACEHOLDER_NO_ARCHIVE)
        self._placeholder.setAlignment(Qt.AlignCenter)
        register_widget_qss(self._placeholder,(
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 14px; background: transparent;"
        ))
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
        if file_path != self._archive_path:
            # 换包：清空密码缓存与搜索态（同一预览器会被宿主复用）
            self._passwords.clear()
            self._reset_search_ui()
        self._archive_path = file_path
        self._refresh()

    def unified_action_host(self):
        """统一操作按钮宿主：返回本预览器顶栏（New 布局注入用）。"""
        return self._top_bar

    def cleanup(self) -> None:
        """清理当前浏览状态（宿主切换/清除预览时调用）。"""
        self._token += 1
        self._loading = False
        self._load_worker = None
        # 在途解压：请求取消（结果槽自行兜底，不再弹进度框）
        if self._extract_cancel_event is not None:
            self._extract_cancel_event.set()
        self._extract_cancel_event = None
        self._archive_path = ""
        self._current_path = ""
        self._passwords.clear()
        self._search_debounce.stop()
        self._search_token += 1
        self._search_worker = None
        self._reset_search_ui()
        self._dir_entries_cache = []
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
        except Exception as exc:
            debug(f"图标缓存清理失败：{exc}")
        self._view.viewport().update()

    # ── 主题 ─────────────────────────────────────────────────────────────────

    def _connect_theme(self) -> None:
        """连接主题切换信号（明暗与强调色分别经由两个信号下发）。"""
        tm.theme_changed.connect(self._on_theme_changed)
        tm.colors_updated.connect(self._on_theme_changed)

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
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 14px; background: transparent;"
        ))
        for _w in (self._content_area, self._overlay):
            _w.style().unpolish(_w)
            _w.style().polish(_w)

    # ── 占位 / 覆盖层 ────────────────────────────────────────────────────────

    def _show_overlay(self, text: str, busy: bool = False) -> None:
        """显示覆盖层（占位 / 加载中 / 空态）。

        Args:
            text: 提示文本。
            busy: True 时显示加载圆环（读取/搜索进行中）；False 时仅显示
                文本（占位/空态/密码/错误）。
        """
        self._placeholder.setText(text)
        self._loading_spinner.setVisible(bool(busy))
        self._content_stack.setCurrentIndex(self._PAGE_OVERLAY)

    def _show_list(self) -> None:
        """切换到条目列表页（隐藏加载圆环）。"""
        self._loading_spinner.setVisible(False)
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
        self._show_overlay(_PLACEHOLDER_LOADING, busy=True)

        worker = _ArchiveListWorker(
            self._archive_path,
            self._current_path,
            token,
            password=self._passwords.get(self._archive_path),
        )
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
        """视图激活（键盘 Enter / 鼠标）：目录进入（搜索结果按完整路径）。"""
        if self._loading or not index.isValid():
            return
        if index.data(_ArchiveListModel.KindRole) != "dir":
            return
        entry = index.data(_ArchiveListModel.EntryRole) or {}
        if entry.get("display"):
            self._enter_search_dir(entry)
            return
        name = entry.get("name", "")
        if name and "/" not in name:
            self._enter_dir(name)

    def _on_list_finished(
        self, token: int, entries: list, status: str, message: str
    ) -> None:
        """工作线程读取完成（令牌守卫防过期结果覆盖）。

        加密压缩包（password_required / password_invalid）转入密码流程，
        不显示通用错误框。
        """
        if token != self._token or not self._archive_path:
            return
        self._loading = False
        self._load_worker = None
        if status in ("password_required", "password_invalid"):
            self._handle_password_status(status)
            return
        if status != "ok":
            self._on_list_failed(token, message or "无法读取压缩包内容")
            return
        self._dir_entries_cache = list(entries)
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

    def _handle_password_status(self, status: str) -> None:
        """加密压缩包：提示输入密码并重试；取消则显示需要密码占位。

        Args:
            status: ``"password_required"`` 或 ``"password_invalid"``。
        """
        archive_name = Path(self._archive_path).name
        if status == "password_invalid":
            self._passwords.pop(self._archive_path, None)
            title = "密码错误"
            prompt = f"「{archive_name}」密码错误，请重新输入。"
        else:
            title = "需要密码"
            prompt = f"「{archive_name}」已加密，请输入打开密码。"
        password = _ask_password(title, prompt)
        if password:
            self._passwords[self._archive_path] = password
            self._refresh()
            return
        self._model.clear()
        self._show_overlay(_PLACEHOLDER_PASSWORD_REQUIRED)
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
        """返回上一级目录（搜索结果态下先退出搜索；无上级或加载中为空操作）。"""
        if self._search_mode:
            self._exit_search_mode()
            return
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

    # ── 搜索 ────────────────────────────────────────────────────────────────

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        """搜索框 Esc：退出搜索并恢复目录视图。"""
        if obj is self._search_edit and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._exit_search_mode()
                return True
        return super().eventFilter(obj, event)

    def _toggle_search(self) -> None:
        """搜索按钮：在路径框与搜索框之间切换。"""
        if self._search_edit.isVisible():
            self._exit_search_mode()
            return
        self._path_edit.hide()
        self._search_edit.clear()
        self._search_edit.show()
        self._search_edit.setFocus()

    def _on_search_text_changed(self, text: str) -> None:
        """搜索输入变化：防抖后发起全包搜索。"""
        self._search_debounce.start()

    def _flush_search(self) -> None:
        """防抖到期：空关键词恢复目录视图，否则后台搜索。"""
        if not self._archive_path:
            return
        keyword = self._search_edit.text().strip()
        if not keyword:
            self._exit_search_mode()
            return
        self._search_token += 1
        token = self._search_token
        self._search_worker = _ArchiveSearchWorker(
            self._archive_path,
            keyword,
            token,
            password=self._passwords.get(self._archive_path),
        )
        self._search_worker.search_finished.connect(self._on_search_finished)
        self._search_worker.search_failed.connect(self._on_search_failed)
        self._show_overlay(_PLACEHOLDER_SEARCHING, busy=True)
        self._search_worker.start()

    def _on_search_finished(self, token: int, keyword: str, entries: list) -> None:
        """搜索完成：平铺显示结果（令牌守卫防过期覆盖）。"""
        if token != self._search_token or not self._archive_path:
            return
        self._search_worker = None
        if self._search_edit.text().strip() != keyword:
            return
        self._search_mode = True
        self._search_keyword = keyword
        self._model.set_entries(entries)
        self._view.scrollToTop()
        self._view.clearSelection()
        if self._model.has_entries():
            self._show_list()
        else:
            self._show_overlay(_PLACEHOLDER_SEARCH_EMPTY)

    def _on_search_failed(self, token: int, message: str) -> None:
        """搜索失败：恢复目录视图并提示。"""
        if token != self._search_token or not self._archive_path:
            return
        self._search_worker = None
        self._exit_search_mode()
        error(f"搜索压缩包失败: {message}")

    def _exit_search_mode(self) -> None:
        """退出搜索：恢复路径框与目录列表（用缓存，不重扫）。"""
        self._search_debounce.stop()
        self._search_token += 1
        self._search_mode = False
        self._search_keyword = ""
        self._search_edit.blockSignals(True)
        self._search_edit.clear()
        self._search_edit.blockSignals(False)
        self._search_edit.hide()
        self._path_edit.show()
        if not self._archive_path:
            return
        self._model.set_entries(self._dir_entries_cache)
        self._view.scrollToTop()
        self._view.clearSelection()
        if self._model.has_entries():
            self._show_list()
        else:
            if self._current_path:
                self._show_overlay(_PLACEHOLDER_DIR_EMPTY)
            else:
                self._show_overlay(_PLACEHOLDER_ROOT_EMPTY)

    def _reset_search_ui(self) -> None:
        """把搜索 UI 恢复到初始（隐藏搜索框、显示路径框）。"""
        self._search_debounce.stop()
        self._search_mode = False
        self._search_keyword = ""
        if hasattr(self, "_search_edit"):
            self._search_edit.blockSignals(True)
            self._search_edit.clear()
            self._search_edit.blockSignals(False)
            self._search_edit.hide()
        if hasattr(self, "_path_edit"):
            self._path_edit.show()

    def _enter_search_dir(self, entry: dict) -> None:
        """从搜索结果进入某个目录（完整相对路径），并退出搜索态。"""
        path = str(entry.get("path", "") or "")
        if not path:
            return
        self._current_path = path
        self._exit_search_mode()
        self._refresh()

    # ── 排序 ────────────────────────────────────────────────────────────────

    def _on_sort_clicked(self) -> None:
        """排序按钮：弹出排序菜单（键 + 升降序，当前项打勾）。"""
        menu = StyledContextMenu(parent=self)
        for key, label in _ArchiveListModel.SORT_KEYS:
            menu.add_item(
                label,
                checkable=True,
                checked=(self._model.sort_key == key),
                callback=lambda k=key: self._model.set_sort(
                    k, self._model.sort_desc
                ),
            )
        menu.add_separator()
        menu.add_item(
            "升序",
            checkable=True,
            checked=not self._model.sort_desc,
            callback=lambda: self._model.set_sort(self._model.sort_key, False),
        )
        menu.add_item(
            "降序",
            checkable=True,
            checked=self._model.sort_desc,
            callback=lambda: self._model.set_sort(self._model.sort_key, True),
        )
        menu.exec(
            self._sort_btn.mapToGlobal(QPoint(0, self._sort_btn.height()))
        )

    # ── 解压 ────────────────────────────────────────────────────────────────

    def _selected_entries(self) -> list:
        """当前选中条目的包内路径列表（无选中返回空列表）。"""
        model = self._view.selectionModel()
        if model is None:
            return []
        entries: list = []
        for index in model.selectedIndexes():
            entry = index.data(_ArchiveListModel.EntryRole)
            if isinstance(entry, dict) and entry.get("path"):
                entries.append(str(entry["path"]))
        return entries

    def _on_extract_clicked(self) -> None:
        """解压按钮：确认范围 → 选目标目录 → 后台解压（可取消）。"""
        if not self._archive_path or self._loading:
            return
        if not self._model.has_entries():
            _show_custom_dialog(
                "无可解压内容", "当前没有可解压的条目。",
                ["知道了"], ["primary"], dialog_type="info",
            )
            return
        selected = self._selected_entries()
        scope = f"选中的 {len(selected)} 项" if selected else "全部文件"

        password = self._passwords.get(self._archive_path)
        if password is None:
            # 头加密的包此时已被密码流程拦截；这里兜底 zip 类条目级加密
            try:
                if get_7z_core().is_encrypted(self._archive_path):
                    password = _ask_password(
                        "需要密码",
                        f"「{Path(self._archive_path).name}」已加密，"
                        "解压需要密码。",
                    )
                    if password is None:
                        return
                    self._passwords[self._archive_path] = password
            except Exception:  # noqa: BLE001 - 加密探测失败不阻塞解压尝试
                password = None

        choice = _show_custom_dialog(
            "解压",
            f"将{scope}解压到所选文件夹。\n\n"
            "同名文件会自动改名，不会覆盖已有文件。",
            ["选择目标文件夹…", "取消"],
            ["primary", "normal"],
        )
        if choice != 0:
            return
        target_dir = QFileDialog.getExistingDirectory(self, "选择解压目标文件夹")
        if not target_dir:
            return

        self._extract_cancel_event = threading.Event()
        self._extract_progress = QProgressDialog(
            "正在解压…", "取消", 0, 0, self
        )
        self._extract_progress.setWindowTitle("解压进度")
        self._extract_progress.setMinimumDuration(0)
        self._extract_progress.canceled.connect(self._on_extract_cancel)

        worker = _ArchiveExtractWorker(
            self._archive_path,
            target_dir,
            selected or None,
            password,
            self._extract_cancel_event,
        )
        self._extract_worker = worker
        worker.extract_finished.connect(self._on_extract_finished)
        worker.start()
        self._extract_progress.exec()

    def _on_extract_cancel(self) -> None:
        """进度框取消：置位取消事件（worker 轮询后 kill 7z）。"""
        if self._extract_cancel_event is not None:
            self._extract_cancel_event.set()

    def _on_extract_finished(self, result: dict) -> None:
        """解压完成：关闭进度框并汇总结果（成功/失败/取消）。"""
        self._extract_worker = None
        self._extract_cancel_event = None
        progress = self._extract_progress
        self._extract_progress = None
        if progress is not None:
            try:
                progress.close()
            except RuntimeError:
                pass
        if not self._archive_path:
            return
        if result.get("cancelled"):
            _show_custom_dialog(
                "解压已取消",
                "已取消解压。目标文件夹中可能残留部分已解压文件。",
                ["知道了"], ["primary"],
            )
            return
        success = int(result.get("success", 0) or 0)
        failed = int(result.get("failed", 0) or 0)
        errors = result.get("errors") or []
        output_dir = str(result.get("output_dir", "") or "")
        if failed or errors:
            detail = "\n".join(str(e) for e in errors)[:1500]
            message = f"成功 {success} 项，失败 {failed} 项。"
            if detail:
                message += f"\n\n{detail}"
            _show_custom_dialog(
                "解压完成（有错误）", message, ["知道了"], ["primary"],
                dialog_type="danger",
            )
            return
        _show_custom_dialog(
            "解压完成",
            f"成功解压 {success} 项到：\n{output_dir}",
            ["知道了"], ["primary"], dialog_type="success",
        )

    # ── standalone 辅助 ──────────────────────────────────────────────────────

    def _style_browse_button(self) -> None:
        """刷新 standalone 模式覆盖层打开按钮样式。"""
        if self._overlay_open_btn is None:
            return
        register_widget_qss(self._overlay_open_btn,(
            f"""
            QPushButton {{
                background-color: {tm.alpha_of(tm.surface, 85).name()};
                color: {tm.text.name()};
                border: 1px solid {tm.qss_color(tm.control_border)};
                border-radius: 6px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.accent, 20).name()};
                border-color: {tm.accent.name()};
            }}
            """
        ))

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
