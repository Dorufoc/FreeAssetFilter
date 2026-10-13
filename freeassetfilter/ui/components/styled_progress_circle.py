"""Styled Circular Progress component - matches web circular progress exactly."""

import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QRectF, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPainter, QPaintEvent, QFont, QPen
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
    WARNING_THRESHOLD = 0.8
    DANGER_THRESHOLD = 0.9

    @classmethod
    def variant_for_value(cls, value: float) -> str:
        """Return the semantic color variant for a usage ratio."""
        value = max(0.0, min(1.0, float(value)))
        if value >= cls.DANGER_THRESHOLD:
            return "danger"
        if value >= cls.WARNING_THRESHOLD:
            return "warning"
        return "default"

    @classmethod
    def paint_progress(
        cls,
        painter: QPainter,
        rect: QRectF,
        value: float,
        variant: str = "default",
        show_percentage: bool = True,
        size_variant: str = "sm",
        fit_to_rect: bool = False,
    ) -> None:
        """Paint a circular progress ring using the styled component's visuals."""
        if not painter.isActive() or rect.isEmpty():
            return
        value = max(0.0, min(1.0, float(value)))
        variant = variant if variant in cls.COLOR_CONFIG else "default"
        size = min(float(rect.width()), float(rect.height()))
        config = cls.SIZE_CONFIG.get(size_variant, cls.SIZE_CONFIG["sm"])
        if fit_to_rect:
            scale = size / float(config["radius"] * 2 + config["stroke_width"])
        else:
            scale = size / float(config["size"] + config["margin"] * 2)
        radius = config["radius"] * scale
        stroke_width = max(1.0, config["stroke_width"] * scale)
        center = rect.center()
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            track = (
                tm.alpha_of(tm.mid, 40) if tm.is_dark_theme()
                else tm.alpha_of(tm.text, 8)
            )
            pen = QPen(track, stroke_width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawEllipse(center, radius, radius)
            if value > 0.0:
                pen.setColor(cls.COLOR_CONFIG[variant])
                painter.setPen(pen)
                painter.drawArc(
                    int(center.x() - radius), int(center.y() - radius),
                    int(radius * 2), int(radius * 2), 90 * 16, -int(value * 360 * 16),
                )
            if show_percentage:
                font = QFont("Microsoft YaHei UI", max(1, int(config["font_size"] * scale)))
                font.setWeight(QFont.Weight.Medium)
                painter.setFont(font)
                painter.setPen(tm.text)
                painter.drawText(rect, Qt.AlignCenter, f"{int(value * 100)}%")
        finally:
            painter.restore()

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
            size_variant=self._size,
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
            size_variant=self._size,
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
        size_variant: str = "md",
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
        self._size_variant = size_variant
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
        StyledProgressCircle.paint_progress(
            painter,
            QRectF(self.rect()),
            self._anim_value,
            self._variant,
            self._show_percentage,
            self._size_variant,
        )
        if painter.isActive():
            painter.end()
