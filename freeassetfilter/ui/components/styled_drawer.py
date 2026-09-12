"""Styled Drawer component — slides in from right, left, or top edge.

Two physical layers: (1) backdrop QWidget covering the entire screen with
semi-transparent black fill faded via a painted opacity-property animation;
(2) drawer panel QWidget sliding via QPropertyAnimation on pos().

Signals: opened(), closed()
Close triggers: backdrop click, close (×) button, Escape key.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QApplication,
)
from PySide6.QtCore import (
    Qt, Signal, Property, QPropertyAnimation, QEasingCurve, QPoint, QEvent,
)
from PySide6.QtGui import QFont, QCursor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QColor

from theme import tm
from components.paint_utils import render_soft_shadow
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss

SIZE_CONFIG: dict[str, dict[str, int]] = {
    "sm": {"right": 280, "left": 280, "top": 240},
    "default": {"right": 400, "left": 400, "top": 300},
    "lg": {"right": 560, "left": 560, "top": 400},
}
VALID_ORIENTATIONS = ("right", "left", "top")
ANIM_MS = 250


class _DrawerBackdrop(QWidget):
    """Full-area backdrop: translucent fill plus the panel edge glow.

    ``backdrop_opacity`` (0.0–1.0) drives both the black fill alpha and
    the glow strength; the drawer open/close transitions animate it with
    the same duration/easing as before. The glow is a pre-baked
    soft-shadow bitmap drawn around the panel's *live* geometry, so it
    tracks the slide animation with one blit per frame — no effect
    pipeline on the paint path.
    """

    _GLOW_PAD: int = 24

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._backdrop_opacity: float = 0.0
        self._fill_base = tm.alpha_of(tm.black, 60)
        self._glow_color = tm.with_alpha(tm.black, 112)
        self._panel: Optional[QWidget] = None

    def set_panel(self, panel: QWidget) -> None:
        """Attach the panel whose silhouette the glow follows."""
        self._panel = panel

    def _get_backdrop_opacity(self) -> float:
        return self._backdrop_opacity

    def _set_backdrop_opacity(self, value: float) -> None:
        self._backdrop_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    backdrop_opacity = Property(float, _get_backdrop_opacity, _set_backdrop_opacity)

    def set_backdrop_opacity(self, value: float) -> None:
        """Set the backdrop opacity directly (0.0 = invisible)."""
        self._set_backdrop_opacity(value)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            fill = QColor(self._fill_base)
            fill.setAlphaF(
                self._fill_base.alphaF() * self._backdrop_opacity
            )
            painter.fillRect(self.rect(), fill)
            if (
                self._panel is not None
                and self._backdrop_opacity > 0.01
                and self._panel.isVisible()
            ):
                geom = self._panel.geometry()
                glow = render_soft_shadow(
                    geom.width(), geom.height(), 0, 60,
                    self._glow_color, self._GLOW_PAD,
                )
                if not glow.isNull():
                    painter.setOpacity(self._backdrop_opacity)
                    painter.drawPixmap(
                        geom.x() - self._GLOW_PAD,
                        geom.y() - self._GLOW_PAD + 10,
                        glow,
                    )
                    painter.setOpacity(1.0)
        finally:
            painter.end()


class StyledDrawer(QWidget):
    """Drawer component that slides in from right, left, or top edge.

    Orientation: ``'right'``, ``'left'``, ``'top'`` (no ``'bottom'``).
    Sizes: ``'sm'``, ``'default'``, ``'lg'``.
    Right/left drawers vary in *width*; top drawers vary in *height*.
    """

    opened = Signal()
    closed = Signal()

    def __init__(
        self,
        orientation: str = "right",
        size: str = "default",
        title: str = "",
        body_widget: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
        bare: bool = False,
    ) -> None:
        """If *bare* is True, the drawer contains no header, body scroll-area,
        or footer — only the raw *body_widget* (if any) is placed directly
        in the panel.  Backdrop, animations, and Escape-key close still work."""
        super().__init__(parent)

        self._orientation = orientation if orientation in VALID_ORIENTATIONS else "right"
        self._size = size if size in SIZE_CONFIG else "default"
        self._is_open = False
        self._animating = False
        self._bare = bare

        self.setObjectName("StyledDrawer")
        self.installEventFilter(self)

        # When no parent, behave as a full-screen overlay window
        if parent is None:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground)

        # Container geometry (parent widget or full-screen fallback)
        self._update_container_geom()
        self.setGeometry(0, 0, self._cw, self._ch)

        # ── Layer 1: Backdrop (self-painted fill + panel glow) ──
        self._backdrop = _DrawerBackdrop(self)
        self._backdrop.setObjectName("DrawerBackdrop")
        self._backdrop.setGeometry(0, 0, self._cw, self._ch)
        self._backdrop.mousePressEvent = self._on_backdrop_clicked  # type: ignore[method-assign]

        # ── Layer 2: Drawer panel ──
        pw, ph = self._get_panel_size()
        self._panel = QWidget(self)
        self._panel.setObjectName("DrawerPanel")

        _border_clr = tm.mid.name()
        _border_map = {
            "right": f"border-left: 1px solid {_border_clr};",
            "left": f"border-right: 1px solid {_border_clr};",
            "top": f"border-bottom: 1px solid {_border_clr};",
        }
        register_widget_qss(self._panel,(
            f"#DrawerPanel {{ background-color: {tm.surface.name()}; {_border_map.get(self._orientation, '')}}}"
        ))

        # Panel edge glow is painted by the backdrop around the panel's
        # live geometry (pre-baked bitmap, no graphics effect).
        self._backdrop.set_panel(self._panel)

        self._start_pos, self._end_pos = self._get_anim_positions(pw, ph)
        self._panel.setGeometry(self._start_pos.x(), self._start_pos.y(), pw, ph)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        if bare:
            if body_widget is not None:
                body_widget.setParent(self._panel)
                panel_layout.addWidget(body_widget)
        else:
            self._build_header(title, panel_layout)
            self._build_body(body_widget, panel_layout)
            self._build_footer(panel_layout)
        self._panel.raise_()

        # ── Animations ──
        self._backdrop_anim = QPropertyAnimation(self._backdrop, b"backdrop_opacity")
        self._backdrop_anim.setDuration(ANIM_MS)
        self._backdrop_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._backdrop_anim.valueChanged.connect(lambda _v: self._backdrop.update())

        self._slide_anim = QPropertyAnimation(self._panel, b"pos")
        self._slide_anim.setDuration(ANIM_MS)
        self._slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._slide_anim.finished.connect(self._on_slide_finished)
        self._slide_anim.valueChanged.connect(lambda _v: self._backdrop.update())

    # ── Container geometry (parent widget, or full-screen fallback) ──

    def _update_container_geom(self) -> None:
        """Sync self._cw / self._ch from parent widget or primary screen."""
        parent = self.parent()
        if parent is not None and parent.isWidgetType():
            self._cw = parent.width()
            self._ch = parent.height()
        else:
            screen = QApplication.primaryScreen()
            geom = screen.geometry()
            self._cw = geom.width()
            self._ch = geom.height()

    # ── Sizing ──

    def _get_panel_size(self) -> tuple[int, int]:
        dim = SIZE_CONFIG[self._size]
        if self._orientation in ("right", "left"):
            return dim[self._orientation], self._ch
        return self._cw, dim["top"]

    def _get_anim_positions(self, pw: int, ph: int) -> tuple[QPoint, QPoint]:
        cw = self._cw
        if self._orientation == "right":
            return QPoint(cw, 0), QPoint(cw - pw, 0)
        if self._orientation == "left":
            return QPoint(-pw, 0), QPoint(0, 0)
        return QPoint(0, -ph), QPoint(0, 0)

    # ── Header ──

    def _build_header(self, title: str, parent_layout: QVBoxLayout) -> None:
        header = QWidget()
        header.setObjectName("DrawerHeader")
        header.setContentsMargins(0, 0, 0, 0)
        register_widget_qss(header,(f"#DrawerHeader {{ background: transparent; border-bottom: 1px solid {tm.alpha_of(tm.mid, 30).name()}; }}"))

        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(24, 20, 12, 20)
        hdr_layout.setSpacing(0)

        if title:
            label = QLabel(title)
            font = QFont("Microsoft YaHei UI", 16)
            font.setWeight(QFont.Weight.DemiBold)
            label.setFont(font)
            register_widget_qss(label,(f"color: {tm.text.name()}; background: transparent; border: none;"))
            hdr_layout.addWidget(label, stretch=1)
        else:
            hdr_layout.addStretch(1)

        hdr_layout.addSpacing(12)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(QCursor(Qt.PointingHandCursor))
        register_widget_qss(close_btn,(
            f"QPushButton {{ background: transparent; border: none; border-radius: 6px;"
            f" color: {tm.mid.name()}; font-size: 18px; font-weight: 300; }}"
            f"QPushButton:hover {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; }}"
        ))
        close_btn.clicked.connect(self.close_drawer)
        hdr_layout.addWidget(close_btn, alignment=Qt.AlignTop)

        parent_layout.addWidget(header)

    # ── Body ──

    def _build_body(self, content: Optional[QWidget], parent_layout: QVBoxLayout) -> None:
        scroll = QScrollArea()
        scroll.setObjectName("DrawerBody")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        register_widget_qss(scroll,("#DrawerBody { border: none; background: transparent; }"))
        register_widget_qss(scroll.viewport(),("background: transparent;"))

        wrapper = QWidget()
        register_widget_qss(wrapper,("background: transparent;"))
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(24, 16, 24, 16)
        wrapper_layout.setSpacing(0)
        if content is not None:
            content.setParent(wrapper)
            wrapper_layout.addWidget(content)
        wrapper_layout.addStretch()

        scroll.setWidget(wrapper)
        parent_layout.addWidget(scroll, stretch=1)

    # ── Footer ──

    def _build_footer(self, parent_layout: QVBoxLayout) -> None:
        footer = QWidget()
        footer.setObjectName("DrawerFooter")
        footer.setContentsMargins(0, 0, 0, 0)
        register_widget_qss(footer,(f"#DrawerFooter {{ background: transparent; border-top: 1px solid {tm.alpha_of(tm.mid, 30).name()}; }}"))

        self._footer_layout = QHBoxLayout(footer)
        self._footer_layout.setContentsMargins(24, 16, 24, 16)
        self._footer_layout.setSpacing(10)
        self._footer_layout.addStretch()
        parent_layout.addWidget(footer)

    @property
    def footer_layout(self) -> QHBoxLayout:
        return self._footer_layout

    # ── Backdrop click ──

    def _on_backdrop_clicked(self, event: QMouseEvent) -> None:
        if self._is_open and not self._animating:
            self.close_drawer()

    # ── Event filter (Escape) ──

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.KeyPress and self._is_open:
            ke = event  # type: QKeyEvent
            if ke.key() == Qt.Key_Escape:
                self.close_drawer()
                return True
        return super().eventFilter(obj, event)

    # ── Public API ──

    def open_drawer(self) -> None:
        if self._is_open or self._animating:
            return
        self._is_open = True
        self._animating = True

        self._update_container_geom()
        self.setGeometry(0, 0, self._cw, self._ch)
        self._backdrop.setGeometry(0, 0, self._cw, self._ch)

        pw, ph = self._get_panel_size()
        self._start_pos, self._end_pos = self._get_anim_positions(pw, ph)
        self._panel.resize(pw, ph)
        self._panel.move(self._start_pos)
        self._panel.raise_()
        self.show()
        self.raise_()

        self._backdrop_anim.setStartValue(0.0)
        self._backdrop_anim.setEndValue(1.0)
        self._backdrop_anim.start()

        self._slide_anim.setStartValue(self._start_pos)
        self._slide_anim.setEndValue(self._end_pos)
        self._slide_anim.start()

    def close_drawer(self) -> None:
        if not self._is_open or self._animating:
            return
        self._is_open = False
        self._animating = True

        self._backdrop_anim.setStartValue(1.0)
        self._backdrop_anim.setEndValue(0.0)
        self._backdrop_anim.start()

        self._slide_anim.setStartValue(self._panel.pos())
        self._slide_anim.setEndValue(self._start_pos)
        self._slide_anim.start()

    # ── Animation callback ──

    def _on_slide_finished(self) -> None:
        self._animating = False
        if self._is_open:
            self.opened.emit()
        else:
            self.hide()
            self.closed.emit()
