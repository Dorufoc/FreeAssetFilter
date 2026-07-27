"""Styled music info panel for audio preview mode.

FreeAssetFilter - 多功能文件预览与管理工具
Copyright (c) 2026 Dorufoc <dorufoc@outlook.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QSizePolicy,
    QWidget,
)

from freeassetfilter.core._paths import icons_dir
from theme import tm


class StyledMusicInfoPanel(QWidget):
    """Music information panel for audio preview.

    Displays a cover pixmap on the left (or a fallback SVG placeholder) and
    the track title plus artist stacked on the right. Long text is elided with
    ``Qt.ElideRight``. The panel uses a translucent background so it can be
    composited over a fluid background without obscuring it.
    """

    COVER_SIZE: int = 120
    H_MARGIN: int = 24
    V_MARGIN: int = 16
    H_SPACING: int = 16
    TEXT_SPACING: int = 8
    TITLE_FONT_SIZE: int = 16
    ARTIST_FONT_SIZE: int = 13

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the music info panel.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)

        self._raw_title: str = ""
        self._raw_artist: str = ""
        self._elide_enabled: bool = True
        self._elide_mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight
        self._placeholder_pixmap: QPixmap = QPixmap()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        self._init_ui()
        self._load_placeholder()

    def _init_ui(self) -> None:
        """Build the panel layout."""
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(
            self.H_MARGIN, self.V_MARGIN, self.H_MARGIN, self.V_MARGIN
        )
        root_layout.setSpacing(self.H_SPACING)

        self._cover_label = QLabel()
        self._cover_label.setFixedSize(self.COVER_SIZE, self.COVER_SIZE)
        self._cover_label.setScaledContents(True)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setStyleSheet("background: transparent;")
        root_layout.addWidget(self._cover_label)

        text_container = QWidget()
        text_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        text_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(self.TEXT_SPACING)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._title_label = QLabel("")
        title_font = QFont("Microsoft YaHei UI", self.TITLE_FONT_SIZE)
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet(
            f"background: transparent; color: {tm.text.name()};"
        )
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._title_label.setWordWrap(False)

        self._artist_label = QLabel("未知艺术家")
        artist_font = QFont("Microsoft YaHei UI", self.ARTIST_FONT_SIZE)
        self._artist_label.setFont(artist_font)
        self._artist_label.setStyleSheet(
            f"background: transparent; color: {tm.mid.name()};"
        )
        self._artist_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._artist_label.setWordWrap(False)

        text_layout.addWidget(self._title_label)
        text_layout.addWidget(self._artist_label)
        text_layout.addStretch(1)

        root_layout.addWidget(text_container, stretch=1)

    def _load_placeholder(self) -> None:
        """Load the SVG placeholder into the cover label."""
        placeholder_path = icons_dir() / "音乐_playing.svg"
        self._placeholder_pixmap = self._render_svg_to_pixmap(
            placeholder_path, self.COVER_SIZE, self.COVER_SIZE
        )
        self._cover_label.setPixmap(self._placeholder_pixmap)

    @staticmethod
    def _render_svg_to_pixmap(svg_path: Path, width: int, height: int) -> QPixmap:
        """Render an SVG file to a pixmap of the requested size.

        If the file cannot be loaded, a solid mid-tone fallback pixmap is
        returned so that the UI still shows a non-empty cover area.

        Args:
            svg_path: Path to the SVG file.
            width: Target pixmap width in pixels.
            height: Target pixmap height in pixels.

        Returns:
            A ``QPixmap`` containing the rendered SVG or the fallback fill.
        """
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        if svg_path.exists():
            try:
                renderer = QSvgRenderer(str(svg_path))
                if renderer.isValid():
                    painter = QPainter(pixmap)
                    try:
                        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                        renderer.render(
                            painter, QRectF(0, 0, width, height)
                        )
                    finally:
                        painter.end()
                    return pixmap
            except OSError:
                pass

        pixmap.fill(tm.mid)
        return pixmap

    def set_title(self, title: str) -> None:
        """Set the track title.

        Args:
            title: Track title text. Empty strings are preserved as empty.
        """
        self._raw_title = title
        self._refresh_text()

    def set_artist(self, artist: str) -> None:
        """Set the artist name.

        Args:
            artist: Artist name. Empty or whitespace-only strings are shown as
                ``未知艺术家``.
        """
        self._raw_artist = artist
        self._refresh_text()

    def set_cover_pixmap(self, pixmap: QPixmap | None) -> None:
        """Set the cover pixmap, or restore the placeholder when ``None``.

        Args:
            pixmap: Cover image, or ``None`` to fall back to the placeholder.
        """
        if pixmap is not None and not pixmap.isNull():
            self._cover_label.setPixmap(pixmap)
        else:
            self._cover_label.setPixmap(self._placeholder_pixmap)

    def set_placeholder(self) -> None:
        """Restore the default SVG placeholder cover."""
        self._cover_label.setPixmap(self._placeholder_pixmap)

    def clear(self) -> None:
        """Reset title, artist and cover back to their initial states."""
        self.set_title("")
        self.set_artist("")
        self.set_placeholder()

    def resizeEvent(self, event) -> None:
        """Re-elide labels when the panel size changes."""
        super().resizeEvent(event)
        self._refresh_text()

    def _refresh_text(self) -> None:
        """Refresh visible label text, applying right-side elision if needed."""
        title = self._raw_title
        artist = self._raw_artist.strip() or "未知艺术家"

        available_width = max(
            0,
            self.width()
            - self.COVER_SIZE
            - self.H_MARGIN * 2
            - self.H_SPACING,
        )
        if available_width > 0:
            title_metrics = QFontMetrics(self._title_label.font())
            title = title_metrics.elidedText(
                title, self._elide_mode, available_width
            )
            artist_metrics = QFontMetrics(self._artist_label.font())
            artist = artist_metrics.elidedText(
                artist, self._elide_mode, available_width
            )

        self._title_label.setText(title)
        self._artist_label.setText(artist)
