"""Styled Tabs component - matches web tabs exactly.

SIZE_OK: 301 pure LOC across _TabHeader (private internal paint class)
and StyledTabWidget (public API).  _TabHeader must stay co-located because
it shares animation state and geometry logic with the parent widget —
separating them would add a public surface for an internal implementation
detail with no caller benefit.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QStackedWidget
from PySide6.QtCore import Qt, Signal, Property, QRectF, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QFontMetrics, QMouseEvent

from theme import tm


# Tab padding per size variant (vertical, horizontal, font_size)
SIZE_CONFIG = {
    "sm": {"pad_v": 8, "pad_h": 16, "font": 12},
    "default": {"pad_v": 10, "pad_h": 20, "font": 13},
    "lg": {"pad_v": 12, "pad_h": 24, "font": 15},
}


class _TabHeader(QWidget):
    """Internal header widget — paints tab labels, hover/active states, and indicator.

    This is a full custom-paint widget (no child QLabel widgets) so that
    the animated underline indicator can be drawn at arbitrary sub-pixel
    positions without layout jitter.
    """

    tab_clicked = Signal(int)
    tab_hovered = Signal(int)

    def __init__(self, parent, variant: str, size: str):
        super().__init__(parent)
        self._variant = variant
        self._tabs: list[dict] = []           # each: {"label": str, "disabled": bool}
        self._tab_rects: list[QRectF] = []    # precomputed rects in header coords
        self._current_index = 0
        self._hover_index = -1
        self._header_height = 0

        cfg = SIZE_CONFIG.get(size, SIZE_CONFIG["default"])
        self._pad_v = cfg["pad_v"]
        self._pad_h = cfg["pad_h"]
        self._font_size = cfg["font"]

        # ── Underline indicator state (animated via Q_PROPERTY) ──
        self._indicator_pos = 0.0
        self._indicator_width = 0.0

        # ── Animations ──────────────────────────────────────────
        self._pos_anim = QPropertyAnimation(self, b"indicator_pos")
        self._pos_anim.setDuration(200)
        self._pos_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._width_anim = QPropertyAnimation(self, b"indicator_width")
        self._width_anim.setDuration(200)
        self._width_anim.setEasingCurve(QEasingCurve.OutQuad)

        # Track mouse for hover without WA_Hover (more reliable for
        # multi-rect hit-testing).
        self.setMouseTracking(True)

    # ── Theme helpers ──────────────────────────────────────────

    @property
    def _text_secondary(self) -> QColor:
        return tm.mid

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    @property
    def _accent_primary(self) -> QColor:
        return tm.accent

    @property
    def _disabled_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    @property
    def _divider_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 30)

    # ── Q_PROPERTYs for animation ───────────────────────────────

    @Property(float)
    def indicator_pos(self):
        return self._indicator_pos

    @indicator_pos.setter
    def indicator_pos(self, value: float):
        self._indicator_pos = value
        self.update()

    @Property(float)
    def indicator_width(self):
        return self._indicator_width

    @indicator_width.setter
    def indicator_width(self, value: float):
        self._indicator_width = value
        self.update()

    # ── Public helpers called by StyledTabWidget ────────────────

    def update_tabs(self, tabs: list[dict]):
        """Replace the tab list and recalculate layout geometry."""
        self._tabs = tabs
        self._recalc_geometry()

    def set_current(self, index: int, animate: bool = True):
        """Mark *index* as active and slide the indicator to match."""
        if index < 0 or index >= len(self._tab_rects):
            return
        self._current_index = index
        target = self._tab_rects[index]

        if animate and self._variant == "underline":
            self._pos_anim.stop()
            self._pos_anim.setStartValue(self._indicator_pos)
            self._pos_anim.setEndValue(target.x())
            self._pos_anim.start()

            self._width_anim.stop()
            self._width_anim.setStartValue(self._indicator_width)
            self._width_anim.setEndValue(target.width())
            self._width_anim.start()
        else:
            self._indicator_pos = target.x()
            self._indicator_width = target.width()
            self.update()

    def reconfigure(self, variant: str, size: str):
        """Update variant / size tokens and recalculate (called when parent props change)."""
        self._variant = variant
        cfg = SIZE_CONFIG.get(size, SIZE_CONFIG["default"])
        self._pad_v = cfg["pad_v"]
        self._pad_h = cfg["pad_h"]
        self._font_size = cfg["font"]
        self._recalc_geometry()

    # ── Geometry ────────────────────────────────────────────────

    def _make_font(self) -> QFont:
        return QFont("Microsoft YaHei UI", self._font_size, QFont.Weight.Medium)

    def _recalc_geometry(self):
        """Measure every tab label and build the rect array + header height."""
        font = self._make_font()
        fm = QFontMetrics(font)
        text_height = fm.height()
        header_h = text_height + self._pad_v * 2

        rects: list[QRectF] = []
        x = 0.0
        for tab in self._tabs:
            text_w = fm.horizontalAdvance(tab["label"])
            tab_w = text_w + self._pad_h * 2
            rects.append(QRectF(x, 0.0, tab_w, float(header_h)))
            x += tab_w

        self._tab_rects = rects
        self._header_height = header_h
        self.setMinimumHeight(header_h)
        self.setMaximumHeight(header_h)

        # If there is at least one tab, ensure the indicator matches
        if self._tab_rects and self._current_index < len(self._tab_rects):
            r = self._tab_rects[self._current_index]
            self._indicator_pos = r.x()
            self._indicator_width = r.width()
        else:
            self._indicator_pos = 0.0
            self._indicator_width = 0.0

        self.update()

    # ── Hit-testing ─────────────────────────────────────────────

    def _tab_at(self, x: float) -> int:
        """Return the index of the tab containing *x*, or -1."""
        for i, r in enumerate(self._tab_rects):
            if r.x() <= x <= r.x() + r.width():
                return i
        return -1

    # ── Mouse events ────────────────────────────────────────────

    def mouseMoveEvent(self, event: QMouseEvent):
        idx = self._tab_at(event.position().x())
        if idx != self._hover_index:
            self._hover_index = idx
            self.tab_hovered.emit(idx)
            # Update cursor
            if idx >= 0 and idx < len(self._tabs) and self._tabs[idx].get("disabled", False):
                self.setCursor(Qt.ArrowCursor)
            elif idx >= 0:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_index = -1
        self.setCursor(Qt.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        idx = self._tab_at(event.position().x())
        if idx >= 0 and idx < len(self._tabs) and not self._tabs[idx].get("disabled", False):
            self.tab_clicked.emit(idx)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # ── Paint ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        if not self._tab_rects:
            return

        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            w = self.width()
            h = self._header_height

            font = self._make_font()
            fm = QFontMetrics(font)

            # ── 1. Bottom divider (underline variant) ─────────
            if self._variant == "underline":
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._divider_color)
                painter.drawRect(0, h - 1, w, 1)

            # ── 2. Draw each tab label ────────────────────────
            for i, rect in enumerate(self._tab_rects):
                if i >= len(self._tabs):
                    break
                tab = self._tabs[i]
                is_active = (i == self._current_index)
                is_hovered = (i == self._hover_index)
                is_disabled = tab.get("disabled", False)

                # Determine text color
                if is_disabled:
                    color = self._disabled_color
                elif is_active:
                    color = self._accent_primary
                elif is_hovered:
                    color = self._text_primary
                else:
                    color = self._text_secondary

                text_x = rect.x() + self._pad_h
                text_y = rect.y() + (rect.height() - fm.height()) / 2 + fm.ascent()

                # ── Pill background ───────────────────────────────
                if self._variant == "pills" and is_active:
                    painter.setPen(Qt.NoPen)
                    bg = QColor(self._accent_primary)
                    bg.setAlpha(51)  # 20 % opacity
                    painter.setBrush(bg)
                    painter.drawRoundedRect(rect.adjusted(0, 2, 0, -2), 4, 4)

                    # Accent underline for active pill
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(self._accent_primary)
                    accent_y = h - 2
                    painter.drawRoundedRect(
                        QRectF(rect.x() + 8, accent_y, rect.width() - 16, 2), 1, 1
                    )

                # ── Label ─────────────────────────────────────────
                painter.setPen(color)
                painter.setFont(font)
                painter.drawText(int(text_x), int(text_y), tab["label"])

            # ── 3. Underline indicator (underline variant only) ──
            if self._variant == "underline" and self._indicator_width > 0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._accent_primary)
                indicator_y = h - 2
                painter.drawRoundedRect(
                    QRectF(self._indicator_pos, indicator_y, self._indicator_width, 2),
                    1, 1,
                )

    # ── Size hint ───────────────────────────────────────────────

    def sizeHint(self):
        total_w = sum(r.width() for r in self._tab_rects) if self._tab_rects else 0
        return QSize(int(total_w), self._header_height)


class StyledTabWidget(QWidget):
    """A tab widget matching the web component exactly.

    Provides a header row of clickable tab labels (fully custom-painted)
    and a QStackedWidget for tab content.  The active tab is indicated
    by either an animated underline (underline variant) or a filled pill
    background (pills variant).

    Signals:
        current_changed(int) — emitted when the active tab switches.
    """

    current_changed = Signal(int)

    def __init__(
        self,
        variant: str = "underline",
        size: str = "default",
        parent=None,
    ):
        super().__init__(parent)

        self._variant = variant
        self._size = size
        self._tabs: list[dict] = []       # {"label": str, "disabled": bool}
        self._current_index = 0

        # Layout: vertical stack of header + content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = _TabHeader(self, variant, size)
        self._content_stack = QStackedWidget()

        layout.addWidget(self._header)
        layout.addWidget(self._content_stack, 1)  # stretch

        # Wire header signals
        self._header.tab_clicked.connect(self._on_tab_clicked)

    # ── Public API ──────────────────────────────────────────────

    def add_tab(self, label: str, widget: QWidget, disabled: bool = False) -> int:
        """Append a tab and return its index.

        Parameters
        ----------
        label : str
            Display text for the tab header.
        widget : QWidget
            Content widget shown when this tab is active.
        disabled : bool
            If True the tab cannot be selected (default False).
        """
        index = len(self._tabs)
        self._tabs.append({"label": label, "disabled": disabled})
        self._content_stack.addWidget(widget)
        self._header.update_tabs(self._tabs)

        # Auto-select the first non-disabled tab
        if self._current_index == 0 and not disabled and index == 0:
            self.set_current_index(0)
        elif self._current_index == 0 and index == 0 and disabled:
            # First tab is disabled — try to find the next non-disabled one
            self._current_index = 0
            self._header.set_current(0, animate=False)

        return index

    @property
    def current_index(self) -> int:
        """The index of the currently active tab."""
        return self._current_index

    def set_current_index(self, index: int):
        """Switch to the tab at *index*.

        Does nothing if *index* is out of range or the target tab is
        disabled.
        """
        if index < 0 or index >= len(self._tabs):
            return
        if self._tabs[index].get("disabled", False):
            return
        if index == self._current_index:
            return

        self._current_index = index
        self._content_stack.setCurrentIndex(index)
        self._header.set_current(index)
        self.current_changed.emit(index)

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, value: str):
        if value not in ("underline", "pills"):
            return
        self._variant = value
        self._header.reconfigure(value, self._size)

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in SIZE_CONFIG:
            return
        self._size = value
        self._header.reconfigure(self._variant, value)

    def tab_count(self) -> int:
        """Return the number of tabs."""
        return len(self._tabs)

    def set_tab_disabled(self, index: int, disabled: bool):
        """Enable or disable the tab at *index*."""
        if 0 <= index < len(self._tabs):
            self._tabs[index]["disabled"] = disabled

    # ── Internal slots ──────────────────────────────────────────

    def _on_tab_clicked(self, index: int):
        self.set_current_index(index)
