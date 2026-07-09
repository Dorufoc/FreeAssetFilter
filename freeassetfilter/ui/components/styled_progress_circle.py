"""Styled Circular Progress component - matches web circular progress exactly."""

import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QPropertyAnimation, QEasingCurve, Property, QPointF
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QPen
from theme import tm


class StyledProgressCircle(QWidget):
    """A styled circular progress bar matching the web component exactly.
    
    Variants: default, success, warning, danger
    Sizes: sm (48px), md (64px), lg (80px)
    Features: percentage label, smooth animation
    """

    COLOR_CONFIG = {
        "default": tm.accent,
        "success": tm.accent,
        "warning": tm.warning,
        "danger": tm.danger,
    }

    SIZE_CONFIG = {
        "sm": {
            "size": 48,
            "stroke_width": 4,
            "radius": 20,
            "margin": 4,
            "font_size": 10,
        },
        "md": {
            "size": 64,
            "stroke_width": 5,
            "radius": 26,
            "margin": 4,
            "font_size": 12,
        },
        "lg": {
            "size": 80,
            "stroke_width": 6,
            "radius": 34,
            "margin": 4,
            "font_size": 14,
        },
    }

    def __init__(
        self,
        value: float = 0.0,
        size: str = "md",
        variant: str = "default",
        show_percentage: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self._size = size if size in self.SIZE_CONFIG else "md"
        self._variant = variant if variant in self.COLOR_CONFIG else "default"
        self._show_percentage = show_percentage

        self._circle_widget = None

        self._setup_ui()

    def _setup_ui(self):
        config = self.SIZE_CONFIG[self._size]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        margin = config["margin"]

        self._circle_widget = CircleWidget(
            value=self._value,
            radius=config["radius"],
            stroke_width=config["stroke_width"],
            variant=self._variant,
            margin=margin,
            show_percentage=self._show_percentage,
            font_size=config["font_size"],
        )
        circle_size = config["size"] + margin * 2
        self._circle_widget.setFixedSize(circle_size, circle_size)
        layout.addWidget(self._circle_widget, alignment=Qt.AlignCenter)

        widget_size = circle_size
        self.setFixedSize(widget_size, widget_size)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    @Property(float)
    def value(self):
        return self._value

    @value.setter
    def value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        if self._circle_widget:
            self._circle_widget.value = self._value

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, v: str):
        if v not in self.SIZE_CONFIG:
            return
        self._size = v
        self._rebuild_ui()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, v: str):
        if v not in self.COLOR_CONFIG:
            return
        self._variant = v
        if self._circle_widget:
            self._circle_widget.variant = v

    def _rebuild_ui(self):
        """Rebuild the UI with new size config."""
        # Clear existing layout
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        config = self.SIZE_CONFIG[self._size]
        margin = config["margin"]

        self._circle_widget = CircleWidget(
            value=self._value,
            radius=config["radius"],
            stroke_width=config["stroke_width"],
            variant=self._variant,
            margin=margin,
            show_percentage=self._show_percentage,
            font_size=config["font_size"],
        )
        circle_size = config["size"] + margin * 2
        self._circle_widget.setFixedSize(circle_size, circle_size)
        self.layout().addWidget(self._circle_widget, alignment=Qt.AlignCenter)

        widget_size = circle_size
        self.setFixedSize(widget_size, widget_size)


class CircleWidget(QWidget):
    """The circle widget that handles SVG-like circle progress painting."""

    def __init__(
        self,
        value: float = 0.0,
        radius: int = 26,
        stroke_width: int = 5,
        variant: str = "default",
        margin: int = 4,
        show_percentage: bool = True,
        font_size: int = 12,
        parent=None,
    ):
        super().__init__(parent)
        self._value = value
        self._radius = radius
        self._stroke_width = stroke_width
        self._variant = variant
        self._margin = margin
        self._show_percentage = show_percentage
        self._font_size = font_size
        self._anim_value = value

        # Circumference = 2 * pi * r
        self._circumference = 2 * math.pi * radius

        # Font used for the centered percentage label
        self._percent_font = QFont("Microsoft YaHei UI", font_size)
        self._percent_font.setWeight(QFont.Weight.Medium)

        # Animation for smooth transition
        self._value_anim = QPropertyAnimation(self, b"anim_value")
        self._value_anim.setDuration(400)
        self._value_anim.setEasingCurve(QEasingCurve.InOutCubic)

    @Property(float)
    def anim_value(self):
        return self._anim_value

    @anim_value.setter
    def anim_value(self, v: float):
        self._anim_value = v
        self.update()

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float):
        self._value = max(0.0, min(1.0, v))

        # Get current animated position as start point
        if self._value_anim.state() == QPropertyAnimation.State.Running:
            current = self._value_anim.currentValue()
            if current is not None:
                start = float(current)
            else:
                start = self._anim_value
        else:
            start = self._anim_value

        # Duration proportional to distance (min 50ms, max 400ms)
        distance = abs(self._value - start)
        duration = max(50, int(400 * distance)) if distance > 0.01 else 50

        self._value_anim.stop()
        self._value_anim.setDuration(duration)
        self._value_anim.setStartValue(start)
        self._value_anim.setEndValue(self._value)
        self._value_anim.start()
        self.update()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, v: str):
        self._variant = v
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Offset by margin so the circle is centered in the padded widget
            m = float(self._margin)
            cx = float(self.width()) / 2.0
            cy = float(self.height()) / 2.0
            r = float(self._radius)

            # Track circle (background)
            track_color = tm.alpha_of(tm.mid, 40)
            pen = QPen(track_color, float(self._stroke_width))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawEllipse(QPointF(cx, cy), r, r)

            # Fill circle (progress) using arc drawing
            fill_color = StyledProgressCircle.COLOR_CONFIG[self._variant]
            pen.setColor(fill_color)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            # Draw arc for progress (0% = no arc, 100% = full circle)
            # Qt arc angles: 0 = 3 o'clock, increases counter-clockwise
            # Start from top: 90 * 16, sweep clockwise with negative angle
            progress_angle = self._anim_value * 360 * 16  # 16ths of a degree
            if progress_angle > 0:
                painter.drawArc(
                    int(cx - r), int(cy - r),
                    int(r * 2), int(r * 2),
                    90 * 16,  # Start from top
                    -int(progress_angle)  # Negative for clockwise sweep
                )

            # Percentage label centered inside the ring
            if self._show_percentage:
                painter.setPen(tm.text)
                painter.setFont(self._percent_font)
                text = f"{int(self._anim_value * 100)}%"
                text_rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
                painter.drawText(text_rect, Qt.AlignCenter, text)
        finally:
            if painter.isActive():
                painter.end()
