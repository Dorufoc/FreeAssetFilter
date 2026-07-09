"""Styled Avatar component - matches web avatar exactly."""

from typing import Optional

from PySide6.QtWidgets import QWidget, QHBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QPaintEvent,
    QFont,
    QFontMetrics,
    QPixmap,
    QPainterPath,
)

from components.icon_utils import icon_path
from theme import tm

# ---------------------------------------------------------------------------
# Design tokens matching avatar.css
# ---------------------------------------------------------------------------

SIZE_CONFIG: dict[str, dict[str, int]] = {
    "sm": {"size": 28, "font": 11},
    "default": {"size": 36, "font": 13},
    "lg": {"size": 48, "font": 16},
    "xl": {"size": 64, "font": 22},
}

COLOR_VARIANTS: dict[str, tuple[str, QColor]] = {
    "green": (tm.accent.name(), tm.alpha_of(tm.accent, 20)),
    "blue": (tm.info.name(), tm.alpha_of(tm.info, 20)),
    "purple": (tm.purple.name(), tm.alpha_of(tm.purple, 20)),
    "orange": (tm.warning.name(), tm.alpha_of(tm.warning, 20)),
    "default": (tm.mid.name(), tm.fill),
}




class StyledAvatar(QWidget):
    """An avatar widget supporting text (initials), icon, and image modes.

    Size variants: sm (28×28), default (36×36), lg (48×48), xl (64×64)
    Shape variants: circle (default), square (radius=6px)
    Color variants: green, blue, purple, orange, default (gray)
    """

    def __init__(
        self,
        text: str = "",
        icon: str = "",
        size: str = "default",
        shape: str = "circle",
        color: str = "default",
        parent=None,
    ):
        super().__init__(parent)
        self._text = text
        self._icon_name = icon
        self._size = size
        self._shape = shape
        self._color = color
        self._pixmap: Optional[QPixmap] = None
        self._in_group = False

        config = self._get_config()
        self.setFixedSize(config["size"], config["size"])
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _get_config(self) -> dict:
        return SIZE_CONFIG.get(self._size, SIZE_CONFIG["default"])

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value in SIZE_CONFIG:
            self._size = value
            config = SIZE_CONFIG[value]
            self.setFixedSize(config["size"], config["size"])
            self.update()

    @property
    def shape(self) -> str:
        return self._shape

    @shape.setter
    def shape(self, value: str):
        if value in ("circle", "square"):
            self._shape = value
            self.update()

    @property
    def color(self) -> str:
        return self._color

    @color.setter
    def color(self, value: str):
        if value in COLOR_VARIANTS:
            self._color = value
            self.update()

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self.update()

    @property
    def icon(self) -> str:
        return self._icon_name

    @icon.setter
    def icon(self, value: str):
        self._icon_name = value
        self._pixmap = None
        self.update()

    @property
    def pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    def setPixmap(self, pixmap: QPixmap):
        """Set an image for the avatar. Clips to current shape."""
        self._pixmap = pixmap
        self._icon_name = ""
        self._text = ""
        self.update()

    # ── Size hint ────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        config = self._get_config()
        return QSize(config["size"], config["size"])

    # ── Paint ────────────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)

            w = self.width()
            h = self.height()

            # Build clip path for shape
            clip_path = QPainterPath()
            if self._shape == "square":
                clip_path.addRoundedRect(QRectF(0, 0, w, h), 6, 6)
            else:
                clip_path.addEllipse(QRectF(0, 0, w, h))

            painter.setClipPath(clip_path)

            text_color_hex, bg_color = self._get_color_values()

            if self._pixmap is not None and not self._pixmap.isNull():
                self._paint_pixmap(painter, w, h)
            else:
                self._paint_background_and_content(
                    painter, w, h, bg_color, text_color_hex
                )

            # ── Border (always drawn, outside clip) ──────────────────
            painter.setClipping(False)
            if self._in_group:
                border_color = tm.surface
                border_width = 2
            else:
                border_color = tm.mid
                border_width = 1

            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(Qt.NoBrush)

            bw = float(border_width)
            offset = bw / 2.0
            if self._shape == "square":
                painter.drawRoundedRect(
                    QRectF(offset, offset, w - bw, h - bw), 6, 6
                )
            else:
                painter.drawEllipse(
                    QRectF(offset, offset, w - bw, h - bw)
                )

    def _get_color_values(self):
        return COLOR_VARIANTS.get(self._color, COLOR_VARIANTS["default"])

    def _paint_pixmap(self, painter: QPainter, w: int, h: int):
        """Scale and center the pixmap to fill the avatar area."""
        scaled = self._pixmap.scaled(
            w, h,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        x = (w - scaled.width()) / 2
        y = (h - scaled.height()) / 2
        painter.drawPixmap(int(x), int(y), scaled)

    def _paint_background_and_content(
        self,
        painter: QPainter,
        w: int,
        h: int,
        bg_color: QColor,
        text_color_hex: str,
    ):
        """Fill background then draw icon or initials."""
        # Background fill
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        if self._shape == "square":
            painter.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
        else:
            painter.drawEllipse(QRectF(0, 0, w, h))

        text_color = QColor(text_color_hex)

        if self._icon_name:
            self._paint_icon(painter, w, h, text_color)
        elif self._text:
            self._paint_initials(painter, w, h, text_color)

    def _paint_icon(self, painter: QPainter, w: int, h: int, color: QColor):
        """Draw a named icon centered in the avatar."""
        icon_path_obj = icon_path(self._icon_name)
        if icon_path_obj.isEmpty():
            return

        painter.save()
        icon_size = w * 0.55
        view_size = 24.0
        scale = icon_size / view_size

        painter.translate(w / 2.0, h / 2.0)
        painter.scale(scale, scale)
        painter.translate(-view_size / 2.0, -view_size / 2.0)

        painter.setPen(
            QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(icon_path_obj)
        painter.restore()

    def _paint_initials(self, painter: QPainter, w: int, h: int, color: QColor):
        """Draw uppercase initials centered in the avatar."""
        config = self._get_config()
        font = QFont("Segoe UI", config["font"])
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setClipping(False)

        fm = QFontMetrics(font)
        upper = self._text.upper()
        text_rect = fm.boundingRect(upper)
        text_x = (w - text_rect.width()) / 2
        text_y = (h + fm.ascent() - fm.descent()) / 2

        painter.setPen(color)
        painter.drawText(int(text_x), int(text_y), upper)


class AvatarGroup(QWidget):
    """Container for overlapping avatar stack.

    Children are laid out in reverse z-order with -8px overlap
    and a 2px border matching bg-secondary (#1a1a1a).

    Matches CSS:
        .avatar-group { flex-direction: row-reverse; }
        .avatar-group .avatar { margin-right: -8px; border: 2px solid var(--bg-secondary); }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(-8)
        # RightToLeft matches CSS row-reverse: last-added child is at the left (on top)
        self._layout.setDirection(QHBoxLayout.RightToLeft)

    def addAvatar(self, avatar: StyledAvatar):
        """Add an avatar to the group with overlap styling."""
        avatar._in_group = True
        self._layout.addWidget(avatar)


__all__ = ["StyledAvatar", "AvatarGroup"]
