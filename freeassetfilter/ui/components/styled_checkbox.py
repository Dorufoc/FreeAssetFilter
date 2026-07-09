"""Styled Checkbox component - matches web checkbox exactly."""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Property, QRectF, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent, QFont, QFontMetrics

from theme import tm


class StyledCheckbox(QWidget):
    """A checkbox matching the web component exactly.

    Fully self-drawn: checkbox box + label text are painted together
    in a single paintEvent, guaranteeing pixel-perfect vertical alignment.

    Sizes (checkbox box size):
        - sm: 14x14 (checkmark 9px, radius 3px)
        - default: 18x18 (checkmark 12px, radius 4px)
        - lg: 22x22 (checkmark 14px, radius 5px)

    Features:
        - checked / unchecked / indeterminate states
        - hover animation
        - press animation
        - optional label
        - disabled state
    """

    toggled = Signal(bool)

    SIZE_CONFIG = {
        "sm": {"box": 14, "check": 9, "radius": 3, "indeterminate_w": 7, "indeterminate_h": 2, "label_font": 12},
        "default": {"box": 18, "check": 12, "radius": 4, "indeterminate_w": 10, "indeterminate_h": 2, "label_font": 13},
        "lg": {"box": 22, "check": 14, "radius": 5, "indeterminate_w": 12, "indeterminate_h": 3, "label_font": 14},
    }

    def __init__(
        self,
        checked: bool = False,
        size: str = "default",
        enabled: bool = True,
        text: str = "",
        indeterminate: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._checked = checked
        self._size = size
        self._enabled = enabled
        self._text = text
        self._indeterminate = indeterminate
        self._hovered = False
        self._pressed = False
        self._hover_progress = 0.0
        self._press_progress = 0.0
        self._scale_progress = 1.0 if (checked or indeterminate) else 0.0
        self._bg_progress = 1.0 if (checked or indeterminate) else 0.0

        config = self._get_config()
        self._box_size = config["box"]
        self._radius = config["radius"]
        self._indeterminate_w = config["indeterminate_w"]
        self._indeterminate_h = config["indeterminate_h"]
        self._label_font_size = config["label_font"]
        self._gap = 10  # gap between box and text
        self._padding = 4  # outer padding to avoid layout clipping

        self.setCursor(Qt.PointingHandCursor)
        self._update_cursor()
        self._update_size_hint()

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

        # Scale animation for checkmark
        self._scale_anim = QPropertyAnimation(self, b"scale_progress")
        self._scale_anim.setDuration(200)
        self._scale_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._scale_anim.setParent(self)

        # Background color animation
        self._bg_anim = QPropertyAnimation(self, b"bg_progress")
        self._bg_anim.setDuration(200)
        self._bg_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._bg_anim.setParent(self)

    def _get_config(self) -> dict:
        return self.SIZE_CONFIG.get(self._size, self.SIZE_CONFIG["default"])

    def _update_cursor(self):
        if not self._enabled:
            self.setCursor(Qt.ForbiddenCursor)
        else:
            self.setCursor(Qt.PointingHandCursor)

    def _update_size_hint(self):
        """Recalculate minimum size based on box + text + padding."""
        fm = QFontMetrics(self._make_font())
        text_w = fm.horizontalAdvance(self._text) if self._text else 0
        p = self._padding
        h = max(self._box_size, fm.height()) + p * 2
        w = self._box_size + (self._gap + text_w if text_w else 0) + p * 2
        self.setMinimumSize(w, h)

    def _make_font(self) -> QFont:
        font = QFont("Segoe UI", self._label_font_size)
        return font

    # ── Qt properties for animation ──────────────────────────────

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

    @Property(float)
    def scale_progress(self):
        return self._scale_progress

    @scale_progress.setter
    def scale_progress(self, value: float):
        self._scale_progress = value
        self.update()

    @Property(float)
    def bg_progress(self):
        return self._bg_progress

    @bg_progress.setter
    def bg_progress(self, value: float):
        self._bg_progress = value
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
        self._indeterminate = False
        target = 1.0 if value else 0.0

        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale_progress)
        self._scale_anim.setEndValue(target)
        self._scale_anim.start()

        self._bg_anim.stop()
        self._bg_anim.setStartValue(self._bg_progress)
        self._bg_anim.setEndValue(target)
        self._bg_anim.start()

        self.update()
        self.toggled.emit(value)

    @property
    def indeterminate(self) -> bool:
        return self._indeterminate

    @indeterminate.setter
    def indeterminate(self, value: bool):
        self._indeterminate = value
        if value:
            self._checked = False
            self._scale_progress = 1.0
            self._bg_progress = 1.0
        self.update()

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        config = self.SIZE_CONFIG[value]
        self._box_size = config["box"]
        self._radius = config["radius"]
        self._indeterminate_w = config["indeterminate_w"]
        self._indeterminate_h = config["indeterminate_h"]
        self._label_font_size = config["label_font"]
        self._update_size_hint()
        self.update()

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str):
        self._text = value
        self._update_size_hint()
        self.update()

    def toggle(self):
        if self._enabled:
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

    # ── Paint ───────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)

            box = self._box_size
            radius = self._radius
            w, h = self.width(), self.height()
            p = self._padding

            # Checkbox box: vertically centered, with padding offset
            box_x = p
            box_y = (h - box) / 2

            # Determine colors
            if not self._enabled:
                if self._checked or self._indeterminate:
                    bg_color = tm.alpha_of(tm.accent, 39)
                    border_color = tm.alpha_of(tm.accent, 39)
                else:
                    bg_color = QColor(0, 0, 0, 0)
                    border_color = tm.mid
                check_alpha = 128
            else:
                _accent = tm.accent
                _border = tm.alpha_of(tm.mid, 40)
                border_color = _border
                bg_color = QColor(0, 0, 0, 0)
                check_alpha = 255

                p = self._bg_progress
                if p > 0:
                    bg_r = int(_accent.red() * p)
                    bg_g = int(_accent.green() * p)
                    bg_b = int(_accent.blue() * p)
                    bg_a = int(p * 255)
                    bg_color = QColor(bg_r, bg_g, bg_b, bg_a)

                    border_r = int(_border.red() * (1 - p) + _accent.red() * p)
                    border_g = int(_border.green() * (1 - p) + _accent.green() * p)
                    border_b = int(_border.blue() * (1 - p) + _accent.blue() * p)
                    border_color = QColor(border_r, border_g, border_b)

                hover_target = tm.alpha_of(tm.mid, 60)
                if self._hover_progress > 0 and p <= 0:
                    r = int(border_color.red() + (hover_target.red() - border_color.red()) * self._hover_progress)
                    g = int(border_color.green() + (hover_target.green() - border_color.green()) * self._hover_progress)
                    b = int(border_color.blue() + (hover_target.blue() - border_color.blue()) * self._hover_progress)
                    border_color = QColor(r, g, b)

            # Draw box background
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg_color)
            painter.drawRoundedRect(box_x, box_y, box, box, radius, radius)

            # Draw box border
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(box_x + 0.5, box_y + 0.5, box - 1, box - 1, radius, radius)

            # Draw checkmark or indeterminate line
            if self._checked or self._indeterminate:
                painter.setOpacity(check_alpha / 255.0)

                if self._indeterminate:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(tm.text)
                    line_x = box_x + (box - self._indeterminate_w) / 2
                    line_y = box_y + (box - self._indeterminate_h) / 2
                    painter.drawRoundedRect(
                        QRectF(line_x, line_y, self._indeterminate_w, self._indeterminate_h),
                        self._indeterminate_h / 2,
                        self._indeterminate_h / 2,
                    )
                else:
                    painter.setPen(QPen(tm.text, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

                    s = self._scale_progress
                    m = box * 0.125
                    bw = box - m * 2

                    x1 = box_x + m + bw * 0.80
                    y1 = box_y + m + bw * 0.25
                    x2 = box_x + m + bw * 0.33
                    y2 = box_y + m + bw * 0.75
                    x3 = box_x + m + bw * 0.15
                    y3 = box_y + m + bw * 0.48

                    cx = box_x + box / 2
                    cy = box_y + box / 2

                    def scale_point(px, py):
                        return (cx + (px - cx) * s, cy + (py - cy) * s)

                    x1, y1 = scale_point(x1, y1)
                    x2, y2 = scale_point(x2, y2)
                    x3, y3 = scale_point(x3, y3)

                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                    painter.drawLine(int(x2), int(y2), int(x3), int(y3))

            # Draw label text — align text horizontal midline with box center
            if self._text:
                font = self._make_font()
                fm = QFontMetrics(font)
                text_x = box_x + box + self._gap
                # Use boundingRect for actual text visual height (excludes line spacing)
                text_rect = fm.boundingRect(self._text)
                text_visual_h = text_rect.height()
                # baseline y so that text midline == box midline
                text_y = box_y + (box - text_visual_h) / 2 + fm.ascent()

                painter.setPen(tm.text if self._enabled else tm.alpha_of(tm.mid, 40))
                painter.setFont(font)
                painter.drawText(int(text_x), int(text_y), self._text)

    def set_checked_no_signal(self, value: bool):
        """Set checked state without emitting signal."""
        self._checked = value
        self._indeterminate = False
        self._scale_progress = 1.0 if value else 0.0
        self._bg_progress = 1.0 if value else 0.0
        self.update()
