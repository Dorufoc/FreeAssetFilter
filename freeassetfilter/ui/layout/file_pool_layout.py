"""
文件池布局 — 内容区（自适应拉伸）+ 底栏（固定高度）

基于 StyledInfoCard 列表，提供文件暂存池的完整交互：
- 卡片列表展示（StyledInfoCard 实例列表）
- 添加/删除/清空文件操作
- hover 悬浮操作按钮（重命名/删除）
- 自动备份保存/恢复
- 重命名对话框
- 主题切换适配
"""

from __future__ import annotations

import sys
from pathlib import Path

# 独立运行/无 GUI 测试环境的 sys.path 引导：styled 组件体系内部使用
# ``from theme/components import ...`` 短路径导入（与各预览器布局一致），
# 需保证 freeassetfilter/ui 在 sys.path 上。
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent)  # freeassetfilter/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)

import json
import os
import shutil
import threading
from typing import Callable, Optional

from PySide6.QtCore import (
    Qt, Signal, QTimer, QEvent, QRunnable, QThreadPool, QEventLoop,
    QPoint, QRect, QSize, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup,
    QSequentialAnimationGroup, QPauseAnimation, QAbstractAnimation,
)
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QApplication,
    QAbstractButton,
    QScrollArea,
    QFileDialog,
    QProgressDialog,
    QSpacerItem,
    QLayout,
    QLayoutItem,
    QWidgetItem,
)

from theme import tm
from components.styled_button import StyledButton
from components.styled_info_card import StyledInfoCard
from components.box_selection import BoxSelectionGesture
from components.file_card_delegate import (
    CARD_CONFIG,
    LIST_CONFIG,
    FileCardDelegate,
    calc_grid_base_width,
    calc_grid_cell,
)
from components.styled_scroll_area import StyledScrollBar, StyledScrollArea
from components.styled_dialog import create_input_dialog, ask_custom_dialog
from freeassetfilter.utils.path_utils import get_app_data_path
from freeassetfilter.core._paths import icons_dir
from freeassetfilter.services.staging_pool_service import StagingPoolService
from freeassetfilter.core.workers.staging_tasks import MD5CalculationTask
from freeassetfilter.core.native.bridges.faf_core_bridge import get_faf_core_bridge
from freeassetfilter.utils.animation_settings import is_animation_enabled
from freeassetfilter.utils.app_logger import debug, warning
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

# 导出复制单批 native 最大源数（进度/取消按批次粒度；与 Rust CHUNK_SIZE=32 对齐）。
_EXPORT_BATCH_SIZE = 32


def _show_custom_dialog(parent, title, message, buttons, variants=None, vertical=False, dialog_type="default"):
    """池内同步弹窗（委托公共同步助手 ``styled_dialog.ask_custom_dialog``）。

    文件池弹窗统一不显示右上角关闭按钮（所有场景都有"取消"按钮作为退出路径）。
    ``parent`` 参数保留以兼容全部调用点签名（StyledDialog 为顶层窗口，无需父级）。
    """
    return ask_custom_dialog(
        title=title,
        message=message,
        buttons=list(buttons),
        variants=list(variants) if variants else None,
        vertical=vertical,
        dialog_type=dialog_type,
        show_close=False,
    )


class _ExportCopyRunnable(QRunnable):
    """导出复制任务（QRunnable 投 ``QThreadPool.globalInstance()``）。

    一次性任务：后台线程平铺/分类复制文件，进度经 ``update_progress``
    信号回主线程，完成统计经 ``_export_finished`` 信号回传；线程池
    线程为 daemon 语义，进程退出不被阻塞。

    取消按**批次粒度**响应：``cancel_event`` 置位后，在下一个批次（≤
    ``_EXPORT_BATCH_SIZE`` 源）边界停止；单文件/单目录复制为原子操作，
    不属于批次间取消作用点。

    Args:
        owner: 所属 FilePoolLayout（复制方法与信号发射经由它）。
        files: 文件信息列表。
        target_dir: 目标目录。
        mode: 0=平铺, 1=分类。
        cancel_event: 可选取消标记（``threading.Event``）；置位后在批次
            边界提前终止（否则复制全部文件后正常结束）。
    """

    def __init__(
        self,
        owner: FilePoolLayout,
        files: list,
        target_dir: str,
        mode: int,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._owner = owner
        self._files = files
        self._target_dir = target_dir
        self._mode = mode
        self._cancel_event = cancel_event

    def _should_stop(self) -> bool:
        """批次间取消探测：``cancel_event`` 置位即应在下个批次边界停止。

        Returns:
            bool: True 表示需要终止复制。
        """
        return self._cancel_event is not None and self._cancel_event.is_set()

    def run(self) -> None:
        try:
            if self._mode == 0:
                s, f, e = self._owner.copy_files(
                    self._files, self._target_dir, should_stop=self._should_stop
                )
            else:
                s, f, e = self._owner.copy_files_categorized(
                    self._files, self._target_dir, should_stop=self._should_stop
                )
            self._owner._export_finished.emit(s, f, e)
        except Exception as ex:  # noqa: BLE001  # 导出任务异常兜底
            warning(f"导出线程异常: {ex}")


class _PoolCardsLayout(QLayout):
    """暂存池卡片布局：列表（单列全宽）/ 网格（流式多列）双模式。

    - ``list``：每个卡片占满内容宽度、垂直排列（与历史 QVBoxLayout 行为一致）；
    - ``grid``：卡片固定宽度（由池子按容器宽度与缩放统一计算），流式换行排布。

    兼容历史 QVBoxLayout 用法子集：``addWidget`` / ``insertWidget`` /
    ``removeWidget`` / ``indexOf`` / ``count`` / ``itemAt`` / ``takeAt`` /
    ``setSpacing`` / ``setContentsMargins`` / ``addStretch``（空操作，流式
    布局天然顶部对齐）。``heightForWidth`` 让外层按内容高度同步滚动范围。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._mode: str = "list"

    # ── 模式 ─────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """切换排布模式（"list" / "grid"），触发失效重排。"""
        mode = mode if mode in ("list", "grid") else "list"
        if mode != self._mode:
            self._mode = mode
            self.invalidate()

    @property
    def mode(self) -> str:
        """当前排布模式。"""
        return self._mode

    # ── QLayout 接口 ─────────────────────────────────────────────

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:  # noqa: N802
        if 0 <= index < len(self._items):
            self.invalidate()
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, max(0, width), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        width = self.geometry().width()
        if width <= 0:
            parent = self.parentWidget()
            width = parent.width() if parent is not None else 100
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self):  # noqa: N802
        width = self.geometry().width()
        if width <= 0:
            parent = self.parentWidget()
            width = parent.width() if parent is not None else 100
        return QSize(0, self.heightForWidth(width))

    def addStretch(self, stretch: int = 0) -> None:  # noqa: N802
        """兼容历史 QVBoxLayout 调用：流式布局天然顶部对齐，无需弹簧。"""

    def insertWidget(self, index: int, widget: QWidget) -> None:  # noqa: N802
        """按索引插入控件（对齐历史 QVBoxLayout.insertWidget 语义）。"""
        try:
            widget.setParent(self.parentWidget())
        except RuntimeError:
            return
        index = max(0, min(int(index), len(self._items)))
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    # ── 内部排布 ─────────────────────────────────────────────────

    @staticmethod
    def _item_metrics(item: QLayoutItem) -> tuple[int, int]:
        """取子项排布尺寸：优先使用控件显式约束（定高 / 固定宽）。"""
        hint = item.sizeHint()
        width = max(0, hint.width())
        height = max(0, hint.height())
        widget = item.widget()
        if widget is not None:
            max_h = widget.maximumHeight()
            if 0 < max_h < 16777215:
                height = max_h
            min_w = widget.minimumWidth()
            if min_w > 0:
                width = max(width, min_w)
        return width, height

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        """按模式排布子项并返回所需总高度（test_only 时不写几何）。"""
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        spacing = max(0, self.spacing())
        x, y = effective.x(), effective.y()
        line_height = 0
        placed = False

        for item in self._items:
            # 注意：不能依赖 item.isEmpty()/控件 isHidden() 跳过——新建控件
            # 加入布局后要到下一轮事件循环才会被 Qt 显示（QWidgetItem.isEmpty
            # 在隐藏时为 True），跳过会让首个同步周期的高度/位置失真。
            if item.widget() is None:
                continue
            item_width, item_height = self._item_metrics(item)
            if self._mode == "grid":
                if x > effective.x() and x + item_width > effective.right() + 1:
                    x = effective.x()
                    y += line_height + spacing
                    line_height = 0
                if not test_only:
                    item.setGeometry(QRect(x, y, item_width, item_height))
                x += item_width + spacing
                line_height = max(line_height, item_height)
            else:
                if not test_only:
                    item.setGeometry(
                        QRect(effective.x(), y, max(effective.width(), 0), item_height)
                    )
                y += item_height + spacing
                line_height = item_height
            placed = True

        if self._mode == "grid":
            total = (y + line_height) if placed else effective.y()
        else:
            total = (y - spacing) if placed else effective.y()
        return max(0, total - rect.y() + margins.bottom())


class FilePoolLayout(QWidget):
    """文件池布局（中间栏）"""

    # ── 对外信号 ───────────────────────────────────────────────────────────

    item_left_clicked = Signal(dict)       # 左键点击某个池条目时发出
    item_right_clicked = Signal(dict)      # 右键点击某个池条目时发出
    preview_cancel_requested = Signal()    # 需要取消预览时发出
    update_progress = Signal(int)          # 进度更新信号（导出等操作）
    _export_finished = Signal(int, int, object)  # 导出完成信号（成功数, 失败数, 错误列表）
    pool_changed = Signal()                # 池内容变更（添加/移除/清空），通知选择器刷新状态
    _folder_size_ready = Signal(str, object)  # 文件夹大小就绪（路径, 大小），worker 线程经此信号回主线程更新 UI

    def __init__(self, parent=None):
        super().__init__(parent)
        # 图标目录（_build_bottom_bar 与 add_file 都需要使用，必须在 _build_bottom_bar 之前初始化）
        self._icons_dir = icons_dir()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("FilePoolContent")
        layout.addWidget(self._content_area, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("FilePoolBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)

        # ── 运行状态 ────────────────────────────────────────────────────
        self.items: list[dict] = []
        self.previewing_file_path: Optional[str] = None
        self._card_widgets: dict[str, StyledInfoCard] = {}  # path → card
        self._removing_paths: set[str] = set()  # 正在播放移除动画的路径

        # ── InfoCard 创建/移除动画 ──────────────────────────────────────
        self._card_motion_duration_ms = 100
        self._card_motion_min_slide = 28
        self._card_motion_max_slide = 96
        self._card_motion_slide_ratio = 0.18
        self._card_motion_shrink_scale = 0.8  # 网格移除：原地"向后缩小"目标缩放
        self._active_card_animations: dict[str, dict] = {}  # path → {"group": ..., "on_finished": ..., "kind": ...}
        self._entry_spacers: dict[str, QSpacerItem] = {}  # path → 创建动画期间占位 spacer
        self._active_remove_motion_groups: dict[str, QParallelAnimationGroup] = {}  # path → 占位控件折叠动画组（驱动下方卡片整体上移）
        self._grid_fill_group: Optional[QParallelAnimationGroup] = None  # 网格移除补位动画组（单一活动）
        # 网格补位动画（级联柔和）：相对退出开始的起步延迟、单卡时长、
        # 逐格错峰步长与封顶（距空位越远延迟越大，形成向外扩散的波浪收拢）
        self._card_fill_delay_ms = 50
        self._card_fill_duration_ms = 220
        self._card_fill_stagger_ms = 12
        self._card_fill_stagger_max_ms = 48

        # ── Ctrl+滚轮 卡片缩放 ──────────────────────────────────────────
        self._card_scale_min = 0.7
        self._card_scale_max = 1.6
        self._card_scale = 1.0
        # 卡片 base size_overrides（_card_scale=1.0 时的设计值，作为缩放基准）。
        # 直接派生自文件选择器 list 模式 LIST_CONFIG（单一事实来源），
        # 保证暂存池卡片与文件选择器横向卡片的高度、图标、文字排列完全一致。
        self._card_base_overrides: dict = dict(LIST_CONFIG)
        # 视图模式：list（经典列表）/ grid（New 布局网格，竖向瓦片 + 自动列数）
        self._view_mode: str = "list"
        # 各视图模式各自记忆缩放（网格默认最小值，列表默认 1.0）
        self._list_scale: float = 1.0
        self._grid_scale: float = self._card_scale_min
        # 网格瓦片的缩放基准：与文件选择器网格卡同一规格（CARD_CONFIG，
        # 单一事实来源）。text_width=0 使竖向最小宽度 = padding*2 + media，
        # 与实际卡宽无关（列宽由 calc_grid_cell 统一计算并 set_fixed_width）。
        self._grid_base_overrides: dict = dict(CARD_CONFIG, text_width=0)

        # ── ScrollArea + StyledInfoCard 列表 ────────────────────────────
        # 与 FileSelectorLayout 一致：隐藏 QScrollArea 自带滚动条，
        # 改用独立的 StyledScrollBar 作为浮动覆盖层（自绘圆角条形 + hover 动画）。
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        # 内部子布局必须保持透明，让基础底层（_content_area）的半透明 section fill 单一透出，
        # 防止多层半透明背景叠加。主题切换由 _apply_pool_theme 再次刷新。
        register_widget_qss(self._scroll_area,(
            "background-color: transparent; border: none;"
        ))
        self._scroll_area.viewport().installEventFilter(self)

        self._card_container = QWidget()
        self._card_container.setObjectName("FilePoolCardContainer")
        register_widget_qss(self._card_container,("background-color: transparent;"))
        self._card_layout = _PoolCardsLayout(self._card_container)
        # 防递归守卫：水平边距动态计算时避免 setContentsMargins 触发的布局重入
        self._updating_pool_margins = False
        # 初始左右边距用「无滚动条居中」默认值（10*dpi），后续由
        # _update_pool_card_margins 根据滚动条状态动态覆盖；
        # 顶部固定 6（与文件选择器网格/列表模式一致），
        # 底部统一为 10*dpi（与文件选择器网格模式基准一致）
        _init_pad = int(10 * 1.0)
        self._card_layout.setContentsMargins(_init_pad, 6, _init_pad, _init_pad)
        # 卡片间距与文件选择器 list 模式一致（其卡片间隙基准值为 5，
        # 且随 _card_scale 缩放：gap = int(5 * scale)），此处同样按当前缩放计算。
        self._card_layout.setSpacing(int(5 * self._card_scale))
        self._scroll_area.setWidget(self._card_container)

        content_layout = QVBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._scroll_area)

        # 浮动覆盖层滚动条（贴 _content_area 右侧，覆盖在 _scroll_area 之上）
        self._pool_scrollbar = StyledScrollBar(self._content_area)
        self._pool_scrollbar.setFixedWidth(max(6, int(8 * 1.0)))
        self._pool_scrollbar.raise_()

        # 同步浮动滚动条与 _scroll_area 垂直滚动条的范围/值
        area_vbar = self._scroll_area.verticalScrollBar()
        self._pool_scrollbar.setRange(area_vbar.minimum(), area_vbar.maximum())
        self._pool_scrollbar.setSingleStep(area_vbar.singleStep())
        self._pool_scrollbar.setPageStep(area_vbar.pageStep())
        area_vbar.rangeChanged.connect(self._sync_pool_scrollbar_range)
        self._pool_scrollbar.valueChanged.connect(area_vbar.setValue)
        area_vbar.valueChanged.connect(self._pool_scrollbar.setValue)

        # 空池引导提示：池内无卡片时居中显示（初始即为空池状态，直接可见）。
        # 作为视口子控件悬浮于滚动区之上、不参与布局：鼠标事件透传（不影响
        # 框选/右键语义），两种布局模式（经典列表 / New 网格）共用同一提示；
        # 可见性与几何分别由 _update_empty_hint_visibility /
        # _update_empty_hint_geometry 统一维护。
        self._empty_hint = QLabel("右键选择区卡片以添加文件", self._scroll_area.viewport())
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._apply_empty_hint_style()

        # 滚动时刷新所有卡片的 overlay（修复 StyledInfoCard 的 QGraphicsEffect
        # 缓存导致 hover overlay 在滚动时不同步跟随）。使用 singleShot 节流，
        # 避免范围变化触发的连续 valueChanged 导致所有卡片反复重绘。
        self._pending_scroll_overlay_update = False
        area_vbar.valueChanged.connect(self._on_pool_scrolled)

        # 应用平滑滚动 + 边界回弹 + 触摸手势（与 FileSelectorLayout 一致）
        StyledScrollArea.apply_to(self._scroll_area, enable_mouse_drag=False)

        # 内容区尺寸变化时重新定位浮动滚动条
        self._content_area.installEventFilter(self)
        # 卡片容器纳入事件过滤：Ctrl+滚轮在容器任意位置缩放卡片
        self._card_container.installEventFilter(self)

        # ── 框选多选（左键按住拖拽 = 橡皮筋框选）────────────────────────
        # 框内卡片进入"框选选中态"（虚线 accent 边框 + 半透明填充，不触发预览）；
        # 右键点在已选中卡片上 = 批量移出储存池；单击卡片/空白清除框选。
        self._box_selected_paths: set[str] = set()
        # 本次左键手势起拖时按压的卡片路径（用于手势结束后复位按压缩放）
        self._box_press_card_path: Optional[str] = None
        self._box_gesture = BoxSelectionGesture(
            self,
            overlay_parent=self._scroll_area.viewport(),
            scrollbar_getter=lambda: self._scroll_area.verticalScrollBar(),
            hit_test=self._pool_box_hit_test,
            on_hits=self._apply_pool_box_hits,
        )
        self._box_gesture.finished.connect(self._on_box_gesture_finished)

        # ── 备份系统 ────────────────────────────────────────────────────
        self.backup_file = os.path.join(
            get_app_data_path(), StagingPoolService.BACKUP_FILE_NAME
        )
        self._suspend_backup_save = False
        self._pending_backup_last_path = "All"
        self._backup_save_delay_ms = 1500
        self._backup_save_timer = QTimer(self)
        self._backup_save_timer.setSingleShot(True)
        self._backup_save_timer.timeout.connect(self._flush_pending_backup_save)

        # ── 允许外部拖放 ──────────────────────────────────────────────
        self.setAcceptDrops(True)

        # ── 主题切换 ────────────────────────────────────────────────────
        tm.theme_changed.connect(self._on_theme_changed)
        # 强调色单独变化不发 theme_changed，仅发 colors_updated：卡片图标
        # 与拖放虚线边框（含 accent）同样需要即时刷新。
        tm.colors_updated.connect(self._on_theme_changed)
        # 文件夹大小计算经信号回主线程，避免 worker 线程直接触碰 QWidget。
        self._folder_size_ready.connect(self._on_folder_size_ready_gui)

        # 最小高度：默认网格缩放下一行卡片 + 底栏（主布局据此推导底行下限）
        self.setMinimumHeight(self.minimum_row_height())

    # ═════════════════════════════════════════════════════════════════════
    #  底栏（骨架保留部分）
    # ═════════════════════════════════════════════════════════════════════

    def _build_bottom_bar(self) -> None:
        """构建底栏：导入/导出数据 + 导出文件 + 删除"""
        icons_dir = self._icons_dir
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(6)

        # 左侧文字标签（纵向排列）
        info_container = QWidget()
        info_container.setFixedHeight(32)
        register_widget_qss(info_container,("background: transparent; border: none;"))
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)

        self._count_label = QLabel("0个条目")
        register_widget_qss(self._count_label,(
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px; font-weight: 600;"
        ))
        info_layout.addWidget(self._count_label)

        self._size_label = QLabel("0.00MB")
        register_widget_qss(self._size_label,(
            "background: transparent; border: none;"
            f"color: {tm.qss_color(tm.text_secondary)}; font-size: 10px;"
        ))
        info_layout.addWidget(self._size_label)

        bottom_layout.addWidget(info_container)

        # 竖分割线
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.VLine)
        self._separator.setFrameShadow(QFrame.Sunken)
        self._update_separator_color()
        self._separator.setFixedWidth(1)
        self._separator.setFixedHeight(20)
        bottom_layout.addWidget(self._separator)

        # 将按钮区域推到右侧
        bottom_layout.addStretch(1)

        # 图标按钮 — trash.svg
        trash_icon = str(icons_dir / "trash.svg")
        self._trash_btn = StyledButton("", variant="ghost", size="sm", icon=trash_icon)
        self._trash_btn.setFixedSize(32, 32)
        self._trash_btn.clicked.connect(self.clear_all)
        bottom_layout.addWidget(self._trash_btn)

        # 次要按钮 — 导入/导出数据
        self._import_export_btn = StyledButton(
            "导入/导出数据", variant="secondary", size="sm"
        )
        self._import_export_btn.clicked.connect(self.show_import_export_dialog)
        bottom_layout.addWidget(self._import_export_btn)

        # 强调按钮 — 导出文件
        self._export_btn = StyledButton(
            "导出文件", variant="primary", size="sm"
        )
        self._export_btn.clicked.connect(self.export_selected_files)
        bottom_layout.addWidget(self._export_btn)

    def minimum_row_height(self) -> int:
        """默认网格缩放下「一行卡片（含其下方底栏）」的最小高度。

        口径：卡片容器上边距 + 一张默认缩放（``_card_scale_min``，0.7）网格
        卡片高 + 下边距 + 根布局间距 + 底栏高度。主窗口据此推导底行下限
        （workspace 底行最小高 = max(本值, 信息面板最小高)，见
        ``MainWindow._apply_window_minimums``）；本值同时作为储存池自身的
        最小高度——高度连一行卡片都放不下时界面会显得破碎。

        Returns:
            int: 一行卡片 + 底栏的最小高度（px，随字体度量/DPI 自动换算）。
        """
        _, card_h = FileCardDelegate._calc_card_size(CARD_CONFIG, self._card_scale_min)
        margins = self._card_layout.contentsMargins()
        content_h = margins.top() + int(card_h) + margins.bottom()
        root = self.layout()
        spacing = int(root.spacing()) if root is not None else 10
        return content_h + max(0, spacing) + int(self._bottom_bar.maximumHeight())

    def set_section_styles(
        self,
        fill_color: str,
        border_color: str,
        bar_fill_color: Optional[str] = None,
    ) -> None:
        """应用面板样式到内容区、底栏（主题切换时由 MainWindow 调用）。

        Args:
            fill_color: 内容区填充色。
            border_color: 边框色。
            bar_fill_color: 底栏填充色；``None`` 时与内容区同色（深色模式口径）。
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
        # 拖放反馈（蓝色虚线边框）以动态属性选择器并入内容区的同一片段：
        # register_widget_qss 每个控件仅保存一个片段，独立注册会在主题
        # 重注册时被覆盖（审查 3.1#22）。
        # 面板声明必须包进显式 ``* { ... }`` 规则块：同一片段里「裸声明 +
        # 后续选择器规则」的粘连形态会被 scope_qss 误判（rgba(...) 里的逗号
        # 还会把选择器切碎）生成畸形规则，而 Qt 解析器遇到畸形规则会丢弃
        # 整张样式表的后续内容（储存池丢样式回归，见 scope_qss 拆分逻辑）。
        drag_border = tm.qss_color(tm.accent)
        content_style = (
            "* {" + section_style + "}\n"
            f'QFrame[dragActive="true"] {{ border: 2px dashed {drag_border}; }}'
        )
        register_widget_qss(self._content_area, content_style)
        register_widget_qss(self._bottom_bar, bar_style)
        for _w in (self._content_area, self._bottom_bar):
            # 强制已显示控件重新套用样式（延迟构建场景下必须，否则边框/填充不重绘）
            _w.style().unpolish(_w)
            _w.style().polish(_w)

    def _update_separator_color(self) -> None:
        """刷新竖分割线颜色"""
        mid = tm.mid
        register_widget_qss(self._separator,(
            "background: transparent; border: none;"
            f"border-left: 1px solid rgba({mid.red()},{mid.green()},{mid.blue()},0.25);"
        ))

    def _on_theme_changed(self, theme: str) -> None:
        """主题/配色切换时刷新标签文字颜色、池视图主题与卡片图标。"""
        self._update_separator_color()
        register_widget_qss(self._count_label,(
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px; font-weight: 600;"
        ))
        register_widget_qss(self._size_label,(
            "background: transparent; border: none;"
            f"color: {tm.qss_color(tm.text_secondary)}; font-size: 10px;"
        ))
        self._apply_empty_hint_style()
        self._apply_pool_theme()
        self._refresh_card_icons()

    def _refresh_card_icons(self) -> None:
        """按当前主题重取所有卡片图标并回填。

        卡片图标在加入时经 ``set_media_pixmap`` 存入（含主题色替换的
        类型图标/缩略图），不会自动跟随主题；明暗或强调色变化后必须
        重取回填，否则一直显示旧配色（历史缺陷：储存池卡片图标换主题
        后不刷新，须移除重加才更新）。
        """
        if not self._card_widgets:
            return
        info_by_path = {}
        for file_info in self.items:
            path = os.path.normpath(file_info.get("path", ""))
            if path:
                info_by_path[path] = file_info
        for path, card in self._card_widgets.items():
            if path in self._removing_paths:
                continue
            file_info = info_by_path.get(path)
            if not file_info:
                continue
            try:
                icon_pixmap = self._get_file_icon_pixmap(file_info)
                if icon_pixmap and not icon_pixmap.isNull():
                    card.set_media_pixmap(icon_pixmap)
            except (RuntimeError, AttributeError) as exc:
                # 卡片已销毁（移除动画与主题刷新交错）：跳过该卡片。
                debug(f"刷新储存池卡片图标失败（已销毁）：{exc}")

    def _apply_empty_hint_style(self) -> None:
        """刷新空池引导提示样式（次级提示文字色，随主题/强调色变化）。"""
        register_widget_qss(self._empty_hint,(
            "background: transparent; border: none;"
            f"color: {tm.qss_color(tm.text_hint)}; font-size: 13px;"
        ))

    def _apply_pool_theme(self) -> None:
        """为卡片容器和 scroll area 应用当前主题样式（保持透明，避免多层半透明叠加）"""
        # 内部子布局（_scroll_area、_card_container）必须保持透明，
        # 让基础底层（_content_area / _bottom_bar）的半透明 section fill 透出，
        # 防止多层半透明背景叠加。
        register_widget_qss(self._scroll_area,(
            "background-color: transparent; border: none;"
        ))
        register_widget_qss(self._card_container,(
            "background-color: transparent;"
        ))
        # 刷新所有卡片的颜色（A4 批量纪律：N 张卡片逐个 update 合并为容器一次重绘）。
        self._card_container.setUpdatesEnabled(False)
        try:
            for card in self._card_widgets.values():
                card.update()
        finally:
            self._card_container.setUpdatesEnabled(True)
        self._card_container.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Ctrl+滚轮 卡片缩放（匹配文件选择器行为）
    # ═════════════════════════════════════════════════════════════════════

    def eventFilter(self, obj, event):
        if obj is self._content_area and event.type() == QEvent.Resize:
            # 内容区尺寸变化时重新定位浮动滚动条
            self._update_pool_scrollbar_geometry()
            # 宽度/高度变化后同步重算卡片左右边距
            self._update_pool_card_margins()
            # 边距变化影响网格可用宽度：重算列宽/容器高度
            self._sync_pool_card_geometry()
        if obj is self._scroll_area.viewport() and event.type() == QEvent.Resize:
            # 视口宽度变化：网格重算列数/列宽，两种模式同步容器高度
            self._sync_pool_card_geometry()
            # 空池提示随视口尺寸居中铺满
            self._update_empty_hint_geometry()
        # 池视口 / 卡片容器 / 卡片及其子控件：滚轮缩放 + 左键框选 + 右键批量移除
        is_pool_target = (
            obj is self._scroll_area.viewport()
            or obj is self._card_container
            or (
                isinstance(obj, QWidget)
                and self._card_container.isAncestorOf(obj)
            )
        )
        if is_pool_target:
            if event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ControlModifier:
                    self._handle_card_zoom(event)
                    return True
            elif event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton and not isinstance(obj, QAbstractButton):
                    # 只记录起点，不消费按下事件（保留卡片单击/按钮语义）；
                    # 按钮上的按下不参与框选，避免按钮按压状态被拖拽打断。
                    pos = self._pool_viewport_pos(event, obj)
                    self._box_press_card_path = self._pool_card_path_at(pos)
                    self._box_gesture.begin(pos)
            elif event.type() == QEvent.MouseMove:
                if self._box_gesture.started:
                    pressed = bool(event.buttons() & Qt.LeftButton)
                    if self._box_gesture.update(self._pool_viewport_pos(event, obj), pressed):
                        return True
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton and self._box_gesture.started:
                    pos = self._pool_viewport_pos(event, obj)
                    if self._box_gesture.finish(pos):
                        # 拖拽框选结束：消费释放事件，阻止卡片 clicked → 预览
                        # （按压卡片缩放由 _on_box_gesture_finished 复位）
                        return True
                    # 未拖拽的单击：空白区清除框选；卡片单击由 clicked 处理
                    self._box_press_card_path = None
                    if self._pool_card_path_at(pos) is None:
                        self.clear_box_selection()
                elif event.button() == Qt.RightButton:
                    return self._handle_pool_right_release(event, obj)
        return super().eventFilter(obj, event)

    def _pool_viewport_pos(self, event, obj) -> QPoint:
        """将鼠标事件位置统一换算为池视口坐标。

        Args:
            event: 鼠标事件（须提供 position()）。
            obj: 事件目标对象（视口、卡片容器、卡片或卡片子控件）。

        Returns:
            池视口坐标系下的点。
        """
        pos: QPoint = event.position().toPoint()
        viewport = self._scroll_area.viewport()
        if obj is viewport or obj is None or viewport is None:
            return pos
        if isinstance(obj, QWidget):
            try:
                return obj.mapTo(viewport, pos)
            except RuntimeError:
                return pos
        return pos

    def _pool_card_path_at(self, pos: QPoint) -> Optional[str]:
        """命中判定：返回池视口坐标下包含该点的卡片路径。

        Args:
            pos: 池视口坐标。

        Returns:
            命中的卡片路径；空白区返回 None。
        """
        viewport = self._scroll_area.viewport()
        if viewport is None:
            return None
        for path, card in self._card_widgets.items():
            if path in self._removing_paths:
                continue
            try:
                if card.isHidden():
                    continue
                top_left = card.mapTo(viewport, QPoint(0, 0))
                card_rect = QRect(top_left, card.size())
            except RuntimeError:
                continue
            if card_rect.contains(pos):
                return path
        return None

    def _pool_box_hit_test(self, rect: QRect) -> set[str]:
        """计算与选框矩形相交的池卡片路径集合（视觉重叠即命中）。

        Args:
            rect: 选框矩形（池视口坐标）。

        Returns:
            命中卡片路径集合；移除动画中的卡片不参与命中。
        """
        viewport = self._scroll_area.viewport()
        hits: set[str] = set()
        if viewport is None:
            return hits
        for path, card in self._card_widgets.items():
            if path in self._removing_paths:
                continue
            try:
                if card.isHidden():
                    continue
                top_left = card.mapTo(viewport, QPoint(0, 0))
                card_rect = QRect(top_left, card.size())
            except RuntimeError:
                continue
            if rect.intersects(card_rect):
                hits.add(path)
        return hits

    def _apply_pool_box_hits(self, hits: set[str]) -> None:
        """把框选命中路径集合应用到卡片选中态（替换语义）。

        Args:
            hits: 命中路径集合；未命中的已选卡片自动取消选中。
        """
        current = self._box_selected_paths
        to_select = hits - current
        to_deselect = current - hits
        self._box_selected_paths = set(hits)
        for path in to_select:
            card = self._card_widgets.get(path)
            if card is None:
                continue
            try:
                card.set_selected(True)
            except RuntimeError:
                continue
        for path in to_deselect:
            card = self._card_widgets.get(path)
            if card is None:
                continue
            try:
                card.set_selected(False)
            except RuntimeError:
                continue

    def clear_box_selection(self) -> None:
        """清空池内所有卡片的框选选中态（幂等）。"""
        if not self._box_selected_paths:
            return
        for path in list(self._box_selected_paths):
            card = self._card_widgets.get(path)
            if card is None:
                continue
            try:
                card.set_selected(False)
            except RuntimeError:
                continue
        self._box_selected_paths.clear()

    def _handle_pool_right_release(self, event, obj) -> bool:
        """右键释放：已选中卡片 = 批量移出储存池；其余情况清除框选后放行。

        Args:
            event: 鼠标释放事件。
            obj: 事件目标对象。

        Returns:
            True 表示已消费（批量移除，阻止卡片 right_clicked）；
            False 表示放行给现有单卡右键/单击语义。
        """
        pos = self._pool_viewport_pos(event, obj)
        path = self._pool_card_path_at(pos)
        if path is None:
            # 空白区右键：清除框选，无其他动作
            self.clear_box_selection()
            return False
        if path in self._box_selected_paths:
            # 命中框选中的卡片：批量移出储存池（快照后逐个移除，防字典变动）
            paths = [
                p for p in self._box_selected_paths
                if p in self._card_widgets and p not in self._removing_paths
            ]
            self.clear_box_selection()
            for p in paths:
                self.remove_file(p)
            return True
        # 未选中卡片：清除框选 + 放行现有单卡右键移除
        self.clear_box_selection()
        return False

    def _on_box_gesture_finished(self, was_active: bool) -> None:
        """手势结束（松开/守卫兜底/应用失活共用）：复位按压卡片的缩放反馈。

        Args:
            was_active: 本次手势是否曾进入框选态。
        """
        path = self._box_press_card_path
        self._box_press_card_path = None
        if not was_active or not path:
            return
        card = self._card_widgets.get(path)
        if card is None:
            return
        try:
            card.reset_press()
        except RuntimeError:
            return

    def _install_card_filters(self, card: QWidget) -> None:
        """给卡片及其全部子控件安装事件过滤器（卡片任意位置可起拖框选）。

        Args:
            card: 新加入池的 StyledInfoCard。
        """
        targets = [card]
        try:
            targets.extend(card.findChildren(QWidget))
        except RuntimeError:
            return
        for widget in targets:
            try:
                widget.installEventFilter(self)
            except RuntimeError:
                continue

    def _sync_pool_scrollbar_range(self, min_val: int, max_val: int) -> None:
        """当 _scroll_area 内部滚动范围变化时，同步浮动 StyledScrollBar 的范围。"""
        self._pool_scrollbar.setRange(min_val, max_val)
        area_vbar = self._scroll_area.verticalScrollBar()
        self._pool_scrollbar.setSingleStep(area_vbar.singleStep())
        self._pool_scrollbar.setPageStep(area_vbar.pageStep())
        # 范围变化时也重定位（隐藏/显示逻辑通过 maximum==0 处理）
        self._update_pool_scrollbar_geometry()
        # 滚动范围变化后刷新卡片边距（恒定对称值，幂等防御性刷新）
        QTimer.singleShot(0, self._update_pool_card_margins)

    def _update_pool_scrollbar_geometry(self) -> None:
        """将浮动滚动条定位到内层 _scroll_area 的右侧边缘（与 FileSelectorLayout 行为一致）。

        参照系用内层 _scroll_area 而非外层 _content_area：_scroll_area 以 0 边距填充
        _content_area 的 contentsRect，天然被 _content_area 的 1px QSS 边框内缩，等价于
        FileSelectorLayout 中滚动条参照 _file_list.width()。这样滚动条落在边框内侧，
        与文件选择器右侧间距逐像素一致，而不会压住 1px 边框与圆角。
        """
        if not hasattr(self, "_pool_scrollbar") or not hasattr(self, "_scroll_area"):
            return
        if self._scroll_area.width() <= 0 or self._scroll_area.height() <= 0:
            return
        edge_padding = int(10 * 1.0)
        scrollbar_w = self._pool_scrollbar.width()
        scrollbar_x = self._scroll_area.width() - scrollbar_w
        scrollbar_y = edge_padding
        scrollbar_h = max(0, self._scroll_area.height() - 2 * edge_padding)
        self._pool_scrollbar.setGeometry(scrollbar_x, scrollbar_y, scrollbar_w, scrollbar_h)
        self._pool_scrollbar.raise_()

    def _update_pool_card_margins(self) -> None:
        """恒定对称边距，完全复刻 FileSelectorLayout._update_list_grid。

        滚动条是完全浮动的覆盖层，不参与布局、不改变卡片边缘位置：
        - 左右边距恒定 10*dpi，与滚动条状态无关，卡片永不因滚动条出现/消失而左右移动；
        - 右侧 10*dpi 预留空间内浮着 8*dpi 宽的滚动条（距卡片 2*dpi），
          与文件选择器 list 模式的右侧间距逐像素一致。
        仅当值变化时才写入，避免无谓布局刷新。
        """
        if self._updating_pool_margins:
            return
        self._updating_pool_margins = True
        try:
            dpi = 1.0
            scrollbar_w = self._pool_scrollbar.width()
            side_margin = int(10 * dpi)
            left = side_margin
            right = max(side_margin, scrollbar_w + int(2 * dpi))
            m = self._card_layout.contentsMargins()
            if (m.left(), m.right()) != (left, right):
                self._card_layout.setContentsMargins(left, m.top(), right, m.bottom())
        finally:
            self._updating_pool_margins = False


    def _update_empty_hint_geometry(self) -> None:
        """让空池提示铺满滚动视口并居中（视口尺寸变化 / 显示时调用）。

        提示为视口子控件，几何以视口矩形为基准；``AlignCenter`` 保证文字
        始终居中。可见时才置顶，避免遮挡框选覆层（覆层激活时自行 raise）。
        """
        if not hasattr(self, "_empty_hint") or not hasattr(self, "_scroll_area"):
            return
        viewport = self._scroll_area.viewport()
        self._empty_hint.setGeometry(0, 0, viewport.width(), viewport.height())
        if self._empty_hint.isVisible():
            self._empty_hint.raise_()

    def _update_empty_hint_visibility(self) -> None:
        """按池内卡片数量同步空池提示显隐（空池显示 / 有卡片隐藏）。"""
        if not hasattr(self, "_empty_hint"):
            return
        show_hint = not self._card_widgets
        if self._empty_hint.isVisible() != show_hint:
            self._empty_hint.setVisible(show_hint)
        if show_hint:
            self._update_empty_hint_geometry()

    def _on_pool_scrolled(self, _value: int) -> None:
        """滚动时让所有卡片的 overlay 重新绘制（修复 QGraphicsEffect 缓存不同步）。"""
        if self._pending_scroll_overlay_update:
            return
        self._pending_scroll_overlay_update = True

        def _update() -> None:
            self._pending_scroll_overlay_update = False
            for card in self._card_widgets.values():
                card.update_overlay()

        QTimer.singleShot(0, _update)

    def showEvent(self, event) -> None:
        """首次显示时定位浮动滚动条。"""
        super().showEvent(event)
        self._update_pool_scrollbar_geometry()
        self._update_pool_card_margins()
        self._sync_pool_card_geometry()
        self._update_empty_hint_visibility()

    def _handle_card_zoom(self, event) -> None:
        """Ctrl+滚轮：缩放所有 StyledInfoCard 卡片尺寸（两种视图各自记忆）。"""
        delta = event.angleDelta().y()
        if delta > 0:
            new_scale = min(self._card_scale_max, self._card_scale + 0.1)
        elif delta < 0:
            new_scale = max(self._card_scale_min, self._card_scale - 0.1)
        else:
            return
        self._card_scale = new_scale
        if self._view_mode == "grid":
            self._grid_scale = new_scale
            # 统一规格基准（CARD_CONFIG）；列宽由 _sync_pool_card_geometry 重算
            for card in self._card_widgets.values():
                card.set_scale(new_scale, base_overrides=self._grid_base_overrides)
        else:
            self._list_scale = new_scale
            # 传入 _card_base_overrides 作为缩放基准（派生自选择器 LIST_CONFIG），
            # 保证已存在卡片缩放后仍与新加入卡片尺寸一致。
            for card in self._card_widgets.values():
                card.set_scale(new_scale, base_overrides=self._card_base_overrides)
        # 卡片间距：列表随缩放（与选择器 list 模式一致）；网格固定 4px（与选择器网格一致）
        self._card_layout.setSpacing(4 if self._view_mode == "grid" else int(5 * new_scale))
        self._sync_pool_card_geometry()

    # ── 视图模式（列表 / 网格）与几何同步 ─────────────────────────────

    def set_view_mode(self, mode: str) -> None:
        """切换卡片视图：``list``（经典列表）/ ``grid``（New 布局网格）。

        - 列表：横向信息卡、单列全宽（历史行为，含路径副标题与悬浮重命名/删除），
          缩放记忆 ``_list_scale``；
        - 网格：竖向平铺瓦片（与文件选择器网格卡同一规格：居中双行文件名、
          无副标题、无悬浮操作），自动列数流式排布，缩放记忆 ``_grid_scale``
          （默认最小值 0.7，Ctrl+滚轮仍可缩放）；
        - 现有卡片原地迁移（不重建），切换后立即重排。
        """
        mode = mode if mode in ("list", "grid") else "list"
        if mode == self._view_mode:
            return
        # 记忆当前模式的缩放，取回目标模式的缩放
        if self._view_mode == "grid":
            self._grid_scale = self._card_scale
        else:
            self._list_scale = self._card_scale
        self._view_mode = mode
        self._card_scale = self._grid_scale if mode == "grid" else self._list_scale
        self._card_layout.set_mode(mode)

        # 现有卡片原地迁移形态/样式与缩放基准
        card_layout_mode = self._card_layout_mode()
        is_grid = mode == "grid"
        for path, card in self._card_widgets.items():
            card.set_tile_style(is_grid)
            card.set_layout_mode(card_layout_mode)
            if is_grid:
                card.clear_actions()
                card.setToolTip(path)
                card.set_scale(
                    self._card_scale, base_overrides=self._grid_base_overrides
                )
            else:
                card.setToolTip("")
                card.clear_actions()
                self._add_card_actions(card, path)
                card.set_fixed_width(None)
                card.set_scale(
                    self._card_scale, base_overrides=self._card_base_overrides
                )
        self._card_layout.setSpacing(4 if is_grid else int(5 * self._card_scale))
        self._sync_pool_card_geometry()

    def get_view_mode(self) -> str:
        """返回当前视图模式（"list" / "grid"，供测试与主窗口查询）。"""
        return self._view_mode

    def _card_layout_mode(self) -> str:
        """当前视图对应的卡片形态（列表=horizontal / 网格=vertical）。"""
        return "vertical" if self._view_mode == "grid" else "horizontal"

    def _sync_pool_card_geometry(self) -> None:
        """按当前视图同步卡片几何（网格：列数/列宽；两种模式：容器高度）。"""
        if self._view_mode == "grid":
            self._sync_grid_geometry()
        else:
            self._sync_card_container_height()

    def _sync_grid_geometry(self) -> None:
        """网格模式：按与文件选择器相同的算法重算列数/列宽并同步容器高度。

        基准宽由 ``calc_grid_base_width(self.font())`` × 缩放得出，列数/列宽
        经 ``calc_grid_cell``（共享单一事实来源）计算——同一缩放、同一可用
        宽度下，池子与选择器的卡片尺寸完全一致。
        """
        viewport_w = self._scroll_area.viewport().width()
        if viewport_w <= 0:
            return
        margins = self._card_layout.contentsMargins()
        available = max(0, viewport_w - margins.left() - margins.right())
        spacing = int(4 * 1.0)
        base_width = int(calc_grid_base_width(self.font()) * self._card_scale)
        if self._card_widgets:
            _, col_w = calc_grid_cell(available, base_width, spacing)
            for card in self._card_widgets.values():
                card.set_fixed_width(col_w)
        self._sync_card_container_height()

    def _sync_card_container_height(self) -> None:
        """按当前布局内容同步卡片容器固定高度（保证滚动范围正确）。

        容器高度由布局 ``heightForWidth`` 计算（列表=卡片高度总和；
        网格=行数 × 行高）；内容不足一屏时外层仍会按视口撑满，无副作用。
        """
        viewport_w = self._scroll_area.viewport().width()
        if viewport_w <= 0:
            return
        target = max(1, self._card_layout.heightForWidth(viewport_w))
        if self._card_container.minimumHeight() != target:
            self._card_container.setFixedHeight(target)

    # 仅布局尺寸键参与缩放；文字字号（title/subtitle/desc）必须原样保留，
    # 与 FileCardDelegate._get_scaled_config / StyledInfoCard.set_scale 行为一致——
    # Ctrl+滚轮缩放卡片时文字大小不跟随变化。weight/radius 等键同样原样保留，
    # 否则 title_weight=700 会被放大为非法字重（与 StyledInfoCard.set_scale 行为对齐）。
    # text_width 为竖向形态的文字基准宽度（随缩放参与最小宽度计算）。
    _SCALABLE_SIZE_KEYS = ("padding", "gap", "media_size", "icon_size", "text_width")

    def _build_card_size_overrides(self) -> dict:
        """按当前视图模式与缩放构建 size_overrides。

        列表：以 LIST_CONFIG（与文件选择器 list 卡片一致）为基准；
        网格：以竖向 SIZE_CONFIG（含 text_width）为基准。
        """
        base = (
            self._card_base_overrides
            if self._view_mode == "list"
            else self._grid_base_overrides
        )
        scale = self._card_scale
        return {
            key: max(1, int(value * scale)) if key in self._SCALABLE_SIZE_KEYS else value
            for key, value in base.items()
        }

    # ═════════════════════════════════════════════════════════════════════
    #  备份系统
    # ═════════════════════════════════════════════════════════════════════

    def _save_backup_if_needed(self, last_path: str = "All") -> None:
        """在允许的情况下请求保存备份（防抖）。"""
        self._pending_backup_last_path = last_path
        if self._suspend_backup_save:
            return
        if self._backup_save_timer.isActive():
            self._backup_save_timer.stop()
        self._backup_save_timer.start(self._backup_save_delay_ms)

    def _flush_pending_backup_save(self) -> None:
        """执行一次实际备份写入。"""
        if self._suspend_backup_save:
            return
        self.save_backup(self._pending_backup_last_path)

    def flush_backup_save_now(self, last_path: Optional[str] = None) -> None:
        """立即执行一次保存，通常用于退出前等必须落盘的场景。"""
        if last_path is not None:
            self._pending_backup_last_path = last_path
        if self._backup_save_timer.isActive():
            self._backup_save_timer.stop()
        self.save_backup(self._pending_backup_last_path)

    def save_backup(self, last_path: str = "All") -> None:
        """保存当前文件列表到备份文件（原子写盘：tmp + replace）。"""
        try:
            backup_data = self._build_backup_payload(last_path)
            tmp_file = f"{self.backup_file}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self.backup_file)
        except (IOError, OSError, TypeError, ValueError):
            pass  # 静默失败，不影响主流程

    @classmethod
    def _serialize_backup_item(cls, file_info: dict) -> Optional[dict]:
        """将运行时文件信息压缩为可安全写入 JSON 的备份结构。

        委派给 ``StagingPoolService.serialize_backup_item``——序列化
        白名单（字符串/布尔字段）由服务层单一维护，避免字段漂移。
        """
        return StagingPoolService.serialize_backup_item(file_info)

    def _build_backup_payload(self, last_path: str = "All") -> dict:
        """构建统一的备份载荷，过滤不可序列化的运行时字段。"""
        items = []
        for file_info in self.items:
            serialized = self._serialize_backup_item(file_info)
            if serialized:
                items.append(serialized)
        return {
            "items": items,
            "selector_state": {
                "last_path": str(last_path or "All"),
            },
        }

    def load_backup(self) -> dict:
        """从备份文件加载文件列表。

        Returns:
            规范化后的备份数据，如果没有备份则返回空结构。
        """
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, "r", encoding="utf-8") as f:
                    raw_backup = json.load(f)
                if isinstance(raw_backup, dict):
                    items = raw_backup.get("items", [])
                    selector_state = raw_backup.get("selector_state", {})
                elif isinstance(raw_backup, list):
                    items = raw_backup
                    selector_state = {}
                else:
                    items = []
                    selector_state = {}
                normalized_items = []
                for file_info in items:
                    serialized = self._serialize_backup_item(file_info)
                    if serialized:
                        normalized_items.append(serialized)
                last_path = (
                    selector_state.get("last_path", "All")
                    if isinstance(selector_state, dict)
                    else "All"
                )
                return {
                    "items": normalized_items,
                    "selector_state": {"last_path": str(last_path or "All")},
                }
        except json.JSONDecodeError:
            pass
        except (IOError, OSError, TypeError, ValueError):
            pass
        return {"items": [], "selector_state": {"last_path": "All"}}

    # ═════════════════════════════════════════════════════════════════════
    #  文件操作
    # ═════════════════════════════════════════════════════════════════════

    def _add_card_actions(self, card: StyledInfoCard, file_path: str) -> None:
        """为列表卡添加悬浮操作按钮（重命名 / 删除）。

        网格瓦片卡不添加按钮（删除走右键；New 布局下暂不提供重命名）。

        Args:
            card: 目标卡片。
            file_path: 卡片对应文件路径（按钮回调绑定用）。
        """
        trash_icon = str(self._icons_dir / "trash.svg")
        card.add_action(
            "重命名",
            variant="secondary",
            size="sm",
            callback=lambda fp=file_path: self.rename_file_by_path(fp),
        )
        card.add_action(
            "",
            icon=trash_icon,
            variant="danger",
            size="sm",
            callback=lambda fp=file_path: self.remove_file(fp),
        )

    def add_file(self, file_info: dict) -> None:
        """添加文件或文件夹到暂存池（创建 StyledInfoCard widget）。"""
        file_path = os.path.normpath(file_info["path"])
        if file_path in self._card_widgets:
            warning(f"已存在于储存池，忽略重复添加: {file_path}")
            return
        file_info = dict(file_info)
        file_info.setdefault("display_name", file_info.get("name", os.path.basename(file_path)))
        file_info.setdefault("original_name", file_info.get("name", os.path.basename(file_path)))
        if file_info.get("is_dir") and "size_calculating" not in file_info:
            file_info["size_calculating"] = True
        if (self.previewing_file_path
                and os.path.normcase(file_path) == os.path.normcase(self.previewing_file_path)):
            file_info["is_previewing"] = True

        # 创建 StyledInfoCard
        display_name = file_info.get("display_name") or file_info.get("name") or os.path.basename(file_path)
        info_text = self._build_info_text(file_info)
        is_grid = self._view_mode == "grid"
        # size_overrides 基于当前 _card_scale 动态计算，使新加入卡片继承用户最新的缩放；
        # 卡片形态/样式随视图模式：列表=横向信息卡（历史），网格=竖向平铺瓦片（New 布局，
        # 与文件选择器网格卡同一规格：居中文件名 + 无副标题 + 无悬浮操作）
        card = StyledInfoCard(
            layout_mode=self._card_layout_mode(),
            title=display_name,
            subtitle="" if is_grid else info_text,
            overlay_enabled=not is_grid,
            tile_style=is_grid,
            size_overrides=self._build_card_size_overrides(),
            parent=self._card_container,
        )
        card.set_file_path(file_path)

        # 尝试加载缩略图/图标
        icon_pixmap = self._get_file_icon_pixmap(file_info)
        if icon_pixmap and not icon_pixmap.isNull():
            card.set_media_pixmap(icon_pixmap)

        if is_grid:
            # 网格瓦片：无悬浮操作按钮（删除走右键，New 布局下不提供重命名），
            # 隐藏的副标题信息以 tooltip 提供
            card.setToolTip(info_text or file_path)
        else:
            self._add_card_actions(card, file_path)

        # 点击预览
        card.clicked.connect(self._handle_card_clicked)
        # 右键处理
        card.right_clicked.connect(self._handle_card_right_clicked)

        # 框选手势：卡片及其子控件纳入事件过滤（任意位置可起拖框选/右键批量移除）
        self._install_card_filters(card)

        # 设置初始状态：框选选中态为瞬时 UI 状态，不随备份恢复，始终以未选中启动
        if file_info.get("is_previewing"):
            card.set_previewing(True)

        # 立即完成其它进行中的入口动画，确保它们的占位 spacer 被真实卡片替换，
        # 避免新卡片插入到尚未释放的占位位置导致重叠。
        self._finalize_entry_animations()

        # 在插入 layout 之前预设为完全透明，避免卡片在动画启动前以完全不透明
        # 状态被绘制一次（这会导致整个列表因新卡片突然占位而抽搐闪烁）。
        # 动画禁用时由 _animate_card_entry 立即恢复为 1.0。
        if is_animation_enabled("file_record_changes", default=True):
            card.card_opacity = 0.0

        # 插入到末尾（视图布局无尾部弹簧）。用 setUpdatesEnabled 包裹，强制
        # layout 同步计算，避免 QScrollArea 异步更新 _card_container geometry
        # 时产生中间状态，导致已有卡片视觉位置跳变（抽搐）。
        self._card_container.setUpdatesEnabled(False)
        try:
            self._card_layout.addWidget(card)
            self._card_layout.activate()
        finally:
            self._card_container.setUpdatesEnabled(True)
            self._card_container.update()
        self._card_widgets[file_path] = card
        debug(f"已添加文件到储存池: {file_path}")
        # 新增卡片后同步视图几何（网格：列宽与容器高度；列表：容器高度）
        self._sync_pool_card_geometry()

        self.items.append(file_info)
        self.update_stats()
        self._save_backup_if_needed()
        self.pool_changed.emit()

        # 播放创建动画（淡入 + 从左侧滑入）
        QTimer.singleShot(
            0,
            lambda c=card, fp=file_path: self._animate_card_entry(c, fp),
        )

        # 如果是目录，异步计算实际大小
        if file_info.get("is_dir"):
            self._calculate_folder_size(file_path)

    def _slide_offset_for_rect(self, rect: QRect) -> int:
        """计算水平滑入/滑出偏移量（viewport 宽度的 18%，限制在 28~96px）。"""
        width = rect.width() if rect.isValid() else self._card_container.width()
        if width <= 0:
            width = self._card_container.width()
        return max(
            self._card_motion_min_slide,
            min(self._card_motion_max_slide, int(width * self._card_motion_slide_ratio)),
        )

    def _animate_card_entry(self, card: StyledInfoCard, file_path: str) -> None:
        """播放卡片创建动画：从左侧淡入并滑入最终位置。

        卡片保持在 layout 中，通过 paint-level 属性实现淡入 + 从左侧滑入，
        不触发 removeWidget/insertWidget，避免 layout 重排导致其它卡片抖动。
        卡片在 add_file 中已被预设为 card_opacity=0.0，因此不会在动画启动前
        闪现完全不透明状态。
        """
        if not is_animation_enabled("file_record_changes", default=True):
            # 动画禁用：直接恢复为完全不透明
            card.card_opacity = 1.0
            return
        if file_path in self._removing_paths:
            # 该卡片已被请求移除，清理可能已存在的 spacer 后让退出动画负责
            self._remove_entry_spacer(file_path)
            return
        if card is None or card.isHidden() or not self._card_widgets:
            return

        # 若该路径已有动画在运行，先完成它，确保旧卡片的 on_finished 得到执行
        self._finalize_card_animation(file_path)
        self._remove_entry_spacer(file_path)

        card.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        target_rect = card.geometry()
        if not target_rect.isValid():
            card.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            card.card_opacity = 1.0
            return

        slide = self._slide_offset_for_rect(target_rect)
        # 卡片已被预设为 card_opacity=0.0，这里只需设置 x_offset 并启动动画。
        # 不调用 processEvents()，避免中间状态被绘制导致抖动。
        card.x_offset = -slide

        self._run_card_motion(
            file_path=file_path,
            card=card,
            start_rect=QRect(
                target_rect.x() - slide, target_rect.y(),
                target_rect.width(), target_rect.height(),
            ),
            end_rect=target_rect,
            start_opacity=0.0,
            end_opacity=1.0,
            duration=self._card_motion_duration_ms,
            easing=QEasingCurve.OutCubic,
            on_finished=lambda: self._finish_card_entry(card, file_path),
            kind="entry",
        )

    def _finish_card_entry(self, card: StyledInfoCard, file_path: str) -> None:
        """创建动画结束：恢复卡片交互状态。"""
        if card is None:
            return
        card.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        card.card_opacity = 1.0
        card.x_offset = 0

    def _remove_entry_spacer(self, file_path: str) -> None:
        """移除并清理指定路径的创建动画占位 spacer。"""
        spacer = self._entry_spacers.pop(file_path, None)
        if spacer is not None:
            try:
                self._card_layout.removeItem(spacer)
            except RuntimeError:
                pass

    def _stop_card_animation(self, file_path: str) -> None:
        """停止并清理指定路径的卡片动画（不执行其 on_finished 回调）。"""
        info = self._active_card_animations.pop(file_path, None)
        if info is None:
            return
        group = info.get("group")
        if group is not None:
            try:
                group.stop()
                group.deleteLater()
            except RuntimeError:
                pass

    def _finalize_card_animation(self, file_path: str) -> None:
        """强制完成指定路径的卡片动画并执行其 on_finished 回调。"""
        info = self._active_card_animations.pop(file_path, None)
        if info is None:
            return
        group = info.get("group")
        if group is not None:
            # 暂时断开 finished 信号，避免 start 后 stop 触发 _cleanup 导致重复执行
            try:
                group.finished.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                group.stop()
            except RuntimeError:
                pass
            try:
                group.deleteLater()
            except RuntimeError:
                pass
        on_finished = info.get("on_finished")
        if on_finished is not None:
            try:
                on_finished()
            except Exception as exc:
                debug(f"卡片动画完成回调失败：{exc}")

    def _finalize_entry_animations(self) -> None:
        """立即完成所有进行中的创建（入口）动画，确保状态恢复。"""
        for path in list(self._active_card_animations.keys()):
            info = self._active_card_animations.get(path)
            if info is not None and info.get("kind") == "entry":
                self._finalize_card_animation(path)

    def _run_card_motion(
        self,
        file_path: str,
        card: StyledInfoCard,
        start_rect: QRect,
        end_rect: QRect,
        start_opacity: float,
        end_opacity: float,
        duration: int,
        easing: QEasingCurve,
        on_finished=None,
        kind: str = "motion",
        shrink_to: Optional[float] = None,
    ) -> None:
        """同时播放 geometry（或 x_offset）、透明度与可选缩小动画。

        ``shrink_to`` 非 None 时追加绘制级 ``card_shrink`` 动画（供网格移除的
        "向后缩小渐隐"使用）；``start_rect == end_rect`` 且非入场动画时跳过
        几何动画（网格退出卡片原地播放绘制级动画、几何不动）。
        """
        if card is None:
            return

        # 停止同路径旧动画，避免属性与状态冲突；旧动画的 on_finished 会恢复
        # 卡片状态，因此要确保在启动新动画前被调用。
        self._finalize_card_animation(file_path)

        # 入场动画不再驱动 geometry（卡片保持在 layout 中），改用 x_offset
        # 属性实现水平滑入，避免 remove/insert 导致的 layout 抖动。
        animations: list[QPropertyAnimation] = []
        if kind == "entry":
            x_anim = QPropertyAnimation(card, b"x_offset")
            x_anim.setDuration(duration)
            x_anim.setStartValue(start_rect.x() - end_rect.x())
            x_anim.setEndValue(0)
            x_anim.setEasingCurve(easing)
            animations.append(x_anim)
        elif start_rect != end_rect:
            geom_anim = QPropertyAnimation(card, b"geometry")
            geom_anim.setDuration(duration)
            geom_anim.setStartValue(start_rect)
            geom_anim.setEndValue(end_rect)
            geom_anim.setEasingCurve(easing)
            animations.append(geom_anim)

        # 绘制级"向后缩小"（网格移除用）：与透明度动画并行，几何保持不变。
        if shrink_to is not None:
            shrink_anim = QPropertyAnimation(card, b"card_shrink")
            shrink_anim.setDuration(duration)
            shrink_anim.setStartValue(card.card_shrink)
            shrink_anim.setEndValue(float(shrink_to))
            shrink_anim.setEasingCurve(easing)
            animations.append(shrink_anim)

        # 使用 StyledInfoCard 的 paint-level 透明度属性，避免 offscreen effect
        # 与 overlay 子控件的 effect 嵌套导致的 painter 冲突。
        card.card_opacity = start_opacity
        opacity_anim = QPropertyAnimation(card, b"card_opacity")
        opacity_anim.setDuration(duration)
        opacity_anim.setStartValue(start_opacity)
        opacity_anim.setEndValue(end_opacity)
        opacity_anim.setEasingCurve(
            QEasingCurve.OutCubic if end_opacity > start_opacity else QEasingCurve.InCubic
        )
        animations.append(opacity_anim)

        group = QParallelAnimationGroup(self)
        for anim in animations:
            group.addAnimation(anim)
        self._active_card_animations[file_path] = {
            "group": group,
            "on_finished": on_finished,
            "kind": kind,
        }

        def _cleanup():
            self._active_card_animations.pop(file_path, None)
            if on_finished is not None:
                on_finished()

        group.finished.connect(_cleanup)
        group.start(QAbstractAnimation.DeleteWhenStopped)

    def _build_info_text(self, file_info: dict) -> str:
        """构建文件信息文本（副标题）。"""
        file_path = file_info.get("path", "")
        if file_info.get("is_missing", False):
            return file_path
        if file_info.get("is_dir", False):
            if file_info.get("size_calculating", False):
                return "正在计算大小..."
            size_text = self._format_file_size(file_info.get("size")) if file_info.get("size") is not None else "文件夹"
            return size_text
        size_text = self._format_file_size(file_info.get("size")) if file_info.get("size") is not None else ""
        if file_path and size_text:
            return f"{file_path}  {size_text}"
        return file_path or size_text or ""

    def _get_file_icon_pixmap(self, file_info: dict) -> Optional[QPixmap]:
        """获取文件图标 QPixmap，与文件选择器 layout 使用相同的 FileIconManager 管线。

        管线优先级（FileIconManager 内部处理）：
        1. 目录 → 文件夹 SVG 图标
        2. 照片/视频 → 优先返回已存在的缩略图
        3. 系统图标（exe/lnk/url）→ SVG 占位符 + 触发异步加载
        4. 其他 → SVG 图标（含未知文件文字叠加）
        """
        try:
            if not file_info.get("path", ""):
                return None
            from freeassetfilter.services.file_icon_manager import FileIconManager
            dpr = self._get_device_pixel_ratio()
            pix = FileIconManager().get_icon_pixmap(file_info, 48, dpr)
            if pix and not pix.isNull():
                return pix
        except Exception as exc:
            debug(f"卡片图标生成失败（回退占位）：{exc}")
        return None

    @staticmethod
    def _get_device_pixel_ratio() -> float:
        """获取设备像素比（DPI 缩放因子），与 FileListModel 实现一致。"""
        try:
            app = QApplication.instance()
            if app:
                screen = app.primaryScreen()
                if screen:
                    ratio = float(screen.devicePixelRatio())
                    if ratio > 0:
                        return ratio
        except (RuntimeError, AttributeError, TypeError, ValueError):
            pass
        return 1.0

    def remove_file(self, file_path: str) -> None:
        """从暂存池移除文件。"""
        normalized_path = os.path.normpath(file_path)
        if normalized_path not in self._card_widgets:
            return
        if normalized_path in self._removing_paths:
            return
        if (self.previewing_file_path
                and os.path.normcase(normalized_path) == os.path.normcase(self.previewing_file_path)):
            self.previewing_file_path = None
            self.preview_cancel_requested.emit()

        if not is_animation_enabled("file_record_changes", default=True):
            self._finalize_remove(normalized_path)
            return

        self._removing_paths.add(normalized_path)
        # 先结束其它进行中的移除位移动画，避免 y_offset 叠加导致位置计算错误
        self._cancel_all_remove_motions()
        QTimer.singleShot(
            0, lambda p=normalized_path: self._animate_card_exit(p)
        )

    def _animate_card_exit(self, file_path: str) -> None:
        """播放卡片移除动画。

        - 列表模式：向左滑出并淡出；退出完成后再带动下方卡片整体上移；
        - 网格（New 布局）：原地"向后缩小"（card_shrink 1.0 → 0.8）并渐隐，
          同时其余卡片以几何动画平滑补位（见 ``_animate_grid_card_exit``）。
        """
        card = self._card_widgets.get(file_path)
        if card is None:
            self._removing_paths.discard(file_path)
            return

        # 若该卡片正在播放创建动画，先完成它，避免创建动画的 cleanup 干扰退出动画
        self._finalize_card_animation(file_path)
        self._remove_entry_spacer(file_path)

        QApplication.processEvents()
        start_rect = card.geometry()
        if not start_rect.isValid():
            self._finalize_remove(file_path)
            return

        if self._view_mode == "grid":
            self._animate_grid_card_exit(file_path, card, start_rect)
            return

        removed_index = self._card_layout.indexOf(card)

        # 列表模式：在目标位置预先插入一个等高的透明占位控件——退出动画期间
        # 目标卡片仍在视觉上占据原位置，下方卡片不会提前上移，避免重叠。
        placeholder: Optional[QWidget] = None
        if removed_index >= 0 and self._view_mode == "list":
            placeholder = QWidget(self._card_container)
            placeholder.setFixedHeight(start_rect.height())
            # category (c) 直写：退出动画的临时透明占位控件（创建即销毁、
            # 无主题色，走注册表反而多一次重建）；见
            # app_stylesheet.DIRECT_SETSTYLESHEET_SITES。
            placeholder.setStyleSheet("background: transparent; border: none;")
            self._card_layout.insertWidget(removed_index, placeholder)

        self._card_layout.removeWidget(card)
        card.setGeometry(start_rect)
        card.raise_()

        def _on_exit_finished() -> None:
            self._finalize_remove(file_path)
            if placeholder is not None:
                self._collapse_placeholder(file_path, placeholder)

        slide = self._slide_offset_for_rect(start_rect)
        end_rect = QRect(
            start_rect.x() - slide, start_rect.y(),
            start_rect.width(), start_rect.height(),
        )
        self._run_card_motion(
            file_path=file_path,
            card=card,
            start_rect=start_rect,
            end_rect=end_rect,
            start_opacity=1.0,
            end_opacity=0.0,
            duration=self._card_motion_duration_ms,
            easing=QEasingCurve.InCubic,
            on_finished=_on_exit_finished,
            kind="exit",
        )

    def _animate_grid_card_exit(
        self, file_path: str, card: StyledInfoCard, start_rect: QRect
    ) -> None:
        """网格移除：被删卡片原地缩小渐隐，其余卡片级联补位。

        被删卡片立即移出布局但固定原几何（raise 后原地播放绘制级动画）；
        其余卡片先快照当前可见几何（可能在上一轮补位动画中途），强制布局
        算出目标几何后回拨到快照，再以"起步延迟 + 按距离错峰 + OutQuint"
        的几何动画滑入目标位置（级联波浪收拢，距空位越远启动越晚）。
        批量移除时后一次移除会停掉上一轮补位并从当前几何续走，最终只剩
        最后一轮补位动画，不与退出动画叠加冲突。
        """
        # 上一轮补位先停下：卡片停留在当前几何，随后统一按新目标续走
        self._cancel_grid_fill()

        # 快照其余卡片当前可见几何（排除已进入移除流程的卡片）
        moving_paths = [
            path for path in self._card_widgets
            if path != file_path and path not in self._removing_paths
        ]
        snapshots = {
            path: QRect(self._card_widgets[path].geometry()) for path in moving_paths
        }

        # 流式序号（错峰距离基准）：必须在 removeWidget 触发重排前记录
        slot_index = self._card_layout.indexOf(card)
        order_index = {
            path: self._card_layout.indexOf(self._card_widgets[path])
            for path in moving_paths
        }

        # 被删卡片移出布局：几何固定，仅播绘制级缩小渐隐
        self._card_layout.removeWidget(card)
        card.setGeometry(start_rect)
        card.raise_()

        # 强制布局同步重排，读取其余卡片的目标几何（列宽不变，坐标可即刻确定）
        try:
            self._card_layout.activate()
        except RuntimeError:
            pass
        targets = {
            path: QRect(self._card_widgets[path].geometry()) for path in moving_paths
        }

        # 回拨快照几何 + 建立级联补位动画（快照 == 目标的卡片无需移动）
        fill_group: Optional[QParallelAnimationGroup] = None
        for path in moving_paths:
            target = targets[path]
            if snapshots[path] == target:
                continue
            fill_card = self._card_widgets.get(path)
            if fill_card is None:
                continue
            fill_card.setGeometry(snapshots[path])
            if fill_group is None:
                fill_group = QParallelAnimationGroup(self)
            # 错峰：紧邻空位者最先启动（起步延迟），越远延迟越大且封顶
            steps = max(0, order_index.get(path, slot_index + 1) - slot_index - 1)
            delay = self._card_fill_delay_ms + min(
                self._card_fill_stagger_ms * steps, self._card_fill_stagger_max_ms
            )
            seq = QSequentialAnimationGroup(fill_group)
            if delay > 0:
                seq.addAnimation(QPauseAnimation(delay, seq))
            fill_anim = QPropertyAnimation(fill_card, b"geometry")
            fill_anim.setDuration(self._card_fill_duration_ms)
            fill_anim.setStartValue(snapshots[path])
            fill_anim.setEndValue(target)
            fill_anim.setEasingCurve(QEasingCurve.OutQuint)
            seq.addAnimation(fill_anim)
            fill_group.addAnimation(seq)

        if fill_group is not None:
            def _on_fill_finished() -> None:
                self._grid_fill_group = None
                # 补位完成：容器高度随新行数回收
                self._sync_pool_card_geometry()

            fill_group.finished.connect(_on_fill_finished)
            self._grid_fill_group = fill_group
            fill_group.start(QAbstractAnimation.DeleteWhenStopped)

        def _on_exit_finished() -> None:
            self._finalize_remove(file_path)

        self._run_card_motion(
            file_path=file_path,
            card=card,
            start_rect=start_rect,
            end_rect=start_rect,
            start_opacity=1.0,
            end_opacity=0.0,
            duration=self._card_motion_duration_ms,
            easing=QEasingCurve.InCubic,
            on_finished=_on_exit_finished,
            kind="exit",
            shrink_to=self._card_motion_shrink_scale,
        )

    def _finalize_remove(self, file_path: str) -> None:
        """最终移除文件（动画完成后）。"""
        self._removing_paths.discard(file_path)
        card = self._card_widgets.pop(file_path, None)
        if card is not None:
            card.deleteLater()
        # 同步清理框选集合中的该路径（卡片已删，仅需移除记录）
        self._box_selected_paths.discard(file_path)
        self.items = [f for f in self.items if os.path.normpath(f.get("path", "")) != file_path]
        self.update_stats()
        self._save_backup_if_needed()
        # 卡片已移除：网格重排 / 容器高度同步。网格补位动画进行中时跳过，
        # 避免布局同步把补位中的卡片拍回目标位——几何同步由补位组 finished
        # 回调兜底；无补位动画（动画禁用 / 无后续卡片）时照常同步。
        if not (self._view_mode == "grid" and self._grid_fill_group is not None):
            self._sync_pool_card_geometry()
        self.pool_changed.emit()

    def _collapse_placeholder(
        self, removed_path: str, placeholder: QWidget
    ) -> None:
        """将占位控件高度动画到 0，通过 layout 驱动下方卡片作为整体向上平移。

        占位控件仍保留在 layout 中，因此下方卡片由 layout 自动同步推动，
        不会出现单张卡片被父容器裁切的问题。
        """
        if not is_animation_enabled("file_record_changes", default=True):
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
            self._sync_pool_card_geometry()
            return

        start_height = placeholder.height()
        if start_height <= 0:
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
            self._sync_pool_card_geometry()
            return

        placeholder.setMinimumHeight(0)
        placeholder.setMaximumHeight(start_height)

        group = QParallelAnimationGroup(self)
        for prop in (b"minimumHeight", b"maximumHeight"):
            anim = QPropertyAnimation(placeholder, prop)
            anim.setDuration(self._card_motion_duration_ms)
            anim.setStartValue(start_height)
            anim.setEndValue(0)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)

        group._placeholder = placeholder

        def _cleanup() -> None:
            self._active_remove_motion_groups.pop(removed_path, None)
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
            # 折叠完成：容器高度随内容回收
            self._sync_pool_card_geometry()

        group.finished.connect(_cleanup)
        self._active_remove_motion_groups[removed_path] = group
        group.start(QAbstractAnimation.DeleteWhenStopped)

    def _cancel_remove_motion(self, removed_path: str) -> None:
        """停止指定路径关联的位移动画并清理占位控件。"""
        group = self._active_remove_motion_groups.pop(removed_path, None)
        if group is None:
            return
        try:
            group.stop()
        except RuntimeError:
            pass
        # 清理关联的占位控件
        placeholder = getattr(group, "_placeholder", None)
        if placeholder is not None:
            try:
                placeholder.setParent(None)
                placeholder.deleteLater()
            except RuntimeError:
                pass
        try:
            group.deleteLater()
        except RuntimeError:
            pass
        self._sync_pool_card_geometry()

    def _cancel_grid_fill(self) -> None:
        """停止网格补位动画（卡片停留在当前几何，不做布局同步）。

        供下一次移除复用：新移除会重新快照当前几何并重建补位动画；
        也供 ``clear_all`` 前置清理复用（统一淡出时不需要补位）。
        """
        group = self._grid_fill_group
        if group is None:
            return
        self._grid_fill_group = None
        try:
            group.finished.disconnect()
        except (TypeError, RuntimeError):
            pass
        try:
            group.stop()
        except RuntimeError:
            pass
        try:
            group.deleteLater()
        except RuntimeError:
            pass

    def _cancel_all_remove_motions(self) -> None:
        """停止所有进行中的移除位移动画（列表占位折叠 + 网格补位）。"""
        for path in list(self._active_remove_motion_groups.keys()):
            self._cancel_remove_motion(path)
        self._cancel_grid_fill()

    def clear_all(self) -> None:
        """清空所有项目（带确认）。"""
        is_confirmed = _show_custom_dialog(
            self,
            "确认清空",
            "确定要清空所有项目吗？",
            ["确定", "取消"],
            ["primary", "normal"],
        ) == 0
        if is_confirmed:
            self.clear_all_without_confirmation()

    def clear_all_without_confirmation(self) -> None:
        """不显示确认对话框，直接清空所有项目。"""
        if not is_animation_enabled("file_record_changes", default=True):
            self._clear_all_immediate()
            return

        cards = list(self._card_widgets.values())
        paths = list(self._card_widgets.keys())
        if not cards:
            self._clear_all_immediate()
            return

        # 停止所有可能正在进行的动画（创建动画 + 移除位移动画）
        for path in paths:
            self._stop_card_animation(path)
        self._cancel_all_remove_motions()
        for path in list(self._entry_spacers.keys()):
            self._remove_entry_spacer(path)

        # 复位可能被网格移除动画缩小的绘制缩放（卡在退出中途被停止时），
        # 统一从原尺寸播放清空淡出动画
        for card in cards:
            try:
                card.card_shrink = 1.0
            except RuntimeError:
                pass

        QApplication.processEvents()
        rects = {card: QRect(card.geometry()) for card in cards}
        for card in cards:
            self._card_layout.removeWidget(card)
            card.setGeometry(rects[card])

        # 清空数据状态
        self._card_widgets.clear()
        self.items.clear()
        self._box_selected_paths.clear()
        self.previewing_file_path = None
        self.update_stats()
        self._save_backup_if_needed()
        # 卡片全部移出布局：容器高度立即回收
        self._sync_pool_card_geometry()
        self.pool_changed.emit()

        # 统一播放淡出左移动画
        for idx, card in enumerate(cards):
            start_rect = rects[card]
            slide = self._slide_offset_for_rect(start_rect)
            end_rect = QRect(
                start_rect.x() - slide, start_rect.y(),
                start_rect.width(), start_rect.height(),
            )
            self._run_card_motion(
                file_path=f"__clear_all_{idx}__",
                card=card,
                start_rect=start_rect,
                end_rect=end_rect,
                start_opacity=1.0,
                end_opacity=0.0,
                duration=self._card_motion_duration_ms,
                easing=QEasingCurve.InCubic,
                on_finished=lambda c=card: c.deleteLater(),
                kind="exit",
            )

    def _clear_all_immediate(self) -> None:
        """立即清空所有项目（无动画）。"""
        for card in list(self._card_widgets.values()):
            self._card_layout.removeWidget(card)
            card.deleteLater()
        self._card_widgets.clear()
        self.items.clear()
        self._box_selected_paths.clear()
        self.previewing_file_path = None
        self.update_stats()
        self._save_backup_if_needed()
        self._sync_pool_card_geometry()
        self.pool_changed.emit()

    def update_stats(self) -> None:
        """更新统计信息（条目数 + 总大小）与空池提示显隐。"""
        total_items = len(self.items)
        total_size = 0
        for item in self.items:
            size_calc = item.get("size_calculating")
            if not size_calc:
                sz = item.get("size")
                if sz is not None:
                    total_size += int(sz)
        self._count_label.setText(f"{total_items}个条目")
        self._size_label.setText(self._format_file_size(total_size))
        self._update_empty_hint_visibility()

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """将字节数格式化为可读的文件大小字符串。"""
        if not isinstance(size_bytes, (int, float)):
            return "0.00 MB"
        units = ["B", "KB", "MB", "GB", "TB"]
        index = 0
        size = float(size_bytes)
        while size >= 1024 and index < len(units) - 1:
            size /= 1024.0
            index += 1
        if index == 0:
            return f"{int(size)} {units[index]}"
        return f"{size:.2f} {units[index]}"

    # ═════════════════════════════════════════════════════════════════════
    #  视图信号处理
    # ═════════════════════════════════════════════════════════════════════

    def has_file(self, file_path: str) -> bool:
        """判断文件是否已在暂存池中。"""
        norm = os.path.normpath(file_path) if file_path else ""
        return norm in self._card_widgets

    def get_pool_paths(self) -> set[str]:
        """返回当前池中所有文件的路径集合。"""
        return set(self._card_widgets.keys())

    def _handle_card_clicked(self, file_path: str) -> None:
        """处理 StyledInfoCard 点击：清除框选后，如果正在预览则取消，否则发射预览信号。"""
        # 单击卡片 = 预览 + 清除框选选中态（"点击其他地方"即取消多选）
        self.clear_box_selection()
        norm_path = os.path.normpath(file_path) if file_path else ""
        if (norm_path
                and self.previewing_file_path
                and os.path.normcase(norm_path) == os.path.normcase(self.previewing_file_path)):
            self.preview_cancel_requested.emit()
        else:
            # 查找对应的 file_info 并发射
            for fi in self.items:
                if fi.get("path") and os.path.normpath(str(fi["path"])) == norm_path:
                    self.item_left_clicked.emit(fi)
                    break

    def _handle_card_right_clicked(self, file_path: str) -> None:
        """处理 StyledInfoCard 右键点击：发射 item_right_clicked 信号。

        Args:
            file_path: 被右键点击的文件路径。
        """
        norm_path = os.path.normpath(file_path) if file_path else ""
        # 查找对应的 file_info
        for fi in self.items:
            p = fi.get("path")
            if p and os.path.normpath(str(p)) == norm_path:
                self.item_right_clicked.emit(fi)
                break

    # ═════════════════════════════════════════════════════════════════════
    #  重命名
    # ═════════════════════════════════════════════════════════════════════

    def rename_file_by_path(self, file_path: str) -> None:
        """重命名池中的文件（显示名）。使用 styled 弹窗（create_input_dialog）输入新名称。"""
        norm_path = os.path.normpath(file_path) if file_path else ""
        # 在 self.items 中查找
        current_info = None
        for fi in self.items:
            p = fi.get("path")
            if p and os.path.normpath(str(p)) == norm_path:
                current_info = fi
                break
        if not current_info:
            return
        current_name = current_info.get("display_name") or current_info.get("name", "")

        # styled 弹窗（create_input_dialog：原生的 StyledDialog + QLineEdit 主题化输入框）
        rename_dialog = create_input_dialog(
            title="重命名",
            message="请输入新的显示名称：",
            placeholder="输入新的文件名",
            cancel_text="取消",
            confirm_text="确定",
        )
        # 预填当前显示名（QLineEdit 主题化样式在 create_input_dialog 中已设置）
        rename_dialog._input_field.setText(current_name)
        rename_dialog._input_field.selectAll()

        # StyledDialog 继承自 QWidget（不是 QDialog），没有 exec()，需要用 show() + QEventLoop 阻塞等待 finished
        result: list[int] = [0]
        loop = QEventLoop()
        rename_dialog.finished.connect(lambda r: result.__setitem__(0, r))
        rename_dialog.finished.connect(loop.quit)
        # 兜底：用户用 ESC / 关闭按钮时 finished 可能不发射，监听 closeEvent
        rename_dialog.destroyed.connect(loop.quit)
        rename_dialog.show()
        loop.exec()

        if result[0] != 1:
            return
        new_name = rename_dialog._input_field.text().strip()

        # 合法性校验
        if not new_name:
            return
        if len(new_name) > 255:
            return
        illegal_chars = r'\/:*?"<>|'
        if any(c in new_name for c in illegal_chars):
            return

        # 更新 self.items
        current_info["display_name"] = new_name
        # 更新对应的 StyledInfoCard
        card = self._card_widgets.get(norm_path)
        if card:
            card.set_title(new_name)
        self.update_stats()
        self._save_backup_if_needed()

    # ═════════════════════════════════════════════════════════════════════
    #  预览状态管理
    # ═════════════════════════════════════════════════════════════════════

    def set_previewing_file(self, file_path: str) -> None:
        """设置预览态：清除旧预览，设置新预览。

        Args:
            file_path: 要预览的文件路径，若为空则仅清除旧预览。
        """
        normalized = os.path.normpath(file_path) if file_path else None

        # 清除旧预览
        if self.previewing_file_path:
            old_card = self._card_widgets.get(self.previewing_file_path)
            if old_card:
                old_card.set_previewing(False)

        # 设置新预览
        self.previewing_file_path = normalized
        if normalized:
            new_card = self._card_widgets.get(normalized)
            if new_card:
                new_card.set_previewing(True)

    def clear_previewing_state(self) -> None:
        """清除所有卡片的预览状态。"""
        if self.previewing_file_path:
            card = self._card_widgets.get(self.previewing_file_path)
            if card:
                card.set_previewing(False)
        self.previewing_file_path = None

    # ═════════════════════════════════════════════════════════════════════
    #  外部拖放支持（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """接受外部 URL 拖入，显示蓝色虚线边框反馈。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_feedback(True)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """拖拽移动中持续接受。"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """拖拽离开时恢复样式。"""
        self._set_drag_feedback(False)

    def dropEvent(self, event: QDropEvent) -> None:
        """处理从外部拖入的文件/文件夹。"""
        self._set_drag_feedback(False)
        # 全局浮窗条目拖出携带自定义判别 MIME；其落点语义由浮窗
        # 自身判定（拖回主池 = 取消），主池绝不能把它当作外部拖入重复入池。
        from freeassetfilter.ui.floating_pool_window import FLOATING_DRAG_MIME

        if event.mimeData().hasFormat(FLOATING_DRAG_MIME):
            event.ignore()
            return
        if not event.mimeData().hasUrls():
            return
        urls = event.mimeData().urls()
        self.add_dropped_paths([url.toLocalFile() for url in urls])
        event.acceptProposedAction()

    def _set_drag_feedback(self, active: bool) -> None:
        """切换内容区拖放反馈（dragActive 动态属性 + repolish）。

        样式片段在 :meth:`set_section_styles` 中随面板基础样式一并注册
        （register_widget_qss 每控件单一片段，独立注册会被主题重注册覆盖），
        此处只切换属性并让样式表重新求值，不再拼接 setStyleSheet。
        """
        area = self._content_area
        if bool(area.property("dragActive")) == active:
            return
        area.setProperty("dragActive", active)
        style = area.style()
        style.unpolish(area)
        style.polish(area)
        area.update()

    def add_dropped_paths(self, paths: list[str]) -> None:
        """批量添加拖入路径（存在性过滤；OLE 拖入 / 提权兜底共用入口）。

        Args:
            paths: 待添加的本地路径列表；空串与不存在的路径一律跳过。
        """
        for file_path in paths:
            if file_path and os.path.exists(file_path):
                self._add_dropped_item(file_path)

    def _add_dropped_item(self, file_path: str) -> None:
        """构建文件信息并添加到暂存池。"""
        file_info = StagingPoolService.build_file_info(file_path)
        if file_info:
            self.add_file(file_info)

    # ═════════════════════════════════════════════════════════════════════
    #  导入/导出数据（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def show_import_export_dialog(self) -> None:
        """导入/导出数据选择对话框。"""
        choice = _show_custom_dialog(
            self,
            "导入/导出数据",
            "请选择操作：",
            ["导入数据", "导出数据", "取消"],
            ["primary", "secondary", "normal"],
        )

        if choice == 0:
            self.import_data()
        elif choice == 1:
            self.export_data()

    def import_data(self) -> None:
        """从 JSON 文件导入备份数据。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择导入文件", "", "JSON 文件 (*.json)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            _show_custom_dialog(
                self, "导入失败", f"读取文件失败：{e}",
                ["确定"], ["primary"], dialog_type="danger",
            )
            return

        # 支持两种格式：dict（含 items 键）或 列表
        if isinstance(raw, dict):
            items = raw.get("items", [])
        elif isinstance(raw, list):
            items = raw
        else:
            _show_custom_dialog(
                self, "导入失败", "文件格式不正确，应为 JSON 数组或备份结构。",
                ["确定"], ["primary"], dialog_type="danger",
            )
            return

        if not items:
            _show_custom_dialog(
                self, "导入提示", "文件中没有有效的条目数据。",
                ["确定"], ["primary"], dialog_type="info",
            )
            return

        # 询问清空或追加
        import_mode = _show_custom_dialog(
            self,
            "确认导入",
            f"即将导入 {len(items)} 个条目。是否清空现有条目？",
            ["清空并导入", "追加导入", "取消"],
            ["primary", "secondary", "normal"],
        )

        if import_mode == 2:
            return

        if import_mode == 0:
            self.clear_all_without_confirmation()

        # 逐条导入，检查文件是否存在
        success_count = 0
        unlinked = []
        for item in items:
            if not isinstance(item, dict) or "path" not in item:
                continue
            item_path = item.get("path", "")
            if os.path.exists(item_path):
                self.add_file(item)
                success_count += 1
            else:
                unlinked.append(item)

        # 显示未链接文件处理
        if unlinked:
            self.show_unlinked_files_dialog(unlinked)

        # 显示结果
        msg = f"成功导入 {success_count} 个条目。"
        if unlinked:
            msg += f"\n{len(unlinked)} 个文件路径不存在（已单独列出）。"
        _show_custom_dialog(
            self, "导入完成", msg,
            ["确定"], ["primary"], dialog_type="success",
        )

    def export_data(self) -> None:
        """将当前暂存池条目导出为 JSON 文件。"""
        if not self.items:
            _show_custom_dialog(
                self, "导出提示", "暂存池中没有数据可导出。",
                ["确定"], ["primary"], dialog_type="info",
            )
            return

        from datetime import datetime

        default_name = f"FAF_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出数据", default_name, "JSON 文件 (*.json)"
        )
        if not file_path:
            return

        payload = self._build_backup_payload("All")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            _show_custom_dialog(
                self, "导出成功",
                f"成功导出 {len(self.items)} 个条目到：\n{file_path}",
                ["确定"], ["primary"], dialog_type="success",
            )
        except (IOError, OSError, PermissionError) as e:
            _show_custom_dialog(
                self, "导出失败", f"写入文件失败：{e}",
                ["确定"], ["primary"], dialog_type="danger",
            )

    # ═════════════════════════════════════════════════════════════════════
    #  未链接文件对话框（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def show_unlinked_files_dialog(self, unlinked_items: list) -> None:
        """显示未链接（路径不存在的）文件处理对话框。

        Args:
            unlinked_items: 路径不存在的条目字典列表。
        """
        names = "\n".join(
            f"• {item.get('display_name', item.get('name', '未知'))}"
            for item in unlinked_items[:20]
        )
        if len(unlinked_items) > 20:
            names += f"\n… 及其他 {len(unlinked_items) - 20} 个"
        choice = _show_custom_dialog(
            self,
            "未链接文件",
            f"以下 {len(unlinked_items)} 个文件路径不存在：\n\n{names}",
            ["手动链接", "忽略这些文件", "取消"],
            ["primary", "secondary", "normal"],
        )

        if choice == 0:
            # 手动链接：选择替换目录
            dir_path = QFileDialog.getExistingDirectory(
                self, "选择包含替代文件的目录"
            )
            if dir_path:
                self._relink_files(unlinked_items, dir_path)
        elif choice == 1:
            pass  # 忽略，不导入这些条目
        # choice == 2 → 取消整个导入

    def _relink_files(self, unlinked_items: list, search_dir: str) -> list:
        """在指定目录中通过文件名匹配重新链接未链接的文件。

        Args:
            unlinked_items: 未链接条目的列表。
            search_dir: 要搜索的目录。

        Returns:
            成功重新链接的条目列表。
        """
        relinked = []
        for item in unlinked_items:
            target_name = item.get("display_name", item.get("name", ""))
            if not target_name:
                continue
            candidate = os.path.join(search_dir, target_name)
            if os.path.exists(candidate):
                item["path"] = candidate
                self.add_file(item)
                relinked.append(item)

        if relinked:
            _show_custom_dialog(
                self, "重新链接", f"成功重新链接 {len(relinked)} 个文件。",
                ["确定"], ["primary"], dialog_type="success",
            )
        return relinked

    # ═════════════════════════════════════════════════════════════════════
    #  导出文件（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def export_selected_files(self) -> None:
        """导出暂存池中的文件（含模式选择、空间检查、进度显示）。"""
        if not self.items:
            _show_custom_dialog(
                self, "提示", "暂存池中没有文件可导出。",
                ["确定"], ["primary"], dialog_type="info",
            )
            return

        # 模式选择
        export_mode = _show_custom_dialog(
            self,
            "选择导出方式",
            "请选择导出模式：\n\n"
            "平铺导出：所有文件直接复制到目标目录\n"
            "分类导出：按原始文件夹分类存放",
            ["平铺导出", "分类导出", "取消"],
            ["primary", "primary", "normal"],
            vertical=True,
        )

        if export_mode == 2:
            return

        # 选择目标目录
        target_dir = QFileDialog.getExistingDirectory(self, "选择导出目标目录")
        if not target_dir:
            return

        # 计算总大小（同步，已知道的不再计算）
        total_size = 0
        for item in self.items:
            sz = item.get("size")
            if sz is not None and not item.get("size_calculating"):
                total_size += int(sz)
            elif os.path.isfile(item.get("path", "")):
                try:
                    total_size += os.path.getsize(item["path"])
                except (OSError, PermissionError):
                    pass

        # 空间检查
        check_ok = self._check_space_and_proceed(target_dir, total_size)
        if check_ok is False:
            return
        if check_ok == "reselect":
            self.export_selected_files()
            return

        self._do_export(list(self.items), target_dir, export_mode)

    def _check_space_and_proceed(
        self, target_dir: str, needed_bytes: int
    ) -> bool | str:
        """检查目标目录磁盘空间是否充足。

        Args:
            target_dir: 目标目录。
            needed_bytes: 所需空间（字节）。

        Returns:
            True: 继续；False: 取消；"reselect": 重新选择。
        """
        total, free = StagingPoolService().get_directory_space(target_dir)
        if total is None or free is None:
            choice = _show_custom_dialog(
                self,
                "无法检测空间",
                "无法获取目标目录的空间信息，是否继续？",
                ["继续", "重新选择", "取消"],
                ["primary", "normal", "normal"],
            )
            return {0: True, 1: "reselect"}.get(choice, False)

        if free is not None and free < needed_bytes:
            choice = _show_custom_dialog(
                self,
                "空间不足",
                f"所需空间：{FilePoolLayout._format_file_size(needed_bytes)}\n"
                f"可用空间：{FilePoolLayout._format_file_size(free)}\n"
                f"缺少：{FilePoolLayout._format_file_size(needed_bytes - free)}",
                ["重新选择", "取消"],
                ["primary", "normal"],
                dialog_type="danger",
            )
            return "reselect" if choice == 0 else False

        return True

    def _do_export(self, files: list, target_dir: str, mode: int) -> None:
        """执行导出：创建进度对话框并启动复制线程。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。
            mode: 0=平铺, 1=分类。
        """
        # 创建进度对话框
        progress = QProgressDialog("正在导出文件…", "取消", 0, len(files), self)
        progress.setWindowTitle("导出进度")
        progress.setMinimumDuration(0)
        progress.setValue(0)

        # 连接进度信号
        self.update_progress.connect(progress.setValue)

        # 批次间取消标记（现有"取消"按钮 → canceled 信号 → Event → 批次边界响应）
        _cancel_event = threading.Event()
        progress.canceled.connect(lambda: _cancel_event.set())

        def _on_finish(success: int, failed: int, errors: list) -> None:
            try:
                self.update_progress.disconnect(progress.setValue)
            except (TypeError, RuntimeError):
                pass
            try:
                self._export_finished.disconnect(_on_finish)
            except (TypeError, RuntimeError):
                pass
            progress.close()

            if failed == 0:
                _show_custom_dialog(
                    self, "导出完成", f"成功导出 {success} 个文件。",
                    ["确定"], ["primary"], dialog_type="success",
                )
            else:
                detail = "\n".join(errors[:5])
                if len(errors) > 5:
                    detail += f"\n… 及其他 {len(errors) - 5} 个错误"
                _show_custom_dialog(
                    self, "导出结果",
                    f"成功 {success} 个，失败 {failed} 个。\n\n{detail}",
                    ["确定"], ["primary"], dialog_type="danger",
                )

        # 连接完成信号（在主线程处理结果）
        self._export_finished.connect(_on_finish)

        # 投递后台复制任务（线程池 daemon 语义，进程退出自动结束）
        QThreadPool.globalInstance().start(
            _ExportCopyRunnable(
                self, files, target_dir, mode, cancel_event=_cancel_event
            )
        )

        # 显示进度对话框（模态）
        progress.exec()

    def copy_files(
        self,
        files: list,
        target_dir: str,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> tuple:
        """平铺导出：将所有文件直接复制到目标目录。

        native（``faf_copy_files``）可用时按 ≤``_EXPORT_BATCH_SIZE`` 源/批
        批量复制，批次间探测 ``should_stop``；否则回退逐文件
        ``shutil.copy2/copytree``（DLL 缺失/失败时与现状字节一致）。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。
            should_stop: 可选取消回调（批次边界探测；True → 提前终止）。

        Returns:
            (成功数, 失败数, 错误信息列表)
        """
        return self._dispatch_export(
            files, target_dir, mode=0, should_stop=should_stop
        )

    def copy_files_categorized(
        self,
        files: list,
        target_dir: str,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> tuple:
        """分类导出：按原始文件夹分类存放。

        与 :meth:`copy_files` 相同的 native 优先/回退策略；分类目录按
        源文件所在父目录名创建，命名空间按目录隔离（比重命名互不影响）。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。
            should_stop: 可选取消回调（批次边界探测；True → 提前终止）。

        Returns:
            (成功数, 失败数, 错误信息列表)
        """
        return self._dispatch_export(
            files, target_dir, mode=1, should_stop=should_stop
        )

    def _dispatch_export(
        self,
        files: list,
        target_dir: str,
        mode: int,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> tuple:
        """平铺/分类导出统一分发：native 批量优先，回退 Python 复制路径。

        语义保持（与改造前逐文件顺序复制等价）：

        * 处理顺序 = 输入顺序；错误按输入顺序追加（错误元组顺序一致）；
        * 冲突改名（:meth:`_get_unique_target_path`）**保持 Python 侧**，
          dispatch 前完成：native 批量会推迟落盘，故任何无法并入当前批的
          文件（重名冲突、display_name 与源名不一致、取消）都先把当前批
          flush 到磁盘，使 ``_get_unique_target_path`` 总在与旧实现逐文件
          执行相同的时间点看到磁盘状态；
        * 同批内目标名互不相同（同名文件触发 flush + 改名重定向），规避
          native 批内同名目标相互覆盖；
        * 进度信号每个文件递增一次且单调不减（批次 flush 按输入序补发）；
        * 取消按**批次粒度**：``should_stop`` 仅在批次边界（及无法并入
          批量的文件前）探测，<500ms 响应；单文件/目录复制为原子操作、
          不属于批次间取消作用点。

        Args:
            files: 文件信息列表。
            target_dir: 目标目录。
            mode: 0=平铺, 1=分类。
            should_stop: 可选取消回调（True → 在下一个批次边界终止）。

        Returns:
            (成功数, 失败数, 错误信息列表)
        """
        bridge = get_faf_core_bridge()
        native_usable = (
            bridge is not None and bridge.available and bridge._supports_copy
        )
        success = 0
        failed = 0
        errors: list = []
        pending: list = []  # [(输入序号, src, display_name, is_dir)]
        pending_names: set = set()
        pending_dest: Optional[str] = None
        stopped = False

        def _flush() -> None:
            """把当前 native 批落盘：native 结果回填 / native 失败回退逐文件 Python。

            native 单源失败记入 failed 不中断整批；每文件的进度在此按输入序补发。
            """
            nonlocal success, failed, errors, pending_dest
            if not pending:
                return
            dest = pending_dest if pending_dest is not None else target_dir
            result = None
            if native_usable:
                try:
                    result = bridge.copy_files([p[1] for p in pending], dest)
                except Exception:  # noqa: BLE001  # FFI 边界兜底 → 回退 Python
                    warning("native 复制失败，回退 Python 复制路径")
                    result = None
            copied_map = None
            fail_map = None
            if result is not None:
                copied_map = {c.get("src"): True for c in result.get("copied", [])}
                fail_map = {
                    f.get("src"): f.get("error", "复制失败")
                    for f in result.get("failed", [])
                }
            for idx, src, display_name, is_dir in pending:
                error_str: Optional[str] = None
                if result is None:
                    # native 不可用/失败 → 逐文件回退（目标名 = 源名，批内互不相同）。
                    dst = os.path.join(dest, display_name)
                    try:
                        if is_dir:
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, dst)
                    except (IOError, OSError, PermissionError, shutil.Error) as e:
                        error_str = str(e)
                elif src in copied_map:
                    error_str = None
                elif src in fail_map:
                    error_str = fail_map[src]
                else:
                    error_str = "native 未返回该源的复制结果"
                if error_str is None:
                    success += 1
                else:
                    failed += 1
                    errors.append(f"{display_name}: {error_str}")
                self.update_progress.emit(idx + 1)
            pending.clear()
            pending_names.clear()
            pending_dest = None

        try:
            for i, fi in enumerate(files):
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                src = str(fi.get("path", ""))
                display_name = fi.get("display_name", os.path.basename(src))
                if not display_name:
                    display_name = os.path.basename(src) or "?"
                is_dir = bool(fi.get("is_dir"))

                dest_dir = target_dir
                if mode == 1:
                    source_dir = os.path.dirname(src)
                    category = os.path.basename(source_dir) or "未分类"
                    dest_dir = os.path.join(target_dir, category)
                    try:
                        os.makedirs(dest_dir, exist_ok=True)
                    except (IOError, OSError) as e:
                        # 分类目录创建失败：先落盘前序批再按旧逻辑记失败。
                        _flush()
                        failed += 1
                        errors.append(f"{display_name}: 创建分类目录失败 - {e}")
                        self.update_progress.emit(i + 1)
                        continue

                # 命名空间/分类目录切换：先 flush 上一目录的批，保证后续冲突
                # 改名总在与旧实现相同的时间点看到磁盘。
                if pending and pending_dest != dest_dir:
                    _flush()
                    if should_stop is not None and should_stop():
                        stopped = True
                        break

                native_eligible = (
                    native_usable and display_name == os.path.basename(src)
                )
                if native_eligible:
                    if pending_dest == dest_dir and display_name in pending_names:
                        # 同批同名：先落盘让后续改名看到真实磁盘，本文件改走
                        # Python 重命名路径（与逐文件执行语义一致）。
                        _flush()
                        native_eligible = False
                        if should_stop is not None and should_stop():
                            stopped = True
                            break
                    elif len(pending) >= _EXPORT_BATCH_SIZE:
                        _flush()
                        if should_stop is not None and should_stop():
                            stopped = True
                            break

                natural = os.path.join(dest_dir, display_name)
                candidate = self._get_unique_target_path(dest_dir, display_name)
                if native_eligible and candidate == natural:
                    # 冲突改名未触发 → 可并入 native 批（目标名 = 源名）。
                    pending.append((i, src, display_name, is_dir))
                    pending_names.add(display_name)
                    pending_dest = dest_dir
                    continue

                # Python 回退路径（重名冲突/自定义 display_name/目标已存在）：
                # 先 flush 前序批，使改名字段与旧实现所见磁盘一致。
                _flush()
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                try:
                    if is_dir:
                        shutil.copytree(src, candidate, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, candidate)
                    success += 1
                except (IOError, OSError, PermissionError, shutil.Error) as e:
                    failed += 1
                    errors.append(f"{display_name}: {e}")
                self.update_progress.emit(i + 1)
        finally:
            if not stopped:
                _flush()
        return success, failed, errors

    @staticmethod
    def _get_unique_target_path(directory: str, filename: str) -> str:
        """生成目标路径，避免文件名冲突。

        Args:
            directory: 目标目录。
            filename: 文件名。

        Returns:
            唯一的完整目标路径。
        """
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(directory, filename)
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{base}_{counter}{ext}")
            counter += 1
        return candidate

    # ═════════════════════════════════════════════════════════════════════
    #  异步文件夹大小计算（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def _calculate_folder_size(self, folder_path: str) -> None:
        """异步提交文件夹大小计算任务。

        Args:
            folder_path: 待计算的文件夹路径。
        """
        service = StagingPoolService()
        service.initialize()
        service.calculate_folder_size_async(
            folder_path,
            callback=lambda size, fp=folder_path: self._folder_size_ready.emit(fp, size),
        )

    def _on_folder_size_ready_gui(self, folder_path: str, size) -> None:
        """文件夹大小就绪的 GUI 槽（主线程执行，更新 items 与卡片）。

        Args:
            folder_path: 文件夹路径。
            size: 计算出的总字节数，None 表示计算失败/取消。
        """
        if size is None:
            return
        norm_path = os.path.normpath(folder_path)
        updated = False
        for fi in self.items:
            p = fi.get("path")
            if p and os.path.normpath(str(p)) == norm_path:
                fi["size"] = int(size)
                fi["size_calculating"] = False
                updated = True
                break
        if updated:
            # 更新卡片的副标题
            card = self._card_widgets.get(norm_path)
            if card:
                card.set_subtitle(self._build_info_text({**fi, "size": int(size), "size_calculating": False}))
            self.update_stats()
            self._save_backup_if_needed()

    def _on_folder_size_ready(self, folder_path: str, size) -> None:
        """文件夹大小计算完成后的回调（历史入口，转发到 GUI 槽）。

        Args:
            folder_path: 文件夹路径。
            size: 计算出的总字节数。

        Returns:
            无返回值；不得在 worker 线程直接调用触 UI，请经信号触发。
        """
        self._on_folder_size_ready_gui(folder_path, size)

    # ═════════════════════════════════════════════════════════════════════
    #  异步 MD5 计算（Phase 3）
    # ═════════════════════════════════════════════════════════════════════

    def calculate_md5_async(
        self, file_path: str, callback
    ) -> None:
        """异步计算文件 MD5 值。

        复用规范实现 ``staging_tasks.MD5CalculationTask``：后台线程计算，
        回调经 ``HeartbeatManager.request_main_thread`` 回到主线程执行。

        Args:
            file_path: 文件路径。
            callback: 回调函数，接收 MD5 字符串或 None。
        """
        task = MD5CalculationTask(file_path, callback)
        QThreadPool.globalInstance().start(task)
