#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置窗口过渡辅助：窗口内快照缩放、关闭淡出参数与过渡输入挡板。

背景
----

设置窗口使用 ``Qt.ExpandedClientAreaHint`` + DWM 扩展帧：真实可见窗口由
DWM 在客户区外侧绘制边框与阴影。历史实现用独立透明浮层播放缩放，结果：

1. 浮层只画 ``grab()`` 的客户区内容，没有 DWM 边框/阴影 → 揭开瞬间才
   「补上」边框和深色背影，视觉上像弹了一下；
2. 浮层按 Qt ``geometry()`` 对齐，而真实可见帧/客户区在 150% DPI 下与
   之相差 1~3px → 揭开时内容整体位移（实测 dx=+2, dy=-1 物理像素）。

改为真实窗口几何缩放后，仍有一个无法消除的物理限制：设置窗口宽 705
逻辑像素，在 150% DPI 下是 1057.5 **物理**像素，左右边缘永远落在半个
物理像素上；Qt 对 x / width 分别取整，动画中宽度奇偶性一变，中心就会
左右摆 0.5~1.5 物理像素——这就是「横向抖动」。

因此最终方案是「**窗口一个像素都不动**」：

- 真实窗口从第一帧就以最终几何、完全不透明出现，DWM 边框/阴影天然存在；
- 窗口内盖一层快照，内容从 104% 轻微收缩归位到 100%（>1 所以四周不会
  露出底色，也不会露出重排后的真实内容）；
- 末帧快照与真实内容逐像素一致，撤层瞬间零跳变。

关闭时真实窗口保持最终尺寸原地淡出，不缩回设置按钮。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QWidget

# ── 过渡参数（集中在此，便于统一调时长） ──────────────────────────────
#: 打开动画时长（ms）。0 = 关闭动画，窗口直接出现。
SETTINGS_WINDOW_OPEN_MS: int = 160
#: 关闭动画时长（ms）。0 = 关闭淡出，同步关闭。
SETTINGS_WINDOW_CLOSE_MS: int = 0
#: 打开时的起始缩放：必须 >1，收缩过程中才不会在四周露出窗口底色。
SETTINGS_WINDOW_OPEN_SCALE: float = 1.04


def client_snapshot_geometry(
    widget: QWidget, snapshot: QPixmap
) -> tuple[QRect, QRectF]:
    """计算快照层在窗口内的几何与快照的设备像素裁剪区。

    关键点：Qt 的 ``widget.mapToGlobal(QPoint(0, 0))`` 与 Win32 真实客户区
    原点并不重合（扩展帧会差 1~2 逻辑像素）；``grab()`` 也比可见客户区宽
    2~3 物理像素。若把 ``grab()`` 直接铺满 widget 矩形，揭开时内容会整体
    位移。这里按真实客户区同时给出层的几何与快照裁剪区，保证末帧 1:1。

    裁剪区一律对齐到整数**设备像素**：半像素采样会让文字和 1px 描边在
    动画中反复重采样，表现为细线「呼吸」。

    Args:
        widget: 产生快照的顶层窗口。
        snapshot: ``widget.grab()`` 的结果。

    Returns:
        ``(layer_geometry, source_rect)``：

        - ``layer_geometry``: 快照层相对窗口客户区（widget 坐标）的逻辑矩形。
        - ``source_rect``: 快照中对应的**设备像素**裁剪区。
    """
    try:
        dpr = float(snapshot.devicePixelRatio()) or 1.0
    except (RuntimeError, AttributeError):
        dpr = 1.0
    fallback = QRect(0, 0, max(1, widget.width()), max(1, widget.height()))
    fallback_src = QRectF(0.0, 0.0, float(snapshot.width()), float(snapshot.height()))
    if sys.platform != "win32" or snapshot.isNull():
        return fallback, fallback_src
    try:
        hwnd = int(widget.winId())
    except (RuntimeError, TypeError, ValueError):
        return fallback, fallback_src
    if not hwnd:
        return fallback, fallback_src
    try:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        ok_rect = user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        ok_origin = user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
    except (OSError, AttributeError):
        return fallback, fallback_src
    if not ok_rect or not ok_origin:
        return fallback, fallback_src
    client_w = int(rect.right - rect.left)
    client_h = int(rect.bottom - rect.top)
    if client_w <= 0 or client_h <= 0:
        return fallback, fallback_src

    widget_origin = widget.mapToGlobal(QPoint(0, 0))
    # 客户区原点相对 widget 左上角的逻辑偏移（可能为负/小数）。
    offset_x = origin.x / dpr - widget_origin.x()
    offset_y = origin.y / dpr - widget_origin.y()
    layer_w = max(1, int(round(client_w / dpr)))
    layer_h = max(1, int(round(client_h / dpr)))
    layer = QRect(int(round(offset_x)), int(round(offset_y)), layer_w, layer_h)

    # 快照里对应的设备像素起点；对齐到整数设备像素并裁到快照边界内。
    src_x = float(max(0, int(round(offset_x * dpr))))
    src_y = float(max(0, int(round(offset_y * dpr))))
    src_w = float(min(client_w, max(1, int(round(snapshot.width() - src_x)))))
    src_h = float(min(client_h, max(1, int(round(snapshot.height() - src_y)))))
    return layer, QRectF(src_x, src_y, src_w, src_h)


class SettingsWindowSnapshotLayer(QWidget):
    """窗口内不透明快照层：内容从 104% 轻微收缩归位，窗口几何不变。

    作为设置窗口根容器的子控件铺满可见客户区。窗口本身**不做任何几何
    变化**，因此不存在左右边缘半像素取整造成的横向抖动；缩放只发生在
    绘制期，并且起始比例 >1，收缩过程中四周不会露出底色或真实内容。

    末帧（progress=1）按 1:1 绘制，与真实内容逐像素一致，撤层无跳变。
    """

    finished = Signal()

    def __init__(
        self,
        snapshot: QPixmap,
        source_rect: QRectF | None = None,
        duration_ms: int = SETTINGS_WINDOW_OPEN_MS,
        start_scale: float = SETTINGS_WINDOW_OPEN_SCALE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)
        self._snapshot: QPixmap = snapshot
        # QPixmap 的 source 矩形按**设备像素**解释。
        if source_rect is None:
            self._source: QRectF = QRectF(
                0.0, 0.0, float(snapshot.width()), float(snapshot.height())
            )
        else:
            self._source = QRectF(source_rect)
        self._duration_ms: int = max(1, int(duration_ms))
        self._start_scale: float = max(1.0, float(start_scale))
        self._progress: float = 0.0
        self._anim: QPropertyAnimation | None = None
        self._finished: bool = False

    # ── 动画属性 ───────────────────────────────────────────────────
    @property
    def snapshot(self) -> QPixmap:
        """当前覆盖的快照（供过渡期几何重算使用）。"""
        return self._snapshot

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    progress = Property(float, get_progress, set_progress)

    def start(self) -> None:
        """开始内容收缩归位动画。"""
        if self._finished:
            return
        anim = QPropertyAnimation(self, b"progress", self)
        anim.setDuration(self._duration_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._on_finished)
        self._anim = anim
        anim.start()

    def finish_now(self) -> None:
        """立即落到 100% 并发出 ``finished``（幂等）。"""
        if self._finished:
            return
        if self._anim is not None:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
            self._anim = None
        self._on_finished()

    def _on_finished(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._progress = 1.0
        self.update()
        self.finished.emit()

    # ── 绘制 ───────────────────────────────────────────────────────
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt 命名
        """按进度把快照从 104% 居中收缩到 1:1（超出部分裁掉）。"""
        if self._snapshot.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        scale = self._start_scale + (1.0 - self._start_scale) * self._progress
        width = self.width() * scale
        height = self.height() * scale
        x = (self.width() - width) / 2.0
        y = (self.height() - height) / 2.0
        # 起始 scale > 1：绘制区始终覆盖整个客户区，不会露出底色。
        painter.drawPixmap(QRectF(x, y, width, height), self._snapshot, self._source)
        painter.end()

    # ── 输入拦截 ───────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        event.accept()


class TransitionInputBlocker(QWidget):
    """透明输入挡板：关闭淡出期间盖住真实窗口，阻止用户误点内部控件。

    挡板作为设置窗口的子控件铺满客户区，只接收 / 吞掉输入，不绘制任何
    像素。过渡结束后由调用方移除。
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsWindowTransitionInputBlocker")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        # 强焦点：过渡期间把键盘焦点也揽到挡板上（默认 keyPressEvent
        # 不上抛到兄弟控件），避免用户在窗口动画过程中误触 Tab/回车改设置。
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt 命名
        """不绘制任何内容（透明挡板）。"""
        return


__all__ = [
    "SETTINGS_WINDOW_CLOSE_MS",
    "SETTINGS_WINDOW_OPEN_MS",
    "SETTINGS_WINDOW_OPEN_SCALE",
    "SettingsWindowSnapshotLayer",
    "TransitionInputBlocker",
    "client_snapshot_geometry",
]
