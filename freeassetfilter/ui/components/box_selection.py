# -*- coding: utf-8 -*-
"""
文件框选手势共享组件（文件选择器 / 文件储存池通用）。

包含：
- SelectionBandOverlay：自绘选框覆层（半透明填充 + 1px 实线边框），
  鼠标事件全部透传，仅作视觉层；
- BoxSelectionGesture：左键拖拽框选手势状态机（拖拽阈值激活、实时命中
  回调、越界自动滚动、释放丢失守卫、应用失活兜底收尾）。

设计约束：
- 覆层父级为面板视口控件（viewport），坐标系为视口坐标；
- 命中判定与选中态应用由调用方通过 ``hit_test`` / ``on_hits`` 回调注入，
  两个面板复用同一手势逻辑，保证行为一致；
- 框选为替换语义：每次拖拽以当前框内集合为准（不引入 Ctrl 追加模式）。
"""

from __future__ import annotations

from typing import Callable, Optional, Set

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from theme import tm

# 释放丢失守卫轮询周期（毫秒）：框选期间周期性校验左键是否仍按下。
BOX_SELECT_GUARD_INTERVAL_MS: int = 80

# 选框填充透明度（0~255）。
BOX_SELECT_FILL_ALPHA: int = 36


class SelectionBandOverlay(QWidget):
    """自绘框选覆层（替代 QRubberBand，避免平台自绘框叠加）。

    覆层仅为视觉层：鼠标事件一律透传（WA_TransparentForMouseEvents），
    手势状态机只由调用方安装的事件过滤器驱动。
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color: QColor = QColor(tm.accent)
        self.hide()

    def set_color(self, color: QColor) -> None:
        """设置边框/填充基色（主题切换时刷新）。

        Args:
            color: 主题强调色。
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
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, False)
            fill = QColor(color)
            fill.setAlpha(BOX_SELECT_FILL_ALPHA)
            painter.fillRect(self.rect(), fill)
            painter.setPen(QPen(color, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        finally:
            painter.end()


class BoxSelectionGesture(QObject):
    """左键拖拽框选手势状态机。

    生命周期：
    - ``begin(pos)``：左键按下时记录起点（调用方不消费按下事件，保留单击语义）；
    - ``update(pos, pressed)``：拖动超过阈值后激活选框，实时回调命中集合；
    - ``finish(pos)``：松开时收尾，返回本次是否进入过框选态（是则调用方
      消费释放事件，阻止单击/预览等默认语义）。

    兜底机制：
    - 释放丢失守卫：框选期间以 ``BOX_SELECT_GUARD_INTERVAL_MS`` 轮询全局
      左键状态，事件流中断时按最后位置收尾；
    - 应用失活（alt-tab / 切换窗口）时立即收尾，防选框粘连。

    Args:
        parent: 父 QObject（通常为布局面板，负责守卫定时器生命周期）。
        overlay_parent: 选框覆层的父控件（面板视口），坐标系基准。
        scrollbar_getter: 返回垂直滚动条的回调（拖出视口上下边时自动滚动）。
        hit_test: 命中判定回调：接收选框矩形（视口坐标），返回命中集合。
        on_hits: 命中集合变化回调：接收最新命中集合（替换语义）。
    """

    # 手势结束（松开/守卫兜底/应用失活共用）：参数为"是否曾进入框选态"。
    finished = Signal(bool)

    def __init__(
        self,
        parent: QObject,
        overlay_parent: QWidget,
        scrollbar_getter: Optional[Callable[[], object]] = None,
        hit_test: Optional[Callable[[QRect], Set]] = None,
        on_hits: Optional[Callable[[Set], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._scrollbar_getter = scrollbar_getter
        self._hit_test = hit_test
        self._on_hits = on_hits
        self._threshold = max(4, QApplication.startDragDistance())

        self._overlay = SelectionBandOverlay(overlay_parent)
        self._start_pos: Optional[QPoint] = None
        self._last_pos: Optional[QPoint] = None
        self._rect: Optional[QRect] = None
        self._active: bool = False
        self._last_hits: Optional[Set] = None
        self._guard_timer: Optional[QTimer] = None

        try:
            tm.theme_changed.connect(self._refresh_style)
        except (RuntimeError, TypeError, AttributeError):
            # 3.1#19 留档：绑定失败即无主题跟随，属预期防御（不改行为；
            # 后续改进为意外分支补 debug 日志）。
            pass
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_application_state_changed)

    # ── 状态查询 ──────────────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        """是否已进入框选态（超过拖拽阈值）。"""
        return self._active

    @property
    def started(self) -> bool:
        """是否已记录手势起点（按下后尚未松开的任一阶段）。"""
        return self._start_pos is not None or self._active

    @property
    def rect(self) -> Optional[QRect]:
        """当前选框矩形（视口坐标），未激活时为 None。"""
        return self._rect

    # ── 手势生命周期 ──────────────────────────────────────────────────────

    def begin(self, pos: QPoint) -> None:
        """左键按下：记录手势起点。

        Args:
            pos: 按下位置（视口坐标）。
        """
        self._reset()
        self._start_pos = QPoint(pos)
        self._last_pos = QPoint(pos)

    def update(self, pos: QPoint, button_pressed: bool) -> bool:
        """左键拖动：超过阈值后激活并实时更新命中集合。

        Args:
            pos: 当前鼠标位置（视口坐标，可为视口之外）。
            button_pressed: 当前左键是否仍处于按下态。

        Returns:
            True 表示已进入框选态（调用方应消费该移动事件）。
        """
        if self._start_pos is None:
            return False
        if not button_pressed:
            # 无按键移动：上一次释放丢失导致的状态残留在此自愈收尾。
            self.finish(self._last_pos)
            return False
        self._last_pos = QPoint(pos)
        if not self._active:
            delta = pos - self._start_pos
            if abs(delta.x()) < self._threshold and abs(delta.y()) < self._threshold:
                return False
            self._active = True
            self._rect = None
            self._last_hits = None
            self._show_overlay()
            self._start_guard()
        self._update_geometry(pos)
        self._emit_hits()
        return True

    def finish(self, pos: Optional[QPoint] = None) -> bool:
        """结束手势：按终点补一次命中更新，隐藏选框并复位。

        松开事件与应用失活守卫共用同一收尾路径，避免状态残留在两处分叉。

        Args:
            pos: 收尾位置（视口坐标）；None 时跳过最后一次命中更新。

        Returns:
            本次手势是否曾进入框选态（True 时调用方应消费释放事件）。
        """
        was_active = self._active
        if self._start_pos is not None and pos is not None:
            self._last_pos = QPoint(pos)
            if was_active:
                self._update_geometry(pos)
                self._emit_hits()
        self._reset()
        self.finished.emit(was_active)
        return was_active

    def abort(self) -> None:
        """中止手势并隐藏选框（不改变调用方选中态）。"""
        self._reset()

    # ── 内部：几何 / 命中 / 守卫 ──────────────────────────────────────────

    def _reset(self) -> None:
        """复位全部手势状态并隐藏选框（幂等，可重复调用）。"""
        self._active = False
        self._start_pos = None
        self._rect = None
        self._last_hits = None
        self._stop_guard()
        overlay = self._overlay
        if overlay is not None:
            try:
                overlay.hide()
            except RuntimeError:
                # 3.1#19 留档：宿主销毁后的预期防御（后续改进补 debug 日志）。
                pass

    def _show_overlay(self) -> None:
        """首次激活：把选框定锚在起点（0×0）并置顶显示。"""
        overlay = self._overlay
        if overlay is None or self._start_pos is None:
            return
        try:
            overlay.setGeometry(QRect(self._start_pos, self._start_pos))
            overlay.show()
            overlay.raise_()
        except RuntimeError:
            # 3.1#19 留档：宿主销毁后的预期防御。
            pass

    def _update_geometry(self, pos: QPoint) -> None:
        """更新选框几何；拖出视口上下边时驱动滚动条自动滚动。

        逻辑矩形（命中判定用）允许越出视口；覆层显示矩形钳制在视口内。

        Args:
            pos: 当前鼠标位置（视口坐标，可为视口之外）。
        """
        start = self._start_pos
        overlay = self._overlay
        if start is None or overlay is None:
            return
        try:
            bounds = QRect(QPoint(0, 0), overlay.parentWidget().size())
        except RuntimeError:
            # 3.1#19 留档：overlay 父级已销毁，预期防御。
            return

        scrollbar = self._scrollbar_getter() if self._scrollbar_getter is not None else None
        if scrollbar is not None and bounds.height() > 0:
            dy = 0
            if pos.y() < 0:
                dy = pos.y()
            elif pos.y() > bounds.height():
                dy = pos.y() - bounds.height()
            if dy:
                try:
                    scrollbar.setValue(scrollbar.value() + dy)
                except (RuntimeError, AttributeError):
                    # 3.1#19 留档：滚动条已销毁/接口缺失，预期防御。
                    pass

        rect = QRect(start, pos).normalized()
        # 零宽/零高矩形的 intersects() 恒为 False：补到 1px 保证纯水平/
        # 纯垂直拖拽也能正常命中。
        if rect.width() < 1:
            rect.setWidth(1)
        if rect.height() < 1:
            rect.setHeight(1)
        self._rect = rect
        display = rect.intersected(bounds)
        try:
            if display.isValid() and not display.isEmpty():
                overlay.setGeometry(display)
            else:
                overlay.setGeometry(rect)
        except RuntimeError:
            # 3.1#19 留档：overlay 已销毁，预期防御。
            pass

    def _emit_hits(self) -> None:
        """命中集合变化时回调调用方（无变化则跳过，避免重复刷新）。"""
        if self._hit_test is None or self._on_hits is None or self._rect is None:
            return
        hits = self._hit_test(self._rect)
        if not isinstance(hits, set):
            hits = set(hits)
        if self._last_hits == hits:
            return
        self._last_hits = set(hits)
        self._on_hits(hits)

    def _start_guard(self) -> None:
        """启动释放丢失守卫（仅框选期间运行的 QTimer）。"""
        timer = self._guard_timer
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(BOX_SELECT_GUARD_INTERVAL_MS)
            timer.timeout.connect(self._on_guard_tick)
            self._guard_timer = timer
        if not timer.isActive():
            timer.start()

    def _stop_guard(self) -> None:
        """停止释放丢失守卫（幂等，未创建/未启动时无副作用）。"""
        timer = self._guard_timer
        if timer is not None and timer.isActive():
            timer.stop()

    def _on_guard_tick(self) -> None:
        """守卫轮询：左键已释放但释放事件未到达时，按最后位置兜底收尾。"""
        if self._start_pos is None and not self._active:
            self._stop_guard()
            return
        if QApplication.mouseButtons() & Qt.LeftButton:
            return
        self.finish(self._last_pos)

    def _on_application_state_changed(self, *args) -> None:
        """应用失活时结束进行中的手势（保留已生效的选中态）。

        Args:
            *args: Qt 信号附带参数（忽略）。
        """
        if self._start_pos is not None or self._active:
            self.finish(self._last_pos)

    def _refresh_style(self, *_args) -> None:
        """主题切换：选框颜色跟随强调色。

        Args:
            *_args: 主题信号附带参数（忽略）。
        """
        overlay = self._overlay
        if overlay is None:
            return
        try:
            overlay.set_color(tm.accent)
        except (RuntimeError, AttributeError):
            # 3.1#19 留档：overlay 已销毁，预期防御。
            pass
