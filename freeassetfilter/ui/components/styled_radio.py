"""Styled Radio Button component - matches web radio exactly."""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal, Property, QRectF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent

from theme import tm


class StyledRadio(QWidget):
    """A radio button matching the web component exactly.

    Sizes (radio circle size):
        - sm: 14x14 (dot 6px)
        - default: 18x18 (dot 8px)
        - lg: 22x22 (dot 10px)

    Features:
        - checked / unchecked states
        - hover animation
        - press animation
        - optional label
        - disabled state
        - group_name for mutual exclusion
    """

    toggled = Signal(bool)

    SIZE_CONFIG = {
        "sm": {"circle": 14, "dot": 6, "border_width": 1.5, "label_font": 12},
        "default": {"circle": 18, "dot": 8, "border_width": 1.5, "label_font": 13},
        "lg": {"circle": 22, "dot": 10, "border_width": 1.5, "label_font": 14},
    }

    # Global registry for group mutual exclusion
    _groups: dict[str, list["StyledRadio"]] = {}

    def __init__(
        self,
        checked: bool = False,
        size: str = "default",
        enabled: bool = True,
        text: str = "",
        group_name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._checked = checked
        self._size = size
        self._enabled = enabled
        self._text = text
        self._group_name = group_name
        self._hovered = False
        self._pressed = False
        self._hover_progress = 0.0
        self._press_progress = 0.0
        self._dot_scale = 1.0 if checked else 0.0

        config = self._get_config()
        self._circle_size = config["circle"]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        self._radio_circle = _RadioCircleWidget(self)
        self._radio_circle.setFixedSize(self._circle_size + 4, self._circle_size + 4)
        layout.addWidget(self._radio_circle)

        if text:
            self._label = QLabel(text, self)
            self._label.setObjectName("radioLabel")
            font = self._label.font()
            font.setPixelSize(config["label_font"])
            self._label.setFont(font)
            self._label.setStyleSheet(f"color: {tm.text.name()};")
            self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(self._label)
        else:
            self._label = None

        layout.setAlignment(Qt.AlignVCenter)

        self.setCursor(Qt.PointingHandCursor)
        self._update_enabled_state()

        # Register to group
        if group_name:
            if group_name not in self._groups:
                self._groups[group_name] = []
            self._groups[group_name].append(self)

        # Hover animation
        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._hover_anim.setParent(self)

        # Press animation
        self._press_anim = QPropertyAnimation(self, b"press_progress")
        self._press_anim.setDuration(120)
        self._press_anim.setEasingCurve(QEasingCurve.OutBack)
        self._press_anim.setParent(self)

        # Dot scale animation
        self._dot_anim = QPropertyAnimation(self, b"dot_scale")
        self._dot_anim.setDuration(200)
        self._dot_anim.setEasingCurve(QEasingCurve.OutBack)
        self._dot_anim.setParent(self)

    def _get_config(self) -> dict:
        return self.SIZE_CONFIG.get(self._size, self.SIZE_CONFIG["default"])

    def _update_enabled_state(self):
        if not self._enabled:
            self.setCursor(Qt.ForbiddenCursor)
        else:
            self.setCursor(Qt.PointingHandCursor)

    # ── Qt properties for animation ──────────────────────────────

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, value: float):
        self._hover_progress = value
        self._radio_circle.update()

    @Property(float)
    def press_progress(self):
        return self._press_progress

    @press_progress.setter
    def press_progress(self, value: float):
        self._press_progress = value
        self._radio_circle.update()

    @Property(float)
    def dot_scale(self):
        return self._dot_scale

    @dot_scale.setter
    def dot_scale(self, value: float):
        self._dot_scale = value
        self._radio_circle.update()

    # ── Public API ───────────────────────────────────────────────

    @property
    def checked(self) -> bool:
        return self._checked

    @checked.setter
    def checked(self, value: bool):
        if value == self._checked:
            return
        self._checked = value
        target = 1.0 if value else 0.0

        # Use stored animation reference instead of creating new one
        self._dot_anim.stop()
        self._dot_anim.setStartValue(self._dot_scale)
        self._dot_anim.setEndValue(target)
        self._dot_anim.start()

        self._radio_circle.update()
        self.toggled.emit(value)

        # If checked and in a group, uncheck other radios in the same group
        if value and self._group_name:
            for radio in self._groups.get(self._group_name, []):
                if radio is not self and radio._checked:
                    radio._checked = False
                    radio._dot_scale = 0.0
                    radio._dot_anim.stop()
                    radio._dot_anim.setStartValue(radio._dot_scale)
                    radio._dot_anim.setEndValue(0.0)
                    radio._dot_anim.start()
                    radio._radio_circle.update()
                    radio.toggled.emit(False)

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        config = self.SIZE_CONFIG[value]
        self._circle_size = config["circle"]
        self._radio_circle.setFixedSize(self._circle_size, self._circle_size)
        if self._label:
            font = self._label.font()
            font.setPixelSize(config["label_font"])
            self._label.setFont(font)
        self._radio_circle.update()

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        if value:
            if not self._label:
                config = self._get_config()
                self._label = QLabel(value, self)
                self._label.setObjectName("radioLabel")
                font = self._label.font()
                font.setPixelSize(config["label_font"])
                self._label.setFont(font)
                self._label.setStyleSheet(f"color: {tm.text.name()};")
                self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
                self.layout().addWidget(self._label)
            else:
                self._label.setText(value)
        elif self._label:
            self._label.deleteLater()
            self._label = None

    @property
    def group_name(self) -> str:
        return self._group_name

    @group_name.setter
    def group_name(self, value: str):
        # Unregister from old group
        if self._group_name and self._group_name in self._groups:
            if self in self._groups[self._group_name]:
                self._groups[self._group_name].remove(self)
        self._group_name = value
        # Register to new group
        if value:
            if value not in self._groups:
                self._groups[value] = []
            self._groups[value].append(self)

    def toggle(self):
        if self._enabled and not self._checked:
            self.checked = True

    # ── Mouse / hover events ────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._enabled:
            self._pressed = True
            self._animate_press(1.0)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pressed and self._enabled:
            self.toggle()
            self._pressed = False
            self._animate_press(0.0)
            event.accept()
        else:
            self._pressed = False
            self._animate_press(0.0)
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        if self._enabled:
            self._hovered = True
            self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self._animate_hover(0.0)
        self._animate_press(0.0)
        super().leaveEvent(event)

    # ── Animation helpers ───────────────────────────────────────

    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        distance = abs(target - self._hover_progress)
        self._hover_anim.setDuration(max(50, int(180 * distance)))
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.setEasingCurve(
            QEasingCurve.OutBack if target > 0.5 else QEasingCurve.InCubic
        )
        self._hover_anim.start()

    def _animate_press(self, target: float):
        self._press_anim.stop()
        distance = abs(target - self._press_progress)
        self._press_anim.setDuration(max(40, int(120 * distance)))
        self._press_anim.setStartValue(self._press_progress)
        self._press_anim.setEndValue(target)
        self._press_anim.setEasingCurve(
            QEasingCurve.OutQuad if target > 0.5 else QEasingCurve.OutElastic
        )
        self._press_anim.start()

    def set_checked_no_signal(self, value: bool):
        """Set checked state without emitting signal."""
        self._checked = value
        self._dot_scale = 1.0 if value else 0.0
        self._radio_circle.update()

    def cleanup(self):
        """Remove from group registry. Call before deletion if needed."""
        if self._group_name and self._group_name in self._groups:
            if self in self._groups[self._group_name]:
                self._groups[self._group_name].remove(self)


class _RadioCircleWidget(QWidget):
    """Internal widget that paints the radio circle."""

    def __init__(self, parent: StyledRadio):
        super().__init__(parent)
        self._parent = parent
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, event: QPaintEvent):
        parent = self._parent
        config = parent._get_config()
        circle_size = config["circle"]
        dot_size = config["dot"]
        border_width = config["border_width"]

        # Determine colors
        if not parent._enabled:
            if parent._checked:
                border_color = tm.alpha_of(tm.accent, 39)
                dot_color = tm.alpha_of(tm.accent, 39)
            else:
                border_color = tm.alpha_of(tm.mid, 40)
                dot_color = tm.alpha_of(tm.mid, 40)
        else:
            _accent = tm.accent
            _border = tm.alpha_of(tm.mid, 40)
            border_color = _border
            dot_color = _accent

            # Hover: animate border toward accent
            if parent._hover_progress > 0:
                r = int(border_color.red() + (_accent.red() - border_color.red()) * parent._hover_progress)
                g = int(border_color.green() + (_accent.green() - border_color.green()) * parent._hover_progress)
                b = int(border_color.blue() + (_accent.blue() - border_color.blue()) * parent._hover_progress)
                border_color = QColor(r, g, b)

        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)

            # Center the drawing within the actual widget bounds
            offset_x = (self.width() - circle_size) / 2
            offset_y = (self.height() - circle_size) / 2
            painter.translate(offset_x, offset_y)

            # Draw outer circle
            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(
                QRectF(
                    border_width / 2,
                    border_width / 2,
                    circle_size - border_width,
                    circle_size - border_width,
                )
            )

            # Draw inner dot if checked
            if parent._checked:
                dot_diameter = dot_size * parent._dot_scale
                if dot_diameter > 0:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(dot_color)
                    dot_rect = QRectF(
                        (circle_size - dot_diameter) / 2,
                        (circle_size - dot_diameter) / 2,
                        dot_diameter,
                        dot_diameter,
                    )
                    painter.drawEllipse(dot_rect)
