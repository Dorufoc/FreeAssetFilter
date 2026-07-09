"""Styled Badge component - matches web badge exactly."""

from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QFontMetrics, QPen
from theme import tm


SIZE_CONFIG = {
    "sm": {"pad_v": 1, "pad_h": 6, "font": 10, "min_w": 16},
    "default": {"pad_v": 2, "pad_h": 8, "font": 11, "min_w": 20},
    "lg": {"pad_v": 4, "pad_h": 12, "font": 13, "min_w": 26},
}


class StyledBadge(QWidget):
    """A badge component matching the web component exactly.

    Variants:
        - solid: filled background with white text (default)
        - dot: 8x8 perfect circle, no text
        - outline: transparent bg, 1px solid border with color

    Color variants: primary, warning, danger, info, purple, default
    Size variants: sm, default, lg
    """

    @staticmethod
    def _badge_colors():
        return {
            "primary": tm.accent,
            "warning": tm.warning,
            "danger": tm.danger,
            "info": tm.info,
            "purple": tm.purple,
            "default": tm.mid,
        }

    def __init__(
        self,
        text: str = "",
        variant: str = "solid",
        color: str = "default",
        size: str = "default",
        parent=None,
    ):
        super().__init__(parent)
        self._text = text
        self._variant = variant if variant in ("solid", "dot", "outline") else "solid"
        colors = self._badge_colors()
        self._color_name = color if color in colors else "default"
        self._size = size if size in SIZE_CONFIG else "default"

        self.setAttribute(Qt.WA_StyledBackground, False)
        self._update_size()

    def _get_config(self) -> dict:
        return SIZE_CONFIG.get(self._size, SIZE_CONFIG["default"])

    def _get_color(self) -> QColor:
        colors = self._badge_colors()
        return colors.get(self._color_name, colors["default"])

    def _update_size(self):
        """Recalculate widget size based on text + padding (for text-bearing variants)."""
        if self._variant == "dot":
            self.setFixedSize(8, 8)
            return

        config = self._get_config()
        font = QFont("Microsoft YaHei UI", config["font"], QFont.Weight.Medium)
        fm = QFontMetrics(font)

        text_w = fm.horizontalAdvance(self._text) if self._text else 0
        pad_h = config["pad_h"]
        pad_v = config["pad_v"]
        min_w = config["min_w"]

        total_w = max(text_w + pad_h * 2, min_w)
        total_h = fm.height() + pad_v * 2

        self.setFixedSize(total_w, total_h)

    # ── Paint ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        color = self._get_color()
        config = self._get_config()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        if self._variant == "dot":
            # Dot: 8x8 perfect circle filled with color
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(0, 0, w, h)
            return

        radius = h // 2  # pill shape (fully rounded)

        if self._variant == "solid":
            # Solid: filled background with white text
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

            if self._text:
                painter.setPen(Qt.white)
                font = QFont("Microsoft YaHei UI", config["font"], QFont.Weight.Medium)
                painter.setFont(font)
                painter.drawText(
                    QRectF(config["pad_h"], 0, w - config["pad_h"] * 2, h),
                    Qt.AlignCenter,
                    self._text,
                )

        elif self._variant == "outline":
            # Outline: transparent bg, 1px solid border in currentColor
            painter.setPen(QPen(color, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)

            if self._text:
                painter.setPen(color)
                font = QFont("Microsoft YaHei UI", config["font"], QFont.Weight.Medium)
                painter.setFont(font)
                painter.drawText(
                    QRectF(config["pad_h"], 0, w - config["pad_h"] * 2, h),
                    Qt.AlignCenter,
                    self._text,
                )

    # ── Properties ───────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        if self._variant != "dot":
            self._update_size()
        self.update()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, value: str):
        if value not in ("solid", "dot", "outline"):
            return
        self._variant = value
        self._update_size()
        self.update()

    @property
    def color_variant(self) -> str:
        return self._color_name

    @color_variant.setter
    def color_variant(self, value: str):
        if value not in self._badge_colors():
            return
        self._color_name = value
        self.update()

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in SIZE_CONFIG:
            return
        self._size = value
        if self._variant != "dot":
            self._update_size()
        self.update()


class BadgeWrapper(QWidget):
    """Wrapper that positions a badge as overlay on another widget.

    Matches web `.badge-wrapper` behavior: places the badge at the
    top-right corner with a -4px outward offset (badge sticks out
    slightly from the parent).

    Usage:
        button = QPushButton("Notifications")
        badge = StyledBadge(text="3", variant="solid", color="danger")
        wrapper = BadgeWrapper(button, badge)
    """

    def __init__(self, child: QWidget, badge: StyledBadge, parent=None):
        super().__init__(parent)
        self._child = child
        self._badge = badge

        # Layout manages the child widget, filling the wrapper
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(child)

        # Badge is NOT in layout - positioned absolutely
        badge.setParent(self)
        badge.raise_()
        self._reposition_badge()

    def _reposition_badge(self):
        """Position badge at top-right with -4px outward offset.

        CSS equivalent: position: absolute; top: -4px; right: -4px;
        """
        bw = self._badge.width()
        x = self.width() - bw + 4  # right: -4px → badge right edge beyond wrapper
        self._badge.move(x, -4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_badge()

    def child_widget(self) -> QWidget:
        """Return the wrapped child widget."""
        return self._child

    def badge_widget(self) -> StyledBadge:
        """Return the badge overlay widget."""
        return self._badge
