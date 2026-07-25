"""Styled Color Picker component - matches web color-picker exactly.

Features:
  - Preview square + hex input line
  - Click preview → popup panel with full controls
  - 2D saturation/value picker with gradient overlay
  - Hue slider with full rainbow gradient
  - Alpha slider with checkered background
  - RGBA numeric input fields (QSpinBox 0-255)
  - Preset swatches row (12 colors)
  - Hex input round-trip
  - Disabled state
"""

from __future__ import annotations

from colorsys import hsv_to_rgb, rgb_to_hsv

from theme import tm
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QEvent, QPoint, QRect, QTimer, QSize
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QBrush,
    QLinearGradient,
    QPainterPath,
    QPaintEvent,
    QMouseEvent,
    QFont,
    QPixmap,
    QCursor,
    QRegion,
    QTransform,
)
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QSpinBox,
    QApplication,
)

# ── Design tokens (dark theme, matching web) ──────────────────────

def BG_INPUT() -> QColor:
    """Lazy-evaluated background color from theme manager."""
    return tm.fill
FONT_FAMILY = "Microsoft YaHei UI"

PRESET_COLORS: list[str] = [
    "#FF0000", "#FF8800", "#FFFF00", "#00FF00",
    "#0088FF", "#0000FF", "#8800FF", "#FF00FF",
    "#FFFFFF", "#888888", "#000000", "#07C160",
]


def _font(size: int) -> QFont:
    f = QFont(FONT_FAMILY, size)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def _hex_from_rgba(r: int, g: int, b: int, a: int = 255) -> str:
    if a < 255:
        return f"#{r:02X}{g:02X}{b:02X}{a:02X}"
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgba_from_hex(hex_str: str) -> tuple[int, int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return r, g, b, 255
    if len(h) == 8:
        r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
        return r, g, b, a
    return 255, 255, 255, 255  # fallback


# ── 2D Saturation / Value Picker ──────────────────────────────────

class _SatValWidget(QWidget):
    """2D square: X = saturation (0→white, 1→pure hue), Y = value (0→black, 1→bright)."""

    sat_val_changed = Signal(int, int)  # saturation 0-255, value 0-255

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(256, 160)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self._hue = 120  # degrees 0-360
        self._saturation = 255
        self._value = 255
        self._dragging = False

    @property
    def _border_color(self):
        return tm.mid

    def set_hue(self, hue: int):
        self._hue = hue % 360
        self.update()

    def set_sat_val(self, sat: int, val: int):
        self._saturation = max(0, min(255, sat))
        self._value = max(0, min(255, val))
        self.update()

    def set_color(self, hue: int, sat: int, val: int):
        self._hue = hue % 360
        self._saturation = max(0, min(255, sat))
        self._value = max(0, min(255, val))
        self.update()

    def cursor_pos(self) -> tuple[float, float]:
        """Return (x, y) cursor position in widget coordinates."""
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return (0, 0)
        x = self._saturation / 255.0 * w
        y = (1.0 - self._value / 255.0) * h
        return (x, y)

    def _pos_to_sat_val(self, pos: QPointF) -> tuple[int, int]:
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return (0, 0)
        sat = int(max(0, min(1.0, pos.x() / w)) * 255)
        val = int(max(0, min(1.0, 1.0 - pos.y() / h)) * 255)
        return (sat, val)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # Clipped rounded rect
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 6, 6)
        painter.setClipPath(path)

        # Step 1: Fill with pure hue
        hue_color = QColor.fromHsv(self._hue, 255, 255)
        painter.fillRect(self.rect(), hue_color)

        # Step 2: Horizontal white → transparent (saturation, left→right)
        w_grad = QLinearGradient(0, 0, w, 0)
        w_grad.setColorAt(0.0, QColor(255, 255, 255))
        w_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), w_grad)

        # Step 3: Vertical transparent → black (value, top→bottom)
        b_grad = QLinearGradient(0, 0, 0, h)
        b_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        b_grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.fillRect(self.rect(), b_grad)

        painter.setClipping(False)

        # Step 4: Border
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 6, 6)

        # Step 5: Cursor circle
        cx, cy = self.cursor_pos()
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), 6, 6)
        painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
        painter.drawEllipse(QPointF(cx, cy), 7, 7)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            sat, val = self._pos_to_sat_val(event.position())
            self._saturation = sat
            self._value = val
            self.update()
            self.sat_val_changed.emit(sat, val)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            sat, val = self._pos_to_sat_val(event.position())
            self._saturation = sat
            self._value = val
            self.update()
            self.sat_val_changed.emit(sat, val)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            event.accept()


# ── Hue Slider ────────────────────────────────────────────────────

class _HueSlider(QWidget):
    """Horizontal hue slider with full rainbow gradient."""

    hue_changed = Signal(int)  # 0-360

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._hue = 120
        self._dragging = False

    @property
    def _border_color(self):
        return tm.mid

    def set_hue(self, hue: int):
        self._hue = hue % 360
        self.update()

    def _hue_from_pos(self, x: float) -> int:
        w = self.width()
        if w <= 0:
            return 0
        return int(max(0, min(359, x / w * 360)))

    def _thumb_x(self) -> float:
        w = self.width()
        if w <= 0:
            return 0
        return self._hue / 360.0 * w

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        gradient = QLinearGradient(0, 0, w, 0)
        stops = [
            (0.00, QColor("#ff0000")),
            (0.17, QColor("#ffff00")),
            (0.33, QColor("#00ff00")),
            (0.50, QColor("#00ffff")),
            (0.67, QColor("#0000ff")),
            (0.83, QColor("#ff00ff")),
            (1.00, QColor("#ff0000")),
        ]
        for pos, color in stops:
            gradient.setColorAt(pos, color)

        track_rect = QRectF(0, 2, w, h - 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(track_rect, 4, 4)

        # Border
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 2.5, w - 1, h - 5), 4, 4)

        # Thumb circle
        tx = self._thumb_x()
        ty = h / 2
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(tx, ty), 7, 7)
        painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
        painter.drawEllipse(QPointF(tx, ty), 8, 8)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            hue = self._hue_from_pos(event.position().x())
            self._hue = hue
            self.update()
            self.hue_changed.emit(hue)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            hue = self._hue_from_pos(event.position().x())
            self._hue = hue
            self.update()
            self.hue_changed.emit(hue)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            event.accept()


# ── Alpha Slider ──────────────────────────────────────────────────

class _AlphaSlider(QWidget):
    """Horizontal alpha slider with checkered background."""

    alpha_changed = Signal(int)  # 0-255

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        self._color = tm.accent
        self._alpha = 255
        self._dragging = False
        self._checker = None  # lazy pixmap

    @property
    def _border_color(self):
        return tm.mid

    def set_color(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def set_alpha(self, alpha: int):
        self._alpha = max(0, min(255, alpha))
        self.update()

    def _alpha_from_pos(self, x: float) -> int:
        w = self.width()
        if w <= 0:
            return 255
        return int(max(0, min(255, x / w * 255)))

    def _thumb_x(self) -> float:
        w = self.width()
        if w <= 0:
            return 0
        return self._alpha / 255.0 * w

    def _checker_pixmap(self, size: int = 8) -> QPixmap:
        if self._checker is None or self._checker.width() != size:
            pm = QPixmap(size * 2, size * 2)
            pm.fill(QColor("#808080"))
            p = QPainter(pm)
            p.fillRect(0, 0, size, size, QColor("#c0c0c0"))
            p.fillRect(size, size, size, size, QColor("#c0c0c0"))
            p.end()
            self._checker = pm
        return self._checker

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        track_rect = QRectF(0, 2, w, h - 4)

        # Checker background
        painter.setBrush(QBrush(self._checker_pixmap()))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(track_rect, 4, 4)

        # Alpha gradient: color → transparent
        base_color = QColor(self._color)
        alpha_grad = QLinearGradient(0, 0, w, 0)
        alpha_grad.setColorAt(0.0, QColor(base_color.red(), base_color.green(), base_color.blue(), 0))
        alpha_grad.setColorAt(1.0, QColor(base_color.red(), base_color.green(), base_color.blue(), 255))
        painter.setBrush(QBrush(alpha_grad))
        painter.drawRoundedRect(track_rect, 4, 4)

        # Border
        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 2.5, w - 1, h - 5), 4, 4)

        # Thumb
        tx = self._thumb_x()
        ty = h / 2
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(tx, ty), 7, 7)
        painter.setPen(QPen(QColor(0, 0, 0, 80), 1))
        painter.drawEllipse(QPointF(tx, ty), 8, 8)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            alpha = self._alpha_from_pos(event.position().x())
            self._alpha = alpha
            self.update()
            self.alpha_changed.emit(alpha)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            alpha = self._alpha_from_pos(event.position().x())
            self._alpha = alpha
            self.update()
            self.alpha_changed.emit(alpha)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            event.accept()


# ── Color Panel (popup) ───────────────────────────────────────────

class _ColorPanel(QFrame):
    """Popup panel with all color picking controls."""

    color_selected = Signal(str)  # hex string
    closed = Signal()

    def __init__(self, parent=None):
        # 使用 Qt.Popup + 正确设置父控件，避免独立 Qt.Tool 窗口在 Windows
        # 上与 FramelessMainWindow 交互导致父窗口异常退出。
        # Popup 自动管理：置顶父窗口、点击外部关闭、无任务栏入口。
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("colorPanel")
        self.setFrameShape(QFrame.NoFrame)
        # 关键：popup 自身绝不能设 WA_TranslucentBackground，否则会被设为
        # WS_EX_LAYERED 窗口；也不挂 QGraphicsEffect，否则 Qt 会创建 offscreen
        # 渲染目标，每帧 effect 重合成都会触发 DWM 重合成，与 SettingsWindow
        # （Mica CPU cold cache）首次绘制冲突，导致 FramelessMainWindow 整页崩溃。
        # 改为：普通顶层窗口（不透明、走 GDI），setMask() 圆角裁剪，
        # paintEvent 中用 QPainter.setOpacity 手动控制透明度，QTimer 驱动帧更新。
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._parent_ref = parent

        # C++ 对象销毁时自动清理事件过滤器，防止 eventFilter 访问
        # 已删除对象导致 RuntimeError（如父窗口因 HWND 重建触发）
        self.destroyed.connect(self._on_destroyed)

        # 监听自身事件（用于在 QApplication 级过滤器之前截获流向
        # popup 自身的事件，做统一的可见性/关闭互斥判断）
        self.installEventFilter(self)

        self._color = tm.accent
        self._hue = 120
        self._saturation = 255
        self._value = 255
        self._alpha = 255
        self._app_filter_installed = False
        self._closing_internally = False
        self._closed_emitted = False

        # 动画状态：QTimer 驱动 paintEvent 重绘，QPainter.setOpacity 控制
        # 背景透明度。完全绕开 QGraphicsEffect / QPropertyAnimation。
        # 透明度只影响 popup 自身 paintEvent 绘制的内容；色控件作为子控件
        # 由 Qt 独立渲染，所以在淡入淡出期间临时 hide/show，避免出现
        # "控件已显示但背景仍透明"的穿帮状态。
        self._current_opacity = 0.0
        self._target_opacity = 1.0
        self._content_widgets: list[QWidget] = []
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(16)  # ~60fps
        self._animation_timer.timeout.connect(self._advance_animation)

        self._build_ui()
        self._collect_content_widgets()
        self._connect_signals()
        self._sync_all()

    @property
    def _border_color(self):
        return tm.mid

    @property
    def _bg_card(self):
        return tm.surface

    @property
    def _accent_primary(self):
        return tm.accent

    @property
    def _text_primary(self):
        return tm.text

    @property
    def _text_tertiary(self):
        return tm.alpha_of(tm.mid, 60)

    def _build_ui(self):
        # 控件直接以 self 为父，不再使用 _FadeContainer。
        # 圆角背景由 popup 自身的 paintEvent 绘制（见 paintEvent），
        # 因此外层布局的 margins 直接控制内容与圆角边的距离。
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # 2D Saturation/Value picker
        self._sat_val = _SatValWidget(self)
        layout.addWidget(self._sat_val, alignment=Qt.AlignCenter)

        # Hue slider
        self._hue_slider = _HueSlider(self)
        layout.addWidget(self._hue_slider)

        # Alpha slider
        self._alpha_slider = _AlphaSlider(self)
        layout.addWidget(self._alpha_slider)

        # RGBA spinboxes
        rgba_layout = QHBoxLayout()
        rgba_layout.setSpacing(6)

        self._spin_r = self._make_spinbox("R")
        self._spin_g = self._make_spinbox("G")
        self._spin_b = self._make_spinbox("B")
        self._spin_a = self._make_spinbox("A")

        rgba_layout.addWidget(self._spin_r)
        rgba_layout.addWidget(self._spin_g)
        rgba_layout.addWidget(self._spin_b)
        rgba_layout.addWidget(self._spin_a)
        layout.addLayout(rgba_layout)

        # Preset swatches
        swatch_layout = QHBoxLayout()
        swatch_layout.setSpacing(5)
        swatch_layout.setContentsMargins(0, 4, 0, 0)
        self._swatches: list[QWidget] = []
        for hex_color in PRESET_COLORS:
            sw = self._make_swatch(hex_color)
            swatch_layout.addWidget(sw)
            self._swatches.append(sw)
        layout.addLayout(swatch_layout)

    def _collect_content_widgets(self) -> None:
        """收集 popup 内所有需要随背景同步淡入淡出的内容子控件。

        只收录直接父级是 self 的顶层子控件；它们在淡入淡出期间会被临时
        hide/show，避免"控件已显示但背景仍透明"的穿帮画面。
        """
        self._content_widgets = []
        for child in self.findChildren(QWidget):
            if child is self:
                continue
            # 必须是 popup 的直接子级（layout 顶层项），不递归 deep-hide
            if child.parent() is self:
                self._content_widgets.append(child)

    def _make_spinbox(self, label: str) -> QWidget:
        w = QWidget()
        w_layout = QVBoxLayout(w)
        w_layout.setContentsMargins(0, 0, 0, 0)
        w_layout.setSpacing(1)

        sb = QSpinBox()
        sb.setRange(0, 255)
        sb.setValue(255)
        sb.setFixedSize(56, 28)
        sb.setAlignment(Qt.AlignCenter)
        sb.setFont(_font(11))
        sb.setStyleSheet(f"""
            QSpinBox {{
                background: {BG_INPUT().name()}; color: {self._text_primary.name()};
                border: 1px solid {self._border_color.name()}; border-radius: 4px;
                padding: 0 2px;
            }}
            QSpinBox:focus {{ border: 1px solid {self._accent_primary.name()}; }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 0; height: 0; border: none;
            }}
        """)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFont(_font(10))
        lbl.setStyleSheet(f"color: {self._text_tertiary.name()}; background: transparent;")

        w_layout.addWidget(sb)
        w_layout.addWidget(lbl)

        setattr(self, f"_sb_{label.lower()}", sb)
        return w

    def _make_swatch(self, hex_color: str) -> QWidget:
        sw = QWidget()
        sw.setFixedSize(20, 20)
        sw.setCursor(Qt.PointingHandCursor)
        color = QColor(hex_color)
        sw._color = color
        sw._hex = hex_color
        sw._active = False

        def paint_swatch(ev, w=sw, c=color):
            p = QPainter(w)
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(w.rect())
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
            if w._active:
                p.setPen(QPen(self._accent_primary, 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
            else:
                p.setPen(QPen(self._border_color, 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)

        sw.paintEvent = paint_swatch

        def mouse_press(ev, w=sw):
            if ev.button() == Qt.LeftButton:
                self._on_swatch_clicked(w._hex)

        sw.mousePressEvent = mouse_press
        return sw

    def _connect_signals(self):
        self._sat_val.sat_val_changed.connect(self._on_sat_val_changed)
        self._hue_slider.hue_changed.connect(self._on_hue_changed)
        self._alpha_slider.alpha_changed.connect(self._on_alpha_changed)

        for label in ("r", "g", "b", "a"):
            sb = getattr(self, f"_sb_{label}")
            sb.valueChanged.connect(self._on_rgba_changed)

    def _on_sat_val_changed(self, sat: int, val: int):
        self._saturation = sat
        self._value = val
        self._update_from_hsv()

    def _on_hue_changed(self, hue: int):
        self._hue = hue
        self._sat_val.set_hue(hue)
        self._update_from_hsv()

    def _on_alpha_changed(self, alpha: int):
        self._alpha = alpha
        sb = self._spin_a.findChild(QSpinBox)
        sb.blockSignals(True)
        sb.setValue(alpha)
        sb.blockSignals(False)
        self._emit_color()

    def _on_rgba_changed(self):
        r = self._spin_r.findChild(QSpinBox).value()
        g = self._spin_g.findChild(QSpinBox).value()
        b = self._spin_b.findChild(QSpinBox).value()
        a = self._spin_a.findChild(QSpinBox).value()
        self._color = QColor(r, g, b, a)
        self._alpha = a
        # Derive HSV from RGB
        h, s, v = rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        self._hue = int(h * 360)
        self._saturation = int(s * 255)
        self._value = int(v * 255)
        # Sync sliders and 2D picker (NOT spinboxes — avoid recursion)
        self._sat_val.set_color(self._hue, self._saturation, self._value)
        self._hue_slider.set_hue(self._hue)
        self._alpha_slider.set_color(self._color)
        self._alpha_slider.set_alpha(self._alpha)
        self._sync_swatches()
        self._emit_color()

    def _on_swatch_clicked(self, hex_color: str):
        r, g, b, a = _rgba_from_hex(hex_color)
        self._color = QColor(r, g, b, a)
        h, s, v = rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        self._hue = int(h * 360)
        self._saturation = int(s * 255)
        self._value = int(v * 255)
        self._alpha = a
        self._sync_all()
        self._emit_color()

    def _update_from_hsv(self):
        """Update color and controls from current HSV+A."""
        r, g, b = hsv_to_rgb(self._hue / 360.0, self._saturation / 255.0, self._value / 255.0)
        self._color = QColor(int(r * 255), int(g * 255), int(b * 255), self._alpha)
        self._alpha_slider.set_color(self._color)
        self._sync_spinboxes()
        self._sync_swatches()
        self._emit_color()

    def _sync_all(self):
        """Sync all controls to current color state."""
        self._sat_val.set_color(self._hue, self._saturation, self._value)
        self._hue_slider.set_hue(self._hue)
        self._alpha_slider.set_color(self._color)
        self._alpha_slider.set_alpha(self._alpha)
        self._sync_spinboxes()
        self._sync_swatches()

    def _sync_spinboxes(self):
        for label in ("r", "g", "b", "a"):
            sb = getattr(self, f"_sb_{label}")
            sb.blockSignals(True)
        self._spin_r.findChild(QSpinBox).setValue(self._color.red())
        self._spin_g.findChild(QSpinBox).setValue(self._color.green())
        self._spin_b.findChild(QSpinBox).setValue(self._color.blue())
        self._spin_a.findChild(QSpinBox).setValue(self._alpha)
        for label in ("r", "g", "b", "a"):
            sb = getattr(self, f"_sb_{label}")
            sb.blockSignals(False)

    def _sync_swatches(self):
        hex_str = self._color.name().upper()
        for sw in self._swatches:
            sw._active = (sw._hex.upper() == hex_str)
            sw.update()

    def _emit_color(self):
        hex_str = _hex_from_rgba(
            self._color.red(), self._color.green(),
            self._color.blue(), self._alpha,
        )
        self.color_selected.emit(hex_str)

    # ── Public API ────────────────────────────────────────────

    def set_color(self, hex_color: str):
        r, g, b, a = _rgba_from_hex(hex_color)
        self._color = QColor(r, g, b, a)
        h, s, v = rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        self._hue = int(h * 360)
        self._saturation = int(s * 255)
        self._value = int(v * 255)
        self._alpha = a
        self._sync_all()

    def current_hex(self) -> str:
        return _hex_from_rgba(
            self._color.red(), self._color.green(),
            self._color.blue(), self._alpha,
        )

    # ── Show / hide ───────────────────────────────────────────

    def show_animated(self, anchor: QPoint):
        # 淡入动画完全在 popup 自身的 paintEvent 中完成，QTimer 每 16ms
        # 推进一次不透明度并触发重绘。绕开 QGraphicsEffect / QPropertyAnimation，
        # 避免 offscreen 渲染目标触发 DWM 重合成导致父 SettingsWindow 崩溃。
        # 淡入期间临时 hide 所有内容子控件，背景完成后再 show，避免穿帮。
        self._closed_emitted = False
        self._closing_internally = False

        # 1. 先在所有控件可见的情况下计算尺寸，确保 setFixedSize 锁定的
        #    是「完整显示」时的尺寸，避免后续 hide 控件时布局塌陷。
        self.setFixedWidth(288)
        self.adjustSize()
        full_size = QSize(self.size())

        # 2. 临时隐藏内容子控件（背景淡入期间不显示），固定窗口尺寸
        for w in self._content_widgets:
            w.hide()
        self.setFixedSize(full_size)

        # 3. 定位 + 圆角遮罩 + 事件过滤器
        self.move(anchor.x(), anchor.y())
        self._apply_round_mask()
        self._install_event_filter()

        # 4. 启动 QTimer 驱动的淡入
        self._current_opacity = 0.0
        self._target_opacity = 1.0
        self._animation_timer.start()

        super().show()
        self.raise_()

    def _apply_round_mask(self) -> None:
        """用 setMask() 实现圆角裁剪（popup 不设 WA_TranslucentBackground）。

        Qt.Popup 设了 WA_TranslucentBackground 就会被当作 WS_EX_LAYERED
        窗口，每帧的 effect 重合成都会触发 DWM 重合成。改用 setMask()
        走窗口级 region 裁剪，popup 保持普通顶层窗口，effect 重合成只
        走 GDI 路径，零 DWM 参与。
        """
        radius = 8
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(0, 0, self.width(), self.height()),
            radius, radius,
        )
        # QPainterPath → QPolygonF → QPolygon → QRegion
        polygon = path.toFillPolygon(QTransform()).toPolygon()
        self.setMask(QRegion(polygon))

    def close_animated(self):
        # 淡出动画同样在 popup 自身 paintEvent 中完成，QTimer 推进透明度。
        # 关闭开始即 hide 内容子控件，只让背景淡出消失。
        if self._closing_internally:
            return
        self._closing_internally = True
        for w in self._content_widgets:
            w.hide()
        self._target_opacity = 0.0
        self._animation_timer.start()

    def _advance_animation(self) -> None:
        """QTimer 回调：每 16ms 推进一次透明度，触发 paintEvent 重绘。

        到达目标值后停止计时器；淡出到位时调用 _on_close_finished 完成关闭。
        淡入到位时把内容子控件 show 出来。
        """
        target = self._target_opacity
        if self._current_opacity < target:
            self._current_opacity = min(target, self._current_opacity + 0.08)
        elif self._current_opacity > target:
            self._current_opacity = max(target, self._current_opacity - 0.1)
        else:
            self._animation_timer.stop()
            return

        self.update()

        if self._current_opacity == target:
            self._animation_timer.stop()
            if target >= 1.0:
                # 淡入到位：show 所有内容子控件
                for w in self._content_widgets:
                    w.show()
            elif target <= 0.0:
                # 淡出到位：完成关闭
                self._on_close_finished()

    def _on_close_finished(self):
        self.hide()
        self._cleanup()
        self._closing_internally = False
        # 重置为不可见状态，方便下次 show_animated 从 0 重新淡入
        self._current_opacity = 0.0
        # 恢复内容子控件为可见，下次 show_animated 会再次 hide 后淡入
        for w in self._content_widgets:
            w.show()

    def _cleanup(self) -> None:
        """关闭/隐藏时统一清理：移除事件过滤器并补发 closed 信号。"""
        self._remove_event_filter()
        if not self._closed_emitted:
            self._closed_emitted = True
            try:
                self.closed.emit()
            except RuntimeError:
                pass

    def _on_destroyed(self) -> None:
        """C++ 对象销毁时清理事件过滤器，防止 eventFilter 访问已删除对象。"""
        try:
            if self._app_filter_installed:
                QApplication.instance().removeEventFilter(self)
                self._app_filter_installed = False
        except RuntimeError:
            pass

    def hideEvent(self, event):
        """隐藏时清理事件过滤器，避免被删除后仍收到事件。"""
        self._cleanup()
        super().hideEvent(event)

    def closeEvent(self, event):
        """关闭时清理事件过滤器，避免被删除后仍收到事件。"""
        self._cleanup()
        super().closeEvent(event)

    def _install_event_filter(self):
        if not self._app_filter_installed:
            QApplication.instance().installEventFilter(self)
            top = self.window()
            if top and top != self:
                top.installEventFilter(self)
            self._app_filter_installed = True

    def _remove_event_filter(self):
        if self._app_filter_installed:
            QApplication.instance().removeEventFilter(self)
            top = self.window()
            if top and top != self:
                top.removeEventFilter(self)
            self._app_filter_installed = False

    def eventFilter(self, obj, event):
        try:
            if self.isVisible() and not self._closing_internally:
                if event.type() == QEvent.MouseButtonPress:
                    pos = event.globalPosition().toPoint() if hasattr(event, 'globalPosition') else QCursor.pos()
                    # Check if click is inside the panel itself (use mapFromGlobal for accuracy)
                    local = self.mapFromGlobal(pos)
                    if self.rect().contains(local):
                        return False
                    # Check if click is inside the parent StyledColorPicker trigger widget
                    try:
                        parent_visible = self._parent_ref and self._parent_ref.isVisible()
                    except RuntimeError:
                        parent_visible = False
                    if parent_visible:
                        parent_local = self._parent_ref.mapFromGlobal(pos)
                        if self._parent_ref.rect().contains(parent_local):
                            return False
                    # Click outside → close
                    self.close_animated()
                    return False
            return super().eventFilter(obj, event)
        except RuntimeError:
            # C++ 对象已被删除（如事件过滤器未同步移除），安全降级。
            return False

    def paintEvent(self, event: QPaintEvent):
        # 在 popup 自身绘制圆角背景与边框，setOpacity 应用当前动画透明度。
        # 这替代了原 _FadeContainer 的作用：完全走 GDI 路径，不触发 DWM 重合成。
        # 子控件（已在淡入淡出期间被 hide）由 Qt 独立渲染在背景之上。
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = 8
        p.setOpacity(self._current_opacity)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(tm.surface))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
        p.setPen(QPen(tm.mid, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)
        p.end()


# ── Preview Widget ────────────────────────────────────────────────

class _PreviewWidget(QWidget):
    """Color preview square with rounded rect and border."""

    clicked = Signal()

    @property
    def _border_color(self):
        return tm.mid

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self._color = tm.accent
        self._enabled = True
        self._hovered = False

    def set_color(self, color: QColor):
        self._color = QColor(color)
        self.update()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ForbiddenCursor)
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = 6

        if self._enabled:
            fill_color = self._color
        else:
            fill_color = tm.fill

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(fill_color))
        painter.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        painter.setPen(QPen(self._border_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)

        if not self._enabled:
            painter.setOpacity(0.5)

        # Hex text overlay
        painter.setFont(_font(9))
        hex_text = self._color.name().upper()
        painter.setPen(QColor("#ffffff") if self._color.lightness() < 128 else QColor("#000000"))
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, hex_text)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._enabled:
            self.clicked.emit()
            event.accept()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)


# ── Main Color Picker ─────────────────────────────────────────────

class StyledColorPicker(QWidget):
    """Color picker matching web component.

    Features:
        - Preview square showing current color
        - Hex input line for direct entry
        - Click preview → popup panel with 2D picker, sliders, RGBA, presets
        - Disabled state
    """

    color_changed = Signal(str)  # hex string "#RRGGBB" or "#RRGGBBAA"

    # ── Theme color properties ─────────────────────────────────
    @property
    def _border_color(self):
        return tm.mid

    @property
    def _accent_primary(self):
        return tm.accent

    @property
    def _text_primary(self):
        return tm.text

    def __init__(
        self,
        color: str = tm.accent.name(),
        enabled: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._enabled = enabled
        self._color = QColor(color)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Preview square
        self._preview = _PreviewWidget(self)
        self._preview.set_color(self._color)
        self._preview.set_enabled(enabled)
        self._preview.clicked.connect(self._toggle_panel)
        layout.addWidget(self._preview)

        # Hex input
        self._hex_input = QLineEdit(self)
        self._hex_input.setText(self._color.name().upper())
        self._hex_input.setFixedHeight(36)
        self._hex_input.setFixedWidth(90)
        self._hex_input.setFont(_font(13))
        self._hex_input.setAlignment(Qt.AlignCenter)
        self._hex_input.setStyleSheet(f"""
            QLineEdit {{
                background: {BG_INPUT().name()}; color: {self._text_primary.name()};
                border: 1px solid {self._border_color.name()}; border-radius: 6px;
                padding: 0 8px;             }}
            QLineEdit:focus {{ border: 1px solid {self._accent_primary.name()}; }}
            QLineEdit:disabled {{ color: {tm.alpha_of(tm.mid, 60).name()}; background: {tm.surface.name()}; }}
        """)
        self._hex_input.setEnabled(enabled)
        self._hex_input.editingFinished.connect(self._on_hex_edited)
        layout.addWidget(self._hex_input)

        # Panel
        self._panel = _ColorPanel(self)
        self._panel.color_selected.connect(self._on_panel_color)
        self._panel.closed.connect(self._on_panel_closed)
        self._panel.hide()

    # ── Public API ────────────────────────────────────────────

    @property
    def color(self) -> str:
        return self._color.name().upper()

    @color.setter
    def color(self, value: str):
        r, g, b, a = _rgba_from_hex(value)
        self._color = QColor(r, g, b, a)
        self._preview.set_color(self._color)
        self._hex_input.setText(self._color.name().upper())
        self._panel.set_color(value)
        self.color_changed.emit(value)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        self._preview.set_enabled(value)
        self._hex_input.setEnabled(value)

    # ── Internal ──────────────────────────────────────────────

    def _toggle_panel(self):
        if not self._enabled:
            return
        if self._panel.isVisible():
            self._panel.close_animated()
        else:
            self._close_other_panels()
            # Sync panel to current color before showing
            self._panel.set_color(self._color.name())
            pos = self.mapToGlobal(QPoint(0, self.height() + 4))
            self._panel.show_animated(pos)

    def _close_other_panels(self):
        for w in QApplication.topLevelWidgets():
            if isinstance(w, _ColorPanel) and w != self._panel and w.isVisible():
                w.close_animated()

    def _on_hex_edited(self):
        text = self._hex_input.text().strip()
        if not text.startswith("#"):
            text = "#" + text
        try:
            r, g, b, a = _rgba_from_hex(text)
        except (ValueError, IndexError):
            self._hex_input.setText(self._color.name().upper())
            return
        self._color = QColor(r, g, b, a)
        self._preview.set_color(self._color)
        self._hex_input.setText(self._color.name().upper())
        self._panel.set_color(text)
        self.color_changed.emit(self._color.name().upper())

    def _on_panel_color(self, hex_color: str):
        r, g, b, a = _rgba_from_hex(hex_color)
        self._color = QColor(r, g, b, a)
        self._preview.set_color(self._color)
        self._hex_input.setText(hex_color.upper())
        self.color_changed.emit(hex_color)

    def _on_panel_closed(self):
        pass

    def closeEvent(self, event):
        self._panel.hide()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._panel.hide()
        super().hideEvent(event)
