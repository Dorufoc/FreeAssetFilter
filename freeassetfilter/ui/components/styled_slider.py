"""Styled Slider component - matches web slider exactly."""

import math

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QMouseEvent, QFont

from theme import tm


class StyledSlider(QWidget):
    """A styled slider matching the web component exactly.
    
    Features: draggable thumb, fill track, tick marks, labels
    Sizes: sm, default, lg
    """

    value_changed = Signal(float)  # 0.0 to 1.0

    SIZE_CONFIG = {
        "sm": {"track_height": 4, "thumb_radius": 6, "width": 240},
        "default": {"track_height": 6, "thumb_radius": 8, "width": 240},
        "lg": {"track_height": 8, "thumb_radius": 10, "width": 240},
    }

    pressed = Signal()
    released = Signal()

    def __init__(
        self,
        value: float = 0.5,
        size: str = "default",
        tick_count: int = 0,
        labels: list = None,
        enabled: bool = True,
        orientation: Qt.Orientation = Qt.Horizontal,
        parent=None,
    ):
        super().__init__(parent)
        self._value = max(0.0, min(1.0, value))
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._tick_count = tick_count
        self._labels = labels or []
        self._enabled = enabled
        self._orientation = orientation
        self._dragging = False
        self._hovered = False

        config = self.SIZE_CONFIG[self._size]

        # Extra internal margin on SliderTrack so the 1.2×-scaled thumb
        # at min/max value stays within the track widget's backing store
        # (QPainter cannot paint beyond the widget's own pixel surface).
        extra = max(2, math.ceil(config["thumb_radius"] * 0.3))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._track_widget = SliderTrack(
            value=self._value,
            track_height=config["track_height"],
            thumb_radius=config["thumb_radius"],
            tick_count=tick_count,
            enabled=enabled,
            extra_margin=extra,
            orientation=orientation,
        )

        if orientation == Qt.Horizontal:
            # 横向模式：轨道直接拉伸填满可用宽度
            layout.addWidget(self._track_widget)
        else:
            # 纵向模式：用水平容器包裹，左右加 stretch 使轨道水平居中，同时允许垂直拉伸
            track_container = QWidget()
            container_layout = QHBoxLayout(track_container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(0)
            container_layout.addStretch()
            container_layout.addWidget(self._track_widget)
            container_layout.addStretch()
            layout.addWidget(track_container, stretch=1)

        if self._labels:
            if orientation == Qt.Horizontal:
                labels_layout = QHBoxLayout()
                labels_layout.setContentsMargins(config["thumb_radius"] + extra, 0, config["thumb_radius"] + extra, 0)
                labels_layout.setSpacing(0)
                for i, label_text in enumerate(self._labels):
                    lbl = QLabel(label_text)
                    font = QFont("Microsoft YaHei UI", 11)
                    lbl.setFont(font)
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()};")
                    labels_layout.addWidget(lbl, stretch=1)
                    if i == 0:
                        lbl.setStyleSheet(f"color: {tm.mid.name()}; font-weight: 500;")
                layout.addLayout(labels_layout)
                self._label_widgets = labels_layout
            else:
                labels_layout = QVBoxLayout()
                labels_layout.setContentsMargins(0, config["thumb_radius"] + extra, 0, config["thumb_radius"] + extra)
                labels_layout.setSpacing(0)
                for i, label_text in enumerate(self._labels):
                    lbl = QLabel(label_text)
                    font = QFont("Microsoft YaHei UI", 11)
                    lbl.setFont(font)
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()};")
                    labels_layout.addWidget(lbl, stretch=1)
                    if i == 0:
                        lbl.setStyleSheet(f"color: {tm.mid.name()}; font-weight: 500;")
                layout.addLayout(labels_layout)
                self._label_widgets = labels_layout

        self._track_widget.value_changed.connect(self._on_value_changed)
        self._track_widget.pressed.connect(self.pressed.emit)
        self._track_widget.released.connect(self.released.emit)

        if orientation == Qt.Horizontal:
            # 支持自适应宽度（移除固定宽度设置）
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumWidth(60 + extra * 2)
            # Calculate height: track + spacing + labels
            track_h = config["track_height"] + int(config["thumb_radius"] * 2 * 1.25) + 8
            label_h = 28 if self._labels else 0
            total_h = track_h + (8 if self._labels else 0) + label_h
            self.setFixedHeight(total_h)
        else:
            # 纵向模式：固定宽度、自适应高度
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            track_w = config["track_height"] + int(config["thumb_radius"] * 2 * 1.25) + 8
            label_w = 32 if self._labels else 0
            total_w = track_w + (8 if self._labels else 0) + label_w
            self.setFixedWidth(total_w)
            self.setMinimumHeight(60 + extra * 2)

    def _on_value_changed(self, value: float):
        self._value = value
        self.value_changed.emit(value)

        # Update label active state
        if self._labels and hasattr(self, "_label_widgets"):
            layout = self._label_widgets
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget():
                    lbl = item.widget()
                    active_index = round(value * (len(self._labels) - 1))
                    if i == active_index:
                        lbl.setStyleSheet(f"color: {tm.mid.name()}; font-weight: 500;")
                    else:
                        lbl.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()};")

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float):
        self._value = max(0.0, min(1.0, v))
        self._track_widget.value = self._value

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        config = self.SIZE_CONFIG[value]
        self._track_widget.track_height = config["track_height"]
        self._track_widget.thumb_radius = config["thumb_radius"]
        # 重新应用方向相关的尺寸约束
        extra = max(2, math.ceil(config["thumb_radius"] * 0.3))
        if self._orientation == Qt.Horizontal:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumWidth(60 + extra * 2)
            track_h = config["track_height"] + int(config["thumb_radius"] * 2 * 1.25) + 8
            label_h = 28 if self._labels else 0
            total_h = track_h + (8 if self._labels else 0) + label_h
            self.setFixedHeight(total_h)
        else:
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            track_w = config["track_height"] + int(config["thumb_radius"] * 2 * 1.25) + 8
            label_w = 32 if self._labels else 0
            total_w = track_w + (8 if self._labels else 0) + label_w
            self.setFixedWidth(total_w)
            self.setMinimumHeight(60 + extra * 2)


class SliderTrack(QWidget):
    """The actual track widget that handles painting and interaction."""

    value_changed = Signal(float)
    pressed = Signal()
    released = Signal()

    def __init__(
        self,
        value: float = 0.5,
        track_height: int = 6,
        thumb_radius: int = 9,
        tick_count: int = 0,
        enabled: bool = True,
        extra_margin: int = 0,
        orientation: Qt.Orientation = Qt.Horizontal,
        parent=None,
    ):
        super().__init__(parent)
        self._value = value
        self._track_height = track_height
        self._thumb_radius = thumb_radius
        self._extra_margin = extra_margin
        self._tick_count = tick_count
        self._enabled = enabled
        self._orientation = orientation
        self._hovered = False
        self._dragging = False
        self._hover_progress = 0.0
        self._drag_progress = 0.0

        thumb_extra = int(thumb_radius * 2 * 1.25) + 4  # +25% for hover scale
        if orientation == Qt.Horizontal:
            self.setMinimumHeight(track_height + thumb_extra)
            self.setMinimumWidth(60 + extra_margin * 2)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.setMinimumWidth(track_height + thumb_extra)
            self.setMinimumHeight(60 + extra_margin * 2)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        # Hover animation
        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.InOutCubic)

        # Drag animation
        self._drag_anim = QPropertyAnimation(self, b"drag_progress")
        self._drag_anim.setDuration(120)
        self._drag_anim.setEasingCurve(QEasingCurve.OutBack)

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float):
        self._value = v
        self.update()

    @property
    def track_height(self) -> int:
        return self._track_height

    @track_height.setter
    def track_height(self, h: int):
        self._track_height = h
        thumb_extra = int(self._thumb_radius * 2 * 1.25) + 4
        if self._orientation == Qt.Horizontal:
            self.setMinimumHeight(h + thumb_extra)
        else:
            self.setMinimumWidth(h + thumb_extra)
        self.update()

    @property
    def thumb_radius(self) -> int:
        return self._thumb_radius

    @thumb_radius.setter
    def thumb_radius(self, r: int):
        self._thumb_radius = r
        thumb_extra = int(r * 2 * 1.25) + 4
        if self._orientation == Qt.Horizontal:
            self.setMinimumHeight(self._track_height + thumb_extra)
        else:
            self.setMinimumWidth(self._track_height + thumb_extra)
        self.update()

    def _get_thumb_pos(self) -> tuple[float, float]:
        margin = self._thumb_radius + self._extra_margin
        if self._orientation == Qt.Horizontal:
            available = self.width() - margin * 2
            x = margin + available * self._value
            y = self.height() / 2.0
            return x, y
        else:
            available = self.height() - margin * 2
            x = self.width() / 2.0
            # 纵向模式：底部为 0，顶部为 1
            y = self.height() - margin - available * self._value
            return x, y

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._enabled:
            self._dragging = True
            self._animate_drag(1.0)
            if self._orientation == Qt.Horizontal:
                self._update_value_from_x(event.pos().x())
            else:
                self._update_value_from_y(event.pos().y())
            self.pressed.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._enabled:
            if self._orientation == Qt.Horizontal:
                self._update_value_from_x(event.pos().x())
            else:
                self._update_value_from_y(event.pos().y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            was_dragging = self._dragging
            self._dragging = False
            self._animate_drag(0.0)
            if was_dragging:
                self.released.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._dragging = False
        self._animate_hover(0.0)
        self._animate_drag(0.0)
        super().leaveEvent(event)

    # ── Animated properties ──────────────────────────────────

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, value: float):
        self._hover_progress = value
        self.update()

    @Property(float)
    def drag_progress(self):
        return self._drag_progress

    @drag_progress.setter
    def drag_progress(self, value: float):
        self._drag_progress = value
        self.update()

    def _animate_hover(self, target: float):
        self._hover_anim.stop()
        d = abs(target - self._hover_progress)
        self._hover_anim.setDuration(max(50, int(180 * d)))
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(target)
        self._hover_anim.setEasingCurve(
            QEasingCurve.OutBack if target > 0.5 else QEasingCurve.InCubic
        )
        self._hover_anim.start()

    def _animate_drag(self, target: float):
        self._drag_anim.stop()
        d = abs(target - self._drag_progress)
        self._drag_anim.setDuration(max(40, int(120 * d)))
        self._drag_anim.setStartValue(self._drag_progress)
        self._drag_anim.setEndValue(target)
        self._drag_anim.setEasingCurve(
            QEasingCurve.OutQuad if target > 0.5 else QEasingCurve.OutElastic
        )
        self._drag_anim.start()

    def _update_value_from_x(self, x: int):
        margin = self._thumb_radius + self._extra_margin
        available = self.width() - margin * 2
        value = (x - margin) / available
        self._apply_value(value)

    def _update_value_from_y(self, y: int):
        margin = self._thumb_radius + self._extra_margin
        available = self.height() - margin * 2
        # 纵向模式：底部为 0，顶部为 1
        value = 1.0 - (y - margin) / available
        self._apply_value(value)

    def _apply_value(self, value: float):
        value = max(0.0, min(1.0, value))

        # Snap to ticks if present
        if self._tick_count > 0:
            snap_points = self._tick_count
            snapped = round(value * snap_points) / snap_points
            value = snapped

        self._value = value
        self.value_changed.emit(value)
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if not painter.isActive():
            return

        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)

            margin = float(self._thumb_radius + self._extra_margin)
            thumb_x, thumb_y = self._get_thumb_pos()
            thumb_r = float(self._thumb_radius)
            track_thickness = float(self._track_height)

            if self._orientation == Qt.Horizontal:
                available = float(self.width()) - margin * 2.0
                track_y = self.height() / 2.0
                y_pos = track_y - track_thickness / 2.0

                # Track background
                painter.setBrush(tm.alpha_of(tm.mid, 40))
                track_rect = QRectF(margin, y_pos, available, track_thickness)
                painter.drawRoundedRect(track_rect, track_thickness / 2.0, track_thickness / 2.0)

                # Track fill
                fill_width = available * self._value
                painter.setBrush(tm.accent)
                fill_rect = QRectF(margin, y_pos, fill_width, track_thickness)
                painter.drawRoundedRect(fill_rect, track_thickness / 2.0, track_thickness / 2.0)

                # Ticks
                if self._tick_count > 0:
                    for i in range(self._tick_count + 1):
                        tick_x = margin + (available * i / self._tick_count)
                        filled = i / self._tick_count <= self._value
                        painter.setBrush(tm.alpha_of(tm.mid, 30) if filled else tm.alpha_of(tm.mid, 20))
                        painter.drawEllipse(int(tick_x - 2), int(track_y - 2), 4, 4)
            else:
                available = float(self.height()) - margin * 2.0
                track_x = self.width() / 2.0
                x_pos = track_x - track_thickness / 2.0

                # Track background（纵向，底部到顶部）
                painter.setBrush(tm.alpha_of(tm.mid, 40))
                track_rect = QRectF(x_pos, margin, track_thickness, available)
                painter.drawRoundedRect(track_rect, track_thickness / 2.0, track_thickness / 2.0)

                # Track fill（从底部向上增长）
                fill_height = available * self._value
                fill_y = margin + available - fill_height
                painter.setBrush(tm.accent)
                fill_rect = QRectF(x_pos, fill_y, track_thickness, fill_height)
                painter.drawRoundedRect(fill_rect, track_thickness / 2.0, track_thickness / 2.0)

                # Ticks
                if self._tick_count > 0:
                    for i in range(self._tick_count + 1):
                        # tick 0 在底部，tick_count 在顶部
                        tick_y = margin + available - (available * i / self._tick_count)
                        filled = i / self._tick_count <= self._value
                        painter.setBrush(tm.alpha_of(tm.mid, 30) if filled else tm.alpha_of(tm.mid, 20))
                        painter.drawEllipse(int(track_x - 2), int(tick_y - 2), 4, 4)

            # Thumb — size animated via hover/drag progress
            scale = 1.0 + 0.1 * self._hover_progress + 0.1 * self._drag_progress
            thumb_r *= scale

            # Thumb shadow
            shadow_offset = 2.0
            painter.setOpacity(0.4)
            painter.setBrush(tm.alpha_of(tm.black, 40))
            painter.drawEllipse(QRectF(
                thumb_x - thumb_r, thumb_y - thumb_r + shadow_offset,
                thumb_r * 2, thumb_r * 2,
            ))

            # Thumb
            painter.setOpacity(1.0)
            painter.setBrush(tm.text)
            painter.drawEllipse(QRectF(
                thumb_x - thumb_r, thumb_y - thumb_r,
                thumb_r * 2, thumb_r * 2,
            ))
        finally:
            if painter.isActive():
                painter.end()