"""Theme transition overlay - crossfade snapshot when theme changes."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QGraphicsOpacityEffect, QApplication
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QVariantAnimation
from PySide6.QtGui import QPixmap, QPainter, QPaintEvent


class ThemeTransitionOverlay(QWidget):
    """A full-window overlay that crossfades from a captured snapshot.

    Usage:
        snapshot = window.grab()
        overlay = ThemeTransitionOverlay(window, snapshot, duration_ms=300)
        overlay.start()
        # Apply theme change immediately after start(); the overlay fades out
        # and reveals the newly themed window underneath.
    """

    DEFAULT_DURATION_MS: int = 300

    def __init__(
        self,
        parent: QWidget,
        snapshot: QPixmap,
        duration_ms: int = DEFAULT_DURATION_MS,
    ):
        super().__init__(parent)
        self._snapshot = snapshot
        self._duration_ms = max(50, duration_ms)

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setGeometry(parent.rect())

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.setDuration(self._duration_ms)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.finished.connect(self._on_finished)

    @classmethod
    def from_widget(
        cls,
        window: QWidget,
        duration_ms: int = DEFAULT_DURATION_MS,
    ) -> "ThemeTransitionOverlay":
        """Capture a top-level window via its native handle and create an overlay.

        ``QScreen.grabWindow(HWND)`` correctly composites OpenGL-backed children
        (e.g. the Mica background) where ``QWidget.grab()`` produces corrupted
        artifacts on some GPU drivers.
        """
        screen = window.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        # WId is the native window handle (HWND on Windows).
        snapshot = screen.grabWindow(int(window.winId()))
        return cls(window, snapshot, duration_ms)

    def start(self) -> None:
        """Show the overlay and begin the fade-out animation."""
        self.show()
        self.raise_()
        self._anim.start()

    def _on_finished(self) -> None:
        """Clean up the overlay after the animation completes."""
        self.setGraphicsEffect(None)
        self.deleteLater()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), self._snapshot)
        finally:
            painter.end()


class ContentTransitionOverlay(QWidget):
    """内容层主题过渡遮罩：旧外观快照打底、自绘淡出。

    与 :class:`ThemeTransitionOverlay`（整窗 ``grabWindow`` 截屏 +
    ``QGraphicsOpacityEffect`` 逐帧全窗软件合成）的分工与差异：

    - 快照由调用方传入（主窗口对内容子树 ``QWidget.grab()``——子树不含
      OpenGL 的 Mica 背景兄弟层，规避 ``QWidget.grab()`` 在 GL 子部件上的
      花屏/黑帧问题，也避免 ``QScreen.grabWindow`` 的整窗同步截屏阻塞）；
    - 淡出为 paintEvent 内单次 ``drawPixmap``（透明度渐变），无逐帧全窗
      效果过滤管线，显著降低切换期主线程合成开销；
    - ``WA_TransparentForMouseEvents`` 鼠标穿透，过渡不阻塞界面交互。

    仅覆盖内容层：Mica 背景过渡由 ``MicaMaterial`` 的材质级交叉过渡
    （``MicaMaterial._start_xfade``）承担，遮罩不遮背景层，两者独立
    并行、互不影响。
    """

    DEFAULT_DURATION_MS: int = 280  # 对齐 ui/mica/config.XFADE_DURATION_MS

    def __init__(
        self,
        parent: QWidget,
        snapshot: QPixmap,
        duration_ms: int = DEFAULT_DURATION_MS,
    ) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._duration_ms = max(50, int(duration_ms))
        self._opacity: float = 1.0

        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(parent.rect())

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self._duration_ms)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._on_value_changed)
        self._anim.finished.connect(self._on_finished)

    def start(self) -> None:
        """显示遮罩并启动淡出动画。"""
        self.show()
        self.raise_()
        self._anim.start()

    def finish_now(self) -> None:
        """立即结束过渡并清理（快速连续切换时的去重路径）。"""
        self._on_finished()

    def _on_value_changed(self, value: object) -> None:
        """动画帧回调：更新透明度并触发重绘。

        Args:
            value: 动画当前值（1.0 → 0.0）。
        """
        try:
            self._opacity = max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        self.update()

    def _on_finished(self) -> None:
        """动画结束清理：停动画、隐藏并调度销毁。"""
        self._anim.stop()
        self.hide()
        self.deleteLater()

    def paintEvent(self, event: QPaintEvent) -> None:
        """按当前透明度自绘旧外观快照（单次 blit，无效果过滤管线）。"""
        if self._opacity <= 0.0 or self._snapshot.isNull():
            return
        painter = QPainter(self)
        try:
            painter.setOpacity(self._opacity)
            painter.drawPixmap(self.rect(), self._snapshot)
        finally:
            painter.end()
