"""
文件选择器布局 — 顶栏（固定高度）+ 内容区（自适应拉伸）+ 底栏（固定高度）
"""

import ctypes
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QListView, QLabel, QAbstractItemView, QApplication, QMessageBox, QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QEvent, QMargins, QPoint, QRect, QItemSelectionModel, QObject
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from theme import tm
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.utils.app_logger import debug as _rubber_log
from freeassetfilter.core.workers.thumbnail_controller import ThumbnailController
from components.styled_button import StyledButton
from components.styled_lineedit import StyledLineEdit
from components.styled_context_menu import StyledContextMenu
from components.styled_dialog import StyledDialog, FOOTER_RIGHT, FOOTER_CENTER, create_basic_dialog, _show_dialog
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.file_list_model import FileListModel, FilePathRole, FileNameRole, IsDirRole, FileSizeRole, ModifiedRole, CreatedRole, SuffixRole, IsPreviewingRole, IconPixmapRole
from components.file_card_delegate import FileCardDelegate, CARD_CONFIG, LIST_CONFIG
from components.animated_file_list_view import AnimatedFileListView
from freeassetfilter.services.favorites_service import FavoritesService
from freeassetfilter.services.file_icon_manager import FileIconManager

# 释放丢失守卫的轮询周期（毫秒）：框选期间周期性校验按键是否仍按下。
# 仅在框选激活期间运行，100ms 对拖拽帧率与 CPU 均无可见影响。
RUBBER_GUARD_INTERVAL_MS = 100

# 框选覆层半透明填充的全局 alpha（与旧 QRubberBand QSS background @36 一致）。
_RUBBER_FILL_ALPHA = 36


def _btn_str(value: Any) -> str:
    """Qt 按键枚举/flags 的日志安全格式化。

    PySide6 6.10+ 的枚举不再支持 ``int()``（抛 TypeError），统一走 ``.value``。

    Args:
        value: Qt.MouseButton / Qt.MouseButtons 或任意值。

    Returns:
        可读字符串（取不到 value 时回退 str）。
    """
    try:
        return str(getattr(value, "value", value))
    except Exception:  # noqa: BLE001
        return "?"


class _RubberBandOverlay(QWidget):
    """文件选择器专用的单框橡皮筋覆层（替代 QRubberBand）。

    背景：Windows 各平台样式下 QRubberBand 会在 QSS 边框之上叠加平台自绘
    的 XOR 框，真实鼠标拖拽时肉眼看到两个叠加的选框、且平台框不受 QSS
    颜色约束；这里改为完全自绘的单边框覆层——恰好一个矩形、颜色精确
    （左键框选 = 主题强调色，右键框选 = 警告色）、随主题实时刷新。

    鼠标事件一律透传（WA_TransparentForMouseEvents）：覆层仅是视觉层，
    框选状态机只由 viewport 的事件过滤器驱动，覆层自身不参与事件。
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color: QColor = QColor(Qt.transparent)

    def set_color(self, color: QColor) -> None:
        """设置边框与填充的基色（填充取其 36 透明度版本）。

        Args:
            color: 主题强调色或警告色。
        """
        color = QColor(color)
        if color == self._color:
            return
        self._color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """自绘单边框矩形：半透明填充 + 1px 实心边框（无抗锯齿防发虚）。"""
        color = self._color
        if color.alpha() == 0:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, False)
            fill = QColor(color)
            fill.setAlpha(_RUBBER_FILL_ALPHA)
            painter.fillRect(self.rect(), fill)
            painter.setPen(QPen(color))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        finally:
            painter.end()


class FileSelectorLayout(QWidget):
    """文件选择器布局（左侧栏）"""

    file_selected = Signal(dict)
    file_selection_changed = Signal(dict, bool)
    preview_cancel_requested = Signal()
    add_to_pool_requested = Signal(dict)        # 左键框选/批量入池：逐文件添加（add-only，池内去重）
    remove_from_pool_requested = Signal(dict)   # 右键框选批量删除：逐文件从池移除
    toggle_pool_requested = Signal(dict)  # 右键直连：添加/移除文件池
    # 异步目录加载：后台线程收集完成后发射（path, entries 或 None, token）
    _dir_entries_ready = Signal(str, object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._previewing_file_path: str = ""  # 当前预览态卡片的文件路径（空 = 无）
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
        self._file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
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
        self._file_list.setStyleSheet("""
            QListView {
                background: transparent;
                border: none;
                padding: 0px;
            }
            QListView::item {
                background: transparent;
            }
        """)

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

        # ── 框选多选状态（鼠标左键按住拖拽 = 橡皮筋框选 / 右键 = 批量删除）───────
        # 状态机按键无关：_rubber_button 记录本次手势按键（Left/Right）。
        # 左键框选 = 选中卡片并加入存储池；右键框选 = 批量删除池内卡片。
        self._rubber_band: Optional[QWidget] = None  # 自绘单框覆层（_RubberBandOverlay）
        self._rubber_button: Optional[Qt.MouseButton] = None  # 手势按键（None = 无手势）
        self._rubber_start_pos: Optional[QPoint] = None  # 按下起点（viewport 坐标），None = 未按下
        self._rubber_rect: Optional[QRect] = None        # 当前框选矩形
        self._rubber_active: bool = False                # 是否已超过拖拽阈值进入框选态
        self._rubber_ctrl: bool = False                  # 按下时是否按住 Ctrl（追加模式）
        self._rubber_pressed_row: int = -1               # 按下位置所在行（空白处 = -1）
        self._rubber_preselect: set = set()              # 按下时已选中的行集合（Ctrl 追加基准）
        self._rubber_last_rows: Optional[Set[int]] = None  # 上次应用的行集合（无变化时跳过刷新）
        self._rubber_last_pos: Optional[QPoint] = None   # 最后一次拖拽位置（释放丢失时守卫据此收尾）
        # 右键框选结束后压制随之而来的 ContextMenu（避免拖选完成弹出右键菜单）。
        self._context_menu_suppressed: bool = False
        # 释放丢失守卫：仅框选期间运行的 QTimer，轮询鼠标按键状态兜底收尾。
        self._rubber_guard_timer: Optional[QTimer] = None
        # 网格指标（由 _apply_grid_layout / _update_list_grid 维护，用于框选时 O(1) 定位行）
        self._grid_metrics: Dict[str, int] = {}
        # 当前文件池路径集合（右键框选"仅删除已在池的卡片"的判定依据，由 sync_pool_status 更新）
        self._pool_paths: Set[str] = set()
        # 应用失活（真实鼠标拖拽中途 alt-tab/窗口切换）时兜底中止，防选框粘连。
        try:
            app = QApplication.instance()
            if app is not None:
                app.applicationStateChanged.connect(self._on_application_state_changed)
        except (RuntimeError, TypeError, AttributeError):
            pass
        # 主题切换时刷新框选样式（覆层颜色跟随强调色）。
        try:
            tm.theme_changed.connect(self._refresh_rubber_band_style)
        except (RuntimeError, TypeError, AttributeError):
            pass

    # ── 事件过滤器：在 QListView resize 前更新网格 ──────────────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """事件过滤器：网格自适应 + 缩放 + 左键框选 + 右键框选 + 侧键后退。

        同时监听 viewport 与 QListView 自身的 Resize；Wheel+Ctrl 走卡片缩放；
        左键 press/move/release 委托给框选三件套（左键 = 框选入池）；
        右键 press/move/release 同样委托（右键 = 框选批量删除池内卡片）；
        右键框选结束后压制紧随的 ContextMenu（避免菜单弹出）。

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
                if event.button() in (Qt.LeftButton, Qt.RightButton):
                    return self._on_rubber_press(event, obj)
            elif event.type() == QEvent.MouseMove:
                if self._rubber_start_pos is not None:
                    return self._on_rubber_move(event, obj)
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() in (Qt.LeftButton, Qt.RightButton) and (
                    self._rubber_active or self._rubber_start_pos is not None
                ):
                    return self._on_rubber_release(event, obj)
            elif event.type() == QEvent.ContextMenu:
                # 右键拖拽释放后若状态已复位，仅靠 _rubber_active/_rect 无法判定，
                # 由 _context_menu_suppressed 标记压制本次拖拽跟随弹出的菜单（一次即清）。
                if self._context_menu_suppressed:
                    self._context_menu_suppressed = False
                    return True
                if self._rubber_active or self._rubber_rect is not None:
                    return True
        return super().eventFilter(obj, event)

    # ── 框选多选（橡皮筋）─────────────────────────────────────────────

    def _viewport_pos(self, event: QEvent, obj: Optional[object] = None) -> QPoint:
        """将鼠标事件位置统一换算为 viewport 坐标。

        与文件池 _pool_viewport_pos 同策略：事件可能来自 viewport、QListView
        本体（帧/边距区）等不同对象，直接取 event.position() 会带着对象自身
        的坐标系，导致选框起点/锚点错位（"起点乱飞"）；统一映射到 viewport
        坐标系后，起点永远精确落在鼠标按下位置。

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

    def _on_rubber_press(self, event: QEvent, obj=None) -> bool:
        """按下：记录手势起点（按键无关，左键 = 框选入池 / 右键 = 框选删除）。

        起点统一映射到 viewport 坐标（见 _viewport_pos），保证选框锚点精确。

        左键：单手势接管起点（不立即激活，等待移动超过拖拽阈值），吞掉事件——
        Qt 原生 IconMode 框选与自定义橡皮筋不可共存，单击语义由松开时合成。
        右键：与文件池一致"只记录起点、放行事件"，保留既有右键单击直连
        文件池（_on_right_click_toggle_pool）语义。

        Args:
            event: 鼠标按下事件。
            obj: 事件来源对象（viewport 或列表视图）。

        Returns:
            左键恒为 True（已消费）；右键 False（放行给默认处理，保留单击语义）。
        """
        self._abort_rubber_selection()
        # 新一次手势开始：消费上一次可能残留的右键菜单压制标记
        # （拖拽释放后若 ContextMenu 从未到达，标记需在下一次按下前复位）。
        self._context_menu_suppressed = False
        pos = self._viewport_pos(event, obj)
        self._rubber_button = event.button()
        index = self._file_list.indexAt(pos)
        self._rubber_pressed_row = index.row() if index.isValid() else -1
        self._rubber_start_pos = pos
        self._rubber_ctrl = bool(event.modifiers() & Qt.ControlModifier)
        self._rubber_preselect = set(self._file_model.get_selected_rows())
        self._rubber_last_rows = None
        self._rubber_last_pos = pos
        try:
            _rubber_log(
                f"[rubber] press obj={type(obj).__name__} pos={pos.x()},{pos.y()} "
                f"row={self._rubber_pressed_row} btn={_btn_str(self._rubber_button)}"
            )
        except Exception:
            pass
        if event.button() == Qt.RightButton:
            # 右键 press 放行前显式抓取 viewport：防止空区域按下被 ignore 后
            # 沿父链传播，导致真实鼠标拖拽中 move 路由丢失、框选无法激活。
            # 抓取由 _abort_rubber_selection 统一 releaseMouse，无残留路径。
            try:
                self._file_list.viewport().grabMouse()
            except (RuntimeError, AttributeError, TypeError):
                pass
        return event.button() == Qt.LeftButton

    def _on_rubber_move(self, event: QEvent, obj=None) -> bool:
        """拖拽：超过阈值后激活橡皮筋，实时更新选框（左键同时更新命中选中态）。

        Args:
            event: 鼠标移动事件（viewport 坐标系）。
            obj: 事件来源对象。

        Returns:
            True 已进入框选态并消费事件，False 尚未超过拖拽阈值。
        """
        if self._rubber_start_pos is None or self._rubber_button is None:
            return False
        # 无按键移动：此前某次释放丢失/中断导致的状态残留在此自愈清理，
        # 保证选框永不跟随空移鼠标（正常拖拽中手势按键始终处于按下态）。
        if not (event.buttons() & self._rubber_button):
            self._abort_rubber_selection()
            return False
        pos = self._viewport_pos(event, obj)
        if not self._rubber_active:
            delta = pos - self._rubber_start_pos
            threshold = max(4, QApplication.startDragDistance())
            if abs(delta.x()) < threshold and abs(delta.y()) < threshold:
                return False
            self._rubber_active = True
            try:
                self._file_list.viewport().grabMouse()
            except (RuntimeError, AttributeError, TypeError):
                pass
            self._show_rubber_band()
            self._start_rubber_guard()
            try:
                _rubber_log(
                    f"[rubber] activate btn={int(self._rubber_button)} "
                    f"pos={pos.x()},{pos.y()}"
                )
            except Exception:
                pass
        self._rubber_last_pos = pos
        self._update_rubber_geometry(pos)
        # 左键框选：实时更新框内卡片选中态；右键框选：纯视觉（不触碰选中态）。
        if self._rubber_button == Qt.LeftButton:
            self._update_rubber_selection(pos)
        return True

    def _update_rubber_geometry(self, pos: QPoint) -> None:
        """按当前鼠标位置更新选框几何，并在拖出 viewport 上下边时自动滚动。

        逻辑命中矩形可超出 viewport（扩展矩形参与完全包含判定），
        显示矩形（覆层几何）钳制在 viewport 内。

        Args:
            pos: 当前鼠标位置（viewport 坐标，可为 viewport 之外）。
        """
        start = self._rubber_start_pos
        if start is None:
            return
        viewport = self._file_list.viewport()
        vbar = self._file_list.verticalScrollBar()
        # 越界自动滚动（DPI 无关，滚动步长取像素差）。
        if vbar is not None and viewport is not None:
            vp_h = viewport.height()
            if pos.y() < 0:
                vbar.setValue(vbar.value() + pos.y())
            elif pos.y() > vp_h:
                vbar.setValue(vbar.value() + (pos.y() - vp_h))
        rect = QRect(start, pos).normalized()
        if rect.isNull():
            return
        empty_threshold = max(4, QApplication.startDragDistance())
        if rect.width() < empty_threshold or rect.height() < empty_threshold:
            return
        self._rubber_rect = rect
        if self._rubber_band is not None and viewport is not None:
            display_rect = rect.intersected(QRect(QPoint(0, 0), viewport.size()))
            if display_rect.isValid():
                self._rubber_band.setGeometry(display_rect)
            else:
                self._rubber_band.setGeometry(rect)

    def _update_rubber_selection(self, pos: QPoint) -> None:
        """根据当前框选矩形更新卡片选中态（模型驱动，delegate 同步高亮）。

        选框几何与自动滚动由 _update_rubber_geometry 统一处理，这里只负责
        把命中行集合应用到模型 + QItemSelectionModel（仅左键框选使用）。

        Args:
            pos: 当前鼠标位置（viewport 坐标，可为 viewport 之外）。
        """
        start = self._rubber_start_pos
        if start is None:
            return
        rect = QRect(start, pos).normalized()
        if rect.isNull():
            return
        empty_threshold = max(4, QApplication.startDragDistance())
        if rect.width() < empty_threshold or rect.height() < empty_threshold:
            return
        if self._rubber_rect is None:
            self._rubber_rect = rect

        band_rows = self._rows_in_rect(rect)
        target_rows = band_rows | self._rubber_preselect if self._rubber_ctrl else band_rows
        if target_rows == self._rubber_last_rows:
            return
        self._rubber_last_rows = set(target_rows)

        model = self._file_model
        current_rows = model.get_selected_rows()
        to_select = target_rows - current_rows
        to_deselect = current_rows - target_rows
        model.set_rows_selected(to_select, True)
        model.set_rows_selected(to_deselect, False)
        # 同步 QItemSelectionModel，保证视图内部选中态一致
        selection_model = self._file_list.selectionModel()
        if selection_model is not None:
            for row in to_deselect:
                selection_model.select(
                    model.index(row, 0), QItemSelectionModel.Deselect | QItemSelectionModel.Rows
                )
            for row in to_select:
                selection_model.select(
                    model.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows
                )

    def _on_rubber_release(self, event: QEvent, obj=None) -> bool:
        """松开：按键无关的收尾分发（左键 = 框选入池 / 右键 = 框选批量删除）。

        已激活 → 统一走 _finish_rubber_selection（松开事件与守卫共用收尾路径）。
        未拖拽（单击）：
          - 左键：合成点击（还原 clicked → _on_file_clicked 语义，因为按下已被接管）；
          - 右键：放行给 Qt，保留既有右键单击直连文件池（ContextMenu → toggle）。

        Args:
            event: 鼠标松开事件（viewport 坐标系）。
            obj: 事件来源对象（仅用于诊断日志）。

        Returns:
            左键单击恒为 True（已消费）；右键单击返回 False（放行）。
        """
        try:
            _rubber_log(
                f"[rubber] release obj={type(obj).__name__} "
                f"buttons={_btn_str(event.buttons())} active={self._rubber_active} "
                f"pos={event.position().toPoint().x()},{event.position().toPoint().y()}"
            )
        except Exception:
            pass
        button = self._rubber_button
        if self._rubber_active:
            self._finish_rubber_selection(self._viewport_pos(event, obj))
            return True
        if button != Qt.LeftButton:
            # 右键单击：恢复初始态并放行，保留 ContextMenu → 直连文件池语义。
            self._abort_rubber_selection()
            return False
        # 左键单击：按下已被单手势接管，Qt 收不到 press，这里合成点击还原。
        pressed_row = self._rubber_pressed_row
        self._rubber_start_pos = None
        self._rubber_rect = None
        self._rubber_last_rows = None
        self._rubber_ctrl = False
        self._rubber_button = None
        self._rubber_pressed_row = -1
        self._rubber_preselect = set()
        self._rubber_last_pos = None
        if pressed_row < 0:
            # 空白处单击：清空选中（兼容 Qt 默认行为）
            self._clear_selector_selection()
            return True
        # 卡片上单击：合成点击（还原 clicked → _on_file_clicked 语义）。
        model = self._file_model
        index = self._file_list.indexAt(self._viewport_pos(event, obj))
        if not index.isValid() and 0 <= pressed_row < model.rowCount():
            index = model.index(pressed_row, 0)
        if index.isValid():
            self._on_file_clicked(index)
        else:
            self._clear_selector_selection()
        return True

    def _finish_rubber_selection(self, pos: Optional[QPoint]) -> None:
        """收尾一次已激活的框选：补终点更新 → 执行手势动作 → 复位状态。

        按键分支：
          - 左键：把框内选中卡片追加加入存储池（add-only，池内去重、绝不移出）；
            随后清空选择器选中态。
          - 右键：把框内"已在存储池"的卡片批量移出存储池（未入池的不受影响）。

        松开事件与守卫定时器共用同一条收尾路径，避免逻辑分叉导致状态残留；
        任何中间异常都不导致选框/抓取/守卫定时器残留（外层 finally 兜底复位）。

        Args:
            pos: 收尾时的鼠标位置（viewport 坐标）；None 表示无可用终点，
                跳过最后一次命中行补充（仍完成手势动作与清理）。
        """
        if not self._rubber_active:
            self._abort_rubber_selection()
            return
        button = self._rubber_button
        try:
            if pos is not None:
                self._update_rubber_geometry(pos)
                if button == Qt.LeftButton:
                    self._update_rubber_selection(pos)
            try:
                if button == Qt.RightButton:
                    self._batch_remove_pool_cards_in_rect(self._rubber_rect)
                    self._context_menu_suppressed = True
                    return
                # 左键入池信号直连主窗口槽（池添加/备份/动画），其中抛异常
                # 也不得跳过选中清理，否则模型高亮残留形成"粘连/幽灵框"。
                self._add_selected_to_pool()
            finally:
                if button == Qt.LeftButton:
                    self._clear_selector_selection()
        finally:
            self._abort_rubber_selection()

    def _batch_remove_pool_cards_in_rect(self, rect: Optional[QRect]) -> None:
        """右键框选批量删除：把框内"已在存储池"的卡片逐文件移出存储池。

        仅对已在池内的路径生效（命中判定用 _pool_paths，与 delegate 的"已在池"
        边框标记同源）；非池内卡片不受任何影响。逐文件发射 remove_from_pool_requested，
        池的 remove_file 幂等，可安全批量调用。

        Args:
            rect: 框选矩形（viewport 坐标，已 normalized）；None 时跳过。
        """
        if rect is None or rect.isNull():
            return
        pool_paths = self._pool_paths
        if not pool_paths:
            return
        model = self._file_model
        removed_count = 0
        for row in sorted(self._rows_in_rect(rect)):
            idx = model.index(row, 0)
            file_path = model.data(idx, FilePathRole) or ""
            if not file_path:
                continue
            if os.path.normcase(os.path.normpath(file_path)) not in pool_paths:
                continue
            info: Dict[str, Any] = {
                "name": model.data(idx, FileNameRole) or "",
                "path": file_path,
                "is_dir": bool(model.data(idx, IsDirRole)),
                "size": int(model.data(idx, FileSizeRole) or 0),
                "modified": model.data(idx, ModifiedRole) or "",
                "created": model.data(idx, CreatedRole) or "",
                "suffix": (model.data(idx, SuffixRole) or "").lower(),
            }
            self.remove_from_pool_requested.emit(info)
            removed_count += 1
        try:
            _rubber_log(f"[rubber] right-select removed={removed_count}")
        except Exception:
            pass

    def _start_rubber_guard(self) -> None:
        """启动释放丢失守卫（主线程 QTimer，仅在框选期间运行）。

        仅依赖 viewport 的 move 自愈存在盲区：松开事件若因窗口失焦、被其他
        控件消费、鼠标抓取失效等原因未到达本控件，且鼠标不再回到列表区域，
        状态将一直残留。守卫改为轮询 QApplication 的全局按键状态，不再依赖
        任何事件到达，从机制上消除框选态/选框粘连。
        """
        timer = self._rubber_guard_timer
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(RUBBER_GUARD_INTERVAL_MS)
            timer.timeout.connect(self._on_rubber_guard_tick)
            self._rubber_guard_timer = timer
        if not timer.isActive():
            timer.start()

    def _stop_rubber_guard(self) -> None:
        """停止释放丢失守卫（幂等，未创建/未启动时无副作用）。"""
        timer = getattr(self, "_rubber_guard_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _on_rubber_guard_tick(self) -> None:
        """守卫轮询：手势按键已释放但框选态仍在时兜底收尾。

        QTimer 与鼠标事件同处主线程，无跨线程竞争；正常拖拽中按键始终按下，
        守卫不会干预。补充说明：真实鼠标松开事件丢失时 ``QApplication.mouseButtons``
        亦可能失真（它由 Qt 事件流驱动），_on_application_state_changed 的
        窗口失活中止是兜底的第二道防线。
        """
        if not self._rubber_active and self._rubber_start_pos is None:
            self._stop_rubber_guard()
            return
        button = self._rubber_button
        if button is not None and QApplication.mouseButtons() & button:
            return
        try:
            _rubber_log(
                "[rubber] guard finalize: button released without release event "
                f"btn={int(button) if button is not None else -1} "
                f"active={self._rubber_active} last_pos={self._rubber_last_pos}"
            )
        except Exception:
            pass
        if self._rubber_active:
            self._finish_rubber_selection(self._rubber_last_pos)
        else:
            self._abort_rubber_selection()

    def _on_application_state_changed(self, *args) -> None:
        """应用失活（alt-tab / 切换到其它窗口）时兜底中止进行中的框选。

        真实鼠标拖拽中途窗口失活，松开事件不会到达本控件，滚轮守卫依赖的
        ``QApplication.mouseButtons`` 也可能因事件流中断而失真（按键残留为
        按下态、守卫永不收尾）——应用失活是此类粘连最可靠的终止信号。

        Args:
            *args: Qt 信号附带参数（忽略）。
        """
        if self._rubber_start_pos is not None or self._rubber_active:
            try:
                _rubber_log("[rubber] app inactive -> abort")
            except Exception:
                pass
            self._abort_rubber_selection()

    def _rubber_band_color(self) -> QColor:
        """返回当前手势的选框颜色：左键 = 主题强调色，右键 = 警告色。

        Returns:
            QColor 实例（跟随主题实时变化）。
        """
        if self._rubber_button == Qt.RightButton:
            return QColor(tm.warning)
        return QColor(tm.accent)

    def _show_rubber_band(self) -> None:
        """创建（首次）并显示自绘单框覆层，颜色随手势按键（强调色/警告色）。

        viewport overlay 方案：覆层父级为 viewport，坐标系为 viewport 坐标；
        按下起点在此定锚为 0×0（后续由 _update_rubber_geometry 扩展）。
        """
        if self._rubber_band is None:
            self._rubber_band = _RubberBandOverlay(self._file_list.viewport())
            self._refresh_rubber_band_style()
        else:
            self._refresh_rubber_band_style()
        if self._rubber_start_pos is not None:
            self._rubber_band.setGeometry(QRect(self._rubber_start_pos, QSize(0, 0)))
        self._rubber_band.show()
        self._rubber_band.raise_()

    def _refresh_rubber_band_style(self, *_args: Any) -> None:
        """刷新选框颜色以跟随主题与当前手势按键（tm.theme_changed 槽函数）。

        Args:
            *_args: 主题信号附带参数（忽略，仅触发重算）。
        """
        band = self._rubber_band
        if band is None:
            return
        if hasattr(band, "set_color"):
            band.set_color(self._rubber_band_color())
        else:  # 兼容旧 QRubberBand 引用（防御）
            band.setGeometry(band.geometry())

    def _rows_in_rect(self, rect: QRect) -> Set[int]:
        """计算与框选矩形视觉重叠的行号集合（相交语义）。

        两段式判定：先用 _grid_metrics 做 first_row/last_row 粗筛定位候选
        范围，再对每个候选行用 view.visualRect 取 Qt 真实 item 矩形做
        rect.intersects(visual) 精判（视觉重叠即选中）。_row_rect /
        _resolve_flow_origin 仅提供粗筛原点兜底，不作为选中与否的最终依据。

        Args:
            rect: 框选矩形（viewport 坐标，已 normalized）。

        Returns:
            与框相交的行号集合；无指标/无数据时返回空集合。
        """
        metrics = self._grid_metrics
        model = self._file_model
        view = self._file_list
        row_count = model.rowCount()
        if row_count <= 0 or not metrics:
            return set()
        cell_w = metrics.get("cell_w", 0)
        cell_h = metrics.get("cell_h", 0)
        cols = metrics.get("cols", 0)
        if cell_w <= 0 or cell_h <= 0 or cols <= 0:
            return set()
        origin = self._resolve_flow_origin(rect)
        if origin is None:
            return set()
        x0, y0 = origin
        first_row = max(0, ((rect.top() - y0) // cell_h) * cols)
        last_row = min(row_count - 1, ((rect.bottom() - y0) // cell_h) * cols + cols - 1)
        hit_rows: Set[int] = set()
        for row in range(first_row, last_row + 1):
            visual = view.visualRect(model.index(row, 0))
            if not visual.isValid() or visual.isNull():
                continue
            if rect.intersects(visual):
                hit_rows.add(row)
        return hit_rows

    def _resolve_flow_origin(self, rect: QRect) -> Optional[Tuple[int, int]]:
        """从框选矩形附近可见的参考行解析流布局原点（viewport 坐标，含滚动偏移）。

        框全落空白时 indexAt 无命中，此时兜底：先扫描 viewport 可见首行
        的 visualRect 推导原点；仍无可见行则按 viewport 边距 + 滚动条值估算，
        避免大面积空白拖选直接返回空集合导致失效。

        Args:
            rect: 框选矩形（viewport 坐标）。

        Returns:
            原点 (x0, y0)；无数据/无指标时返回 None。
        """
        model = self._file_model
        view = self._file_list
        metrics = self._grid_metrics
        if model.rowCount() <= 0 or not metrics:
            return None
        cell_w = metrics.get("cell_w", 0)
        cell_h = metrics.get("cell_h", 0)
        cols = metrics.get("cols", 0)
        if cell_w <= 0 or cell_h <= 0 or cols <= 0:
            return None
        ref_row = -1
        for point in (rect.center(), rect.topLeft() + QPoint(1, 1), rect.bottomRight() - QPoint(1, 1), QPoint(2, 0)):
            index = view.indexAt(point)
            if index.isValid():
                ref_row = index.row()
                break
        if ref_row < 0:
            # 兜底 1：扫描 viewport 可见首行（沿垂直中线多点探测）。
            viewport = view.viewport()
            if viewport is not None:
                probe_x = max(2, viewport.width() // 2)
                probe_ys = (2, viewport.height() // 4, viewport.height() // 2,
                            viewport.height() * 3 // 4, max(2, viewport.height() - 3))
                for probe_y in probe_ys:
                    probe_index = view.indexAt(QPoint(probe_x, int(probe_y)))
                    if probe_index.isValid():
                        ref_row = probe_index.row()
                        break
        if ref_row < 0:
            # 兜底 2：按 viewport 边距 + 垂直滚动条值估算原点。
            viewport = view.viewport()
            vbar = view.verticalScrollBar()
            if viewport is None or vbar is None:
                return None
            margins = view.viewportMargins()
            x0 = margins.left()
            y0 = margins.top() - vbar.value()
            return x0, y0
        ref_rect = view.visualRect(model.index(ref_row, 0))
        if not ref_rect.isValid():
            return None
        x0 = ref_rect.x() - (ref_row % cols) * cell_w
        y0 = ref_rect.y() - (ref_row // cols) * cell_h
        return x0, y0

    @staticmethod
    def _row_rect(row: int, x0: int, y0: int, metrics: Dict[str, int]) -> QRect:
        """计算指定行的网格单元格矩形（基于流布局原点 + 网格间距）。

        Args:
            row: 行号（0-based）。
            x0: 流布局原点横坐标（viewport 坐标）。
            y0: 流布局原点纵坐标（viewport 坐标）。
            metrics: 网格指标（含 cell_w/cell_h/cols）。

        Returns:
            该行的单元格矩形（viewport 坐标）。
        """
        col = row % metrics["cols"]
        line = row // metrics["cols"]
        return QRect(
            x0 + col * metrics["cell_w"],
            y0 + line * metrics["cell_h"],
            metrics["cell_w"],
            metrics["cell_h"],
        )

    def _add_selected_to_pool(self) -> None:
        """将当前所有选中卡片追加加入存储池（add-only，已在池中的保持不变）。

        逐个发射 add_to_pool_requested，去重由 FilePoolLayout.add_file 负责。
        空选中时不发射任何信号。
        """
        model = self._file_model
        for file_path in model.get_selected_files():
            row = model.get_row(file_path)
            if row < 0:
                continue
            idx = model.index(row, 0)
            info: Dict[str, Any] = {
                "name": model.data(idx, FileNameRole) or "",
                "path": file_path,
                "is_dir": bool(model.data(idx, IsDirRole)),
                "size": int(model.data(idx, FileSizeRole) or 0),
                "modified": model.data(idx, ModifiedRole) or "",
                "created": model.data(idx, CreatedRole) or "",
                "suffix": (model.data(idx, SuffixRole) or "").lower(),
            }
            self.add_to_pool_requested.emit(info)

    def _clear_selector_selection(self) -> None:
        """清空文件选择器内所有卡片的选中态。

        模型（FileListModel.set_rows_selected）与 QItemSelectionModel 双路同步，
        卡片高亮由 delegate 按选中态自动绘制。
        """
        model = self._file_model
        model.set_rows_selected(model.get_selected_rows(), False)
        selection_model = self._file_list.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()

    def _abort_rubber_selection(self) -> None:
        """终止框选状态（释放鼠标抓取、隐藏覆层、复位记录；不触碰模型选中态）。

        连续框选安全：重复调用无副作用，隐藏后的覆层可复用。

        幂等清理全部框选状态：_rubber_active/_button/_start_pos/_rect/_ctrl/
        _pressed_row/_preselect/_last_rows，并隐藏覆层，保证永不残留。
        _context_menu_suppressed 不在本方法清理——右键拖拽收尾在 abort 前
        置位该标记，abort 若清除会导致紧随的 ContextMenu 压制失效；该标记
        由下一次手势按下（_on_rubber_press）或一次被压制的 ContextMenu 消费。
        """
        was_active = self._rubber_active
        had_start = self._rubber_start_pos is not None
        band_visible = False
        try:
            band_visible = bool(
                self._rubber_band is not None and self._rubber_band.isVisible()
            )
        except (RuntimeError, AttributeError):
            band_visible = False
        if was_active or had_start or band_visible:
            try:
                _rubber_log(
                    f"[rubber] abort was_active={was_active} had_start={had_start} "
                    f"band_visible={band_visible}"
                )
            except Exception:
                pass
        self._rubber_active = False
        self._rubber_button = None
        self._rubber_start_pos = None
        self._rubber_rect = None
        self._rubber_ctrl = False
        self._rubber_pressed_row = -1
        self._rubber_preselect = set()
        self._rubber_last_rows = None
        self._rubber_last_pos = None
        self._stop_rubber_guard()
        if self._rubber_band is not None:
            try:
                self._rubber_band.hide()
            except (RuntimeError, AttributeError):
                pass
        viewport = None
        try:
            viewport = self._file_list.viewport()
        except (RuntimeError, AttributeError):
            viewport = None
        if viewport is not None:
            try:
                viewport.releaseMouse()
            except (RuntimeError, AttributeError, TypeError):
                pass

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

    # ── 首次加载 ──────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if self._first_show:
            self._first_show = False
            QTimer.singleShot(50, self._init_navigation)

    def _init_navigation(self) -> None:
        app = QApplication.instance()
        initial_navigate_path = getattr(app, "initial_navigate_path", None)
        if initial_navigate_path and os.path.exists(initial_navigate_path):
            # 启动首次加载走异步路径，避免大目录 listdir+stat 阻塞首屏
            self._navigate_to_async(initial_navigate_path)
            return
        if self._try_restore_last_path():
            return
        self._navigate_to_all()

    # ── All 视图 ──────────────────────────────────────────────────────────

    def _navigate_to_all(self) -> None:
        direction = self._infer_navigation_direction(self._current_path, "All")
        started = False
        if direction != 0:
            started = self._file_list.begin_path_transition(direction)
        self._load_all()
        self._current_path = "All"
        self._update_path_input("All")
        self._nav_history = ["All"]
        self._history_index = 0
        self._clear_last_path()
        if started:
            self._file_list.finish_path_transition(direction)

    def _load_all(self) -> None:
        self._abort_rubber_selection()
        entries: List[Dict[str, Any]] = []
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            drives_bitmask = kernel32.GetLogicalDrives()
            for drive in range(26):
                if drives_bitmask & (1 << drive):
                    drive_name = chr(65 + drive) + ":"
                    drive_path = drive_name + "\\"
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
        self._file_model.set_files(entries)
        self._update_grid_size()
        self._update_file_count(len(entries))
        self._file_list.update()

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
            if last_path and os.path.exists(last_path):
                self._navigate_to_async(last_path)
                return True
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
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
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
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(8, 6, 8, 6)
        bottom_layout.setSpacing(6)

        self._file_count_label = QLabel("0 个条目")
        self._file_count_label.setStyleSheet("background: transparent; border: none; font-size: 11px;")
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
    def _collect_directory_entries(path: str) -> Optional[List[Dict[str, Any]]]:
        """纯 IO 收集目录条目（listdir + 逐文件 stat）。

        可在后台线程执行——不触碰任何 Qt/主线程状态。返回条目列表；
        目录不可读时返回 None（调用方执行与同步路径一致的清空处理）。
        """
        try:
            entries: List[Dict[str, Any]] = []
            for name in os.listdir(path):
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
        """同步加载目录（收集 + 应用），行为与旧实现逐字节等价。"""
        entries = self._collect_directory_entries(path)
        if entries is None:
            self._abort_rubber_selection()
            self._file_model.clear()
            self._current_path = ""
            self._update_file_count(0)
            self._file_list.update()
            return
        self._apply_directory_entries(path, entries)

    def _apply_directory_entries(self, path: str, entries: List[Dict[str, Any]]) -> None:
        """在主线程应用收集到的目录条目：过滤 + 排序 + 更新 model/路径/计数。"""
        self._abort_rubber_selection()
        if self._filter_pattern:
            entries = [e for e in entries if self._matches_filter(e["name"])]
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        self._apply_sort(entries)
        self._file_model.set_files(entries)
        self._update_grid_size()
        self._current_path = path
        self._update_path_input(path)
        self._update_file_count(len(entries))
        self._file_list.update()

    def _load_directory_async(self, path: str) -> None:
        """异步加载目录：后台线程收集条目，完成后回到主线程应用。

        仅用于启动首次加载等无交互动画的场景（避免与路径过渡动画竞态）。
        递增 token 保证快速连续导航时只应用最后一次请求的结果。
        """
        self._async_load_token += 1
        token = self._async_load_token

        def _worker() -> None:
            entries = self._collect_directory_entries(path)
            self._dir_entries_ready.emit(path, entries, token)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_dir_entries_ready(
        self, path: str, entries: Optional[List[Dict[str, Any]]], token: int
    ) -> None:
        """后台收集完成（主线程槽）：过期结果直接丢弃。"""
        if token != self._async_load_token:
            return
        if entries is None:
            self._abort_rubber_selection()
            self._file_model.clear()
            self._current_path = ""
            self._update_file_count(0)
            self._file_list.update()
            return
        self._apply_directory_entries(path, entries)

    def _navigate_to_async(self, path: str) -> None:
        """轻量异步导航（无过渡动画）：校验 + 异步加载 + 历史栈 + 保存路径。

        仅用于启动首次加载/恢复上次路径，避免大目录 listdir+stat
        阻塞主线程导致首屏卡顿。
        """
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        self._load_directory_async(path)
        if self._history_index >= 0 and self._history_index < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[:self._history_index + 1]
        self._nav_history.append(path)
        self._history_index = len(self._nav_history) - 1
        self._save_last_path(path)

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

    # ── 导航 ──────────────────────────────────────────────────────────────

    def _navigate_to(self, path: str) -> None:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        direction = self._infer_navigation_direction(self._current_path, path)
        started = False
        if direction != 0:
            started = self._file_list.begin_path_transition(direction)
        self._load_directory(path)
        if started:
            self._file_list.finish_path_transition(direction)
        if self._history_index >= 0 and self._history_index < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[:self._history_index + 1]
        self._nav_history.append(path)
        self._history_index = len(self._nav_history) - 1
        self._save_last_path(path)

    def _navigate_to_input_path(self) -> None:
        path = self._path_input.text().strip()
        if path:
            self._navigate_to(path)

    def _reload_directory(self) -> None:
        if self._current_path == "All":
            self._load_all()
        elif self._current_path:
            self._load_directory(self._current_path)

    def _load_directory_with_transition(self, path: str, direction: int) -> None:
        """带路径过渡动画的同步目录加载。

        Args:
            path: 要加载的目录绝对路径。
            direction: 过渡方向（>0 前进，<0 后退，0 不做动画）。

        复用 begin/finish 的 started 守卫：begin 返回 False（不可见/
        快照为空）时静默跳过 finish，仅执行同步加载；不等待图标/
        缩略图，不增加额外 IO。
        """
        started = False
        if direction != 0:
            started = self._file_list.begin_path_transition(direction)
        self._load_directory(path)
        if started:
            self._file_list.finish_path_transition(direction)

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
        """点击文件 = 预览（先清除框选选中态，预览只替换边框、背景保持原状态）。

        再次点击当前预览文件 = 取消预览；点击目录 = 进入目录。
        """
        # 左键点击任意卡片：清除框选选中态（"点击其他地方"即取消多选）
        self._clear_selector_selection()
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
        """右键直连文件池。

        - 右键点击"已选中的卡片"：将全部选中卡片追加加入文件池（add-only，
          已在池中的保持不变、绝不移出），加入后清除选中态；
        - 否则（未多选或点的是未选中卡片）：保留原有单卡片"添加/移除"切换。
        """
        index = self._file_list.indexAt(pos)
        if not index.isValid():
            return
        file_path: str = self._file_model.data(index, FilePathRole) or ""
        if not file_path:
            return
        # 命中已选中的卡片 → 批量添加全部选中项
        if file_path in self._file_model.get_selected_files():
            self._add_selected_to_pool()
            self._clear_selector_selection()
            return
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

    def _show_properties_dialog(self, file_info: Dict[str, Any]) -> None:
        """显示文件 / 文件夹属性对话框"""
        is_dir = file_info.get("is_dir", False)
        name = file_info.get("name", "")
        path = file_info.get("path", "")
        lines: list[str] = [
            f"名称: {name}",
            f"路径: {path}",
            f"类型: {'文件夹' if is_dir else '文件'}",
        ]
        if not is_dir:
            suffix = file_info.get("suffix", "")
            lines.append(f"后缀: .{suffix}" if suffix else "后缀: (无)")
            size = int(file_info.get("size", 0))
            if size >= 1024 * 1024:
                size_str = f"{size / (1024 * 1024):.2f} MB"
            elif size >= 1024:
                size_str = f"{size / 1024:.2f} KB"
            else:
                size_str = f"{size} B"
            lines.append(f"大小: {size_str}")
        modified = file_info.get("modified", "")
        if modified:
            lines.append(f"修改时间: {modified}")
        created = file_info.get("created", "")
        if created:
            lines.append(f"创建时间: {created}")

        QMessageBox.information(
            self, "属性", "\n".join(lines),
            QMessageBox.Ok,
        )

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
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        list_widget: Optional[QListWidget] = None
        if not favorites:
            empty_label = QLabel("暂无收藏，点击路径栏的 ★ 可添加当前路径")
            empty_label.setWordWrap(True)
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet(
                f"font-size: 14px; color: {tm.mid.name()}; background: transparent;"
            )
            empty_label.setFixedHeight(120)
            body_layout.addWidget(empty_label)
        else:
            list_widget = QListWidget()
            list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget.setSelectionMode(QAbstractItemView.NoSelection)
            list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
            list_widget.setMouseTracking(True)
            list_widget.setStyleSheet(f"""
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
            """)
            for fav in favorites:
                item = QListWidgetItem(f"{fav['name']}  -  {fav['path']}")
                item.setData(Qt.UserRole, fav["path"])
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
        path = item.data(Qt.UserRole)
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
        path = item.data(Qt.UserRole)
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
        path = item.data(Qt.UserRole)
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
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        tip = QLabel(label_text)
        tip.setStyleSheet(f"font-size: 14px; color: {tm.mid.name()}; background: transparent;")
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
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setStyleSheet(f"font-size: 14px; color: {tm.text.name()}; background: transparent;")
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
        """收集缩略图生成目标：优先选中文件，无选中时取当前目录全部文件。

        目录条目不参与收集；非媒体文件与已有缩略图的文件由
        ``ThumbnailController.start_generation`` 内部过滤。

        Returns:
            List[str]: 候选文件路径列表。
        """
        selected = self._file_model.get_selected_files()
        if selected:
            return selected
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
        body.setStyleSheet("background: transparent;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        tip = QLabel("输入文件名筛选正则（不区分大小写）。\n例如：\\.png$ 仅显示 png，项目 匹配名称含“项目”的文件。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"font-size: 14px; color: {tm.mid.name()}; background: transparent;")
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
            self._reload_directory()

        def on_clear() -> None:
            self._filter_pattern = ""
            self._update_filter_button_state()
            dialog.close_dialog(1)
            self._reload_directory()

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
        self._file_count_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 11px;"
        )

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

    def sync_pool_status(self, pool_paths: set[str]) -> None:
        """同步文件池中的路径集合到 delegate，刷新"已在池中"边框标记。

        同时缓存归一化路径集合到 _pool_paths——右键框选批量删除据此判定
        "仅处理已在存储池的卡片"。

        Args:
            pool_paths: 文件池中的文件路径集合。
        """
        self._pool_paths = {
            os.path.normcase(os.path.normpath(p)) for p in (pool_paths or set())
        }
        self._card_delegate.set_pool_files(pool_paths)
        self._file_list.viewport().update()

    # ── 预览状态管理 ────────────────────────────────────────────────────────

    def set_previewing_file(self, file_path: str) -> None:
        """设置文件选择器卡片的预览态：清除旧预览，设置新预览。

        预览态由 delegate 绘制为流光渐变边框（角锥渐变旋转动画），
        与文件池 `set_previewing_file` 行为一致。

        Args:
            file_path: 要预览的文件路径，若为空则仅清除旧预览。
        """
        import os

        # 清除旧预览
        if self._previewing_file_path:
            row = self._file_model.get_row(self._previewing_file_path)
            if row >= 0:
                idx = self._file_model.index(row, 0)
                self._file_model.setData(idx, False, IsPreviewingRole)
        self._previewing_file_path = ""

        # 设置新预览（路径规范化后匹配，与文件池保持一致）
        if file_path:
            normalized = os.path.normpath(file_path)
            row = self._file_model.get_row(normalized)
            if row >= 0:
                idx = self._file_model.index(row, 0)
                self._file_model.setData(idx, True, IsPreviewingRole)
                self._previewing_file_path = normalized

        self._file_list.viewport().update()

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

        # 高亮目标文件卡片（用 model 中实际存储的路径，规避大小写不一致）
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
        """计算卡片的基础宽度（基于日期文本宽度），与旧 file_selector.py 保持一致。"""
        dpi = 1.0
        base_min_width = int(50 * dpi)

        small_font = QFont(self.font())
        small_font.setPointSize(int(self.font().pointSize() * 0.85))
        small_font_metrics = QFontMetrics(small_font)

        date_text = "2024-12-31"
        date_text_width = small_font_metrics.horizontalAdvance(date_text)
        char_width = small_font_metrics.horizontalAdvance("W")
        horizontal_margins = int(4 * dpi) * 2
        border_width = int(1 * dpi) * 2

        required_width = date_text_width + char_width + horizontal_margins + border_width
        return max(required_width, base_min_width)

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
        cell_base_width = card_base_width + spacing
        max_cols = max(1, available_width // max(1, cell_base_width))

        # 先确定列数，再在该列数内部平滑放大卡片，避免 resize 时列数来回抖动
        cell_width = max(cell_base_width, available_width // max_cols)
        card_width = max(card_base_width, cell_width - spacing)

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

        # 网格指标（框选行定位用）：单元格间距 + 列数，行矩形由 _resolve_flow_origin
        # 从 Qt 实际 item 布局推导原点后再解析展开，不依赖 viewportMargins。
        self._grid_metrics = {
            "cell_w": grid_cell_width,
            "cell_h": grid_cell_height,
            "cols": max_cols,
        }

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

        # 网格指标（框选行定位用）：列表模式单列，行距 = 卡片高 + 间距
        self._grid_metrics = {
            "cell_w": file_list_width,
            "cell_h": card_height + gap,
            "cols": 1,
        }

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
        """切换排序模式并重新加载当前目录。"""
        self._sort_mode = mode
        self._sort_btn.setToolTip(f"排序: {self.SORT_MODE_NAMES[mode]}")
        if self._current_path:
            self._reload_directory()

    def _toggle_view_mode(self) -> None:
        self._abort_rubber_selection()
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
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
            _w.setStyleSheet(section_style)
            # 强制已显示控件重新套用样式（延迟构建场景下必须，否则边框/填充不重绘）
            _w.style().unpolish(_w)
            _w.style().polish(_w)
