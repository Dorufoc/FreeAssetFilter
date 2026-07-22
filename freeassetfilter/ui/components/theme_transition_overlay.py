"""Theme transition overlay - crossfade snapshot when theme changes."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QGraphicsOpacityEffect, QApplication
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
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
