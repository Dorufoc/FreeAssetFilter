"""
AnimatedFileListView - 带路径切换过渡动画的 QListView。

移植自旧 file_selector.py 中的 FileListView 路径切换动画：
在进入子目录、返回上级或切换到 All 视图时，先捕获当前 viewport 快照，
待新目录内容加载完成后再捕获新快照，通过单个 QTimer 驱动两张 pixmap 的
整体平移 + 渐隐渐现效果。
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QTimer, Qt, QEasingCurve
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QListView, QWidget

from freeassetfilter.utils.animation_settings import is_animation_enabled


class AnimatedFileListView(QListView):
    """文件选择器动画列表视图。

    在标准 QListView 基础上增加目录切换时的整体卡片网格过渡动画：
    - begin_path_transition(direction): 捕获旧视图快照并进入等待状态
    - finish_path_transition(direction=None): 捕获新视图快照并播放动画
    - cancel_path_transition(update=True): 取消当前动画

    动画开关由 ``is_animation_enabled('directory_transition')`` 控制。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # 路径切换动画状态
        self._path_transition_enabled: bool = True
        self._path_transition_direction: int = 0
        self._path_transition_duration_ms: int = 120
        self._path_transition_progress: float = 1.0
        self._path_transition_start_ms: float = 0.0
        self._path_transition_outgoing_pixmap: QPixmap = QPixmap()
        self._path_transition_incoming_pixmap: QPixmap = QPixmap()
        self._path_transition_waiting_for_incoming: bool = False
        self._path_transition_active: bool = False
        self._path_transition_capturing_base: bool = False

        self._transition_timer = QTimer(self)
        self._transition_timer.setInterval(16)
        self._transition_timer.timeout.connect(self._advance_path_transition)

        self._load_settings()

    def _load_settings(self) -> None:
        """加载动画开关设置。"""
        try:
            self._path_transition_enabled = is_animation_enabled(
                "directory_transition", default=True
            )
        except Exception:
            self._path_transition_enabled = True

    def _get_monotonic_time_ms(self) -> float:
        """返回当前单调时间（毫秒）。"""
        return time.monotonic() * 1000.0

    def _capture_viewport_snapshot(self) -> QPixmap:
        """捕获 viewport 当前内容的 QPixmap 快照。"""
        viewport = self.viewport()
        if viewport is None:
            return QPixmap()

        size = viewport.size()
        if not size.isValid() or size.width() <= 0 or size.height() <= 0:
            return QPixmap()

        dpr = max(1.0, float(viewport.devicePixelRatioF()))
        pixmap = QPixmap(
            max(1, int(size.width() * dpr)),
            max(1, int(size.height() * dpr)),
        )
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)

        self._path_transition_capturing_base = True
        try:
            viewport.render(pixmap)
        finally:
            self._path_transition_capturing_base = False

        return pixmap

    # ── 公开 API ─────────────────────────────────────────────────────────

    def begin_path_transition(self, direction: int) -> bool:
        """开始路径切换动画：捕获旧视图快照并等待新内容就绪。

        Args:
            direction: 切换方向。>0 表示进入子目录/前进，<0 表示返回上级/后退。

        Returns:
            动画成功启动返回 True，否则返回 False。
        """
        self._load_settings()
        if not self._path_transition_enabled or not self.isVisible():
            return False

        outgoing_pixmap = self._capture_viewport_snapshot()
        if outgoing_pixmap.isNull():
            return False

        self.cancel_path_transition(update=False)
        self._path_transition_direction = self._normalize_direction(direction)
        self._path_transition_outgoing_pixmap = outgoing_pixmap
        self._path_transition_incoming_pixmap = QPixmap()
        self._path_transition_waiting_for_incoming = True
        self._path_transition_active = False
        self._path_transition_progress = 0.0
        self.viewport().update()
        return True

    def finish_path_transition(self, direction: int | None = None) -> bool:
        """完成路径切换动画：捕获新视图快照并播放过渡。

        Args:
            direction: 可选的切换方向，用于覆盖 begin 时传入的方向。

        Returns:
            动画成功播放返回 True，否则返回 False。
        """
        self._load_settings()
        if not self._path_transition_enabled:
            self.cancel_path_transition()
            return False

        if direction is not None:
            self._path_transition_direction = self._normalize_direction(direction)

        incoming_pixmap = self._capture_viewport_snapshot()
        if incoming_pixmap.isNull():
            self.cancel_path_transition()
            return False

        if self._path_transition_outgoing_pixmap.isNull():
            self._path_transition_outgoing_pixmap = incoming_pixmap

        self._path_transition_incoming_pixmap = incoming_pixmap
        self._path_transition_waiting_for_incoming = False
        self._path_transition_active = True
        self._path_transition_progress = 0.0
        self._path_transition_start_ms = self._get_monotonic_time_ms()
        self._transition_timer.start()
        self.viewport().update()
        return True

    def cancel_path_transition(self, update: bool = True) -> None:
        """取消当前路径切换动画。"""
        self._transition_timer.stop()
        self._path_transition_active = False
        self._path_transition_waiting_for_incoming = False
        self._path_transition_progress = 1.0
        self._path_transition_outgoing_pixmap = QPixmap()
        self._path_transition_incoming_pixmap = QPixmap()
        if update:
            self.viewport().update()

    # ── 内部辅助 ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_direction(direction: int) -> int:
        if direction > 0:
            return 1
        if direction < 0:
            return -1
        return 0

    def _advance_path_transition(self, now_ms: float | None = None) -> None:
        """计时器回调：推进动画进度。"""
        if not self._path_transition_active:
            self._transition_timer.stop()
            return

        current_time_ms = self._get_monotonic_time_ms() if now_ms is None else float(now_ms)
        elapsed_ms = max(0.0, current_time_ms - self._path_transition_start_ms)
        progress = elapsed_ms / max(1.0, float(self._path_transition_duration_ms))

        if progress >= 1.0:
            self.cancel_path_transition()
            return

        self._path_transition_progress = max(0.0, min(1.0, progress))
        self.viewport().update()

    @staticmethod
    def _ease_path_transition(progress: float) -> float:
        """使用 Qt 原生 InOutCubic 缓动曲线。"""
        progress = max(0.0, min(1.0, float(progress)))
        return QEasingCurve(QEasingCurve.InOutCubic).valueForProgress(progress)

    def _path_transition_offset(self) -> int:
        """计算水平偏移量（viewport 宽度的 4%，限制在 12~48px 之间）。"""
        width = self.viewport().width()
        if width <= 0:
            return 0
        return max(12, min(48, int(width * 0.04)))

    def _draw_transition_pixmap(
        self,
        painter: QPainter,
        pixmap: QPixmap,
        dx: int,
        opacity: float,
    ) -> None:
        """以指定透明度和水平偏移绘制一张过渡 pixmap。"""
        if pixmap.isNull() or opacity <= 0.0:
            return

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, float(opacity))))
        painter.drawPixmap(int(dx), 0, pixmap)
        painter.restore()

    def _paint_path_transition(self) -> None:
        """在 viewport 上绘制路径切换过渡效果。"""
        viewport = self.viewport()
        painter = QPainter(viewport)
        try:
            # viewport 本身透明，不额外填充背景，直接叠加两张快照
            if self._path_transition_waiting_for_incoming:
                self._draw_transition_pixmap(
                    painter, self._path_transition_outgoing_pixmap, 0, 1.0
                )
                return

            direction = self._path_transition_direction
            progress = max(0.0, min(1.0, self._path_transition_progress))
            eased = self._ease_path_transition(progress)
            offset = self._path_transition_offset()

            outgoing_dx = int(-direction * offset * eased) if direction else 0
            incoming_dx = int(direction * offset * (1.0 - eased)) if direction else 0
            outgoing_opacity = max(0.0, 1.0 - progress * 1.12)
            incoming_opacity = min(1.0, progress * 1.18)

            self._draw_transition_pixmap(
                painter, self._path_transition_outgoing_pixmap, outgoing_dx, outgoing_opacity
            )
            self._draw_transition_pixmap(
                painter, self._path_transition_incoming_pixmap, incoming_dx, incoming_opacity
            )
        finally:
            painter.end()

    # ── 事件重写 ─────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        """正常绘制或绘制路径切换过渡。"""
        if self._path_transition_capturing_base:
            super().paintEvent(event)
            return

        if self._path_transition_active or self._path_transition_waiting_for_incoming:
            self._paint_path_transition()
            event.accept()
            return

        super().paintEvent(event)

    def resizeEvent(self, event) -> None:
        """尺寸变化时取消动画，避免快照错位。"""
        if self._path_transition_active:
            self.cancel_path_transition(update=False)
        super().resizeEvent(event)
