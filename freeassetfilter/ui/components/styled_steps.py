# allow: SIZE_OK — config data tables (~60 LOC) + two tightly-coupled
# classes (StepWidget + StyledSteps) that form a single component and
# should not be split across files.

"""StyledSteps component - step progress indicator matching web steps UI.

Provides a multi-step progress indicator with states (pending, current,
completed, error), multiple variants (default numbered, dot, icon),
horizontal/vertical orientation, size variants (sm/default/lg), and
click interaction.
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRectF, QPoint, QEvent
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QPaintEvent,
    QFont,
    QMouseEvent,
    QFontMetrics,
)

from theme import tm
from components.icon_utils import render_icon

# ── Design tokens ─────────────────────────────────────────────────────

SIZE_CONFIG = {
    "sm": {"indicator": 26, "number": 11, "title": 12, "desc": 10, "gap": 4, "pad": 8},
    "default": {"indicator": 32, "number": 13, "title": 13, "desc": 12, "gap": 6, "pad": 12},
    "lg": {"indicator": 40, "number": 16, "title": 15, "desc": 13, "gap": 8, "pad": 16},
}

DOT_SIZE = {"sm": 10, "default": 12, "lg": 14}

_CONNECTOR_WIDTH = 2
_INDICATOR_TOP_GAP = 4  # px from widget top to indicator circle top edge


class StepWidget(QWidget):
    """A single step item with a painted indicator and content labels.

    Paints its own indicator circle (numbered, dot, or icon) and provides
    title/description labels arranged according to orientation.
    """

    clicked = Signal(int)  # emits step index

    def __init__(
        self,
        title: str = "",
        description: str = "",
        state: str = "pending",
        variant: str = "default",
        size: str = "default",
        index: int = 0,
        icon_name: str = "",
        orientation: str = "horizontal",
        parent=None,
    ):
        super().__init__(parent)
        self._title = title
        self._description = description
        self._state = state
        self._variant = variant
        self._size = size
        self._index = index
        self._icon_name = icon_name
        self._orientation = orientation
        self._hovered = False

        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._build_ui()

    # ── Theme helpers ────────────────────────────────────────────

    @staticmethod
    def _get_steps_colors() -> dict[str, tuple[QColor, QColor, QColor]]:
        return {
            "pending": (tm.alpha_of(tm.mid, 40), tm.alpha_of(tm.mid, 40), tm.alpha_of(tm.mid, 60)),
            "current": (tm.accent, tm.alpha_of(tm.accent, 10), tm.accent),
            "completed": (tm.accent, tm.accent, tm.text),
            "error": (tm.danger, tm.alpha_of(tm.danger, 10), tm.danger),
        }

    # ── Configuration accessors ────────────────────────────────────

    def _cfg(self) -> dict:
        return SIZE_CONFIG.get(self._size, SIZE_CONFIG["default"])

    def _colors(self) -> tuple[QColor, QColor, QColor]:
        return self._get_steps_colors().get(self._state, self._get_steps_colors()["pending"])

    # ── UI construction ────────────────────────────────────────────

    def _build_ui(self):
        # Remove the previous layout (if any) before creating a new one
        # when size/orientation changes, to suppress "already has a layout".
        old = self.layout()
        if old is not None:
            old.setParent(None)
            old.deleteLater()

        cfg = self._cfg()
        pad = cfg["pad"]
        d = self.indicator_diameter()

        if self._orientation == "horizontal":
            # Reserve the top area for the painted indicator
            indicator_area_height = _INDICATOR_TOP_GAP + d + 4

            layout = QVBoxLayout(self)
            layout.setContentsMargins(pad, indicator_area_height, pad, pad)
            layout.setSpacing(cfg["gap"])

            # Title — centered
            self._title_lbl = QLabel(self._title)
            f = QFont("Microsoft YaHei UI", cfg["title"])
            f.setWeight(QFont.Weight.Medium)
            self._title_lbl.setFont(f)
            self._title_lbl.setAlignment(Qt.AlignCenter)
            self._title_lbl.setWordWrap(True)
            layout.addWidget(self._title_lbl)

            # Description — centered
            self._desc_lbl = QLabel(self._description)
            self._desc_lbl.setFont(QFont("Microsoft YaHei UI", cfg["desc"]))
            self._desc_lbl.setAlignment(Qt.AlignCenter)
            self._desc_lbl.setWordWrap(True)
            layout.addWidget(self._desc_lbl)

            layout.addStretch()

        else:  # vertical
            # Reserve the left area for the painted indicator
            indicator_area_width = pad + d + 4

            layout = QHBoxLayout(self)
            layout.setContentsMargins(indicator_area_width, pad, pad, pad)
            layout.setSpacing(12)

            cl = QVBoxLayout()
            cl.setSpacing(2)

            self._title_lbl = QLabel(self._title)
            f = QFont("Microsoft YaHei UI", cfg["title"])
            f.setWeight(QFont.Weight.Medium)
            self._title_lbl.setFont(f)
            cl.addWidget(self._title_lbl)

            self._desc_lbl = QLabel(self._description)
            self._desc_lbl.setFont(QFont("Microsoft YaHei UI", cfg["desc"]))
            cl.addWidget(self._desc_lbl)

            cl.addStretch()
            layout.addLayout(cl, stretch=1)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    # ── Indicator geometry helpers ─────────────────────────────────

    def indicator_diameter(self) -> int:
        if self._variant == "dot":
            return DOT_SIZE.get(self._size, 12)
        return self._cfg()["indicator"]

    def indicator_center(self) -> QPoint:
        """Return indicator centre in widget-local coordinates."""
        d = self.indicator_diameter()
        pad = self._cfg()["pad"]
        if self._orientation == "horizontal":
            cx = self.width() // 2
            cy = _INDICATOR_TOP_GAP + d // 2
            return QPoint(cx, cy)
        else:
            cx = pad + d // 2
            cy = self.height() // 2
            return QPoint(cx, cy)

    # ── Paint ──────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing)

        border, bg, text = self._colors()
        d = self.indicator_diameter()
        c = self.indicator_center()
        r = d / 2.0
        rect = QRectF(c.x() - r, c.y() - r, d, d)

        if self._variant == "dot":
            painter.setPen(Qt.NoPen)
            painter.setBrush(border)
            painter.drawEllipse(rect)

        elif self._variant == "icon":
            painter.setPen(QPen(border, 2))
            painter.setBrush(bg)
            painter.drawEllipse(rect)
            if self._icon_name:
                icon_sz = d * 0.55
                icon_rect = QRectF(
                    c.x() - icon_sz / 2.0,
                    c.y() - icon_sz / 2.0,
                    icon_sz,
                    icon_sz,
                )
                render_icon(painter, self._icon_name, icon_rect, text, 1.5)

        else:  # default (numbered)
            if self._state == "completed":
                # Filled green circle with white checkmark
                painter.setPen(Qt.NoPen)
                painter.setBrush(bg)
                painter.drawEllipse(rect)
                check_sz = d * 0.5
                check_rect = QRectF(
                    c.x() - check_sz / 2.0,
                    c.y() - check_sz / 2.0,
                    check_sz,
                    check_sz,
                )
                render_icon(painter, "checkmark", check_rect, text, 2.0)
            else:
                # Circle with border and number
                painter.setPen(QPen(border, 2))
                painter.setBrush(bg)
                painter.drawEllipse(rect)

                f = QFont("Microsoft YaHei UI", self._cfg()["number"])
                f.setWeight(QFont.Weight.Medium)
                painter.setFont(f)
                painter.setPen(text)
                painter.drawText(rect, Qt.AlignCenter, str(self._index + 1))

        # Hover subtle ring
        if self._hovered:
            painter.setPen(QPen(QColor(border.red(), border.green(), border.blue(), 60), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect.adjusted(-3, -3, 3, 3))

    # ── Mouse interaction ──────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._index)
            event.accept()
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event: QEvent):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ── State property ─────────────────────────────────────────────

    @property
    def step_state(self) -> str:
        return self._state

    @step_state.setter
    def step_state(self, value: str):
        if value in self._get_steps_colors():
            self._state = value
            self.update()


class StyledSteps(QWidget):
    """A step progress indicator.

    Manages a sequence of StepWidgets arranged horizontally or vertically
    with connector lines between indicators.
    """

    step_clicked = Signal(int)  # emitted when a step is clicked

    valid_states = frozenset({"pending", "current", "completed", "error"})
    valid_variants = frozenset({"default", "dot", "icon"})
    valid_sizes = frozenset({"sm", "default", "lg"})
    valid_orientations = frozenset({"horizontal", "vertical"})

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(parent)
        self._steps: list[StepWidget] = []
        self._current_step: int = -1
        self._variant: str = "default"
        self._size: str = "default"
        self._orientation: str = "horizontal"
        self._icon_name: str = ""

        self.setMouseTracking(True)

        # Layout is created lazily in _ensure_layout() / add_step()
        # to avoid the access violation that occurs when swapping
        # layouts via delete-later + create-new in the orientation setter.
        self._layout = None  # QVBoxLayout or QHBoxLayout, created lazily

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    # ── Layout helper ──────────────────────────────────────────────

    def _ensure_layout(self):
        """Create the layout matching current orientation if needed."""
        if self._layout is not None:
            return
        if self._orientation == "horizontal":
            self._layout = QHBoxLayout(self)
        else:
            self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    # ── Public API ─────────────────────────────────────────────────

    def add_step(
        self,
        title: str,
        description: str = "",
        state: str = "pending",
    ) -> int:
        """Add a step.  Returns its index."""
        if state not in self.valid_states:
            state = "pending"

        self._ensure_layout()
        idx = len(self._steps)
        widget = StepWidget(
            title=title,
            description=description,
            state=state,
            variant=self._variant,
            size=self._size,
            index=idx,
            icon_name=self._icon_name,
            orientation=self._orientation,
            parent=self,
        )
        widget.clicked.connect(self._on_step_clicked)
        self._steps.append(widget)
        self._layout.addWidget(widget)
        return idx

    def clear(self):
        """Remove all steps."""
        if self._layout is None:
            return
        for w in self._steps:
            self._layout.removeWidget(w)
            w.deleteLater()
        self._steps.clear()
        self._current_step = -1

    # ── Properties ─────────────────────────────────────────────────

    @property
    def current_step(self) -> int:
        return self._current_step

    @current_step.setter
    def current_step(self, value: int):
        """Set the active step index.

        Steps before *value* become ``completed``, step *value* becomes
        ``current``, and steps after remain ``pending`` (unless they are
        explicitly ``error`` — those are preserved).
        """
        value = max(-1, min(value, len(self._steps) - 1))
        self._current_step = value
        for i, w in enumerate(self._steps):
            if w._state == "error":
                continue  # preserve explicit error
            if i < value:
                w.step_state = "completed"
            elif i == value:
                w.step_state = "current"
            else:
                w.step_state = "pending"
        self.update()

    @property
    def variant(self) -> str:
        return self._variant

    @variant.setter
    def variant(self, value: str):
        if value not in self.valid_variants:
            return
        self._variant = value
        for w in self._steps:
            w._variant = value
            w.update()
        self.update()

    @property
    def size(self) -> str:
        return self._size

    @size.setter
    def size(self, value: str):
        if value not in self.valid_sizes:
            return
        self._size = value
        for w in self._steps:
            w._size = value
            w._build_ui()
            w.update()
        self.update()

    @property
    def orientation(self) -> str:
        return self._orientation

    @orientation.setter
    def orientation(self, value: str):
        if value not in self.valid_orientations or value == self._orientation:
            return
        self._orientation = value

        if not self._steps:
            # No steps yet — discard any unused layout; _ensure_layout
            # will create the correct type on first add_step.
            if self._layout is not None:
                old = self._layout
                self._layout = None
                old.setParent(None)
                old.deleteLater()
            return

        # Steps exist — rebuild layout with new orientation.
        # Remove step widgets from old layout first so they aren't
        # double-parented during the swap.
        for w in self._steps:
            w._orientation = self._orientation
            w._build_ui()
            self._layout.removeWidget(w)

        old = self._layout
        self._layout = None
        old.setParent(None)
        old.deleteLater()

        self._ensure_layout()
        for w in self._steps:
            self._layout.addWidget(w)
            w.update()
        self.update()

    @property
    def icon_name(self) -> str:
        return self._icon_name

    @icon_name.setter
    def icon_name(self, value: str):
        self._icon_name = value
        if self._variant == "icon":
            for w in self._steps:
                w._icon_name = value
                w.update()
            self.update()

    # ── Theme helpers ─────────────────────────────────────────────

    @property
    def _connector_pending(self) -> QColor:
        return tm.alpha_of(tm.mid, 40)

    @property
    def _connector_completed(self) -> QColor:
        return tm.accent

    # ── Click handling ─────────────────────────────────────────────

    def _on_step_clicked(self, index: int):
        self.step_clicked.emit(index)

    # ── Connector line painting ────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        super().paintEvent(event)
        if len(self._steps) < 2:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing)

        for i in range(len(self._steps) - 1):
            w1 = self._steps[i]
            w2 = self._steps[i + 1]

            # Determine connector colour
            if w1._state == "completed":
                clr = self._connector_completed
            else:
                clr = self._connector_pending

            painter.setPen(QPen(clr, _CONNECTOR_WIDTH, Qt.SolidLine, Qt.RoundCap))

            c1 = w1.indicator_center()  # widget-local
            c2 = w2.indicator_center()

            g1 = w1.mapTo(self, c1)  # container coords
            g2 = w2.mapTo(self, c2)

            d = w1.indicator_diameter()
            r = d / 2.0

            if self._orientation == "horizontal":
                # Horizontal line from right of indicator1 to left of indicator2
                x1 = g1.x() + r
                x2 = g2.x() - r
                y = g1.y()
                painter.drawLine(int(x1), int(y), int(x2), int(y))
            else:
                # Vertical line from bottom of indicator1 to top of indicator2
                y1 = g1.y() + r
                y2 = g2.y() - r
                x = g1.x()
                painter.drawLine(int(x), int(y1), int(x), int(y2))
