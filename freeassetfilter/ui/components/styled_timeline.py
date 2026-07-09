"""Styled Timeline component - matches web timeline exactly.

Provides a vertical timeline with colored dots, connecting line,
icon variants, size variants, and an empty state.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QBrush

from .icon_utils import render_icon
from theme import tm

DOT_SIZE_MAP: dict[str, float] = {
    "sm": 8.0,
    "default": 12.0,
    "lg": 16.0,
}

# Variants where the line segment above the dot is also colored
_COLORED_LINE_VARIANTS = frozenset({"primary", "danger"})

# Layout constants (from CSS)
LINE_X = 7           # vertical-line center x (from item-left edge)
DOT_CX = 7           # dot center x (centred on the line)
CONTENT_X = 24       # content start x (12–17 px right of dot)
DOT_TOP_Y = 4        # dot top y from item top


# ═══════════════════════════════════════════════════════════════════════
# Internal: single timeline item
# ═══════════════════════════════════════════════════════════════════════


class _TimelineItem(QWidget):
    """A single timeline node – dot, connecting line, and content.

    Fully self-drawn via ``paintEvent``.  Colour / icon / size variants
    are set at construction time.
    """

    def __init__(
        self,
        title: str = "",
        description: str = "",
        time_str: str = "",
        color: str = "default",
        icon: str = "",
        size_variant: str = "default",
        is_last: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._title = title
        self._description = description
        self._time_str = time_str
        self._color_name = color if color in self._color_map() else "default"
        self._icon = icon
        self._dot_diameter = DOT_SIZE_MAP.get(size_variant, DOT_SIZE_MAP["default"])
        self._is_last = is_last

        self._title_font = QFont("Microsoft YaHei UI", 13, QFont.Weight.Medium)
        self._desc_font = QFont("Microsoft YaHei UI", 12)
        self._time_font = QFont("Microsoft YaHei UI", 11)

        self._update_size()

    # ── Theme helpers ────────────────────────────────────────────

    @staticmethod
    def _color_map() -> dict[str, QColor]:
        return {
            "primary": tm.accent,
            "warning": tm.warning,
            "danger": tm.danger,
            "info": tm.info,
            "default": tm.mid,
        }

    @property
    def _line_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 30)

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    @property
    def _text_secondary(self) -> QColor:
        return tm.mid

    @property
    def _text_tertiary(self) -> QColor:
        return tm.alpha_of(tm.mid, 60)

    # ── Public helpers ─────────────────────────────────────────────

    def set_is_last(self, is_last: bool) -> None:
        """Mark whether this is the last item (removes bottom spacing)."""
        if self._is_last != is_last:
            self._is_last = is_last
            self._update_size()

    # ── Internals ──────────────────────────────────────────────────

    def _get_color(self) -> QColor:
        return self._color_map().get(self._color_name, self._color_map()["default"])

    def _use_colored_line(self) -> bool:
        return self._color_name in _COLORED_LINE_VARIANTS

    def _update_size(self) -> None:
        fm_title = QFontMetrics(self._title_font)
        title_h = fm_title.height() if self._title else 0
        desc_h = QFontMetrics(self._desc_font).height() if self._description else 0
        time_h = QFontMetrics(self._time_font).height() if self._time_str else 0

        content_h = title_h
        if self._description:
            content_h += 4 + desc_h
        if self._time_str:
            content_h += 4 + time_h

        dot_end = DOT_TOP_Y + self._dot_diameter
        item_h = max(dot_end, content_h)
        if not self._is_last:
            item_h += 24  # bottom spacing between items

        self.setFixedHeight(max(1, item_h))

    # ── Paint ──────────────────────────────────────────────────────

    def paintEvent(self, event):  # noqa: N802
        color = self._get_color()
        dot_r = self._dot_diameter / 2.0
        dot_cy = DOT_TOP_Y + dot_r  # dot centre y
        w = self.width()
        h = self.height()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # ── 1. Vertical connecting line ──
        gray_pen = QPen(self._line_color, 2)
        if self._use_colored_line():
            # Coloured segment above the dot (primary / danger)
            colored_pen = QPen(color, 2)
            painter.setPen(colored_pen)
            painter.drawLine(LINE_X, 0, LINE_X, int(dot_cy))
            painter.setPen(gray_pen)
            painter.drawLine(LINE_X, int(dot_cy), LINE_X, h)
        else:
            painter.setPen(gray_pen)
            painter.drawLine(LINE_X, 0, LINE_X, h)

        # ── 2. Dot / Icon ──
        if self._icon:
            # Icon variant: 20×20 outlined circle with icon drawn inside
            icon_size = 20.0
            icon_r = icon_size / 2.0
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(
                QRectF(DOT_CX - icon_r, dot_cy - icon_r, icon_size, icon_size)
            )
            icon_rect = QRectF(
                DOT_CX - icon_r, dot_cy - icon_r, icon_size, icon_size
            )
            render_icon(painter, self._icon, icon_rect, color, pen_width=1.5)
        else:
            # Solid dot filled with colour variant
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(
                QRectF(DOT_CX - dot_r, DOT_TOP_Y, self._dot_diameter, self._dot_diameter)
            )

        # ── 3. Content ──
        content_right = max(1, w - CONTENT_X - 8)
        y = 0

        if self._title:
            painter.setFont(self._title_font)
            painter.setPen(self._text_primary)
            tr = QRectF(CONTENT_X, y, content_right, 20)
            painter.drawText(tr, Qt.AlignLeft | Qt.AlignTop, self._title)
            y += QFontMetrics(self._title_font).height()

        if self._description:
            y += 4
            painter.setFont(self._desc_font)
            painter.setPen(self._text_secondary)
            dr = QRectF(CONTENT_X, y, content_right, 18)
            painter.drawText(dr, Qt.AlignLeft | Qt.AlignTop, self._description)
            y += QFontMetrics(self._desc_font).height()

        if self._time_str:
            y += 4
            painter.setFont(self._time_font)
            painter.setPen(self._text_tertiary)
            tr = QRectF(CONTENT_X, y, content_right, 16)
            painter.drawText(tr, Qt.AlignLeft | Qt.AlignTop, self._time_str)

    def sizeHint(self):  # noqa: N802
        return QSize(200, self.height())


# ═══════════════════════════════════════════════════════════════════════
# Internal: empty-state placeholder
# ═══════════════════════════════════════════════════════════════════════


class _TimelineEmptyState(QWidget):
    """Centred icon + "暂无数据" message shown when no items exist."""

    @property
    def _text_tertiary(self) -> QColor:
        return tm.alpha_of(tm.mid, 60)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0

        # Icon (bell, 28×28)
        icon_size = 28.0
        icon_rect = QRectF(cx - icon_size / 2, cy - icon_size / 2 - 6, icon_size, icon_size)
        render_icon(painter, "bell", icon_rect, self._text_tertiary, pen_width=1.5)

        # Text
        painter.setFont(QFont("Microsoft YaHei UI", 12))
        painter.setPen(self._text_tertiary)
        text_rect = QRectF(0, cy + 10, w, 20)
        painter.drawText(text_rect, Qt.AlignCenter, "暂无数据")


# ═══════════════════════════════════════════════════════════════════════
# Public container
# ═══════════════════════════════════════════════════════════════════════


class StyledTimeline(QWidget):
    """Vertical timeline container matching the web component.

    Usage::

        timeline = StyledTimeline()
        timeline.add_item("Title", "Description", time_str="2024-01-01",
                          color="primary")
        timeline.add_item("Icon item", icon="bell", color="warning")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._empty_state = _TimelineEmptyState(self)
        self._layout.addWidget(self._empty_state)

        self._items: list[_TimelineItem] = []

    # ── Public API ─────────────────────────────────────────────────

    def add_item(
        self,
        title: str = "",
        description: str = "",
        time_str: str = "",
        color: str = "default",
        icon: str = "",
        size_variant: str = "default",
    ) -> _TimelineItem:
        """Append a timeline item and return the created widget.

        Parameters
        ----------
        title:
            Primary item text (13 px, medium weight).
        description:
            Secondary text (12 px, grey).
        time_str:
            Timestamp / auxiliary text (11 px, muted).
        color:
            One of ``"primary"``, ``"warning"``, ``"danger"``,
            ``"info"``, ``"default"``.
        icon:
            Name of an icon from :mod:`icon_utils` to render inside the
            dot circle.  When set the dot becomes a 20×20 outlined circle.
        size_variant:
            Dot size: ``"sm"`` (8 px), ``"default"`` (12 px), ``"lg"`` (16 px).
        """
        item = _TimelineItem(title, description, time_str, color, icon, size_variant)
        self._items.append(item)
        self._refresh_last_flag()
        self._layout.addWidget(item)
        self._toggle_empty_state()
        return item

    def clear(self) -> None:
        """Remove all timeline items."""
        for item in self._items:
            self._layout.removeWidget(item)
            item.deleteLater()
        self._items.clear()
        self._toggle_empty_state()
        self.update()

    @property
    def items(self) -> list[_TimelineItem]:
        """Read-only list of current items."""
        return list(self._items)

    # ── Internals ──────────────────────────────────────────────────

    def _refresh_last_flag(self) -> None:
        for i, item in enumerate(self._items):
            item.set_is_last(i == len(self._items) - 1)

    def _toggle_empty_state(self) -> None:
        has_items = bool(self._items)
        self._empty_state.setVisible(not has_items)
        for item in self._items:
            item.setVisible(has_items)
