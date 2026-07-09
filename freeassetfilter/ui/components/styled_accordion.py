"""StyledAccordion component - collapsible sections matching web accordion.

Provides StyledAccordionItem (single collapsible section) and StyledAccordion
(container with single/multi-open modes, bordered variant).
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent, QFont, QFontMetrics, QMouseEvent

from theme import tm


class StyledAccordionItem(QWidget):
    """A single collapsible accordion section.

    The header (title + chevron) is painted via QPainter. Body content is
    wrapped in a container with QPropertyAnimation on maximumHeight.
    """

    toggled = Signal(bool)  # emitted when item opens (True) or closes (False)

    _HEADER_HEIGHT = 48  # 14px padding-top + 14px padding-bottom + ~20px font

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._open = False
        self._enabled = True
        self._hovered = False
        self._bordered = False

        # Layout: content wrapper sits below the painted header
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, self._HEADER_HEIGHT, 0, 0)
        self._layout.setSpacing(0)

        # Content wrapper that gets animated
        self._content_wrapper = QWidget(self)
        self._content_wrapper.setStyleSheet("background: transparent;")
        self._wrapper_layout = QVBoxLayout(self._content_wrapper)
        self._wrapper_layout.setContentsMargins(16, 0, 16, 14)
        self._wrapper_layout.setSpacing(0)
        self._content_wrapper.setMaximumHeight(0)
        self._content_wrapper.setVisible(False)
        self._layout.addWidget(self._content_wrapper)

        # Expand/collapse animation
        self._anim = QPropertyAnimation(self._content_wrapper, b"maximumHeight")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutQuad)
        self._anim.finished.connect(self._on_anim_finished)

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    @property
    def _text_primary(self): return tm.text

    @property
    def _text_tertiary(self): return tm.alpha_of(tm.mid, 60)

    @property
    def _divider_color(self): return tm.alpha_of(tm.mid, 30)

    @property
    def _bg_hover(self): return tm.alpha_of(tm.surface, 90)

    @property
    def _border_color(self): return tm.alpha_of(tm.mid, 40)

    def _on_anim_finished(self):
        if not self._open:
            self._content_wrapper.setVisible(False)
            self._content_wrapper.setMaximumHeight(0)

    def set_content_widget(self, widget: QWidget):
        """Set the content widget displayed when this item is expanded."""
        while self._wrapper_layout.count():
            item = self._wrapper_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._wrapper_layout.addWidget(widget)

    @property
    def is_open(self) -> bool:
        return self._open

    @is_open.setter
    def is_open(self, value: bool):
        if value == self._open:
            return
        self._open = value
        self._animate_toggle()
        self.toggled.emit(value)
        self.update()

    def set_open_no_anim(self, value: bool):
        """Set open state without animation (for initial setup)."""
        self._open = value
        if value:
            self._content_wrapper.setMaximumHeight(self._content_wrapper.sizeHint().height())
            self._content_wrapper.setVisible(True)
        else:
            self._content_wrapper.setMaximumHeight(0)
            self._content_wrapper.setVisible(False)
        self.update()

    def _animate_toggle(self):
        self._anim.stop()
        if self._open:
            self._content_wrapper.setVisible(True)
            self._content_wrapper.layout().invalidate()
            target = max(0, self._content_wrapper.sizeHint().height())
            self._anim.setStartValue(0)
            self._anim.setEndValue(target)
        else:
            start = max(0, self._content_wrapper.maximumHeight())
            self._anim.setStartValue(start)
            self._anim.setEndValue(0)
        self._anim.start()

    def toggle(self):
        """Toggle open/closed state."""
        self._open = not self._open
        self._animate_toggle()
        self.toggled.emit(self._open)
        self.update()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        self.setCursor(Qt.PointingHandCursor if value else Qt.ForbiddenCursor)
        self.update()

    # ── Mouse events ────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._enabled:
            if event.position().y() <= self._HEADER_HEIGHT:
                self.toggle()
                event.accept()
                return
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ── Paint ───────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            w = self.width()
            h = self._HEADER_HEIGHT

            alpha = 128 if not self._enabled else 255

            # Hover background (only on header area)
            if self._hovered and self._enabled:
                painter.fillRect(0, 0, w, h, self._bg_hover)

            # Non-bordered: bottom border on header
            if not self._bordered:
                painter.setPen(QPen(self._divider_color, 1))
                painter.drawLine(0, h - 1, w, h - 1)

            # Title text
            font = QFont("Segoe UI", 13.5)
            font.setWeight(QFont.Weight(500))
            painter.setFont(font)
            fm = QFontMetrics(font)

            tp = self._text_primary
            painter.setPen(QColor(
                tp.red(), tp.green(), tp.blue(), alpha,
            ))
            text_rect = fm.boundingRect(self._title)
            text_y = (h - text_rect.height()) / 2 + fm.ascent()
            painter.drawText(16, int(text_y), self._title)

            # Chevron icon (right-aligned, 16px from right edge)
            chevron_size = 12
            chevron_x = w - 16 - chevron_size
            chevron_y = (h - chevron_size) / 2

            tt = self._text_tertiary
            painter.setPen(QPen(
                QColor(tt.red(), tt.green(), tt.blue(), alpha),
                2, Qt.SolidLine, Qt.RoundCap,
            ))

            cx = chevron_x + chevron_size / 2
            cy = chevron_y + chevron_size / 2
            half = chevron_size / 3

            if self._open:
                # v shape (pointing down) = > rotated 90deg CW
                painter.drawLine(QPointF(cx - half, cy - half), QPointF(cx, cy + half))
                painter.drawLine(QPointF(cx + half, cy - half), QPointF(cx, cy + half))
            else:
                # > shape (pointing right)
                painter.drawLine(QPointF(cx - half, cy - half), QPointF(cx + half, cy))
                painter.drawLine(QPointF(cx - half, cy + half), QPointF(cx + half, cy))

            # Bordered variant: draw full item border
            if self._bordered:
                painter.setPen(QPen(self._border_color, 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(0, 0, w - 1, self.height() - 1, 6, 6)


class StyledAccordion(QWidget):
    """Container widget for accordion sections with single/multi-open modes."""

    section_toggled = Signal(int, bool)  # index, open

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[StyledAccordionItem] = []
        self._accordion_mode = True  # single-open by default
        self._bordered = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add_item(
        self, title: str, content_widget: QWidget = None, disabled: bool = False,
    ) -> StyledAccordionItem:
        """Add an accordion item. Returns the item for further customization."""
        item = StyledAccordionItem(title)
        item._bordered = self._bordered
        if content_widget is not None:
            item.set_content_widget(content_widget)
        if disabled:
            item.enabled = False

        item.toggled.connect(lambda open, idx=len(self._items): self._on_item_toggled(idx, open))
        self._layout.addWidget(item)
        self._items.append(item)
        return item

    def _on_item_toggled(self, idx: int, open: bool):
        if open and self._accordion_mode:
            # Close all other items (block signals to avoid re-entrant emission)
            for i, item in enumerate(self._items):
                if i != idx and item.is_open:
                    item.blockSignals(True)
                    item.is_open = False
                    item.blockSignals(False)
        self.section_toggled.emit(idx, open)

    @property
    def accordion_mode(self) -> bool:
        return self._accordion_mode

    @accordion_mode.setter
    def accordion_mode(self, value: bool):
        self._accordion_mode = value

    @property
    def bordered(self) -> bool:
        return self._bordered

    @bordered.setter
    def bordered(self, value: bool):
        self._bordered = value
        for item in self._items:
            item._bordered = value
            item.update()
        self._layout.setSpacing(8 if value else 0)
