# allow: SIZE_OK — grouped module: 4 tightly coupled notification classes
# (NotificationItem, _CountBadge, _EmptyStateWidget, NotificationBadgeList)
# that share layout constants and are always imported together.

"""Styled NotificationBadge component — matches web notification badge exactly.

Provides:
  - NotificationItem: single notification row with icon, content, unread dot
  - NotificationBadgeList: popover container with header, items, footer
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QLabel, QPushButton, QStackedWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QRectF, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QFontMetrics, QPen

from components.icon_utils import render_icon
from theme import tm


# ═════════════════════════════════════════════════════════════════════
#  Design tokens
# ═════════════════════════════════════════════════════════════════════

# COUNT_BG removed — use tm.alpha_of(tm.danger, 15) inline


# ═════════════════════════════════════════════════════════════════════
#  NotificationItem
# ═════════════════════════════════════════════════════════════════════

class NotificationItem(QWidget):
    """A single notification row with icon column, unread dot, and text content.

    Fully custom-painted for precise alignment and pulse animation on the
    unread dot.  Emits ``clicked(index)`` when clicked.
    """

    clicked = Signal(int)

    # Layout constants (match CSS: padding 12px 16px, gap 12px, icon 36px)
    PADDING_H = 16
    PADDING_V = 12
    ICON_SIZE = 36
    DOT_SIZE = 8
    GAP = 12
    ITEM_HEIGHT = 76

    # ── Theme helpers ────────────────────────────────────────────

    @staticmethod
    def _icon_colors() -> dict[str, QColor]:
        return {
            "success": tm.accent,
            "warning": tm.warning,
            "error": tm.danger,
            "info": tm.info,
        }

    @property
    def _hover_bg(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    @property
    def _unread_dot(self) -> QColor:
        return tm.accent

    @property
    def _text_primary(self) -> QColor:
        return tm.text

    @property
    def _text_secondary(self) -> QColor:
        return tm.mid

    @property
    def _text_tertiary(self) -> QColor:
        return tm.alpha_of(tm.mid, 60)

    def __init__(
        self,
        icon_name: str,
        title: str,
        description: str,
        time_str: str,
        color_variant: str = "info",
        unread: bool = False,
        index: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self._icon_name = icon_name
        self._title = title
        self._description = description
        self._time_str = time_str
        self._color_variant = color_variant if color_variant in self._icon_colors() else "info"
        self._unread = unread
        self._index = index
        self._hovered = False
        self._pulse_opacity = 1.0

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedHeight(self.ITEM_HEIGHT)

        # Pulse animation: 1 → 0.5 → 1 over 2s, infinite loop
        self._pulse_anim = QPropertyAnimation(self, b"pulse_opacity")
        self._pulse_anim.setDuration(2000)
        self._pulse_anim.setStartValue(1.0)
        self._pulse_anim.setKeyValueAt(0.5, 0.5)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.SineCurve)

        if self._unread:
            self._pulse_anim.start()

    # ── Qt property for animation ─────────────────────────────────

    @Property(float)
    def pulse_opacity(self) -> float:
        return self._pulse_opacity

    @pulse_opacity.setter
    def pulse_opacity(self, value: float):
        self._pulse_opacity = value
        self.update()

    # ── Events ─────────────────────────────────────────────────────

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._index)
            event.accept()
        else:
            super().mousePressEvent(event)

    # ── Paint ─────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()

        # ── Hover background ──
        if self._hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._hover_bg)
            painter.drawRoundedRect(QRectF(0, 0, w, h), 0, 0)

        color = self._icon_colors()[self._color_variant]

        # ── Icon column (36×36 rounded rect at 20% opacity) ──
        icon_x = self.PADDING_H
        icon_y = (h - self.ICON_SIZE) / 2.0
        icon_rect = QRectF(icon_x, icon_y, self.ICON_SIZE, self.ICON_SIZE)

        bg_color = QColor(color)
        bg_color.setAlpha(int(255 * 0.2))
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(icon_rect, 6, 6)

        # Icon (18×18 viewBox centered in 36×36)
        render_icon(
            painter, self._icon_name,
            icon_rect.adjusted(9, 9, -9, -9),
            color, pen_width=1.8,
        )

        # ── Content area start ──
        content_x = icon_x + self.ICON_SIZE + self.GAP

        # ── Unread dot (8×8 green circle, pulse-animated) ──
        if self._unread:
            dot_x = content_x
            dot_y = self.PADDING_V + 6   # margin-top: 6px from CSS
            dot_rect = QRectF(dot_x, dot_y, self.DOT_SIZE, self.DOT_SIZE)
            painter.setOpacity(self._pulse_opacity)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._unread_dot)
            painter.drawEllipse(dot_rect)
            painter.setOpacity(1.0)
            content_x = dot_x + self.DOT_SIZE + self.GAP

        # ── Text content area ──
        content_w = w - content_x - self.PADDING_H
        if content_w < 10:
            content_w = 10

        # Title (13px, Medium weight)
        title_font = QFont("Microsoft YaHei UI", 13, QFont.Weight.Medium)
        painter.setFont(title_font)
        painter.setPen(self._text_primary)
        title_rect = QRectF(content_x, self.PADDING_V, content_w, 21)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignTop, self._title)

        # Description (12px, single-line ellipsis)
        desc_font = QFont("Microsoft YaHei UI", 12, QFont.Weight.Normal)
        painter.setFont(desc_font)
        painter.setPen(self._text_secondary)
        desc_rect = QRectF(content_x, self.PADDING_V + 22, content_w, 18)
        desc_elided = painter.fontMetrics().elidedText(
            self._description, Qt.ElideRight, int(content_w),
        )
        painter.drawText(desc_rect, Qt.AlignLeft | Qt.AlignTop, desc_elided)

        # Time (11px, tertiary)
        time_font = QFont("Microsoft YaHei UI", 11, QFont.Weight.Normal)
        painter.setFont(time_font)
        painter.setPen(self._text_tertiary)
        painter.drawText(
            QRectF(content_x, self.PADDING_V + 42, content_w, 16),
            Qt.AlignLeft | Qt.AlignTop,
            self._time_str,
        )

    # ── Properties ────────────────────────────────────────────────

    @property
    def item_index(self) -> int:
        return self._index

    @item_index.setter
    def item_index(self, value: int):
        self._index = value

    @property
    def is_unread(self) -> bool:
        return self._unread

    @is_unread.setter
    def is_unread(self, value: bool):
        if value == self._unread:
            return
        self._unread = value
        if value:
            self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse_opacity = 1.0
        self.update()


# ═════════════════════════════════════════════════════════════════════
#  Internal widgets
# ═════════════════════════════════════════════════════════════════════

class _CountBadge(QWidget):
    """Small pill badge showing the unread notification count.

    Styled as: ``rgba(239,68,68,0.15)`` background with ``#ef4444`` text,
    12px font, fully rounded (pill shape).
    """

    @property
    def _count_text(self) -> QColor:
        return tm.danger

    def __init__(self, count: int = 0, parent=None):
        super().__init__(parent)
        self._count = count
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_count(self, count: int):
        self._count = count
        self.update()
        self._adjust_size()

    def _adjust_size(self):
        fm = QFontMetrics(QFont("Microsoft YaHei UI", 12, QFont.Weight.Medium))
        text_w = fm.horizontalAdvance(str(self._count)) if self._count > 0 else 0
        w = max(text_w + 16, 24)
        self.setFixedSize(int(w), 22)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        radius = h / 2.0

        # Pill background
        painter.setPen(Qt.NoPen)
        painter.setBrush(tm.alpha_of(tm.danger, 15))
        painter.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)

        # Count text
        if self._count > 0:
            painter.setPen(self._count_text)
            font = QFont("Microsoft YaHei UI", 12, QFont.Weight.Medium)
            painter.setFont(font)
            painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, str(self._count))


class _EmptyStateWidget(QWidget):
    """Empty state shown when there are no notifications.

    Renders a bell icon at 40% opacity and ``暂无通知`` text below.
    """

    @property
    def _text_secondary(self) -> QColor:
        return tm.mid

    @property
    def _text_tertiary(self) -> QColor:
        return tm.alpha_of(tm.mid, 60)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()

        # Bell icon centred, 48×48
        icon_size = 48.0
        icon_rect = QRectF(
            (w - icon_size) / 2.0, (h - icon_size) / 2.0 - 16,
            icon_size, icon_size,
        )
        painter.setOpacity(0.4)
        render_icon(painter, "bell", icon_rect, self._text_secondary, pen_width=2.0)
        painter.setOpacity(1.0)

        # "暂无通知" text below icon
        font = QFont("Microsoft YaHei UI", 13, QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(self._text_tertiary)
        painter.drawText(
            QRectF(0, icon_rect.bottom() + 12, w, 24),
            Qt.AlignCenter,
            "暂无通知",
        )


# ═════════════════════════════════════════════════════════════════════
#  NotificationBadgeList
# ═════════════════════════════════════════════════════════════════════

class NotificationBadgeList(QWidget):
    """A notification popover matching the web component.

    Structure::

        ┌─ Header (title "通知" + count badge) ─┐
        ├─ Items (scrollable) ──────────────────┤
        │   [item 1]                            │
        │   [item 2]                            │
        │   [item 3]                            │
        ├─ Footer ("查看全部" link) ───────────┤
        └────────────────────────────────────────┘

    Signals
    -------
    item_clicked(index: int)
        Emitted when a notification item is clicked.
    view_all_clicked
        Emitted when the footer "查看全部" button is clicked.
    """

    item_clicked = Signal(int)
    view_all_clicked = Signal()

    WIDTH = 320
    MAX_HEIGHT = 400

    @property
    def _bg_color(self) -> QColor:
        return tm.surface

    @property
    def _border_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    @property
    def _divider_color(self) -> QColor:
        return tm.alpha_of(tm.mid, 30)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setMaximumHeight(self.MAX_HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Outer background border (painted via paintEvent)
        self.setStyleSheet("background: transparent;")

        # Header
        self._header = self._make_header()
        main_layout.addWidget(self._header)

        # Scrollable items area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 6px; background: transparent; }"
            f"QScrollBar::handle:vertical {{ background: {tm.alpha_of(tm.fill, 40).name()}; border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        # QStackedWidget: page 0 = empty state, page 1 = items
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        # Page 0: empty state
        self._empty_widget = _EmptyStateWidget()
        self._stack.addWidget(self._empty_widget)

        # Page 1: items container
        self._items_container = QWidget()
        self._items_container.setStyleSheet("background: transparent;")
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(0)
        self._items_layout.addStretch()  # keeps items top-aligned
        self._stack.addWidget(self._items_container)

        self._scroll.setWidget(self._stack)
        main_layout.addWidget(self._scroll, 1)

        # Footer
        self._footer = self._make_footer()
        main_layout.addWidget(self._footer)

        # Initial state
        self._update_state()

    def _make_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(44)
        header.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(8)

        title = QLabel("通知")
        title.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {tm.text.name()};"
            " background: transparent; border: none;"
        )
        layout.addWidget(title)

        self._count_badge = _CountBadge(0)
        layout.addWidget(self._count_badge)

        layout.addStretch()
        return header

    def _make_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(36)
        footer.setStyleSheet("background: transparent;")

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        btn = QPushButton("查看全部")
        btn.setCursor(Qt.PointingHandCursor)
        accent = tm.accent.name()
        hover_bg = tm.mid.name()
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {accent}; font-size: 12px;
                font-family: "Microsoft YaHei UI", sans-serif;
                padding: 4px 12px; border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
        """)
        btn.clicked.connect(self._on_view_all)
        layout.addWidget(btn)

        return footer

    # ── Paint (outer background + borders) ────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Rounded background (#2d2d2d)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._bg_color)
        painter.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # 1 px border (#3a3a3a)
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, w - 1, h - 1), 8, 8,
        )

        # Header divider line (bottom of header area)
        header_h = self._header.height() if self._header else 44
        painter.setPen(QPen(self._divider_color, 1))
        painter.drawLine(0, header_h, w, header_h)

        # Footer divider line (top of footer area)
        footer_h = self._footer.height() if self._footer else 36
        footer_y = h - footer_h
        painter.drawLine(0, footer_y, w, footer_y)

    # ── Public API ────────────────────────────────────────────────

    def add_item(self, item: NotificationItem):
        """Append a *NotificationItem* to the list."""
        item.clicked.connect(self._on_item_clicked)
        # Insert before the trailing stretch
        self._items_layout.insertWidget(self._items_layout.count() - 1, item)
        self._update_state()

    def insert_item(self, index: int, item: NotificationItem):
        """Insert a *NotificationItem* at *index* (0-based)."""
        item.clicked.connect(self._on_item_clicked)
        self._items_layout.insertWidget(index, item)
        self._update_state()

    def remove_item(self, item: NotificationItem):
        """Remove a specific *NotificationItem* from the list."""
        self._items_layout.removeWidget(item)
        item.deleteLater()
        self._update_state()

    def clear_items(self):
        """Remove all notification items."""
        while self._items_layout.count() > 1:  # keep the trailing stretch
            item = self._items_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._update_state()

    def item_count(self) -> int:
        """Return the number of notification items."""
        return max(0, self._items_layout.count() - 1)  # minus stretch

    def set_count(self, count: int):
        """Override the displayed count (e.g. from external data)."""
        self._count_badge.set_count(count)

    # ── Internal ──────────────────────────────────────────────────

    def _on_item_clicked(self, index: int):
        self.item_clicked.emit(index)

    def _on_view_all(self):
        self.view_all_clicked.emit()

    def _update_state(self):
        """Toggle between empty state and items list."""
        count = self.item_count()
        if count == 0:
            self._stack.setCurrentIndex(0)
            self._count_badge.set_count(0)
        else:
            self._stack.setCurrentIndex(1)
            self._count_badge.set_count(count)
