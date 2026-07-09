# allow: SIZE_OK — single logical component (StyledCascader + 2 private helpers);
# separating _CascaderColumnItem or _CascaderPanel into their own files would
# add module boundary friction with no reuse benefit.

"""Styled Cascader component — multi-level selector with column navigation."""

from theme import tm
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QApplication,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPoint, QPropertyAnimation,
    QEasingCurve, Property, QEvent,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QFont, QMouseEvent, QKeyEvent, QPen,
)

from components.icon_utils import icon_path

# ── Constants ──────────────────────────────────────────────────────────────

_COLUMN_WIDTH = 200
_PANEL_MAX_HEIGHT = 260
_INPUT_HEIGHT = 36
_BORDER_RADIUS = 6
_ITEM_HEIGHT = 34
_FONT = "Microsoft YaHei UI"
_FONT_SIZE = 13
_COLUMN_PAD = 6


# ── Column item widget ────────────────────────────────────────────────────

class _CascaderColumnItem(QWidget):
    """Single item in a cascader column. Has animated hover highlight."""

    clicked = Signal(object)  # emits the item dict

    # ── Theme colors ────────────────────────────────────────────

    @property
    def _color_text(self) -> str:
        return tm.text.name()

    @property
    def _color_text_secondary(self) -> str:
        return tm.mid.name()

    def __init__(self, item: dict, has_children: bool, parent=None):
        super().__init__(parent)
        self._item = item
        self._has_children = has_children
        self._hover_progress = 0.0
        self.setFixedHeight(_ITEM_HEIGHT)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setCursor(Qt.PointingHandCursor)

        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

    # ── animated property ──────────────────────────────────────

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, v: float):
        self._hover_progress = v
        self.update()

    # ── paint ──────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # Hover background
        if self._hover_progress > 0:
            bg_r = int(45 + (51 - 45) * self._hover_progress)
            bg_g = int(45 + (51 - 45) * self._hover_progress)
            bg_b = int(45 + (51 - 45) * self._hover_progress)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(bg_r, bg_g, bg_b))
            p.drawRect(QRectF(0, 0, w, h))

        # Label text
        font = QFont(_FONT, _FONT_SIZE)
        p.setFont(font)
        p.setPen(QColor(self._color_text))
        text_rect = QRectF(16, 0, w - 48, h)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                    self._item.get("label", ""))

        # Chevron-right icon if item has children
        if self._has_children:
            self._draw_expand_icon(p, w, h)

        p.end()

    @staticmethod
    def _draw_expand_icon(p: QPainter, w: int, h: int):
        """Draw a small chevron_right icon at the right edge."""
        icon_sz = 14.0
        ix = w - icon_sz - 14
        iy = (h - icon_sz) / 2.0
        path = icon_path("chevron_right")
        if path.isEmpty():
            return

        p.save()
        view = 24.0
        sc = icon_sz / view
        p.translate(ix + icon_sz / 2.0, iy + icon_sz / 2.0)
        p.scale(sc, sc)
        p.translate(-view / 2.0, -view / 2.0)
        p.setPen(QPen(QColor(self._color_text_secondary), 2.0,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.restore()

    # ── mouse / hover ──────────────────────────────────────────

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._item)
            event.accept()


# ── Cascader column popup (single-column overlay) ──────────────────────────

class _CascaderColumnPopup(QWidget):
    """Single-column cascader popup card — one level of the cascade.

    Each popup is an independent window with its own size based on its
    own item count, positioned to the right of its parent column.
    """

    item_selected = Signal(object)  # emits the clicked item dict

    # ── Theme colors ────────────────────────────────────────────

    @property
    def _color_bg(self) -> str:
        return tm.surface.name()

    @property
    def _color_border(self) -> str:
        return tm.alpha_of(tm.mid, 40).name()

    def __init__(self, items: list[dict], depth: int, parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._depth = depth
        self._closing_internally = False
        self._radius = _BORDER_RADIUS + 2

        # Own height based on own content
        content_h = len(items) * _ITEM_HEIGHT + _COLUMN_PAD * 2 + 12
        panel_h = min(content_h, _PANEL_MAX_HEIGHT)
        self._target_w = _COLUMN_WIDTH
        self._target_h = panel_h

        # Column layout
        col_widget = QWidget()
        col_layout = QVBoxLayout(col_widget)
        col_layout.setContentsMargins(_COLUMN_PAD, _COLUMN_PAD,
                                      _COLUMN_PAD, _COLUMN_PAD)
        col_layout.setSpacing(1)

        for item in items:
            has_children = bool(item.get("children"))
            item_w = _CascaderColumnItem(item, has_children)
            item_w.clicked.connect(self._on_item_clicked)
            col_layout.addWidget(item_w)
        col_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(col_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFixedWidth(_COLUMN_WIDTH)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{
                width: 6px; background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: {tm.fill.name()}; border-radius: 3px; min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def show_animated(self, anchor: QPoint):
        """Fade in + slide down from anchor point (combobox-style)."""
        if self._depth == 0:
            # First column: collapse→expand (slide down)
            start_h = 10
            self.setGeometry(anchor.x(), anchor.y(), self._target_w, start_h)
        else:
            # Subsequent columns: appear at final position (fade only)
            self.setGeometry(anchor.x(), anchor.y(), self._target_w, self._target_h)

        self.setWindowOpacity(0.0)
        super().show()

        # Opacity fade-in (ALL columns)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(200)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.start()

        if self._depth == 0:
            # Height slide animation (first column only — grown downward)
            self._slide = QPropertyAnimation(self, b"geometry")
            self._slide.setDuration(220)
            self._slide.setStartValue(self.geometry())
            end_geo = QRectF(anchor.x(), anchor.y(),
                           self._target_w, self._target_h).toRect()
            self._slide.setEndValue(end_geo)
            self._slide.setEasingCurve(QEasingCurve.OutCubic)
            self._slide.start()

    def _on_item_clicked(self, item: dict):
        self.item_selected.emit(item)

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self._radius
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color_bg))
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
        p.setPen(QPen(QColor(self._color_border), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def close_animated(self):
        """Fade out + collapse for smooth dismiss (combobox-style)."""
        self._closing_internally = True

        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(150)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.InCubic)
        self._fade.finished.connect(self.close)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()

        if self._depth == 0:
            self._slide = QPropertyAnimation(self, b"geometry")
            self._slide.setDuration(150)
            self._slide.setStartValue(self.geometry())
            geo = QRectF(self.geometry())
            geo.setHeight(10)
            self._slide.setEndValue(geo.toRect())
            self._slide.setEasingCurve(QEasingCurve.InCubic)
            self._slide.start()

    def hideEvent(self, event):
        """Notify parent if hidden externally (e.g. focus lost)."""
        super().hideEvent(event)
        if not self._closing_internally and self._depth == 0:
            # Only the first column signals external dismissal
            self.item_selected.emit(None)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.item_selected.emit(None)  # None signals dismissal
        super().keyPressEvent(event)


# ── Main cascader widget ──────────────────────────────────────────────────

class StyledCascader(QWidget):
    """Multi-level cascader selector.

    Displays a clickable input area.  Clicking opens a multi-column overlay
    panel where users drill down through nested levels.  The selected path
    is shown in the input and emitted via *path_changed*.

    Parameters
    ----------
    data : list[dict]
        Nested items with ``{label, value, children: [...]}`` shape.
    parent : QWidget or None
    """

    path_changed = Signal(list)  # emits list of {label, value} dicts

    # ── Theme colors ────────────────────────────────────────────

    @property
    def _color_text(self) -> str:
        return tm.text.name()

    @property
    def _color_text_disabled(self) -> str:
        return tm.alpha_of(tm.mid, 40).name()

    @property
    def _color_accent(self) -> str:
        return tm.accent.name()

    def __init__(self, data: list = None, parent=None):
        super().__init__(parent)
        self._data = data or []
        self._selected_path: list[dict] = []
        self._open = False
        self._arrow_rotation = 0.0
        self._hover_progress = 0.0
        self._column_popups: list[_CascaderColumnPopup] = []
        self._path_stack: list[dict] = []
        self._app_filter_installed = False

        self.setFixedHeight(_INPUT_HEIGHT)
        self.setMinimumWidth(200)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        # Hover animation
        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Arrow rotation animation
        self._arrow_anim = QPropertyAnimation(self, b"arrow_rotation")
        self._arrow_anim.setDuration(200)
        self._arrow_anim.setEasingCurve(QEasingCurve.OutCubic)

    # ── public API ─────────────────────────────────────────────

    def setData(self, data: list):
        """Replace the cascader data and reset selection."""
        self._data = data
        self._clear_selection()

    def setSelectedPath(self, path: list[dict]):
        """Programmatically set the selected path.

        *path* is a list of {label, value} dicts matching the data tree.
        """
        self._selected_path = list(path)
        self.path_changed.emit(self._selected_path)
        self.update()

    def currentPath(self) -> list[dict]:
        """Return the current selected path (list of {label, value} dicts)."""
        return list(self._selected_path)

    def currentText(self) -> str:
        """Return the label-path as a joined string, or empty string."""
        if not self._selected_path:
            return ""
        return " / ".join(item.get("label", "") for item in self._selected_path)

    # ── internal ───────────────────────────────────────────────

    def _clear_selection(self):
        """Reset selection to empty."""
        self._selected_path.clear()
        self.path_changed.emit(self._selected_path)
        self.update()

    def _toggle(self):
        if self._open:
            self._close()
        else:
            self._open_panel()

    def _open_panel(self):
        self._open = True
        self._animate_arrow(1.0)
        self.update()
        self._path_stack.clear()
        self._open_column(self._data, 0)
        if not self._app_filter_installed:
            QApplication.instance().installEventFilter(self)
            self._app_filter_installed = True

    def _open_column(self, items: list[dict], depth: int):
        popup = _CascaderColumnPopup(items, depth)
        popup.item_selected.connect(
            lambda item, d=depth: self._on_column_item_selected(item, d)
        )

        # Position:
        #   depth 0: below input widget
        #   depth N: to the right of previous column
        if depth == 0:
            anchor = self.mapToGlobal(QPoint(0, self.height() + 4))
        else:
            prev = self._column_popups[depth - 1]
            anchor = prev.mapToGlobal(QPoint(prev.width(), 0))

        popup.show_animated(anchor)
        if depth == 0:
            popup.setFocus()

        self._column_popups.append(popup)

    def _on_column_item_selected(self, item: dict, depth: int):
        # None signals Escape dismissal
        if item is None:
            self._close()
            return

        # Update selection path
        self._path_stack = self._path_stack[:depth]
        self._path_stack.append(item)

        # Close deeper columns
        while len(self._column_popups) > depth + 1:
            old = self._column_popups.pop()
            old.close_animated()

        children = item.get("children")
        if children:
            self._open_column(children, depth + 1)
        else:
            self._selected_path = list(self._path_stack)
            self.path_changed.emit(self._selected_path)
            self._close()

    def _close(self):
        for popup in self._column_popups:
            popup.close_animated()
        self._column_popups.clear()
        self._path_stack.clear()
        self._open = False
        self._animate_arrow(0.0)
        self.update()

    def _animate_arrow(self, target: float):
        self._arrow_anim.stop()
        self._arrow_anim.setStartValue(self._arrow_rotation)
        self._arrow_anim.setEndValue(target)
        self._arrow_anim.start()

    # ── animated properties ────────────────────────────────────

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, v: float):
        self._hover_progress = v
        self.update()

    @Property(float)
    def arrow_rotation(self):
        return self._arrow_rotation

    @arrow_rotation.setter
    def arrow_rotation(self, v: float):
        self._arrow_rotation = v
        self.update()

    # ── paint ──────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        rad = _BORDER_RADIUS
        enabled = self.isEnabled()

        # ── background ──
        if not enabled:
            bg = tm.alpha_of(tm.surface, 90)
        else:
            r = int(45 + (51 - 45) * self._hover_progress)
            g = int(45 + (51 - 45) * self._hover_progress)
            b = int(45 + (51 - 45) * self._hover_progress)
            bg = QColor(r, g, b)

        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), rad, rad)

        # ── border ──
        if not enabled:
            border = tm.surface
        elif self._open:
            border = QColor(self._color_accent)
        else:
            r = int(58 + (68 - 58) * self._hover_progress)
            g = int(58 + (68 - 58) * self._hover_progress)
            b = int(58 + (68 - 58) * self._hover_progress)
            border = QColor(r, g, b)

        pen = QPen(border, 1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), rad, rad)

        # ── text (selected path or placeholder) ──
        font = QFont(_FONT, _FONT_SIZE)
        p.setFont(font)

        # Calculate available width (reserve space for arrow + clear)
        right_reserved = 12 + 16 + 8  # padding + arrow + gap
        if self._selected_path and enabled:
            right_reserved += 20  # clear button area
        text_max_w = max(w - 12 - right_reserved, 0)

        if self._selected_path:
            display_text = " / ".join(
                item.get("label", "") for item in self._selected_path
            )
        else:
            display_text = "请选择"

        if not enabled:
            tc = QColor(self._color_text_disabled)
        else:
            tc = QColor(self._color_text) if self._selected_path else tm.alpha_of(tm.mid, 60)

        p.setPen(tc)
        p.drawText(QRectF(12, 0, text_max_w, h),
                   Qt.AlignVCenter | Qt.AlignLeft, display_text)

        # ── layout positions for interactive elements ──
        arrow_center_x = w - 12 - 8  # 12px right padding + half of 16px arrow
        clear_center_x = arrow_center_x - 28  # 8px gap + half of 16px clear

        # ── arrow icon (chevron_down, rotated) ──
        if not enabled:
            arrow_color = tm.alpha_of(tm.mid, 50)
        else:
            arrow_color = tm.alpha_of(tm.mid, 80)

        arrow_sz = 16.0
        path_down = icon_path("chevron_down")
        if not path_down.isEmpty():
            p.save()
            view = 24.0
            sc = arrow_sz / view
            p.translate(arrow_center_x, h / 2.0)
            angle = 180.0 * self._arrow_rotation
            p.rotate(angle)
            p.scale(sc, sc)
            p.translate(-view / 2.0, -view / 2.0)
            p.setPen(QPen(arrow_color, 2.0,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path_down)
            p.restore()

        # ── clear button (×) ──
        if self._selected_path and enabled:
            clear_sz = 14.0
            path_close = icon_path("close")
            if not path_close.isEmpty():
                p.save()
                sc = clear_sz / view
                p.translate(clear_center_x, h / 2.0)
                p.scale(sc, sc)
                p.translate(-view / 2.0, -view / 2.0)
                p.setPen(QPen(tm.mid, 1.8,
                              Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path_close)
                p.restore()

        p.end()

    # ── mouse / hover ──────────────────────────────────────────

    def mousePressEvent(self, event):
        if not self.isEnabled():
            return
        if event.button() == Qt.LeftButton:
            x = event.position().x()
            w = self.width()

            # Layout from right edge:
            #   12px pad | arrow(16px) | 8px gap | clear(16px) | text
            arrow_start = w - 12 - 16  # w-28
            clear_end = arrow_start - 8  # w-36
            clear_start = clear_end - 16  # w-52

            if self._selected_path and clear_start <= x <= clear_end:
                self._clear_selection()
                event.accept()
                return

            self._toggle()
            event.accept()

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(event)

    # ── event filter (outside-click detection) ─────────────────

    def eventFilter(self, obj, event):
        """App-level filter: close popup on outside click or Escape."""
        if self._open and self._column_popups:
            if event.type() == QEvent.KeyPress:
                if isinstance(event, QKeyEvent) and event.key() == Qt.Key_Escape:
                    self._close()
                    return True
            if event.type() in (QEvent.MouseButtonPress, QEvent.TouchBegin):
                if isinstance(event, QMouseEvent):
                    global_pos = event.globalPosition().toPoint()
                    # Click on the trigger widget → let toggle handle it
                    if self.rect().contains(self.mapFromGlobal(global_pos)):
                        return False
                    # Check click inside any column popup
                    for popup in self._column_popups:
                        if (popup.isVisible()
                            and popup.rect().contains(
                                popup.mapFromGlobal(global_pos))):
                            return False
                    self._close()
                    return True
        return super().eventFilter(obj, event)

    # ── disabled state paint update ────────────────────────────

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self.update()
