"""
Mica Window — reusable base window with blurred desktop wallpaper background.

Usage:
    from components.mica_window import MicaWindow

    window = MicaWindow()
    window.content_layout.addWidget(your_widget)
    window.show()

Or subclass:
    class MyWindow(MicaWindow):
        def __init__(self):
            super().__init__(window_title="My App")
            self.content_layout.addWidget(QLabel("Hello"))
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Union

# Ensure project root is on sys.path (for both direct run and package import)
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QResizeEvent, QMoveEvent, QPaintEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from components.mica_material import MicaMaterial


# Current default config from main.py
DEFAULT_MICA_CONFIG = {
    "blur_radius": 200,
    "tint_color": "#202020E8",
    "luminosity": 0.65,
    "contrast": 1.5,
    "saturation": 4.0,
}


class MicaWindow(QWidget):
    """
    A QWidget with built-in Mica (blurred desktop wallpaper) background.

    Call ``setLayout(your_layout)`` to add content. Use ``self.content_layout``
    to access the current layout after setting it.

    Window resize/move automatically updates the background crop.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        window_title: str = "",
        blur_radius: Optional[int] = None,
        tint_color: Optional[str] = None,
        luminosity: Optional[float] = None,
        contrast: Optional[float] = None,
        saturation: Optional[float] = None,
    ):
        """
        All Mica params default to the project-wide DEFAULT_MICA_CONFIG.
        Pass explicit values to override per-window.
        """
        super().__init__(parent)

        cfg = DEFAULT_MICA_CONFIG
        self._blur_radius = blur_radius if blur_radius is not None else cfg["blur_radius"]
        self._tint_color = tint_color if tint_color is not None else cfg["tint_color"]
        self._luminosity = luminosity if luminosity is not None else cfg["luminosity"]
        self._contrast = contrast if contrast is not None else cfg["contrast"]
        self._saturation = saturation if saturation is not None else cfg["saturation"]

        if window_title:
            self.setWindowTitle(window_title)

        # Mica background
        self._mica = MicaMaterial(
            self, self._blur_radius, self._tint_color,
            self._luminosity, self._contrast, self._saturation,
        )

    # ---- Public ----

    @property
    def mica(self) -> MicaMaterial:
        return self._mica

    @property
    def content_layout(self) -> Optional[Union[QVBoxLayout, QHBoxLayout]]:
        """The widget's layout — returns self.layout()."""
        return self.layout()

    def refresh_background(self) -> None:
        """Reload wallpaper and rebuild blur (e.g. after wallpaper change)."""
        self._mica.refresh()

    # ---- Internal ----

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        self._mica.paint(painter, event)
        painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._mica.invalidate_cache()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self._mica.invalidate_cache()
