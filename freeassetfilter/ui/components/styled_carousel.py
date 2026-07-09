"""StyledCarousel — image/card carousel with slide/fade, arrows, indicators, autoplay."""

from typing import Optional

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, Signal, Property, QPropertyAnimation, QEasingCurve, QTimer, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QPaintEvent, QMouseEvent, QPainterPath, QRegion

from theme import tm
from components.paint_utils import draw_chevron

SIZE_H = {"sm": 120, "default": 200, "lg": 300}


class _Arrow(QPushButton):
    @property
    def _arrow_bg(self): return tm.alpha_of(tm.black, 50)

    @property
    def _arrow_hover(self): return tm.alpha_of(tm.black, 70)

    def __init__(self, direction: str, parent=None):
        super().__init__(parent)
        self._dir = direction
        self._hover = False
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:none;")

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, e):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            p.setBrush(self._arrow_hover if self._hover else self._arrow_bg)
            p.setPen(Qt.NoPen)
            p.drawEllipse(self.rect())
            d = "left" if self._dir == "prev" else "right"
            # Use a vertically-halved rect so draw_chevron's hs = min(w,h)/2 = 8
            r = QRectF(self.rect())
            r.setHeight(r.height() / 2.0)
            r.moveCenter(QRectF(self.rect()).center())
            draw_chevron(p, r, tm.text, direction=d, pen_width=2.0, t=0.25)


class _Dot(QPushButton):
    active = False
    def __init__(self, outside: bool = False, parent=None):
        super().__init__(parent)
        self._out = outside
        self._hover = False
        self._anim_width = 8.0
        self._anim = None
        self.setFixedSize(8, 8)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;border:none;")

    @property
    def _accent(self): return tm.accent

    @property
    def _dot_inactive(self): return tm.alpha_of(tm.text, 40)

    @property
    def _dot_hover(self): return tm.alpha_of(tm.text, 70)

    @property
    def _dot_out(self): return tm.alpha_of(tm.surface, 90)

    @property
    def _dot_border(self): return tm.alpha_of(tm.mid, 40)

    def _get_aw(self): return self._anim_width
    def _set_aw(self, w):
        self._anim_width = w
        iw = int(round(w))
        self.setFixedSize(iw, 8)
        self.update()
    anim_width = Property(float, _get_aw, _set_aw)

    def animate_to(self, target_active: bool, duration: int = 300):
        if self._anim:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        self.active = target_active
        self._anim = QPropertyAnimation(self, b"anim_width")
        self._anim.setDuration(duration)
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(24.0 if target_active else 8.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_done)
        self._anim.start()

    def _on_anim_done(self):
        self._anim = None

    def enterEvent(self, e): self._hover = True; self.update(); super().enterEvent(e)
    def leaveEvent(self, e): self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, e):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            if self.active:
                p.setPen(Qt.NoPen); p.setBrush(self._accent)
                r = self.height() / 2
                p.drawRoundedRect(self.rect(), r, r)
            elif self._out:
                p.setPen(QPen(self._dot_border, 1)); p.setBrush(self._dot_out)
                p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
            elif self._hover:
                p.setPen(Qt.NoPen); p.setBrush(self._dot_hover); p.drawEllipse(self.rect())
            else:
                p.setPen(Qt.NoPen); p.setBrush(self._dot_inactive); p.drawEllipse(self.rect())


class StyledCarousel(QWidget):
    """Carousel with slide/fade variants, arrows, dot indicators, and autoplay.

    Parameters
    ----------
    variant : "slide" | "fade"
    size : "sm" | "default" | "lg"
    autoplay_interval : int  (0 = disabled, default 3000)
    indicators : "inside" | "outside"

    Signals
    -------
    slide_changed(int)
    """
    slide_changed = Signal(int)

    # ── Theme color properties ─────────────────────────────────
    @property
    def ACCENT(self): return tm.accent

    @property
    def ARROW_BG(self): return tm.alpha_of(tm.black, 50)

    @property
    def ARROW_HOVER(self): return tm.alpha_of(tm.black, 70)

    @property
    def DOT_INACTIVE(self): return tm.alpha_of(tm.text, 40)

    @property
    def DOT_HOVER(self): return tm.alpha_of(tm.text, 70)

    @property
    def DOT_OUT(self): return tm.alpha_of(tm.surface, 90)

    @property
    def DOT_BORDER(self): return tm.alpha_of(tm.mid, 40)

    def __init__(self, variant="slide", size="default", autoplay_interval=3000, indicators="inside", parent=None):
        super().__init__(parent)
        self._v = variant
        self._ind_pos = indicators
        self._slides: list[QWidget] = []
        self._cur = 0
        self._anim = False
        self._h = SIZE_H.get(size, 200)
        self.setFixedHeight(self._h)

        self._vp = QWidget(self)
        self._vp.setAttribute(Qt.WA_StyledBackground)
        self._vp.setStyleSheet("background:transparent;")

        self._track: Optional[QWidget] = None
        if variant == "slide":
            self._track = QWidget(self._vp)
            self._track.setStyleSheet("background:transparent;")
            lo = QHBoxLayout(self._track)
            lo.setContentsMargins(0, 0, 0, 0); lo.setSpacing(0)
            self._sa = QPropertyAnimation(self._track, b"pos")
            self._sa.setDuration(500); self._sa.setEasingCurve(QEasingCurve.OutCubic)
            self._sa.finished.connect(self._finish)

        self._fc: Optional[QWidget] = None
        self._fa: Optional[QPropertyAnimation] = None
        if variant == "fade":
            self._fc = QWidget(self._vp)
            self._fc.setStyleSheet("background:transparent;")

        self._prev = _Arrow("prev", self._vp)
        self._next = _Arrow("next", self._vp)
        self._prev.clicked.connect(self.prev)
        self._next.clicked.connect(self.next)

        self._dw = QWidget(self if indicators == "outside" else self._vp)
        self._dw.setAttribute(Qt.WA_StyledBackground)
        self._dw.setStyleSheet("background:transparent;")
        dl = QHBoxLayout(self._dw)
        dl.setContentsMargins(0, 0, 0, 0); dl.setSpacing(8); dl.setAlignment(Qt.AlignCenter)
        self._dots: list[_Dot] = []
        self._interval = autoplay_interval
        self._timer = QTimer(self)
        self._timer.setInterval(autoplay_interval)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WA_Hover, True)

    # ── Public ─────────────────────────────────────────────────

    def add_slide(self, w: QWidget) -> int:
        idx = len(self._slides)
        if self._v == "slide" and self._track:
            self._track.layout().addWidget(w)
        elif self._fc:
            w.setParent(self._fc); w.show()
            e = QGraphicsOpacityEffect(w)
            e.setOpacity(1.0 if idx == 0 else 0.0)
            w.setGraphicsEffect(e)
        self._slides.append(w)
        d = _Dot(outside=self._ind_pos == "outside")
        d.clicked.connect(lambda checked, i=idx: self.set_current_index(i))
        self._dw.layout().addWidget(d)
        self._dots.append(d)
        if idx == 0:
            d.animate_to(True, duration=0)  # immediate, no animation
        self._layout()
        return idx

    def set_current_index(self, idx: int):
        if self._anim or not self._slides: return
        n = len(self._slides)
        idx = max(0, min(idx, n - 1))
        if idx == self._cur: return
        self._anim = True
        prev = self._cur; self._cur = idx
        # Start dot animation in parallel with slide transition
        for i, d in enumerate(self._dots):
            d.animate_to(i == idx)
        w = self._vp.width()
        if w <= 0: self._anim = False; self._done(idx); return
        if self._v == "slide" and self._track:
            self._sa.stop()
            self._sa.setStartValue(self._track.pos())
            self._sa.setEndValue(QPoint(-idx * w, 0))
            self._sa.start()
        elif self._v == "fade" and self._fc:
            self._fade(prev, idx)

    def next(self):
        if not self._slides: return
        n = self._cur + 1
        if n >= len(self._slides): n = 0
        self.set_current_index(n)

    def prev(self):
        if not self._slides: return
        p = self._cur - 1
        if p < 0: p = len(self._slides) - 1
        self.set_current_index(p)

    @property
    def current_index(self) -> int: return self._cur

    def start_autoplay(self):
        if self._interval > 0 and len(self._slides) > 1: self._timer.start()

    def stop_autoplay(self): self._timer.stop()

    @property
    def autoplay_enabled(self) -> bool: return self._timer.isActive()

    # ── Internal ───────────────────────────────────────────────

    def _fade(self, fi: int, ti: int):
        os, ns = self._slides[fi], self._slides[ti]
        oe = os.graphicsEffect(); ne = ns.graphicsEffect()
        if oe is None or ne is None: self._anim = False; self._done(ti); return
        oa = QPropertyAnimation(oe, b"opacity")
        oa.setDuration(400); oa.setStartValue(1.0); oa.setEndValue(0.0); oa.setEasingCurve(QEasingCurve.OutCubic)
        na = QPropertyAnimation(ne, b"opacity")
        na.setDuration(400); na.setStartValue(0.0); na.setEndValue(1.0); na.setEasingCurve(QEasingCurve.OutCubic)
        oa.finished.connect(lambda: na.start())
        na.finished.connect(self._finish)
        self._fa = oa; oa.start()

    def _finish(self):
        self._anim = False
        self._done(self._cur)

    def _done(self, idx: int):
        for i, d in enumerate(self._dots):
            d.animate_to(i == idx)
        has = len(self._slides) > 1
        self._prev.setVisible(has); self._next.setVisible(has)
        self.slide_changed.emit(idx)

    def _tick(self):
        if not self._anim and self._slides: self.next()

    def enterEvent(self, e):
        if self._timer.isActive(): self._timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._interval > 0 and len(self._slides) > 1: self._timer.start()
        super().leaveEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e); self._layout()

    def _layout(self):
        w = self.width(); h = self._h
        vph = h - 28 if self._ind_pos == "outside" else h
        self._vp.setGeometry(0, 0, w, vph)
        pa = QPainterPath(); pa.addRoundedRect(QRectF(self._vp.rect()), 8, 8)
        self._vp.setMask(QRegion(pa.toFillPolygon().toPolygon()))

        if self._track and self._slides:
            self._track.setGeometry(0, 0, w * len(self._slides), vph)
            self._track.move(-self._cur * w, 0)
            for s in self._slides: s.setFixedSize(w, vph)
        if self._fc:
            self._fc.setGeometry(0, 0, w, vph)
            for s in self._slides: s.setFixedSize(w, vph)

        ay = vph // 2 - 16
        self._prev.move(12, ay); self._next.move(w - 44, ay)

        iy = vph + 4 if self._ind_pos == "outside" else vph - 20
        dw = sum(24 if d.active else 8 for d in self._dots) + max(0, len(self._dots) - 1) * 8
        self._dw.setGeometry((w - dw) // 2 if dw < w else 0, iy, min(dw + 16, w), 8)

    def paintEvent(self, e):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen); p.setBrush(tm.alpha_of(tm.surface, 85))
            p.drawRoundedRect(self.rect(), 8, 8)
