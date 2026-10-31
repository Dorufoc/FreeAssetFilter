"""
文件夹预览器布局 — 顶栏（48px 固定高度）+ 内容区（自适应拉伸）

功能：
- 以单列列表（图标 + 名称）展示文件夹内容，目录优先、名称不区分大小写排序
- 双击 / Enter 进入子文件夹；顶栏返回按钮与鼠标侧键（XButton1）返回上级；
  以 set_file 传入的文件夹为根边界，不能越出根目录向上浏览
- 单击条目仅选中高亮，点击空白取消选中；双击文件无动作
- 每次进入 / 返回目录时在后台线程重新扫描
- **自动监听刷新**：QFileSystemWatcher 监听当前目录，外部增删改名后
  300ms 防抖重新扫描（网络盘等监听不生效场景自动降级，不影响手动导航）
- **信息面板联动**：选中条目发出 ``entry_selected`` 信号（宿主转发给
  主窗口的信息面板），取消选中发 None
- **隐藏/系统过滤**：按实例开关（``set_show_hidden_files`` /
  ``set_show_system_files``，由统一预览器宿主下发）过滤带
  FILE_ATTRIBUTE_HIDDEN / FILE_ATTRIBUTE_SYSTEM 属性的条目，语义与
  文件选择器一致（仅「系统」位的条目恒可见；「隐藏+系统」双重位才受
  系统开关控制）；默认关闭（不显示隐藏/双重位条目），变更后立即重扫

触发方式：文件夹被加入文件储存池后，左键点击文件池中的文件夹卡片时，
由统一预览器宿主路由到本组件；与文件选择器的常规文件夹导航相互独立。

明确不计划：应用内「内层文件预览」（双击文件打开预览）——双击文件保持
无动作；相关设计文档已不存在，不再引用。
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# 独立运行时的 sys.path 引导（在模块级导入前执行）
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent.parent)  # sopeek/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)
_project_root = str(_this_file.parent.parent.parent.parent.parent)  # 项目根
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from components.styled_button import StyledButton
from components.styled_lineedit import StyledLineEdit
from components.styled_loading import StyledLoading
from PySide6.QtCore import (
    QAbstractListModel,
    QFileSystemWatcher,
    QModelIndex,
    QObject,
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
    QListView,
    QPushButton,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from sopeek.core import pools as thread_pools
from theme import tm

from sopeek.core._paths import icons_dir
from sopeek.core.native import api as native_api
from sopeek.services.file_icon_manager import FileIconManager
from sopeek.ui.components.styled_scroll_area import (
    StyledScrollArea,
    StyledScrollBar,
)
from sopeek.utils.app_logger import debug, info, warning
from sopeek.ui.theme.app_stylesheet import register_widget_qss

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

# Windows 文件属性位（Win32 FILE_ATTRIBUTE_*，取自 stat 的 st_file_attributes）：
# 隐藏位与系统位。目录收集后按实例开关过滤，语义与文件选择器完全一致：
# 仅「系统」位单独出现（如重定向后的桌面/下载/音乐等系统文件夹）恒可见；
# 「隐藏+系统」双重位（受保护的操作系统文件）需两个开关同时开启。
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4


def _native_scan_directory(path: str) -> Optional[list]:
    """经 spk_core 桥扫描目录；桥不可用/失败返回 None（调用方回退 Python）。

    与文件选择器（file_selector_layout._native_scan_directory）同构：模块级
    helper，双 try/except 防御 FFI 边界（构造单例 + 实际调用），失败一律
    返回 None，不向调用方抛异常。

    Args:
        path: 要扫描的目录绝对路径。

    Returns:
        Optional[list]: 7 键条目字典列表；DLL 缺失、native 失败或超
            ``MAX_JSON_BYTES`` 上限时返回 ``None``。
    """
    return native_api.scan_directory(path)


def _collect_directory_entries(
    path: str,
    show_hidden: Optional[bool] = None,
    show_system: Optional[bool] = None,
) -> Optional[list]:
    """收集目录条目（native 优先，Python 回退），可选隐藏/系统过滤。

    单点接线：``_FolderScanWorker.run`` 的唯一扫描入口（后台线程可执行，
    不触碰 Qt/主线程状态）。spk_core 桥可用且 ``scan_directory`` 返回非
    None 时直接使用 native 结果；否则回退 :func:`_collect_directory_entries_python`
    的原实现。返回契约与改造前一致：条目 dict 列表（7 键同构）或目录不可读
    时返回 None。

    隐藏/系统过滤：``show_hidden`` 与 ``show_system`` 均为 ``None`` 时不做
    任何过滤（保持静态直调的 legacy 口径）；否则对 native 或 Python 回退
    收集到的条目统一套用 :func:`_apply_hidden_system_filter`（与文件选择器
    ``file_selector_layout`` 的同名过滤语义一致——只删条目不改变条目结构）。

    Args:
        path: 要扫描的目录绝对路径。
        show_hidden: 是否显示隐藏文件（FILE_ATTRIBUTE_HIDDEN）；``None``
            表示不启用过滤。仅「系统」位（FILE_ATTRIBUTE_SYSTEM 单独
            出现，如重定向后的桌面/下载/音乐等系统文件夹）恒可见。
        show_system: 是否显示系统文件（FILE_ATTRIBUTE_SYSTEM）；仅当
            ``show_hidden`` 亦为真时生效，且只影响同时带「隐藏+系统」
            双重位的受保护操作系统文件/文件夹。

    Returns:
        Optional[list]: 条目 dict 列表；目录不可读/不存在时返回 None。
    """
    native_entries = _native_scan_directory(path)
    # P1.3：仅在需要过滤时收集属性旁路表；native 路径不返回属性位，
    # 留 None 让 ``_apply_hidden_system_filter`` 自行 scandir。
    wants_filter = not (show_hidden is None and show_system is None)
    if native_entries is not None:
        entries = native_entries
        attrs_by_name: Optional[dict] = None
    else:
        attrs_by_name = {} if wants_filter else None
        entries = _collect_directory_entries_python(path, attrs_out=attrs_by_name)
    if entries is None:
        return None
    return _apply_hidden_system_filter(
        entries, path, show_hidden, show_system, attrs_by_name=attrs_by_name
    )


def _apply_hidden_system_filter(
    entries: list,
    path: str,
    show_hidden: Optional[bool],
    show_system: Optional[bool],
    attrs_by_name: Optional[dict] = None,
) -> list:
    """按隐藏/系统文件属性过滤条目（保持原顺序，只删不改）。

    与文件选择器（``file_selector_layout.FileSelectorLayout._apply_hidden_system_filter``）
    逐行同构：以 ``os.scandir`` 扫一遍目录建立 ``name -> st_file_attributes``
    映射（逐条目 stat 失败则跳过该条目；scandir 本身失败则 fail-open 原样
    返回）。无映射的条目（名称缺失）保持可见；``.`` 前缀不算隐藏（仅按
    属性位判定）。过滤口径对齐资源管理器：仅「隐藏」位随 ``show_hidden``；
    仅「系统」位（如重定向后的桌面/下载/音乐等系统文件夹）恒可见；
    「隐藏+系统」双重位（受保护的操作系统文件）需两个开关同时开启。

    P1.3：若调用方已在条目扫描时同步采集了属性（``attrs_by_name`` 非
    None），则**不再**重复 scandir。

    Args:
        entries: 待过滤的条目 dict 列表。
        path: 对应目录路径（仅在需要自行 scandir 时使用）。
        show_hidden: 是否显示隐藏文件；``None`` 表示不过滤。
        show_system: 是否显示系统文件；仅当 ``show_hidden`` 亦为真时生效。
        attrs_by_name: 可选旁路属性表（``name -> st_file_attributes``，
            ``follow_symlinks=False`` 口径）。

    Returns:
        list: 过滤后的条目列表。
    """
    if show_hidden is None and show_system is None:
        return entries
    show_hidden = bool(show_hidden)
    effective_system = bool(show_system) and show_hidden
    if show_hidden and effective_system:
        return entries
    if attrs_by_name is None:
        attrs_by_name = {}
        try:
            with os.scandir(path) as it:
                for dir_entry in it:
                    try:
                        st = dir_entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs_by_name[dir_entry.name] = getattr(
                        st, "st_file_attributes", 0
                    )
        except OSError:
            return entries
    result: list = []
    for entry in entries:
        attrs = attrs_by_name.get(entry["name"], 0)
        is_hidden = bool(attrs & _FILE_ATTRIBUTE_HIDDEN)
        is_system = bool(attrs & _FILE_ATTRIBUTE_SYSTEM)
        if is_hidden and not show_hidden:
            continue
        if is_hidden and is_system and not effective_system:
            continue
        result.append(entry)
    return result


def _collect_directory_entries_python(
    path: str,
    attrs_out: Optional[dict] = None,
) -> Optional[list]:
    """纯 IO 收集目录条目（scandir + 逐文件 stat），native 回退路径。

    与文件选择器（file_selector_layout._collect_directory_entries_python）
    语义一致：
    - 条目字段同构（含后缀/大小/修改与创建时间），隐藏文件不过滤
    - 单项 stat 权限异常跳过，目录整体不可读时返回 None

    P1.3：改用 ``os.scandir``（与文件选择器同构）以复用目录项缓存；
    传入 ``attrs_out`` 时同步采集 ``st_file_attributes``（``follow_symlinks=
    False`` 口径），避免额外的整目录枚举。

    Args:
        path: 要扫描的目录绝对路径。
        attrs_out: 可选旁路属性表；传入时写入
            ``name -> st_file_attributes``。

    Returns:
        条目 dict 列表；目录不可读/不存在时返回 None。
    """
    try:
        entries: list = []
        with os.scandir(path) as it:
            for dir_entry in it:
                try:
                    st = dir_entry.stat(follow_symlinks=True)
                    is_dir = dir_entry.is_dir(follow_symlinks=True)
                except (PermissionError, OSError):
                    continue
                name = dir_entry.name
                if attrs_out is not None:
                    try:
                        st_no_follow = dir_entry.stat(follow_symlinks=False)
                    except OSError:
                        st_no_follow = None
                    if st_no_follow is not None:
                        attrs_out[name] = getattr(
                            st_no_follow, "st_file_attributes", 0
                        )
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
                        "path": dir_entry.path,
                        "is_dir": is_dir,
                        "size": st.st_size,
                        "modified": modified,
                        "created": created,
                        "suffix": suffix,
                    }
                )
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
        """获取条目图标 pixmap（可能为空），并约束到列表行图标框。"""
        if not entry:
            return None
        try:
            pixmap = self._icon_manager.get_icon_pixmap(
                entry,
                self._icon_size,
                self._list_view.devicePixelRatioF(),
            )
            if pixmap is not None and not pixmap.isNull():
                return self._fit_icon_to_row(pixmap)
        except Exception as exc:
            debug(f"文件夹条目图标生成失败（回退占位）：{exc}")
        return None

    def _fit_icon_to_row(self, pixmap: object) -> object:
        """把图标/缩略图等比约束到列表行图标框（``_icon_size`` 逻辑像素）。

        ``FileIconManager.get_icon_pixmap`` 对「图片/视频且磁盘已有缩略图」
        的条目直接返回缩略图原始位图（BASE_SIZE=128 级，忽略 ``icon_size``
        请求），其余类型才精确渲染为 ``icon_size × icon_size``。若原样交给
        ``paint`` 按自然尺寸绘制，已有缩略图的行会画出远超 32px 行高的巨图，
        文字起点被一并顶开——即「已创建缩略图的图片比例异常」缺陷。

        本方法只做等比缩小、不放大：默认 SVG 图标（已 ≤ 图标框）原样返回，
        零额外开销；超框位图缩到 ``_icon_size × _icon_size`` 边界内并居中由
        ``paint`` 完成。缩放结果设置 DPR 后返回副本，不修改
        ``FileIconManager`` 缓存中共享的原图。

        Args:
            pixmap: ``get_icon_pixmap`` 返回的源 pixmap（非空）。

        Returns:
            object: 逻辑尺寸不超过图标框的 pixmap。
        """
        view_dpr = float(self._list_view.devicePixelRatioF() or 1.0)
        src_dpr = float(pixmap.devicePixelRatio() or 1.0)
        logical_w = pixmap.width() / src_dpr
        logical_h = pixmap.height() / src_dpr

        if logical_w <= self._icon_size and logical_h <= self._icon_size:
            return pixmap

        box_phys = max(1, int(round(self._icon_size * view_dpr)))
        fitted = pixmap.scaled(
            box_phys,
            box_phys,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        fitted.setDevicePixelRatio(view_dpr)
        return fitted

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

        # ── 图标：固定 _ICON_SIZE 图标框，位图在框内居中 ────────────────
        # 缩略图比例各异（横图/竖图/方图），若按各自宽度左对齐绘制，
        # 文字起点会随图片宽度漂移、行与行无法对齐；统一以图标框中心
        # 定位，文字起点只由图标框右缘 + 固定间距决定。
        entry = index.data(_FolderListModel.EntryRole) or {}
        pixmap = self._fetch_icon(entry)
        icon_left = rect.left() + _TEXT_LEFT
        icon_box = QRectF(
            icon_left,
            rect.top() + (rect.height() - _ICON_SIZE) / 2.0,
            _ICON_SIZE,
            _ICON_SIZE,
        )
        if pixmap is not None:
            pixmap_dpr = pixmap.devicePixelRatio() or 1.0
            pw = pixmap.width() / pixmap_dpr
            ph = pixmap.height() / pixmap_dpr
            pix_x = int(round(icon_box.center().x() - pw / 2.0))
            pix_y = int(round(icon_box.center().y() - ph / 2.0))
            painter.drawPixmap(pix_x, pix_y, pixmap)

        # 文字起点与图片宽高无关，恒为图标框右缘 + 固定间距
        text_left = int(round(icon_left + _ICON_SIZE + _ICON_TEXT_GAP))

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

    ``run()`` 在 ``thread_pools.pool("interactive")`` 的池线程中执行；
    ``scan_finished`` / ``scan_failed`` 信号挂在 ``_FolderScanSignals``
    中转对象上（以属性方式透出），调用方连接签名与旧 QThread 版一致。
    """

    def __init__(
        self,
        directory_path: str,
        token: int,
        parent: Optional[QWidget] = None,
        show_hidden: bool = False,
        show_system: bool = False,
    ) -> None:
        """初始化扫描任务。

        Args:
            directory_path: 要扫描的目录绝对路径。
            token: 异步加载世代快照，过期结果由槽侧丢弃。
            parent: 仅为兼容旧构造签名保留；QRunnable 非 QObject，不参与父子。
            show_hidden: 显示隐藏文件开关快照（UI 线程派发时捕获，
                避免后台线程读取可变实例状态）。
            show_system: 显示系统文件开关快照（UI 线程派发时捕获）。
        """
        super().__init__()
        self.setAutoDelete(True)
        self._directory_path = directory_path
        self._token = token
        self._show_hidden = bool(show_hidden)
        self._show_system = bool(show_system)
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
        thread_pools.pool("interactive").start(self)

    def run(self) -> None:
        entries = _collect_directory_entries(
            self._directory_path,
            show_hidden=self._show_hidden,
            show_system=self._show_system,
        )
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
        entry_selected: 选中条目变化（条目 dict；取消选中为 None），
            由统一预览器转发、主窗口联动文件信息面板
    """

    close_requested = Signal()
    # 条目选中变化：dict（真实磁盘路径信息）或 None（取消选中/清空）
    entry_selected = Signal(object)

    # 内容区页面索引
    _PAGE_LIST = 0
    _PAGE_OVERLAY = 1

    #: 目录监听防抖时长（毫秒）：外部批量操作合并为一次重扫
    WATCHER_DEBOUNCE_MS = 300

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
        # 显示隐藏文件开关（general.show_hidden_files，默认关闭；由统一
        # 预览器宿主随启动读取结果与设置提交下发，经 set_show_hidden_files 更新）
        self._show_hidden_files: bool = False
        # 显示系统文件开关（general.show_system_files，默认关闭；仅当隐藏
        # 文件开关亦开启时生效，经 set_show_system_files 下发）
        self._show_system_files: bool = False

        # 自动监听刷新：监视当前目录，变更后防抖重扫（addPath 失败静默降级）
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._watcher_debounce = QTimer(self)
        self._watcher_debounce.setSingleShot(True)
        self._watcher_debounce.setInterval(self.WATCHER_DEBOUNCE_MS)
        self._watcher_debounce.timeout.connect(self._on_refresh_debounce)
        # 最近一次对外发射的选中条目路径（去重，避免重复 set_file 信息面板）
        self._last_selected_path: Optional[str] = None

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
        self._view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self._content_stack.addWidget(self._view)

        self._overlay = QWidget()
        self._overlay.setObjectName("FolderPreviewerOverlay")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setSpacing(16)

        # 加载圆环（仅加载中显示；空闲/空态/错误态隐藏）
        self._loading_spinner = StyledLoading(size="lg")
        self._loading_spinner.setVisible(False)
        overlay_layout.addWidget(self._loading_spinner, 0, Qt.AlignCenter)

        self._placeholder = QLabel(_PLACEHOLDER_NO_FOLDER)
        self._placeholder.setAlignment(Qt.AlignCenter)
        register_widget_qss(self._placeholder,(
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 14px; background: transparent;"
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

    def unified_action_host(self):
        """统一操作按钮宿主：返回本预览器顶栏（New 布局注入用）。"""
        return self._top_bar

    def cleanup(self) -> None:
        """清理当前浏览状态（宿主切换/清除预览时调用）。

        同步停止目录监听与防抖定时器；若此前有选中条目，向外发一次
        None 让宿主信息面板恢复（避免残留已失效条目的展示）。
        """
        self._token += 1
        self._loading = False
        self._scan_worker = None
        self._root_path = ""
        self._current_rel = ""
        self._watcher_debounce.stop()
        self._disarm_watcher()
        self._model.clear()
        self._view.scrollToTop()
        self._path_edit.setText(_PLACEHOLDER_NO_FOLDER)
        self._back_btn.setEnabled(False)
        self._show_overlay(_PLACEHOLDER_NO_FOLDER)
        if self._last_selected_path is not None:
            self._last_selected_path = None
            self.entry_selected.emit(None)
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
        except Exception as exc:
            debug(f"图标缓存清理失败：{exc}")
        self._view.viewport().update()

    # ── 显示过滤开关（统一预览器宿主下发） ───────────────────────────────────

    def set_show_hidden_files(self, enabled: bool) -> None:
        """设置「显示隐藏文件」开关（幂等；宿主启动/设置提交路径调用）。

        关闭时同步关闭「显示系统文件」（系统文件可见性以隐藏文件开关为
        前提）；任一口径变化且当前已加载文件夹时立即重扫以体现新口径。

        Args:
            enabled: True 显示隐藏文件（带 FILE_ATTRIBUTE_HIDDEN 位）；
                False 隐藏（默认）。
        """
        enabled = bool(enabled)
        changed = enabled != self._show_hidden_files
        if not enabled and self._show_system_files:
            self._show_system_files = False
            changed = True
        self._show_hidden_files = enabled
        if changed:
            self._refresh_hidden_filter_view()

    def set_show_system_files(self, enabled: bool) -> None:
        """设置「显示系统文件」开关（幂等；宿主启动/设置提交路径调用）。

        仅当「显示隐藏文件」亦开启时生效（AND 语义），且只影响同时带
        「隐藏+系统」双重位的受保护操作系统文件/文件夹；口径变化且当前已
        加载文件夹时立即重扫以体现新口径。

        Args:
            enabled: True 显示同时带「隐藏+系统」双重位的条目；
                False 隐藏（默认）。
        """
        enabled = bool(enabled) and self._show_hidden_files
        if enabled == self._show_system_files:
            return
        self._show_system_files = enabled
        self._refresh_hidden_filter_view()

    def _refresh_hidden_filter_view(self) -> None:
        """隐藏/系统过滤口径变化后，若已加载文件夹则重扫。"""
        if self._root_path:
            self._refresh()

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
            busy: True 时显示加载圆环（读取中/搜索中等进行中状态）；
                False 时仅显示文本（占位/空态/错误）。
        """
        self._placeholder.setText(text)
        self._loading_spinner.setVisible(bool(busy))
        self._content_stack.setCurrentIndex(self._PAGE_OVERLAY)

    def _show_list(self) -> None:
        """切换到条目列表页（隐藏加载圆环）。"""
        self._loading_spinner.setVisible(False)
        self._content_stack.setCurrentIndex(self._PAGE_LIST)

    # ── 状态刷新 ─────────────────────────────────────────────────────────────

    def _current_directory(self) -> str:
        """当前浏览目录的真实绝对路径。"""
        if self._current_rel:
            return os.path.join(self._root_path, *self._current_rel.split("/"))
        return self._root_path

    def _refresh(self) -> None:
        """按当前浏览目录异步重新扫描（每次进入/返回都会触发）。

        扫描前先撤销旧目录监听，成功后由 ``_on_scan_finished`` 重新布防，
        避免导航期间旧目录事件误触发重扫。派发时捕获显示隐藏/系统过滤
        开关快照（后台线程不读取可变实例状态）。
        """
        if not self._root_path:
            return
        self._disarm_watcher()
        self._update_path_edit()
        self._loading = True
        self._token += 1
        token = self._token
        self._show_overlay(_PLACEHOLDER_LOADING, busy=True)

        worker = _FolderScanWorker(
            self._current_directory(),
            token,
            show_hidden=self._show_hidden_files,
            show_system=self._show_system_files,
        )
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
        self._arm_watcher()

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

    # ── 自动监听刷新 ─────────────────────────────────────────────────────────

    def _arm_watcher(self) -> None:
        """对当前目录重新布防（切换目录/扫描完成后调用；失败静默降级）。"""
        self._disarm_watcher()
        target = self._current_directory()
        if not target or not os.path.isdir(target):
            return
        try:
            if not self._watcher.addPath(target):
                debug(f"目录监听未生效（可能不可访问或不支持）: {target}")
        except Exception as exc:  # noqa: BLE001 - 监听失败不影响导航
            debug(f"目录监听异常: {exc}")

    def _disarm_watcher(self) -> None:
        """移除当前全部监听路径（cleanup/重新布防前调用）。"""
        try:
            paths = self._watcher.directories()
            if paths:
                self._watcher.removePaths(paths)
        except RuntimeError:
            pass

    def _on_directory_changed(self, path: str) -> None:
        """目录内容变化：重启防抖定时器（多次事件合并为一次重扫）。"""
        if self._root_path:
            self._watcher_debounce.start()

    def _on_refresh_debounce(self) -> None:
        """防抖到期：重扫当前目录（token 机制自动丢弃并发扫描的旧结果）。"""
        if self._root_path:
            self._refresh()

    # ── 选中联动 ─────────────────────────────────────────────────────────────

    def _on_selection_changed(self, *_args: Any) -> None:
        """列表选中变化：向宿主发射当前选中条目（按路径去重；空选发 None）。"""
        indexes = self._view.selectionModel().selectedIndexes()
        entry: Optional[dict] = None
        if indexes:
            entry = indexes[0].data(_FolderListModel.EntryRole)
        path = entry.get("path") if isinstance(entry, dict) else None
        if path == self._last_selected_path:
            return
        self._last_selected_path = path
        self.entry_selected.emit(dict(entry) if isinstance(entry, dict) else None)

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
