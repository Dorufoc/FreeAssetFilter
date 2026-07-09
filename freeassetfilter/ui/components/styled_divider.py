"""Styled Divider component - matches web divider exactly."""

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter, QPen, QFont, QFontMetrics

from theme import tm


class StyledDivider(QWidget):
    """A divider matching the web component exactly.

    Fully self-drawn with QPainter, supporting:
        - Horizontal (default) and vertical orientations
        - Optional centered text (horizontal only)
        - Thin (1px) and thick (2px) line width
        - Solid and dashed line styles
    """

    def __init__(
        self,
        orientation: str = "horizontal",
        text: str = "",
        thick: bool = False,
        dashed: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._orientation = orientation
        self._text = text
        self._thick = thick
        self._dashed = dashed
        self._text_font = QFont("Segoe UI", 12)

        self._update_size_hint()
        self._update_size_policy()

    def _update_size_hint(self):
        """Recalculate minimum size based on orientation and content."""
        if self._orientation == "vertical":
            # CSS: width 1px, height 1em, margin 0 12px
            fm = QFontMetrics(self._text_font)
            default_h = fm.height()  # 1em
            self.setMinimumSize(1, default_h)
            self.setMaximumWidth(1)
        else:
            # Horizontal
            if self._text:
                fm = QFontMetrics(self._text_font)
                text_h = fm.height()
                self.setMinimumHeight(text_h)
            else:
                # Minimal height — just the line itself
                self.setMinimumHeight(2 if self._thick else 1)
            self.setMinimumWidth(1)

    # ── Paint ───────────────────────────────────────────────────

    def _update_size_policy(self):
        """Set size policy: expand in primary direction, fixed in cross direction."""
        if self._orientation == "vertical":
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ── Paint ───────────────────────────────────────────────────

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)

            w, h = self.width(), self.height()

            if self._orientation == "vertical":
                self._paint_vertical(painter, w, h)
            else:
                self._paint_horizontal(painter, w, h)

    def _paint_vertical(self, painter: QPainter, w: int, h: int):
        """Draw vertical line from top to bottom at horizontal center."""
        pen = self._make_pen()
        x = w / 2
        painter.setPen(pen)
        painter.drawLine(int(x), 0, int(x), h)

    def _paint_horizontal(self, painter: QPainter, w: int, h: int):
        """Draw horizontal line across full width, optionally with centered text.

        With text, the layout matches CSS:
            [line] [12px gap] [8px pad] text [8px pad] [12px gap] [line]
        where the two line segments fill the remaining width equally.
        """
        pen = self._make_pen()
        y_center = h / 2

        if self._text:
            fm = QFontMetrics(self._text_font)
            text_w = fm.horizontalAdvance(self._text)
            text_h = fm.height()
            text_ascent = fm.ascent()

            # CSS spacing values
            text_pad = 8    # .divider-text padding 0 8px
            side_gap = 12   # .divider-with-text ::before/::after margin 0 12px

            # Total half-width consumed by text + padding + gaps (one side)
            half_content = text_w / 2 + text_pad + side_gap

            # Left segment: from 0 to center - half_content
            left_end = int(w / 2 - half_content)
            if left_end > 0:
                painter.setPen(pen)
                painter.drawLine(0, int(y_center), left_end, int(y_center))

            # Right segment: from center + half_content to w
            right_start = int(w / 2 + half_content)
            if right_start < w:
                painter.setPen(pen)
                painter.drawLine(right_start, int(y_center), w, int(y_center))

            # Text centered at horizontal midpoint
            text_x = int(w / 2 - text_w / 2)
            text_y = int(y_center - text_h / 2 + text_ascent)
            painter.setFont(self._text_font)
            painter.setPen(tm.alpha_of(tm.mid, 60))
            painter.drawText(text_x, text_y, self._text)
        else:
            # Simple line across full width at vertical center
            painter.setPen(pen)
            painter.drawLine(0, int(y_center), w, int(y_center))

    def _make_pen(self) -> QPen:
        """Build the pen matching current thick/dashed configuration."""
        width = 2 if self._thick else 1
        style = Qt.DashLine if self._dashed else Qt.SolidLine
        pen = QPen(tm.alpha_of(tm.mid, 30), width, style)
        if self._dashed:
            pen.setDashPattern([4, 4])
        return pen

    # ── Public API ───────────────────────────────────────────────

    @property
    def orientation(self) -> str:
        return self._orientation

    @orientation.setter
    def orientation(self, value: str):
        if value not in ("horizontal", "vertical"):
            return
        self._orientation = value
        self._update_size_hint()
        self._update_size_policy()
        self.update()

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self._update_size_hint()
        self.update()

    @property
    def thick(self) -> bool:
        return self._thick

    @thick.setter
    def thick(self, value: bool):
        self._thick = value
        self._update_size_hint()
        self.update()

    @property
    def dashed(self) -> bool:
        return self._dashed

    @dashed.setter
    def dashed(self, value: bool):
        self._dashed = value
        self.update()
