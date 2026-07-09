"""Styled Progress component - matches web progress bar exactly."""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property, QTimer
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QFont, QLinearGradient, QBrush
from theme import tm


class StyledProgress(QWidget):
    """A styled linear progress bar matching the web component exactly.
    
    Variants: default, success, warning, danger
    Sizes: sm (4px), default (8px), lg (12px)
    Features: label support, striped animation, inline label mode
    """

    COLOR_CONFIG = {
        "default": tm.accent,
        "success": tm.accent,
        "warning": tm.warning,
        "danger": tm.danger,
    }

    SIZE_CONFIG = {
        "sm": {"track_height": 4, "font_size": 11},
        "default": {"track_height": 8, "font_size": 12},
        "lg": {"track_height": 12, "font_size": 12},
    }

    def __init__(
        self,
        value: float = 0.0,
        size: str = "default",
        variant: str = "default",
        striped: bool = False,
        label_title: str = "",
        label_value: str = "",
        label_inline: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._variant = variant if variant in self.COLOR_CONFIG else "default"
        self._striped = striped
        self._label_title = label_title
        self._label_value = label_value
        self._label_inline = label_inline
        self._stripe_offset = 0.0

        self._label_layout = None
        self._inline_label = None
        self._track_widget = None

        self._setup_ui()

        if striped:
            self._start_stripe_animation()

    def _setup_ui(self):
        config = self.SIZE_CONFIG[self._size]

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Label row (top labels)
        if self._label_title or self._label_value:
            self._label_layout = QHBoxLayout()
            self._label_layout.setContentsMargins(0, 0, 0, 6)
            self._label_layout.setSpacing(0)

            self._title_label = QLabel(self._label_title)
            title_font = QFont("Microsoft YaHei UI", config["font_size"])
            title_font.setWeight(QFont.Weight.Normal)
            self._title_label.setFont(title_font)
            self._title_label.setStyleSheet(f"color: {tm.mid.name()};")
            self._label_layout.addWidget(self._title_label)

            self._label_layout.addStretch()

            self._value_label = QLabel(self._label_value)
            value_font = QFont("Microsoft YaHei UI", config["font_size"])
            value_font.setWeight(QFont.Weight.Normal)
            self._value_label.setFont(value_font)
            self._value_label.setStyleSheet(f"color: {tm.mid.name()};")
            self._label_layout.addWidget(self._value_label)

            main_layout.addLayout(self._label_layout)

        # Inline label or track row
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        if self._label_inline:
            self._inline_label = QLabel(f"{int(self._value * 100)}%")
            inline_font = QFont("Microsoft YaHei UI", config["font_size"])
            self._inline_label.setFont(inline_font)
            self._inline_label.setStyleSheet(f"color: {tm.mid.name()};")
            self._inline_label.setMinimumWidth(42)
            row_layout.addWidget(self._inline_label)

        self._track_widget = ProgressTrack(
            value=self._value,
            track_height=config["track_height"],
            variant=self._variant,
            striped=self._striped,
        )
        row_layout.addWidget(self._track_widget, stretch=1)

        main_layout.addLayout(row_layout)

        # Set fixed height
        total_h = config["track_height"] + 8
        if self._label_layout:
            total_h += config["font_size"] + 6
        self.setFixedHeight(total_h)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _start_stripe_animation(self):
        self._stripe_timer = QTimer(self)
        self._stripe_timer.timeout.connect(self._on_stripe_tick)
        self._stripe_timer.start(50)

    def _on_stripe_tick(self):
        self._stripe_offset = (self._stripe_offset + 1) % 16
        if self._track_widget:
            self._track_widget.stripe_offset = self._stripe_offset

    @Property(float)
    def value(self):
        return self._value

    @value.setter
    def value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        if self._track_widget:
            self._track_widget.value = self._value
        if self._label_inline and self._inline_label:
            self._inline_label.setText(f"{int(self._value * 100)}%")

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, v: str):
        if v not in self.SIZE_CONFIG:
            return
        self._size = v
        if self._track_widget:
            self._track_widget.track_height = self.SIZE_CONFIG[v]["track_height"]

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, v: str):
        if v not in self.COLOR_CONFIG:
            return
        self._variant = v
        if self._track_widget:
            self._track_widget.variant = v

    def set_label(self, title: str = "", value: str = ""):
        """Update top labels."""
        self._label_title = title
        self._label_value = value
        if self._label_layout:
            self._title_label.setText(title)
            self._value_label.setText(value)

    def set_value_label(self, text: str):
        """Update inline value label."""
        if self._inline_label:
            self._inline_label.setText(text)


class ProgressTrack(QWidget):
    """The track widget that handles progress bar painting."""

    def __init__(
        self,
        value: float = 0.0,
        track_height: int = 8,
        variant: str = "default",
        striped: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._value = value
        self._track_height = track_height
        self._variant = variant
        self._striped = striped
        self._stripe_offset = 0.0
        self._anim_value = value

        self.setMinimumHeight(track_height)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Width animation
        self._width_anim = QPropertyAnimation(self, b"anim_value")
        self._width_anim.setDuration(400)
        self._width_anim.setEasingCurve(QEasingCurve.InOutCubic)

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
        if self._width_anim.state() == QPropertyAnimation.State.Running:
            current = self._width_anim.currentValue()
            if current is not None:
                start = float(current)
            else:
                start = self._anim_value
        else:
            start = self._anim_value

        # Duration proportional to distance (min 50ms, max 400ms)
        distance = abs(self._value - start)
        duration = max(50, int(400 * distance)) if distance > 0.01 else 50

        self._width_anim.stop()
        self._width_anim.setDuration(duration)
        self._width_anim.setStartValue(start)
        self._width_anim.setEndValue(self._value)
        self._width_anim.start()
        self.update()

    @property
    def track_height(self) -> int:
        return self._track_height

    @track_height.setter
    def track_height(self, h: int):
        self._track_height = h
        self.setMinimumHeight(h)
        self.update()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, v: str):
        self._variant = v
        self.update()

    @property
    def stripe_offset(self) -> float:
        return self._stripe_offset

    @stripe_offset.setter
    def stripe_offset(self, v: float):
        self._stripe_offset = v
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)

            radius = float(self._track_height) / 2.0
            fill_width = float(self.width()) * self._anim_value

            # Track background
            bg_color = tm.alpha_of(tm.mid, 40)
            painter.setBrush(bg_color)
            painter.drawRoundedRect(
                QRectF(0, 0, float(self.width()), float(self._track_height)),
                radius,
                radius,
            )

            # Track fill - draw with proper rounded ends
            if fill_width > 0:
                fill_color = StyledProgress.COLOR_CONFIG[self._variant]
                painter.setBrush(fill_color)

                # Draw rounded rect exactly at fill width
                # Both ends are always rounded (left and right)
                painter.drawRoundedRect(
                    QRectF(0, 0, fill_width, float(self._track_height)),
                    radius,
                    radius,
                )

                # Striped overlay
                if self._striped and fill_width > 0:
                    painter.save()
                    painter.setClipRect(
                        QRectF(0, 0, fill_width, float(self._track_height))
                    )
                    self._draw_stripes(painter, fill_width)
                    painter.restore()
        finally:
            if painter.isActive():
                painter.end()

    def _draw_stripes(self, painter: QPainter, fill_width: float):
        """Draw diagonal stripes on the fill."""
        stripe_size = 16.0
        offset = self._stripe_offset

        painter.setPen(Qt.PenStyle.NoPen)
        stripe_color = tm.alpha_of(tm.text, 15)  # rgba(255,255,255,0.15)

        # Draw 45-degree diagonal stripes
        h = float(self._track_height)
        x = -stripe_size + offset
        while x < fill_width + stripe_size:
            points = [
                (x, 0),
                (x + stripe_size / 2, 0),
                (x + stripe_size / 2 + h, h),
                (x + h, h),
            ]
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            polygon = QPolygonF([QPointF(p[0], p[1]) for p in points])
            painter.setBrush(stripe_color)
            painter.drawPolygon(polygon)

            # Second stripe in the pattern
            points2 = [
                (x + stripe_size, 0),
                (x + stripe_size * 1.5, 0),
                (x + stripe_size * 1.5 + h, h),
                (x + stripe_size + h, h),
            ]
            polygon2 = QPolygonF([QPointF(p[0], p[1]) for p in points2])
            painter.drawPolygon(polygon2)

            x += stripe_size * 2
