"""
文件选择器布局 — 顶栏（固定高度）+ 内容区（自适应拉伸）+ 底栏（固定高度）
"""

import ctypes
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QListView, QLabel, QAbstractItemView, QApplication, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QMargins, QObject, QPoint, QRect, QRunnable, QThreadPool
from PySide6.QtGui import QFont, QFontMetrics

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
from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge


# 目录加载指示器延迟显示时长（毫秒）：快目录不闪遮罩，慢目录（大目录/
# 机械盘/网络盘）才有转圈反馈。
DIR_LOADING_INDICATOR_DELAY_MS = 120

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


def _native_scan_directory(path: str) -> Optional[List[Dict[str, Any]]]:
    """经 faf_core 桥扫描目录；桥不可用/失败返回 None（调用方回退 Python）。

    Args:
        path: 待扫描目录绝对路径。

    Returns:
        Optional[List[Dict[str, Any]]]: 7 键条目列表；DLL 缺失、native 失败
            或超 8MB 上限时返回 ``None``。
    """
    try:
        bridge = get_faf_core_bridge()
    except Exception:  # noqa: BLE001  # FFI 边界防御
        return None
    if bridge is None or not bridge.available or not getattr(bridge, "_supports_scan", False):
        return None
    try:
        return bridge.scan_directory(path)
    except Exception:  # noqa: BLE001  # FFI 边界防御
        return None


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
    try:
        bridge = get_faf_core_bridge()
    except Exception:  # noqa: BLE001  # FFI 边界防御
        return None
    if bridge is None or not bridge.available or not getattr(bridge, "_supports_sort", False):
        return None
    try:
        return bridge.sort_entries(entries, mode)
    except Exception:  # noqa: BLE001  # FFI 边界防御
        return None


class _DirectoryCollectRunnable(QRunnable):
    """异步目录收集任务（QRunnable 投 ``QThreadPool.globalInstance()``）。

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
    """

    def __init__(
        self,
        owner: "FileSelectorLayout",
        path: str,
        token: int,
        include_remote: bool = False,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._owner = owner
        self._path = path
        self._token = token
        self._include_remote = bool(include_remote)

    def run(self) -> None:
        try:
            entries = self._owner._collect_directory_entries(
                self._path,
                cancel_check=lambda: self._owner._async_load_token != self._token,
                include_remote=self._include_remote,
            )
        except Exception as exc:  # noqa: BLE001  # 后台任务兜底：异常按不可读处理
            debug(f"目录收集异常（{self._path}）: {exc}")
            entries = None
        try:
            self._owner._dir_entries_ready.emit(self._path, entries, self._token)
        except RuntimeError:
            # 宿主（FileSelectorLayout）已销毁：丢弃结果即可
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._previewing_file_path: str = ""  # 当前预览态卡片的文件路径（空 = 无）
        # 网络/映射盘与光驱加载开关（general.include_remote_drives，默认关闭；
        # 启动时与设置提交时经 set_include_remote_drives 下发）
        self._include_remote_drives: bool = _DEFAULT_INCLUDE_REMOTE_DRIVES
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

        # 设置最小宽度，确保至少能显示 3 列卡片（与旧 file_selector.py 保持一致）
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
        self._view_mode: str = "card"
        self._nav_history: List[str] = []
        self._history_index: int = -1
        self._sort_mode: int = 0
        self._first_show: bool = True
        # 异步目录加载：递增 token 丢弃过期结果（快速连续导航场景）
        self._async_load_token: int = 0
        self._dir_entries_ready.connect(self._on_dir_entries_ready)
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

        Args:
            obj: 事件来源对象（viewport 或文件列表视图）。
            event: Qt 事件对象。

        Returns:
            True 表示事件已消费，False 表示放行给默认处理。
        """
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
        if self._first_show:
            self._first_show = False
            QTimer.singleShot(50, self._init_navigation)

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
        # 注：盘符过滤开关由 _load_directory_async → _DirectoryCollectRunnable
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
                entries.append({
                    "name": drive_name, "path": drive_path, "is_dir": True,
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
        except Exception:
            pass
        return False

    def _save_last_path(self, path: str) -> None:
        save_file = Path(get_app_data_path()) / "last_path.json"
        try:
            import json
            with open(save_file, "w", encoding="utf-8") as f:
                json.dump({"last_path": os.path.abspath(path)}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _clear_last_path(self) -> None:
        """删除 last_path.json，使下次启动不恢复任何路径，直接落到 All。"""
        save_file = Path(get_app_data_path()) / "last_path.json"
        try:
            save_file.unlink(missing_ok=True)
        except Exception:
            pass

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
        nav_row.addWidget(self._path_input, stretch=1)

        arrow_icon = str(icons_dir / "arrow_right.svg")
        self._arrow_btn = StyledButton("", variant="ghost", size="sm", icon=arrow_icon)
        self._arrow_btn.setFixedSize(32, 32)
        nav_row.addWidget(self._arrow_btn)

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
    ) -> Optional[List[Dict[str, Any]]]:
        """纯 IO 收集目录条目（桥可用时优先 native 扫描，否则 Python 回退）。

        单点接线：同步路径（``_load_directory``）与异步路径
        （``_DirectoryCollectRunnable.run``）都经此方法。可在后台线程执行
        ——不触碰任何 Qt/主线程状态。``"All"`` 视图固定走纯 Python 枚举
        （不经 native 桥）。返回条目列表；目录不可读时返回 None
        （调用方执行与同步路径一致的清空处理）。

        Args:
            path: 待收集目录路径；``"All"`` 表示磁盘视图。
            cancel_check: 可选取消检查回调（后台线程用，返回 True 表示
                请求已过期、应尽快放弃）；仅 Python 回退路径消费。
            include_remote: ``"All"`` 视图的网络/映射盘与光驱开关；其他
                路径忽略。``None`` 时取静态默认（关闭）。

        Returns:
            Optional[List[Dict[str, Any]]]: 7 键条目列表；目录不可读返回
                ``None``。
        """
        if path == "All":
            return FileSelectorLayout._collect_all_drives_python(include_remote)
        native_entries = _native_scan_directory(path)
        if native_entries is not None:
            return native_entries
        return FileSelectorLayout._collect_directory_entries_python(path, cancel_check)

    @staticmethod
    def _collect_directory_entries_python(
        path: str,
        cancel_check=None,
    ) -> Optional[List[Dict[str, Any]]]:
        """既有 Python 收集实现（listdir + 逐文件 stat），native 回退路径。

        Args:
            path: 待收集目录路径。
            cancel_check: 可选取消检查回调；每个条目处理前调用，返回 True
                时立即放弃并返回 ``None``（过期结果由 token 侧丢弃）。

        Returns:
            Optional[List[Dict[str, Any]]]: 7 键条目列表；目录不可读返回
                ``None``。
        """
        try:
            entries: List[Dict[str, Any]] = []
            for name in os.listdir(path):
                if cancel_check is not None and cancel_check():
                    return None
                full_path = os.path.join(path, name)
                try:
                    st = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    suffix = os.path.splitext(name)[1].lower().lstrip(".") if not is_dir else ""
                    modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
                    created = datetime.fromtimestamp(st.st_ctime).strftime("%Y-%m-%d %H:%M")
                    entries.append({
                        "name": name, "path": full_path, "is_dir": is_dir,
                        "size": st.st_size, "modified": modified, "created": created, "suffix": suffix,
                    })
                except (PermissionError, OSError):
                    continue
            return entries
        except (PermissionError, FileNotFoundError, OSError):
            return None

    def _load_directory(self, path: str) -> None:
        """同步加载目录（收集 + 应用），行为与旧实现逐字节等价。

        仅供测试与特殊同步场景使用；交互式导航请走 ``_load_directory_async``
        （后台线程收集，不阻塞 UI 线程）。
        """
        entries = self._collect_directory_entries(
            path, include_remote=self._include_remote_drives
        )
        if entries is None:
            self._file_list.setUpdatesEnabled(False)
            try:
                self._file_model.clear()
                self._current_path = ""
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
        """异步加载目录：后台线程收集条目，完成后回主线程应用。

        所有交互式导航（进入子目录/返回/刷新/路径框/收藏夹/定位）与启动
        首次加载统一走本入口：请求即返回，UI 线程零文件 IO。递增 token
        保证快速连续导航只应用最后一次请求的结果；过期任务在 Python 回退
        扫描中经 ``cancel_check`` 尽早退出（native 扫描无法中途取消，但
        仍在后台线程执行，不阻塞 UI）。

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
        self._update_path_input(path)
        self._start_loading_indicator()
        QThreadPool.globalInstance().start(
            _DirectoryCollectRunnable(
                self, path, token, self._include_remote_drives
            )
        )

    def _on_dir_entries_ready(
        self, path: str, entries: Optional[List[Dict[str, Any]]], token: int
    ) -> None:
        """后台收集完成（主线程槽）：过期结果直接丢弃，否则应用并收尾。

        成功：应用条目（All 视图走 ``_apply_all_entries``）→ 播放挂起的
        路径过渡动画 → 处理挂起定位请求；失败：取消过渡、保留当前目录
        视图（回滚路径框/历史/last_path），启动首次加载失败则回退到
        All 视图。
        """
        if token != self._async_load_token:
            return
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
        """排序条目列表（name 预排序 + 模式排序；native 优先，回退 Python）。

        与既有 ``_apply_directory_entries`` 的排序管线逐字节一致：先按
        ``(not is_dir, name.lower())`` 稳定预排序，再按当前模式排序——
        equal-key 相对序由预排序决定，native（``faf_sort_entries``，语义与
        ``_apply_sort`` 逐字节一致）与 Python 结果等价，故两路径可互换。

        Args:
            entries: 7 键条目列表（不被就地修改）。

        Returns:
            List[Dict[str, Any]]: 排序后的条目列表。
        """
        entries = list(entries)
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        native = _native_sort_entries(entries, self._sort_mode)
        if native is not None:
            return native
        self._apply_sort(entries)
        return entries

    def _apply_entries_in_memory(self) -> None:
        """从 raw 缓存内存重排（筛选 + 排序）并更新 model/网格/计数，不重扫磁盘。

        排序切换与筛选应用（``_set_sort_mode`` / ``_apply_filter_or_reload``）
        共用：复制原始条目 → Python 侧 ``_matches_filter`` 筛选 → 内存排序
        （native ``faf_sort_entries`` 优先，否则 ``_apply_sort``）。仅在
        ``_raw_entries_path == _current_path`` 且非 "All" 时调用。
        """
        entries = [dict(e) for e in self._raw_entries]
        if self._filter_pattern:
            entries = [e for e in entries if self._matches_filter(e["name"])]
        sorted_entries = self._sort_entries(entries)
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
        保持既有重扫行为（刷新语义）。
        """
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
        path = self._path_input.text().strip()
        if path:
            self._navigate_to(path)

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
        info = {
            "name": self._file_model.data(index, FileNameRole) or "",
            "path": file_path,
            "is_dir": False,
            "size": int(self._file_model.data(index, FileSizeRole) or 0),
            "modified": self._file_model.data(index, ModifiedRole) or "",
            "created": self._file_model.data(index, CreatedRole) or "",
            "suffix": (self._file_model.data(index, SuffixRole) or "").lower(),
        }
        # 再次点击当前预览文件 → 取消预览；否则预览
        import os

        if (self._previewing_file_path
                and os.path.normcase(os.path.normpath(self._previewing_file_path))
                == os.path.normcase(os.path.normpath(file_path))):
            self.preview_cancel_requested.emit()
        else:
            self.file_selected.emit(info)

    # ── 右键菜单 ──────────────────────────────────────────────────────────

    def _on_right_click_toggle_pool(self, pos) -> None:
        """右键：已选中卡片批量入池/移出；未选中卡片单卡切换；空白区返回上一级。

        - 右键点在框选选中的卡片上：
          - 全部选中项都已在储存池中 → 批量移出储存池（取消加入）；
          - 否则 → 批量加入储存池（add-only，已在池中的保持不变）；
          两种情况随后均清除框选选中态；
        - 右键点在未选中卡片上：清除框选 + 保留原有单卡"添加/移除"切换；
        - 右键点在空白区：清除框选 + 返回上一级（与顶栏按钮/鼠标侧键一致，
          两条路径互不冲突）。
        """
        index = self._file_list.indexAt(pos)
        if not index.isValid():
            # 无卡片空白区右键 = 返回上一级（历史优先，与顶栏按钮/鼠标侧键一致）
            self.clear_box_selection()
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
                f"font-size: 14px; color: {tm.mid.name()}; background: transparent;"
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
        register_widget_qss(tip,(f"font-size: 14px; color: {tm.mid.name()}; background: transparent;"))
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

    def _show_message_dialog(self, title: str, message: str) -> None:
        """通用消息提示弹窗（StyledDialog）。"""
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
        register_widget_qss(tip,(f"font-size: 14px; color: {tm.mid.name()}; background: transparent;"))
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
        self._path_input.setText(path)

    def _update_file_count(self, count: int) -> None:
        self._file_count_label.setText(f"{count} 个条目")
        register_widget_qss(self._file_count_label,(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 11px;"
        ))

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
        except Exception:
            pass

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
        """设置最小宽度，确保至少能显示 3 列卡片（与旧 file_selector.py 一致）。"""
        dpi = 1.0
        card_width = self._calculate_card_base_width()
        spacing = int(4 * dpi)
        margin = int(5 * dpi)
        cards_total_width = 3 * card_width + 2 * spacing
        margins_total = 2 * margin
        min_filelist_width = cards_total_width + margins_total

        # 滚动条为浮动覆盖层，不计入最小宽度
        self.setMinimumWidth(min_filelist_width)

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

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        for _w in (self._top_bar, self._content_area, self._bottom_bar):
            register_widget_qss(_w,(section_style))
            # 强制已显示控件重新套用样式（延迟构建场景下必须，否则边框/填充不重绘）
            _w.style().unpolish(_w)
            _w.style().polish(_w)
