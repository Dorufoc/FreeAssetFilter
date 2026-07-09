"""Styled Tooltip component — matches web tooltip exactly.

Attaches to any QWidget, shows on hover with a 300 ms delay and
fade-in animation.  Draws a rounded-rect bubble + a rotated-square
arrow pointing to the parent widget.  Auto-flips placement when
near a screen edge.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QPointF, QRectF, QEvent
from PySide6.QtGui import QPainter, QPen, QFont, QFontMetrics
from PySide6.QtGui import QPainterPath, QTransform

from theme import tm

# ── Design constants (pure integers, not theme-derived) ──────────────
FONT_SIZE = 12
PADDING_H = 12
PADDING_V = 6
BORDER_RADIUS = 6
ARROW_SIZE = 8          # rotated-square side length
ARROW_OVERLAP = 2       # px the arrow sinks into the bubble
GAP = 8                 # px between bubble edge and parent
FADE_DURATION = 150      # ms
SHOW_DELAY = 300         # ms (avoid flicker on rapid hover)

# Half-diagonal of the rotated square: 8 × √2 / 2 ≈ 5.66 → 6
_ARROW_HALF = int(ARROW_SIZE * 2**0.5 / 2 + 0.5)


class StyledTooltip(QWidget):
    """A tooltip that attaches to any QWidget.

    Shows on hover with a fade-in animation.  The tooltip is a
    top-level :attr:`Qt.ToolTip` window — it does not accept focus
    or mouse events, and has no taskbar entry.

    Parameters
    ----------
    parent_widget:
        The widget to attach the tooltip to.
    text:
        The tooltip label.
    placement:
        Preferred placement.  One of ``"top"`` (default),
        ``"bottom"``, ``"left"``, or ``"right"``.  The tooltip
        automatically flips to the opposite side if it would go
        off-screen.
    """

    def __init__(self, parent_widget: QWidget, text: str,
                 placement: str = "top") -> None:
        super().__init__(parent_widget.window())
        self._parent = parent_widget
        self._text = text
        self._requested = placement
        self._actual = placement
        self._visible = False

        # Window flags — no taskbar entry, no focus
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        # Compute content / widget sizes
        self._compute_sizes()

        # Show timer (debounce rapid hover)
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._do_show)

        # Fade animation
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_DURATION)

        # Event filter on the parent widget
        parent_widget.installEventFilter(self)

        # Also listen to the top-level window for move/resize
        window = parent_widget.window()
        if window != parent_widget:
            window.installEventFilter(self)

    # ── Sizing ──────────────────────────────────────────────────────

    def _compute_sizes(self) -> None:
        """Calculate bubble content size and total widget size."""
        font = QFont("Microsoft YaHei UI", FONT_SIZE)
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(self._text) if self._text else 0
        text_h = fm.height()

        self._content_w = max(text_w + PADDING_H * 2, 30)
        self._content_h = text_h + PADDING_V * 2
        self._font = font

        # Extension of arrow beyond the bubble edge
        ext = _ARROW_HALF - ARROW_OVERLAP

        # Calculate size based on placement
        if self._requested in ("left", "right"):
            w = self._content_w + ext
            h = self._content_h
        else:
            w = self._content_w
            h = self._content_h + ext

        self._total_w = w
        self._total_h = h
        self.setFixedSize(int(w), int(h))

    # ── Event filter ───────────────────────────────────────────────

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        etype = event.type()

        if obj is self._parent:
            if etype == QEvent.Enter:
                self._show_timer.start(SHOW_DELAY)
            elif etype == QEvent.Leave:
                self._show_timer.stop()
                self.hide()
            elif etype in (QEvent.Hide, QEvent.Destroy):
                self._show_timer.stop()
                self.hide()
            elif etype in (QEvent.Move, QEvent.Resize) and self._visible:
                self._reposition()
        elif obj is self._parent.window():
            if etype in (QEvent.Move, QEvent.Resize) and self._visible:
                self._reposition()

        return super().eventFilter(obj, event)

    # ── Show / hide ────────────────────────────────────────────────

    def _do_show(self) -> None:
        """Compute position, place widget, start fade-in."""
        pos = self._calc_position()
        self.move(pos)
        self.setWindowOpacity(0.0)
        super().show()
        self._visible = True

        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def hide(self) -> None:
        self._visible = False
        self._show_timer.stop()
        super().hide()

    def hideEvent(self, event: QEvent) -> None:
        self._visible = False
        self._show_timer.stop()
        super().hideEvent(event)

    # ── Positioning ────────────────────────────────────────────────

    def _calc_position(self) -> QPoint:
        """Return the global top-left position for the tooltip.

        Tries the requested placement first.  If the tooltip would
        extend beyond the available screen geometry, it flips to
        the opposite placement.
        """
        p = self._parent.mapToGlobal(QPoint(0, 0))
        pr = QRectF(float(p.x()), float(p.y()),
                    float(self._parent.width()), float(self._parent.height()))

        screen = QApplication.primaryScreen().availableGeometry()

        placements = [self._requested]
        flip = {"top": "bottom", "bottom": "top",
                "left": "right", "right": "left"}
        placements.append(flip[self._requested])

        for pl in placements:
            pos = self._pos_for(pl, pr)
            tr = QRectF(float(pos.x()), float(pos.y()),
                        float(self._total_w), float(self._total_h))
            if screen.contains(tr.toRect()):
                self._actual = pl
                return pos

        # Fallback — clamp to screen
        self._actual = self._requested
        pos = self._pos_for(self._requested, pr)
        return pos

    def _pos_for(self, placement: str, pr: QRectF) -> QPoint:
        """Return top-left widget position for a given placement."""
        cx = pr.center().x()
        cy = pr.center().y()
        ext = _ARROW_HALF - ARROW_OVERLAP

        # Calculate position based on placement
        if placement == "top":
            x = cx - self._total_w / 2
            y = pr.top() - GAP - self._content_h
        elif placement == "bottom":
            x = cx - self._total_w / 2
            y = pr.bottom() + GAP - ext
        elif placement == "left":
            x = pr.left() - GAP - self._content_w
            y = cy - self._total_h / 2
        else:  # right
            x = pr.right() + GAP - ext
            y = cy - self._total_h / 2

        return QPoint(int(x), int(y))

    def _reposition(self) -> None:
        if self._visible:
            self.move(self._calc_position())

    # ── Paint ──────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        bubble_bg = tm.alpha_of(tm.surface, 90)
        bubble_border = tm.alpha_of(tm.mid, 40)
        text_color = tm.text

        ext = _ARROW_HALF - ARROW_OVERLAP
        cw = self._content_w
        ch = self._content_h

        # Bubble rect  /  arrow centre  (widget-local coords)
        if self._actual == "top":
            bubble = QRectF(0.0, 0.0, float(cw), float(ch))
            arrow_c = QPointF(float(cw) / 2, float(ch) - ARROW_OVERLAP)
        elif self._actual == "bottom":
            bubble = QRectF(0.0, float(ext), float(cw), float(ch))
            arrow_c = QPointF(float(cw) / 2, float(ext) + ARROW_OVERLAP)
        elif self._actual == "left":
            bubble = QRectF(0.0, 0.0, float(cw), float(ch))
            arrow_c = QPointF(float(cw) - ARROW_OVERLAP, float(ch) / 2)
        else:  # right
            bubble = QRectF(float(ext), 0.0, float(cw), float(ch))
            arrow_c = QPointF(float(ext) + ARROW_OVERLAP, float(ch) / 2)

        # ── Combined shape: rounded-rect bubble + rotated square ──
        path = QPainterPath()
        path.addRoundedRect(bubble, float(BORDER_RADIUS), float(BORDER_RADIUS))

        arrow_local = QPainterPath()
        hs = ARROW_SIZE / 2.0
        arrow_local.addRect(QRectF(-hs, -hs, float(ARROW_SIZE), float(ARROW_SIZE)))

        t = QTransform()
        t.translate(arrow_c.x(), arrow_c.y())
        t.rotate(45)
        path.addPath(t.map(arrow_local))

        # Fill + stroke
        painter.setPen(QPen(bubble_border, 1.0))
        painter.setBrush(bubble_bg)
        painter.drawPath(path)

        # ── Text ──────────────────────────────────────────────────
        if self._text:
            painter.setPen(text_color)
            painter.setFont(self._font)
            text_rect = QRectF(
                bubble.x() + PADDING_H,
                bubble.y() + PADDING_V,
                cw - PADDING_H * 2,
                ch - PADDING_V * 2,
            )
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             self._text)
