# -*- coding: utf-8 -*-
"""FloatingPoolWindow — 全局存储池浮窗窗口本体。

无父顶层窗口（``Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint``）：
不进入任务栏，主窗口最小化或被遮挡时仍常驻桌面；``WA_ShowWithoutActivating``
保证显示 / 重建时不会抢走用户当前应用的输入焦点。

视觉与动效
----------
窗口是一个 **透明画布**，真正被看到的是 ``paintEvent`` 里按状态绘制的一张
「卡片」：窗口几何负责命中区域与布局，卡片几何负责观感，两者解耦后几何
切换可以在测试可断言的同步语义下仍然播放形变动画。

* **入场 / 出场（Appear / Disappear）**：首次上屏与程序退出时，卡片以
  「整体缩放（``0.92 ↔ 1.0``）+ 透明度（``0 ↔ 1``）」的非线性缓动淡入淡出，
  不再硬切入 / 硬消失；退出时若面板展开先收回圆形再淡出（避免内容与卡片
  错位）。启动 5s / 退出 3s 双预算兜底：超时直接无动画显示或立即关闭，
  绝不因一个小浮窗拖累主程序。
* **位置记忆（Position Memory）**：关闭 / 退出时把**折叠态**左上角与屏幕
  环境指纹（主屏、每屏名称 / 显示器矩形 / 可用区 / DPI）写入 V2 设置
  （``app.floating_pool_position``）；下次启动仅在指纹完全一致时原位恢复，
  显示器、分辨率、任务栏位置或缩放发生变化时一律回默认位置。
* **圆形入口（折叠态）**：卡片是正方形，圆角半径恒等于高度的一半 → 完美
  圆形；悬停时描边泛出主题色微光并轻微放大，配合计数徽标显示池内条目数。
* **就近边缘锚定（Edge Anchoring）**：展开、收拢、拖入拉伸三类形态变化
  都先按「浮窗距工作区哪侧更近」重新选定固定边（水平、垂直各自独立判定；
  两侧相等时回退右 + 上），固定边不动、内容向屏幕内侧生长，使展开的面板
  与胶囊始终完整落在屏幕内；收拢也按当前位置重算，圆形总是缩到当前更
  贴近的那一侧，且形变方向与几何落点同源（无位置跳变）。
* **拖入胶囊（Drag-over）**：外部 URL 拖入后窗口横向拉伸（固定边不动、向
  屏幕内侧生长）成胶囊，卡片圆角仍是高度的一半，因此形变永远是「圆 → 胶囊」的
  连续过渡；提示文案随拉伸进度淡入。
* **成功回弹（Drop Success）**：接收成功后卡片按关键帧做
  ``1.00 → 0.90 → 1.10 → 0.975 → 1.02 → 1.00`` 的弹性缩放（squish &
  bounce），随后与展开动画叠加，形成「接住并摊开」的观感。
* **展开面板（Click-to-Expand）**：点击圆形入口后，卡片从锚定角的圆形
  向外扩散成圆角矩形（``morphProgress`` 0→1，``QEasingCurve.OutQuart``），
  内容容器同步 mask 到卡片区域，实现「逐步揭示」；收拢时反向播放，动画
  结束才落定窗口尺寸（圆形恰好落在原位，几何跳变不可见）。形变缓动到
  终值即结束，**不叠加缩放回弹**（越过终态尺寸的弹性抖动已按实测反馈移除）。

所有动画都是 ``QPropertyAnimation`` 驱动本类的 Qt Property（``morphProgress``
/ ``dragProgress`` / ``hoverProgress`` / ``pulseScale``），帧内只做绘制与
一次 ``setFixedSize``，不阻塞事件循环。

本模块实现窗口骨架（折叠 / 展开两态、主题化圆角自绘背景与拖动定位）、
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
    COLLAPSED_SIZE: 折叠态窗口尺寸（正方形 → 绘制出的卡片为完美圆形）。
    DRAG_HOVER_SIZE: 拖入悬停态窗口尺寸（横向拉伸后的胶囊）。
    EXPANDED_SIZE: 展开态固定尺寸（高度会按屏幕可用高度钳制）。
    EXPANDED_HEIGHT_RATIO: 展开态高度占屏幕可用高度的比例上限。
    TITLE_BAR_HEIGHT: 展开态标题栏条带高度（拖动热点区）。
    INITIAL_INSET: 初始定位相对屏幕右上角的内缩距离（px）。
    SNAP_THRESHOLD: 松手后外边缘距屏幕可用区对应边 ≤ 该值时吸附（px）。
    SNAP_DURATION_MS: 夹回 / 吸附位移动画时长（ms，惯性启停缓动）。
    SETTLE_DELAY_MS: 系统移动循环结束的静默判定窗口（ms，无移动后触发吸附）。
    MORPH_DURATION_MS: 圆形 → 面板的展开形变时长（ms）。
    COLLAPSE_DURATION_MS: 面板 → 圆形的收拢形变时长（ms）。
    DRAG_STRETCH_DURATION_MS: 圆形 → 胶囊的横向拉伸时长（ms）。
    HOVER_DURATION_MS: 悬停微光过渡时长（ms）。
    SUCCESS_BOUNCE_MS: 成功接收回弹动画时长（ms）。
    ENTRANCE_DURATION_MS: 首次入场（整体缩放 + 透明度）动画时长（ms）。
    EXIT_DURATION_MS: 出场（整体缩放 + 透明度）动画时长（ms）。
    ENTRANCE_SCALE_FROM / EXIT_SCALE_TO: 入场起始 / 出场终止绘制缩放。
    ENTRANCE_BUDGET_MS: 启动兜底预算（自构造起超时则直接显示，不播动画）。
    EXIT_BUDGET_MS: 退出兜底预算（超时直接关闭，绝不拖累主程序退出）。
    DRAG_HINT_TEXT: 拖入悬停态主提示文案。
    EMPTY_HINT_TEXT: 展开态空池引导文案。
    COUNT_LABEL_FORMAT: 展开态计数标签格式（``存储池 (N)``）。
    FLOATING_DRAG_MIME: 条目拖出时携带的自定义判别 MIME 格式。
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional, Sequence

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEventLoop,
    QMimeData,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    Property,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QContextMenuEvent,
    QCursor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QMouseEvent,
    QMoveEvent,
    QPaintEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
    QResizeEvent,
    QScreen,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from components.styled_icon_button import StyledIconButton
from components.styled_scroll_area import StyledScrollArea
from freeassetfilter.services.staging_pool_service import StagingPoolService
from freeassetfilter.ui.components.icon_utils import render_icon
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu
from freeassetfilter.ui.elevated_drop import ElevatedDropFallbackMixin
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from freeassetfilter.utils.app_logger import debug, info, warning
from freeassetfilter.utils.screen_utils import screen_work_area
from theme import tm

COLLAPSED_SIZE = QSize(64, 64)
"""QSize: 折叠态窗口尺寸（正方形，绘制出的卡片为完美圆形）。"""

DRAG_HOVER_SIZE = QSize(212, 64)
"""QSize: 拖入悬停态窗口尺寸（固定边不动，向屏幕内侧拉伸成胶囊）。"""

EXPANDED_SIZE = QSize(296, 384)
"""QSize: 展开态固定尺寸（宽度固定，高度受屏幕可用高度钳制）。"""

EXPANDED_HEIGHT_RATIO = 0.7
"""float: 展开态高度上限相对屏幕可用高度的比例。"""

TITLE_BAR_HEIGHT = 40
"""int: 展开态标题栏条带高度，命中该区域即触发窗口拖动。"""

INITIAL_INSET = 16
"""int: 初始定位相对屏幕可用区域右上角的内缩距离（px）。"""

SNAP_THRESHOLD = 24
"""int: 拖动松手后外边缘距屏幕可用区对应边 ≤ 该值时触发吸附（px）。"""

SNAP_DURATION_MS = 220
"""int: 夹回 / 吸附 / 展开重定位位移动画时长（ms，``QEasingCurve.InOutCubic``）。"""

SETTLE_DELAY_MS = 150
"""int: 系统移动循环结束的静默判定窗口（ms，无移动事件后触发吸附）。"""

MORPH_DURATION_MS = 320
"""int: 圆形 → 展开面板的形变时长（ms，``QEasingCurve.OutQuart``）。"""

COLLAPSE_DURATION_MS = 200
"""int: 展开面板 → 圆形的收拢时长（ms，``QEasingCurve.InCubic``）。"""

DRAG_STRETCH_DURATION_MS = 240
"""int: 拖入时圆形 → 胶囊的横向拉伸时长（ms）。"""

HOVER_DURATION_MS = 160
"""int: 悬停微光 / 轻微放大的过渡时长（ms）。"""

SUCCESS_BOUNCE_MS = 520
"""int: 成功接收的 squish & bounce 关键帧动画时长（ms）。"""

ENTRANCE_DURATION_MS = 240
"""int: 首次入场（整体缩放 + 透明度）动画时长（ms，``OutQuart`` / ``OutCubic``）。"""

EXIT_DURATION_MS = 200
"""int: 出场（整体缩放 + 透明度）动画时长（ms，``InCubic``）。"""

ENTRANCE_SCALE_FROM = 0.92
"""float: 入场起始绘制缩放（终态为 1.0）。"""

EXIT_SCALE_TO = 0.92
"""float: 出场终止绘制缩放。"""

ENTRANCE_BUDGET_MS = 5000
"""int: 启动兜底预算——自浮窗构造起超过该时长仍未走完入场，直接无动画显示。"""

EXIT_BUDGET_MS = 3000
"""int: 退出兜底预算——出场动画超时仍未结束，直接关闭（绝不拖累主程序退出）。"""

COLLAPSED_PLACEHOLDER = "拖入文件"
"""str: 折叠态占位文案（保留常量用于兼容，现由自绘图标替代显示）。"""

DRAG_HINT_TEXT = "拖拽文件到此处"
"""str: 拖入悬停态的主提示文案。"""

DRAG_HINT_SUB_TEXT = "松开即加入存储池"
"""str: 拖入悬停态的辅助提示文案。"""

EMPTY_HINT_TEXT = "拖入文件到浮窗加入存储池"
"""str: 展开态空池时显示的引导文案。"""

EMPTY_HINT_SUB_TEXT = "支持拖入多个文件或文件夹"
"""str: 展开态空池时的辅助说明。"""

COUNT_LABEL_FORMAT = "存储池 ({count})"
"""str: 展开态标题栏计数标签格式。"""

FLOATING_DRAG_MIME = "application/x-faf-floating-drag"
"""str: 条目拖出时随 ``QUrl`` 一并携带的自定义判别 MIME 格式。

主池 ``dropEvent`` 据此识别「浮窗条目拖回」并忽略，避免被当作外部拖入重复入池。
"""

_ROW_HEIGHT = 56
"""int: 展开态单个条目行的固定高度（px，48 图标 + 上下各 4 边距）。"""

_TITLE_ROW_HEIGHT = 32
"""int: 展开态标题行高度（px）。"""

_TITLE_DOT_SPACE = 14
"""int: 标题标签左侧留给强调色圆点的内边距（px）。"""

_ROW_RADIUS = 8
"""int: 条目行卡片的圆角半径。"""

_CARD_MARGIN = 4
"""int: 卡片相对窗口边界的留白（px），用于绘制外发光与回弹缩放余量。"""

_PANEL_RADIUS = 14
"""int: 展开面板卡片的圆角半径。"""

_SCROLL_BAR_WIDTH = 4
"""int: 竖向滚动条滑块常态宽度（px，命中宽度由 ``sizeHint()`` 的 8px 提供）。"""

_SCROLL_BAR_HOVER_WIDTH = 6
"""int: 竖向滚动条滑块悬停 / 拖动时的宽度（px）。"""

_FONT_CACHE: dict = {}
"""dict: ``(像素尺寸, 字重)`` → ``QFont`` 缓存（绘制路径避免逐帧构造）。"""

_POSITION_KEY = "app.floating_pool_position"
"""str: V2 设置里保存浮窗位置与环境指纹的点号键。

值形如 ``{"x": int, "y": int, "env": [主屏名, [[屏幕名, 显示器矩形, 可用区,
DPI], ...]]}``。只存**折叠态（圆形）左上角**，并在屏幕环境指纹不一致时
直接忽略（回默认位置），避免跨分辨率 / DPI / 任务栏布局错位。
"""


def _screen_env_signature() -> list:
    """返回屏幕环境指纹（影响坐标映射的一切因素）。

    包含：主屏名、每块屏幕的名称 / 显示器矩形 / 真实可用区（已扣除任务栏）
    与设备像素比，按屏幕名排序（屏顺序不稳定）。任一项变化（插拔显示器、
    改分辨率、移任务栏、改缩放）都会使上次保存的位置失效。

    Returns:
        list: 可直接 JSON 序列化的指纹（主屏名 + 屏条目列表）。
    """
    app = QApplication.instance()
    if app is None:
        return ["", []]
    primary = app.primaryScreen()
    entries: list = []
    for screen in app.screens():
        geometry = screen.geometry()
        work = screen_work_area(screen)
        entries.append(
            [
                str(screen.name()),
                geometry.x(),
                geometry.y(),
                geometry.width(),
                geometry.height(),
                work.x(),
                work.y(),
                work.width(),
                work.height(),
                round(float(screen.devicePixelRatio()), 3),
            ]
        )
    entries.sort()
    return [primary.name() if primary is not None else "", entries]


def _position_settings() -> Any:
    """返回用于读写位置的 V2 设置管理器。

    优先复用应用级实例（``app.settings_manager``，启动时已加载）；无则新建
    （``save()`` 只合并脏键，多实例并发写盘不会丢其它写入方的新值）。

    Returns:
        SettingsManagerV2: V2 设置管理器实例。
    """
    app = QApplication.instance()
    manager = getattr(app, "settings_manager", None) if app is not None else None
    if manager is not None:
        return manager
    from freeassetfilter.core.managers.settings_manager_v2 import SettingsManagerV2

    return SettingsManagerV2()


def _load_persisted_position() -> Optional[dict]:
    """读取上次退出时保存的浮窗位置（失败一律当作无记录）。

    Returns:
        dict | None: ``{"x", "y", "env"}``；无记录 / 读取失败为 None。
    """
    try:
        value = _position_settings().get(_POSITION_KEY, None)
    except Exception as exc:  # noqa: BLE001 - 位置恢复失败不得阻断建窗
        debug(f"[floating_pool] 读取保存位置失败：{exc}")
        return None
    return value if isinstance(value, dict) else None


def _save_persisted_position(payload: dict) -> None:
    """把浮窗位置与环境指纹写入 V2 设置并立即落盘。

    Args:
        payload: ``{"x", "y", "env"}``（必须可 JSON 序列化）。
    """
    try:
        manager = _position_settings()
        manager.set(_POSITION_KEY, payload)
        manager.save()
    except Exception as exc:  # noqa: BLE001 - 退出路径不得因持久化抛错
        warning(f"[floating_pool] 保存位置失败：{exc}")


def _ui_font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """返回按像素尺寸缓存的界面字体。

    Args:
        pixel_size: 字号（逻辑像素，随 DPI 自动缩放）。
        weight: 字重枚举。

    Returns:
        QFont: 共享字体对象（调用方不得修改）。
    """
    key = (int(pixel_size), int(weight))
    font = _FONT_CACHE.get(key)
    if font is None:
        font = QFont(QApplication.font())
        font.setPixelSize(int(pixel_size))
        font.setWeight(weight)
        _FONT_CACHE[key] = font
    return font


class FloatingPoolWindow(ElevatedDropFallbackMixin, QWidget):
    """全局存储池浮窗窗口本体（无父顶层 Tool 置顶窗口）。

    折叠态是一个圆形拖放入口，拖入时横向拉伸为胶囊，展开态是固定尺寸的
    存储池面板。窗口本体只负责窗口标志 / 属性、两态几何切换、主题化卡片
    自绘、动效编排、拖动定位与展开态内容列表渲染；池数据拖入 / 拖出由信号
    桥接到主池。

    Attributes:
        add_file_requested: 拖入有效文件 / 目录后发射，携带
            ``StagingPoolService.build_file_info`` 产出的文件信息字典。
        remove_file_requested: 条目拖出面板且落点为外部（非本应用窗口）时
            发射，负载为被拖出文件的路径字符串（由主窗口接线到主池移除）。
        _expanded: 当前是否处于展开态（状态语义，立即翻转）。
        _visual_expanded: 绘制语义上的展开态（收拢动画期间仍为 True）。
        _morph: 圆形 ↔ 面板的形变进度（0 = 圆形，1 = 面板）。
        _anchor_right: 展开 / 拉伸是否以右缘为固定边（False = 左缘固定）
        _anchor_bottom: 展开是否以下缘为固定边（False = 上缘固定）
        _drag_progress: 拖入胶囊的拉伸进度（0 = 圆形，1 = 胶囊）。
        _hover_progress: 悬停微光进度（0–1）。
        _pulse: 绘制缩放倍率（回弹 / 按压反馈，静止时为 1.0）。
        _fade: 整体绘制不透明度（入场 / 出场淡入淡出系数，静止时为 1.0）。
        _entrance_done: 入场是否已结束（含跳过）。
        _entrance_expired: 启动预算（5s）是否已耗尽（耗尽后一律不播入场）。
        _exit_requested: 是否已请求带出场动画关闭。
        _exit_finished: 出场流程是否已彻底结束（幂等门）。
        _exit_waiters: 关闭后要执行的回调（如 ``deleteLater``）。
        _exit_guard: 退出兜底定时器（``EXIT_BUDGET_MS`` 超时直接关闭）。
        _count: 池内条目数（折叠态计数徽标）。
        _content: 展开态内容容器（可见性跟随 ``_expanded``）。
        _count_label: 标题栏计数标签（文本 ``存储池 (N)``）。
        _collapse_button: 标题栏折叠按钮（短横线图标，点击收回为折叠态小圆形）。
        _scroll_area: 条目列表滚动区（``StyledScrollArea``）。
        _rows_container: 滚动区内容容器。
        _rows_layout: 条目行垂直布局（含空态提示与尾部弹簧）。
        _rows: 当前条目行 widget 列表（``_PoolItemRow``）。
        _empty_hint: 空池引导控件（仅零条目时可见）。
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
        _geometry_anim_active: 拉伸形变引起的程序化位移期间为 True
            （``moveEvent`` 据此不再重启静默定时器）。
        _collapse_pending: 收拢动画在途（窗口几何尚未落定）为 True。
        _internal_moving: 程序化移动（动画 / 初始化）期间为 True，抑制静默定时器。
        _theme_conn: ``tm.theme_changed`` 的连接对象（销毁时断开用）。
        _drag_move_logged: 本次外部拖拽是否已记录过 ``dragMoveEvent``
            （日志去重：每次拖拽只记录一次，纯日志状态，不影响控制流）。
    """

    add_file_requested = Signal(dict)
    """Signal(dict): 拖入并成功构建文件信息时发射，负载为文件信息字典。"""

    remove_file_requested = Signal(str)
    """Signal(str): 条目拖出且落点为外部时发射，负载为源文件路径。"""

    hide_for_session_requested = Signal()
    """Signal(): 用户选择「本次启动期间隐藏」时发射。

    只改宿主的**内存**意图（本会话不再重建），不写入设置：下次启动仍按用户
    设置正常加载浮窗。
    """

    # ── 动画驱动的 Qt Property ───────────────────────────────────

    def _get_morph(self) -> float:
        """返回圆形 ↔ 面板形变进度。

        Returns:
            float: 0（圆形）到 1（完整面板）。
        """
        return self._morph

    def _set_morph(self, value: float) -> None:
        """写入形变进度（同步内容裁剪并请求重绘）。

        Args:
            value: 目标进度（越界自动钳制到 0–1）。
        """
        value = max(0.0, min(1.0, float(value)))
        if value == self._morph:
            return
        self._morph = value
        self._sync_content_mask()
        self.update()

    morphProgress = Property(float, _get_morph, _set_morph)
    """float: 圆形 → 展开面板的形变进度（``QPropertyAnimation`` 驱动）。"""

    def _get_drag_progress(self) -> float:
        """返回拖入胶囊的拉伸进度。

        Returns:
            float: 0（圆形）到 1（完整胶囊）。
        """
        return self._drag_progress

    def _set_drag_progress(self, value: float) -> None:
        """写入拉伸进度（同步窗口宽度并请求重绘）。

        Args:
            value: 目标进度（越界自动钳制到 0–1）。
        """
        value = max(0.0, min(1.0, float(value)))
        if value == self._drag_progress:
            return
        self._drag_progress = value
        if not self._expanded and not self._collapse_pending:
            self._apply_collapsed_geometry()
        self.update()

    dragProgress = Property(float, _get_drag_progress, _set_drag_progress)
    """float: 拖入胶囊的横向拉伸进度（``QPropertyAnimation`` 驱动）。"""

    def _get_hover_progress(self) -> float:
        """返回悬停微光进度。

        Returns:
            float: 0（未悬停）到 1（完全悬停）。
        """
        return self._hover_progress

    def _set_hover_progress(self, value: float) -> None:
        """写入悬停进度并请求重绘。

        Args:
            value: 目标进度（越界自动钳制到 0–1）。
        """
        value = max(0.0, min(1.0, float(value)))
        if value == self._hover_progress:
            return
        self._hover_progress = value
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)
    """float: 悬停微光进度（``QPropertyAnimation`` 驱动）。"""

    def _get_pulse(self) -> float:
        """返回绘制缩放倍率。

        Returns:
            float: 静止 1.0；按压 < 1，回弹 > 1。
        """
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        """写入绘制缩放倍率并请求重绘。

        Args:
            value: 缩放倍率（钳制到 0.80–1.25）。
        """
        value = max(0.80, min(1.25, float(value)))
        if value == self._pulse:
            return
        self._pulse = value
        self.update()

    pulseScale = Property(float, _get_pulse, _set_pulse)
    """float: 卡片绘制缩放倍率（按压 squish / 成功回弹）。"""

    def _get_fade(self) -> float:
        """返回整体绘制不透明度（入场 / 出场淡入淡出系数）。

        Returns:
            float: 1.0 = 完全可见；0.0 = 完全透明。
        """
        return self._fade

    def _set_fade(self, value: float) -> None:
        """写入绘制不透明度并请求重绘。

        走自绘透明度而非 ``setWindowOpacity``：本窗口是 ``WS_EX_LAYERED``
        半透明窗口，平台层不透明度在部分合成路径上不生效（实测无法验证），
        自绘才能保证入场 / 出场真的看得到淡入淡出。

        Args:
            value: 目标不透明度（越界自动钳制到 0–1）。
        """
        value = max(0.0, min(1.0, float(value)))
        if value == self._fade:
            return
        self._fade = value
        self.update()

    fadeProgress = Property(float, _get_fade, _set_fade)
    """float: 整体绘制不透明度（入场 / 出场动画驱动）。"""

    def _set_paint_opacity(self, painter: QPainter, alpha: float) -> None:
        """把内部元素的不透明度乘以淡入淡出系数后写入绘制器。

        所有带淡入的绘制环节必须经此入口：直接 ``painter.setOpacity`` 会
        把入场 / 出场的基础透明度覆盖掉。

        Args:
            painter: 绘制器。
            alpha: 该元素自身的相对不透明度（0–1）。
        """
        painter.setOpacity(max(0.0, min(1.0, alpha)) * self._fade)


    def __init__(self) -> None:
        """构造浮窗：设置窗口标志 / 属性、构建展开内容、进入折叠态并定位。"""
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        # 状态位（延后预声明：None 区分"从未收到更新"（防抖）/"无宿主窗口"）。
        self._expanded = False
        self._visual_expanded = False
        self._collapse_pending = False
        self._drag_active = False
        # 外部拖入日志去重（dragMoveEvent 每次拖拽仅记录一次；纯日志状态）。
        self._drag_move_logged = False
        self._shown_diag_logged = False
        self._pending_items: Optional[list] = None
        self._host_window: Optional[QWidget] = None
        self._press_pos: Optional[QPoint] = None
        self._drag_source_path: Optional[str] = None

        # 贴边吸附 / 惯性位移动画状态。
        self._snap_enabled = True
        self._internal_moving = False
        self._geometry_anim_active = False
        self._move_anim: Optional[QPropertyAnimation] = None

        # 展开 / 拉伸方向的固定边（True = 以右 / 下缘为固定边）：形态变化前
        # 由 _update_anchor 按「距工作区哪侧更近」重算，绘制与几何共用同一
        # 组值，保证形变朝固定边的对角方向生长。默认右 + 上（历史行为）。
        self._anchor_right = True
        self._anchor_bottom = False

        # 动效进度（绘制输入）。
        self._morph = 1.0 if self._expanded else 0.0
        self._drag_progress = 0.0
        self._hover_progress = 0.0
        self._pulse = 1.0
        self._fade = 1.0
        self._count = 0
        self._shown_once = False

        # 入场 / 出场（整体缩放 + 透明度）状态与预算兜底。
        self._entrance_done = False
        self._entrance_expired = False
        self._exit_requested = False
        self._exit_finished = False
        self._exit_waiters: list[Callable[[], None]] = []
        self._exit_guard: Optional[QTimer] = None

        # 动画句柄（每次启动前先停旧的，避免叠加）。
        self._morph_anim: Optional[QPropertyAnimation] = None
        self._drag_anim: Optional[QPropertyAnimation] = None
        self._hover_anim: Optional[QPropertyAnimation] = None
        self._pulse_anim: Optional[QPropertyAnimation] = None
        self._entrance_anim: Optional[QParallelAnimationGroup] = None
        self._exit_anim: Optional[QParallelAnimationGroup] = None

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

        # 启动兜底：自构造起 ENTRANCE_BUDGET_MS 内入场还没走完 → 直接无动画显示，
        # 避免浮窗动画拖累启动（见 _on_entrance_budget_exceeded）。
        self._entrance_guard = QTimer(self)
        self._entrance_guard.setSingleShot(True)
        self._entrance_guard.timeout.connect(self._on_entrance_budget_exceeded)
        self._entrance_guard.start(ENTRANCE_BUDGET_MS)

        self._internal_moving = True
        self._apply_state_geometry()
        # 位置记忆：环境指纹一致 → 用上次退出的位置；否则回默认（右上角）。
        if not self._restore_saved_position():
            self.move(self._compute_initial_position(self.size()))
        self._internal_moving = False

        # 主题切换实时重绘 + 条目行图标重建（明暗/强调色均需刷新）；
        # 连接对象存引用，供生命周期断开。
        self._theme_conn = tm.theme_changed.connect(self._on_theme_refresh)
        self._colors_conn = tm.colors_updated.connect(self._on_theme_refresh)

    # ── 展开内容构建 ────────────────────────────────────────────

    def _build_content(self) -> None:
        """构建展开态内容：标题行（强调色圆点 + 计数 + 折叠按钮）+ 滚动条目列表 + 空态提示。

        内容容器 ``self._content`` 覆盖整个窗口，可见性跟随展开态（折叠态
        隐藏以保证圆形入口自绘干净）。标题栏条带严格位于顶部
        ``TITLE_BAR_HEIGHT`` 像素内，保证 ``_is_drag_region`` 判定准确；
        ``_CARD_MARGIN`` 的卡片留白折算进布局边距，使内容不压住圆角描边。
        """
        self._content = QWidget(self)
        self._content.setAttribute(Qt.WA_TranslucentBackground)

        root_layout = QVBoxLayout(self._content)
        root_layout.setContentsMargins(
            _CARD_MARGIN + 12,
            _CARD_MARGIN + 4,
            _CARD_MARGIN + 10,
            _CARD_MARGIN + 8,
        )
        root_layout.setSpacing(0)

        # 标题行：计数标签（鼠标透传）+ 折叠按钮（标题区唯一消费点击的控件）
        title_row = QWidget(self._content)
        title_row.setFixedHeight(_TITLE_ROW_HEIGHT)
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)

        self._count_label = QLabel(
            COUNT_LABEL_FORMAT.format(count=0), title_row
        )
        self._count_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._count_label.setFont(_ui_font(12, QFont.Weight.DemiBold))
        title_layout.addWidget(self._count_label)
        title_layout.addStretch(1)

        # 折叠按钮用「短横线」（最小化语义）：点击后面板收回为折叠态的小圆形
        # 浮窗，不与展开方向的 chevron 混淆（chevron 会暗示“继续展开”）。
        self._collapse_button = StyledIconButton(
            "minus",
            size="sm",
            shape="circle",
            variant="ghost",
            tooltip="折叠",
            parent=title_row,
        )
        self._collapse_button.clicked.connect(
            lambda: self.set_expanded(False)
        )
        title_layout.addWidget(self._collapse_button)

        root_layout.addWidget(title_row)

        # 滚动条目列表：竖向滚动条必须是**真正可见**的 ``StyledScrollBar``
        # （``StyledScrollArea`` 构造时已装入），支持滑块拖动与轨道点击跳转；
        # 历史实现用 ``ScrollBarAlwaysOff`` 把整条滚动条藏掉，只剩滚轮可用。
        self._scroll_area = StyledScrollArea(self._content)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 只对滚动区自身去底色：无选择器的片段会泄漏到子控件（含滚动条）。
        register_widget_qss(
            self._scroll_area,
            "QScrollArea { background-color: transparent; border: none; }",
        )
        self._scroll_area.viewport().setAutoFillBackground(False)
        self._style_vertical_scrollbar()
        root_layout.addWidget(self._scroll_area, 1)

        self._rows_container = QWidget()
        self._rows_container.setAttribute(Qt.WA_TranslucentBackground)
        register_widget_qss(
            self._rows_container, "background-color: transparent;"
        )
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(6, 4, 6, 4)
        self._rows_layout.setSpacing(4)
        # widgetResizable 的 QScrollArea 依据容器 minimumSize 计算滚动范围，
        # 而非布局 minimumSizeHint；SetMinAndMaxSize 把容器最小/最大尺寸
        # 绑到布局尺寸，条目溢出时滚动条范围（range）才会 > 0。
        self._rows_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)

        # 空态：自绘图标 + 主 / 辅助文案（布局常驻，垂直弹性伸缩以居中）
        self._empty_hint = _EmptyState(self._rows_container)
        self._empty_hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._empty_hint.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Expanding
        )
        self._rows_layout.addWidget(self._empty_hint, 1)
        self._rows_layout.addStretch(1)
        self._scroll_area.setWidget(self._rows_container)

        self._rows: list[_PoolItemRow] = []

        self._content.setGeometry(self.rect())
        self._content.setVisible(self._expanded)
        self._apply_label_styles()

    def _style_vertical_scrollbar(self) -> None:
        """校准竖向 ``StyledScrollBar`` 的视觉度量（与主界面浮动滚动条同口径）。

        滚动条命中宽度来自 ``sizeHint()``（8px）；滑块本体只 4px（悬停 /
        拖动时 6px）、2px 贴边内缩 —— 与 ``StyledScrollArea`` 默认值一致，
        这里显式声明以便浮窗面板跟随同一套视觉参数。
        """
        configure = getattr(
            self._scroll_area.verticalScrollBar(), "configure", None
        )
        if callable(configure):
            configure(
                normal_width=_SCROLL_BAR_WIDTH,
                hover_width=_SCROLL_BAR_HOVER_WIDTH,
                padding=2,
            )

    def _apply_label_styles(self) -> None:
        """按当前主题重注册标题标签样式（强调色圆点由 ``paintEvent`` 绘制）。"""
        register_widget_qss(
            self._count_label,
            "background: transparent; border: none;"
            f" padding-left: {_TITLE_DOT_SPACE}px;"
            f" color: {tm.text.name()};"
            " font-size: 12px; font-weight: 600;",
        )

    # ── 两态切换 ────────────────────────────────────────────────

    def set_expanded(self, expanded: bool) -> None:
        """切换折叠 / 展开态（状态立即翻转，形变异步播放）。

        展开：先按当前折叠位置重算**锚定边**（:meth:`_update_anchor`：哪侧更
        贴近工作区边缘就以该侧为固定边），再尺寸与位置**同帧原子更新**
        （``setGeometry`` 一次平台调用）——固定边不动，面板向屏幕内侧生长。
        之所以不再分两步（先 ``setFixedSize`` 再位移动画）：卡片始终锚定在
        固定边上，固定边不动就意味着卡片在屏幕上根本不需要位移；分两步
        反而会让窗口先在生长方向多出一个面板宽度（面板被推出屏幕）再滑回。
        整体几何再夹回真实工作区，由 ``morphProgress`` 的展开形变承担全部
        动效。

        收起：``_expanded`` 立即为 False（对外状态同步可断言），但**几何落定
        推迟到收拢动画结束**——可见窗口先播放面板缩回圆形的形变，再一次性
        把窗口缩到 ``COLLAPSED_SIZE``。收拢前同样按**当前位置**重算锚定边
        （与展开同一套判定：哪侧更近就以该侧为固定边），保证形变方向与几何
        落点同源：圆形恰好落在收拢动画终点，既无位置跳变，也总是落在当前
        更贴近的那一侧。窗口不可见（测试 / 未上屏）时无从观看动画，直接
        同步落定。

        Args:
            expanded: True 进入展开态，False 回到折叠态。
        """
        expanded = bool(expanded)
        if expanded == self._expanded:
            self.update()
            return

        if expanded:
            self._expanded = True
            self._visual_expanded = True
            self._collapse_pending = False
            self._reset_drag_state()
            target_size = self._expanded_size()
            self._update_anchor()
            target = self._anchored_rect(target_size)
            self._stop_move_animation()
            self._settle_timer.stop()
            self._internal_moving = True
            self.setGeometry(target)
            self._internal_moving = False
            self._apply_state_geometry()
            self._animate_morph(1.0)
            self.update()
            return

        self._expanded = False
        # 回收也要按**当前位置**重算固定边（展开 / 收拢同一套判定）：形变
        # 方向与最终几何必须同源，否则圆形会朝旧锚定角缩回、再被几何落定
        # 拉到新一侧，出现可见跳变。
        self._update_anchor()
        if self.isVisible() and self._morph > 0.01:
            # 可见：几何滞后到收拢动画结束再落定（圆形落在动画终点）。
            self._collapse_pending = True
            self._animate_morph(0.0, finished=self._finish_collapse)
            return
        self._finish_collapse()

    def _finish_collapse(self) -> None:
        """收拢落定：缩回折叠尺寸、按收拢时重算的锚定边、复位形变 / 蒙版并重绘。

        沿用 :meth:`set_expanded` 收拢分支刚刚重算的锚定边（与收拢形变的
        方向同源），圆形落在形变终点，不产生位置跳变。
        """
        self._collapse_pending = False
        target_size = self._target_size()
        target = self._anchored_rect(target_size)
        self._visual_expanded = False
        # 收拢动画已把圆形画到窗口的锚定角：此处纯几何收边，位置跳变不可见。
        # 尺寸与位置一次 `setGeometry` 同时生效，避免中间帧错位；位移是
        # 程序化的，抑制静默定时器，避免折叠后又被吸附规则挪动。
        self._stop_move_animation()
        self._settle_timer.stop()
        self._internal_moving = True
        self.setGeometry(target)
        self._internal_moving = False
        self._apply_state_geometry()
        self._stop_animation("_pulse_anim")
        self._pulse = 1.0
        self._morph = 0.0
        self._sync_content_mask()
        self.update()
        # 出场请求在收拢阶段到达：面板已缩回圆形，接上缩放 + 淡出。
        if self._exit_requested and self._exit_anim is None:
            self._play_exit_fade()

    def is_expanded(self) -> bool:
        """返回当前是否处于展开态。

        Returns:
            bool: 展开态返回 True，折叠态返回 False。
        """
        return self._expanded

    def _target_size(self) -> QSize:
        """返回当前状态下应使用的固定尺寸。

        Returns:
            QSize: 展开态为钳制后的展开尺寸；折叠态为按拖入进度插值的宽度
            （进度为 0 时即 ``COLLAPSED_SIZE``）。
        """
        if self._expanded:
            return self._expanded_size()
        base = COLLAPSED_SIZE
        progress = self._drag_progress
        if progress <= 0.0:
            return QSize(base)
        width = round(
            base.width()
            + (DRAG_HOVER_SIZE.width() - base.width()) * progress
        )
        return QSize(width, base.height())

    def _expanded_size(self) -> QSize:
        """计算展开态尺寸：高度钳制到屏幕可用高度的 70%。

        ``avail_h`` 取自窗口所在屏幕（``screenAt``）；``screenAt`` 返回 None
        时回退主屏幕，两者皆不可用时退回 ``EXPANDED_SIZE``。可用高度经
        :func:`screen_work_area` 取真实工作区高度——Qt 的
        ``availableGeometry()`` 在任务栏停靠左 / 上侧时会越出物理屏幕（见
        ``utils/screen_utils`` 模块文档）。

        Returns:
            QSize: 宽度固定为 ``EXPANDED_SIZE.width()``，高度为
            ``min(EXPANDED_SIZE.height(), int(avail_h * EXPANDED_HEIGHT_RATIO))``。
        """
        screen = QApplication.screenAt(self.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QSize(EXPANDED_SIZE)
        avail = screen_work_area(screen)
        if not avail.isValid():
            return QSize(EXPANDED_SIZE)
        avail_h = avail.height()
        clamped = min(
            EXPANDED_SIZE.height(),
            int(avail_h * EXPANDED_HEIGHT_RATIO),
        )
        return QSize(EXPANDED_SIZE.width(), clamped)

    def _apply_state_geometry(self) -> None:
        """把当前状态的固定尺寸应用到窗口（``setFixedSize``）。

        同时同步展开内容容器的几何、可见性与裁剪蒙版（折叠态隐藏内容，
        保证圆形入口自绘干净）。
        """
        self.setFixedSize(self._target_size())
        content = getattr(self, "_content", None)
        if content is not None:
            content.setGeometry(self.rect())
            content.setVisible(self._expanded)
        self._sync_content_mask()

    def _apply_collapsed_geometry(self) -> None:
        """折叠态宽度变化（拖入拉伸）：固定锚定边并向屏幕内侧生长。"""
        target = self._target_size()
        if target == self.size():
            return
        rect = self._anchored_rect(target)
        self.setFixedSize(target)
        self.move(rect.topLeft())

    def _current_screen(self) -> Optional[QScreen]:
        """返回窗口几何中心所在屏幕（``screenAt`` → 主屏幕回退）。

        Returns:
            QScreen | None: 当前屏幕；无可用屏幕时为 None。
        """
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen

    def _compute_anchor(self) -> tuple[bool, bool]:
        """按「距工作区哪侧更近」决定展开 / 拉伸时的固定边。

        水平 / 垂直各自独立判定：窗口左缘比右缘更接近工作区对应边时，左缘
        为固定边（向右展开），否则右缘固定（向左展开）；垂直同理（上缘固定
        向下展开 / 下缘固定向上展开）。两侧边距相等时回退历史默认（右 + 上），
        避免居中摆放的浮窗出现无意义的方向跳变。

        Returns:
            tuple: ``(anchor_right, anchor_bottom)``。
        """
        work = screen_work_area(self._current_screen())
        if not work.isValid():
            return True, False
        left_gap = self.x() - work.left()
        right_gap = work.right() - (self.x() + self.width() - 1)
        top_gap = self.y() - work.top()
        bottom_gap = work.bottom() - (self.y() + self.height() - 1)
        return right_gap <= left_gap, bottom_gap < top_gap

    def _update_anchor(self) -> None:
        """形态变化（展开 / 收拢 / 拖入拉伸）起点重算锚定边。

        三种形态变化都以**当前位置**重新判定（:meth:`_compute_anchor`：距
        工作区哪侧更近就以该侧为固定边），保证：

        * 展开：固定边不动，向屏幕内侧生长（不越屏）；
        * 收拢：与形变方向同源，圆形落在当前更贴近的那一侧，无跳变；
        * 拖入拉伸：胶囊向屏幕内侧生长，收回不横移。
        """
        self._anchor_right, self._anchor_bottom = self._compute_anchor()

    def _anchored_rect(self, size: QSize) -> QRect:
        """按当前锚定边计算目标矩形：固定边不动，向屏幕内侧生长。

        生长出的矩形再整体夹回真实工作区（:func:`screen_work_area`：任务栏
        停靠左 / 上侧时 Qt 的 ``availableGeometry()`` 会越出物理屏幕，见该
        模块文档），保证展开内容完整落在屏幕内。

        Args:
            size: 目标窗口尺寸。

        Returns:
            QRect: 目标几何（全局坐标）。
        """
        current = self.geometry()
        width = size.width()
        height = size.height()
        if self._anchor_right:
            x = current.right() - width + 1
        else:
            x = current.left()
        if self._anchor_bottom:
            y = current.bottom() - height + 1
        else:
            y = current.top()
        work = screen_work_area(self._current_screen())
        if work.isValid():
            x = max(work.left(), min(x, work.right() - width + 1))
            y = max(work.top(), min(y, work.bottom() - height + 1))
        return QRect(x, y, width, height)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口尺寸变化时同步展开内容容器几何与裁剪蒙版。

        Args:
            event: 尺寸变化事件（交回基类处理）。
        """
        super().resizeEvent(event)
        content = getattr(self, "_content", None)
        if content is not None:
            content.setGeometry(self.rect())
        self._sync_content_mask()

    def showEvent(self, event: QShowEvent) -> None:
        """显示时淡入并输出一次性诊断日志（HWND / 拖放注册状态）。

        淡入只在首次显示时播放（``windowOpacity`` 0→1），避免每次从主窗口
        切回都被重播；诊断日志仅一次，避免重复 show 刷屏——真实运行环境下
        排查「外部拖入未达 ``dragEnterEvent``」类缺陷时可仅凭日志判断窗口
        是否可见、原生句柄是否建立、``WA_DropSiteRegistered`` 是否就位。

        Args:
            event: 显示事件（交回基类处理）。
        """
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            self._play_entrance()
        if self._shown_diag_logged:
            return
        self._shown_diag_logged = True
        try:
            handle = self.windowHandle()
            wh_type = int(handle.type()) if handle is not None else -1
            wh_flags = int(handle.flags()) & 0xFFFFFFFF if handle is not None else 0
            info(
                "[floating_pool] shown diagnostics: "
                f"hwnd={int(self.winId())} geometry={self.geometry()} "
                f"isVisible={self.isVisible()} "
                f"acceptDrops={self.acceptDrops()} "
                f"WA_AcceptDrops={self.testAttribute(Qt.WA_AcceptDrops)} "
                f"WA_DropSiteRegistered={self.testAttribute(Qt.WA_DropSiteRegistered)} "
                f"WA_TransparentForMouseEvents={self.testAttribute(Qt.WA_TransparentForMouseEvents)} "
                f"WA_TranslucentBackground={self.testAttribute(Qt.WA_TranslucentBackground)} "
                f"whExists={handle is not None} whType={wh_type} "
                f"whFlags=0x{wh_flags:x}"
            )
        except Exception as exc:  # noqa: BLE001 - 诊断日志失败绝不阻断显示
            warning(f"[floating_pool] shown diagnostics 失败: {exc}")

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭前记忆位置、停止全部定时器 / 动画并复位视觉状态。

        Args:
            event: 关闭事件（交回基类处理）。
        """
        # 退出即记忆位置（只存折叠态左上角 + 屏幕环境指纹，见 _persist_position）
        self._persist_position()
        self._debounce_timer.stop()
        self._settle_timer.stop()
        self._entrance_guard.stop()
        if self._exit_guard is not None:
            self._exit_guard.stop()
        self._stop_move_animation()
        for attr in (
            "_morph_anim",
            "_drag_anim",
            "_hover_anim",
            "_pulse_anim",
            "_entrance_anim",
            "_exit_anim",
        ):
            self._stop_animation(attr)
        # 复位视觉状态（可能因中途关闭而停在缩放 / 淡出途中）
        self._pulse = 1.0
        self._fade = 1.0
        try:
            self.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        self._collapse_pending = False
        super().closeEvent(event)

    def _on_theme_refresh(self, *_args) -> None:
        """主题/配色变化：重绘自身、重注册文字样式并重建全部条目行图标。

        行图标在构造时经 ``setPixmap`` 存入 ``QLabel``，类型图标含主题色
        替换，不会自动跟随；必须逐行重取回填，否则一直显示旧配色（历史
        缺陷）。真实磁盘缩略图仍走 thumb 键，不重读磁盘。

        Args:
            *_args: 主题信号附带参数（未使用）。
        """
        self._apply_label_styles()
        self.update()
        for row in self._rows:
            try:
                row.refresh_icon()
            except RuntimeError:
                # 行已随重建销毁（deleteLater 未及清理）：跳过。
                continue

    # ── 位置记忆（退出时保存 / 启动时恢复）───────────────

    def _restore_saved_position(self) -> bool:
        """尝试用上次退出时记住的位置摆放浮窗。

        仅当屏幕环境指纹（:func:`_screen_env_signature`）与保存时完全一致
        才恢复；显示器 / 分辨率 / 任务栏位置 / DPI 等任一变化均视为环境不
        匹配，交回调用方使用默认位置。恢复出的坐标还会夹回所在屏幕的
        真实工作区，避免存盘期间布局微小漂移把浮窗摆到屏幕外。

        Returns:
            bool: 已按保存位置定位返回 True；无记录 / 环境不匹配 / 数据非法
            返回 False（调用方退回默认位置）。
        """
        state = _load_persisted_position()
        if not state:
            return False
        if state.get("env") != _screen_env_signature():
            debug("[floating_pool] 屏幕环境已变化，使用默认位置")
            return False
        try:
            x = int(state["x"])
            y = int(state["y"])
        except (KeyError, TypeError, ValueError):
            return False

        point = QPoint(x, y)
        screen = QApplication.screenAt(point)
        if screen is None:
            screen = QApplication.primaryScreen()
        work = screen_work_area(screen)
        size = self.size()
        if work.isValid():
            x = max(work.left(), min(x, work.right() - size.width() + 1))
            y = max(work.top(), min(y, work.bottom() - size.height() + 1))
        self.move(QPoint(x, y))
        debug(f"[floating_pool] 已恢复上次位置：({x}, {y})")
        return True

    def _collapsed_geometry_for_persist(self) -> QRect:
        """返回应当持久化的几何——始终是**折叠态（圆形）**的位置。

        展开 / 收拢动画中 / 拖入胶囊拉伸中，直接存当前矩形会得到面板或胶囊
        的左上角（下一次启动会以它为圆形的左上角，看起来就是位置偏移）；
        因此这三种情形下按当前锚定边反推圆形应在的角。

        Returns:
            QRect: 折叠尺寸的窗口矩形（全局坐标）。
        """
        if self._expanded or self._collapse_pending or self._drag_progress > 0.01:
            return self._anchored_rect(QSize(COLLAPSED_SIZE))
        return self.geometry()

    def _persist_position(self) -> None:
        """把当前折叠态位置 + 屏幕环境指纹写入设置（退出 / 关闭时调用）。"""
        try:
            rect = self._collapsed_geometry_for_persist()
            _save_persisted_position(
                {
                    "x": int(rect.x()),
                    "y": int(rect.y()),
                    "env": _screen_env_signature(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 关闭路径不得因持久化失败中断
            warning(f"[floating_pool] 退出时记忆位置失败：{exc}")

    def _compute_initial_position(self, size: QSize) -> QPoint:
        """计算默认（无可用记忆）位置：屏幕可用区域右上角，内缩 ``INITIAL_INSET``。

        可用区经 :func:`screen_work_area` 求解（不能用 Qt 的
        ``availableGeometry()``——任务栏停靠左 / 上侧时它的右缘 / 下缘会越出
        物理屏幕，导致浮窗首帧就有一截露在屏幕外）。右缘留白与
        :meth:`_settle_and_snap` 的吸附口径一致（均按包含式边界留
        ``INITIAL_INSET``，避免落定后被吸附规则再挪 1px）。

        Args:
            size: 窗口当前尺寸（用于从右边缘向左推算 x）。

        Returns:
            QPoint: 初始左上角全局坐标；无可用屏幕时退回 ``(0, 0)``。
        """
        screen = QApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen_work_area(screen)
        if not avail.isValid():
            return QPoint(0, 0)
        x = avail.right() - INITIAL_INSET - size.width() + 1
        y = avail.top() + INITIAL_INSET
        return QPoint(x, y)

    # ── 绘制 ────────────────────────────────────────────────────

    def _card_rect(self) -> QRectF:
        """返回卡片（可见圆角矩形）在窗口内的矩形。

        折叠态：铺满窗口留白内的整个区域，圆角半径取高度一半 → 进度为 0
        时是完美圆形，拖入拉伸后是连续过渡出的胶囊。展开态：从**锚定角**
        （:attr:`_anchor_right` / :attr:`_anchor_bottom` 所指的角）的圆形按
        ``_morph`` 向外扩散到完整面板——固定边不动，形变方向与窗口几何的
        生长方向严格一致。

        Returns:
            QRectF: 卡片矩形（窗口本地坐标）。
        """
        width = max(1.0, float(self.width() - 2 * _CARD_MARGIN))
        height = max(1.0, float(self.height() - 2 * _CARD_MARGIN))
        if not self._visual_expanded:
            return QRectF(
                float(_CARD_MARGIN), float(_CARD_MARGIN), width, height
            )
        progress = self._morph
        diameter = max(1.0, float(COLLAPSED_SIZE.height() - 2 * _CARD_MARGIN))
        card_w = diameter + (width - diameter) * progress
        card_h = diameter + (height - diameter) * progress
        left = float(_CARD_MARGIN) + (
            width - card_w if self._anchor_right else 0.0
        )
        top = float(_CARD_MARGIN) + (
            height - card_h if self._anchor_bottom else 0.0
        )
        return QRectF(left, top, card_w, card_h)

    def _card_radius(self, card: QRectF) -> float:
        """返回卡片圆角半径（折叠态恒为高度一半，展开态插值到面板圆角）。

        Args:
            card: 当前卡片矩形。

        Returns:
            float: 圆角半径（px）。
        """
        if not self._visual_expanded:
            return card.height() / 2.0
        progress = self._morph
        radius = card.height() / 2.0 * (1.0 - progress) + _PANEL_RADIUS * progress
        return max(_PANEL_RADIUS * 0.6, min(radius, card.height() / 2.0))

    def _effective_pulse(self, card: QRectF) -> float:
        """把回弹缩放钳制在留白余量内（放大不得越出窗口被裁切）。

        Args:
            card: 当前卡片矩形。

        Returns:
            float: 实际使用的缩放倍率。
        """
        span = max(1.0, min(card.width(), card.height()))
        limit = 1.0 + (2.0 * _CARD_MARGIN) / span
        return max(0.80, min(self._pulse, limit))

    def paintEvent(self, event: QPaintEvent) -> None:
        """自绘主题化卡片：渐变底 + 玻璃边缘 + 拖放发光 + 圆形入口内容。

        配色实时取自主题（``tm`` 语义 token），与
        ``styled_floating_panel.FloatingPanel.paintEvent`` 同口径；拖放高亮
        沿用 ``dragActive`` 动态属性，悬停 / 拖入 / 回弹由动画进度驱动。

        Args:
            event: 绘制事件（未直接使用）。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        card = self._card_rect()
        radius = self._card_radius(card)
        scale = self._effective_pulse(card)
        if abs(scale - 1.0) > 1e-3:
            # 缩放围绕锚定角进行，放大才不会把固定边那一侧推离原位。
            anchor = QPointF(
                card.right() if self._anchor_right else card.left(),
                card.bottom() if self._anchor_bottom else card.top(),
            )
            painter.translate(anchor)
            painter.scale(scale, scale)
            painter.translate(-anchor)

        # 入场 / 出场：整体透明度作用到后续全部绘制（内部淡入必经
        # _set_paint_opacity 叠乘，否则会把该基础透明度覆盖掉）。
        self._set_paint_opacity(painter, 1.0)

        # 悬停微光只作用于圆形入口；展开面板保持克制，避免整块面板持续发光。
        glow = 0.0
        if self.property("dragActive"):
            glow = 1.0
        elif not self._visual_expanded:
            glow = self._hover_progress * 0.6
        self._paint_glow(painter, card, radius, glow)
        self._paint_surface(painter, card, radius)

        if self._visual_expanded:
            self._paint_panel_furniture(painter, card)
        else:
            self._paint_circle_content(painter, card)

        self._paint_border(painter, card, radius, glow)
        painter.end()

    def _paint_glow(
        self, painter: QPainter, card: QRectF, radius: float, glow: float
    ) -> None:
        """绘制卡片外圈的主题色光晕（悬停微光 / 拖入高亮）。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
            radius: 卡片圆角半径。
            glow: 光晕强度（0–1）。
        """
        if glow <= 0.01:
            return
        painter.setBrush(Qt.NoBrush)
        for step, alpha in ((1.5, 30.0), (3.0, 18.0), (4.5, 9.0)):
            painter.setPen(
                QPen(tm.alpha_of(tm.accent, alpha * glow), 1.0 + step * 0.7)
            )
            painter.drawRoundedRect(
                card.adjusted(-step, -step, step, step),
                radius + step,
                radius + step,
            )

    def _paint_surface(
        self, painter: QPainter, card: QRectF, radius: float
    ) -> None:
        """绘制卡片底：下沉阴影 + 主题渐变填充 + 拖入强调色叠加。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
            radius: 卡片圆角半径。
        """
        dark = tm.is_dark_theme()
        painter.setPen(Qt.NoPen)

        # 1) 底部柔和投影（留白内，模拟轻量抬升）
        painter.setBrush(
            tm.alpha_of(tm.black if dark else tm.text, 30 if dark else 16)
        )
        painter.drawRoundedRect(card.translated(0, 1.5), radius, radius)

        # 2) 垂直渐变底：上亮下稍实，接近亚克力板材的透光层次
        gradient = QLinearGradient(card.topLeft(), card.bottomLeft())
        if dark:
            gradient.setColorAt(0.0, tm.alpha_of(tm.surface, 90))
            gradient.setColorAt(1.0, tm.alpha_of(tm.surface, 78))
        else:
            gradient.setColorAt(0.0, tm.alpha_of(tm.white, 95))
            gradient.setColorAt(1.0, tm.alpha_of(tm.white, 86))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(card, radius, radius)

        # 3) 拖入态强调色薄层（与光晕一起构成明确的接收反馈）
        if self.property("dragActive"):
            painter.setBrush(tm.alpha_of(tm.accent, 14))
            painter.drawRoundedRect(card, radius, radius)

    def _paint_border(
        self, painter: QPainter, card: QRectF, radius: float, glow: float
    ) -> None:
        """绘制卡片描边、顶部玻璃高光与拖入强调色边框。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
            radius: 卡片圆角半径。
            glow: 光晕强度（0–1，决定描边向强调色过渡的程度）。
        """
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(tm.card_border, 1))
        painter.drawRoundedRect(
            card.adjusted(0.5, 0.5, -0.5, -0.5),
            max(0.0, radius - 0.5),
            max(0.0, radius - 0.5),
        )

        # 顶部玻璃高光：只在内侧直边段绘制，避免压进圆角
        if card.width() > 2.0 * radius and card.height() > 4.0:
            painter.setPen(
                QPen(tm.alpha_of(tm.white, 26 if tm.is_dark_theme() else 78), 1)
            )
            painter.drawLine(
                QPointF(card.left() + radius, card.top() + 1.0),
                QPointF(card.right() - radius, card.top() + 1.0),
            )

        if self.property("dragActive"):
            painter.setPen(QPen(tm.accent, 1.6))
            painter.drawRoundedRect(
                card.adjusted(0.8, 0.8, -0.8, -0.8),
                max(0.0, radius - 0.8),
                max(0.0, radius - 0.8),
            )
        elif glow > 0.02:
            painter.setPen(
                QPen(tm.alpha_of(tm.accent, 65 * min(1.0, glow * 1.7)), 1.2)
            )
            painter.drawRoundedRect(
                card.adjusted(0.7, 0.7, -0.7, -0.7),
                max(0.0, radius - 0.7),
                max(0.0, radius - 0.7),
            )

    def _paint_panel_furniture(self, painter: QPainter, card: QRectF) -> None:
        """绘制展开面板的装饰：标题区强调色圆点 + 分隔线（随形变淡入）。

        装饰统一裁剪到卡片圆角路径内，形变过程中不会溢到卡片之外。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
        """
        fade = min(1.0, max(0.0, (self._morph - 0.45) / 0.4))
        if fade <= 0.01:
            return
        radius = self._card_radius(card)
        clip = QPainterPath()
        clip.addRoundedRect(card, radius, radius)

        painter.save()
        painter.setClipPath(clip)
        self._set_paint_opacity(painter, fade)

        # 标题行左侧的强调色圆点（与标题文字基线居中对齐）
        dot = 6.0
        center_y = card.top() + _CARD_MARGIN + _TITLE_ROW_HEIGHT / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(tm.accent)
        painter.drawEllipse(
            QRectF(
                card.left() + _CARD_MARGIN + 8.0,
                center_y - dot / 2.0,
                dot,
                dot,
            )
        )

        # 标题区下沿分隔线
        if card.height() > TITLE_BAR_HEIGHT + 6:
            painter.setPen(QPen(tm.divider, 1))
            y = card.top() + TITLE_BAR_HEIGHT - _CARD_MARGIN
            painter.drawLine(
                QPointF(card.left() + 14, y), QPointF(card.right() - 14, y)
            )

        self._set_paint_opacity(painter, 1.0)
        painter.restore()

    def _paint_circle_content(self, painter: QPainter, card: QRectF) -> None:
        """绘制圆形入口内容：拖放图标、计数徽标与拖入提示文案。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
        """
        progress = self._drag_progress
        center = card.center()

        icon_opacity = 1.0 - min(1.0, progress * 1.6)
        if icon_opacity > 0.02:
            highlight = (
                bool(self.property("dragActive"))
                or self._hover_progress > 0.5
            )
            painter.setOpacity(icon_opacity * self._fade)
            side = min(23.0, card.height() * 0.42)
            render_icon(
                painter,
                "download",
                QRectF(
                    center.x() - side / 2.0,
                    center.y() - side / 2.0,
                    side,
                    side,
                ),
                tm.accent_text if highlight else tm.text,
                1.7,
            )
            self._set_paint_opacity(painter, 1.0)

        if self._count > 0 and progress < 0.4:
            self._set_paint_opacity(painter, 1.0 - min(1.0, progress / 0.4))
            self._paint_count_badge(painter, card)
            self._set_paint_opacity(painter, 1.0)

        if progress > 0.05:
            self._paint_drag_hint(painter, card, progress)

    def _paint_count_badge(self, painter: QPainter, card: QRectF) -> None:
        """绘制折叠态条目数徽标（主题色实底 + 自动可读前景）。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
        """
        diameter = 17.0
        center = QPointF(
            card.right() - 14.0 if self._anchor_right else card.left() + 14.0,
            card.top() + 14.0,
        )
        badge = QRectF(
            center.x() - diameter / 2.0,
            center.y() - diameter / 2.0,
            diameter,
            diameter,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(tm.accent)
        painter.drawEllipse(badge)

        text = "99+" if self._count > 99 else str(self._count)
        painter.setPen(tm.readable_on(tm.accent))
        painter.setFont(_ui_font(9, QFont.Weight.DemiBold))
        painter.drawText(badge, Qt.AlignCenter, text)

    def _paint_drag_hint(
        self, painter: QPainter, card: QRectF, progress: float
    ) -> None:
        """绘制拖入胶囊内的引导文案（随拉伸进度淡入，由新露出的那一侧带出）。

        文案填充在**新生长出来的区域**：右缘固定时从卡片左缘带入（图标在
        左、文字左对齐），左缘固定时左右镜像（图标靠右、文字右对齐），
        避免提示文字压在圆形入口上。

        Args:
            painter: 绘制器。
            card: 卡片矩形。
            progress: 拉伸进度（0–1）。
        """
        fade = min(1.0, max(0.0, (progress - 0.15) / 0.55))
        if fade <= 0.01:
            return
        self._set_paint_opacity(painter, fade)

        icon_side = 22.0
        icon_x = (
            card.left() + 20.0
            if self._anchor_right
            else card.right() - 20.0 - icon_side
        )
        icon_rect = QRectF(
            icon_x,
            card.center().y() - icon_side / 2.0,
            icon_side,
            icon_side,
        )
        render_icon(painter, "download", icon_rect, tm.accent_text, 1.6)

        if self._anchor_right:
            text_left = card.left() + 52.0
            text_width = max(10.0, card.right() - 14.0 - text_left)
            align = int(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            text_left = card.left() + 14.0
            text_width = max(10.0, card.right() - 52.0 - text_left)
            align = int(Qt.AlignRight | Qt.AlignVCenter)
        painter.setFont(_ui_font(12, QFont.Weight.DemiBold))
        painter.setPen(tm.text)
        painter.drawText(
            QRectF(text_left, card.top() + 14.0, text_width, 18.0),
            align,
            DRAG_HINT_TEXT,
        )
        painter.setFont(_ui_font(10))
        painter.setPen(tm.text_hint)
        painter.drawText(
            QRectF(text_left, card.top() + 31.0, text_width, 16.0),
            align,
            DRAG_HINT_SUB_TEXT,
        )
        self._set_paint_opacity(painter, 1.0)

    def _sync_content_mask(self) -> None:
        """把展开内容裁剪到当前卡片区域（形变期间的「逐步揭示」）。

        完整展开（``_morph`` ≈ 1）或未展开时清空蒙版：蒙版只为动画服务，
        常驻会让子控件在圆角边缘出现锯齿裁切。
        """
        content = getattr(self, "_content", None)
        if content is None:
            return
        if not self._visual_expanded or self._morph >= 0.999:
            content.clearMask()
            return
        card = self._card_rect()
        path = QPainterPath()
        path.addRoundedRect(card, self._card_radius(card), self._card_radius(card))
        content.setMask(QRegion(path.toFillPolygon().toPolygon()))

    # ── 动效编排 ────────────────────────────────────────────────

    def _stop_animation(self, attr: str) -> None:
        """停止并销毁指定动画句柄（幂等；``stop()`` 不发射 ``finished``）。

        Args:
            attr: 保存 ``QPropertyAnimation`` 的实例属性名。
        """
        anim = getattr(self, attr, None)
        setattr(self, attr, None)
        if anim is None:
            return
        try:
            anim.stop()
        except RuntimeError:
            pass
        anim.deleteLater()

    def _animate_morph(
        self,
        target: float,
        finished: Optional[Callable[[], None]] = None,
    ) -> None:
        """播放圆形 ↔ 面板形变动画。

        窗口不可见时不播放（无人观看，也让测试的同步语义保持确定），直接
        落定数值并调用 ``finished``。

        展开方向只用 ``QEasingCurve.OutQuart`` 缓动收敛到终值后直接结束，
        **不**再串联任何缩放脉冲：历史上曾在形变结束后叠加一个
        ``1.0 → 0.982 → 1.008 → 1.0`` 的「落定回弹」，其中 ``1.008`` 越过
        终态尺寸，用户实测表现为面板展开到末期又轻微鼓一下（弹性溢出）。

        Args:
            target: 目标进度（0 = 圆形，1 = 面板）。
            finished: 动画自然结束后的回调（被新动画打断时不触发）。
        """
        self._stop_animation("_morph_anim")
        if not self.isVisible():
            self.morphProgress = target
            if finished is not None:
                finished()
            return

        expanding = target > self._morph
        anim = QPropertyAnimation(self, b"morphProgress", self)
        anim.setDuration(MORPH_DURATION_MS if expanding else COLLAPSE_DURATION_MS)
        anim.setEasingCurve(
            QEasingCurve.OutQuart if expanding else QEasingCurve.InCubic
        )
        anim.setStartValue(self._morph)
        anim.setEndValue(target)
        if finished is not None:
            anim.finished.connect(finished)
        anim.finished.connect(lambda: setattr(self, "_morph_anim", None))
        self._morph_anim = anim
        anim.start()

    def _animate_drag_stretch(self, active: bool) -> None:
        """播放 / 收回拖入胶囊的横向拉伸。

        已展开或窗口不可见时不拉伸（展开面板本身就是完整接收区），直接落定
        进度。拉伸期间 ``_geometry_anim_active`` 为 True，``moveEvent`` 不再
        重启静默吸附定时器（右缘锚定需要每帧移动窗口）。

        Args:
            active: True 拉伸成胶囊，False 收回圆形。
        """
        target = 1.0 if active else 0.0
        self._stop_animation("_drag_anim")
        if self._expanded:
            # 展开面板本身就是完整接收区：不拉伸，只保留高亮。
            self._geometry_anim_active = False
            self.dragProgress = 0.0
            return
        if active:
            # 拉伸前按当前折叠位置重算固定边（收回时沿用同一组值，
            # 否则胶囊缩回圆形时可能滑到另一侧）。
            self._update_anchor()
        if not self.isVisible():
            self._geometry_anim_active = False
            self.dragProgress = target
            return
        if self._drag_progress == target:
            self._geometry_anim_active = False
            return

        self._settle_timer.stop()
        self._geometry_anim_active = True
        anim = QPropertyAnimation(self, b"dragProgress", self)
        anim.setDuration(DRAG_STRETCH_DURATION_MS)
        anim.setEasingCurve(
            QEasingCurve.OutCubic if active else QEasingCurve.InOutCubic
        )
        anim.setStartValue(self._drag_progress)
        anim.setEndValue(target)
        anim.finished.connect(self._on_geometry_anim_finished)
        self._drag_anim = anim
        anim.start()

    def _on_geometry_anim_finished(self) -> None:
        """几何形变动画结束：解除 ``moveEvent`` 抑制并清空句柄。"""
        self._geometry_anim_active = False
        self._drag_anim = None

    def _animate_hover(self, target: float) -> None:
        """播放悬停微光过渡（窗口不可见时直接落定）。

        Args:
            target: 1.0 进入悬停，0.0 离开。
        """
        self._stop_animation("_hover_anim")
        if not self.isVisible():
            self.hoverProgress = target
            return
        anim = QPropertyAnimation(self, b"hoverProgress", self)
        anim.setDuration(HOVER_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(self._hover_progress)
        anim.setEndValue(target)
        anim.finished.connect(lambda: setattr(self, "_hover_anim", None))
        self._hover_anim = anim
        anim.start()

    def _animate_pulse(
        self,
        keys: Sequence[tuple],
        duration: int,
        easing: QEasingCurve.Type = QEasingCurve.OutCubic,
    ) -> None:
        """播放卡片缩放关键帧动画（按压 / 回弹）。

        Args:
            keys: ``(时间占比, 缩放倍率)`` 序列，首尾应分别覆盖 0 与 1。
            duration: 动画时长（ms）。
            easing: 段间缓动曲线。
        """
        self._stop_animation("_pulse_anim")
        if not self.isVisible():
            self.pulseScale = keys[-1][1]
            return
        anim = QPropertyAnimation(self, b"pulseScale", self)
        anim.setDuration(duration)
        anim.setEasingCurve(easing)
        for position, value in keys:
            anim.setKeyValueAt(float(position), float(value))
        anim.finished.connect(lambda: setattr(self, "_pulse_anim", None))
        self._pulse_anim = anim
        anim.start()

    def _play_success_bounce(self) -> None:
        """播放「文件已接收」的 squish & bounce 弹性缩放。"""
        self._animate_pulse(
            (
                (0.0, 1.0),
                (0.16, 0.90),
                (0.40, 1.10),
                (0.62, 0.975),
                (0.82, 1.02),
                (1.0, 1.0),
            ),
            SUCCESS_BOUNCE_MS,
        )

    def _play_receive_press(self) -> None:
        """播放「面板已展开时又拖入文件」的轻微下压确认（关键帧全程 ≤ 1.0）。

        只做一次下压再回到终值，不产生越过终态尺寸的弹性抖动；展开形变本身
        不再叠加任何缩放脉冲（见 :meth:`_animate_morph`）。
        """
        self._animate_pulse(
            ((0.0, 1.0), (0.45, 0.982), (1.0, 1.0)),
            240,
        )

    # ── 入场 / 出场（整体缩放 + 透明度）──────────────────────────

    def _play_entrance(self) -> None:
        """播放首次入场：整体缩放（``0.92 → 1.0``）+ 透明度（``0 → 1``）。

        两段动画并行、均用非线性缓动（缩放 ``OutQuart``、透明度
        ``OutCubic``），避免浮窗硬切入桌面。只播一次（``_shown_once`` 门）；
        入场预算已耗尽（:meth:`_on_entrance_budget_exceeded`）或窗口不可见时
        直接落定终态，不播动画。
        """
        self._stop_animation("_entrance_anim")
        if self._entrance_expired or not self.isVisible():
            self._settle_entrance()
            return

        self._pulse = ENTRANCE_SCALE_FROM
        self._fade = 0.0
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"fadeProgress", group)
        fade.setDuration(ENTRANCE_DURATION_MS)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        scale = QPropertyAnimation(self, b"pulseScale", group)
        scale.setDuration(ENTRANCE_DURATION_MS)
        scale.setEasingCurve(QEasingCurve.OutQuart)
        scale.setStartValue(ENTRANCE_SCALE_FROM)
        scale.setEndValue(1.0)
        group.addAnimation(fade)
        group.addAnimation(scale)
        group.finished.connect(self._on_entrance_finished)
        self._entrance_anim = group
        group.start()

    def _on_entrance_finished(self) -> None:
        """入场动画自然结束：落定终态并解除启动预算守护。"""
        self._entrance_anim = None
        self._settle_entrance()

    def _settle_entrance(self) -> None:
        """把入场强制收尾到终态（缩放 / 透明度归 1，停预算守护；幂等）。"""
        self._entrance_done = True
        self._stop_animation("_entrance_anim")
        self._entrance_guard.stop()
        self.pulseScale = 1.0
        self.fadeProgress = 1.0
        try:
            self.setWindowOpacity(1.0)
        except RuntimeError:
            pass
        self.update()

    def _on_entrance_budget_exceeded(self) -> None:
        """启动预算耗尽：后续入场一律不播（若正在播则立即拆到终态）。

        典型场景：窗口迟迟未 show（启动慢 / 被主窗口启动遮罩延后），此时
        入场动画对用户已无意义，硬切入即可——不能让一个小浮窗拖累启动。
        """
        self._entrance_expired = True
        if not self._entrance_done:
            self._settle_entrance()

    def _abort_entrance(self) -> None:
        """中止入场但保留当前透明度 / 缩放（作为出场起点，避免闪一下全显）。"""
        self._entrance_done = True
        self._stop_animation("_entrance_anim")
        self._entrance_guard.stop()

    def request_close_with_animation(
        self, finished: Optional[Callable[[], None]] = None
    ) -> None:
        """请求带出场动画关闭（非阻塞、幂等）。

        行为：未上屏 / 入场预算已耗尽 → 立即 ``close()``；否则先播放
        「整体缩放 + 透明度」出场（若面板展开则先折回圆形，避免内容与卡片
        错位），动画结束后才真正关闭。``finished`` 回调在关闭之后执行，供调用
        方 ``deleteLater``。整个过程受 :data:`EXIT_BUDGET_MS` 兜底。

        Args:
            finished: 关闭完成后执行的回调（可选；多个调用方的回调都会执行）。
        """
        if finished is not None:
            self._exit_waiters.append(finished)
        if self._exit_requested:
            return
        self._exit_requested = True
        self._entrance_guard.stop()
        # 无人观看（未显示 / 入场预算耗尽）：不播动画，立即关
        if not self.isVisible() or self._entrance_expired:
            self._finish_exit()
            return
        self._abort_entrance()
        if self._expanded:
            # 先把面板收回圆形：否则卡片缩小时子控件内容不跟着缩，会错位
            self.set_expanded(False)
            if self._collapse_pending:
                # 收拢动画结束（_finish_collapse）中会接上出场淡出
                return
        self._play_exit_fade()

    def _play_exit_fade(self) -> None:
        """播放出场：整体缩放（``1.0 → 0.92``）+ 透明度（``1 → 0``），结束后关闭。"""
        if self._exit_finished or self._exit_anim is not None:
            return
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"fadeProgress", group)
        fade.setDuration(EXIT_DURATION_MS)
        fade.setEasingCurve(QEasingCurve.InCubic)
        fade.setStartValue(self._fade)
        fade.setEndValue(0.0)
        scale = QPropertyAnimation(self, b"pulseScale", group)
        scale.setDuration(EXIT_DURATION_MS)
        scale.setEasingCurve(QEasingCurve.InCubic)
        scale.setStartValue(self._pulse)
        scale.setEndValue(EXIT_SCALE_TO)
        group.addAnimation(fade)
        group.addAnimation(scale)
        group.finished.connect(self._finish_exit)
        self._exit_anim = group
        # 退出兜底：超时直接关（保住「不拖累主程序退出」的底线）
        if self._exit_guard is None:
            self._exit_guard = QTimer(self)
            self._exit_guard.setSingleShot(True)
            self._exit_guard.timeout.connect(self._finish_exit)
        self._exit_guard.start(EXIT_BUDGET_MS)
        group.start()

    def _finish_exit(self) -> None:
        """出场收尾：停动画 / 复位视觉 / 关闭窗口，并执行全部关闭回调（幂等）。"""
        if self._exit_finished:
            return
        self._exit_finished = True
        if self._exit_guard is not None:
            self._exit_guard.stop()
        self._stop_animation("_exit_anim")
        try:
            self.close()
        except RuntimeError:
            pass
        # close 之后再复位视觉（否则会先以全不透明重绘一帧再消失）
        self._pulse = 1.0
        self._fade = 1.0
        callbacks, self._exit_waiters = self._exit_waiters, []
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001 - 关闭回调失败不影响退出
                debug(f"浮窗关闭回调失败：{exc}")

    def is_exit_finished(self) -> bool:
        """返回出场流程（含动画）是否已彻底结束。

        Returns:
            bool: 已关闭 / 动画已收尾为 True。
        """
        return self._exit_finished

    def wait_for_exit_animation(self, timeout_ms: int = EXIT_BUDGET_MS) -> bool:
        """有界等待出场流程结束（绝不无上限阻塞调用方）。

        供主窗口在退出前调用：正常仅等待 ~200–400ms（展开态会先收拢再淡出），
        最长不超过 ``timeout_ms``（默认 :data:`EXIT_BUDGET_MS`）；未在出场 /
        已关闭时立即返回。用短定时轮询 ``_exit_finished`` 而非监听单个动画，
        因为「展开态出场」是「收拢 → 淡出」两段动画串起来的。

        Args:
            timeout_ms: 最长等待毫秒数。

        Returns:
            bool: True 表示已彻底结束；False 表示未在出场或等待超时。
        """
        if self._exit_finished:
            return True
        if not self._exit_requested or timeout_ms <= 0:
            return False

        loop = QEventLoop()
        # 定时器不挂父对象：即使窗口在等待期间被销毁，也能保证循环退出。
        budget = QTimer()
        budget.setSingleShot(True)
        budget.timeout.connect(loop.quit)
        budget.start(int(timeout_ms))
        poll = QTimer()
        poll.setInterval(10)

        def _check_finished() -> None:
            if self._exit_finished:
                loop.quit()

        poll.timeout.connect(_check_finished)
        poll.start()
        # 窗口被销毁（如 teardown 的 deleteLater）也要立即结束等待
        try:
            self.destroyed.connect(loop.quit)
        except (RuntimeError, TypeError):
            pass
        loop.exec()
        budget.stop()
        poll.stop()
        poll.deleteLater()
        budget.deleteLater()
        return self._exit_finished

    def _reset_drag_state(self) -> None:
        """立即收回拖入胶囊形态（展开 / 收拢前调用，不播放动画）。"""
        self._stop_animation("_drag_anim")
        self._geometry_anim_active = False
        self._drag_progress = 0.0

    # ── 右键菜单 ────────────────────────────────────────────────

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """右键菜单：打开主窗口 / 清空全部文件池内容 / 本次启动期间隐藏。

        子控件（面板标题 / 条目行）不消费右键事件，事件会沿父链冒泡到本窗，
        因此折叠态圆形与展开态面板上右键行为一致。

        Args:
            event: 右键菜单事件。
        """
        self._build_context_menu().exec(event.globalPos())
        event.accept()

    def _build_context_menu(self) -> StyledContextMenu:
        """构建浮窗右键菜单（样式走 styled 系列组件）。

        Returns:
            StyledContextMenu: 已挂好三个动作的菜单（调用方负责 ``exec``）。
        """
        menu = StyledContextMenu(parent=self)
        pool = self._host_file_pool()
        menu.add_item(
            "打开主窗口",
            callback=lambda: self._defer(self._activate_host_window),
        )
        menu.add_item(
            "清空全部文件池内容",
            danger=True,
            disabled=not self._pool_has_items(pool),
            callback=lambda: self._defer(self._clear_pool_with_confirmation),
        )
        menu.add_separator()
        menu.add_item(
            "本次启动期间隐藏",
            callback=lambda: self._defer(self.hide_for_session),
        )
        return menu

    @staticmethod
    def _defer(callback: Callable[[], None]) -> None:
        """把菜单动作推迟到下一轮事件循环（先让菜单收起，避免重入）。

        Args:
            callback: 待执行的动作。
        """
        QTimer.singleShot(0, callback)

    def _host_file_pool(self) -> Optional[QWidget]:
        """返回宿主的文件池控件（无宿主 / 已销毁时为 None）。

        Returns:
            FilePoolLayout | None: 主池控件（不重建强类型依赖，仅鸭子类型使用）。
        """
        host = self._host_window
        if host is None:
            return None
        try:
            return getattr(host, "_file_pool", None)
        except RuntimeError:
            self._host_window = None
            return None

    @staticmethod
    def _pool_has_items(pool: Optional[QWidget]) -> bool:
        """判定主池是否有条目（无池 / 读取失败一律视为空）。

        Args:
            pool: 主池控件（可为 None）。

        Returns:
            bool: 有内容为 True。
        """
        if pool is None:
            return False
        try:
            return bool(getattr(pool, "items", None))
        except RuntimeError:
            return False

    def _activate_host_window(self) -> None:
        """把宿主主窗口从最小化 / 后台切到前台并获得焦点。"""
        host = self._host_window
        if host is None:
            return
        try:
            if host.isMinimized():
                host.showNormal()
            host.raise_()
            host.activateWindow()
            handle = host.windowHandle()
            if handle is not None:
                handle.requestActivate()
            debug("[floating_pool] 已请求激活主窗口")
        except RuntimeError:
            self._host_window = None

    def _clear_pool_with_confirmation(self) -> None:
        """拉主窗口的「确认清空」弹窗并执行清空（复用主池的确认链路）。"""
        pool = self._host_file_pool()
        if pool is None:
            return
        # 先把主窗口抬到前台：确认弹窗属于主窗口，后台窗口的弹窗会被淹没。
        self._activate_host_window()
        try:
            pool.clear_all()
        except RuntimeError:
            pass
        except Exception as exc:  # noqa: BLE001 - 菜单动作失败不得影响浮窗
            warning(f"浮窗右键清空文件池失败：{exc}")

    def hide_for_session(self) -> None:
        """本次启动期间隐藏：通知宿主后播出场动画并关闭（不写入设置）。

        宿主收到 :attr:`hide_for_session_requested` 后仅关闭本会话的启用意图
        并释放引用；下次启动仍按用户设置正常加载。重复调用幂等。
        """
        self.hide_for_session_requested.emit()
        self.request_close_with_animation(self.deleteLater)

    # ── 悬停 ────────────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        """鼠标进入：点亮圆形入口的微光。

        Args:
            event: 进入事件（交回基类处理）。
        """
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开：熄灭微光并解除按压待决状态。

        Args:
            event: 离开事件（交回基类处理）。
        """
        self._animate_hover(0.0)
        self._press_pos = None
        super().leaveEvent(event)

    # ── 外部拖入 ────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """外部 URL 拖入窗口时接受、点亮高亮并横向拉伸为胶囊。

        折叠 / 展开两态一律接受；``mimeData().hasUrls()`` 之外的内容
        （纯文本等）交回基类处理。

        Args:
            event: 拖入事件。
        """
        self._drag_move_logged = False
        mime = event.mimeData()
        has_urls = mime.hasUrls()
        debug(f"浮窗拖入进入：hasUrls={has_urls} | formats={mime.formats()}")
        if has_urls:
            event.acceptProposedAction()
            self._set_drag_highlight(True)
            urls = mime.urls()
            debug(
                f"浮窗拖入进入：已接受，url 数={len(urls)} | "
                + " ; ".join(url.toString() for url in urls)
            )
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """拖拽移动中持续接受 URL 拖入。

        展开态 drop 落在条目行或背景上不作区分，统一入池。

        Args:
            event: 拖拽移动事件。
        """
        if not self._drag_move_logged:
            self._drag_move_logged = True
            mime = event.mimeData()
            debug(
                f"浮窗拖拽移动：hasUrls={mime.hasUrls()} | formats={mime.formats()}"
            )
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """拖拽离开窗口时清除高亮并收回胶囊。

        Args:
            event: 拖拽离开事件。
        """
        debug("浮窗拖拽离开：清除拖放高亮")
        self._drag_move_logged = False
        self._set_drag_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """处理外部 URL 放下：逐个构建文件信息并发射 ``add_file_requested``。

        依次遍历 ``mimeData().urls()``：``toLocalFile()`` 为空、路径不存在、
        同一事件内重复或 ``build_file_info`` 返回 ``None`` 的条目一律跳过。
        处理完全部 URL 后清除高亮；若有条目成功发射且当前为折叠态，则播放
        接收回弹并自动展开窗口。本方法**只发射信号**，不触碰主池数据源。

        Args:
            event: 拖放事件。
        """
        mime = event.mimeData()
        emitted = 0
        if mime.hasUrls():
            urls = mime.urls()
            debug(f"浮窗拖放落下：收到 url 数={len(urls)}")
            emitted = self._emit_dropped_urls(urls)
            event.acceptProposedAction()
        else:
            debug(
                "浮窗拖放落下：载荷不含 URL，忽略 | "
                f"hasUrls={mime.hasUrls()} | formats={mime.formats()}"
            )
        self._set_drag_highlight(False)
        self._finish_external_drop(emitted)
        debug(f"浮窗拖放处理完成：emitted={emitted}")

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
            raw_url = url.toString()
            file_path = url.toLocalFile()
            debug(f"拖入项解析：url={raw_url} | toLocalFile={file_path}")
            if not file_path:
                warning(f"跳过拖入项：toLocalFile() 为空（url={raw_url}）")
                continue
            if file_path in seen:
                warning(
                    f"跳过拖入项：事件内重复（url={raw_url} / path={file_path}）"
                )
                continue
            seen.add(file_path)
            if not os.path.exists(file_path):
                warning(
                    "跳过拖入项：路径不存在(os.path.exists=False)"
                    f"（url={raw_url} / path={file_path}）"
                )
                continue
            file_info = StagingPoolService.build_file_info(file_path)
            if file_info is None:
                warning(
                    "跳过拖入项：build_file_info 返回 None"
                    f"（url={raw_url} / path={file_path}）"
                )
                continue
            self.add_file_requested.emit(file_info)
            emitted += 1
            debug(f"拖入项已发射 add_file_requested：path={file_path}")
        return emitted

    def _finish_external_drop(self, emitted: int) -> None:
        """外部拖放收尾：有成功入池条目且处于折叠态时回弹并自动展开。

        OLE ``dropEvent`` 与提权兜底（:meth:`_elevated_drop_accept_paths`）
        共用，保证两条链路行为一致。回弹在展开形变之前起跑（缩放作用于
        圆形入口），随后卡片向外扩散并露出列表，形成「接住 → 摊开」的
        连续观感。

        Args:
            emitted: 本次拖放实际发射 ``add_file_requested`` 的次数。
        """
        if not emitted:
            return
        if self.is_expanded():
            self._play_receive_press()
            return
        self._play_success_bounce()
        self.set_expanded(True)

    def _elevated_drop_accept_paths(self, paths: list[str]) -> None:
        """提权兜底入口：把原生 ``WM_DROPFILES`` 路径按 OLE 拖入同口径处理。

        路径先转 ``QUrl`` 以复用 :meth:`_emit_dropped_urls` 的全部过滤 / 事件内
        去重 / ``build_file_info`` 构建语义，再走 :meth:`_finish_external_drop`
        的统一收尾。整窗都是接收区（``_elevated_drop_accepts_point`` 用默认实现）。

        Args:
            paths: 原生兜底解析出的本地路径列表。
        """
        debug(f"浮窗提权兜底拖入：收到路径数={len(paths)}")
        emitted = self._emit_dropped_urls([QUrl.fromLocalFile(p) for p in paths])
        self._finish_external_drop(emitted)
        debug(f"浮窗提权兜底拖放处理完成：emitted={emitted}")

    def _set_drag_highlight(self, active: bool) -> None:
        """切换拖放高亮的 ``dragActive`` 动态属性并请求重绘。

        本窗口为手动自绘（非 QSS 样式控件），故只置属性 + ``update()``，
        不走 ``unpolish`` / ``polish``；同时播放 / 收回胶囊拉伸。

        Args:
            active: True 点亮高亮，False 清除。
        """
        active = bool(active)
        if bool(self.property("dragActive")) == active:
            return
        self.setProperty("dragActive", active)
        self._animate_drag_stretch(active)
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
        而非追加；完成后把 ``self._pending_items`` 复位为 ``None``，并同步
        折叠态计数徽标。
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
        self._count = valid
        self._pending_items = None
        self.update()

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
        """可拖动区左键按下：展开态立即移动，折叠态记录起点 + 按下压缩。

        展开态标题栏按下即 ``_start_system_move()``；折叠态
        按下只记录起点并播放轻微压缩，是否移动 / 展开延后到移动 / 释放
        事件仲裁。

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
                self._animate_pulse(((0.0, 1.0), (1.0, 0.955)), 110)
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
                self._animate_pulse(((0.0, 0.955), (1.0, 1.0)), 160)
                self._start_system_move()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """折叠态待决手势：未超阈值释放则回弹并展开窗口。

        Args:
            event: 鼠标事件。
        """
        if self._press_pos is not None and event.button() == Qt.LeftButton:
            self._press_pos = None
            self._animate_pulse(((0.0, 0.955), (0.55, 1.028), (1.0, 1.0)), 260)
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
        （动画 / 初始化等程序化移动）或 ``_geometry_anim_active`` 为 True
        （拖入胶囊拉伸的右缘锚定位移）时不重启，避免自触发循环。

        Args:
            event: 移动事件（交回基类处理）。
        """
        super().moveEvent(event)
        if self._internal_moving or self._geometry_anim_active:
            return
        self._settle_timer.start(SETTLE_DELAY_MS)

    def _settle_and_snap(self) -> None:
        """移动静默结束后：先完整夹回屏内，再按阈值四边吸附，最后动画位移。

        取窗口几何中心所在屏幕（``screenAt`` → ``primaryScreen`` 回退）的
        真实工作区（:func:`screen_work_area`）；无可用屏幕时静默返回。夹回
        保证窗口四边都落在工作区内；吸附仅在 :meth:`is_snap_enabled` 为 True
        时对左 / 右 / 上 / 下四条边分别判定（外边缘距对应边 ≤ ``SNAP_THRESHOLD``
        时吸到 ``INITIAL_INSET`` 留白处）。目标位置经 :meth:`_animate_move`
        缓动移动；目标与当前位置相同时不产生动画。``_internal_moving`` 为
        True 时早退。
        """
        if self._internal_moving:
            return
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen_work_area(screen)
        if not avail.isValid():
            return
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

    视觉上对齐主界面卡片语言：8px 圆角、悬停时铺 ``tm.hover_veil`` 并浮出
    强调色描边；文字层级用 ``tm.text`` / ``tm.text_hint``，与
    ``file_card_delegate`` 的标题 / 副标题口径一致。仅承载展示信息，**无**
    点击 / 右键语义；实现「拖出复制」手势——左键按下记录起点，位移超过
    ``QApplication.startDragDistance()`` 后委托给窗口（``self.window()``，
    ``isinstance`` 守卫）启动 ``QDrag``。共享拖拽状态（``_drag_active`` /
    ``_pending_items`` / ``_debounce_timer``）留在窗口，故本行只做阈值检测
    与委托。

    Attributes:
        file_info: 原始文件信息字典（引用，拖出手势复用）。
        path: 文件路径字符串（空路径条目不会构造本行）。
        _press_pos: 左键按下的行本地起点；``None`` 表示无待决拖出手势。
        _hovered: 鼠标是否悬停在本行（决定悬停覆盖层绘制）。
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
        self._hovered = False
        self.setFixedHeight(_ROW_HEIGHT)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(self.path)
        self.setCursor(Qt.OpenHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(10)

        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(48, 48)
        self._icon_label.setAlignment(Qt.AlignCenter)
        pixmap = self._load_icon()
        if pixmap is not None and not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        layout.addWidget(self._icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self._name_label = QLabel(self._display_name(), self)
        self._name_label.setFont(_ui_font(12, QFont.Weight.Medium))
        self._name_label.setTextFormat(Qt.PlainText)
        # 长文件名不得反向撑宽行（滚动区已关横向滚动）
        self._name_label.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Preferred
        )
        text_layout.addWidget(self._name_label)

        self._size_label = QLabel(
            StagingPoolService.format_file_size(file_info.get("size")), self
        )
        self._size_label.setFont(_ui_font(10))
        if not self._size_label.text():
            self._size_label.hide()
        text_layout.addWidget(self._size_label)

        layout.addLayout(text_layout, 1)

        self._apply_label_styles()
        self._apply_elide()

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

    def _apply_label_styles(self) -> None:
        """按当前主题重注册名称 / 大小标签颜色（文字层级与主卡片一致）。"""
        register_widget_qss(
            self._name_label,
            "background: transparent; border: none;"
            f" color: {tm.text.name()};",
        )
        register_widget_qss(
            self._size_label,
            "background: transparent; border: none;"
            f" color: {tm.text_hint.name()};",
        )

    def _apply_elide(self) -> None:
        """按当前行宽对显示名做中段省略（避免长文件名撑破面板）。"""
        available = self._name_label.width()
        if available <= 8:
            available = max(24, self.width() - (8 + 48 + 10 + 10))
        metrics = QFontMetrics(self._name_label.font())
        elided = metrics.elidedText(
            self._display_name(), Qt.ElideMiddle, available
        )
        if elided != self._name_label.text():
            self._name_label.setText(elided)

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

    def refresh_icon(self) -> None:
        """按当前主题重取并回填图标、刷新文字配色与省略状态。

        重取失败（异常 / 空 pixmap）时清空图标回退，绝不抛出以保护主题
        刷新链路。
        """
        self._apply_label_styles()
        self._apply_elide()
        pixmap = self._load_icon()
        if pixmap is not None and not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        else:
            self._icon_label.clear()
        self.update()

    # ── 绘制 ────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制行卡片底：静息为极淡填充，悬停铺覆盖层并浮出强调色描边。

        Args:
            event: 绘制事件（未直接使用）。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        if self._hovered:
            painter.setPen(QPen(tm.alpha_of(tm.accent, 45), 1))
            painter.setBrush(tm.hover_veil)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(
                tm.alpha_of(tm.text, 5 if tm.is_dark_theme() else 4)
            )
        painter.drawRoundedRect(rect, _ROW_RADIUS, _ROW_RADIUS)
        painter.end()

    def enterEvent(self, event) -> None:
        """鼠标进入：点亮行悬停态。

        Args:
            event: 进入事件（交回基类处理）。
        """
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开：熄灭行悬停态。

        Args:
            event: 离开事件（交回基类处理）。
        """
        self._hovered = False
        self._press_pos = None
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """行宽变化时重算文件名省略。

        Args:
            event: 尺寸变化事件（交回基类处理）。
        """
        super().resizeEvent(event)
        self._apply_elide()

    # ── 拖出手势 ────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键按下记录拖出起点；其余按钮交回基类。

        Args:
            event: 鼠标事件。
        """
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
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
        """释放清空拖出起点并恢复手型光标，交回基类。

        Args:
            event: 鼠标事件。
        """
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class _EmptyState(QWidget):
    """展开态空池引导：自绘拖放图标 + 两级文案（与面板同色阶）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """构造空态控件。

        Args:
            parent: 父控件（通常为 ``_rows_container``）。
        """
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def sizeHint(self) -> QSize:
        """返回空态控件的建议尺寸。

        ``_rows_layout`` 开了 ``SetMinAndMaxSize``，容器的最大高度即布局 size
        hint；返回固定高度才能让空态在列表区里垂直居中，而不是被锁在顶部。

        Returns:
            QSize: 建议尺寸（高度足以容纳图标 + 两级文案并留出上留白）。
        """
        return QSize(200, 260)

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制居中的拖放图标与引导文案。

        Args:
            event: 绘制事件（未直接使用）。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        width = float(self.width())
        center_y = self.height() / 2.0

        side = 34.0
        render_icon(
            painter,
            "download",
            QRectF((width - side) / 2.0, center_y - 62.0, side, side),
            tm.alpha_of(tm.text_hint, 62),
            1.4,
        )

        painter.setFont(_ui_font(12, QFont.Weight.Medium))
        painter.setPen(tm.text_hint)
        painter.drawText(
            QRectF(0.0, center_y - 18.0, width, 20.0),
            Qt.AlignCenter,
            EMPTY_HINT_TEXT,
        )

        painter.setFont(_ui_font(10))
        painter.setPen(tm.alpha_of(tm.text_hint, 62))
        painter.drawText(
            QRectF(0.0, center_y + 6.0, width, 18.0),
            Qt.AlignCenter,
            EMPTY_HINT_SUB_TEXT,
        )
        painter.end()
