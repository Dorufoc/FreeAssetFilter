"""
文件选择器布局 — 顶栏（固定高度）+ 内容区（自适应拉伸）+ 底栏（固定高度）
"""

import ctypes
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QListView, QLabel, QAbstractItemView, QApplication, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QMargins, QObject, QPoint, QRect, QRunnable

from freeassetfilter.core import pools as thread_pools

from theme import tm
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.app_logger import debug
from freeassetfilter.core._paths import icons_dir as get_icons_dir
from freeassetfilter.core.workers.thumbnail_controller import ThumbnailController
from components.styled_button import StyledButton
from components.styled_lineedit import StyledLineEdit
from components.styled_context_menu import StyledContextMenu
from components.styled_dialog import StyledDialog, FOOTER_RIGHT, FOOTER_CENTER, create_basic_dialog, _show_dialog
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.styled_loading import StyledLoading
from components.box_selection import BoxSelectionGesture
from components.file_list_model import FileListModel, FilePathRole, FileNameRole, IsDirRole, FileSizeRole, ModifiedRole, CreatedRole, SuffixRole, IsPreviewingRole, IconPixmapRole
from components.file_card_delegate import (
    FileCardDelegate,
    CARD_CONFIG,
    LIST_CONFIG,
    calc_grid_base_width,
    calc_grid_cell,
)
from components.animated_file_list_view import AnimatedFileListView
from freeassetfilter.services.favorites_service import FavoritesService
from freeassetfilter.services.file_icon_manager import FileIconManager
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from freeassetfilter.core.native import api as native_api


# 目录加载指示器延迟显示时长（毫秒）：快目录不闪遮罩，慢目录（大目录/
# 机械盘/网络盘）才有转圈反馈。
DIR_LOADING_INDICATOR_DELAY_MS = 120

# ── 流式目录加载缓冲策略（OPT-002 Phase 1：小目录原子落地，超大/网络目录才渐进）──
# 扫描期间批次先进缓冲窗口，满足任一条件才首次落地：
#   1) 收尾批到达（本地绝大多数目录：扫描快，单批即收尾）；
#   2) 缓冲条目数达到 DIR_STREAM_HOLD_MAX_ENTRIES（对齐 Nemo 的
#      MAX_LOADING_PENDING_HELD）；
#   3) 距请求派发超过 DIR_STREAM_HOLD_MAX_MS（慢盘/超大盘保住"先进入、
#      慢慢加载"的体验）。
# 这样快目录只发生一次「已排序的原子落地」：路径过渡快照永远是完整最终
# 帧，不再出现「未排序首帧 → 收尾重排」的卡片跳闪。
DIR_STREAM_HOLD_MAX_ENTRIES = 500
DIR_STREAM_HOLD_MAX_MS = DIR_LOADING_INDICATOR_DELAY_MS

# 渐进模式下主线程合帧结算间隔（毫秒）：同一帧到达的多批条目合并为一次
# 模型插入 + 一次重绘，避免快扫描时逐批 relayout。
DIR_STREAM_FLUSH_INTERVAL_MS = 16

#: 待合帧批次数上限（P6.5 背压）：超限丢最旧批次——界面合帧只关心最新窗口，
#: 原始条目已进入 ``_raw_entries``，丢弃只影响展示时机、不丢数据。
DIR_STREAM_MAX_PENDING_BATCHES = 64

# ── native 排序门控（P1.2，依据 build/bench 的 P0 实测）──
# 2000 条时 native 路径净成本 ≥3.1ms（json.dumps 1.97 + json.loads 1.13）
# vs 纯 Python ``sort`` 0.32ms；30k 条时 native 的 8MB 守卫先白烧 115.2ms
# 再整体回退 Python（后者只要 2.7ms）。因此默认**关闭** native 排序；
# 仅在 P3 句柄式 ABI 落地并复测转正后才启用。
# 设置 ``FAF_NATIVE_SORT=1`` 可临时打开做对照实验。
NATIVE_SORT_ENABLED: bool = os.environ.get("FAF_NATIVE_SORT", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
#: native 排序的最小条目数门槛（仅 ``NATIVE_SORT_ENABLED`` 时生效）。
NATIVE_SORT_MIN_ENTRIES: int = 20000

# ── native 流式扫描（P3.4，默认开启）──
# Rust 持有 ``ReadDir`` 迭代器跨批推进，保留 P2.1 的「零额外 syscall」收益，
# 并把 Windows 属性位（隐藏/系统）一并回传。P0 实测整目录扫描 10k 条目
# 50.5ms vs Python 133.7ms（2.65×）；任何异常/旧 DLL → 自动回退 Python。
# 对照实验可设 ``FAF_NATIVE_STREAM=0`` 强制走 Python 逐批。
NATIVE_STREAM_ENABLED: bool = os.environ.get(
    "FAF_NATIVE_STREAM", "1"
).strip().lower() not in {"0", "false", "off", "no"}

# Windows 盘类型常量（GetDriveTypeW 返回值）。「All」视图默认只加载物理
# 磁盘（固定盘/可移动盘/RAM 盘）；网络磁盘与映射盘（DRIVE_REMOTE）以及
# 光驱（DRIVE_CDROM）由设置项 general.include_remote_drives（默认关闭）
# 控制，提交后经 FileSelectorLayout.set_include_remote_drives 运行时下发。
DRIVE_TYPE_REMOVABLE = 2
DRIVE_TYPE_FIXED = 3
DRIVE_TYPE_REMOTE = 4
DRIVE_TYPE_CDROM = 5
DRIVE_TYPE_RAMDISK = 6
_PHYSICAL_DRIVE_TYPES = frozenset(
    {DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_FIXED, DRIVE_TYPE_RAMDISK}
)
# 网络/映射盘与光驱的静态默认值：仅作为不携带实例状态的静态调用
#（测试/工具）的默认口径，交互路径始终由实例开关显式传入。
_DEFAULT_INCLUDE_REMOTE_DRIVES = False

# Windows 文件属性位（Win32 FILE_ATTRIBUTE_*，取自 stat 的 st_file_attributes）：
# 隐藏位与系统位。过滤口径对齐资源管理器：仅「隐藏」位随显示隐藏文件开关；
# 仅「系统」位（如重定向后的桌面/下载/音乐等系统文件夹）恒可见；「隐藏+系统」
# 双重位（受保护的操作系统文件）需隐藏文件与系统文件开关同时开启。
_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4


def _native_scan_directory(path: str) -> Optional[List[Dict[str, Any]]]:
    """经 faf_core 桥扫描目录；桥不可用/失败返回 None（调用方回退 Python）。

    Args:
        path: 待扫描目录绝对路径。

    Returns:
        Optional[List[Dict[str, Any]]]: 7 键条目列表；DLL 缺失、native 失败
            或超 8MB 上限时返回 ``None``。
    """
    return native_api.scan_directory(path)


def _native_sort_entries(
    entries: List[Dict[str, Any]], mode: int
) -> Optional[List[Dict[str, Any]]]:
    """经 faf_core 桥内存排序；桥不可用/失败返回 None（调用方回退 Python）。

    Args:
        entries: 7 键条目列表。
        mode: 排序模式 0-7。

    Returns:
        Optional[List[Dict[str, Any]]]: 排序后的条目列表；失败返回 ``None``。
    """
    return native_api.sort_entries(entries, mode)


class _DirectoryCollectRunnable(QRunnable):
    """异步目录收集任务（QRunnable 投 ``thread_pools.pool("interactive")``）。

    一次性任务：后台线程执行 ``listdir + stat`` 收集目录条目，完成经
    ``_dir_entries_ready`` 信号回主线程应用（跨线程信号按 AutoConnection
    排队到 UI 线程）；线程池线程为 daemon 语义，进程退出不被阻塞。
    收集期间以世代 token 作取消检查：过期请求在 Python 回退扫描中尽早
    放弃（不经信号回主线程），避免快速连续导航时白占线程与磁盘 IO。

    Args:
        owner: 所属 FileSelectorLayout（收集器与信号发射经由它）。
        path: 待收集目录路径（或 ``"All"`` 磁盘视图）。
        token: 异步加载世代快照，过期结果由槽侧丢弃。
        include_remote: 网络/映射盘与光驱开关快照（UI 线程派发时捕获，
            避免后台线程读取可变实例状态）。
        show_hidden: 显示隐藏文件开关快照（UI 线程派发时捕获）。
        show_system: 显示系统文件开关快照（UI 线程派发时捕获）。
    """

    def __init__(
        self,
        owner: "FileSelectorLayout",
        path: str,
        token: int,
        include_remote: bool = False,
        show_hidden: bool = False,
        show_system: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._owner = owner
        self._path = path
        self._token = token
        self._include_remote = bool(include_remote)
        self._show_hidden = bool(show_hidden)
        self._show_system = bool(show_system)

    def run(self) -> None:
        try:
            entries = self._owner._collect_directory_entries(
                self._path,
                cancel_check=lambda: self._owner._async_load_token != self._token,
                include_remote=self._include_remote,
                show_hidden=self._show_hidden,
                show_system=self._show_system,
            )
        except Exception as exc:  # noqa: BLE001  # 后台任务兜底：异常按不可读处理
            debug(f"目录收集异常（{self._path}）: {exc}")
            entries = None
        try:
            self._owner._dir_entries_ready.emit(self._path, entries, self._token)
        except RuntimeError:
            # 宿主（FileSelectorLayout）已销毁：丢弃结果即可
            pass


class _DirectoryStreamRunnable(QRunnable):
    """流式目录扫描任务（QRunnable 投 ``QThreadPool``）。

    渐进式加载：后台线程逐批扫描目录，每批经 ``_dir_batch_ready`` 信号回主
    线程（主线程侧走"缓冲窗口 + 原子落地/渐进追加"管线，见
    ``_on_dir_batch_ready``）。世代 token 兼作取消检查——过期请求在下一次
    迭代顶部尽快退出（``with os.scandir`` 保证句柄关闭）。与
    ``_DirectoryCollectRunnable`` 不同：本任务按批回报，且"未读到任何条目即
    失败"与"已读到若干批后失败"由主线程槽侧区分（后者不回溯回滚）。

    Args:
        owner: 所属 FileSelectorLayout（扫描器与信号发射经由它）。
        path: 待扫描目录路径（或 ``"All"`` 磁盘视图）。
        token: 异步加载世代快照，过期批次由槽侧丢弃。
        include_remote: 网络/映射盘与光驱开关快照（UI 线程派发时捕获，避免
            后台线程读取可变实例状态）。
        show_hidden: 显示隐藏文件开关快照（UI 线程派发时捕获）。
        show_system: 显示系统文件开关快照（UI 线程派发时捕获）。
    """

    def __init__(
        self,
        owner: "FileSelectorLayout",
        path: str,
        token: int,
        include_remote: bool = False,
        show_hidden: bool = False,
        show_system: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._owner = owner
        self._path = path
        self._token = token
        self._include_remote = bool(include_remote)
        self._show_hidden = bool(show_hidden)
        self._show_system = bool(show_system)

    def run(self) -> None:
        def cancel() -> bool:
            """世代 token 过期检查（不在后台线程读 UI 状态）。"""
            return self._owner._async_load_token != self._token

        # P1.3 单遍扫描：属性位随条目扫描一并采集（`follow_symlinks=False`
        # 口径与 `_hidden_system_attrs_map` 一致），不再前置一次整目录枚举。
        need_filter = self._path != "All" and not (
            self._show_hidden and self._show_system
        )
        attrs_by_name: Optional[Dict[str, int]] = {} if need_filter else None

        try:
            for batch, is_final in self._owner._iter_directory_batches(
                self._path,
                self._include_remote,
                cancel,
                attrs_out=attrs_by_name,
            ):
                if cancel():
                    return
                if attrs_by_name is not None:
                    batch = [
                        entry
                        for entry in batch
                        if self._owner._entry_visible_by_attrs(
                            entry, attrs_by_name, self._show_hidden, self._show_system
                        )
                    ]
                try:
                    self._owner._dir_batch_ready.emit(
                        self._path, batch, self._token, is_final
                    )
                except RuntimeError:
                    # 宿主已销毁：丢弃结果即可
                    return
                if is_final:
                    return
        except Exception as exc:  # noqa: BLE001  # 后台任务兜底：打开目录失败按零批错误上报
            debug(f"目录流式扫描异常（{self._path}）: {exc}")
            try:
                self._owner._dir_batch_ready.emit(self._path, None, self._token, True)
            except RuntimeError:
                pass


class FileSelectorLayout(QWidget):
    """文件选择器布局（左侧栏）"""

    file_selected = Signal(dict)
    file_selection_changed = Signal(dict, bool)
    preview_cancel_requested = Signal()
    toggle_pool_requested = Signal(dict)  # 右键直连：添加/移除文件池
    add_files_to_pool_requested = Signal(list)  # 框选批量加入储存池（file_info 列表，add-only）
    remove_files_from_pool_requested = Signal(list)  # 框选全部已在池时批量移出储存池（file_info 列表）
    # 异步目录加载：后台线程收集完成后发射（path, entries 或 None, token）
    _dir_entries_ready = Signal(str, object, int)
    # 流式目录加载：后台线程分批发射（path, batch 或 None, token, is_final）。
    # entries 为 None 且 is_final=True 表示"零批错误"（打开目录即失败）。
    _dir_batch_ready = Signal(str, object, int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._previewing_file_path: str = ""  # 当前预览态卡片的文件路径（空 = 无）
        # 网络/映射盘与光驱加载开关（general.include_remote_drives，默认关闭；
        # 启动时与设置提交时经 set_include_remote_drives 下发）
        self._include_remote_drives: bool = _DEFAULT_INCLUDE_REMOTE_DRIVES
        # 空白区右键返回上一级开关（general.blank_right_click_go_back，默认
        # 关闭；启动时与设置提交时经 set_blank_right_click_go_back 下发）
        self._blank_right_click_go_back: bool = False
        # 显示隐藏文件开关（general.show_hidden_files，默认关闭；启动时与
        # 设置提交时经 set_show_hidden_files 下发）
        self._show_hidden_files: bool = False
        # 显示系统文件开关（general.show_system_files，默认关闭；仅当隐藏
        # 文件开关亦开启时生效，经 set_show_system_files 下发）
        self._show_system_files: bool = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 顶栏区域（固定高度，包含两行）
        self._top_bar = QFrame()
        self._top_bar.setObjectName("FileSelectorTopBar")
        self._top_bar.setFixedHeight(88)
        self._build_top_bar()
        layout.addWidget(self._top_bar)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("FileSelectorContent")
        layout.addWidget(self._content_area, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("FileSelectorBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)

        # 设置最小宽度：顶栏/底栏完整显示图标与文字所需的较大者（自然最小）
        self._update_minimum_width()

        # ── 文件列表模型 + 委托 + 视图 ──
        self._file_model = FileListModel(self)
        self._card_delegate = FileCardDelegate(self)
        self._file_list = AnimatedFileListView()
        self._file_list.setViewMode(QListView.IconMode)
        self._file_list.setWrapping(True)
        self._file_list.setResizeMode(QListView.Fixed)
        self._file_list.setMovement(QListView.Static)
        self._file_list.setFlow(QListView.LeftToRight)
        self._file_list.setSpacing(0)
        # 无选择模式：单击 = 预览/进入目录（右键为单卡入池/移出池），
        # 同时杜绝 Qt 内建拖拽框选与选中高亮（批量框选已移除）。
        self._file_list.setSelectionMode(QAbstractItemView.NoSelection)
        self._file_list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._file_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._file_list.setUniformItemSizes(True)
        self._file_list.setLayoutMode(QListView.Batched)
        self._file_list.setBatchSize(50)
        # QListView 自身隐藏默认滚动条，由同级的 StyledScrollBar 接管
        self._file_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._file_list.setMouseTracking(True)
        self._file_list.setModel(self._file_model)
        self._file_list.setItemDelegate(self._card_delegate)
        # 注入视图引用：delegate 的 hover 图标缩放动画每帧触发 viewport 重绘
        self._card_delegate.set_view(self._file_list)
        self._file_list.setFrameShape(QFrame.NoFrame)
        register_widget_qss(self._file_list,("""
            QListView {
                background: transparent;
                border: none;
                padding: 0px;
            }
            QListView::item {
                background: transparent;
            }
        """))

        # 右键直连文件池：添加到池或从池移除
        self._file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._file_list.customContextMenuRequested.connect(self._on_right_click_toggle_pool)

        # 防递归守卫（与旧 file_selector.py 一致——旧代码无守卫，这里仅防止极端递归）
        self._updating_grid: bool = False

        # 当前网格几何快照（每次布局计算时更新，供空白位右键命中判定使用）：
        # _grid_cols = 每行格子数（列表模式恒为 1，0 = 尚未布局）；
        # _grid_card_size = 卡片本体尺寸（不含格子预留的间距）。
        self._grid_cols: int = 0
        self._grid_card_size: QSize = QSize()

        # 卡片缩放系数（Ctrl+滚轮调整）
        self._card_scale: float = 1.0
        self._card_scale_min: float = 0.5
        self._card_scale_max: float = 2.0

        # 文件列表独占内容区全宽，滚动条作为浮动覆盖层
        content_layout = QHBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._file_list, stretch=1)

        # 滚动条作为浮动子控件覆盖在内容区右侧，置于文件列表之上
        self._file_scrollbar = StyledScrollBar(self._content_area)
        self._file_scrollbar.setFixedWidth(max(6, int(8 * 1.0)))
        self._file_scrollbar.raise_()

        # 将 StyledScrollBar 连接至 QListView 的垂直滚动
        list_vbar = self._file_list.verticalScrollBar()
        self._file_scrollbar.setRange(
            list_vbar.minimum(), list_vbar.maximum()
        )
        self._file_scrollbar.setSingleStep(list_vbar.singleStep())
        self._file_scrollbar.setPageStep(list_vbar.pageStep())
        list_vbar.rangeChanged.connect(self._sync_scrollbar_range)
        list_vbar.rangeChanged.connect(self._on_list_range_changed)
        self._file_scrollbar.valueChanged.connect(list_vbar.setValue)
        list_vbar.valueChanged.connect(self._file_scrollbar.setValue)

        # 应用平滑滚动 + 触摸手势
        StyledScrollArea.apply_to(self._file_list, enable_mouse_drag=False)

        # ── 目录加载遮罩（延迟显示）──────────────────────────────────────
        # 复用 StyledLoading overlay 模式：慢目录加载时盖在内容区上（旧画面
        # 压暗 + 居中转圈），完成后由 _stop_loading_indicator 隐藏；延迟
        # DIR_LOADING_INDICATOR_DELAY_MS 出现，避免快目录闪烁。遮罩期间鼠标
        # 事件被吞掉，防止误点旧卡片触发预览/导航。
        self._loading_overlay = StyledLoading(
            size="lg", overlay=True, backdrop="dim", parent=self._content_area
        )
        self._loading_overlay.fit_to_parent()
        self._loading_overlay.hide()
        self._loading_show_timer = QTimer(self)
        self._loading_show_timer.setSingleShot(True)
        self._loading_show_timer.timeout.connect(self._on_loading_indicator_timeout)

        # 导航状态
        self._current_path: str = "All"
        # 标记路径框是否被用户手动编辑但未提交跳转（失焦时回填当前显示路径）
        self._path_input_dirty: bool = False
        self._view_mode: str = "card"
        self._nav_history: List[str] = []
        self._history_index: int = -1
        self._sort_mode: int = 0
        self._first_show: bool = True
        # 方向键导航状态（arrow-key-file-preview-nav Todo 1：仅状态与模型行
        # 数学，不含按键处理）。_nav_cursor_path = 手势光标文件路径；
        # _nav_active = 手势进行中（按下未释放）；_nav_cursor_row = 手势内
        # 模型行（仅按住期间有效）；_nav_last_key = 手势起始方向键；
        # _nav_model_key = 手势起始时的模型签名（路径/行数/视图），用于判定
        # 模型是否已变化（变化即不再视为同一手势的延续）。
        self._nav_cursor_path: str = ""
        self._nav_active: bool = False
        self._nav_cursor_row: int = -1
        self._nav_last_key: int = 0
        self._nav_model_key: Optional[Tuple[Any, int, str]] = None
        # 异步目录加载：递增 token 丢弃过期结果（快速连续导航场景）
        self._async_load_token: int = 0
        self._dir_entries_ready.connect(self._on_dir_entries_ready)
        self._dir_batch_ready.connect(self._on_dir_batch_ready)
        # 流式加载状态：_stream_active_token 为在途流式请求的 token（-1=无）；
        # _stream_started_token 为首帧已落地（呈现）的 token（-1=无），用于区分
        # "零批错误"（回滚）与"已落地若干批后错误"（保留部分结果）；"All"
        # 视图载荷另存，避免污染目录 raw 缓存。
        self._stream_active_token: int = -1
        self._stream_started_token: int = -1
        self._stream_all_entries: List[Dict[str, Any]] = []
        # 缓冲窗口状态（OPT-002 Phase 1）：_stream_holding=True 表示首帧尚未
        # 落地，批次先积累在 _stream_hold_entries（收尾批/积满/超时才落地，
        # 见 DIR_STREAM_HOLD_MAX_*）；_stream_hold_path 为超时落地时定位用；
        # _stream_hold_start 为窗口起点（monotonic 秒）。
        self._stream_holding: bool = False
        self._stream_hold_entries: List[Dict[str, Any]] = []
        self._stream_hold_path: str = ""
        self._stream_hold_start: float = 0.0
        self._stream_hold_timer = QTimer(self)
        self._stream_hold_timer.setSingleShot(True)
        self._stream_hold_timer.timeout.connect(self._on_stream_hold_timeout)
        # 渐进模式合帧缓冲：批次先入 _stream_pending_batches，帧定时器到点
        # 一次性结算（一次插入 + 一次重绘），避免逐批 relayout。
        self._stream_pending_batches: List[List[Dict[str, Any]]] = []
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setSingleShot(True)
        self._stream_flush_timer.timeout.connect(self._flush_stream_batches)
        # 异步加载应用状态：本次请求的过渡方向（0=无动画）/初始加载标记/
        # 历史回滚标记（显式导航失败时回滚已压入的历史栈；刷新/返回不回滚）
        self._pending_transition_direction: int = 0
        self._pending_initial_load: bool = False
        self._pending_history_rollback: bool = False
        # 挂起定位：locate_file 异步导航后，等条目落地再高亮/滚动目标卡片
        self._pending_locate_path: str = ""
        # raw entries 缓存：最近一次目录加载的原始（未筛选未排序）条目，
        # 与 _current_path 绑定；排序切换/筛选应用据此内存重排，不再重扫磁盘。
        self._raw_entries: List[Dict[str, Any]] = []
        self._raw_entries_path: str = ""

        # 收藏夹与筛选状态
        self._favorites_service = FavoritesService()
        self._filter_pattern: str = ""
        self._active_dialogs: List = []  # 保持弹窗引用，防止被 GC

        # ── 缩略图生成 / 清除控制器（parent=self 防 GC）──
        # 生成进度文案（"done/total"），供生成中点击弹窗的提示语拼接
        self._gen_progress_text: str = ""
        self._thumb_controller = ThumbnailController(self)
        self._thumb_controller.progress_emitted.connect(self._on_thumbnail_progress)
        self._thumb_controller.files_ready.connect(self._on_thumbnails_ready)
        self._thumb_controller.batch_finished.connect(self._on_thumbnail_batch_finished)
        self._thumb_controller.clear_finished.connect(self._on_thumbnails_cleared)
        self._thumb_controller.failed.connect(self._on_thumbnail_failed)

        # ── 信号连接 ──
        self._path_input.returnPressed.connect(self._navigate_to_input_path)
        self._path_input.textEdited.connect(self._on_path_input_text_edited)
        self._arrow_btn.clicked.connect(self._navigate_to_input_path)
        self._refresh_btn.clicked.connect(self._reload_directory)
        self._undo_btn.clicked.connect(self._go_back)
        self._sort_btn.clicked.connect(self._show_sort_menu)
        self._card_btn.clicked.connect(self._toggle_view_mode)
        self._file_list.clicked.connect(self._on_file_clicked)

        # 占位 / 初次导航
        self._tool_star_btn.clicked.connect(self._show_favorites_dialog)
        self._sift_btn.clicked.connect(self._show_filter_dialog)
        self._driver_btn.clicked.connect(self._navigate_to_all)
        self._star_btn.clicked.connect(self._add_current_path_to_favorites)
        self._gen_thumb_btn.clicked.connect(self._on_generate_thumbnails)
        self._clean_btn.clicked.connect(self._on_clear_thumbnails)

        self._sort_btn.setToolTip("排序: 名称↑")
        self._card_btn.setToolTip("切换为列表视图")
        self._refresh_btn.setToolTip("刷新")
        self._tool_star_btn.setToolTip("收藏夹")
        self._sift_btn.setToolTip("筛选文件")
        self._star_btn.setToolTip("添加当前路径到收藏夹")
        self._undo_btn.setToolTip("返回上一级")
        self._driver_btn.setToolTip("全部磁盘")
        self._arrow_btn.setToolTip("跳转路径")
        self._clean_btn.setToolTip("清除缩略图")

        # 监听 viewport 和 file_list 自身的 resize（与旧 file_selector.py 一致）
        self._file_list.viewport().installEventFilter(self)
        self._file_list.installEventFilter(self)

        # 主题切换：刷新计数标签等构建期注册的配色
        tm.theme_changed.connect(self._on_theme_changed)

        # 当前文件池路径集合（由 sync_pool_status 更新，"已在池中"标记局部重绘的 diff 基准）
        self._pool_paths: Set[str] = set()

        # ── 框选多选（左键按住拖拽 = 橡皮筋框选）────────────────────────
        # 框内卡片进入"框选选中态"（虚线 accent 边框 + 半透明填充，不触发预览）；
        # 右键点在已选中卡片上 = 批量加入储存池；空白区右键仍返回上一级。
        self._box_gesture = BoxSelectionGesture(
            self,
            overlay_parent=self._file_list.viewport(),
            scrollbar_getter=lambda: self._file_list.verticalScrollBar(),
            hit_test=self._box_hit_test,
            on_hits=self._apply_box_hits,
        )

    # ── 事件过滤器：在 QListView resize 前更新网格 ──────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """事件过滤器：网格自适应 + Ctrl+滚轮缩放 + 左键框选 + 鼠标侧键后退。

        同时监听 viewport 与 QListView 自身的 Resize；Wheel+Ctrl 走卡片缩放；
        左键按下/拖动/松开委托给框选手势（超过拖拽阈值后进入框选并实时
        更新选中态，未拖拽的单击保留原有"点击=预览"语义）；
        鼠标侧键（后退键）返回上一层级目录。
        另外监听路径框：Resize 时跟动内嵌跳转按钮，FocusOut 时回填未提交编辑。

        Args:
            obj: 事件来源对象（viewport、文件列表视图或路径输入框）。
            event: Qt 事件对象。

        Returns:
            True 表示事件已消费，False 表示放行给默认处理。
        """
        # 路径框：Resize 跟动内嵌跳转按钮，FocusOut 回填未提交的手动编辑。
        # 需先于文件列表分支处理：路径框事件可能在 _file_list 创建前到达，
        # 此刻读取 self._file_list 会抛 AttributeError；处理完直接放行。
        if obj is self._path_input:
            if event.type() == QEvent.Resize:
                self._position_path_jump_btn()
            elif event.type() == QEvent.FocusOut:
                self._on_path_input_focus_out()
            elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                # ESC：取消编辑，回填当前路径并移出焦点（消费事件不向上传递）
                self._update_path_input(self._current_path)
                self._path_input.clearFocus()
                return True
            return super().eventFilter(obj, event)
        # 同时监听 viewport 和 QListView 的 Resize（与旧 file_selector.py 一致）
        if obj is self._file_list.viewport() or obj is self._file_list:
            if event.type() == QEvent.Resize:
                self._update_grid_size()
            elif event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    self._handle_card_zoom(event)
                    return True
            elif event.type() == QEvent.MouseButtonPress:
                if self._is_back_navigation_button(event.button()):
                    # 鼠标侧键（后退键）返回上一层级目录，与顶栏"返回上一级"按钮行为一致
                    self._go_back()
                    return True
                if event.button() == Qt.LeftButton:
                    # 只记录起点，不消费按下事件（保留 QListView 的单击语义）
                    self._box_gesture.begin(self._viewport_pos(event, obj))
            elif event.type() == QEvent.MouseMove:
                if self._box_gesture.started:
                    pressed = bool(event.buttons() & Qt.LeftButton)
                    if self._box_gesture.update(self._viewport_pos(event, obj), pressed):
                        return True
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton and self._box_gesture.started:
                    pos = self._viewport_pos(event, obj)
                    if self._box_gesture.finish(pos):
                        # 拖拽框选结束：消费释放事件，阻止 clicked → 预览
                        return True
                    # 未拖拽的单击：空白区清除框选；卡片单击由 clicked 处理
                    if not self._file_list.indexAt(pos).isValid():
                        self.clear_box_selection()
        return super().eventFilter(obj, event)

    @staticmethod
    def _is_back_navigation_button(button: Any) -> bool:
        """判断是否为鼠标侧键（后退键）。

        兼容不同 Qt 枚举名：Qt6 中 XButton1 是 BackButton 的别名，
        旧版环境可能仅有 ExtraButton1 / BackButton 之一，因此逐一探测。

        Args:
            button: 鼠标按键枚举值。

        Returns:
            True 为后退侧键，False 为其他按键。
        """
        for button_name in ("BackButton", "XButton1", "ExtraButton1"):
            back_button = getattr(Qt, button_name, None)
            if back_button is not None and button == back_button:
                return True
        return False

    # ── 框选多选（橡皮筋）──────────────────────────────────────────────────

    def _viewport_pos(self, event: QEvent, obj: Optional[object] = None) -> QPoint:
        """将鼠标事件位置统一换算为 viewport 坐标。

        事件可能来自 viewport 或 QListView 本体（帧/边距区），直接取
        event.position() 会带着对象自身坐标系导致选框起点错位；统一映射到
        viewport 坐标系后，起点始终精确落在鼠标按下位置。

        Args:
            event: 鼠标事件（须提供 position()）。
            obj: 事件目标对象（viewport / QListView）。

        Returns:
            viewport 坐标系下的点。
        """
        pos: QPoint = event.position().toPoint()
        viewport = self._file_list.viewport()
        if obj is viewport or obj is None or viewport is None:
            return pos
        if isinstance(obj, QWidget):
            try:
                return obj.mapTo(viewport, pos)
            except RuntimeError:
                return pos
        return pos

    def _box_hit_test(self, rect: QRect) -> Set[int]:
        """计算与选框矩形相交的卡片行号集合（视觉重叠即命中）。

        QListView 采用 Batched 惰性布局：只有视口附近的行才拥有有效可视
        矩形，远端未布局行没有几何信息。因此先探测一个可见锚点行，再向上
        回退到首行、向下扫描到选框/视口底部，只对可视区（含选框越界部分）
        做精确相交判定；万级目录下开销只与可视行数相关，而非全量行数。

        Args:
            rect: 选框矩形（viewport 坐标）。

        Returns:
            与选框相交的行号集合。
        """
        model = self._file_model
        view = self._file_list
        count = model.rowCount()
        if count <= 0:
            return set()
        viewport = view.viewport()
        vp = QRect(QPoint(0, 0), viewport.size())
        if vp.width() <= 0 or vp.height() <= 0:
            return set()

        def _visual(row: int) -> QRect:
            return view.visualRect(model.index(row, 0))

        # 可见锚点行：沿视口取 3×3 探针的最小有效行（考虑多列网格空隙）
        anchor = -1
        probe_xs = (2, max(2, vp.width() // 2), max(2, vp.width() - 3))
        probe_ys = (2, max(2, vp.height() // 2), max(2, vp.height() - 3))
        for px in probe_xs:
            for py in probe_ys:
                index = view.indexAt(QPoint(px, py))
                if index.isValid() and (anchor < 0 or index.row() < anchor):
                    anchor = index.row()

        if anchor < 0:
            # 视口内无已布局卡片（空目录 / 尚未布局）：从首行做有界回退扫描
            first_row = 0
        else:
            first_row = anchor
            # 向上回退到首个仍与视口相交的行（跨批次的已布局行）
            while first_row > 0:
                prev = _visual(first_row - 1)
                if not prev.isValid() or prev.bottom() < 0:
                    break
                first_row -= 1

        limit_y = max(rect.bottom(), vp.height() - 1)
        hits: Set[int] = set()
        row = first_row
        scanned = 0
        while row < count and scanned < 4096:
            visual = _visual(row)
            if not visual.isValid():
                # 已到未布局区（Batched 惰性布局）：后续行无可视矩形
                break
            if visual.top() > limit_y:
                break
            if rect.intersects(visual):
                hits.add(row)
            row += 1
            scanned += 1
        return hits

    def _apply_box_hits(self, rows: Set[int]) -> None:
        """把框选命中行集合应用到模型选中态（替换语义）。

        Args:
            rows: 命中行号集合；未命中的已选行自动取消选中。
        """
        model = self._file_model
        current = model.get_selected_rows()
        to_select = rows - current
        to_deselect = current - rows
        if to_select:
            model.set_rows_selected(to_select, True)
        if to_deselect:
            model.set_rows_selected(to_deselect, False)

    def clear_box_selection(self) -> None:
        """清空文件选择器内所有卡片的框选选中态（幂等）。"""
        model = self._file_model
        selected = model.get_selected_rows()
        if selected:
            model.set_rows_selected(selected, False)

    def _selected_file_infos(self) -> List[Dict[str, Any]]:
        """组装当前框选选中项的 file_info 列表（按入池/预览所需字段）。

        Returns:
            file_info 字典列表；无选中时返回空列表。
        """
        model = self._file_model
        infos: List[Dict[str, Any]] = []
        for file_path in model.get_selected_files():
            row = model.get_row(file_path)
            if row < 0:
                continue
            idx = model.index(row, 0)
            infos.append({
                "name": model.data(idx, FileNameRole) or "",
                "path": file_path,
                "is_dir": bool(model.data(idx, IsDirRole)),
                "size": int(model.data(idx, FileSizeRole) or 0),
                "modified": model.data(idx, ModifiedRole) or "",
                "created": model.data(idx, CreatedRole) or "",
                "suffix": (model.data(idx, SuffixRole) or "").lower(),
            })
        return infos

    def _all_in_pool(self, infos: List[Dict[str, Any]]) -> bool:
        """判断给定条目是否全部已在储存池中。

        比对基准为 ``_pool_paths``（sync_pool_status 维护的 normcase+normpath
        归一化池路径集合），与卡片"已在池中"边框标记同源。

        Args:
            infos: file_info 字典列表。

        Returns:
            True 表示全部已在池中；空列表、池为空或任一条目缺失路径/不在池
            时返回 False。
        """
        if not infos or not self._pool_paths:
            return False
        for info in infos:
            path = str(info.get("path") or "")
            if not path:
                return False
            if os.path.normcase(os.path.normpath(path)) not in self._pool_paths:
                return False
        return True

    # ── 首次加载 ──────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_first_show", False):
            self._first_show = False
            # 首次导航本身已经异步（后台扫描 + 分批落地），无需再等 50ms；
            # 越早派发越早拿到首批条目（实测省 ~50ms 首帧延迟）。
            QTimer.singleShot(0, self._init_navigation)

    def start_initial_navigation(self) -> None:
        """启动首次导航（幂等）；由宿主任意时机调用均可。

        典型调用点是主窗口刚构建完选择器、还未 addWidget/show 时：目录扫描
        在后台线程跑，不依赖控件可见，提前派发可将扫描与其余三个面板的构建
        并行，把“转圈结束后才出首批条目”的延迟前移。
        """
        if getattr(self, "_initial_navigation_started", False):
            return
        self._initial_navigation_started = True
        # 标记首显钩子已消费，避免 showEvent 重复导航
        self._first_show = False
        self._init_navigation()

    def _init_navigation(self) -> None:
        app = QApplication.instance()
        initial_navigate_path = getattr(app, "initial_navigate_path", None)
        if initial_navigate_path and os.path.isdir(initial_navigate_path):
            # 启动首次加载走异步路径，避免大目录 listdir+stat 阻塞首屏
            self._navigate_to(initial_navigate_path, transition=False, initial=True)
            return
        if self._try_restore_last_path():
            return
        self._navigate_to_all()

    # ── All 视图 ──────────────────────────────────────────────────────────

    def _navigate_to_all(self) -> None:
        """切换到「All」磁盘视图（异步加载物理磁盘；请求即返回）。

        默认只加载物理磁盘（固定盘/可移动盘/RAM 盘）；网络/映射盘与光驱
        由设置项 general.include_remote_drives 控制（默认关闭），
        经 ``set_include_remote_drives`` 运行时下发。
        """
        direction = self._infer_navigation_direction(self._current_path, "All")
        started = direction != 0 and self._file_list.begin_path_transition(direction)
        self._load_directory_async("All", direction if started else 0)
        # 注：盘符过滤开关由 _load_directory_async → _DirectoryStreamRunnable
        # 在派发时快照 self._include_remote_drives，线程内不读实例状态。
        self._current_path = "All"
        self._update_path_input("All")
        self._nav_history = ["All"]
        self._history_index = 0
        self._clear_last_path()

    def _load_all(self) -> None:
        """同步加载「All」视图（保留给测试/兜底；交互导航走异步管线）。"""
        self._apply_all_entries(
            self._collect_all_drives_python(self._include_remote_drives)
        )

    def _apply_all_entries(self, entries: List[Dict[str, Any]]) -> None:
        """应用「All」视图条目：刷新模型/网格/计数（与旧 _load_all 行为一致）。

        Args:
            entries: 7 键盘符条目列表。
        """
        self._file_list.setUpdatesEnabled(False)
        try:
            self._file_model.set_files(entries)
            self.reset_nav_state()
            self._update_grid_size()
            self._update_file_count(len(entries))
        finally:
            self._file_list.setUpdatesEnabled(True)
        self._file_list.viewport().update()

    @staticmethod
    def _is_supported_drive_type(
        drive_path: str, include_remote: Optional[bool] = None
    ) -> bool:
        """判断盘符是否应出现在「All」视图中（Windows GetDriveTypeW）。

        默认仅包含固定盘（DRIVE_FIXED）、可移动盘（DRIVE_REMOVABLE）与
        RAM 盘（DRIVE_RAMDISK）；``include_remote=True`` 时额外包含网络/
        映射盘（DRIVE_REMOTE）与光驱（DRIVE_CDROM）。类型探测失败时保守
        放行，保持旧行为。

        Args:
            drive_path: 盘符根路径（如 ``"C:\\"``）。
            include_remote: 网络/映射盘与光驱开关；``None`` 时取静态默认
                （关闭），交互路径应显式传入实例开关快照。

        Returns:
            bool: True 表示应包含在「All」视图中。
        """
        if include_remote is None:
            include_remote = _DEFAULT_INCLUDE_REMOTE_DRIVES
        try:
            drive_type = int(
                ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive_path))
            )
        except Exception:  # noqa: BLE001  # 类型探测失败保守放行
            return True
        if drive_type in (DRIVE_TYPE_REMOTE, DRIVE_TYPE_CDROM):
            return bool(include_remote)
        return drive_type in _PHYSICAL_DRIVE_TYPES

    @staticmethod
    def _collect_all_drives_python(
        include_remote: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """纯 Python 枚举「All」视图条目（不经 faf_core native）。

        ``include_remote=False``（默认）仅加载物理磁盘（固定盘/可移动盘/
        RAM 盘）；True 时额外包含网络/映射盘与光驱。Windows 上经
        ``GetLogicalDrives`` 位掩码 + ``GetDriveTypeW`` 类型过滤后逐个
        ``os.stat``；非 Windows 回退为根目录 ``/`` 一个条目。

        Args:
            include_remote: 网络/映射盘与光驱开关；``None`` 时取静态默认
                （关闭）。

        Returns:
            List[Dict[str, Any]]: 7 键条目列表（与目录扫描产物同构）。
        """
        entries: List[Dict[str, Any]] = []
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            drives_bitmask = kernel32.GetLogicalDrives()
            for drive in range(26):
                if not drives_bitmask & (1 << drive):
                    continue
                drive_name = chr(65 + drive) + ":"
                drive_path = drive_name + "\\"
                if not FileSelectorLayout._is_supported_drive_type(
                    drive_path, include_remote
                ):
                    continue
                try:
                    st = os.stat(drive_path)
                    modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                    created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
                except OSError:
                    modified = ""
                    created = ""
                usage_ratio: Optional[float] = None
                try:
                    usage = shutil.disk_usage(drive_path)
                    if usage.total > 0:
                        usage_ratio = max(
                            0.0,
                            min(1.0, (usage.total - usage.free) / usage.total),
                        )
                except Exception:  # noqa: BLE001  # 盘符容量探测失败不阻塞 All 视图
                    pass
                entries.append({
                    "name": drive_name, "path": drive_path, "is_dir": True,
                    "is_drive": True, "usage_ratio": usage_ratio,
                    "size": 0, "modified": modified, "created": created, "suffix": "",
                })
        else:
            entries.append({
                "name": "/", "path": "/", "is_dir": True,
                "size": 0, "modified": "", "created": "", "suffix": "",
            })
        return entries

    # ── 上次路径恢复 ─────────────────────────────────────────────────────
    def _try_restore_last_path(self) -> bool:
        save_file = Path(get_app_data_path()) / "last_path.json"
        try:
            if not save_file.exists():
                return False
            import json
            with open(save_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            last_path = data.get("last_path")
            if last_path and os.path.isdir(last_path):
                # 恢复上次路径走异步加载；失败时由 initial 标记回退到 All 视图
                return self._navigate_to(last_path, transition=False, initial=True)
        except Exception as exc:
            debug(f"恢复上次路径失败（回退 All 视图）：{exc}")
        return False

    def _save_last_path(self, path: str) -> None:
        save_file = Path(get_app_data_path()) / "last_path.json"
        try:
            import json
            with open(save_file, "w", encoding="utf-8") as f:
                json.dump({"last_path": os.path.abspath(path)}, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            debug(f"保存路径历史失败：{exc}")

    def _clear_last_path(self) -> None:
        """删除 last_path.json，使下次启动不恢复任何路径，直接落到 All。"""
        save_file = Path(get_app_data_path()) / "last_path.json"
        try:
            save_file.unlink(missing_ok=True)
        except Exception as exc:
            debug(f"清除路径历史失败：{exc}")

    # ── UI 构建 ──────────────────────────────────────────────────────────

    def _build_top_bar(self):
        icons_dir = get_icons_dir()
        top_layout = QVBoxLayout(self._top_bar)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(8, 4, 8, 0)
        nav_row.setSpacing(4)

        driver_icon = str(icons_dir / "driver.svg")
        self._driver_btn = StyledButton("", variant="ghost", size="sm", icon=driver_icon)
        self._driver_btn.setFixedSize(32, 32)
        nav_row.addWidget(self._driver_btn)

        self._path_input = StyledLineEdit(size="default")
        self._path_input.setPlaceholderText("输入路径...")
        # 右侧预留 36px 文本空间，防止输入文字被内嵌跳转按钮遮挡
        # （28px 按钮 + 4px 间隙 + 4px 右边距）。
        self._path_input.setTextMargins(12, 8, 36, 8)
        nav_row.addWidget(self._path_input, stretch=1)

        arrow_icon = str(icons_dir / "arrow_right.svg")
        self._arrow_btn = StyledButton("", variant="ghost", size="sm", icon=arrow_icon)
        self._arrow_btn.setFixedSize(28, 28)
        # 内嵌浮层方案：跳转按钮不占布局项，reparent 进路径框内部并 raise 到
        # 最上层，浮于输入框右端（与 _file_scrollbar 覆盖在内容区上同一思路）。
        self._arrow_btn.setParent(self._path_input)
        self._arrow_btn.raise_()
        self._path_input.installEventFilter(self)

        star_icon = str(icons_dir / "star.svg")
        self._star_btn = StyledButton("", variant="ghost", size="sm", icon=star_icon)
        self._star_btn.setFixedSize(32, 32)
        nav_row.addWidget(self._star_btn)

        top_layout.addLayout(nav_row)

        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(5, 4, 5, 4)
        tool_row.setSpacing(2)

        unto_icon = str(icons_dir / "unto.svg")
        self._undo_btn = StyledButton("", variant="ghost", size="sm", icon=unto_icon)
        self._undo_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._undo_btn)

        refresh_icon = str(icons_dir / "refresh.svg")
        self._refresh_btn = StyledButton("", variant="ghost", size="sm", icon=refresh_icon)
        self._refresh_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._refresh_btn)

        star_icon = str(icons_dir / "star.svg")
        self._tool_star_btn = StyledButton("", variant="ghost", size="sm", icon=star_icon)
        self._tool_star_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._tool_star_btn)

        sift_icon = str(icons_dir / "sift.svg")
        self._sift_btn = StyledButton("", variant="ghost", size="sm", icon=sift_icon)
        self._sift_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._sift_btn)

        sort_icon = str(icons_dir / "sort.svg")
        self._sort_btn = StyledButton("", variant="ghost", size="sm", icon=sort_icon)
        self._sort_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._sort_btn)

        card_icon = str(icons_dir / "list.svg")  # card 模式下显示"列表"图标
        self._card_btn = StyledButton("", variant="ghost", size="sm", icon=card_icon)
        self._card_btn.setFixedSize(28, 28)
        tool_row.addWidget(self._card_btn)

        top_layout.addLayout(tool_row)
        # 构建末尾先摆一次内嵌跳转按钮（后续由 eventFilter 随输入框 resize 跟动）
        self._position_path_jump_btn()

    def _position_path_jump_btn(self) -> None:
        """把内嵌跳转按钮定位到路径框右端（水平内缩，垂直居中，越界钳到 0）。

        首次构建与路径框每次 resize 时调用；坐标以路径框本地坐标系为准。
        """
        x = self._path_input.width() - self._arrow_btn.width() - 4
        y = (self._path_input.height() - self._arrow_btn.height()) // 2
        self._arrow_btn.move(max(x, 0), max(y, 0))

    def _build_bottom_bar(self) -> None:
        icons_dir = get_icons_dir()
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(8, 6, 8, 6)
        bottom_layout.setSpacing(6)

        self._file_count_label = QLabel("0 个条目")
        register_widget_qss(self._file_count_label,("background: transparent; border: none; font-size: 11px;"))
        bottom_layout.addWidget(self._file_count_label)

        self._gen_thumb_btn = StyledButton("生成缩略图", variant="primary", size="sm")
        bottom_layout.addWidget(self._gen_thumb_btn, stretch=1)

        clean_icon = str(icons_dir / "clean.svg")
        self._clean_btn = StyledButton("", variant="ghost", size="sm", icon=clean_icon)
        self._clean_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._clean_btn)

        bottom_layout.addStretch()

    # ── 目录加载 ──────────────────────────────────────────────────────────

    @staticmethod
    def _collect_directory_entries(
        path: str,
        cancel_check=None,
        include_remote: Optional[bool] = None,
        show_hidden: Optional[bool] = None,
        show_system: Optional[bool] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """纯 IO 收集目录条目（桥可用时优先 native 扫描，否则 Python 回退）。

        单点接线：同步路径（``_load_directory``）与异步路径
        （``_DirectoryCollectRunnable.run``）都经此方法。可在后台线程执行
        ——不触碰任何 Qt/主线程状态。``"All"`` 视图固定走纯 Python 枚举
        （不经 native 桥）。返回条目列表；目录不可读时返回 None
        （调用方执行与同步路径一致的清空处理）。

        隐藏/系统过滤：``show_hidden`` 与 ``show_system`` 均为 ``None`` 时
        不做任何过滤（保持静态直调的legacy 口径）；否则对 native 或 Python
        回退收集到的条目统一套用 ``_apply_hidden_system_filter``（``"All"``
        盘符分支始终不过滤）。过滤只删条目、不改条目结构，返回值仍为 7 键
        条目列表。

        Args:
            path: 待收集目录路径；``"All"`` 表示磁盘视图。
            cancel_check: 可选取消检查回调（后台线程用，返回 True 表示
                请求已过期、应尽快放弃）；仅 Python 回退路径消费。
            include_remote: ``"All"`` 视图的网络/映射盘与光驱开关；其他
                路径忽略。``None`` 时取静态默认（关闭）。
            show_hidden: 是否显示隐藏文件（FILE_ATTRIBUTE_HIDDEN）；``None``
                表示不启用过滤。仅「系统」位（FILE_ATTRIBUTE_SYSTEM 单独
                出现，如重定向后的桌面/下载/音乐等系统文件夹）恒可见。
            show_system: 是否显示系统文件（FILE_ATTRIBUTE_SYSTEM）；仅当
                ``show_hidden`` 亦为真时生效，且只影响同时带「隐藏+系统」
                双重位的受保护操作系统文件/文件夹。

        Returns:
            Optional[List[Dict[str, Any]]]: 7 键条目列表；目录不可读返回
                ``None``。
        """
        if path == "All":
            return FileSelectorLayout._collect_all_drives_python(include_remote)
        # P1.3：仅在需要过滤时收集属性旁路表；native 路径不返回属性位，
        # 留 None 让 ``_apply_hidden_system_filter`` 自行 scandir。
        wants_filter = not (show_hidden is None and show_system is None)
        native_entries = _native_scan_directory(path)
        if native_entries is not None:
            entries = native_entries
            attrs_by_name: Optional[Dict[str, int]] = None
        else:
            attrs_by_name = {} if wants_filter else None
            entries = FileSelectorLayout._collect_directory_entries_python(
                path, cancel_check, attrs_out=attrs_by_name
            )
        if entries is None:
            return None
        return FileSelectorLayout._apply_hidden_system_filter(
            entries, path, show_hidden, show_system, attrs_by_name=attrs_by_name
        )

    @staticmethod
    def _apply_hidden_system_filter(
        entries: List[Dict[str, Any]],
        path: str,
        show_hidden: Optional[bool],
        show_system: Optional[bool],
        attrs_by_name: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """按隐藏/系统文件属性过滤条目（保持原顺序，只删不改）。

        以 ``os.scandir`` 扫一遍目录建立 ``name -> st_file_attributes`` 映射
        （逐条目 stat 失败则跳过该条目；scandir 本身失败则 fail-open 原样
        返回）。无映射的条目（名称缺失）保持可见；``.`` 前缀不算隐藏（仅按
        属性位判定）。过滤口径与 :meth:`_entry_visible_by_attrs` 一致：仅
        「系统」位单独出现的条目恒可见。

        P1.3：若调用方已在条目扫描时同步采集了属性（``attrs_by_name`` 非
        None），则**不再**重复 scandir——这是单遍扫描的收益来源。

        Args:
            entries: 待过滤的 7 键条目列表。
            path: 对应目录路径（仅在需要自行 scandir 时使用）。
            show_hidden: 是否显示隐藏文件；``None`` 表示不过滤。
            show_system: 是否显示系统文件；仅当 ``show_hidden`` 亦为真时生效。
            attrs_by_name: 可选旁路属性表（``name -> st_file_attributes``，
                ``follow_symlinks=False`` 口径）；``None`` 时本方法自行枚举。

        Returns:
            List[Dict[str, Any]]: 过滤后的条目列表。
        """
        if show_hidden is None and show_system is None:
            return entries
        show_hidden = bool(show_hidden)
        show_system = bool(show_system)
        if show_hidden and show_system:
            return entries
        if attrs_by_name is None:
            attrs_by_name = FileSelectorLayout._hidden_system_attrs_map(
                path, show_hidden, show_system
            )
        if attrs_by_name is None:
            return entries
        return [
            entry
            for entry in entries
            if FileSelectorLayout._entry_visible_by_attrs(
                entry, attrs_by_name, show_hidden, show_system
            )
        ]

    @staticmethod
    def _hidden_system_attrs_map(
        path: str,
        show_hidden: bool,
        show_system: bool,
    ) -> Optional[Dict[str, int]]:
        """构建目录的 ``name -> st_file_attributes`` 映射（纯 IO，可后台线程）。

        过滤的一次性 IO 开销集中在此：流式路径逐批过滤复用同一映射，避免按
        批重复 ``scandir``。隐藏与系统文件均需显示（无需过滤）时直接返回
        ``None``；``os.scandir`` 失败同样返回 ``None``（fail-open，原样显示）。
        逐条目 stat 失败则跳过该条目（视为无属性、保持可见）。

        Args:
            path: 目录路径（``"All"`` 磁盘视图不适用，由调用方跳过）。
            show_hidden: 是否显示隐藏文件。
            show_system: 是否显示系统文件。

        Returns:
            Optional[Dict[str, int]]: 属性映射；``None`` 表示无需过滤或过滤
                不可用。
        """
        if show_hidden and show_system:
            return None
        attrs_by_name: Dict[str, int] = {}
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
            return None
        return attrs_by_name

    @staticmethod
    def _entry_visible_by_attrs(
        entry: Dict[str, Any],
        attrs_by_name: Dict[str, int],
        show_hidden: bool,
        show_system: bool,
    ) -> bool:
        """按隐藏/系统属性判断条目是否可见（与过滤函数同口径）。

        口径对齐资源管理器：仅「隐藏」位 → 随 ``show_hidden``；仅「系统」
        位（如重定向后的桌面/下载/音乐等系统文件夹）恒可见；「隐藏+系统」
        双重位（受保护的操作系统文件）需 ``show_hidden`` 与 ``show_system``
        同时开启。

        Args:
            entry: 7 键条目字典。
            attrs_by_name: ``_hidden_system_attrs_map`` 产出的属性映射。
            show_hidden: 是否显示隐藏文件。
            show_system: 是否显示系统文件；仅当 ``show_hidden`` 亦为真时生效。

        Returns:
            bool: True 表示该条目应显示。
        """
        attrs = attrs_by_name.get(entry["name"], 0)
        is_hidden = bool(attrs & _FILE_ATTRIBUTE_HIDDEN)
        is_system = bool(attrs & _FILE_ATTRIBUTE_SYSTEM)
        effective_system = bool(show_system) and bool(show_hidden)
        if is_hidden and not show_hidden:
            return False
        if is_hidden and is_system and not effective_system:
            return False
        return True

    @staticmethod
    def _entry_from_direntry(
        entry: "os.DirEntry",
        attrs_out: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """把 ``os.DirEntry`` 归一化为 7 键条目字典。

        ``_collect_directory_entries_python``（同步/回退路径）与
        ``_iter_directory_batches``（流式路径）共用，保证两条路径的字段
        值与格式完全相同（``follow_symlinks=True`` 与 ``os.path.isdir``
        口径一致，目录的 ``suffix`` 恒为空串）。

        P1.3：传入 ``attrs_out`` 时额外采集 ``st_file_attributes``（**必须**
        用 ``follow_symlinks=False``，与 ``_hidden_system_attrs_map`` 同
        口径——隐藏/系统位属于链接自身）。Windows 上该 stat 直接读
        ``read_dir`` 缓存的 ``WIN32_FIND_DATA``，不产生额外 syscall，因此
        这一遍采集几乎免费，却能省掉一次整目录枚举。**不写入 7 键条目**
        （契约锁定）。

        Args:
            entry: ``os.scandir`` 产出的目录项。
            attrs_out: 可选旁路属性表；传入时写入
                ``name -> st_file_attributes``。

        Returns:
            Dict[str, Any]: 7 键条目字典（name/path/is_dir/size/modified/
                created/suffix）。
        """
        st = entry.stat(follow_symlinks=True)
        is_dir = entry.is_dir(follow_symlinks=True)
        name = entry.name
        if attrs_out is not None:
            try:
                st_no_follow = entry.stat(follow_symlinks=False)
            except OSError:
                st_no_follow = None
            if st_no_follow is not None:
                attrs_out[name] = getattr(st_no_follow, "st_file_attributes", 0)
        suffix = os.path.splitext(name)[1].lower().lstrip(".") if not is_dir else ""
        modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
        return {
            "name": name, "path": entry.path, "is_dir": is_dir,
            "size": st.st_size, "modified": modified, "created": created, "suffix": suffix,
        }

    @staticmethod
    def _collect_directory_entries_python(
        path: str,
        cancel_check=None,
        attrs_out: Optional[Dict[str, int]] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """既有 Python 收集实现（scandir + 逐文件 stat），native 回退路径。

        Args:
            path: 待收集目录路径。
            cancel_check: 可选取消检查回调；每个条目处理前调用，返回 True
                时立即放弃并返回 ``None``（过期结果由 token 侧丢弃）。
            attrs_out: 可选旁路属性表；传入时同步采集
                ``name -> st_file_attributes``（P1.3 单遍扫描）。

        Returns:
            Optional[List[Dict[str, Any]]]: 7 键条目列表；目录不可读返回
                ``None``。
        """
        try:
            entries: List[Dict[str, Any]] = []
            with os.scandir(path) as it:
                for direntry in it:
                    if cancel_check is not None and cancel_check():
                        return None
                    try:
                        entries.append(
                            FileSelectorLayout._entry_from_direntry(
                                direntry, attrs_out=attrs_out
                            )
                        )
                    except (PermissionError, OSError):
                        continue
            return entries
        except (PermissionError, FileNotFoundError, OSError):
            return None

    @staticmethod
    def _iter_directory_batches(
        path: str,
        include_remote: bool,
        cancel_check: Callable[[], bool],
        batch_size: int = 64,
        batch_interval_s: float = 0.04,
        *,
        attrs_out: Optional[Dict[str, int]] = None,
    ) -> Iterator[Tuple[List[Dict[str, Any]], bool]]:
        """渐进式目录扫描入口：优先 native 流式游标，否则 Python 逐批。

        P3.4：DLL 提供 ``faf_scan_*`` 时，由 Rust 持有 ``ReadDir`` 迭代器
        跨批推进（保留 P2.1 的零额外 syscall），并把 Windows 属性位一起
        回传（写进 ``attrs_out``，**不进** 7 键条目）。任何异常/游标不可用
        时立即回退到 :meth:`_iter_directory_batches_python`，语义完全一致。

        Args:
            path: 待扫描目录路径；``"All"`` 表示磁盘视图。
            include_remote: ``"All"`` 视图的网络/映射盘与光驱开关。
            cancel_check: 取消检查回调（返回 True 表示请求已过期）。
            batch_size: 单批最大条目数。
            batch_interval_s: 单批最长等待秒数（仅 Python 路径使用）。
            attrs_out: 可选旁路属性表。

        Yields:
            Tuple[List[Dict[str, Any]], bool]: 一批条目与该批是否为最后一批。
        """
        if NATIVE_STREAM_ENABLED and path != "All" and native_api.supports(
            "scanstream"
        ):
            handle = native_api.scan_begin(path)
            if handle:
                try:
                    yielded = 0
                    while True:
                        if cancel_check():
                            return
                        rows = native_api.scan_next(handle, batch_size)
                        if rows is None:
                            if yielded == 0:
                                # 首批就失败：交给 Python 路径重新开始（无重复发射）。
                                break
                            # 中途失败：按最后一批收尾（已交付批次不回滚）。
                            yield ([], True)
                            return
                        if not rows:
                            yield ([], True)
                            return
                        if attrs_out is not None:
                            for row in rows:
                                attrs_out[row["name"]] = int(row.pop("attrs", 0) or 0)
                        else:
                            for row in rows:
                                row.pop("attrs", None)
                        is_last = len(rows) < batch_size
                        yielded += len(rows)
                        yield (rows, is_last)
                        if is_last:
                            return
                finally:
                    native_api.scan_free(handle)
                if yielded:
                    return
        yield from FileSelectorLayout._iter_directory_batches_python(
            path,
            include_remote,
            cancel_check,
            batch_size,
            batch_interval_s,
            attrs_out=attrs_out,
        )

    @staticmethod
    def _iter_directory_batches_python(
        path: str,
        include_remote: bool,
        cancel_check: Callable[[], bool],
        batch_size: int = 64,
        batch_interval_s: float = 0.04,
        *,
        attrs_out: Optional[Dict[str, int]] = None,
    ) -> Iterator[Tuple[List[Dict[str, Any]], bool]]:
        """渐进式目录扫描生成器（纯 Python oracle / 回退路径）。

        纯 IO：不读取任何 Qt/UI 状态，可在后台线程运行。``"All"`` 视图一次
        枚举全部盘符并单批发完（``os.scandir`` 不适用于盘符视图）。普通目录
        以 ``os.scandir`` 迭代，批满 ``batch_size`` 或距上次发射超过
        ``batch_interval_s`` 即发一批；无论如何收尾必发 ``(batch, True)``
        （空目录的唯一发射即 ``([], True)``）。每次迭代顶部检查
        ``cancel_check()``，为 True 立即 ``return``（``with`` 关闭句柄）。
        打开目录失败（权限/不存在）时异常向上抛出（零批），由调用方转成
        错误信号。

        Args:
            path: 待扫描目录路径；``"All"`` 表示磁盘视图。
            include_remote: ``"All"`` 视图的网络/映射盘与光驱开关；其他
                路径忽略。
            cancel_check: 取消检查回调（返回 True 表示请求已过期）。
            batch_size: 单批最大条目数。
            batch_interval_s: 单批最长等待秒数（与 ``batch_size`` 先到为准）。
            attrs_out: 可选旁路属性表；传入时每条目同步写入
                ``name -> st_file_attributes``（P1.3 单遍扫描），
                写入发生在 ``yield`` **之前**，保证消费方可直接过滤本批。

        Yields:
            Tuple[List[Dict[str, Any]], bool]: 一批条目与该批是否为最后一批。
        """
        if path == "All":
            entries = FileSelectorLayout._collect_all_drives_python(include_remote)
            yield (entries, True)
            return
        batch: List[Dict[str, Any]] = []
        last_emit: float = time.monotonic()
        with os.scandir(path) as it:
            for direntry in it:
                if cancel_check():
                    return
                try:
                    batch.append(
                        FileSelectorLayout._entry_from_direntry(
                            direntry, attrs_out=attrs_out
                        )
                    )
                except OSError:
                    continue
                now = time.monotonic()
                if len(batch) >= batch_size or (now - last_emit) >= batch_interval_s:
                    yield (batch, False)
                    batch = []
                    last_emit = now
        yield (batch, True)

    def _load_directory(self, path: str) -> None:
        """同步加载目录（收集 + 应用），行为与旧实现逐字节等价。

        仅供测试与特殊同步场景使用；交互式导航请走 ``_load_directory_async``
        （后台线程收集，不阻塞 UI 线程）。
        """
        entries = self._collect_directory_entries(
            path,
            include_remote=self._include_remote_drives,
            show_hidden=self._show_hidden_files,
            show_system=self._show_system_files,
        )
        if entries is None:
            self._file_list.setUpdatesEnabled(False)
            try:
                self._file_model.clear()
                self._current_path = ""
                self.reset_nav_state()
                self._update_file_count(0)
            finally:
                self._file_list.setUpdatesEnabled(True)
            self._file_list.viewport().update()
            return
        self._apply_directory_entries(path, entries)

    def _apply_directory_entries(self, path: str, entries: List[Dict[str, Any]]) -> None:
        """在主线程应用收集到的目录条目：过滤 + 排序 + 更新 model/路径/计数。

        entries 原样（未筛选未排序）复制保存到 ``_raw_entries`` 缓存并绑定
        ``_raw_entries_path``，供排序切换/筛选应用做内存重排（不重扫磁盘）。
        """
        self._raw_entries = list(entries)
        self._raw_entries_path = path
        # P7.3：切目录后旧目录的缩略图/视频帧不再可见，主动收缩缓存。
        self._shrink_thumbnail_caches("navigate")
        # A4 批量纪律：model 重置 + 网格尺寸 + 路径输入 + 计数标签合并为一次重绘，
        # 目录切换非动画帧，此处 setUpdatesEnabled 批量安全。
        file_list = self._file_list
        file_list.setUpdatesEnabled(False)
        try:
            if self._filter_pattern:
                entries = [e for e in entries if self._matches_filter(e["name"])]
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            self._apply_sort(entries)
            self._file_model.set_files(entries)
            self._update_grid_size()
            self._current_path = path
            self.reset_nav_state()
            if not self._path_input_dirty:
                # 路径框正在编辑（未提交）时不覆盖用户输入；失焦时会回填到 _current_path
                self._update_path_input(path)
            self._update_file_count(len(entries))
        finally:
            file_list.setUpdatesEnabled(True)
        file_list.viewport().update()

    # ── 加载指示器 ────────────────────────────────────────────────────────

    def _start_loading_indicator(self) -> None:
        """进入加载态：启动延迟显示计时器（到点才显示遮罩与「加载中…」）。"""
        self._loading_show_timer.start(DIR_LOADING_INDICATOR_DELAY_MS)

    def _on_loading_indicator_timeout(self) -> None:
        """延迟计时器到点：显示加载遮罩并把条目计数切成「加载中…」。"""
        self._loading_overlay.fit_to_parent()
        self._loading_overlay.raise_()
        self._loading_overlay.show()
        self._file_count_label.setText("加载中…")

    def _stop_loading_indicator(self) -> None:
        """退出加载态：取消未到点的延迟显示并隐藏遮罩（幂等）。

        无条件调用 ``hide()``：``isVisible()`` 在父链未显示（启动阶段面板
        尚未 show）时恒为 False，若据此跳过隐藏，会在面板随后显示时让
        遮罩错误地闪现。
        """
        self._loading_show_timer.stop()
        self._loading_overlay.hide()

    # ── 异步目录加载 ──────────────────────────────────────────────────────

    def _load_directory_async(
        self,
        path: str,
        direction: int = 0,
        *,
        initial: bool = False,
        rollback_history: bool = False,
    ) -> None:
        """异步加载目录（流式）：后台线程分批扫描，主线程缓冲/原子落地。

        所有交互式导航（进入子目录/返回/刷新/路径框/收藏夹/定位）与启动
        首次加载统一走本入口：请求即返回，UI 线程零文件 IO。递增 token
        保证快速连续导航只应用最后一次请求的结果；过期任务在扫描迭代中经
        ``cancel_check`` 立即退出（``os.scandir`` 句柄随 ``with`` 关闭）。

        首帧呈现策略（OPT-002 Phase 1）：扫描期间批次先进缓冲窗口——
        收尾批到达、或窗口内积满 ``DIR_STREAM_HOLD_MAX_ENTRIES`` 条、
        或超过 ``DIR_STREAM_HOLD_MAX_MS`` 仍未收尾（网络盘/超大盘），才
        首次落地；前两者单次 ``set_files(最终排序结果)``（首帧即最终帧），
        后者先落地已缓冲部分并转渐进模式。计数标签立即切到「加载中… N」，
        但**不显示**压暗遮罩（遮罩会盖住正在到达的卡片）；遮罩延迟计时器
        仍启动，由首帧落地（``_present_first_frame``）取消，故仅慢目录
        首帧前偶尔一闪、首帧到达即撤下。

        Args:
            path: 待加载目录路径，或 ``"All"`` 磁盘视图。
            direction: 路径过渡方向（进入 1 / 返回 -1 / 无动画 0）；仅当
                ``begin_path_transition`` 成功启动时才应传非 0。
            initial: 是否为启动首次加载（失败时回退到 All 视图）。
            rollback_history: 失败时是否回滚已压入的历史栈条目
                （显式导航 True；刷新/返回 False）。
        """
        self._async_load_token += 1
        token = self._async_load_token
        self._pending_transition_direction = direction
        self._pending_initial_load = initial
        self._pending_history_rollback = rollback_history
        self._pending_locate_path = ""
        self._stream_active_token = token
        self._reset_stream_pipeline(path)
        self._update_path_input(path)
        self._set_count_loading(0)
        self._start_loading_indicator()
        thread_pools.pool("interactive").start(
            _DirectoryStreamRunnable(
                self,
                path,
                token,
                self._include_remote_drives,
                self._show_hidden_files,
                self._show_system_files,
            )
        )

    def _on_dir_batch_ready(
        self,
        path: str,
        entries: Optional[List[Dict[str, Any]]],
        token: int,
        is_final: bool,
    ) -> None:
        """流式批次落地槽（主线程）：缓冲窗口内先积聚、收尾原子落地；超窗转渐进。

        小目录（本地绝大多数）扫描在缓冲窗口（``DIR_STREAM_HOLD_MAX_MS``）
        内收尾，条目只落地一次且已是最终序——路径过渡快照永远是完整最终
        帧，不再出现"未排序首帧 → 收尾重排"的卡片跳闪。慢目录（网络盘/
        超大盘）超过窗口（时长或 ``DIR_STREAM_HOLD_MAX_ENTRIES`` 条）后
        转渐进模式，保住"先进入、慢慢加载"的体验。

        ``entries is None`` 表示"零批/中途错误"：缓冲为空 → 保留旧视图并
        回滚；缓冲非空 → 落地已读到的部分（与旧"不回溯已落地批次"语义
        一致，不丢数据）。

        Args:
            path: 批次所属目录路径。
            entries: 本批条目；``None`` 表示错误。
            token: 异步加载世代 token。
            is_final: 本批是否为最后一批。
        """
        if token != self._async_load_token or self._stream_active_token != token:
            # 过期世代（已被新导航取代）或本世代已收尾/中止：批次一律丢弃
            return

        if self._stream_holding:
            if entries is None:
                if self._stream_hold_entries:
                    # 缓冲期已读到部分条目后失败：落地已读到部分并正常收尾
                    self._present_first_frame(path, token, streaming=True)
                    self._finalize_stream(path, token)
                else:
                    self._abort_stream_keep_old(path, token)
                return
            self._stream_hold_entries.extend(entries)
            if not is_final:
                if path != "All":
                    self._set_count_loading(self._count_held_display())
                expired = (
                    (time.monotonic() - self._stream_hold_start) * 1000.0
                    >= DIR_STREAM_HOLD_MAX_MS
                )
                if (
                    len(self._stream_hold_entries) >= DIR_STREAM_HOLD_MAX_ENTRIES
                    or expired
                ):
                    # 超过缓冲窗口：转渐进模式，已缓冲部分先落地
                    self._present_first_frame(path, token, streaming=True)
                return
            # 收尾批在缓冲窗口内到达：一次成型（首帧即最终序，无二次重排）
            self._present_first_frame(path, token, streaming=False)
            self._finalize_stream(path, token, already_settled=True)
            return

        # 渐进模式（首帧已落地）
        if entries and path != "All":
            self._queue_stream_batch(entries)
        if is_final:
            self._flush_stream_batches()
            self._finalize_stream(path, token)

    def _present_first_frame(
        self, path: str, token: int, *, streaming: bool
    ) -> None:
        """首次落地（原子/渐进共用）：跳转目标目录并按最终序呈现首帧。

        ``streaming=False``：收尾批在缓冲窗口内到达，单次 ``set_files``
        即为最终序（唯一一次重绘，无跳变）；``streaming=True``：超窗/
        中途失败转渐进，先落地已缓冲部分（其相对序即最终序在该子集上的
        投影），后续批次经合帧缓冲渐进追加。

        两种模式均在路径过渡快照捕获前同步完成挂起布局，避免 ``Batched``
        布局下快照只含部分卡片（缺卡/错位）。

        Args:
            path: 目标目录路径或 ``"All"``。
            token: 异步加载世代 token。
            streaming: 是否为"超窗/失败转渐进"的首次落地。
        """
        if self._stream_started_token == token:
            return
        self._stream_started_token = token
        self._stream_holding = False
        self._stream_hold_timer.stop()
        direction = self._pending_transition_direction
        self._pending_transition_direction = 0
        self._pending_initial_load = False
        self._pending_history_rollback = False
        self._stop_loading_indicator()
        batch = self._stream_hold_entries
        self._stream_hold_entries = []
        self._stream_hold_path = ""
        debug(
            f"目录首帧落地（{'渐进' if streaming else '原子'}）: {path} "
            f"共 {len(batch)} 条"
        )
        if path == "All":
            self._stream_all_entries = list(batch)
            self._apply_all_entries(batch)
        else:
            self._current_path = path
            self._raw_entries = list(batch)
            self._raw_entries_path = path
            self.reset_nav_state()
            display = self._sorted_filtered_raw()
            file_list = self._file_list
            file_list.setUpdatesEnabled(False)
            try:
                self._file_model.set_files(display)
                self._update_grid_size()
                self._update_path_input(path)
                self._set_count_loading(len(display))
            finally:
                file_list.setUpdatesEnabled(True)
            file_list.viewport().update()
        if direction != 0:
            # 快照前同步完成布局：Batched 模式下入帧快照可能只含部分卡片
            self._file_list.flush_pending_layout()
            self._file_list.finish_path_transition(direction)

    def _on_stream_hold_timeout(self) -> None:
        """缓冲窗口到时（毫秒计时器）：已缓冲条目立即转渐进落地。

        空缓冲时保留缓冲态，等首批到达时由 ``_on_dir_batch_ready`` 的
        超窗分支直接转渐进（避免慢盘"第一条"还要再等一个窗口）。
        """
        if not self._stream_holding or not self._stream_hold_entries:
            return
        token = self._stream_active_token
        if token < 0:
            return
        self._present_first_frame(self._stream_hold_path, token, streaming=True)

    def _queue_stream_batch(self, entries: List[Dict[str, Any]]) -> None:
        """渐进模式：批次入合帧缓冲，按帧一次性结算（减少逐批 relayout）。

        Args:
            entries: 本批原始条目（后台已完成隐藏/系统过滤）。
        """
        self._raw_entries.extend(entries)
        if len(self._stream_pending_batches) >= DIR_STREAM_MAX_PENDING_BATCHES:
            self._stream_pending_batches.pop(0)
            try:
                from freeassetfilter.utils.perf_metrics import increment_global

                increment_global("dir_stream.batch_dropped")
            except Exception:  # noqa: BLE001 - 埋点不得影响流式路径
                pass
        self._stream_pending_batches.append(entries)
        if not self._stream_flush_timer.isActive():
            # 首屏首批立即结算（典型为 0ms 定时器）：早一帧上屏，避免
            # “转圈结束后网格空白”的观感。后续批次仍 16ms 合帧。
            first_landing = self._file_model.rowCount() == 0
            self._stream_flush_timer.start(
                0 if first_landing else DIR_STREAM_FLUSH_INTERVAL_MS
            )

    def _flush_stream_batches(self) -> None:
        """结算合帧缓冲中的全部批次（一次插入 + 一次重绘），刷新加载计数。

        收尾（``_finalize_stream``）会先同步调用本方法再清 token，保证
        挂起批次不丢；定时器晚到触发时缓冲已空则直接返回。
        """
        self._stream_flush_timer.stop()
        batches = self._stream_pending_batches
        if not batches:
            return
        self._stream_pending_batches = []
        if self._stream_active_token < 0:
            return
        display = [
            e
            for batch in batches
            for e in batch
            if self._matches_filter(e["name"])
        ]
        if not display:
            return
        file_list = self._file_list
        file_list.setUpdatesEnabled(False)
        try:
            self._file_model.append_files(display)
        finally:
            file_list.setUpdatesEnabled(True)
        file_list.viewport().update()
        self._set_count_loading(self._file_model.rowCount())

    def _count_held_display(self) -> int:
        """缓冲窗口内已读条目按当前筛选口径的可展示数（计数标签反馈用）。"""
        if not self._filter_pattern:
            return len(self._stream_hold_entries)
        return sum(
            1 for e in self._stream_hold_entries if self._matches_filter(e["name"])
        )

    def _reset_stream_pipeline(self, path: str) -> None:
        """复位流式管线并开启缓冲窗口（派发新请求时调用）。

        Args:
            path: 本次请求目标路径（超时落地时定位用）。
        """
        self._stream_holding = True
        self._stream_hold_entries = []
        self._stream_hold_path = path
        self._stream_hold_start = time.monotonic()
        self._stream_pending_batches = []
        self._stream_flush_timer.stop()
        self._stream_hold_timer.start(DIR_STREAM_HOLD_MAX_MS)

    def _clear_stream_pipeline(self) -> None:
        """停止流式管线计时器并清空缓冲（收尾/中止共用，幂等）。"""
        self._stream_holding = False
        self._stream_hold_entries = []
        self._stream_hold_path = ""
        self._stream_hold_timer.stop()
        self._stream_pending_batches = []
        self._stream_flush_timer.stop()

    def _finalize_stream(
        self, path: str, token: int, *, already_settled: bool = False
    ) -> None:
        """流式收尾：停用流式态、恢复计数、补挂定位。

        ``already_settled=True``（缓冲窗口内收尾批原子落地）：模型已经是
        最终序，此处不再重排/重设网格——首帧与最终帧完全一致，无跳变；
        否则（渐进模式）：先结算合帧缓冲，再按最终筛选/排序口径核对重排
        （``apply_order`` 只重排不删减；期间口径变更过则整表重建）。

        Args:
            path: 完成的目录路径或 ``"All"``。
            token: 异步加载世代 token。
            already_settled: 模型是否已处于最终展示序（原子落地路径）。
        """
        if self._stream_active_token != token:
            return
        self._stop_loading_indicator()
        if not already_settled:
            # 先结算挂起批次（flush 以 token 判定世代，必须在清 token 前）
            self._flush_stream_batches()
        self._stream_active_token = -1
        self._clear_stream_pipeline()
        if already_settled or path == "All":
            final_n = self._file_model.rowCount()
        else:
            settled = self._sorted_filtered_raw()
            settled_paths = [e["path"] for e in settled]
            model = self._file_model
            consistent = (
                model.rowCount() == len(settled_paths)
                and all(model.get_row(p) >= 0 for p in settled_paths)
            )
            if consistent:
                model.apply_order(settled_paths)
            else:
                # 流式期间筛选条件变更过：增量追加的成员集与最终集合不一致，
                # 需整表重建到最终集合（apply_order 只重排不删减）。
                model.set_files(settled)
            self._update_grid_size()
            final_n = len(settled)
        self._update_file_count(final_n)
        if self._pending_locate_path:
            self._handle_pending_locate()
        legacy_entries = (
            self._stream_all_entries if path == "All" else list(self._raw_entries)
        )
        self._dir_entries_ready.emit(path, legacy_entries, token)

    def _abort_stream_keep_old(self, path: str, token: int) -> None:
        """零批错误：保留旧视图，取消过渡，按需回退历史/回退到 All。

        Args:
            path: 加载失败的目标路径。
            token: 异步加载世代 token。
        """
        self._stream_active_token = -1
        self._stream_started_token = token
        self._clear_stream_pipeline()
        self._stop_loading_indicator()
        initial = self._pending_initial_load
        rollback_history = self._pending_history_rollback
        self._pending_transition_direction = 0
        self._pending_initial_load = False
        self._pending_history_rollback = False
        self._pending_locate_path = ""
        self._file_list.cancel_path_transition()
        self._update_file_count(self._file_model.rowCount())
        if initial:
            debug(f"启动恢复路径不可读，回退到 All 视图: {path}")
            self._navigate_to_all()
            return
        if rollback_history:
            self._rollback_failed_navigation(path)
        debug(f"目录加载失败，保留当前视图: {path}")

    def _on_dir_entries_ready(
        self, path: str, entries: Optional[List[Dict[str, Any]]], token: int
    ) -> None:
        """后台收集完成（主线程槽）：过期结果直接丢弃，否则应用并收尾。

        成功：应用条目（All 视图走 ``_apply_all_entries``）→ 播放挂起的
        路径过渡动画 → 处理挂起定位请求；失败：取消过渡、保留当前目录
        视图（回滚路径框/历史/last_path），启动首次加载失败则回退到
        All 视图。流式管线已应用过的 token（``_stream_started_token`` 命中）
        在此直接返回——该信号在流式路径中仅作向后兼容广播。
        """
        if token != self._async_load_token:
            return
        if self._stream_started_token == token:
            return
        if self._stream_active_token == token:
            # 兼容路径（生产交互不经过）：本世代结果由此落地，终止流式管线
            self._stream_active_token = -1
            self._clear_stream_pipeline()
        direction = self._pending_transition_direction
        initial = self._pending_initial_load
        rollback_history = self._pending_history_rollback
        self._pending_transition_direction = 0
        self._pending_initial_load = False
        self._pending_history_rollback = False
        self._stop_loading_indicator()

        if entries is None:
            self._file_list.cancel_path_transition()
            self._pending_locate_path = ""
            self._update_file_count(self._file_model.rowCount())
            if initial:
                debug(f"启动恢复路径不可读，回退到 All 视图: {path}")
                self._navigate_to_all()
                return
            if rollback_history:
                self._rollback_failed_navigation(path)
            debug(f"目录加载失败，保留当前视图: {path}")
            return

        if path == "All":
            self._apply_all_entries(entries)
        else:
            self._apply_directory_entries(path, entries)
        if direction != 0:
            self._file_list.finish_path_transition(direction)
        self._handle_pending_locate()

    def _rollback_failed_navigation(self, path: str) -> None:
        """交互导航失败：回滚历史栈/路径框/last_path（保留当前目录视图）。

        Args:
            path: 加载失败的目标路径。
        """
        if (
            self._nav_history
            and 0 <= self._history_index < len(self._nav_history)
            and self._same_selector_path(self._nav_history[self._history_index], path)
        ):
            self._nav_history.pop(self._history_index)
            self._history_index = len(self._nav_history) - 1
        self._update_path_input(self._current_path)
        if self._current_path and self._current_path != "All":
            self._save_last_path(self._current_path)
        else:
            self._clear_last_path()

    def _handle_pending_locate(self) -> None:
        """应用挂起的定位请求：条目落地后高亮目标卡片并滚动到可见。"""
        file_path = self._pending_locate_path
        if not file_path:
            return
        self._pending_locate_path = ""
        model_file_path = self._locate_model_file_path(file_path)
        if not model_file_path:
            return
        self.set_previewing_file(model_file_path)
        # 目录过渡动画（120ms）结束后再滚动，避免与过渡快照错位
        QTimer.singleShot(180, lambda p=model_file_path: self._scroll_to_file(p))

    @staticmethod
    def _shrink_thumbnail_caches(reason: str) -> None:
        """在切目录时主动收缩缩略图缓存（P7.3）。

        惰性导入 + 全异常吞掉：缓存收缩是纯收益动作，不得影响导航。

        Args:
            reason: 触发原因（写入性能元数据）。
        """
        try:
            from freeassetfilter.core.managers.thumbnail_manager import (
                ThumbnailManager,
            )

            manager = getattr(ThumbnailManager, "_instance", None)
            if manager is not None:
                manager.shrink_caches(reason)
        except Exception:  # noqa: BLE001 - 收缩失败不得影响导航
            pass

    def _apply_sort(self, entries: List[Dict[str, Any]]) -> None:
        mode = self._sort_mode
        if mode == 0:
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        elif mode == 1:
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()), reverse=True)
        elif mode == 2:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")), reverse=True)
        elif mode == 3:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("modified", "")))
        elif mode == 4:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)), reverse=True)
        elif mode == 5:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("size", 0)))
        elif mode == 6:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("created", "")), reverse=True)
        elif mode == 7:
            entries.sort(key=lambda x: (not x["is_dir"], x.get("created", "")))

    def _sort_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """排序条目列表（native 门控；P0 实测后默认走纯 Python）。

        口径与 ``_apply_directory_entries`` 逐字节一致：

        * mode 2–7：**必须**先按 ``(not is_dir, name.lower())`` 稳定预排序
          ——native 与 Python 的稳定排序都保持 equal-key 的输入序，而输入
          序来自 ``read_dir``（非确定），预排序是平局确定性的唯一来源；
        * mode 0/1：排序键与预排序键完全相同，预排序纯冗余，跳过。

        native 路径默认关闭（``NATIVE_SORT_ENABLED=False``）：P0 实测其
        JSON 往返成本高于 Python 排序本身（2000 条 ≥3.1ms vs 0.32ms），
        且大目录会先撞 8MB 上限再整体回退（30k 条白烧 115.2ms）。

        Args:
            entries: 7 键条目列表（不被就地修改）。

        Returns:
            List[Dict[str, Any]]: 排序后的条目列表。
        """
        entries = list(entries)
        mode = self._sort_mode
        if mode >= 2:
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        if NATIVE_SORT_ENABLED and len(entries) >= NATIVE_SORT_MIN_ENTRIES:
            native = _native_sort_entries(entries, mode)
            if native is not None:
                return native
        self._apply_sort(entries)
        return entries

    def _filter_entries(
        self, entries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """按当前筛选正则过滤条目（无正则时返回浅拷贝）。

        ``_apply_entries_in_memory`` 与流式收尾（``_finalize_stream``）共用，
        保证两条路径的筛选口径一致。

        Args:
            entries: 7 键条目列表。

        Returns:
            List[Dict[str, Any]]: 过滤后的条目列表（新列表，元素为原对象）。
        """
        if not self._filter_pattern:
            return list(entries)
        return [e for e in entries if self._matches_filter(e["name"])]

    def _sorted_filtered_raw(self) -> List[Dict[str, Any]]:
        """从 raw 缓存计算最终展示序（筛选 + 排序），不写模型。

        与 ``_apply_entries_in_memory`` 的管线一致：筛选 → 内存排序
        （``_sort_entries`` 内部会复制列表再排）。

        P3.6/P7.3：**不再逐条 ``dict(e)`` 深拷**——``_filter_entries`` 已返回
        新列表（元素为原字典），``_sort_entries`` 又复制一份再排序，两者都
        只动顺序不动字典，因此 10k 条目可省掉一次全量字典构造（约 6ms +
        2MB 瞬时峰值）。

        Returns:
            List[Dict[str, Any]]: 最终展示顺序的条目列表。
        """
        entries = self._filter_entries(self._raw_entries)
        return self._sort_entries(entries)

    def _apply_entries_in_memory(self) -> None:
        """从 raw 缓存内存重排（筛选 + 排序）并更新 model/网格/计数，不重扫磁盘。

        排序切换与筛选应用（``_set_sort_mode`` / ``_apply_filter_or_reload``）
        共用：复制原始条目 → Python 侧 ``_matches_filter`` 筛选 → 内存排序
        （native ``faf_sort_entries`` 优先，否则 ``_apply_sort``）。仅在
        ``_raw_entries_path == _current_path`` 且非 "All" 时调用。
        """
        sorted_entries = self._sorted_filtered_raw()
        file_list = self._file_list
        file_list.setUpdatesEnabled(False)
        try:
            self._file_model.set_files(sorted_entries)
            self._update_grid_size()
            self._update_file_count(len(sorted_entries))
        finally:
            file_list.setUpdatesEnabled(True)
        file_list.viewport().update()

    def _apply_filter_or_reload(self) -> None:
        """筛选应用/清除后：raw 缓存可用则内存重排，否则回退重扫磁盘。

        仅当 ``_current_path`` 非空非 "All" 且缓存与当前路径绑定一致时走
        内存重排；"All" 视图（``_load_all`` 不写 raw 缓存）与缓存缺失场景
        保持既有重扫行为（刷新语义）。流式加载进行中时直接返回——调用方已
        更新 ``_filter_pattern``，收尾时按最新正则重derive 最终集合。
        """
        if self._stream_active_token == self._async_load_token:
            return
        if (
            self._current_path
            and self._current_path != "All"
            and self._raw_entries_path == self._current_path
        ):
            self._apply_entries_in_memory()
        else:
            self._reload_directory()

    # ── 导航 ──────────────────────────────────────────────────────────────

    def _navigate_to(
        self, path: str, *, transition: bool = True, initial: bool = False
    ) -> bool:
        """导航到指定目录（异步加载，请求即返回，UI 线程不阻塞）。

        请求时立即压历史栈/更新路径框/保存 last_path；目录条目由后台线程
        收集，完成后回主线程应用并播放过渡动画。

        Args:
            path: 目标目录路径。
            transition: 是否尝试播放路径过渡动画（启动首次加载传 False）。
            initial: 是否为启动首次加载（加载失败时回退到 All 视图）。

        Returns:
            bool: True 表示已发出加载请求；False 表示路径不是目录。
        """
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return False
        direction = 0
        if transition:
            inferred = self._infer_navigation_direction(self._current_path, path)
            if inferred != 0 and self._file_list.begin_path_transition(inferred):
                direction = inferred
        self._load_directory_async(
            path, direction, initial=initial, rollback_history=True
        )
        if self._history_index >= 0 and self._history_index < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[:self._history_index + 1]
        self._nav_history.append(path)
        self._history_index = len(self._nav_history) - 1
        self._save_last_path(path)
        return True

    def _navigate_to_input_path(self) -> None:
        """路径框跳转：空输入/字面 All 回 All 视图；无效路径弹提示；成功后取消输入焦点。

        无效路径弹窗确认关闭后立即回填当前显示路径（不保留无效文本）。
        """
        path = self._path_input.text().strip()
        # 显式跳转尝试：清除"未提交编辑"标记，失焦时不再回填当前路径
        self._path_input_dirty = False
        if not path or path.lower() == "all":
            # 空输入或字面 "all"（不分大小写，与 All 视图下路径框显示值一致）→ All 视图
            self._navigate_to_all()
            self._path_input.clearFocus()
            return
        if self._navigate_to(path):
            self._path_input.clearFocus()
        else:
            self._show_message_dialog(
                "无效路径",
                "该路径不存在，请检查后重新输入",
                on_closed=self._on_invalid_path_dialog_closed,
            )

    def _on_invalid_path_dialog_closed(self) -> None:
        """无效路径弹窗关闭：立即回填当前显示路径并把焦点转交文件列表。

        弹窗关闭时系统会把焦点还原给路径框，主动转交文件列表可避免
        路径框被自动聚焦。
        """
        self._update_path_input(self._current_path)
        self._file_list.setFocus()

    def _on_path_input_text_edited(self, _text: str) -> None:
        """用户手动编辑路径框：标记未提交编辑（失焦时回填当前显示路径）。

        Args:
            _text: 编辑后的文本（不使用，仅用于匹配 textEdited 信号签名）。
        """
        self._path_input_dirty = True

    def _on_path_input_focus_out(self) -> None:
        """路径框失焦：未提交跳转的手动编辑回填为当前显示路径。"""
        if self._path_input_dirty:
            self._update_path_input(self._current_path)

    def _reload_directory(self) -> None:
        """刷新当前目录（异步重扫；不重排历史栈、不改 last_path）。"""
        if self._current_path == "All":
            self._load_directory_async("All", 0, initial=False)
        elif self._current_path:
            self._load_directory_async(self._current_path, 0, initial=False)

    def set_include_remote_drives(self, enabled: bool) -> None:
        """设置「All」视图是否包含网络/映射盘与光驱（设置提交路径调用；幂等）。

        开关在派发异步收集任务时快照传入后台线程；若当前正停留在
        「All」视图则立即重扫以体现新口径。

        Args:
            enabled: True 额外列出 DRIVE_REMOTE 与 DRIVE_CDROM。
        """
        enabled = bool(enabled)
        if enabled == self._include_remote_drives:
            return
        self._include_remote_drives = enabled
        if self._current_path == "All":
            self._reload_directory()

    def set_blank_right_click_go_back(self, enabled: bool) -> None:
        """设置「空白区右键返回上一级」开关（启动与设置提交路径调用；幂等）。

        开启后，右键仅在满足以下全部条件时返回上一级：当前页面无需滚动
        （垂直滚动条无滚动范围）、点击落在空格子的卡片脚印区域内（卡片本体
        本该占据的矩形，不含卡片间缝隙与格子边缘间距）。关闭时空白区右键
        不做任何导航，仅清除框选。

        Args:
            enabled: True 开启空白区右键返回；False 关闭（默认）。
        """
        self._blank_right_click_go_back = bool(enabled)

    def set_show_hidden_files(self, enabled: bool) -> None:
        """设置「显示隐藏文件」开关（启动与设置提交路径调用；幂等）。

        关闭时同步关闭「显示系统文件」（系统文件可见性以隐藏文件开关为
        前提）；任一口径变化且当前处于普通目录视图时立即重扫以体现新口径。

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
        """设置「显示系统文件」开关（启动与设置提交路径调用；幂等）。

        仅当「显示隐藏文件」亦开启时生效（AND 语义），且只影响同时带
        「隐藏+系统」双重位的受保护操作系统文件/文件夹；口径变化且当前处于
        普通目录视图时立即重扫以体现新口径。

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
        """隐藏/系统过滤口径变化后，若当前处于普通目录视图则重扫。"""
        if self._current_path and self._current_path != "All":
            self._reload_directory()

    def _load_directory_with_transition(self, path: str, direction: int) -> None:
        """带路径过渡动画的异步目录加载。

        先捕获旧视图快照进入等待态，随后异步收集目录条目；条目落地后由
        ``_on_dir_entries_ready`` 播放过渡（finish）。begin 未成功启动
        （不可见/快照为空）时静默退化为无动画加载；不等待图标/缩略图，
        不增加额外 IO。

        Args:
            path: 要加载的目录绝对路径。
            direction: 过渡方向（>0 前进，<0 后退，0 不做动画）。
        """
        started = direction != 0 and self._file_list.begin_path_transition(direction)
        self._load_directory_async(path, direction if started else 0)

    def _go_back(self) -> None:
        """返回上级：历史栈命中、parent 回退、盘符根回退到 All。

        所有路径统一触发 direction=-1 的过渡动画；历史命中 All 时
        直接委托 `_navigate_to_all`（其内部已有动画），避免双重 begin。
        历史栈与落盘语义与原实现保持一致。
        """
        if self._history_index > 0:
            self._history_index -= 1
            path = self._nav_history[self._history_index]
            if path == "All":
                self._navigate_to_all()
                return
            self._load_directory_with_transition(path, -1)
            self._save_last_path(path)
            return
        elif self._current_path and self._current_path != "All":
            # 向上回退到上级目录，替换历史栈防止循环
            parent = os.path.dirname(self._current_path)
            if parent and parent != self._current_path and os.path.isdir(parent):
                self._load_directory_with_transition(parent, -1)
                self._nav_history = [parent]
                self._history_index = 0
                self._save_last_path(parent)
            elif parent == self._current_path:
                # 盘符根目录（如 D:\）：跳到 All 视图
                self._navigate_to_all()

    def _infer_navigation_direction(self, source_path: str, target_path: str) -> int:
        """根据源路径和目标路径推断导航方向。

        Returns:
            1 表示进入子目录/前进（新内容从右侧进入），
            -1 表示返回上级/后退（新内容从左侧进入），
            0 表示方向不确定或无需动画。
        """
        if self._same_selector_path(source_path, target_path):
            return 0
        if source_path == "All" and target_path != "All":
            return 1
        if target_path == "All":
            return -1
        if self._is_descendant_selector_path(target_path, source_path):
            return 1
        if self._is_descendant_selector_path(source_path, target_path):
            return -1
        return 1

    @staticmethod
    def _same_selector_path(left: str, right: str) -> bool:
        if left == right:
            return True
        if not left or not right or left == "All" or right == "All":
            return False
        try:
            return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_descendant_selector_path(candidate_path: str, base_path: str) -> bool:
        if not candidate_path or not base_path or candidate_path == "All" or base_path == "All":
            return False
        try:
            candidate = os.path.normcase(os.path.normpath(candidate_path))
            base = os.path.normcase(os.path.normpath(base_path))
            if candidate == base:
                return False
            return os.path.commonpath([candidate, base]) == base
        except (OSError, TypeError, ValueError):
            return False

    # ── 文件选择 ──────────────────────────────────────────────────────────

    def _on_file_clicked(self, index) -> None:
        """点击文件 = 预览（先清除框选选中态）。

        再次点击当前预览文件 = 取消预览；点击目录 = 进入目录。
        """
        # 左键单击任意卡片：清除框选选中态（"点击其他地方"即取消多选）
        self.clear_box_selection()
        file_path = self._file_model.data(index, FilePathRole)
        if not file_path:
            return
        is_dir = bool(self._file_model.data(index, IsDirRole))
        if is_dir:
            self._navigate_to(file_path)
            return
        # 文件信息字典统一由 _build_file_info_for_path 构造（与方向键导航
        # 释放共用，单一事实来源）。file_path 取自模型行，正常不会为 None。
        info = self._build_file_info_for_path(file_path)
        # 再次点击当前预览文件 → 取消预览；否则预览
        import os

        if (self._previewing_file_path
                and os.path.normcase(os.path.normpath(self._previewing_file_path))
                == os.path.normcase(os.path.normpath(file_path))):
            self.preview_cancel_requested.emit()
        else:
            if info is not None:
                self.file_selected.emit(info)

    def _build_file_info_for_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        """构造 ``file_selected`` 信号使用的 7 键文件信息字典。

        单一事实来源：点击预览（``_on_file_clicked``）与方向键手势释放
        （``handle_nav_key_release``）共用，避免两处重复维护字典结构。

        Args:
            file_path: 模型内条目的完整路径（须与 ``FilePathRole`` 值精确
                匹配；``get_row`` 为精确字典查找）。

        Returns:
            Optional[Dict[str, Any]]: name/path/is_dir/size/modified/created/
            suffix 字典；路径不在当前模型中返回 None。
        """
        row = self._file_model.get_row(file_path)
        if row < 0:
            return None
        idx = self._file_model.index(row, 0)
        return {
            "name": self._file_model.data(idx, FileNameRole) or "",
            "path": file_path,
            "is_dir": False,
            "size": int(self._file_model.data(idx, FileSizeRole) or 0),
            "modified": self._file_model.data(idx, ModifiedRole) or "",
            "created": self._file_model.data(idx, CreatedRole) or "",
            "suffix": (self._file_model.data(idx, SuffixRole) or "").lower(),
        }

    # ── 右键菜单 ──────────────────────────────────────────────────────────

    def _on_right_click_toggle_pool(self, pos) -> None:
        """右键：已选中卡片批量入池/移出；未选中卡片单卡切换；空白区返回上一级。

        - 右键点在框选选中的卡片上：
          - 全部选中项都已在储存池中 → 批量移出储存池（取消加入）；
          - 否则 → 批量加入储存池（add-only，已在池中的保持不变）；
          两种情况随后均清除框选选中态；
        - 右键点在未选中卡片上：清除框选 + 保留原有单卡"添加/移除"切换；
        - 右键点在空白区：清除框选；仅当「空白区右键返回上一级」开关开启、
          当前页面无需滚动、且点击落在空卡片位的卡片脚印内（卡片间缝隙与
          格子边缘间距不算）时返回上一级（与顶栏按钮/鼠标侧键一致）。

        Args:
            pos: 右键位置（viewport 坐标系，与 ``indexAt`` 口径一致）。
        """
        index = self._file_list.indexAt(pos)
        if not index.isValid():
            # 空白区：清除框选；满足空位条件时返回上一级，否则不做导航。
            self.clear_box_selection()
            if self._is_blank_slot_go_back_zone(pos):
                self._go_back()
            return
        file_path: str = self._file_model.data(index, FilePathRole) or ""
        if not file_path:
            return
        if file_path in self._file_model.get_selected_files():
            # 命中框选中的卡片：全部已在池中 → 批量移出；否则批量加入（add-only）
            infos = self._selected_file_infos()
            self.clear_box_selection()
            if infos:
                if self._all_in_pool(infos):
                    self.remove_files_from_pool_requested.emit(infos)
                else:
                    self.add_files_to_pool_requested.emit(infos)
            return
        # 未选中卡片：清除框选 + 保留原有单卡"添加/移除"切换
        self.clear_box_selection()
        is_dir: bool = bool(self._file_model.data(index, IsDirRole) or False)
        file_info: Dict[str, Any] = {
            "name": self._file_model.data(index, FileNameRole) or "",
            "path": file_path,
            "is_dir": is_dir,
            "size": int(self._file_model.data(index, FileSizeRole) or 0),
            "modified": self._file_model.data(index, ModifiedRole) or "",
            "created": self._file_model.data(index, CreatedRole) or "",
            "suffix": (self._file_model.data(index, SuffixRole) or "").lower(),
        }
        self.toggle_pool_requested.emit(file_info)

    def _is_blank_slot_go_back_zone(self, pos) -> bool:
        """判断右键点是否满足「空白空位返回上一级」的全部条件。

        条件（全部满足才返回 True）：

        1. 开关 ``_blank_right_click_go_back`` 已开启；
        2. 当前页面无需滚动（垂直滚动条最大值为 0，内容未超出视口）；
        3. 点击落在某个**空格子**（该格无卡片）的「卡片脚印」内——即若该格
           放置卡片，卡片本体将占据的矩形。格子之间/卡片之间预留的间距带
           （``gridSize`` 相对卡片本体多出的部分）永远不算，保证卡片间缝隙
           点击不触发；最后一排右侧未排满的空位与下方整排空位均算空位。

        命中判定在内容坐标系完成（viewport 坐标 + 滚动偏移），与
        ``indexAt`` 的口径一致；Qt 将卡片本体在格子内水平居中、垂直贴顶
        （多出的高度统一落在卡片下方，与委托 ``_resolve_card_rect`` 的假设
        一致）。

        Args:
            pos: 右键位置（viewport 坐标系）。

        Returns:
            bool: True 表示应当返回上一级。
        """
        if not self._blank_right_click_go_back:
            return False
        cell = self._file_list.gridSize()
        card = self._grid_card_size
        cols = self._grid_cols
        if (
            not cell.isValid() or cell.width() <= 0 or cell.height() <= 0
            or not card.isValid() or card.width() <= 0 or card.height() <= 0
            or cols <= 0
        ):
            return False  # 尚未完成网格布局：无从判定
        if self._file_list.verticalScrollBar().maximum() > 0:
            return False  # 需要滚动时一律不触发

        target_w = min(cell.width(), card.width())
        target_h = min(cell.height(), card.height())
        offset_x = max(0, (cell.width() - target_w + 1) // 2)
        offset_y = 0

        cx = pos.x() + self._file_list.horizontalScrollBar().value()
        cy = pos.y() + self._file_list.verticalScrollBar().value()
        col = cx // cell.width()
        row = cy // cell.height()
        if col < 0 or col >= cols or row < 0:
            return False
        local_x = cx - col * cell.width()
        local_y = cy - row * cell.height()
        if not (offset_x <= local_x < offset_x + target_w):
            return False  # 卡片脚印左右两侧的间距带
        if not (offset_y <= local_y < offset_y + target_h):
            return False  # 卡片脚印下方（行间）的间距带
        # 空格子：该格在线性序号上已超出模型行数（最后一排尾部/下方整排）
        return row * cols + col >= self._file_model.rowCount()

    # ── 收藏夹 ────────────────────────────────────────────────────────────

    def _get_favorites(self) -> List[Dict[str, str]]:
        """读取收藏夹并归一化为 [{"name": ..., "path": ...}]。

        兼容两种持久化格式：List[str]（纯路径）与 List[Dict]（旧版 name/path）。
        """
        result: List[Dict[str, str]] = []
        for entry in self._favorites_service.load():
            if isinstance(entry, dict) and entry.get("path"):
                path = str(entry["path"])
                name = str(entry.get("name") or "") or os.path.basename(path.rstrip("\\/")) or path
                result.append({"name": name, "path": path})
            elif isinstance(entry, str) and entry:
                result.append({
                    "name": os.path.basename(entry.rstrip("\\/")) or entry,
                    "path": entry,
                })
        return result

    def _add_current_path_to_favorites(self) -> None:
        """添加当前路径到收藏夹（路径栏星标按钮）。"""
        current_path = self._current_path
        if not current_path or current_path == "All":
            self._show_message_dialog("提示", "请先进入一个文件夹再添加到收藏夹")
            return
        favorites = self._get_favorites()
        if any(f["path"] == current_path for f in favorites):
            self._show_message_dialog("提示", "该路径已在收藏夹中")
            return
        default_name = os.path.basename(current_path.rstrip("\\/")) or current_path
        self._prompt_input(
            "添加到收藏夹", "请输入收藏名称:", default_name,
            on_confirm=lambda name: self._commit_add_favorite(name, current_path),
        )

    def _commit_add_favorite(self, name: str, path: str) -> None:
        """确认添加：名称非空时写入收藏夹并持久化。"""
        if not name:
            return
        service = self._favorites_service
        raw = service.load()
        raw.append({"name": name, "path": path})
        service.save(raw)

    def _show_favorites_dialog(self) -> None:
        """显示收藏夹对话框（工具栏星标按钮）。"""
        favorites = self._get_favorites()

        body = QWidget()
        register_widget_qss(body,("background: transparent;"))
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        list_widget: Optional[QListWidget] = None
        if not favorites:
            empty_label = QLabel("暂无收藏，点击路径栏的 ★ 可添加当前路径")
            empty_label.setWordWrap(True)
            empty_label.setAlignment(Qt.AlignCenter)
            register_widget_qss(empty_label,(
                f"font-size: 14px; color: {tm.qss_color(tm.text_hint)}; background: transparent;"
            ))
            empty_label.setFixedHeight(120)
            body_layout.addWidget(empty_label)
        else:
            list_widget = QListWidget()
            list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget.setSelectionMode(QAbstractItemView.NoSelection)
            list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
            list_widget.setMouseTracking(True)
            register_widget_qss(list_widget,(f"""
                QListWidget {{
                    background: transparent; border: none;
                    color: {tm.text.name()}; font-size: 13px;
                }}
                QListWidget::item {{
                    padding: 8px 10px; border-radius: 6px;
                }}
                QListWidget::item:hover {{
                    background-color: {tm.alpha_of(tm.fill, 60).name()};
                }}
            """))
            for fav in favorites:
                item = QListWidgetItem(f"{fav['name']}  -  {fav['path']}")
                item.setData(Qt.ItemDataRole.UserRole, fav["path"])
                item.setToolTip(fav["path"])
                list_widget.addItem(item)
            list_widget.setFixedHeight(280)

            list_widget.itemDoubleClicked.connect(
                lambda item: self._on_favorite_activated(item, list_widget)
            )
            list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
            list_widget.customContextMenuRequested.connect(
                lambda pos: self._show_favorite_context_menu(list_widget, pos)
            )
            body_layout.addWidget(list_widget)

        dialog = StyledDialog(
            size="lg", title="收藏夹", body_widget=body, footer_type=FOOTER_RIGHT,
        )
        dialog._favorites_list_widget = list_widget
        self._track_dialog(dialog)

        close_btn = StyledButton("关闭", variant="primary")
        close_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(close_btn)
        _show_dialog(dialog)

    def _on_favorite_activated(self, item, list_widget) -> None:
        """双击收藏项 → 跳转到对应路径并关闭对话框。"""
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        if os.path.isdir(path):
            self._navigate_to(path)
        dialog = list_widget.window()
        if isinstance(dialog, StyledDialog):
            dialog.close_dialog(1)

    def _show_favorite_context_menu(self, list_widget, pos) -> None:
        """收藏夹项的右键菜单：打开 / 重命名 / 删除。"""
        item = list_widget.itemAt(pos)
        if not item:
            return
        menu = StyledContextMenu(parent=list_widget)
        menu.add_item("打开", callback=lambda: self._on_favorite_activated(item, list_widget))
        menu.add_separator()
        menu.add_item(
            "重命名",
            callback=lambda: self._rename_favorite(item, list_widget),
        )
        menu.add_item(
            "删除",
            danger=True,
            callback=lambda: self._delete_favorite(item, list_widget),
        )
        menu.exec(list_widget.mapToGlobal(pos))

    def _rename_favorite(self, item, list_widget) -> None:
        """重命名收藏项（弹输入框）。"""
        path = item.data(Qt.ItemDataRole.UserRole)
        favorites = self._get_favorites()
        fav = next((f for f in favorites if f["path"] == path), None)
        if not fav:
            return
        self._prompt_input(
            "重命名收藏", "请输入新的收藏名称:", fav["name"],
            on_confirm=lambda name: self._commit_rename_favorite(path, name, item),
        )

    def _commit_rename_favorite(self, path: str, name: str, item) -> None:
        """确认重命名：更新名称并持久化（纯字符串格式自动升级为 dict）。"""
        if not name:
            return
        service = self._favorites_service
        raw = service.load()
        for i, entry in enumerate(raw):
            if isinstance(entry, dict) and entry.get("path") == path:
                entry["name"] = name
                break
            elif isinstance(entry, str) and entry == path:
                raw[i] = {"name": name, "path": path}
                break
        service.save(raw)
        item.setText(f"{name}  -  {path}")

    def _delete_favorite(self, item, list_widget) -> None:
        """删除收藏项（带确认对话框）。"""
        path = item.data(Qt.ItemDataRole.UserRole)
        text = item.text()
        name = text.split("  -  ", 1)[0] if "  -  " in text else path
        dialog = create_basic_dialog(
            title="确认删除",
            message=f"确定要删除收藏 '{name}' 吗？",
            cancel_text="取消",
            confirm_text="删除",
        )
        self._track_dialog(dialog)
        dialog.finished.connect(
            lambda result: self._do_delete_favorite(path, item, list_widget)
            if result == 1 else None
        )

    def _do_delete_favorite(self, path: str, item, list_widget) -> None:
        """确认删除后移除收藏项并刷新列表。"""
        service = self._favorites_service
        raw = service.load()
        raw = [
            e for e in raw
            if not (
                (isinstance(e, dict) and e.get("path") == path)
                or (isinstance(e, str) and e == path)
            )
        ]
        service.save(raw)
        row = list_widget.row(item)
        list_widget.takeItem(row)

    def _prompt_input(self, title: str, label_text: str, default_text: str,
                      on_confirm) -> None:
        """通用输入弹窗：StyledDialog + StyledLineEdit，确认回调 on_confirm(text)。"""
        body = QWidget()
        register_widget_qss(body,("background: transparent;"))
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        tip = QLabel(label_text)
        register_widget_qss(tip,(f"font-size: 14px; color: {tm.qss_color(tm.text_hint)}; background: transparent;"))
        body_layout.addWidget(tip)

        edit = StyledLineEdit(size="default")
        edit.setText(default_text)
        body_layout.addWidget(edit)

        dialog = StyledDialog(title=title, body_widget=body, footer_type=FOOTER_RIGHT)
        self._track_dialog(dialog)

        cancel_btn = StyledButton("取消", variant="ghost")
        ok_btn = StyledButton("确定", variant="primary")
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        ok_btn.clicked.connect(lambda: (on_confirm(edit.text().strip()), dialog.close_dialog(1)))
        dialog._footer_layout.addWidget(cancel_btn)
        dialog._footer_layout.addWidget(ok_btn)
        edit.returnPressed.connect(ok_btn.click)
        _show_dialog(dialog)

    def _show_message_dialog(
        self, title: str, message: str, *, on_closed: Optional[Callable[[], None]] = None
    ) -> None:
        """通用消息提示弹窗（StyledDialog）。

        Args:
            title: 弹窗标题。
            message: 弹窗正文。
            on_closed: 弹窗关闭后的回调（可选，供调用方恢复状态）。
        """
        body = QWidget()
        register_widget_qss(body,("background: transparent;"))
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        msg = QLabel(message)
        msg.setWordWrap(True)
        register_widget_qss(msg,(f"font-size: 14px; color: {tm.text.name()}; background: transparent;"))
        body_layout.addWidget(msg)

        dialog = StyledDialog(title=title, body_widget=body, footer_type=FOOTER_CENTER)
        self._track_dialog(dialog)
        if on_closed is not None:
            # finished 信号带 result 参数，lambda 吞掉后调用无参回调
            dialog.finished.connect(lambda *_: on_closed())

        ok_btn = StyledButton("确定", variant="primary")
        ok_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(ok_btn)
        _show_dialog(dialog)

    def _track_dialog(self, dialog: StyledDialog) -> None:
        """保持弹窗引用，finished 后自动释放，防止被 GC。"""
        self._active_dialogs.append(dialog)
        dialog.finished.connect(
            lambda *_: self._active_dialogs.remove(dialog)
            if dialog in self._active_dialogs else None
        )

    # ── 缩略图生成 / 清除 ──────────────────────────────────────────────────

    def _collect_thumbnail_targets(self) -> List[str]:
        """收集缩略图生成目标：当前目录全部文件。

        目录条目不参与收集；非媒体文件与已有缩略图的文件由
        ``ThumbnailController.start_generation`` 内部过滤。

        Returns:
            List[str]: 候选文件路径列表。
        """
        paths: List[str] = []
        model = self._file_model
        for row in range(model.rowCount()):
            idx = model.index(row, 0)
            if model.data(idx, IsDirRole):
                continue
            file_path = model.data(idx, FilePathRole)
            if file_path:
                paths.append(file_path)
        return paths

    def _on_generate_thumbnails(self) -> None:
        """「生成缩略图」按钮：收集目标并启动后台批量生成。

        生成进行中再次点击：不再直接忽略，而是弹出「继续生成 /
        取消任务」对话框——确认取消则中止当前任务（见
        ``_cancel_generation``），继续则不打断当前生成流程。
        """
        if self._thumb_controller.is_busy:
            progress_hint = (
                f"（已生成 {self._gen_progress_text}）"
                if self._gen_progress_text else ""
            )
            dialog = create_basic_dialog(
                title="缩略图生成中",
                message=f"正在生成缩略图{progress_hint}，是否取消当前任务？",
                cancel_text="继续生成",
                confirm_text="取消任务",
            )
            self._track_dialog(dialog)
            dialog.finished.connect(
                lambda result: self._cancel_generation() if result == 1 else None
            )
            return
        paths = self._collect_thumbnail_targets()
        self._enter_generation_busy()
        # 空任务由 controller 同步 emit batch_finished(0,0)，
        # 槽内恢复按钮并弹轻提示，随后才回到这里返回
        if not self._thumb_controller.start_generation(paths):
            self._set_thumbnail_buttons_busy(False)

    def _enter_generation_busy(self) -> None:
        """进入生成忙碌态：生成按钮切入进度模式，清除按钮禁用。

        生成按钮保持可用——生成中再次点击可弹出「继续/取消」对话框；
        进度模式下按钮自绘「轨道 + 填充 + spinner + 百分比」组合，
        文案不再经 setText 更新（见 StyledButton.paintEvent 进度分支）。
        """
        self._gen_progress_text = ""
        self._clean_btn.setEnabled(False)
        self._gen_thumb_btn.set_progress(0.0)

    def _cancel_generation(self) -> None:
        """确认取消当前生成任务：释放互斥、恢复按钮并弹取消通知。

        弹窗打开期间任务可能恰好已结束（``is_busy`` 为 False），此时
        完成槽已恢复过按钮，这里仅做兜底恢复、不再重复弹提示。
        """
        if not self._thumb_controller.is_busy:
            self._set_thumbnail_buttons_busy(False)
            return
        self._thumb_controller.cancel()  # 释放互斥；旧任务收尾事件被世代 token 丢弃
        self._set_thumbnail_buttons_busy(False)
        self._show_message_dialog("缩略图", "已取消缩略图生成任务")

    def _on_clear_thumbnails(self) -> None:
        """「清除缩略图」按钮：确认对话框后启动全量缩略图缓存清除。"""
        if self._thumb_controller.is_busy:
            return  # 防御：按钮已禁用，正常不可达
        dialog = create_basic_dialog(
            title="清除缩略图",
            message="确定要清除全部缩略图缓存吗？此操作无法撤销。",
            cancel_text="取消",
            confirm_text="清除",
        )
        self._track_dialog(dialog)
        dialog.finished.connect(
            lambda result: self._start_clear_thumbnails() if result == 1 else None
        )

    def _start_clear_thumbnails(self) -> None:
        """确认清除后启动清除任务：禁用按钮 + 后台执行。"""
        if self._thumb_controller.is_busy:
            return  # 确认框打开期间已有新任务启动，交给该任务的槽恢复按钮
        self._set_thumbnail_buttons_busy(True, "清除中...")
        if not self._thumb_controller.start_clear():
            self._set_thumbnail_buttons_busy(False)

    def _set_thumbnail_buttons_busy(self, busy: bool, text: str = "") -> None:
        """切换生成 / 清除按钮的忙碌态（禁用 + 文案反馈）。

        进入前先让生成按钮退出进度模式——进度条仅属于生成流程，
        清除是另一忙碌状态；恢复场景（任务结束）同样需要退出进度
        模式回到普通绘制。

        Args:
            busy: True 进入忙碌态（两按钮禁用）；False 恢复默认可用态。
            text: 忙碌态下生成按钮的文案，恢复时回到默认文案。
        """
        self._gen_thumb_btn.set_progress(None)  # 退出进度模式（如在生成进度态）
        self._gen_thumb_btn.setEnabled(not busy)
        self._clean_btn.setEnabled(not busy)
        self._gen_thumb_btn.setText(text if busy else "生成缩略图")

    def _on_thumbnail_progress(self, done_count: int, total_count: int) -> None:
        """生成进度槽：更新进度文案并驱动生成按钮进度模式。

        进度模式下按钮自绘百分比文本，不再经 setText 更新文案；
        ``_gen_progress_text`` 供生成中点击弹窗的提示语拼接。

        Args:
            done_count: 已完成文件数。
            total_count: 总文件数。
        """
        self._gen_progress_text = f"{done_count}/{total_count}"
        self._gen_thumb_btn.set_progress(
            done_count / total_count if total_count > 0 else 0.0
        )

    def _on_thumbnails_ready(self, file_paths: List[str]) -> None:
        """一批缩略图就绪槽：按路径失效图标缓存并回填刷新受影响行。

        图片/视频类型的图标缓存键含文件路径（thumb 键），可按路径精确
        失效——仅本批涉及文件重查磁盘，其余文件的图标缓存保持命中，
        避免批量生成期间反复全清导致无关图标（含系统图标）反复重载。

        Args:
            file_paths: 本批就绪的文件路径列表。
        """
        if not file_paths:
            return
        icon_manager = FileIconManager()
        for file_path in file_paths:
            icon_manager.clear_cache(file_path)
        self._file_model.emit_icon_changed(file_paths)

    def _on_thumbnail_batch_finished(self, success_count: int, processed_count: int) -> None:
        """生成完成槽：恢复按钮；空任务（无可生成项）时弹轻提示。"""
        self._set_thumbnail_buttons_busy(False)
        if processed_count == 0:
            self._show_message_dialog("生成缩略图", "所选文件均已有缩略图或无媒体文件")

    def _on_thumbnails_cleared(self, deleted_count: int) -> None:
        """清除完成槽：全清图标缓存 + 全行刷新图标 + 弹结果通知。"""
        FileIconManager().clear_cache()
        model = self._file_model
        if model.rowCount() > 0:
            top = model.index(0, 0)
            bottom = model.index(model.rowCount() - 1, 0)
            model.dataChanged.emit(top, bottom, [IconPixmapRole])
        self._set_thumbnail_buttons_busy(False)
        self._show_message_dialog("清除缩略图", f"已清除 {deleted_count} 个缩略图缓存文件")

    def _on_thumbnail_failed(self, message: str) -> None:
        """后台任务异常槽：恢复按钮并弹错误提示（含异常消息）。"""
        self._set_thumbnail_buttons_busy(False)
        self._show_message_dialog("缩略图", f"缩略图任务失败：{message}")

    # ── 筛选 ──────────────────────────────────────────────────────────────

    def _show_filter_dialog(self) -> None:
        """显示筛选弹窗：输入文件名正则（不区分大小写），应用后重载目录。"""
        body = QWidget()
        register_widget_qss(body,("background: transparent;"))
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        tip = QLabel("输入文件名筛选正则（不区分大小写）。\n例如：\\.png$ 仅显示 png，项目 匹配名称含“项目”的文件。")
        tip.setWordWrap(True)
        register_widget_qss(tip,(f"font-size: 14px; color: {tm.qss_color(tm.text_hint)}; background: transparent;"))
        body_layout.addWidget(tip)

        edit = StyledLineEdit(size="default")
        edit.setPlaceholderText("例如: \\.png$ 或 项目")
        edit.setText(self._filter_pattern)
        body_layout.addWidget(edit)

        dialog = StyledDialog(title="筛选文件", body_widget=body, footer_type=FOOTER_RIGHT)
        self._track_dialog(dialog)

        clear_btn = StyledButton("移除筛选", variant="ghost")
        cancel_btn = StyledButton("取消", variant="ghost")
        apply_btn = StyledButton("应用", variant="primary")

        def on_apply() -> None:
            pattern = edit.text().strip()
            if pattern and not self._is_valid_regex(pattern):
                self._show_message_dialog("筛选", "正则表达式无效，请检查后重试")
                return
            self._filter_pattern = pattern
            self._update_filter_button_state()
            dialog.close_dialog(1)
            self._apply_filter_or_reload()

        def on_clear() -> None:
            self._filter_pattern = ""
            self._update_filter_button_state()
            dialog.close_dialog(1)
            self._apply_filter_or_reload()

        apply_btn.clicked.connect(on_apply)
        clear_btn.clicked.connect(on_clear)
        cancel_btn.clicked.connect(lambda: dialog.close_dialog(0))
        dialog._footer_layout.addWidget(clear_btn)
        dialog._footer_layout.addWidget(cancel_btn)
        dialog._footer_layout.addWidget(apply_btn)
        edit.returnPressed.connect(apply_btn.click)
        _show_dialog(dialog)

    def _update_filter_button_state(self) -> None:
        """筛选激活时高亮筛选按钮（ghost → info）并更新 tooltip。"""
        has_filter = bool(self._filter_pattern)
        self._sift_btn.set_variant("info" if has_filter else "ghost")
        self._sift_btn.setToolTip(
            f"筛选: {self._filter_pattern}" if has_filter else "筛选文件"
        )

    def _matches_filter(self, name: str) -> bool:
        """判断文件名是否匹配当前筛选正则（不区分大小写）。"""
        pattern = self._filter_pattern
        if not pattern:
            return True
        try:
            return re.search(pattern, name, re.IGNORECASE) is not None
        except re.error:
            return True

    @staticmethod
    def _is_valid_regex(pattern: str) -> bool:
        """校验正则是否可编译。"""
        try:
            re.compile(pattern)
            return True
        except re.error:
            return False

    # ── UI 更新 ────────────────────────────────────────────────────────────

    def _update_path_input(self, path: str) -> None:
        """同步路径框文本（程序化写入即视为已提交，清除未提交编辑标记）。"""
        self._path_input.setText(path)
        self._path_input_dirty = False

    def _update_file_count(self, count: int) -> None:
        """落地态计数标签：正常配色 + 数值。"""
        self._file_count_label.setText(f"{count} 个条目")
        register_widget_qss(self._file_count_label,(self._count_label_style()))

    def _set_count_loading(self, n: int) -> None:
        """加载态计数标签：显示「加载中… N」（N=已落地条目数），配色用 hint 色。

        Args:
            n: 已落地（筛选后展示）的条目数。
        """
        self._file_count_label.setText(f"加载中… {n}")
        register_widget_qss(self._file_count_label, self._count_label_loading_style())

    @staticmethod
    def _count_label_style() -> str:
        """条目计数标签样式（浅色=语义次要文字，深色=mid，随主题现取）。"""
        return (
            "background: transparent; border: none;"
            f"color: {tm.qss_color(tm.text_secondary)}; font-size: 11px;"
        )

    @staticmethod
    def _count_label_loading_style() -> str:
        """加载态计数标签样式（hint 色，比落地态更弱，随主题现取）。"""
        return (
            "background: transparent; border: none;"
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 11px;"
        )

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换：按流式是否在途刷新计数标签配色（面板边框/填充由 MainWindow 统一下放）。"""
        if self._stream_active_token == self._async_load_token:
            register_widget_qss(
                self._file_count_label, self._count_label_loading_style()
            )
        else:
            register_widget_qss(self._file_count_label, self._count_label_style())

    # ── 滚动条同步 ────────────────────────────────────────────────────────

    def _sync_scrollbar_range(self) -> None:
        """当 QListView 内部滚动范围变化时，同步 StyledScrollBar 的范围。"""
        list_vbar = self._file_list.verticalScrollBar()
        maximum = list_vbar.maximum()
        self._file_scrollbar.setRange(list_vbar.minimum(), maximum)
        self._file_scrollbar.setSingleStep(list_vbar.singleStep())
        self._file_scrollbar.setPageStep(list_vbar.pageStep())

    def _on_list_range_changed(self, min_val: int, max_val: int) -> None:
        """列表模式下滚动范围变化后修正卡片边距（延迟到 Qt 布局稳定后执行）。"""
        if self._view_mode == "list":
            QTimer.singleShot(0, self._update_list_grid)

    # ── 卡片缩放（Ctrl+滚轮）──────────────────────────────────────────────

    def _handle_card_zoom(self, event) -> None:
        delta = event.angleDelta().y()
        if delta > 0:
            new_scale = min(self._card_scale_max, self._card_scale + 0.1)
        elif delta < 0:
            new_scale = max(self._card_scale_min, self._card_scale - 0.1)
        else:
            return
        self._card_scale = new_scale
        self._card_delegate.set_card_scale(new_scale)
        self._update_grid_size()

    def _invalidate_file_rows(self, rows) -> None:
        """按行矩形局部失效文件列表 viewport（A4 局部重绘纪律）。

        脏区取各行 ``visualRect`` 并集（viewport 坐标系）；行无效/不可见或
        行数过多（>64，脏区近全窗）时回退整 viewport ``update()``。

        Args:
            rows: 行号可迭代对象。
        """
        from PySide6.QtCore import QRect as _QRect

        view = self._file_list
        try:
            viewport = view.viewport()
            model = view.model()
        except Exception:
            return
        if viewport is None or model is None:
            return
        dirty = _QRect()
        count = 0
        try:
            for row in rows:
                if row is None or row < 0 or row >= model.rowCount():
                    continue
                rect = view.visualRect(model.index(row, 0))
                if rect.isValid() and not rect.isEmpty():
                    dirty = rect if dirty.isNull() else dirty.united(rect)
                    count += 1
                    if count > 64:
                        break
        except Exception:
            dirty = _QRect()
        try:
            if dirty.isNull() or count > 64:
                viewport.update()
            else:
                viewport.update(dirty.adjusted(-1, -1, 1, 1).intersected(viewport.rect()))
        except Exception as exc:
            debug(f"文件列表局部重绘失败：{exc}")

    def sync_pool_status(self, pool_paths: set[str]) -> None:
        """同步文件池中的路径集合到 delegate，刷新"已在池中"边框标记。

        同时缓存归一化路径集合到 _pool_paths，作为局部重绘的差异基准。

        Args:
            pool_paths: 文件池中的文件路径集合。
        """
        new_pool = {
            os.path.normcase(os.path.normpath(p)) for p in (pool_paths or set())
        }
        old_pool = self._pool_paths
        self._pool_paths = new_pool
        self._card_delegate.set_pool_files(pool_paths)
        # A4 局部重绘：仅"池中态"翻转的行需要重绘；无变化时零重绘；
        # 行解析失败时保守回退整 viewport（绝不漏重绘）。
        if new_pool == old_pool:
            return
        changed_rows: list = []
        lookup_failed = False
        try:
            model = self._file_model
            for row in range(model.rowCount()):
                raw = model.get_file_info(model.index(row, 0)).get("path", "")
                if not raw:
                    continue
                key = os.path.normcase(os.path.normpath(raw))
                if (key in new_pool) != (key in old_pool):
                    changed_rows.append(row)
        except Exception:
            lookup_failed = True
        if lookup_failed:
            self._file_list.viewport().update()
            return
        if not changed_rows:
            return
        self._invalidate_file_rows(changed_rows)

    # ── 预览状态管理 ────────────────────────────────────────────────────────

    def set_previewing_file(self, file_path: str) -> None:
        """设置文件选择器卡片的预览态：清除旧预览，设置新预览。

        预览态由 delegate 绘制为流光渐变边框（角锥渐变旋转动画），
        与文件池 `set_previewing_file` 行为一致。

        Args:
            file_path: 要预览的文件路径，若为空则仅清除旧预览。
        """
        import os

        # A4 局部重绘：新旧预览行按行矩形失效（setData 本身也会触发行级 dataChanged）。
        dirty_rows: list = []
        # 清除旧预览
        if self._previewing_file_path:
            row = self._file_model.get_row(self._previewing_file_path)
            if row >= 0:
                idx = self._file_model.index(row, 0)
                self._file_model.setData(idx, False, IsPreviewingRole)
                dirty_rows.append(row)
        self._previewing_file_path = ""

        # 设置新预览（路径规范化后匹配，与文件池保持一致）
        if file_path:
            normalized = os.path.normpath(file_path)
            row = self._file_model.get_row(normalized)
            if row >= 0:
                idx = self._file_model.index(row, 0)
                self._file_model.setData(idx, True, IsPreviewingRole)
                self._previewing_file_path = normalized
                dirty_rows.append(row)

        self._invalidate_file_rows(dirty_rows)

    def clear_previewing_state(self) -> None:
        """清除所有卡片的预览状态。"""
        self.set_previewing_file("")

    # ── 定位 ──────────────────────────────────────────────────────────

    def locate_file(self, file_info: Dict[str, Any]) -> None:
        """定位到预览文件的所在目录：导航文件列表并高亮滚动到该文件卡片。

        与旧版"定位到所在目录"语义一致：左侧文件选择器切到目标目录并定位
        文件卡片（新 UI 中不修改文件池内容，仅做视觉定位）。

        Args:
            file_info: 目标文件信息（须含 'path'）。
        """
        if not file_info:
            return
        file_path = file_info.get("path", "")
        if not file_path:
            return

        file_path = os.path.abspath(file_path)
        file_dir = os.path.dirname(file_path)
        if not file_dir or not os.path.isdir(file_dir):
            self._show_message_dialog("错误", f"目录不存在: {file_dir}")
            return

        # 目标目录与当前显示的目录不同（含 All 视图）→ 先导航过去
        current_path = self._current_path or ""
        needs_navigation = not (
            current_path
            and os.path.normcase(os.path.normpath(current_path))
            == os.path.normcase(os.path.normpath(file_dir))
        )
        if needs_navigation:
            self._navigate_to(file_dir)
            # 异步导航：条目落地后由 _on_dir_entries_ready → _handle_pending_locate
            # 完成高亮与滚动（此处仅登记挂起目标）
            self._pending_locate_path = file_path
            return

        # 目标目录即当前目录：立即高亮目标文件卡片（用 model 中实际存储的
        # 路径，规避大小写不一致）
        model_file_path = self._locate_model_file_path(file_path)
        if model_file_path:
            self.set_previewing_file(model_file_path)
            # 目录过渡动画（120ms）结束后再滚动，避免与过渡快照错位
            QTimer.singleShot(180, lambda p=model_file_path: self._scroll_to_file(p))

    def _locate_model_file_path(self, file_path: str) -> Optional[str]:
        """在 model 中按路径（忽略大小写）查找文件，返回 model 存储的路径。

        Args:
            file_path: 目标文件的绝对路径。

        Returns:
            model 中匹配条目的 'path' 值；未找到返回 None。
        """
        exact = self._file_model.get_row(file_path)
        if exact >= 0:
            idx = self._file_model.index(exact, 0)
            return self._file_model.data(idx, FilePathRole) or file_path

        target_key = os.path.normcase(file_path)
        for row in range(self._file_model.rowCount()):
            idx = self._file_model.index(row, 0)
            entry_path = self._file_model.data(idx, FilePathRole)
            if entry_path and os.path.normcase(entry_path) == target_key:
                return entry_path
        return None

    def _scroll_to_file(self, file_path: str) -> None:
        """滚动到指定文件卡片使其在视口中可见（文件不在列表中则忽略）。"""
        row = self._file_model.get_row(file_path)
        if row < 0:
            return
        idx = self._file_model.index(row, 0)
        self._file_list.scrollTo(idx, QAbstractItemView.PositionAtCenter)

    # ── 方向键导航：状态与模型行数学（arrow-key-file-preview-nav Todo 1）──

    def reset_nav_state(self) -> None:
        """重置方向键导航手势状态（幂等）。

        MainWindow 在主窗口失活时调用；模型重填（目录切换）路径同样调用，
        保证旧目录的光标行/手势不会残留在新目录的模型上。
        """
        self._nav_active = False
        self._nav_cursor_row = -1
        self._nav_model_key = None

    def _nav_cols(self) -> int:
        """当前视图的一行格子数（列表模式恒为 1；卡片模式取 ``_grid_cols``）。

        无副作用：绝不触发 ``_update_grid_size()``/``_apply_grid_layout()``
        ——本方法运行在按键事件内，任何重排都会造成可见抖动。``_grid_cols``
        尚未计算（0，列表未显示/未 resize）时回退为 1，等网格布局完成后
        自然纠正。

        Returns:
            int: 大于等于 1 的列数。
        """
        if self._view_mode == "list":
            return 1
        return max(1, int(self._grid_cols or 0) or 1)

    def _nav_model_signature(self) -> Tuple[Any, int, str]:
        """当前模型签名（路径, 行数, 视图模式），用于判定手势新鲜度。

        Returns:
            Tuple[Any, int, str]: (``_current_path``, ``rowCount()``,
            ``_view_mode``) 三元组。
        """
        return (self._current_path, self._file_model.rowCount(), self._view_mode)

    def _row_is_dir(self, row: int) -> bool:
        """判断模型行是否为目录（越界行按非目录处理）。

        Args:
            row: 模型行号。

        Returns:
            bool: True 表示该行是目录。
        """
        if not (0 <= row < self._file_model.rowCount()):
            return False
        return bool(
            self._file_model.data(self._file_model.index(row, 0), IsDirRole) or False
        )

    def _row_path(self, row: int) -> str:
        """取模型行的文件路径（越界行返回空串）。

        Args:
            row: 模型行号。

        Returns:
            str: 该行 ``FilePathRole`` 路径；越界或无数据为空串。
        """
        if not (0 <= row < self._file_model.rowCount()):
            return ""
        return self._file_model.data(self._file_model.index(row, 0), FilePathRole) or ""

    def _scan_file_row(self, row: int, step: int) -> Optional[int]:
        """沿模型顺序扫描下一个/上一个非目录行（跨目录连续跳过、环绕）。

        Args:
            row: 起始模型行号。
            step: 步进方向（+1 向前 / -1 向后）。

        Returns:
            Optional[int]: 命中的非目录行号；全模型皆目录或空模型返回 None。
        """
        n = self._file_model.rowCount()
        if n == 0:
            return None
        for i in range(1, n + 1):
            r = (row + step * i) % n
            if not self._row_is_dir(r):
                return r
        return None

    def _grid_step_row(self, row: int, delta_rows: int) -> Optional[int]:
        """卡片网格的垂直步进：按模型行算上/下相邻格，再吸附到最近非目录。

        ``cols`` 计全部格子（含目录），故上下相邻格必须由模型行 ``divmod``
        得出（不能用"文件序"步进——目录占用的格子会错位）；目标网格行整体
        皆目录时返回 None，由调用方回退为文件序扫描。

        Args:
            row: 起始模型行号。
            delta_rows: 行步进（+1 向下 / -1 向上）。

        Returns:
            Optional[int]: 命中的非目录行号；空模型或目标行无文件返回 None。
        """
        cols = self._nav_cols()
        n = self._file_model.rowCount()
        if n == 0:
            return None
        grid_row, grid_col = divmod(row, cols)
        total = (n + cols - 1) // cols
        ng = (grid_row + delta_rows) % total
        start = ng * cols
        end = min(start + cols, n)
        for r in sorted(range(start, end), key=lambda r: (abs((r - start) - grid_col), r)):
            if not self._row_is_dir(r):
                return r
        return None

    def _resolve_anchor_row(self) -> int:
        """解析当前导航锚点的模型行：手势光标路径优先，其次预览文件路径。

        先按 ``get_row`` 精确查询；未命中时按 ``normcase``/``normpath`` 全表
        扫描回退（Windows 盘符/路径段大小写差异，与
        ``_locate_model_file_path`` 同口径）。两者皆无解析结果返回 -1。

        Returns:
            int: 锚点模型行号；无任何可解析锚点返回 -1。
        """
        for candidate in (self._nav_cursor_path, self._previewing_file_path):
            if not candidate:
                continue
            row = self._file_model.get_row(str(candidate))
            if row >= 0:
                return row
            target = os.path.normcase(os.path.normpath(str(candidate)))
            for r in range(self._file_model.rowCount()):
                if os.path.normcase(os.path.normpath(self._row_path(r))) == target:
                    return r
        return -1

    # ── 方向键导航：按下/释放手势（arrow-key-file-preview-nav Todo 2）──────

    def handle_nav_key_press(self, key: int) -> bool:
        """处理一次方向键按下（按住连发 = 同一手势内持续步进）。

        仅移动高亮（``set_previewing_file`` + ``_scroll_to_file``），**不发**
        ``file_selected``；预览加载统一由 ``handle_nav_key_release`` 在释放时
        只发一次。

        手势模型：非活动态 / 换键 / 模型签名变化 → 新手势，先解析锚点行
        （``_resolve_anchor_row``，无锚点则按方向取第一个/最后一个文件）；
        否则在当前光标行继续步进（长按连发）。

        Args:
            key: Qt 键值（仅四个方向键被消费；其余原样放行）。

        Returns:
            bool: True = 事件已消费（光标已移动）；False = 非方向键 / 空模型 /
            无文件可命中（调用方应放行事件）。
        """
        arrow_map = {
            Qt.Key_Left: ("col", -1),
            Qt.Key_Right: ("col", +1),
            Qt.Key_Up: ("row", -1),
            Qt.Key_Down: ("row", +1),
        }
        if key not in arrow_map:
            return False
        direction, step = arrow_map[key]
        n = self._file_model.rowCount()
        if n == 0:
            return False
        sig = self._nav_model_signature()
        fresh = (
            (not self._nav_active)
            or (key != self._nav_last_key)
            or (self._nav_model_key != sig)
        )
        if fresh:
            self._nav_model_key = sig
        if fresh:
            base = self._resolve_anchor_row()
        else:
            base = self._nav_cursor_row
        target: Optional[int]
        if base < 0:
            # 新手势无锚点：+ 方向取第一个文件、- 方向取最后一个文件（跳过目录）
            target = None
            rows = range(n) if step > 0 else range(n - 1, -1, -1)
            for r in rows:
                if not self._row_is_dir(r):
                    target = r
                    break
            if target is None:
                return False
        elif direction == "col":
            # 左右方向：离散点按 = 每次前进一个文件（跨目录连续跳过、环绕）
            target = self._scan_file_row(base, step)
        elif self._view_mode == "list":
            target = self._scan_file_row(base, step)
        else:
            # 卡片模式：优先按模型行网格上下步进；目标行整行皆目录时回退
            # 文件序扫描。必须用显式 None 判断：合法目标行 0 是 falsy，
            # `or` 兜底会把"环绕到首行"误换成文件序邻居。
            grid_target = self._grid_step_row(base, step)
            target = (
                grid_target
                if grid_target is not None
                else self._scan_file_row(base, step)
            )
        if target is None:
            return False
        self._nav_cursor_row = target
        path = self._row_path(target)
        if not path:
            return False
        self._nav_cursor_path = path
        self._nav_active = True
        self._nav_last_key = key
        self.set_previewing_file(path)
        self._scroll_to_file(path)
        return True

    def handle_nav_key_release(self, key: int) -> bool:
        """处理方向键释放：结束手势并发出一次 ``file_selected``。

        Args:
            key: Qt 键值（须与手势起始键一致，否则视为无关释放原样放行）。

        Returns:
            bool: True = 释放已消费（含光标路径失效时的静默吞掉）；False =
            无活动手势或键与手势不匹配。
        """
        if not self._nav_active:
            return False
        if key != self._nav_last_key:
            return False
        self._nav_active = False
        path = self._nav_cursor_path
        if not path:
            return True
        info = self._build_file_info_for_path(path)
        if info is None:
            return True
        self.file_selected.emit(info)
        return True

    # ── 网格布局 ──────────────────────────────────────────────────────────

    def _update_grid_size(self) -> None:
        """
        自适应网格布局：根据视口宽度动态计算卡片宽度和每行数量。
        防递归守卫防止 margins 改变引发的布局震荡。
        """
        if self._updating_grid:
            return
        self._updating_grid = True
        try:
            self._do_update_grid_size()
        finally:
            self._updating_grid = False

    def _do_update_grid_size(self) -> None:
        if self._view_mode == "list":
            self._update_list_grid()
            return

        viewport = self._file_list.viewport()
        if not viewport or viewport.width() <= 0:
            return

        # 直接计算并设置 gridSize，不加 setUpdatesEnabled 包裹（与旧代码一致）
        self._apply_grid_layout(viewport)
        self._file_list.update()

    # ── 卡片尺寸与列数计算（移植自旧 CustomFileSelector）────────────────────

    def _calculate_card_base_width(self) -> int:
        """计算卡片的基础宽度（基于日期文本宽度），与旧 file_selector.py 保持一致。

        公式已抽取为 ``file_card_delegate.calc_grid_base_width``（选择器与
        储存池网格共用，单一事实来源）。
        """
        return calc_grid_base_width(self.font())

    def _update_minimum_width(self) -> None:
        """设置最小宽度：顶栏与底栏完整显示图标/文字前提下的较大者。

        历史实现强制「至少 3 列卡片」（约 225px），会把整栏最小宽度抬到
        超过顶栏/底栏自身需求；现改为自然最小（顶栏/底栏最小宽取大），
        网格列数随实际宽度自适应（可能少于 3 列）。
        """
        top_min = self._top_bar.minimumSizeHint().width()
        bottom_min = self._bottom_bar.minimumSizeHint().width()
        self.setMinimumWidth(max(0, top_min, bottom_min))

    def _apply_grid_layout(self, viewport) -> None:
        """卡片模式网格布局：基于 file_list 全宽居中卡片网格，滚动条浮动覆盖在右侧边距中。"""
        dpi = 1.0

        # 滚动条为浮动覆盖层，file_list 独占 content_area 全宽
        file_list_width = self._file_list.width()
        if file_list_width <= 0:
            return

        edge_padding = int(10 * dpi)
        card_base_width = int(self._calculate_card_base_width() * self._card_scale)
        spacing = int(4 * dpi)
        margin = edge_padding

        available_width = max(0, file_list_width - 2 * margin)
        # 列数/列宽计算：与储存池网格共用（file_card_delegate.calc_grid_cell）
        max_cols, card_width = calc_grid_cell(
            available_width, card_base_width, spacing
        )

        _, card_height = FileCardDelegate._calc_card_size(CARD_CONFIG, self._card_scale)
        grid_cell_width = card_width + spacing
        grid_cell_height = card_height + spacing

        # 让 viewport 宽度刚好容纳 max_cols 个 grid cell。
        # +1 补偿 Qt QListView IconMode 换行边界检查的 off-by-one：
        # Qt 使用 >= 而非 > 判断换行，导致 viewport == cols * grid_cell_width 时提前换行。
        desired_viewport_width = max_cols * grid_cell_width + 1
        total_side_margin = max(0, file_list_width - desired_viewport_width)
        left_margin = total_side_margin // 2
        right_margin = total_side_margin - left_margin

        self._file_list.setSpacing(0)
        new_grid = QSize(grid_cell_width, grid_cell_height)
        if self._file_list.gridSize() != new_grid:
            self._file_list.setGridSize(new_grid)
        # 顶部间距以文件储存池为基准：池 _card_layout 顶部边距为固定 6px（非 DPI 缩放）。
        # 这里将顶部 viewport 边距对齐为 6，使第一排卡片距上边缘的间距与储存池一致；
        # 底部边距与滚动条几何仍沿用 edge_padding，保持滚动行为不变。
        top_padding = 6
        new_margins = QMargins(left_margin, top_padding, right_margin, edge_padding)
        if self._file_list.viewportMargins() != new_margins:
            self._file_list.setViewportMargins(new_margins)
        # 保持 grid_offset_x=0，避免 hover 时卡片绘制超出自身 grid cell 产生残影
        self._file_model.set_grid_offset_x(0)
        self._file_model.set_card_width(card_width, card_height)
        # 记录网格几何快照（空白位右键命中判定使用；与 gridSize 同一处更新）
        self._grid_cols = max_cols
        self._grid_card_size = QSize(card_width, card_height)

        # 滚动条作为浮动覆盖层，定位在右侧边距内（贴右边缘）；
        # 每次定位后 raise_() 保持悬浮覆盖层层级，避免与卡片列表同级堆叠。
        scrollbar_w = self._file_scrollbar.width()
        scrollbar_x = file_list_width - scrollbar_w
        scrollbar_y = edge_padding
        scrollbar_h = max(0, self._file_list.height() - 2 * edge_padding)
        self._file_scrollbar.setGeometry(scrollbar_x, scrollbar_y, scrollbar_w, scrollbar_h)
        self._file_scrollbar.raise_()

    def _update_list_grid(self) -> None:
        """列表模式布局（移植自旧 CustomFileSelector._update_list_layout）。

        直接使用 file_list 全宽而非 viewport.width()。
        viewport.width() 受当前 viewportMargins 影响：卡片→列表切换时，
        卡片模式遗留的 margins 会压缩 viewport 宽度，导致网格尺寸计算错误。
        """
        file_list_width = self._file_list.width()
        if file_list_width <= 0:
            return
        dpi = 1.0
        # 边距以 dpi 为恒定基准，不随卡片缩放（_card_scale）变化，
        # 保证 ctrl+滚轮缩放时卡片列表距视口左右的距离始终不变。
        edge_padding = int(10 * dpi)
        card_width = max(200, file_list_width)
        _, card_height = FileCardDelegate._calc_list_size(LIST_CONFIG, self._card_scale)
        gap = int(5 * self._card_scale)
        new_grid = QSize(file_list_width, card_height + gap)
        if self._file_list.gridSize() != new_grid:
            self._file_list.setGridSize(new_grid)

        # 左右边距恒定且对称：右侧预留滚动条浮动覆盖层宽度，
        # 滚动条浮在预留空间内，不与卡片重叠、不改变卡片边缘位置。
        scrollbar_w = self._file_scrollbar.width()
        side_margin = int(10 * dpi)
        left_margin = side_margin
        right_margin = max(side_margin, scrollbar_w + int(2 * dpi))

        # 顶部间距以文件储存池为基准，固定 6px，与卡片模式保持一致。
        top_padding = 6
        new_margins = QMargins(left_margin, top_padding, right_margin, edge_padding)
        if self._file_list.viewportMargins() != new_margins:
            self._file_list.setViewportMargins(new_margins)
        self._file_model.set_grid_offset_x(0)
        self._file_model.set_card_width(card_width, card_height)
        # 记录网格几何快照（空白位右键命中判定使用；列表模式恒为单列）
        self._grid_cols = 1
        self._grid_card_size = QSize(card_width, card_height)

        # 滚动条定位在右侧边缘（与卡片模式一致，保留顶部边距）；
        # 每次定位后 raise_() 保持其悬浮覆盖层层级，不与卡片列表同级堆叠。
        scrollbar_x = self._file_list.width() - scrollbar_w
        scrollbar_y = edge_padding
        scrollbar_h = max(0, self._file_list.height() - 2 * edge_padding)
        self._file_scrollbar.setGeometry(scrollbar_x, scrollbar_y, scrollbar_w, scrollbar_h)
        self._file_scrollbar.raise_()

    # ── 排序与视图 ────────────────────────────────────────────────────────

    SORT_MODE_NAMES: Dict[int, str] = {
        0: "名称↑", 1: "名称↓", 2: "修改时间↓",
        3: "修改时间↑", 4: "大小↓", 5: "大小↑",
        6: "创建时间↓", 7: "创建时间↑",
    }

    def _show_sort_menu(self) -> None:
        """显示排序方式下拉菜单（8 种模式，当前模式打勾）。

        使用 StyledContextMenu 实现，与 web 端下拉样式保持一致。
        """
        menu = StyledContextMenu(parent=self._sort_btn)
        for mode in range(8):
            menu.add_item(
                self.SORT_MODE_NAMES[mode],
                checkable=True,
                checked=(mode == self._sort_mode),
                callback=lambda m=mode: self._set_sort_mode(m),
            )
        btn = self._sort_btn
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _set_sort_mode(self, mode: int) -> None:
        """切换排序模式：raw 缓存可用则内存重排，否则重扫当前目录。

        Args:
            mode: 排序模式 0-7。
        """
        self._sort_mode = mode
        self._sort_btn.setToolTip(f"排序: {self.SORT_MODE_NAMES[mode]}")
        if not self._current_path:
            return
        if self._stream_active_token == self._async_load_token:
            # 流式加载进行中：仅更新模式，收尾时按新模式重排最终集合。
            return
        if self._current_path != "All" and self._raw_entries_path == self._current_path:
            self._apply_entries_in_memory()
        else:
            self._reload_directory()

    def _toggle_view_mode(self) -> None:
        icons_dir = get_icons_dir()
        if self._view_mode == "card":
            self._view_mode = "list"
            self._card_delegate.set_list_mode()
            self._file_list.setViewMode(QListView.IconMode)
            self._file_list.setFlow(QListView.TopToBottom)
            self._file_list.setWrapping(False)
            self._card_btn.set_svg_icon(str(icons_dir / "card.svg"))
            self._card_btn.setToolTip("切换为卡片视图")
        else:
            self._view_mode = "card"
            self._card_delegate.set_card_mode()
            self._file_list.setViewMode(QListView.IconMode)
            self._file_list.setFlow(QListView.LeftToRight)
            self._file_list.setWrapping(True)
            self._card_btn.set_svg_icon(str(icons_dir / "list.svg"))
            self._card_btn.setToolTip("切换为列表视图")
        QTimer.singleShot(0, self._update_grid_size)

    def set_section_styles(
        self,
        fill_color: str,
        border_color: str,
        bar_fill_color: Optional[str] = None,
    ) -> None:
        """应用面板样式到顶栏/内容区/底栏（主题切换时由 MainWindow 调用）。

        Args:
            fill_color: 内容区填充色。
            border_color: 边框色。
            bar_fill_color: 顶栏/底栏填充色；``None`` 时与内容区同色
                （深色模式口径）。
        """
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        bar_style = section_style
        if bar_fill_color is not None:
            bar_style = f"""
            background-color: {bar_fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        for _w, _style in (
            (self._top_bar, bar_style),
            (self._content_area, section_style),
            (self._bottom_bar, bar_style),
        ):
            register_widget_qss(_w, _style)
            # 强制已显示控件重新套用样式（延迟构建场景下必须，否则边框/填充不重绘）
            _w.style().unpolish(_w)
            _w.style().polish(_w)
