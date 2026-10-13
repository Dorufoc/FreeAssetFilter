"""Floating Panel component - 通用半透明圆角浮层面板基类。

提取自播放器控制栏的 ``_PlayerPopup``（音量/倍速/设置弹窗）与各预览器的
``_ZoomPopup`` / ``_WeightPopup``：它们共享同一套窗口设置（frameless 半透明
Tool 窗口）、主题圆角背景绘制、淡入 + 几何滑动动画与 ``close_animated``
生命周期。本模块把公共部分收敛为 ``FloatingPanel``，供播放器之外的浮层
复用（见 styled_player_bar.py 头部原先的 TODO(后续专项)）。
"""

import time

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import (
    Qt, Signal, QEvent, QPoint, QRect, QRectF, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import (
    QPainter, QPaintEvent, QPen, QMouseEvent, QKeyEvent,
)

from theme import tm


class FloatingPanel(QWidget):
    """半透明圆角浮层面板基类。

    特性：
    - frameless 半透明 Tool 窗口（``Qt.Tool | Qt.FramelessWindowHint`` +
      ``WA_TranslucentBackground`` + ``WA_ShowWithoutActivating``）；
    - ``paintEvent`` 现取主题色绘制圆角背景（``surface`` 85%）+ 1px 边框
      （``mid`` 30%），主题切换调用 :meth:`refresh_theme` 即可重绘；
    - ``show_animated`` 淡入（180ms）+ 几何滑动（200ms，OutCubic），支持
      ``bottom-center`` / ``bottom-right`` / ``top-center`` 锚点模式并带
      屏幕可用区域钳制；
    - ``close_animated`` 淡出 + 高度收缩到 8px（120ms），带重入保护，
      完成时发射一次 :attr:`closed`，可选 ``delete_on_close``；
    - 可选外部点击 / Esc 关闭（默认关闭，预览器浮层沿用各自预览器的
      手势逻辑，不启用应用级事件过滤）。

    Signals:
        closed: 带动画关闭完成（窗口已隐藏）后发射。
    """

    closed = Signal()

    def __init__(
        self,
        parent=None,
        radius: int = 8,
        padding: int = 8,
        dismiss_on_outside_click: bool = False,
        dismiss_on_escape: bool = False,
        delete_on_close: bool = False,
    ):
        """初始化浮层面板。

        Args:
            parent: 真实 Qt 父级（owned tool 窗口，随父级销毁）。
            radius: 圆角半径。
            padding: 内容内边距（子类布局与绘制共用）。
            dismiss_on_outside_click: 是否在点击面板外时自动收起。
            dismiss_on_escape: 是否在按下 Esc 时自动收起。
            delete_on_close: 关闭完成后是否 ``deleteLater()``。
        """
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._radius = radius
        self._padding = padding
        self._target_w = 0
        self._target_h = 0

        # 关闭重入保护与 closed 单次发射标记
        self._closing = False
        self._closed_notified = False
        self._close_anim_connected = False
        self._closed_at = 0.0
        self._delete_on_close = bool(delete_on_close)
        self._delete_pending = False

        # 外部点击 / Esc 关闭（应用级事件过滤）
        self._dismiss_on_outside_click = bool(dismiss_on_outside_click)
        self._dismiss_on_escape = bool(dismiss_on_escape)
        self._dismiss_filter_installed = False

        # 淡入动画（windowOpacity）与滑动动画（geometry）
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

    # ── 绘制 / 主题 ─────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        """绘制半透明圆角背景 + 1px 边框（颜色实时取自主题）。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius

        # 背景（浅色用更实的浅色板，保证浮层与窗口的分层）
        p.setPen(Qt.NoPen)
        p.setBrush(
            tm.alpha_of(tm.surface, 85)
            if tm.is_dark_theme()
            else tm.alpha_of(tm.surface, 96)
        )
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        # 边框
        p.setPen(
            QPen(
                tm.alpha_of(tm.mid, 30) if tm.is_dark_theme()
                else tm.alpha_of(tm.text, 12),
                1,
            )
        )
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def refresh_theme(self) -> None:
        """主题切换时刷新面板（背景色在 paintEvent 现取，只需触发重绘）。"""
        self.update()

    # ── 展开 / 关闭动画 ─────────────────────────────────────────

    def show_animated(
        self,
        anchor_global: QPoint,
        popup_w: int,
        popup_h: int,
        anchor_mode: str = "bottom-center",
    ):
        """淡入 + 滑动展开面板，锚定到给定全局锚点。

        支持的锚点模式：
        - ``bottom-center``：面板底边在锚点上方 8px，水平居中（播放器弹窗）；
        - ``bottom-right``：面板底边在锚点上方 8px，右边缘与锚点对齐；
        - ``top-center``：面板顶边在锚点下方 8px，水平居中（预览器弹窗）。

        定位结果会钳制在 ``QApplication.primaryScreen()`` 的可用区域内。
        需要差异化定位（如 DPI 间距 / 贴近屏幕底边时上翻）的子类可自行
        计算目标矩形后调用 :meth:`_show_at_rect`。

        Args:
            anchor_global: 全局坐标锚点（通常是按钮下缘中心/右下角）。
            popup_w: 面板目标宽度。
            popup_h: 面板目标高度。
            anchor_mode: 锚点模式，见上。
        """
        target = self._anchor_target_rect(
            anchor_global, popup_w, popup_h, anchor_mode
        )
        self._show_at_rect(target, grow_from_bottom=anchor_mode.startswith("bottom"))

    def _anchor_target_rect(
        self, anchor_global: QPoint, popup_w: int, popup_h: int, anchor_mode: str
    ) -> QRect:
        """按锚点模式计算目标矩形并做屏幕可用区域钳制。"""
        gap = 8
        if anchor_mode == "bottom-right":
            x = anchor_global.x() - popup_w  # 右边缘与锚点对齐
        else:
            x = anchor_global.x() - popup_w // 2  # 水平居中
        if anchor_mode == "top-center":
            y = anchor_global.y() + gap  # 从锚点下缘向下展开
        else:
            y = anchor_global.y() - popup_h - gap  # 上方 + 8px 间隙

        screen = QApplication.primaryScreen()
        if screen is not None:
            sg = screen.availableGeometry()
            x = max(sg.x() + 8, min(x, sg.right() - popup_w - 8))
            y = max(sg.y() + 8, min(y, sg.bottom() - popup_h - 8))
        return QRect(x, y, popup_w, popup_h)

    def _show_at_rect(self, target: QRect, grow_from_bottom: bool = False):
        """按目标矩形播放展开动画（子类差异化定位的落点）。

        Args:
            target: 展开完成后的目标几何矩形。
            grow_from_bottom: True 时起始窗口贴目标底边（向上展开），
                False 时贴目标顶边（向下展开）。
        """
        popup_w, popup_h = target.width(), target.height()
        self._target_w = popup_w
        self._target_h = popup_h

        start_h = 10
        if grow_from_bottom:
            start = QRect(target.x(), target.y() + popup_h - start_h, popup_w, start_h)
        else:
            start = QRect(target.x(), target.y(), popup_w, start_h)

        self._closing = False
        self._closed_notified = False
        self._fade.stop()
        self._slide.stop()
        # 若上一次关闭动画被外部 hide 打断，清掉残留的 finished 连接，
        # 避免展开动画结束时误触发关闭收尾
        self._detach_close_anim_handler()

        self.setGeometry(start)
        self.setWindowOpacity(0.0)
        super().show()
        self.raise_()
        self.activateWindow()

        self._fade.setDuration(180)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

        self._slide.setDuration(200)
        self._slide.setStartValue(start)
        self._slide.setEndValue(target)

        self._fade.start()
        self._slide.start()

    def close_animated(self):
        """淡出 + 高度收缩到 8px（120ms），完成后隐藏并发射 ``closed``。

        重入保护：关闭过程中重复调用直接返回；``closed`` 每次打开周期
        只发射一次。动画完成可选 ``deleteLater()``（``delete_on_close``）。
        """
        if self._closing:
            return
        if not self.isVisible():
            self._finalize_close()
            return

        self._closing = True
        self._fade.stop()
        self._fade.setDuration(120)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)

        self._slide.stop()
        self._slide.setDuration(120)
        self._slide.setStartValue(self.geometry())
        end = QRect(self.geometry())
        end.setHeight(8)
        self._slide.setEndValue(end)

        # 防御性断连：避免中断后重开导致 finished 槽重复连接
        if not self._close_anim_connected:
            self._slide.finished.connect(self._on_close_anim_finished)
            self._close_anim_connected = True
        self._fade.start()
        self._slide.start()

    def _detach_close_anim_handler(self) -> None:
        """断开关闭动画 finished 连接（幂等，无 disconnect 警告）。"""
        if not self._close_anim_connected:
            return
        self._close_anim_connected = False
        try:
            self._slide.finished.disconnect(self._on_close_anim_finished)
        except (RuntimeError, TypeError):
            pass

    def _on_close_anim_finished(self):
        """关闭动画完成回调（断开连接后执行收尾）。"""
        self._detach_close_anim_handler()
        self._finalize_close()

    def _finalize_close(self):
        """收尾关闭：停止动画、隐藏窗口、发射一次 ``closed``（必要时删除）。"""
        self._closing = False
        self._fade.stop()
        self._slide.stop()
        self.hide()
        # 记录关闭时刻：宿主（如播放栏按钮）可据此避免同一次点击的释放重新打开
        self._closed_at = time.monotonic()
        if not self._closed_notified:
            self._closed_notified = True
            self.closed.emit()
        if self._delete_on_close and not self._delete_pending:
            self._delete_pending = True
            self.deleteLater()

    def reposition(self, rect: QRect) -> None:
        """把面板直接移动到指定目标矩形（不重播展开动画，供宿主移动时贴附）。

        子类（如预览器缩放弹窗）通常在收到宿主 Move/Resize 事件时调用，
        传入自行计算好的锚点目标矩形。
        """
        if self._closing or not self.isVisible():
            return
        self._slide.stop()
        self.setGeometry(rect)
        self.update()

    # ── 外部点击 / Esc 关闭（可选） ─────────────────────────────

    def _install_dismiss_filter(self) -> None:
        """安装 QApplication 级事件过滤器（面板显示期间）。"""
        app = QApplication.instance()
        if app is None or self._dismiss_filter_installed:
            return
        app.installEventFilter(self)
        self._dismiss_filter_installed = True

    def _remove_dismiss_filter(self) -> None:
        """移除 QApplication 级事件过滤器（面板隐藏/销毁时）。"""
        app = QApplication.instance()
        if app is not None and self._dismiss_filter_installed:
            app.removeEventFilter(self)
        self._dismiss_filter_installed = False

    def _is_event_inside_panel(self, watched, event) -> bool:
        """判断事件目标（或其祖先、或全局坐标）是否落在本面板内。"""
        if isinstance(watched, QWidget):
            widget = watched
            while widget is not None:
                if widget is self:
                    return True
                widget = widget.parentWidget()
        if isinstance(event, QMouseEvent):
            return self.frameGeometry().contains(event.globalPosition().toPoint())
        return False

    def eventFilter(self, watched, event) -> bool:
        """面板外的鼠标按下 → 收起；Esc → 收起（仅在启用对应选项时）。"""
        if self._dismiss_filter_installed and self.isVisible():
            etype = event.type()
            if (
                self._dismiss_on_escape
                and etype == QEvent.Type.KeyPress
                and isinstance(event, QKeyEvent)
                and event.key() == Qt.Key_Escape
            ):
                self.close_animated()
                return True
            if (
                self._dismiss_on_outside_click
                and etype == QEvent.Type.MouseButtonPress
                and not self._is_event_inside_panel(watched, event)
            ):
                # 不消费事件：外部控件仍需收到本次点击
                self.close_animated()
        return super().eventFilter(watched, event)

    # ── 事件 ────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        """显示时安装外部点击/Esc 关闭过滤（若启用）。"""
        super().showEvent(event)
        if self._dismiss_on_outside_click or self._dismiss_on_escape:
            self._install_dismiss_filter()

    def hideEvent(self, event) -> None:
        """隐藏时停止动画、重置内部关闭状态并移除事件过滤。"""
        self._fade.stop()
        self._slide.stop()
        self._closing = False
        self._detach_close_anim_handler()
        self._remove_dismiss_filter()
        super().hideEvent(event)
