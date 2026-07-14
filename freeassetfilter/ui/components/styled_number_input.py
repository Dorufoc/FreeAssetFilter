"""Styled Number Input component - matches web number-input exactly."""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLineEdit, QSizePolicy
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QSize
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QIntValidator, QFont, QPaintEvent
from theme import tm


class _NumberDisplay(QLineEdit):
    """QLineEdit whose width adapts to the rendered width of its text."""

    def __init__(self, h_padding: int = 12, parent=None):
        super().__init__(parent)
        self._h_padding = h_padding
        # 水平 Preferred: 不会主动扩展填充父容器，最小尺寸 = sizeHint
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def sizeHint(self):
        fm = self.fontMetrics()
        text = self.text() or "0"
        text_w = fm.horizontalAdvance(text)
        h = super().sizeHint().height()
        return QSize(text_w + self._h_padding * 2, h)

    def minimumSizeHint(self):
        return self.sizeHint()


class _NumberButton(QWidget):
    """A self-painted +/- button for the number input."""

    pressed = Signal()
    released = Signal()

    def __init__(self, symbol: str, position: str, parent=None):
        super().__init__(parent)
        self._symbol = symbol
        self._position = position  # "left" or "right"
        self._hovered = False
        self._pressed_state = False
        self._button_disabled = False
        self._update_cursor()

    def set_button_disabled(self, disabled: bool):
        self._button_disabled = disabled
        self._update_cursor()
        self.update()

    def _update_cursor(self):
        parent = self.parent()
        if self._button_disabled or (parent and not parent._enabled):
            self.setCursor(Qt.ForbiddenCursor)
        else:
            self.setCursor(Qt.PointingHandCursor)

    def _button_path(self, w: int, h: int, radius: int) -> QPainterPath:
        """Build a path with rounded corners only on the outer side of the button."""
        path = QPainterPath()
        if self._position == "left":
            # Rounded: top-left & bottom-left; square: top-right & bottom-right
            path.moveTo(radius, 0)
            path.lineTo(w, 0)
            path.lineTo(w, h)
            path.lineTo(radius, h)
            # Bottom-left rounded corner (from bottom side → left side)
            path.arcTo(0, h - 2 * radius, 2 * radius, 2 * radius, 90, 90)
            path.lineTo(0, radius)
            # Top-left rounded corner (from left side → top side)
            path.arcTo(0, 0, 2 * radius, 2 * radius, 180, 90)
        else:  # "right"
            # Rounded: top-right & bottom-right; square: top-left & bottom-left
            path.moveTo(0, 0)
            path.lineTo(w - radius, 0)
            # Top-right rounded corner (from top side → right side)
            path.arcTo(w - 2 * radius, 0, 2 * radius, 2 * radius, 270, 90)
            path.lineTo(w, h - radius)
            # Bottom-right rounded corner (from right side → bottom side)
            path.arcTo(w - 2 * radius, h - 2 * radius, 2 * radius, 2 * radius, 0, 90)
            path.lineTo(0, h)
        path.closeSubpath()
        return path

    def paintEvent(self, event: QPaintEvent):
        parent = self.parent()
        is_parent_disabled = parent._enabled is False if parent else False

        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()

            disabled = is_parent_disabled or self._button_disabled

            # 按钮始终透明背景，无hover/pressed效果
            arrow_color = tm.mid
            if disabled:
                painter.fillRect(self.rect(), QColor(Qt.transparent))
                color = QColor(arrow_color)
                color.setAlphaF(0.3)
                painter.setPen(QPen(color, 2))
            else:
                painter.fillRect(self.rect(), QColor(Qt.transparent))
                painter.setPen(QPen(arrow_color, 2))

            # Draw symbol centered
            icon_sz = 14
            if parent:
                config = parent._get_config()
                icon_sz = config["icon_size"]
            cx = w / 2
            cy = h / 2
            half = icon_sz / 2

            painter.drawLine(int(cx - half), int(cy), int(cx + half), int(cy))
            if self._symbol == "+":
                painter.drawLine(int(cx), int(cy - half), int(cx), int(cy + half))

    def mousePressEvent(self, event):
        parent = self.parent()
        if (
            event.button() == Qt.LeftButton
            and not self._button_disabled
            and parent
            and parent._enabled
        ):
            self._pressed_state = True
            self.update()
            self.pressed.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed_state = False
            self.update()
            self.released.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._update_cursor()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        was_pressed = self._pressed_state
        self._hovered = False
        self._pressed_state = False
        self.update()
        if was_pressed:
            self.released.emit()
        super().leaveEvent(event)


class StyledNumberInput(QWidget):
    """A styled number input with +/- buttons matching web component exactly.

    Features:
        - Increment/decrement buttons with +/- symbols
        - Button hover/active feedback
        - Disabled state (gray out, no interaction)
        - Error state (red border for invalid input)
        - Button disabled at min/max boundaries
        - Size variants: sm, default, lg
        - Auto-repeat on long-press (400ms delay, 200ms repeat)
        - value_changed(value: int) signal
    """

    value_changed = Signal(int)

    SIZE_CONFIG = {
        "sm": {"btn_w": 30, "height": 30, "input_w": 50, "font_size": 12, "icon_size": 12, "radius": 4},
        "default": {"btn_w": 36, "height": 36, "input_w": 60, "font_size": 14, "icon_size": 14, "radius": 6},
        "lg": {"btn_w": 44, "height": 44, "input_w": 70, "font_size": 16, "icon_size": 16, "radius": 6},
    }

    def __init__(
        self,
        value: int = 0,
        min_val: int = 0,
        max_val: int = 100,
        step: int = 1,
        size: str = "default",
        error: bool = False,
        enabled: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._value = value
        self._min = min_val
        self._max = max_val
        self._step = step
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._error = error
        self._enabled = enabled
        self._focused = False

        config = self._get_config()
        self.setFixedHeight(config["height"])

        # sizePolicy: 水平 Preferred（不主动扩展填充父容器）+ 垂直 Fixed
        # 最小尺寸 = sizeHint（由三个子控件自然组合），最大尺寸 = 父容器约束
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # Layout: 总宽度由三个子控件自然组合而成（左按钮 + 输入框 + 右按钮）
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)

        # Decrement button: 保持正方形 (width == height)
        self._decrement_btn = _NumberButton("-", "left", self)
        self._decrement_btn.setFixedSize(config["height"], config["height"])
        self._decrement_btn.pressed.connect(self._on_decrement_pressed)
        self._decrement_btn.released.connect(self._stop_repeat)
        layout.addWidget(self._decrement_btn)

        # Input: 宽度根据文字渲染宽度自适应（font metrics + 左右内边距）
        font = QFont("Microsoft YaHei UI", config["font_size"])
        self._input = _NumberDisplay(h_padding=12, parent=self)
        self._input.setObjectName(f"StyledNumberInput_input_{id(self)}")
        self._input.setFont(font)
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setFixedHeight(config["height"])
        self._validator = QIntValidator(min_val, max_val, self)
        self._input.setValidator(self._validator)
        self._input.setText(str(value))
        self._input.textChanged.connect(self._on_text_changed)
        self._input.installEventFilter(self)
        layout.addWidget(self._input, stretch=0)

        # Increment button: 保持正方形 (width == height)
        self._increment_btn = _NumberButton("+", "right", self)
        self._increment_btn.setFixedSize(config["height"], config["height"])
        self._increment_btn.pressed.connect(self._on_increment_pressed)
        self._increment_btn.released.connect(self._stop_repeat)
        layout.addWidget(self._increment_btn)

        # Auto-repeat timers
        self._initial_timer = QTimer(self)
        self._initial_timer.setSingleShot(True)
        self._initial_timer.setInterval(400)
        self._initial_timer.timeout.connect(self._on_initial_timeout)

        self._repeat_timer = QTimer(self)
        self._repeat_timer.setSingleShot(False)
        self._repeat_timer.setInterval(200)
        self._repeat_timer.timeout.connect(self._on_repeat_timeout)

        self._repeat_direction = 0

        self._apply_stylesheet()
        self._update_buttons()

        if not enabled:
            self._set_enabled(False)

    # ── Config ─────────────────────────────────────────────────

    def _get_config(self) -> dict:
        return self.SIZE_CONFIG.get(self._size, self.SIZE_CONFIG["default"])

    def refresh_theme(self) -> None:
        """Refresh stylesheet to reflect current theme colors."""
        self._apply_stylesheet()

    def _apply_stylesheet(self):
        config = self._get_config()
        input_obj = self._input.objectName()

        # Web版输入框是透明背景，颜色统一处理
        self._input.setStyleSheet(f"""
            #{input_obj} {{
                background-color: transparent;
                color: {tm.text.name()};
                border: none;
                font-size: {config["font_size"]}px;
                selection-background-color: {tm.accent.name()};
                selection-color: {tm.text.name()};
            }}
        """)

        self.update()

    def _update_buttons(self):
        """Enable/disable buttons based on current value vs min/max."""
        at_min = self._value <= self._min
        at_max = self._value >= self._max
        self._decrement_btn.set_button_disabled(at_min or not self._enabled)
        self._increment_btn.set_button_disabled(at_max or not self._enabled)

    # ── Value change ───────────────────────────────────────────

    def _change_value(self, direction: int) -> bool:
        """Change value by direction * step, clamped to [min, max]. Returns True if changed."""
        old_value = self._value
        new_value = old_value + direction * self._step
        new_value = max(self._min, min(self._max, new_value))
        if new_value == old_value:
            return False

        self._value = new_value
        self._input.blockSignals(True)
        self._input.setText(str(new_value))
        self._input.blockSignals(False)
        self._input.updateGeometry()
        self._error = False
        self._update_buttons()
        self.update()
        self.value_changed.emit(self._value)
        return True

    def _on_decrement_pressed(self):
        self._start_auto_repeat(-1)

    def _on_increment_pressed(self):
        self._start_auto_repeat(1)

    def _start_auto_repeat(self, direction: int):
        """Perform one immediate change and start timer for auto-repeat."""
        if not self._change_value(direction):
            return
        self._repeat_direction = direction
        self._initial_timer.start()

    def _on_initial_timeout(self):
        self._repeat_timer.start()

    def _on_repeat_timeout(self):
        self._change_value(self._repeat_direction)

    def _stop_repeat(self):
        self._initial_timer.stop()
        self._repeat_timer.stop()

    def _on_text_changed(self, text: str):
        self._input.updateGeometry()
        text = text.strip()
        if text == "" or text == "-":
            self._update_buttons()
            return

        try:
            val = int(text)
        except ValueError:
            self._set_error(True)
            self._update_buttons()
            return

        if val < self._min or val > self._max:
            self._set_error(True)
            self._update_buttons()
            return

        self._set_error(False)
        if val != self._value:
            self._value = val
            self._update_buttons()
            self.value_changed.emit(self._value)

    def _set_error(self, error: bool):
        if error != self._error:
            self._error = error
            self.update()

    def _set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._input.setEnabled(enabled)
        self._apply_stylesheet()
        self._update_buttons()
        self._decrement_btn.update()
        self._increment_btn.update()
        # Web版禁用状态使用opacity: 0.5统一处理
        if enabled:
            self.setGraphicsEffect(None)
        else:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            opacity_effect = QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.5)
            self.setGraphicsEffect(opacity_effect)
        self.update()

    # ── Public API ─────────────────────────────────────────────

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, val: int):
        val = max(self._min, min(self._max, val))
        if val != self._value:
            self._value = val
            self._input.blockSignals(True)
            self._input.setText(str(val))
            self._input.blockSignals(False)
            self._input.updateGeometry()
            self._error = False
            self._update_buttons()
            self.update()
            self.value_changed.emit(self._value)

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        config = self._get_config()
        self.setFixedHeight(config["height"])
        self._decrement_btn.setFixedSize(config["height"], config["height"])
        self._input.setFixedHeight(config["height"])
        font = QFont("Microsoft YaHei UI", config["font_size"])
        self._input.setFont(font)
        self._input.updateGeometry()
        self._increment_btn.setFixedSize(config["height"], config["height"])
        self._apply_stylesheet()
        self._decrement_btn.update()
        self._increment_btn.update()
        self.update()

    @property
    def error(self) -> bool:
        return self._error

    @error.setter
    def error(self, value: bool):
        self._error = value
        self.update()

    @property
    def min_val(self) -> int:
        return self._min

    @min_val.setter
    def min_val(self, value: int):
        self._min = value
        self._validator.setBottom(value)
        self._update_buttons()
        if self._value < value:
            self.value = value

    @property
    def max_val(self) -> int:
        return self._max

    @max_val.setter
    def max_val(self, value: int):
        self._max = value
        self._validator.setTop(value)
        self._update_buttons()
        if self._value > value:
            self.value = value

    # ── Events ─────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()
            config = self._get_config()
            radius = config["radius"]

            # Web版容器背景: #3a3a3a (--bg-input)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tm.alpha_of(tm.mid, 40))
            painter.drawRoundedRect(0, 0, w, h, radius, radius)

            # 错误状态的红色外发光 (box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.15))
            if self._error and self._focused:
                painter.setPen(Qt.NoPen)
                painter.setBrush(tm.alpha_of(tm.danger, 15))
                painter.drawRoundedRect(-2, -2, w + 4, h + 4, radius + 2, radius + 2)

            # Border
            if self._error:
                border_color = tm.danger
            elif self._focused:
                border_color = tm.accent
            elif not self._enabled:
                border_color = tm.alpha_of(tm.mid, 40)
            else:
                border_color = tm.alpha_of(tm.mid, 40)

            painter.setPen(QPen(border_color, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(1.0, 1.0, w - 2, h - 2, radius, radius)

    def eventFilter(self, obj, event):
        if obj is self._input:
            if event.type() == QEvent.FocusIn:
                self._focused = True
                self.update()
            elif event.type() == QEvent.FocusOut:
                self._focused = False
                self.update()
        return super().eventFilter(obj, event)
