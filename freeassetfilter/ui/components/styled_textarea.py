"""Styled Textarea component - wraps QPlainTextEdit with label, counter, and description.

Matches the web textarea component exactly (see components/textarea/textarea.css).

Features:
    - Optional label above textarea
    - Character counter with max_length support (e.g. "0/500")
    - Description text below
    - Error state (red border, red description)
    - Disabled state (greyed out)
    - Custom placeholder text
    - Size variants: sm, default, lg
    - text_changed(text: str) signal
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QPlainTextEdit,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import (
    QFont,
    QPainter,
    QColor,
    QPainterPath,
)
from theme import tm


class _StyledTextEdit(QPlainTextEdit):
    """Internal QPlainTextEdit subclass with size/error/hover/focus tracking.

    Styling (padding, font_size, radius) is synced 1:1 with StyledLineEdit's
    SIZE_CONFIG.

    Background is drawn entirely in paintEvent (not QSS) so it reliably fills
    both the frame and viewport area. The viewport has autoFillBackground
    disabled — only text/cursor are rendered on top of our painted background.
    Hover and focus states are tracked via event overrides.
    """

    SIZE_CONFIG = {
        "sm": {"padding_h": 10, "padding_v": 6, "font_size": 12, "radius": 6, "min_height": 60},
        "default": {"padding_h": 12, "padding_v": 8, "font_size": 13, "radius": 6, "min_height": 100},
        "lg": {"padding_h": 16, "padding_v": 12, "font_size": 15, "radius": 6, "min_height": 140},
    }

    def __init__(self, size: str, error: bool = False, parent=None):
        super().__init__(parent)
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._error = error
        self._hovered = False
        self._focused = False
        self._obj_name = f"_StyledTextEdit_{id(self)}"
        self.setObjectName(self._obj_name)
        self.setAttribute(Qt.WA_Hover, True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setTabChangesFocus(True)
        # Make viewport transparent => our paintEvent background shows through
        self.viewport().setAutoFillBackground(False)
        self._apply_size()
        self._apply_stylesheet()

    # ---- background color ----

    def _bg_color(self) -> QColor:
        """Return the current background color based on state."""
        if not self.isEnabled():
            return tm.alpha_of(tm.mid, 30)
        if self._hovered or self._focused:
            return tm.alpha_of(tm.mid, 50)
        return tm.alpha_of(tm.mid, 40)

    # ---- layout helpers ----

    def _apply_size(self):
        """Apply font and minimum height from current config."""
        config = self.SIZE_CONFIG[self._size]
        font = QFont("Microsoft YaHei UI", config["font_size"])
        self.setFont(font)
        self.setMinimumHeight(config["min_height"])

    def _apply_stylesheet(self):
        """Regenerate the stylesheet from current config and error state.

        Only border, color, selection — background is handled by paintEvent.
        """
        config = self.SIZE_CONFIG[self._size]
        border_color = tm.danger.name() if self._error else tm.alpha_of(tm.mid, 50).name()
        focus_border = tm.danger.name() if self._error else tm.accent.name()

        self.setStyleSheet(f"""
            #{self._obj_name} {{
                background: transparent;
                color: {tm.text.name()};
                border: 1px solid {border_color};
                border-radius: {config["radius"]}px;
                padding: {config["padding_v"]}px {config["padding_h"]}px;
                font-size: {config["font_size"]}px;
                selection-background-color: {tm.accent.name()};
                selection-color: {tm.text.name()};
            }}
            #{self._obj_name}:focus {{
                border-color: {focus_border};
            }}
            #{self._obj_name}:disabled {{
                background: transparent;
                color: {tm.alpha_of(tm.mid, 40).name()};
                border-color: {tm.alpha_of(tm.mid, 20).name()};
            }}
        """)

    # ---- paint ----

    def paintEvent(self, event):
        """Draw background rounded rect, then let QPlainTextEdit render text."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        config = self.SIZE_CONFIG[self._size]
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), config["radius"], config["radius"])
        painter.fillPath(path, self._bg_color())
        painter.end()
        super().paintEvent(event)

    # ---- event tracking ----

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._focused = True
        self._apply_stylesheet()  # update border to focus color
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._focused = False
        self._apply_stylesheet()  # restore border
        self.update()
        super().focusOutEvent(event)

    # ---- properties ----

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        self._apply_size()
        self._apply_stylesheet()

    @property
    def error(self) -> bool:
        return self._error

    @error.setter
    def error(self, value: bool):
        self._error = value
        self._apply_stylesheet()


class StyledTextarea(QWidget):
    """A styled textarea wrapping QPlainTextEdit with label, counter, and description.

    Signals:
        text_changed(text: str): Emitted whenever the text content changes,
            passing the current text value.
    """

    text_changed = Signal(str)

    def __init__(
        self,
        text: str = "",
        placeholder: str = "",
        label: str = "",
        description: str = "",
        max_length: Optional[int] = None,
        size: str = "default",
        error: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._error = error
        self._max_length = max_length

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # --- Label ---
        self._label = QLabel(label)
        self._label.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {tm.text.name()};"
        )
        self._label.setVisible(bool(label))
        layout.addWidget(self._label)

        # --- Text edit ---
        self._text_edit = _StyledTextEdit(size, error, self)
        self._text_edit.setPlaceholderText(placeholder)
        if text:
            self._text_edit.setPlainText(text)
        self._text_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._text_edit, stretch=1)

        # --- Bottom row: description (left) | counter (right) ---
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)

        # Description
        self._description_label = QLabel(description)
        self._description_label.setStyleSheet(self._description_style())
        self._description_label.setVisible(bool(description))
        bottom_row.addWidget(self._description_label)

        bottom_row.addStretch()

        # Counter
        initial_count = f"{len(text)}/{max_length}" if max_length is not None else ""
        self._counter_label = QLabel(initial_count)
        self._counter_label.setStyleSheet(
            f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};"
        )
        self._counter_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._counter_label.setVisible(max_length is not None)
        bottom_row.addWidget(self._counter_label)

        layout.addLayout(bottom_row)

    # ---- helpers ----

    def _description_style(self) -> str:
        color = tm.danger.name() if self._error else tm.alpha_of(tm.mid, 60).name()
        return f"font-size: 12px; color: {color};"

    def _on_text_changed(self):
        """Called when QPlainTextEdit text changes - emits text_changed signal."""
        text = self._text_edit.toPlainText()

        # Truncate if exceeds max_length
        if self._max_length is not None and len(text) > self._max_length:
            cursor = self._text_edit.textCursor()
            pos = cursor.position()
            self._text_edit.blockSignals(True)
            truncated = text[:self._max_length]
            self._text_edit.setPlainText(truncated)
            # Restore cursor position as close as possible
            new_pos = min(pos, self._max_length)
            cursor = self._text_edit.textCursor()
            cursor.setPosition(new_pos)
            self._text_edit.setTextCursor(cursor)
            self._text_edit.blockSignals(False)
            text = truncated

        # Update counter
        if self._max_length is not None:
            self._counter_label.setText(f"{len(text)}/{self._max_length}")

        self.text_changed.emit(text)

    # ---- properties ----

    @property
    def text(self) -> str:
        """Current text content."""
        return self._text_edit.toPlainText()

    @text.setter
    def text(self, value: str):
        self._text_edit.setPlainText(value)

    @property
    def placeholder(self) -> str:
        """Placeholder text shown when empty."""
        return self._text_edit.placeholderText()

    @placeholder.setter
    def placeholder(self, value: str):
        self._text_edit.setPlaceholderText(value)

    @property
    def label(self) -> str:
        """Label text above the textarea."""
        return self._label.text()

    @label.setter
    def label(self, value: str):
        self._label.setText(value)
        self._label.setVisible(bool(value))

    @property
    def description(self) -> str:
        """Description text below the textarea."""
        return self._description_label.text()

    @description.setter
    def description(self, value: str):
        self._description_label.setText(value)
        self._description_label.setVisible(bool(value))

    @property
    def max_length(self) -> Optional[int]:
        """Maximum allowed character count (None = unlimited)."""
        return self._max_length

    @max_length.setter
    def max_length(self, value: Optional[int]):
        self._max_length = value
        if value is not None:
            self._counter_label.setText(f"{len(self.text)}/{value}")
            self._counter_label.setVisible(True)
        else:
            self._counter_label.setText("")
            self._counter_label.setVisible(False)

    @property
    def size_variant(self) -> str:
        """Size variant: 'sm', 'default', or 'lg'."""
        return self._text_edit.size_variant

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in _StyledTextEdit.SIZE_CONFIG:
            return
        self._text_edit.size_variant = value

    @property
    def error(self) -> bool:
        """Error state (red border + red description text)."""
        return self._error

    @error.setter
    def error(self, value: bool):
        self._error = value
        self._text_edit.error = value
        self._description_label.setStyleSheet(self._description_style())
