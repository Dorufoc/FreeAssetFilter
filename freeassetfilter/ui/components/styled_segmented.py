"""StyledSegmented component — segmented control with animated focus indicator.

A segmented control (分段按钮) that renders a row of mutually exclusive
options.  The currently focused option is highlighted by an animated
indicator that smoothly slides to the newly selected segment:

- ``pill`` variant — an accent-filled capsule slides behind the active
  segment (label text turns white on top of it).
- ``underline`` variant — an accent underline bar slides beneath the
  active segment.

Both variants animate position + width via two ``QPropertyAnimation``
instances (200 ms, OutQuad), matching the animation language used by
``StyledTabWidget``.  Supports size variants (sm / default / lg), optional
icons, disabled segments, and left/right arrow-key navigation.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, Signal, Property, QRectF, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QFontMetrics, QMouseEvent, QKeyEvent

from theme import tm
from components.icon_utils import render_icon


# Per-size design tokens (vertical padding, horizontal padding, font size,
# icon size, container corner radius).
SIZE_CONFIG = {
    "sm": {"pad_v": 6, "pad_h": 12, "font": 12, "icon": 14, "radius": 7},
    "default": {"pad_v": 8, "pad_h": 16, "font": 13, "icon": 15, "radius": 9},
    "lg": {"pad_v": 10, "pad_h": 20, "font": 15, "icon": 17, "radius": 11},
}

_VALID_VARIANTS = frozenset({"pill", "underline"})
_VALID_SIZES = frozenset(SIZE_CONFIG)

_ANIM_DURATION = 200
_ICON_TEXT_GAP = 5          # px between icon and label inside a segment
_INDICATOR_INSET = 2        # px inset of the pill indicator (y and sides)
_UNDERLINE_INSET = 8        # px each side for the underline indicator


class _SegmentsHeader(QWidget):
    """Internal header widget — paints segments, hover/active states and the
    animated focus indicator.

    Fully custom-painted (no child QLabel widgets) so the sliding indicator
    can be drawn at arbitrary sub-pixel positions without layout jitter.
    Handles mouse hit-testing and arrow-key navigation; emits
    ``segment_clicked`` for both mouse clicks and keyboard moves.
    """

    segment_clicked = Signal(int)

    def __init__(self, parent, variant: str, size: str):
        super().__init__(parent)
        self._variant = variant
        self._segments: list[dict] = []           # {"label": str, "icon": str, "disabled": bool}
        self._seg_rects: list[QRectF] = []        # precomputed rects in header coords
        self._current_index = 0
        self._hover_index = -1
        self._header_height = 0

        cfg = SIZE_CONFIG.get(size, SIZE_CONFIG["default"])
        self._pad_v = cfg["pad_v"]
        self._pad_h = cfg["pad_h"]
        self._font_size = cfg["font"]
        self._icon_size = cfg["icon"]
        self._radius = cfg["radius"]

        # ── Indicator state (animated via Q_PROPERTY) ──
        self._indicator_pos = 0.0
        self._indicator_width = 0.0

        # ── Animations ──────────────────────────────────────────
        self._pos_anim = QPropertyAnimation(self, b"indicator_pos")
        self._pos_anim.setDuration(_ANIM_DURATION)
        self._pos_anim.setEasingCurve(QEasingCurve.OutQuad)

        self._width_anim = QPropertyAnimation(self, b"indicator_width")
        self._width_anim.setDuration(_ANIM_DURATION)
        self._width_anim.setEasingCurve(QEasingCurve.OutQuad)

        # Track mouse for hover without WA_Hover (multi-rect hit-testing).
        self.setMouseTracking(True)
        # Keyboard navigation works when the header (or its parent) has focus.
        self.setFocusPolicy(Qt.StrongFocus)

    # ── Theme helpers ──────────────────────────────────────────

    @property
    def _container_bg(self) -> QColor:
        """Background of the rounded container behind all segments."""
        return tm.alpha_of(tm.mid, 26)

    @property
    def _container_bg_underline(self) -> QColor:
        return tm.alpha_of(tm.mid, 18)

    @property
    def _text_secondary(self) -> QColor:
        return tm.mid

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    @property
    def _accent(self) -> QColor:
        return tm.accent

    @property
    def _disabled_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

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

    # ── Public helpers called by StyledSegmented ────────────────

    def update_segments(self, segments: list[dict]):
        """Replace the segment list and recalculate layout geometry."""
        self._segments = segments
        self._recalc_geometry()

    def set_current(self, index: int, animate: bool = True):
        """Mark *index* as active and slide the indicator to match."""
        if index < 0 or index >= len(self._seg_rects):
            return
        self._current_index = index
        target = self._seg_rects[index]
        pos, width = self._indicator_rect_for(target)

        if animate:
            self._pos_anim.stop()
            self._pos_anim.setStartValue(self._indicator_pos)
            self._pos_anim.setEndValue(pos)
            self._pos_anim.start()

            self._width_anim.stop()
            self._width_anim.setStartValue(self._indicator_width)
            self._width_anim.setEndValue(width)
            self._width_anim.start()
        else:
            self._indicator_pos = pos
            self._indicator_width = width
            self.update()

    def reconfigure(self, variant: str, size: str):
        """Update variant / size tokens and recalculate geometry."""
        self._variant = variant
        cfg = SIZE_CONFIG.get(size, SIZE_CONFIG["default"])
        self._pad_v = cfg["pad_v"]
        self._pad_h = cfg["pad_h"]
        self._font_size = cfg["font"]
        self._icon_size = cfg["icon"]
        self._radius = cfg["radius"]
        self._recalc_geometry()

    # ── Geometry ────────────────────────────────────────────────

    def _make_font(self) -> QFont:
        return QFont("Microsoft YaHei UI", self._font_size, QFont.Weight.Medium)

    def _segment_content_width(self, fm: QFontMetrics, seg: dict) -> float:
        """Total content width (icon + gap + label) for *seg*."""
        icon_w = self._icon_size if seg.get("icon") else 0.0
        gap = _ICON_TEXT_GAP if seg.get("icon") else 0.0
        return icon_w + gap + fm.horizontalAdvance(seg["label"])

    def _recalc_geometry(self):
        """Measure every segment and build the rect array + header height."""
        font = self._make_font()
        fm = QFontMetrics(font)
        text_height = fm.height()
        header_h = text_height + self._pad_v * 2

        rects: list[QRectF] = []
        x = 0.0
        for seg in self._segments:
            content_w = self._segment_content_width(fm, seg)
            seg_w = content_w + self._pad_h * 2
            rects.append(QRectF(x, 0.0, seg_w, float(header_h)))
            x += seg_w

        self._seg_rects = rects
        self._header_height = header_h
        self.setMinimumHeight(header_h)
        self.setMaximumHeight(header_h)

        if self._seg_rects and self._current_index < len(self._seg_rects):
            pos, width = self._indicator_rect_for(self._seg_rects[self._current_index])
            self._indicator_pos = pos
            self._indicator_width = width
        else:
            self._indicator_pos = 0.0
            self._indicator_width = 0.0

        self.update()

    def _indicator_rect_for(self, rect: QRectF) -> tuple[float, float]:
        """Return (x, width) of the indicator for a segment rect.

        The pill indicator insets the segment by ``_INDICATOR_INSET`` on
        each side; the underline indicator insets by ``_UNDERLINE_INSET``.
        """
        if self._variant == "underline":
            width = max(rect.width() - _UNDERLINE_INSET * 2, 8.0)
        else:
            width = max(rect.width() - _INDICATOR_INSET * 2, 8.0)
        pos = rect.x() + (rect.width() - width) / 2.0
        return pos, width

    # ── Hit-testing ─────────────────────────────────────────────

    def _segment_at(self, x: float) -> int:
        """Return the index of the segment containing *x*, or -1."""
        for i, r in enumerate(self._seg_rects):
            if r.x() <= x <= r.x() + r.width():
                return i
        return -1

    # ── Mouse events ────────────────────────────────────────────

    def mouseMoveEvent(self, event: QMouseEvent):
        idx = self._segment_at(event.position().x())
        if idx != self._hover_index:
            self._hover_index = idx
            if idx >= 0 and idx < len(self._segments) and self._segments[idx].get("disabled", False):
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

    def mousePressEvent(self, event: QMouseEvent):
        # Take focus so arrow-key navigation works right after a click.
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return
        idx = self._segment_at(event.position().x())
        if idx >= 0 and idx < len(self._segments) and not self._segments[idx].get("disabled", False):
            self.segment_clicked.emit(idx)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # ── Keyboard navigation ─────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Left:
            self._move_focus(-1)
            event.accept()
        elif event.key() == Qt.Key_Right:
            self._move_focus(1)
            event.accept()
        elif event.key() == Qt.Key_Home:
            self._jump_to(0, forward=True)
            event.accept()
        elif event.key() == Qt.Key_End:
            self._jump_to(len(self._segments) - 1, forward=False)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _move_focus(self, step: int):
        """Move the active index by *step*, skipping disabled segments."""
        n = len(self._segments)
        if n == 0:
            return
        idx = self._current_index + step
        while 0 <= idx < n:
            if not self._segments[idx].get("disabled", False):
                self.segment_clicked.emit(idx)
                return
            idx += step

    def _jump_to(self, start: int, forward: bool):
        """Jump to the nearest enabled segment starting at *start*.

        ``forward=True`` scans toward larger indexes (Home), ``False``
        toward smaller ones (End).
        """
        n = len(self._segments)
        if n == 0:
            return
        idx = start
        while 0 <= idx < n:
            if not self._segments[idx].get("disabled", False):
                self.segment_clicked.emit(idx)
                return
            idx += 1 if forward else -1

    # ── Paint ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        if not self._seg_rects:
            return

        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            w = self.width()
            h = self._header_height

            font = self._make_font()
            fm = QFontMetrics(font)

            # ── 1. Container background ────────────────────────
            painter.setPen(Qt.NoPen)
            if self._variant == "underline":
                painter.setBrush(self._container_bg_underline)
            else:
                painter.setBrush(self._container_bg)
            painter.drawRoundedRect(QRectF(0.0, 0.0, float(w), float(h)), self._radius, self._radius)

            # ── 2. Animated indicator — drawn UNDER the text so the
            #     pill never covers the active segment's label ───
            if self._indicator_width > 0:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._accent)
                if self._variant == "underline":
                    indicator_y = h - 2
                    painter.drawRoundedRect(
                        QRectF(self._indicator_pos, indicator_y, self._indicator_width, 2.0),
                        1, 1,
                    )
                else:
                    painter.drawRoundedRect(
                        QRectF(
                            self._indicator_pos,
                            _INDICATOR_INSET,
                            self._indicator_width,
                            h - _INDICATOR_INSET * 2,
                        ),
                        max(self._radius - 2, 4),
                        max(self._radius - 2, 4),
                    )

            # ── 3. Draw each segment label / icon (on top) ─────
            for i, rect in enumerate(self._seg_rects):
                if i >= len(self._segments):
                    break
                seg = self._segments[i]
                is_active = (i == self._current_index)
                is_hovered = (i == self._hover_index)
                is_disabled = seg.get("disabled", False)

                if is_disabled:
                    color = self._disabled_color
                elif is_active and self._variant == "pill":
                    color = tm.white  # on-top text over the accent pill (matches StyledButton primary)
                elif is_active:
                    color = self._accent
                elif is_hovered:
                    color = self._text_primary
                else:
                    color = self._text_secondary

                content_w = self._segment_content_width(fm, seg)
                cx = rect.x() + (rect.width() - content_w) / 2.0
                cy = rect.center().y()

                icon_w = self._icon_size if seg.get("icon") else 0.0
                if icon_w > 0:
                    icon_rect = QRectF(
                        cx,
                        cy - icon_w / 2.0,
                        icon_w,
                        icon_w,
                    )
                    render_icon(painter, seg["icon"], icon_rect, color, 1.8)
                    cx += icon_w + _ICON_TEXT_GAP

                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(
                    QRectF(cx, rect.y(), rect.x() + rect.width() - cx, rect.height()),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    seg["label"],
                )

    # ── Size hint ───────────────────────────────────────────────

    def sizeHint(self):
        total_w = sum(r.width() for r in self._seg_rects) if self._seg_rects else 0
        return QSize(int(total_w), self._header_height)


class StyledSegmented(QWidget):
    """A segmented control (分段按钮) with an animated focus indicator.

    Options are added via :meth:`add_segment`; the active option is
    highlighted by a smoothly sliding indicator (pill or underline).
    Selection is mutually exclusive and changes are reported through the
    :attr:`current_changed` signal.

    Signals:
        current_changed(int) — emitted when the active segment switches.
    """

    current_changed = Signal(int)

    def __init__(
        self,
        variant: str = "pill",
        size: str = "default",
        parent=None,
    ):
        super().__init__(parent)

        self._variant = variant if variant in _VALID_VARIANTS else "pill"
        self._size = size if size in _VALID_SIZES else "default"
        self._segments: list[dict] = []       # {"label": str, "icon": str, "disabled": bool}
        self._current_index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = _SegmentsHeader(self, self._variant, self._size)
        layout.addWidget(self._header)

        self._header.segment_clicked.connect(self._on_segment_clicked)

    # ── Public API ──────────────────────────────────────────────

    def add_segment(self, label: str, icon: str = "", disabled: bool = False) -> int:
        """Append a segment and return its index.

        Parameters
        ----------
        label : str
            Display text for the segment.
        icon : str
            Optional icon name rendered to the left of the label
            (see ``components.icon_utils`` for available names).
        disabled : bool
            If True the segment cannot be selected (default False).
        """
        index = len(self._segments)
        self._segments.append({"label": label, "icon": icon, "disabled": disabled})
        self._header.update_segments(self._segments)

        # Auto-select the first segment when it is the only (enabled) one.
        if index == 0 and not disabled:
            self._current_index = 0
            self._header.set_current(0, animate=False)
        return index

    @property
    def current_index(self) -> int:
        """The index of the currently active segment."""
        return self._current_index

    def set_current_index(self, index: int, animate: bool = True):
        """Switch the active segment to *index*.

        Does nothing if *index* is out of range, the target segment is
        disabled, or it is already the current one.
        """
        if index < 0 or index >= len(self._segments):
            return
        if self._segments[index].get("disabled", False):
            return
        if index == self._current_index:
            return

        self._current_index = index
        self._header.set_current(index, animate=animate)
        self.current_changed.emit(index)

    def segment_count(self) -> int:
        """Return the number of segments."""
        return len(self._segments)

    def clear(self):
        """Remove all segments and reset to the default state."""
        self._segments.clear()
        self._current_index = 0
        self._header.update_segments([])
        self._header.set_current(0, animate=False)

    def set_segment_disabled(self, index: int, disabled: bool):
        """Enable or disable the segment at *index*."""
        if 0 <= index < len(self._segments):
            self._segments[index]["disabled"] = disabled
            self._header.update()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, value: str):
        if value not in _VALID_VARIANTS:
            return
        self._variant = value
        self._header.reconfigure(value, self._size)

    @property
    def size(self) -> str:
        return self._size

    @size.setter
    def size(self, value: str):
        if value not in _VALID_SIZES:
            return
        self._size = value
        self._header.reconfigure(self._variant, value)

    # ── Internal slots ──────────────────────────────────────────

    def _on_segment_clicked(self, index: int):
        self.set_current_index(index)

    # ── Size hint ───────────────────────────────────────────────

    def sizeHint(self):
        return self._header.sizeHint()
