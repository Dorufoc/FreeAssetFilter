"""
共享预览器顶栏框架 — 参考 Windows 照片查看器（Photos）功能栏布局。

横向结构：:

    ┌─────────────────────────────────────────────────────────────┐
    │ [目录类]  │ [ 左子组 | 居中信息 | 右子组 | 更多⋯ ] │ [全屏类] │
    └─────────────────────────────────────────────────────────────┘

- 目录类功能（如 PDF 索引）固定在功能栏**最左侧**（``add_left``）；
- 全屏显示类功能固定在**最右侧**（``add_right``）；
- 其余操作功能统一放入**顶部居中按钮组**（``add_leading`` /
  ``add_trailing``），**整组（按钮 + 信息标签 + 更多）作为一个整体在
  顶栏可用区域内水平居中**；窗口变窄时按优先级
  （``set_overflow_priority``）逐项折叠进「更多(⋯)」菜单，窗口恢复后
  自动还原；
- 信息标签（页码 / 字数行数 / GIF 播放键等）经 ``set_info_widget``
  注册后位于整组中部、**永不折叠**；每次布局后可调用
  ``info_available_width()`` 查询自身可用宽度，用于「缩小字号 /
  折成两行」等自适应显示，且不遮挡内容；
- 顶栏自身**完全透明**，不绘制任何背景色与边框。

四个预览器（PDF / 文本 / 图片 / 字体）共用本组件，取代原先各自复制的
``_ToolbarFrame``。
"""

import sys
from pathlib import Path
from typing import Optional

# 独立运行时的 sys.path 引导（在模块级导入前执行）
_this_file = Path(__file__).resolve()
_ui_root = str(_this_file.parent.parent.parent)  # freeassetfilter/ui/
if _ui_root not in sys.path:
    sys.path.insert(0, _ui_root)
_project_root = str(_this_file.parent.parent.parent.parent.parent)  # 项目根
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from PySide6.QtCore import QEvent, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QWidget

from components.styled_button import StyledButton
from freeassetfilter.core._paths import icons_dir
from freeassetfilter.ui.components.styled_context_menu import StyledContextMenu


class PreviewToolbarFrame(QFrame):
    """预览器顶栏框架（左目录 / 中功能组 / 右全屏，透明无背景）。

    详见模块 docstring。
    """

    # 布局状态发生变化时发出（折叠 / 展开 / 空间重分配后），
    # 供居中的信息标签做自适应显示（缩字号 / 折行 / 省略）。
    layout_changed = Signal()

    _EDGE = 8     # 左右边缘内边距
    _GAP = 6      # 控件间距
    _MORE_W = 32  # 「更多」按钮宽度
    _MAX = 16777215  # 解除最大宽度限制

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 横向不参与最小尺寸约束：空间不足时的折叠/裁剪由 reflow 自行处理，
        # 避免把「所有按钮可见时」的宽最小宽度传导给外层窗口 / 分割器，
        # 否则窗口永远无法缩窄、折叠逻辑将永远不会触发。
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._left_widgets: list[QWidget] = []
        self._right_widgets: list[QWidget] = []
        self._lead_widgets: list[QWidget] = []
        self._trail_widgets: list[QWidget] = []
        self._overflow_priority: list[QWidget] = []
        self._folded: list[QWidget] = []
        self._info_widget: Optional[QWidget] = None
        self._info_avail = self._MAX
        self._applied_sig: Optional[tuple] = None
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow)
        self._reflowing = False

        # ── 中部按钮组容器：左右各一条等比例弹簧，使整组在可用区域内居中 ──
        self._center_layout = QHBoxLayout(self)
        self._center_layout.setContentsMargins(self._EDGE, 6, self._EDGE, 6)
        self._center_layout.setSpacing(self._GAP)
        self._center_layout.addStretch(1)

        self._lead_box = QWidget(self)
        self._lead_layout = QHBoxLayout(self._lead_box)
        self._lead_layout.setContentsMargins(0, 0, 0, 0)
        self._lead_layout.setSpacing(self._GAP)
        self._center_layout.addWidget(self._lead_box)

        # 居中的信息标签槽位（永不折叠，位于组内自然位置）
        self._info_holder = QWidget(self)
        self._info_layout = QHBoxLayout(self._info_holder)
        self._info_layout.setContentsMargins(0, 0, 0, 0)
        self._info_layout.setSpacing(0)
        self._center_layout.addWidget(self._info_holder)

        self._trail_box = QWidget(self)
        self._trail_layout = QHBoxLayout(self._trail_box)
        self._trail_layout.setContentsMargins(0, 0, 0, 0)
        self._trail_layout.setSpacing(self._GAP)
        self._center_layout.addWidget(self._trail_box)

        self._center_layout.addStretch(1)

        # 「更多(⋯)」溢出按钮：折叠发生时显示，点击弹出被折叠功能的菜单
        self._more_btn = StyledButton(
            "", variant="ghost", size="sm", icon=str(icons_dir() / "more.svg")
        )
        self._more_btn.setFixedSize(self._MORE_W, 32)
        self._more_btn.setToolTip("更多功能")
        self._more_btn.hide()
        self._more_btn.clicked.connect(self._open_overflow_menu)
        self._trail_layout.addWidget(self._more_btn)

    # ── 公共注册 API ─────────────────────────────────────────────

    def add_left(self, widget: QWidget) -> None:
        """注册一个功能栏最左侧控件（目录类功能，如 PDF 索引）。"""
        self._left_widgets.append(widget)
        widget.setParent(self)
        widget.show()
        widget.installEventFilter(self)
        self.request_reflow()

    def add_right(self, widget: QWidget) -> None:
        """注册一个功能栏最右侧控件（全屏显示类功能）。"""
        self._right_widgets.append(widget)
        widget.setParent(self)
        widget.show()
        widget.installEventFilter(self)
        self.request_reflow()

    def add_leading(self, widget: QWidget) -> None:
        """往中部按钮组的左段添加一个操作控件（可折叠进「更多」菜单）。"""
        self._lead_widgets.append(widget)
        widget.setParent(self._lead_box)
        self._lead_layout.addWidget(widget)
        widget.installEventFilter(self)
        self.request_reflow()

    def add_trailing(self, widget: QWidget) -> None:
        """往中部按钮组的右段添加一个操作控件（可折叠进「更多」菜单）。"""
        self._trail_widgets.append(widget)
        widget.setParent(self._trail_box)
        # 「更多」按钮固定在右段末尾，新控件插到它前面
        self._trail_layout.insertWidget(self._trail_layout.count() - 1, widget)
        widget.installEventFilter(self)
        self.request_reflow()

    def set_info_widget(self, widget: Optional[QWidget]) -> None:
        """设置居中的信息标签控件（页码 / 字数行数等，永不折叠）。"""
        if self._info_widget is widget:
            return
        self._info_widget = widget
        if widget is not None:
            widget.setParent(self._info_holder)
            self._info_layout.addWidget(widget)
            widget.setMinimumWidth(0)
            widget.installEventFilter(self)
        self.request_reflow()

    def set_overflow_priority(self, widgets: list) -> None:
        """设置折叠优先级：列表中越靠前的控件在空间不足时越先被隐藏。"""
        self._overflow_priority = list(widgets)
        self.request_reflow()

    # ── 查询 / 触发 API ──────────────────────────────────────────

    def info_available_width(self) -> int:
        """返回居中的信息标签当前可用宽度（像素）。

        布局在每次折叠 / 展开后更新；数值极小（≤0）时表示空间不足，
        调用方应自行缩小内容（缩字号 / 折行 / 省略）。
        """
        return self._info_avail

    def request_reflow(self) -> None:
        """请求一次布局重算（多次请求自动合并为一次）。"""
        if not self._reflow_timer.isActive():
            self._reflow_timer.start(0)

    # ── 事件 ─────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.request_reflow()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.request_reflow()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """监听受管控件的显示 / 隐藏 / 尺寸变化，自动重排。"""
        if event.type() in (QEvent.Show, QEvent.Hide, QEvent.Resize):
            self.request_reflow()
        return super().eventFilter(obj, event)

    # ── 宽度测算 ─────────────────────────────────────────────────

    def _natural_w(self, widget: QWidget) -> int:
        """取控件当前自然宽度（优先已布局宽度，其次 sizeHint）。"""
        w = widget.width()
        if w > 0:
            return w
        return widget.sizeHint().width()

    def _included(self, widget: QWidget, chosen: set) -> bool:
        """控件是否参与宽度测算（被折叠项在 ``chosen`` 中视为已展开）。"""
        if not widget.isHidden():
            return True
        return id(widget) in chosen

    def _seq_total(self, items: list, chosen: set) -> int:
        """统计一组控件总宽（含内部间距），只计入 ``_included`` 的控件。"""
        total = 0
        n = 0
        for w in items:
            if not self._included(w, chosen):
                continue
            total += self._natural_w(w)
            n += 1
        return total + self._GAP * max(n - 1, 0)

    def _fold_pool(self) -> list:
        """当前参与折叠决策的控件：可见的或已被我们折叠的（按优先级序）。"""
        return [
            w for w in self._overflow_priority
            if not w.isHidden() or w in self._folded
        ]

    def _info_visible(self, chosen: set) -> bool:
        return (
            self._info_widget is not None
            and self._included(self._info_widget, chosen)
        )

    def _info_width(self, chosen: set) -> int:
        if not self._info_visible(chosen):
            return 0
        return self._natural_w(self._info_widget)

    def _side_totals(
        self, chosen: set, more_shown: bool
    ) -> tuple[int, int, int]:
        """计算左段、右段与信息标签的当前总宽。

        Returns:
            (lead_total, trail_total, info_w)
        """
        lead_total = self._seq_total(self._lead_widgets, chosen)
        trail_items = list(self._trail_widgets)
        if more_shown:
            trail_items.append(self._more_btn)
        trail_total = self._seq_total(trail_items, chosen)
        info_w = self._info_width(chosen)
        return lead_total, trail_total, info_w

    def _estimate(
        self, lead_total: int, trail_total: int, info_w: int
    ) -> int:
        """估算中部内容总宽（整组内容 + 分组间距，无平衡占位）。"""
        parts = []
        if lead_total > 0:
            parts.append(lead_total)
        if info_w > 0:
            parts.append(info_w)
        if trail_total > 0:
            parts.append(trail_total)
        return sum(parts) + self._GAP * max(len(parts) - 1, 0)

    # ── 主流程 ───────────────────────────────────────────────────

    def _place_anchors(self) -> None:
        """将最左 / 最右注册控件贴到两端（垂直居中）。

        这些控件不参与布局，必须显式给定尺寸：优先沿用当前实际宽高；
        否则取固定尺寸（min==max>0），再退回 sizeHint。
        """
        def _dim(widget: QWidget, width: bool) -> int:
            cur = widget.width() if width else widget.height()
            if cur > 0:
                return cur
            mn = widget.minimumWidth() if width else widget.minimumHeight()
            mx = widget.maximumWidth() if width else widget.maximumHeight()
            if mn == mx and mn > 0:
                return mn
            hint = widget.sizeHint().width() if width else widget.sizeHint().height()
            return max(hint, 0)

        x = self._EDGE
        for w in self._left_widgets:
            if w.isHidden():
                continue
            wd, hd = _dim(w, True), _dim(w, False)
            w.setGeometry(x, max((self.height() - hd) // 2, 0), wd, hd)
            x = w.geometry().right() + self._GAP
        x = self.width() - self._EDGE
        for w in reversed(self._right_widgets):
            if w.isHidden():
                continue
            wd, hd = _dim(w, True), _dim(w, False)
            w.setGeometry(x - wd, max((self.height() - hd) // 2, 0), wd, hd)
            x = w.geometry().left() - self._GAP

    def _center_bounds(self) -> tuple[int, int]:
        """计算两侧固定按钮之间可用区域的左右边界。"""
        left_end = self._EDGE
        for w in self._left_widgets:
            if w.isHidden():
                continue
            left_end = max(left_end, w.geometry().right() + self._GAP)
        right_start = self.width() - self._EDGE
        for w in self._right_widgets:
            if w.isHidden():
                continue
            right_start = min(right_start, w.geometry().left() - self._GAP)
        return left_end, right_start

    def _reflow(self) -> None:
        """执行一次完整的折叠 / 布局 / 约束计算。"""
        if self._reflowing or self.width() <= 0:
            return
        self._reflowing = True
        try:
            self._place_anchors()
            left_end, right_start = self._center_bounds()
            avail = max(right_start - left_end, 0)

            # 1) 在保持折叠优先级的前提下，选出空间允许的最大可见子集。
            #    信息标签是「可伸缩」的（其文本可缩字号/折行缩小），因此
            #    折叠判定按 info 宽度为 0 估算：空间优先留给操作按钮，
            #    标签只占用按钮之外的剩余空间。
            pool = self._fold_pool()
            n_pool = len(pool)
            keep = n_pool
            while keep > 0:
                chosen = {id(w) for w in pool[n_pool - keep:]}
                more_shown = n_pool - keep > 0
                lead_total, trail_total, _ = self._side_totals(
                    chosen, more_shown
                )
                if self._estimate(lead_total, trail_total, 0) <= avail:
                    break
                keep -= 1
            chosen = (
                {id(w) for w in pool[n_pool - keep:]}
                if keep > 0 else set()
            )
            folded = pool[: n_pool - keep]
            more_shown = bool(folded)

            # 2) 依据最终可见集合计算居中约束与信息标签可用宽度
            lead_total, trail_total, info_w = self._side_totals(
                chosen, more_shown
            )
            est = self._estimate(lead_total, trail_total, info_w)

            w = self.width()
            fit_symmetric = (
                (w - est) / 2.0 >= left_end and (w + est) / 2.0 <= right_start
            )
            if fit_symmetric:
                ml = mr = self._EDGE
            else:
                ml = max(left_end, 0)
                mr = max(w - right_start, 0)
            region = max(w - ml - mr, 0)

            parts = (1 if lead_total > 0 else 0) + (
                1 if info_w > 0 else 0
            ) + (1 if trail_total > 0 else 0)
            other_w = max(
                est - info_w - (self._GAP if info_w > 0 and parts > 1 else 0),
                0,
            )
            self._set_info_avail(region, other_w)

            # 3) 应用折叠 / 展开与边距（仅在状态变化时重绘）
            to_hide = [w for w in pool if id(w) not in chosen and not w.isHidden()]
            to_show = [w for w in pool if id(w) in chosen and w in self._folded]
            sig = (
                tuple(sorted(id(x) for x in self._folded)),
                tuple(sorted(id(x) for x in folded)),
                ml,
                mr,
                self._info_avail,
            )
            changed = sig != self._applied_sig
            self._applied_sig = sig
            if changed:
                for wgt in to_hide:
                    wgt.hide()
                for wgt in to_show:
                    wgt.show()
                self._folded = list(folded)
                self._more_btn.setVisible(more_shown)
                self._center_layout.setContentsMargins(ml, 6, mr, 6)
                self.layout_changed.emit()
        finally:
            self._reflowing = False

    def _set_info_avail(self, region: int, other_w: int) -> None:
        """把信息标签可用宽度限制为中部区域扣除其他控件后的余量。"""
        avail = max(region - other_w, 0)
        self._info_avail = avail
        if self._info_widget is not None:
            self._info_widget.setMaximumWidth(max(avail, 1))

    # ── 「更多」溢出菜单 ─────────────────────────────────────────

    def _open_overflow_menu(self) -> None:
        """弹出「更多」菜单：列出当前被折叠进菜单的功能。"""
        if not self._folded:
            return
        menu = StyledContextMenu(parent=self)
        for widget in self._folded:
            label = self._menu_label(widget)
            action = menu.add_item(
                label, callback=lambda w=widget: self._invoke(w)
            )
            icon_path = self._icon_path(widget)
            if icon_path:
                action.setIcon(QIcon(icon_path))
        anchor = self._more_btn.mapToGlobal(
            self._more_btn.rect().bottomRight()
        )
        menu.exec(anchor)

    def _menu_label(self, widget: QWidget) -> str:
        """菜单项文案：优先取 tooltip，其次按钮文本 / 下拉当前值。"""
        tip = getattr(widget, "toolTip", None)
        if callable(tip):
            tip_text = tip()
            if tip_text:
                return tip_text
        for attr in ("text", "currentText"):
            fn = getattr(widget, attr, None)
            if callable(fn):
                text = fn()
                if text:
                    return text
        return "功能"

    def _icon_path(self, widget: QWidget) -> str:
        """取可用的 SVG 图标路径（供菜单项显示图标）。"""
        for attr in ("_svg_icon_path", "_icon"):
            value = getattr(widget, attr, None)
            if isinstance(value, str) and value.endswith(".svg"):
                return value
        return ""

    def _invoke(self, widget: QWidget) -> None:
        """触发被折叠控件的功能：按钮走 click()，下拉框尝试展开选项。"""
        click = getattr(widget, "click", None)
        if callable(click):
            click()
            return
        open_popup = getattr(widget, "_open_popup", None)
        if callable(open_popup):
            open_popup()
