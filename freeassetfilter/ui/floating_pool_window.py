# -*- coding: utf-8 -*-
"""FloatingPoolWindow — 全局存储池浮窗窗口本体。

无父顶层窗口（``Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint``）：
不进入任务栏，主窗口最小化或被遮挡时仍常驻桌面；``WA_ShowWithoutActivating``
保证显示 / 重建时不会抢走用户当前应用的输入焦点。

本模块已实现窗口骨架（折叠 / 展开两态、主题化圆角自绘背景与拖动定位）、
外部 URL 拖入链路（``dragEnterEvent`` / ``dragMoveEvent`` /
``dragLeaveEvent`` / ``dropEvent`` → ``StagingPoolService.build_file_info``
→ ``add_file_requested`` 信号）、展开内容列表（``set_items`` 防抖重建条目行、
计数标签、空态提示、``StyledScrollArea`` 滚动）、折叠态「点击本体展开 /
拖动移动」的手势仲裁，以及条目行「拖出复制」手势（超阈值启动 ``QDrag``，
携带 ``QUrl.fromLocalFile`` 与自定义判别格式 ``application/x-faf-floating-drag``；
exec 返回后经 :meth:`FloatingPoolWindow._on_drag_finished` 判定落点，
外部落点发 ``remove_file_requested``，自窗 / 宿主窗口及其 owned 对话框落点
视为取消）。拖动松手后（``moveEvent`` 静默 ``SETTLE_DELAY_MS`` 启发式）会先
把超出屏幕的窗口完整夹回可用区、再按 ``SNAP_THRESHOLD`` 对四边贴边吸附，位移
统一经 :meth:`FloatingPoolWindow._animate_move` 的惯性启停缓动完成（可用
``set_snap_enabled`` 关闭吸附，关闭后仍夹回）。配套测试见
``tests/unit/ui/test_floating_pool_window.py``。

Module constants:
    COLLAPSED_SIZE: 折叠态固定尺寸（胶囊形拖放目标）。
    EXPANDED_SIZE: 展开态固定尺寸（高度会按屏幕可用高度钳制）。
    EXPANDED_HEIGHT_RATIO: 展开态高度占屏幕可用高度的比例上限。
    TITLE_BAR_HEIGHT: 展开态标题栏条带高度（拖动热点区）。
    INITIAL_INSET: 初始定位相对屏幕右上角的内缩距离（px）。
    SNAP_THRESHOLD: 松手后外边缘距屏幕可用区对应边 ≤ 该值时吸附（px）。
    SNAP_DURATION_MS: 夹回 / 吸附 / 展开重定位位移动画时长（ms，惯性启停缓动）。
    SETTLE_DELAY_MS: 系统移动循环结束的静默判定窗口（ms，无移动后触发吸附）。
    COLLAPSED_PLACEHOLDER: 折叠态占位文案。
    EMPTY_HINT_TEXT: 展开态空池引导文案。
    COUNT_LABEL_FORMAT: 展开态计数标签格式（``存储池 (N)``）。
    FLOATING_DRAG_MIME: 条目拖出时携带的自定义判别 MIME 格式。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QCloseEvent,
    QCursor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QMoveEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QVBoxLayout,
    QWidget,
)

from components.styled_button import StyledButton
from components.styled_scroll_area import StyledScrollArea
from freeassetfilter.services.staging_pool_service import StagingPoolService
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from freeassetfilter.utils.app_logger import debug
from theme import tm

COLLAPSED_SIZE = QSize(140, 48)
"""QSize: 折叠态固定尺寸。"""

EXPANDED_SIZE = QSize(280, 360)
"""QSize: 展开态固定尺寸（宽度固定，高度受屏幕可用高度钳制）。"""

EXPANDED_HEIGHT_RATIO = 0.7
"""float: 展开态高度上限相对屏幕可用高度的比例。"""

TITLE_BAR_HEIGHT = 32
"""int: 展开态标题栏条带高度，命中该区域即触发窗口拖动。"""

INITIAL_INSET = 16
"""int: 初始定位相对屏幕可用区域右上角的内缩距离（px）。"""

SNAP_THRESHOLD = 24
"""int: 拖动松手后外边缘距屏幕可用区对应边 ≤ 该值时触发吸附（px）。"""

SNAP_DURATION_MS = 220
"""int: 夹回 / 吸附 / 展开重定位位移动画时长（ms，``QEasingCurve.InOutCubic``）。"""

SETTLE_DELAY_MS = 150
"""int: 系统移动循环结束的静默判定窗口（ms，无移动事件后触发吸附）。"""

COLLAPSED_PLACEHOLDER = "拖入文件"
"""str: 折叠态居中显示的占位文案。"""

EMPTY_HINT_TEXT = "拖入文件到浮窗加入存储池"
"""str: 展开态空池时显示的引导文案。"""

COUNT_LABEL_FORMAT = "存储池 ({count})"
"""str: 展开态标题栏计数标签格式。"""

FLOATING_DRAG_MIME = "application/x-faf-floating-drag"
"""str: 条目拖出时随 ``QUrl`` 一并携带的自定义判别 MIME 格式。

主池 ``dropEvent`` 据此识别「浮窗条目拖回」并忽略，避免被当作外部拖入重复入池。
"""

_ROW_HEIGHT = 56
"""int: 展开态单个条目行的固定高度（px，48 图标 + 上下各 4 边距）。"""

_RADIUS = 12
"""int: 自绘圆角背景的圆角半径。"""


class FloatingPoolWindow(QWidget):
    """全局存储池浮窗窗口本体（无父顶层 Tool 置顶窗口）。

    折叠态是一个小的拖放目标胶囊，展开态是固定尺寸的存储池面板。窗口本体
    只负责窗口标志 / 属性、两态几何切换、主题圆角自绘、拖动定位与展开态
    内容列表渲染；池数据拖入 / 拖出由信号桥接到主池。

    Attributes:
        add_file_requested: 拖入有效文件 / 目录后发射，携带
            ``StagingPoolService.build_file_info`` 产出的文件信息字典。
        remove_file_requested: 条目拖出面板且落点为外部（非本应用窗口）时
            发射，负载为被拖出文件的路径字符串（由主窗口接线到主池移除）。
        _expanded: 当前是否处于展开态。
        _content: 展开态内容容器（可见性跟随 ``_expanded``）。
        _count_label: 标题栏计数标签（文本 ``存储池 (N)``）。
        _collapse_button: 标题栏折叠按钮（点击回到折叠态）。
        _scroll_area: 条目列表滚动区（``StyledScrollArea``）。
        _rows_container: 滚动区内容容器。
        _rows_layout: 条目行垂直布局（含空态提示与尾部弹簧）。
        _rows: 当前条目行 widget 列表（``_PoolItemRow``）。
        _empty_hint: 空池引导标签（仅零条目时可见）。
        _debounce_timer: 单次防抖定时器，合并同轮 ``set_items`` 调用。
        _drag_active: 拖出手势是否进行中（防抖回调据此互斥）。
        _pending_items: 待重建的条目列表；``None`` 表示"从未收到更新"或
            "本轮重建已消费"。
        _press_pos: 折叠态左键按下的起点；``None`` 表示无待决的点击手势。
        _drag_source_path: 当前拖出手势的源文件路径（拖拽起点记录，
            ``_on_drag_finished`` 据此发射信号）；非拖拽期间为 ``None``。
        _host_window: 宿主主窗口引用（主窗口构建浮窗后赋值）。
        _snap_enabled: 是否启用贴边吸附（``set_snap_enabled`` 切换）。
        _settle_timer: 单次静默定时器，系统移动结束后触发夹回 / 吸附。
        _move_anim: 在途的 ``QPropertyAnimation``（``pos`` 属性）；无则 None。
        _internal_moving: 程序化移动（动画 / 初始化）期间为 True，抑制静默定时器。
        _theme_conn: ``tm.theme_changed`` 的连接对象（销毁时断开用）。
    """

    add_file_requested = Signal(dict)
    """Signal(dict): 拖入并成功构建文件信息时发射，负载为文件信息字典。"""

    remove_file_requested = Signal(str)
    """Signal(str): 条目拖出且落点为外部时发射，负载为源文件路径。"""

    def __init__(self) -> None:
        """构造浮窗：设置窗口标志 / 属性、构建展开内容、进入折叠态并定位。"""
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)

        self._expanded = False
        self._radius = _RADIUS

        # 延后预声明状态：None 区分"从未收到更新"（防抖）/"无宿主窗口"。
        self._drag_active = False
        self._pending_items: Optional[list] = None
        self._host_window: Optional[QWidget] = None
        self._press_pos: Optional[QPoint] = None
        self._drag_source_path: Optional[str] = None

        # 贴边吸附 / 惯性位移动画状态。
        self._snap_enabled = True
        self._internal_moving = False
        self._move_anim: Optional[QPropertyAnimation] = None

        self._build_content()

        # 持久单次防抖定时器：合并同轮多次 set_items，超时重建条目行。
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._rebuild_list)

        # 单次静默定时器：系统移动循环结束后（无移动事件 SETTLE_DELAY_MS）触发
        # 夹回 / 吸附。程序化移动（初始化 / 动画）期间经 _internal_moving 抑制。
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.timeout.connect(self._settle_and_snap)

        self._internal_moving = True
        self._apply_state_geometry()
        self.move(self._compute_initial_position(self.size()))
        self._internal_moving = False

        # 主题切换实时重绘；连接对象存引用，供生命周期断开。
        self._theme_conn = tm.theme_changed.connect(self.update)

    # ── 展开内容构建 ────────────────────────────────────────────

    def _build_content(self) -> None:
        """构建展开态内容：标题行（计数 + 折叠按钮）+ 滚动条目列表 + 空态提示。

        内容容器 ``self._content`` 覆盖整个窗口，可见性跟随展开态（折叠态
        隐藏以保证折叠占位文案自绘干净）。标题栏条带严格位于顶部
        ``TITLE_BAR_HEIGHT`` 像素内，保证 ``_is_drag_region`` 判定准确。
        """
        self._content = QWidget(self)
        self._content.setAttribute(Qt.WA_TranslucentBackground)

        root_layout = QVBoxLayout(self._content)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 标题行：计数标签（鼠标透传）+ 折叠按钮（标题区唯一消费点击的控件）
        title_row = QWidget(self._content)
        title_row.setFixedHeight(TITLE_BAR_HEIGHT)
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(12, 0, 6, 0)
        title_layout.setSpacing(6)

        self._count_label = QLabel(
            COUNT_LABEL_FORMAT.format(count=0), title_row
        )
        self._count_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        register_widget_qss(
            self._count_label,
            "background: transparent; border: none;",
        )
        title_layout.addWidget(self._count_label)
        title_layout.addStretch(1)

        self._collapse_button = StyledButton(
            "▴",
            variant="ghost",
            size="sm",
            parent=title_row,
        )
        self._collapse_button.setFixedSize(24, 24)
        self._collapse_button.setToolTip("折叠")
        self._collapse_button.clicked.connect(
            lambda: self.set_expanded(False)
        )
        title_layout.addWidget(self._collapse_button)

        root_layout.addWidget(title_row)

        # 滚动条目列表（隐藏原生滚动条，滚动范围仍由 Qt 维护）
        self._scroll_area = StyledScrollArea(self._content)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        register_widget_qss(
            self._scroll_area,
            "background-color: transparent; border: none;",
        )
        self._scroll_area.viewport().setAutoFillBackground(False)
        root_layout.addWidget(self._scroll_area, 1)

        self._rows_container = QWidget()
        self._rows_container.setAttribute(Qt.WA_TranslucentBackground)
        register_widget_qss(
            self._rows_container, "background-color: transparent;"
        )
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(6, 4, 6, 4)
        self._rows_layout.setSpacing(2)
        # widgetResizable 的 QScrollArea 依据容器 minimumSize 计算滚动范围，
        # 而非布局 minimumSizeHint；SetMinAndMaxSize 把容器最小/最大尺寸
        # 绑到布局尺寸，条目溢出时滚动条范围（range）才会 > 0。
        self._rows_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._empty_hint = QLabel(EMPTY_HINT_TEXT, self._rows_container)
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self._empty_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        register_widget_qss(
            self._empty_hint,
            "background: transparent; border: none;",
        )
        # 布局常驻：空态提示 + 尾部弹簧；条目行插入到弹簧之前。
        self._rows_layout.addWidget(self._empty_hint)
        self._rows_layout.addStretch(1)
        self._scroll_area.setWidget(self._rows_container)

        self._rows: list[_PoolItemRow] = []

        self._content.setGeometry(self.rect())
        self._content.setVisible(self._expanded)

    # ── 两态切换 ────────────────────────────────────────────────

    def set_expanded(self, expanded: bool) -> None:
        """切换折叠 / 展开态（尺寸即时 + 位置动画），保持窗口右边缘锚定。

        切换改变的是固定尺寸而非位置：先记录切换前的右边缘，切换尺寸后令右边缘
        回到原位（左边缘随宽度反向推移），使面板向左侧生长而不是越过屏幕右缘。
        锚定得到的左边缘再钳入当前屏幕可用区域（``QApplication.screenAt`` →
        ``availableGeometry``）；无可用屏幕时保留当前位置不动（不抛异常）。
        尺寸经 ``setFixedSize`` 即时生效，位置位移经 :meth:`_animate_move`
        以惯性启停缓动完成（``is_snapping()`` 可探测）。

        Args:
            expanded: True 进入展开态，False 回到折叠态。
        """
        expanded = bool(expanded)
        if expanded == self._expanded:
            self.update()
            return
        self._expanded = expanded
        right_edge = self.x() + self.width()
        self._apply_state_geometry()
        new_x = right_edge - self.width()
        screen = QApplication.screenAt(self.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            new_x = max(
                avail.left(),
                min(new_x, avail.right() - self.width() + 1),
            )
        self._animate_move(QPoint(new_x, self.y()))
        self.update()

    def is_expanded(self) -> bool:
        """返回当前是否处于展开态。

        Returns:
            bool: 展开态返回 True，折叠态返回 False。
        """
        return self._expanded

    def _target_size(self) -> QSize:
        """返回当前状态下应使用的固定尺寸。

        Returns:
            QSize: 折叠态为 ``COLLAPSED_SIZE``，展开态为钳制后的展开尺寸。
        """
        if not self._expanded:
            return COLLAPSED_SIZE
        return self._expanded_size()

    def _expanded_size(self) -> QSize:
        """计算展开态尺寸：高度钳制到屏幕可用高度的 70%。

        ``avail_h`` 取自鼠标所在屏幕（``screenAt``）；``screenAt`` 返回 None
        时回退主屏幕，两者皆不可用时退回 ``EXPANDED_SIZE``。

        Returns:
            QSize: 宽度固定为 ``EXPANDED_SIZE.width()``，高度为
            ``min(EXPANDED_SIZE.height(), int(avail_h * EXPANDED_HEIGHT_RATIO))``。
        """
        screen = QApplication.screenAt(self.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QSize(EXPANDED_SIZE)
        avail_h = screen.availableGeometry().height()
        clamped = min(
            EXPANDED_SIZE.height(),
            int(avail_h * EXPANDED_HEIGHT_RATIO),
        )
        return QSize(EXPANDED_SIZE.width(), clamped)

    def _apply_state_geometry(self) -> None:
        """把当前状态的固定尺寸应用到窗口（``setFixedSize``）。

        同时同步展开内容容器的几何与可见性（折叠态隐藏内容，保证折叠占位
        文案自绘干净）。
        """
        self.setFixedSize(self._target_size())
        content = getattr(self, "_content", None)
        if content is not None:
            content.setGeometry(self.rect())
            content.setVisible(self._expanded)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口尺寸变化时同步展开内容容器几何。

        Args:
            event: 尺寸变化事件（交回基类处理）。
        """
        super().resizeEvent(event)
        content = getattr(self, "_content", None)
        if content is not None:
            content.setGeometry(self.rect())

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭前停止防抖 / 静默定时器与位移动画，避免销毁后残留回调触发。

        Args:
            event: 关闭事件（交回基类处理）。
        """
        self._debounce_timer.stop()
        self._settle_timer.stop()
        self._stop_move_animation()
        super().closeEvent(event)

    def _compute_initial_position(self, size: QSize) -> QPoint:
        """计算初始位置：鼠标所在屏幕可用区域右上角，内缩 ``INITIAL_INSET``。

        Args:
            size: 窗口当前尺寸（用于从右边缘向左推算 x）。

        Returns:
            QPoint: 初始左上角全局坐标；无可用屏幕时退回 ``(0, 0)``。
        """
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QPoint(0, 0)
        avail = screen.availableGeometry()
        x = avail.right() - INITIAL_INSET - size.width()
        y = avail.top() + INITIAL_INSET
        return QPoint(x, y)

    # ── 绘制 ────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """自绘主题化圆角背景 + 1px 边框；折叠态居中绘制占位文案。

        颜色实时取自主题（``tm.surface`` 85% 填充、``tm.mid``/``tm.text`` 30%
        边框），与 ``styled_floating_panel.FloatingPanel.paintEvent`` 同款口径。

        Args:
            event: 绘制事件（未直接使用）。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()

        painter.setPen(Qt.NoPen)
        painter.setBrush(tm.alpha_of(tm.surface, 85))
        painter.drawRoundedRect(
            QRectF(0, 0, width, height), self._radius, self._radius
        )

        painter.setPen(
            QPen(
                tm.alpha_of(tm.mid if tm.is_dark_theme() else tm.text, 30),
                1,
            )
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, width - 1, height - 1),
            self._radius,
            self._radius,
        )

        if self.property("dragActive"):
            painter.setPen(QPen(tm.accent, 2))
            painter.drawRoundedRect(
                QRectF(1, 1, width - 2, height - 2),
                self._radius,
                self._radius,
            )

        if not self._expanded:
            painter.setPen(tm.text)
            painter.drawText(
                QRectF(0, 0, width, height),
                Qt.AlignCenter,
                COLLAPSED_PLACEHOLDER,
            )

        painter.end()

    # ── 外部拖入 ────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """外部 URL 拖入窗口时接受并点亮拖放高亮。

        折叠 / 展开两态一律接受；``mimeData().hasUrls()`` 之外的内容
        （纯文本等）交回基类处理。

        Args:
            event: 拖入事件。
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_highlight(True)
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """拖拽移动中持续接受 URL 拖入。

        展开态 drop 落在条目行或背景上不作区分，统一入池。

        Args:
            event: 拖拽移动事件。
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """拖拽离开窗口时清除拖放高亮。

        Args:
            event: 拖拽离开事件。
        """
        self._set_drag_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """处理外部 URL 放下：逐个构建文件信息并发射 ``add_file_requested``。

        依次遍历 ``mimeData().urls()``：``toLocalFile()`` 为空、路径不存在、
        同一事件内重复或 ``build_file_info`` 返回 ``None`` 的条目一律跳过。
        处理完全部 URL 后清除高亮；若有条目成功发射且当前为折叠态，则自动
        展开窗口。本方法**只发射信号**，不触碰主池数据源。

        Args:
            event: 拖放事件。
        """
        mime = event.mimeData()
        emitted = 0
        if mime.hasUrls():
            emitted = self._emit_dropped_urls(mime.urls())
            event.acceptProposedAction()
        self._set_drag_highlight(False)
        if emitted and not self.is_expanded():
            self.set_expanded(True)

    def _emit_dropped_urls(self, urls: list[QUrl]) -> int:
        """遍历 URL 列表，构建文件信息并逐条发射信号。

        Args:
            urls: ``QMimeData.urls()`` 返回的 URL 列表。

        Returns:
            int: 实际发射 ``add_file_requested`` 的次数。
        """
        seen: set[str] = set()
        emitted = 0
        for url in urls:
            file_path = url.toLocalFile()
            if not file_path or file_path in seen:
                continue
            seen.add(file_path)
            if not os.path.exists(file_path):
                continue
            file_info = StagingPoolService.build_file_info(file_path)
            if file_info is None:
                continue
            self.add_file_requested.emit(file_info)
            emitted += 1
        return emitted

    def _set_drag_highlight(self, active: bool) -> None:
        """切换拖放高亮的 ``dragActive`` 动态属性并请求重绘。

        本窗口为手动自绘（非 QSS 样式控件），故只置属性 + ``update()``，
        不走 ``unpolish`` / ``polish``。

        Args:
            active: True 点亮高亮，False 清除。
        """
        active = bool(active)
        if bool(self.property("dragActive")) == active:
            return
        self.setProperty("dragActive", active)
        self.update()

    # ── 展开内容列表 ────────────────────────────────────────────

    def set_items(self, items: list[dict]) -> None:
        """暂存条目列表并启动单次防抖定时器。

        同轮多次调用（如恢复批同步发射 ``pool_changed``）合并为一次重建：
        本方法只写 ``self._pending_items`` 并 ``start(0)``，真正的重建发生在
        :meth:`_rebuild_list` 超时回调中。

        Args:
            items: 文件信息字典列表（来自主池 ``FilePoolLayout.items``）。
        """
        self._pending_items = list(items)
        self._debounce_timer.start(0)

    def _rebuild_list(self) -> None:
        """防抖超时回调：从 ``self._pending_items`` 全量重建条目行。

        拖出手势进行中（``self._drag_active``）时直接返回，**不**重新武装
        定时器（重启由拖出手势处理器 finally 负责）。重建为「清空 + 重加」
        而非追加；完成后把 ``self._pending_items`` 复位为 ``None``。
        """
        if self._drag_active:
            return
        items = self._pending_items or []
        self._clear_rows()

        index = self._rows_layout.count() - 1  # 尾部弹簧之前
        valid = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path:
                continue
            row = _PoolItemRow(item, self._rows_container)
            self._rows_layout.insertWidget(index, row)
            index += 1
            self._rows.append(row)
            valid += 1

        self._count_label.setText(COUNT_LABEL_FORMAT.format(count=valid))
        self._empty_hint.setVisible(valid == 0)
        self._pending_items = None

    def _clear_rows(self) -> None:
        """移除并延迟销毁当前全部条目行（重建前清场，绝不追加）。"""
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

    # ── 拖出复制 ────────────────────────────────────────────────

    def _run_drag(self, drag: QDrag) -> Qt.DropAction:
        """``QDrag.exec`` 的薄封装 seam（供测试 monkeypatch，便于单测）。

        Args:
            drag: 已装配 MIME 数据的拖拽对象。

        Returns:
            Qt.DropAction: 拖拽模态循环结束后目标返回的动作。
        """
        return drag.exec(Qt.CopyAction | Qt.MoveAction)

    def _start_item_drag(self, path: str) -> None:
        """条目行拖出：装配 MIME、跑模态拖拽、结束后判定落点。

        MIME 同时携带 ``QUrl.fromLocalFile(path)`` 与自定义判别格式
        ``FLOATING_DRAG_MIME``（与主池 dropEvent 同串）。
        ``_drag_active`` 在整个 ``_run_drag`` 期间为 True（防抖回调据此互斥），
        在 ``finally`` 中复位；若拖拽期间收到 ``set_items`` 更新
        （``_pending_items`` 非 None）则在结束一拍后重启防抖定时器。

        Args:
            path: 被拖出的源文件路径。
        """
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        mime.setData(FLOATING_DRAG_MIME, b"1")
        drag = QDrag(self)
        drag.setMimeData(mime)

        self._drag_source_path = path
        self._drag_active = True
        try:
            action = self._run_drag(drag)
        finally:
            self._drag_active = False
            if self._pending_items is not None:
                self._debounce_timer.start(0)
        self._on_drag_finished(action)

    def _on_drag_finished(
        self,
        action: Qt.DropAction,
        *,
        window_at: Callable[[QPoint], Optional[QWidget]] = QApplication.widgetAt,
        cursor_pos: Callable[[], QPoint] = QCursor.pos,
    ) -> None:
        """拖拽结束后判定落点，外部落点发射 ``remove_file_requested``。

        ``action == Qt.IgnoreAction``（目标拒绝）直接返回；否则取光标下控件，
        ``None``（非 Qt 窗口，如资源管理器 / 桌面）→ 发射；命中本浮窗自身或
        宿主主窗口及其 owned 对话框（经 ``parentWidget()`` 祖先链归并）
        → 视为取消，不发射；其余无关控件 → 发射。

        Args:
            action: ``QDrag.exec`` 返回的落点动作。
            window_at: 全局坐标 → 落点控件（默认 ``QApplication.widgetAt``，
                可注入 stub）。
            cursor_pos: 当前光标全局坐标（默认 ``QCursor.pos``，可注入 stub）。
        """
        if action == Qt.IgnoreAction:
            return
        path = self._drag_source_path
        target = window_at(cursor_pos())
        if target is None:
            if path is not None:
                self.remove_file_requested.emit(path)
            return
        top: Optional[QWidget] = target.window()
        while top is not None:
            if top is self or top is self._host_window:
                return
            top = top.parentWidget()
        if path is not None:
            self.remove_file_requested.emit(path)

    # ── 拖动定位 ────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """可拖动区左键按下：展开态立即移动，折叠态记录起点待定。

        展开态标题栏按下即 ``_start_system_move()``；折叠态
        按下只记录起点，是否移动 / 展开延后到移动 / 释放事件仲裁。

        Args:
            event: 鼠标事件。
        """
        if event.button() == Qt.LeftButton and self._is_drag_region(
            event.position().toPoint()
        ):
            if self._expanded:
                self._start_system_move()
            else:
                self._press_pos = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """折叠态待决手势：位移超过拖动阈值后转为窗口移动。

        先清 ``_press_pos`` 再触发移动，确保随后的释放不再展开窗口。

        Args:
            event: 鼠标事件。
        """
        if self._press_pos is not None and (event.buttons() & Qt.LeftButton):
            delta = (
                event.position().toPoint() - self._press_pos
            ).manhattanLength()
            if delta > QApplication.startDragDistance():
                self._press_pos = None
                self._start_system_move()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """折叠态待决手势：未超阈值释放则展开窗口。

        Args:
            event: 鼠标事件。
        """
        if self._press_pos is not None and event.button() == Qt.LeftButton:
            self._press_pos = None
            self.set_expanded(True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _is_drag_region(self, pos: QPoint) -> bool:
        """判断窗口本地坐标是否位于可拖动区域。

        Args:
            pos: 窗口本地坐标点。

        Returns:
            bool: 折叠态整块为拖动区；展开态仅顶部标题栏条带
            （``0 <= y < TITLE_BAR_HEIGHT``）为拖动区。
        """
        if not self._expanded:
            return True
        return 0 <= pos.y() < TITLE_BAR_HEIGHT

    def _start_system_move(self) -> None:
        """停止在途位移动画后调用 ``windowHandle().startSystemMove()``。

        动画在途时先经 :meth:`_stop_move_animation` 停掉，把位置控制权交还系统
        移动循环；窗口句柄尚未建立（``windowHandle()`` 为 None）时静默跳过。
        """
        self._stop_move_animation()
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    # ── 贴边吸附 / 惯性位移动画 ───────────────────────────────────

    def set_snap_enabled(self, enabled: bool) -> None:
        """开关贴边吸附（关闭后仍会把窗口完整夹回屏内）。

        Args:
            enabled: True 启用四边吸附，False 仅夹回不吸附。
        """
        self._snap_enabled = bool(enabled)

    def is_snap_enabled(self) -> bool:
        """返回当前是否启用贴边吸附。

        Returns:
            bool: 启用返回 True，禁用返回 False。
        """
        return self._snap_enabled

    def is_snapping(self) -> bool:
        """返回是否有位移动画（夹回 / 吸附 / 展开重定位）在途。

        Returns:
            bool: 动画运行中返回 True，否则 False。
        """
        anim = self._move_anim
        return (
            anim is not None
            and anim.state() == QAbstractAnimation.State.Running
        )

    def moveEvent(self, event: QMoveEvent) -> None:
        """窗口移动后重启静默定时器（程序化移动期间抑制）。

        系统移动循环（``startSystemMove``）不投递 ``mouseReleaseEvent``，故以
        「距上次移动静默 ``SETTLE_DELAY_MS``」作为松手启发式：超时回调
        :meth:`_settle_and_snap` 完成夹回 / 吸附。``_internal_moving`` 为 True
        （动画 / 初始化等程序化移动）时不重启，避免自触发循环。

        Args:
            event: 移动事件（交回基类处理）。
        """
        super().moveEvent(event)
        if self._internal_moving:
            return
        self._settle_timer.start(SETTLE_DELAY_MS)

    def _settle_and_snap(self) -> None:
        """移动静默结束后：先完整夹回屏内，再按阈值四边吸附，最后动画位移。

        取窗口几何中心所在屏幕（``screenAt`` → ``primaryScreen`` 回退）的
        ``availableGeometry()``；无可用屏幕时静默返回。夹回保证窗口四边都落在
        可用区内；吸附仅在 :meth:`is_snap_enabled` 为 True 时对左 / 右 / 上 /
        下四条边分别判定（外边缘距对应边 ≤ ``SNAP_THRESHOLD`` 时吸到
        ``INITIAL_INSET`` 留白处）。目标位置经 :meth:`_animate_move` 缓动移动；
        目标与当前位置相同时不产生动画。``_internal_moving`` 为 True 时早退。
        """
        if self._internal_moving:
            return
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        width = self.width()
        height = self.height()

        # 1) 先完整夹回可用区（右 / 下用包含式边界 avail.right()/bottom()）。
        x = max(avail.left(), min(self.x(), avail.right() - width + 1))
        y = max(avail.top(), min(self.y(), avail.bottom() - height + 1))

        # 2) 再按阈值吸附四条边（左 / 上吸到 left/top + INSET，
        #    右 / 下使右 / 下缘落在 right/bottom - INSET）。
        if self._snap_enabled:
            if x - avail.left() <= SNAP_THRESHOLD:
                x = avail.left() + INITIAL_INSET
            elif avail.right() - (x + width - 1) <= SNAP_THRESHOLD:
                x = avail.right() - INITIAL_INSET - width + 1
            if y - avail.top() <= SNAP_THRESHOLD:
                y = avail.top() + INITIAL_INSET
            elif avail.bottom() - (y + height - 1) <= SNAP_THRESHOLD:
                y = avail.bottom() - INITIAL_INSET - height + 1

        self._animate_move(QPoint(x, y))

    def _animate_move(self, target: QPoint) -> None:
        """以惯性启停缓动把窗口移动到 ``target``（尺寸不变）。

        ``QPropertyAnimation(self, b"pos")``，时长 ``SNAP_DURATION_MS``，
        缓动 ``QEasingCurve.InOutCubic``。启动前清静默定时器并停掉在途动画；
        动画期间 ``_internal_moving`` 为 True（``moveEvent`` 不再重启静默定时器），
        结束后复位。目标与当前位置相同时直接返回（不产生动画）。

        Args:
            target: 目标左上角全局坐标。
        """
        if target == self.pos():
            return
        self._settle_timer.stop()
        self._stop_move_animation()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(SNAP_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setStartValue(self.pos())
        anim.setEndValue(target)
        anim.finished.connect(self._on_move_animation_finished)
        self._move_anim = anim
        self._internal_moving = True
        anim.start()

    def _on_move_animation_finished(self) -> None:
        """位移动画自然结束回调：复位程序化移动标志。"""
        self._internal_moving = False

    def _stop_move_animation(self) -> None:
        """停止并销毁在途位移动画，复位程序化移动标志。

        ``QAbstractAnimation.stop()`` 不发射 ``finished``，故标志须手工复位。
        """
        anim = self._move_anim
        self._move_anim = None
        if anim is not None:
            try:
                anim.stop()
            except RuntimeError:
                pass
            anim.deleteLater()
        self._internal_moving = False


class _PoolItemRow(QWidget):
    """浮窗展开列表中的单个条目行（图标 + 显示名 + 大小副标题）。

    仅承载展示信息，**无**点击 / 右键语义；实现「拖出复制」手势——左键按下
    记录起点，位移超过 ``QApplication.startDragDistance()`` 后委托给窗口
    （``self.window()``，``isinstance`` 守卫）启动 ``QDrag``。共享拖拽状态
    （``_drag_active`` / ``_pending_items`` / ``_debounce_timer``）留在窗口，
    故本行只做阈值检测与委托。

    Attributes:
        file_info: 原始文件信息字典（引用，拖出手势复用）。
        path: 文件路径字符串（空路径条目不会构造本行）。
        _press_pos: 左键按下的行本地起点；``None`` 表示无待决拖出手势。
    """

    def __init__(
        self, file_info: dict, parent: Optional[QWidget] = None
    ) -> None:
        """构造条目行。

        Args:
            file_info: 文件信息字典（须含非空 ``path``）。
            parent: 父控件（通常为 ``_rows_container``）。
        """
        super().__init__(parent)
        self.file_info = file_info
        self.path = str(file_info.get("path") or "")
        self._press_pos: Optional[QPoint] = None
        self.setFixedHeight(_ROW_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(48, 48)
        self._icon_label.setAlignment(Qt.AlignCenter)
        pixmap = self._load_icon()
        if pixmap is not None and not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        layout.addWidget(self._icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)

        self._name_label = QLabel(self._display_name(), self)
        register_widget_qss(
            self._name_label, "background: transparent; border: none;"
        )
        text_layout.addWidget(self._name_label)

        self._size_label = QLabel(
            StagingPoolService.format_file_size(file_info.get("size")), self
        )
        register_widget_qss(
            self._size_label, "background: transparent; border: none;"
        )
        if not self._size_label.text():
            self._size_label.hide()
        text_layout.addWidget(self._size_label)

        layout.addLayout(text_layout, 1)

    def _display_name(self) -> str:
        """返回条目显示名：``display_name`` → ``name`` → 路径 basename。

        Returns:
            str: 非空显示名。
        """
        name = (
            self.file_info.get("display_name")
            or self.file_info.get("name")
            or os.path.basename(self.path)
        )
        return str(name)

    def _load_icon(self) -> Optional[QPixmap]:
        """加载条目图标（与主池卡片同管线的 ``FileIconManager``）。

        图标生成失败（异常 / 空 pixmap）时回退为无图标，绝不抛出以保护
        条目重建流程。

        Returns:
            Optional[QPixmap]: 图标；路径为空或生成失败时返回 ``None``。
        """
        try:
            if not self.path:
                return None
            from freeassetfilter.services.file_icon_manager import (
                FileIconManager,
            )

            dpr = float(self.devicePixelRatioF())
            if dpr <= 0:
                dpr = 1.0
            pixmap = FileIconManager().get_icon_pixmap(
                self.file_info, 48, dpr
            )
            if pixmap is not None and not pixmap.isNull():
                return pixmap
        except Exception as exc:
            debug(f"浮窗条目图标生成失败（回退占位）：{exc}")
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键按下记录拖出起点；其余按钮交回基类。

        Args:
            event: 鼠标事件。
        """
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """按住左键移动超阈值 → 委托窗口启动拖出。

        先清 ``_press_pos`` 再委托，确保同一次手势只启动一次拖拽。

        Args:
            event: 鼠标事件。
        """
        if self._press_pos is not None and (event.buttons() & Qt.LeftButton):
            moved = (
                event.position().toPoint() - self._press_pos
            ).manhattanLength()
            if moved > QApplication.startDragDistance():
                self._press_pos = None
                window = self.window()
                if isinstance(window, FloatingPoolWindow):
                    window._start_item_drag(self.path)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """释放清空拖出起点，交回基类。

        Args:
            event: 鼠标事件。
        """
        self._press_pos = None
        super().mouseReleaseEvent(event)
