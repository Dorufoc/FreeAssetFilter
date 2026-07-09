"""Styled Breadcrumb component - matches web breadcrumb exactly."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal, QRectF, QRect, QPointF
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QFont,
    QFontMetrics,
    QPainterPath,
    QMouseEvent,
    QPaintEvent,
)
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSizePolicy

from theme import tm


SIZE_CONFIG = {
    "sm": {"font": 12, "pad_v": 2, "pad_h": 4, "sep_font": 11},
    "default": {"font": 13, "pad_v": 4, "pad_h": 6, "sep_font": 12},
    "lg": {"font": 14, "pad_v": 6, "pad_h": 8, "sep_font": 13},
}

ICON_SIZE = 14
ICON_TEXT_GAP = 4
RADIUS = 4


# ── SVG Path Data Parser ──────────────────────────────────────


def _tokenize_path(path_data: str) -> list:
    """Tokenize SVG path data into commands and numeric arguments."""
    tokens: list = []
    i = 0
    n = len(path_data)
    while i < n:
        ch = path_data[i]
        if ch in " \t\n\r,":
            i += 1
            continue
        if ch in "AZMCLQTSazmclqtsHhVv":
            tokens.append(ch)
            i += 1
        elif ch in ("-", "+") or ch.isdigit() or ch == ".":
            start = i
            if path_data[i] in ("-", "+"):
                i += 1
            while i < n and (path_data[i].isdigit() or path_data[i] == "."):
                if path_data[i] == "." and "." in path_data[start:i]:
                    break  # second decimal point: start of next number
                i += 1
            if i < n and path_data[i] in "eE":
                i += 1
                if i < n and path_data[i] in ("-", "+"):
                    i += 1
                while i < n and path_data[i].isdigit():
                    i += 1
            num_str = path_data[start:i]
            if num_str and num_str not in (".", "-", "+", "+.", "-."):
                tokens.append(float(num_str))
        else:
            i += 1
    return tokens


def _consume_nums(tokens: list, idx: int, count: int) -> tuple:
    """Consume up to *count* consecutive numbers from *idx*.

    Returns (list_of_numbers, new_index) or (None, idx) on failure.
    """
    args = []
    i = idx
    while len(args) < count and i < len(tokens):
        if isinstance(tokens[i], (int, float)):
            args.append(tokens[i])
            i += 1
        else:
            break
    if len(args) < count:
        return None, idx
    return args, i


def parse_svg_path(path_data: str) -> QPainterPath:
    """Parse SVG path *d* attribute into a ``QPainterPath``.

    Supports absolute and relative commands: M, L, H, V, C, S, Q, T, A, Z.
    """
    result = QPainterPath()
    if not path_data or not path_data.strip():
        return result

    tokens = _tokenize_path(path_data)
    if not tokens:
        return result

    cmd = None
    cp = QPointF(0.0, 0.0)
    start = QPointF(0.0, 0.0)
    prev_ctrl: Optional[QPointF] = None
    i = 0

    while i < len(tokens):
        token = tokens[i]
        if isinstance(token, str):
            cmd = token
            i += 1
        else:
            if cmd is None:
                break

        upper = cmd.upper()
        is_rel = cmd.islower()
        rel = 1.0 if is_rel else 0.0

        if upper == "M":
            r = _consume_nums(tokens, i, 2)
            if r[0] is None:
                break
            args, i = r
            x = cp.x() + args[0] * rel if is_rel else args[0]
            y = cp.y() + args[1] * rel if is_rel else args[1]
            if result.elementCount() == 0:
                result.moveTo(x, y)
            else:
                result.lineTo(x, y)
            cp = QPointF(x, y)
            start = cp
            prev_ctrl = None
            cmd = "l" if is_rel else "L"

        elif upper == "L":
            r = _consume_nums(tokens, i, 2)
            if r[0] is None:
                break
            args, i = r
            x = cp.x() + args[0] * rel if is_rel else args[0]
            y = cp.y() + args[1] * rel if is_rel else args[1]
            result.lineTo(x, y)
            cp = QPointF(x, y)
            prev_ctrl = None

        elif upper == "H":
            r = _consume_nums(tokens, i, 1)
            if r[0] is None:
                break
            args, i = r
            x = cp.x() + args[0] * rel if is_rel else args[0]
            result.lineTo(x, cp.y())
            cp.setX(x)
            prev_ctrl = None

        elif upper == "V":
            r = _consume_nums(tokens, i, 1)
            if r[0] is None:
                break
            args, i = r
            y = cp.y() + args[0] * rel if is_rel else args[0]
            result.lineTo(cp.x(), y)
            cp.setY(y)
            prev_ctrl = None

        elif upper == "C":
            r = _consume_nums(tokens, i, 6)
            if r[0] is None:
                break
            args, i = r
            x1 = cp.x() + args[0] * rel if is_rel else args[0]
            y1 = cp.y() + args[1] * rel if is_rel else args[1]
            x2 = cp.x() + args[2] * rel if is_rel else args[2]
            y2 = cp.y() + args[3] * rel if is_rel else args[3]
            x = cp.x() + args[4] * rel if is_rel else args[4]
            y = cp.y() + args[5] * rel if is_rel else args[5]
            result.cubicTo(x1, y1, x2, y2, x, y)
            cp = QPointF(x, y)
            prev_ctrl = QPointF(x2, y2)

        elif upper == "S":
            r = _consume_nums(tokens, i, 4)
            if r[0] is None:
                break
            args, i = r
            if prev_ctrl is not None:
                x1 = cp.x() + (cp.x() - prev_ctrl.x())
                y1 = cp.y() + (cp.y() - prev_ctrl.y())
            else:
                x1, y1 = cp.x(), cp.y()
            x2 = cp.x() + args[0] * rel if is_rel else args[0]
            y2 = cp.y() + args[1] * rel if is_rel else args[1]
            x = cp.x() + args[2] * rel if is_rel else args[2]
            y = cp.y() + args[3] * rel if is_rel else args[3]
            result.cubicTo(x1, y1, x2, y2, x, y)
            cp = QPointF(x, y)
            prev_ctrl = QPointF(x2, y2)

        elif upper == "Q":
            r = _consume_nums(tokens, i, 4)
            if r[0] is None:
                break
            args, i = r
            x1 = cp.x() + args[0] * rel if is_rel else args[0]
            y1 = cp.y() + args[1] * rel if is_rel else args[1]
            x = cp.x() + args[2] * rel if is_rel else args[2]
            y = cp.y() + args[3] * rel if is_rel else args[3]
            result.quadTo(x1, y1, x, y)
            cp = QPointF(x, y)
            prev_ctrl = QPointF(x1, y1)

        elif upper == "T":
            r = _consume_nums(tokens, i, 2)
            if r[0] is None:
                break
            args, i = r
            if prev_ctrl is not None:
                x1 = cp.x() + (cp.x() - prev_ctrl.x())
                y1 = cp.y() + (cp.y() - prev_ctrl.y())
            else:
                x1, y1 = cp.x(), cp.y()
            x = cp.x() + args[0] * rel if is_rel else args[0]
            y = cp.y() + args[1] * rel if is_rel else args[1]
            result.quadTo(x1, y1, x, y)
            cp = QPointF(x, y)
            prev_ctrl = QPointF(x1, y1)

        elif upper == "A":
            r = _consume_nums(tokens, i, 7)
            if r[0] is None:
                break
            args, i = r
            x = cp.x() + args[5] * rel if is_rel else args[5]
            y = cp.y() + args[6] * rel if is_rel else args[6]
            # Approximate arc with line segment
            result.lineTo(x, y)
            cp = QPointF(x, y)
            prev_ctrl = None

        elif upper == "Z":
            result.closeSubpath()
            cp = QPointF(start)
            prev_ctrl = None

        else:
            i += 1

    return result


def _render_svg_icon(
    painter: QPainter,
    path: QPainterPath,
    rect: QRectF,
    color: QColor,
) -> None:
    """Scale and center *path* inside *rect*, filled with *color*."""
    bbox = path.boundingRect()
    if bbox.isEmpty():
        return
    scale = min(rect.width() / bbox.width(), rect.height() / bbox.height()) * 0.85
    if scale <= 0:
        return
    painter.save()
    painter.translate(rect.center())
    painter.scale(scale, scale)
    painter.translate(-bbox.center())
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)
    painter.restore()


# ── Breadcrumb Link (individual clickable item) ───────────────


class BreadcrumbLink(QWidget):
    """A single clickable breadcrumb item (icon + text)."""

    clicked = Signal(int)

    def __init__(
        self,
        text: str,
        index: int,
        icon_path: Optional[str] = None,
        size: str = "default",
        active: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._index = index
        self._icon_path_str = icon_path
        self._size = size
        self._active = active
        self._hovered = False

        # Parse icon path once
        self._icon_path: Optional[QPainterPath] = None
        if icon_path:
            self._icon_path = parse_svg_path(icon_path)

        cfg = self._cfg()
        self._pad_v = cfg["pad_v"]
        self._pad_h = cfg["pad_h"]
        self._font_size = cfg["font"]

        self.setCursor(Qt.ArrowCursor if active else Qt.PointingHandCursor)
        self._update_size_hint()

    @property
    def _text_primary(self): return tm.text

    @property
    def _text_secondary(self): return tm.mid

    @property
    def _hover_bg(self): return tm.alpha_of(tm.surface, 90)

    @property
    def _icon_color(self): return tm.alpha_of(tm.mid, 60)

    def _cfg(self) -> dict:
        return SIZE_CONFIG.get(self._size, SIZE_CONFIG["default"])

    def _make_font(self) -> QFont:
        f = QFont("Segoe UI", self._font_size)
        f.setBold(self._active)
        return f

    def _update_size_hint(self) -> None:
        fm = QFontMetrics(self._make_font())
        text_w = fm.horizontalAdvance(self._text)
        icon_w = (ICON_SIZE + ICON_TEXT_GAP) if self._icon_path is not None else 0
        w = self._pad_h + icon_w + text_w + self._pad_h
        h = max(fm.height(), ICON_SIZE) + self._pad_v * 2
        self.setMinimumSize(w, h)

    @property
    def active(self) -> bool:
        return self._active

    @active.setter
    def active(self, value: bool) -> None:
        if value == self._active:
            return
        self._active = value
        self.setCursor(Qt.ArrowCursor if value else Qt.PointingHandCursor)
        self._update_size_hint()
        self.update()

    # ── Events ─────────────────────────────────────────────────

    def enterEvent(self, event) -> None:
        if not self._active:
            self._hovered = True
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and not self._active:
            self.clicked.emit(self._index)
            event.accept()
        else:
            super().mousePressEvent(event)

    # ── Paint ──────────────────────────────────────────────────

    def paintEvent(self, _event: QPaintEvent) -> None:
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)

            w = self.width()
            h = self.height()
            x = self._pad_h

            # Hover background
            if self._hovered and not self._active:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._hover_bg)
                painter.drawRoundedRect(self.rect(), RADIUS, RADIUS)

            # Icon
            icon_color = self._icon_color
            if self._icon_path is not None:
                icon_rect = QRectF(
                    float(x),
                    (h - ICON_SIZE) / 2.0,
                    float(ICON_SIZE),
                    float(ICON_SIZE),
                )
                _render_svg_icon(painter, self._icon_path, icon_rect, icon_color)
                x += ICON_SIZE + ICON_TEXT_GAP

            # Text
            font = self._make_font()
            fm = QFontMetrics(font)
            painter.setFont(font)

            text_color = self._text_primary if self._active else (
                self._text_primary if self._hovered else self._text_secondary
            )
            painter.setPen(text_color)

            text_y = (h - fm.height()) / 2 + fm.ascent()
            painter.drawText(int(x), int(text_y), self._text)


# ── Breadcrumb Container ──────────────────────────────────────


class StyledBreadcrumb(QWidget):
    """Horizontal breadcrumb navigation.

    Features:
        - ``add_item(text, callback=None, icon=None)`` to append items
        - Auto-inserts separator (chevron ``>`` or colon ``:``) between items
        - Last item is styled as the *active* (current) page
        - ``background=True`` applies a container background + border
        - Hover effect on non-active links
        - ``navigated(index, text)`` signal on click
    """

    navigated = Signal(int, str)

    def __init__(
        self,
        size: str = "default",
        separator: str = ">",
        background: bool = False,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._sep_type = separator
        self._background = background

        self._items: list[dict] = []         # {text, callback, icon}
        self._link_widgets: list[BreadcrumbLink] = []
        self._sep_labels: list[QLabel] = []

        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._apply_layout_margins()

        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)

    # ── Public API ─────────────────────────────────────────────

    def add_item(
        self,
        text: str,
        callback: Optional[Callable[[], None]] = None,
        icon: Optional[str] = None,
    ) -> None:
        """Append a breadcrumb item.

        Args:
            text: Display label.
            callback: Optional callable invoked on click.
            icon: Optional SVG path data string for a 14×14 icon.
        """
        self._items.append({"text": text, "callback": callback, "icon": icon})
        self._rebuild()

    def clear(self) -> None:
        """Remove all items."""
        self._items.clear()
        self._rebuild()

    def set_items(self, items: list[dict]) -> None:
        """Replace all items at once.

        Each dict must have ``text`` and may have ``callback`` / ``icon`` keys.
        """
        self._items = list(items)
        self._rebuild()

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str) -> None:
        if value not in SIZE_CONFIG:
            return
        self._size = value
        for link in self._link_widgets:
            link._size = value
            link._cfg = link._cfg  # refresh
            cfg = SIZE_CONFIG[value]
            link._pad_v = cfg["pad_v"]
            link._pad_h = cfg["pad_h"]
            link._font_size = cfg["font"]
            link._update_size_hint()
        self._rebuild_sep_font()

    def set_background(self, value: bool) -> None:
        """Enable or disable the background container style."""
        if value == self._background:
            return
        self._background = value
        self._apply_layout_margins()
        self.update()

    # ── Internals ──────────────────────────────────────────────

    @property
    def _border_color(self): return tm.alpha_of(tm.mid, 40)

    @property
    def _bg_container(self): return tm.alpha_of(tm.surface, 90)

    @property
    def _tertiary_color(self): return tm.alpha_of(tm.mid, 60)

    def _apply_layout_margins(self) -> None:
        if self._background:
            self._layout.setContentsMargins(14, 8, 14, 8)
        else:
            self._layout.setContentsMargins(0, 0, 0, 0)

    def _rebuild_sep_font(self) -> None:
        sep_size = SIZE_CONFIG[self._size]["sep_font"]
        tertiary = self._tertiary_color.name()
        for sep in self._sep_labels:
            sep.setStyleSheet(
                f"color: {tertiary}; font-size: {sep_size}px; padding: 0 4px;"
            )

    def _rebuild(self) -> None:
        # Disconnect old signals
        for link in self._link_widgets:
            try:
                link.clicked.disconnect()
            except RuntimeError:
                pass

        # Remove old widgets
        for w in self._link_widgets:
            self._layout.removeWidget(w)
            w.deleteLater()
        for s in self._sep_labels:
            self._layout.removeWidget(s)
            s.deleteLater()
        self._link_widgets.clear()
        self._sep_labels.clear()

        # Rebuild
        count = len(self._items)
        sep_size = SIZE_CONFIG[self._size]["sep_font"]

        tertiary = self._tertiary_color.name()
        for idx, item in enumerate(self._items):
            is_active = idx == count - 1
            link = BreadcrumbLink(
                text=item["text"],
                index=idx,
                icon_path=item.get("icon"),
                size=self._size,
                active=is_active,
                parent=self,
            )
            link.clicked.connect(self._on_link_clicked)
            self._link_widgets.append(link)
            self._layout.addWidget(link)

            # Separator (not after the last item)
            if not is_active:
                sep = QLabel(self._sep_type)
                sep.setStyleSheet(
                    f"color: {tertiary}; font-size: {sep_size}px; padding: 0 4px;"
                )
                sep.setFixedHeight(ICON_SIZE)
                self._sep_labels.append(sep)
                self._layout.addWidget(sep)

        self._layout.addStretch()
        self.update()

    def _on_link_clicked(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            return
        item = self._items[index]
        text = item["text"]
        cb = item.get("callback")
        if cb is not None:
            cb()
        self.navigated.emit(index, text)

    # ── Paint (background variant) ─────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._background:
            with QPainter(self) as painter:
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(self._border_color, 1))
                painter.setBrush(self._bg_container)
                painter.drawRoundedRect(
                    QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                    6,
                    6,
                )
        super().paintEvent(event)
