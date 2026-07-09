"""Styled Tag component - matches web tag exactly."""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QFontMetrics
from theme import tm


SIZE_CONFIG = {
    "sm": {"padding_h": 8, "padding_v": 2, "font_size": 11, "radius": 4, "close_size": 14},
    "default": {"padding_h": 10, "padding_v": 3, "font_size": 12, "radius": 4, "close_size": 16},
    "lg": {"padding_h": 14, "padding_v": 5, "font_size": 13, "radius": 5, "close_size": 18},
}


class _CloseButton(QWidget):
    """Internal close button for closable tags, painted manually."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self._opacity = 0.6
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(14, 14)

    def set_opacity(self, value: float):
        self._opacity = value
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self._opacity = 1.0
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._opacity = 0.6
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent):
        text_color = self.parent().property("_tag_text_color")
        if not text_color:
            text_color = tm.mid

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self._opacity)
        painter.setPen(text_color)
        painter.setFont(QFont("Segoe UI", 14, QFont.Normal))
        painter.drawText(
            QRectF(0, 0, self.width(), self.height()),
            Qt.AlignCenter,
            "\u00d7",
        )


class StyledTag(QWidget):
    """A tag/label component matching the web component exactly.

    Color variants: default, primary, success, warning, danger, info
    Size variants: sm, default, lg
    Pill style: fully rounded corners
    Closable: with close button that emits closed signal

    Features:
        - color variants with semi-transparent backgrounds
        - size variants (sm, default, lg)
        - pill style (fully rounded corners)
        - closable with close button
        - hover effect on close button
    """

    closed = Signal()

    @staticmethod
    def _get_tag_colors() -> dict[str, dict[str, QColor]]:
        return {
            "default": {
                "bg": tm.alpha_of(tm.surface, 90),
                "text": tm.mid,
                "border": tm.alpha_of(tm.mid, 40),
            },
            "primary": {
                "bg": tm.alpha_of(tm.accent, 15),
                "text": tm.accent,
                "border": tm.alpha_of(tm.accent, 30),
            },
            "success": {
                "bg": tm.alpha_of(tm.accent, 15),
                "text": tm.accent,
                "border": tm.alpha_of(tm.accent, 30),
            },
            "warning": {
                "bg": tm.alpha_of(tm.warning, 15),
                "text": tm.warning,
                "border": tm.alpha_of(tm.warning, 30),
            },
            "danger": {
                "bg": tm.alpha_of(tm.danger, 15),
                "text": tm.danger,
                "border": tm.alpha_of(tm.danger, 30),
            },
            "info": {
                "bg": tm.alpha_of(tm.info, 15),
                "text": tm.info,
                "border": tm.alpha_of(tm.info, 30),
            },
        }

    def __init__(
        self,
        text: str = "",
        variant: str = "default",
        size: str = "default",
        closable: bool = False,
        pill: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._text = text
        self._variant = variant if variant in self._get_tag_colors() else "default"
        self._size = size if size in SIZE_CONFIG else "default"
        self._closable = closable
        self._pill = pill

        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._close_btn = None
        if closable:
            self._close_btn = _CloseButton(self)
            self._close_btn.clicked.connect(self._on_close_clicked)

        self._apply_size()

    def _get_config(self) -> dict:
        return SIZE_CONFIG.get(self._size, SIZE_CONFIG["default"])

    def _get_colors(self) -> dict:
        return self._get_tag_colors().get(self._variant, self._get_tag_colors()["default"])

    def _apply_size(self):
        config = self._get_config()
        colors = self._get_colors()

        font = QFont("Microsoft YaHei UI", config["font_size"], QFont.Weight.Medium)
        fm = self.fontMetrics()

        # Calculate text width
        old_font = self.font()
        self.setFont(font)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(self._text)
        self.setFont(old_font)

        # Calculate total width
        padding_h = config["padding_h"]
        gap = 6
        close_w = config["close_size"] if self._close_btn else 0
        total_w = padding_h * 2 + text_w + (gap + close_w if self._close_btn else 0)
        total_h = config["font_size"] + config["padding_v"] * 2

        self.setFixedSize(total_w, total_h)

        if self._close_btn:
            self._close_btn.setFixedSize(config["close_size"], config["close_size"])
            self.setProperty("_tag_text_color", colors["text"])

    def _on_close_clicked(self):
        self.closed.emit()
        self.hide()

    def paintEvent(self, event: QPaintEvent):
        config = self._get_config()
        colors = self._get_colors()

        # Radius
        if self._pill:
            radius = self.height() // 2
        else:
            radius = config["radius"]

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw background
        painter.setPen(Qt.NoPen)
        painter.setBrush(colors["bg"])
        painter.drawRoundedRect(
            QRectF(0, 0, self.width(), self.height()),
            radius,
            radius,
        )

        # Draw border
        painter.setPen(colors["border"])
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
            radius,
            radius,
        )

        # Draw text
        painter.setPen(colors["text"])
        painter.setFont(QFont("Microsoft YaHei UI", config["font_size"], QFont.Weight.Medium))

        # Position close button and calculate text area
        close_w = 0
        if self._close_btn:
            close_w = config["close_size"] + 6  # close_size + gap
            close_x = self.width() - config["padding_h"] - config["close_size"]
            close_y = (self.height() - config["close_size"]) // 2
            self._close_btn.move(int(close_x), int(close_y))

        # Draw text centered vertically
        text_x = config["padding_h"]
        text_rect = QRectF(
            text_x,
            0,
            self.width() - config["padding_h"] * 2 - close_w,
            self.height(),
        )
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)

    # ── Properties ───────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self._apply_size()
        self.update()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, value: str):
        if value not in self._get_tag_colors():
            return
        self._variant = value
        self._apply_size()
        self.update()

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in SIZE_CONFIG:
            return
        self._size = value
        self._apply_size()
        self.update()

    @property
    def closable(self) -> bool:
        return self._closable

    @closable.setter
    def closable(self, value: bool):
        if value == self._closable:
            return
        self._closable = value
        if value and not self._close_btn:
            self._close_btn = _CloseButton(self)
            self._close_btn.clicked.connect(self._on_close_clicked)
        elif not value and self._close_btn:
            self._close_btn.deleteLater()
            self._close_btn = None
        self._apply_size()
        self.update()

    @property
    def pill(self) -> bool:
        return self._pill

    @pill.setter
    def pill(self, value: bool):
        if value == self._pill:
            return
        self._pill = value
        self.update()
