"""Styled Toggle Switch component - matches web toggle exactly."""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Property, QRectF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPaintEvent

from theme import tm


class StyledToggle(QWidget):
    """A toggle switch matching the web component exactly.
    
    Sizes (width x height):
        - sm: 36x20 (thumb 16px, travel 16px)
        - default: 44x24 (thumb 20px, travel 20px)
        - lg: 52x28 (thumb 24px, travel 24px)
    """

    toggled = Signal(bool)

    SIZE_CONFIG = {
        "sm": {"width": 36, "height": 20, "thumb": 16, "travel": 16, "margin": 2},
        "default": {"width": 44, "height": 24, "thumb": 20, "travel": 20, "margin": 2},
        "lg": {"width": 52, "height": 28, "thumb": 24, "travel": 24, "margin": 2},
    }

    def __init__(
        self,
        checked: bool = False,
        size: str = "default",
        enabled: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._checked = checked
        self._size = size
        self._enabled = enabled
        self._anim_progress = 1.0 if checked else 0.0
        self._hovered = False
        self._pressed = False
        self._hover_progress = 0.0    # animated: 0→1 on enter, 1→0 on leave
        self._press_progress = 0.0    # animated: 0→1 on press, 1→0 on release

        config = self.SIZE_CONFIG.get(size, self.SIZE_CONFIG["default"])
        self.setFixedSize(config["width"], config["height"])
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        # Toggle animation (On/Off)
        self._toggle_anim = QPropertyAnimation(self, b"anim_progress")
        self._toggle_anim.setDuration(250)
        self._toggle_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Hover animation
        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutCubic)

        # Press animation
        self._press_anim = QPropertyAnimation(self, b"press_progress")
        self._press_anim.setDuration(120)
        self._press_anim.setEasingCurve(QEasingCurve.OutBack)

        if checked:
            self._anim_progress = 1.0

    def _get_config(self) -> dict:
        return self.SIZE_CONFIG.get(self._size, self.SIZE_CONFIG["default"])

    # ── Qt properties for animation ──────────────────────────────

    @Property(float)
    def anim_progress(self):
        return self._anim_progress

    @anim_progress.setter
    def anim_progress(self, value: float):
        self._anim_progress = value
        self.update()

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    @Property(float)
    def press_progress(self):
        return self._press_progress

    @press_progress.setter
    def press_progress(self, value: float):
        self._press_progress = value
        self.update()

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
        # Constant velocity: 250ms per full unit, min 120ms to prevent jitter
        distance = abs(target - self._anim_progress)
        self._toggle_anim.setDuration(max(120, int(250 * distance)))
        self._toggle_anim.setStartValue(self._anim_progress)
        self._toggle_anim.setEndValue(target)
        self._toggle_anim.start()
        self.toggled.emit(value)

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        config = self.SIZE_CONFIG[value]
        self.setFixedSize(config["width"], config["height"])
        self.update()

    def toggle(self):
        self.checked = not self._checked

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
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
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

    # ── Paint ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        config = self._get_config()
        thumb_size = config["thumb"]
        margin = config["margin"]
        travel = config["travel"]

        # Determine track color
        if not self._enabled:
            if self._checked:
                track_color = tm.alpha_of(tm.accent, 31)
            else:
                track_color = tm.alpha_of(tm.mid, 40)
            thumb_color = tm.alpha_of(tm.mid, 60)
            alpha = 128
        else:
            # Interpolate track color based on toggle progress
            track_off = tm.alpha_of(tm.mid, 40)
            track_on = tm.accent
            r = int(track_off.red() + (track_on.red() - track_off.red()) * self._anim_progress)
            g = int(track_off.green() + (track_on.green() - track_off.green()) * self._anim_progress)
            b = int(track_off.blue() + (track_on.blue() - track_off.blue()) * self._anim_progress)
            base = QColor(r, g, b)

            # Smooth hover brightness via animated progress
            hovered = base.lighter(115)
            track_color = QColor(
                int(base.red()   + (hovered.red()   - base.red())   * self._hover_progress),
                int(base.green() + (hovered.green() - base.green()) * self._hover_progress),
                int(base.blue()  + (hovered.blue()  - base.blue())  * self._hover_progress),
            )

            thumb_color = tm.text
            alpha = 255

        # Calculate thumb rect — base size is 0.8× the original
        base = thumb_size * 0.8
        offset = (thumb_size - base) / 2.0
        thumb_x = margin + travel * self._anim_progress + offset
        thumb_y = margin + offset
        thumb_rect = QRectF(thumb_x, thumb_y, base, base)

        # Uniform scale: default 1.0 → hover 1.1 → press 1.2
        scale = 1.0 + 0.1 * self._hover_progress + 0.1 * self._press_progress
        if scale != 1.0:
            c = thumb_rect.center()
            s = base * scale
            thumb_rect.setWidth(s)
            thumb_rect.setHeight(s)
            thumb_rect.moveCenter(c)

        track_rect = QRectF(0, 0, self.width(), self.height())
        shadow_rect = QRectF(thumb_rect.x(), thumb_rect.y() + 1, thumb_rect.width(), thumb_rect.height())

        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)

            painter.setOpacity(alpha / 255.0)

            # Draw track
            painter.setPen(Qt.NoPen)
            painter.setBrush(track_color)
            painter.drawRoundedRect(track_rect, self.height() / 2, self.height() / 2)

            # Thumb shadow
            painter.setOpacity(alpha / 255.0 * 0.3)
            painter.setBrush(tm.alpha_of(tm.black, 30))
            painter.drawEllipse(shadow_rect)

            # Thumb
            painter.setOpacity(alpha / 255.0)
            painter.setBrush(thumb_color)
            painter.drawEllipse(thumb_rect)
