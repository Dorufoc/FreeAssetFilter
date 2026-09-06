"""Styled ComboBox component — dropdown with animations."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGraphicsDropShadowEffect, QApplication,
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPoint, QSize, QPropertyAnimation,
    QEasingCurve, Property, QTimer, QEvent,
)
from PySide6.QtGui import (
    QPainter, QColor, QPaintEvent, QFont, QFontMetrics, QMouseEvent, QPolygonF,
    QPainterPath, QPen,
)
from theme import tm


# ── Popup item widget ────────────────────────────────────────

class _ComboItemWidget(QWidget):
    """Individual item in dropdown. Animated hover via hover_progress."""

    clicked = Signal()

    def __init__(self, text: str, selected: bool, font_size: float, parent=None):
        super().__init__(parent)
        self._text = text
        self._selected = selected
        self._font_size = font_size
        self._hover_progress = 0.0
        self.setFixedHeight(34)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setCursor(Qt.PointingHandCursor)

        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, v: float):
        self._hover_progress = v
        self.update()

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        accent = tm.accent
        tertiary_bg = tm.surface
        text_primary = tm.text
        text_secondary = tm.mid

        # Background
        if self._selected:
            # Selected: accent color background
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 6, 6)
        elif self._hover_progress > 0:
            p.setPen(Qt.NoPen)
            c1 = tertiary_bg
            c2 = tm.fill
            bg = QColor(
                int(c1.red() + (c2.red() - c1.red()) * self._hover_progress),
                int(c1.green() + (c2.green() - c1.green()) * self._hover_progress),
                int(c1.blue() + (c2.blue() - c1.blue()) * self._hover_progress),
            )
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 6, 6)

        # Text
        if self._selected:
            c = tm.text
        elif self._hover_progress > 0:
            c1 = text_secondary
            c2 = text_primary
            r = int(c1.red() + (c2.red() - c1.red()) * self._hover_progress)
            g = int(c1.green() + (c2.green() - c1.green()) * self._hover_progress)
            b = int(c1.blue() + (c2.blue() - c1.blue()) * self._hover_progress)
            c = QColor(r, g, b)
        else:
            c = text_secondary

        font = QFont("Microsoft YaHei UI", int(self._font_size))
        p.setFont(font)
        p.setPen(c)
        p.drawText(QRectF(12, 0, self.width() - 40, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self._text)

        p.end()

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
            self.clicked.emit()
            event.accept()


# ── Popup divider widget ─────────────────────────────────────

class _ComboDivider(QWidget):
    """Divider line between menu items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(tm.mid, 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()


# ── Popup window ─────────────────────────────────────────────

class _ComboPopup(QWidget):
    """Dropdown popup with fade + slide animation."""

    item_selected = Signal(int)

    def __init__(self, items: list, current_index: int, size: str, min_width: int, align_right: bool = False, parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self._items = items
        self._current_index = current_index
        self._size = size
        self._min_width = min_width
        self._align_right = align_right
        self._target_y = 0
        self._target_h = 0
        self._radius = 10

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Flat layout — items directly in popup, no nesting
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(1)

        font_size_map = {"sm": 12, "default": 13, "lg": 14}
        font_size = font_size_map.get(size, 13)

        item_index = 0
        for item in items:
            if item == "---":
                divider = _ComboDivider()
                layout.addWidget(divider)
            else:
                w = _ComboItemWidget(item, item_index == current_index, font_size)
                w.clicked.connect(lambda idx=item_index: self._on_item_clicked(idx))
                layout.addWidget(w)
                item_index += 1

        layout.addStretch()

        # Calculate popup size
        item_count = sum(1 for i in items if i != "---")
        divider_count = sum(1 for i in items if i == "---")
        item_h = 34 + 1
        divider_h = 1 + 2
        visible_count = min(item_count, 8)
        content_h = visible_count * item_h + divider_count * divider_h + 12

        w = max(self._min_width, self._estimate_width(items, font_size) + 32)
        self.resize(w, content_h)

        self._target_w = w
        self._target_h = content_h
        self._closing_internally = False

    def paintEvent(self, event: QPaintEvent):
        """Draw rounded background + border only."""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = self._radius

        p.setPen(Qt.NoPen)
        p.setBrush(tm.surface)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)

        p.setPen(QPen(tm.mid, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.end()

    def _estimate_width(self, items: list, font_size: float) -> int:
        font = QFont("Microsoft YaHei UI", font_size)
        fm = self.fontMetrics()
        fm = QApplication.fontMetrics()
        m = 0
        for t in items:
            if t != "---":
                m = max(m, fm.horizontalAdvance(t))
        return m + 40

    def show_animated(self, anchor: QPoint):
        """Fade in + slide down from anchor point."""
        # Start geometry: collapsed height, positioned at anchor
        start_h = 10
        
        # Calculate x position based on alignment
        if self._align_right:
            x = anchor.x() - self._target_w + self._min_width
        else:
            x = anchor.x()
            
        self.setGeometry(x, anchor.y(), self._target_w, start_h)
        self.setWindowOpacity(0.0)
        super().show()

        # Opacity animation
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(200)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        # Height slide animation
        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setDuration(220)
        self._slide.setStartValue(self.geometry())
        self._slide.setEndValue(
            QRectF(x, anchor.y(), self._target_w, self._target_h).toRect()
        )
        self._slide.setEasingCurve(QEasingCurve.OutCubic)

        self._fade.start()
        self._slide.start()

    def _on_item_clicked(self, index: int):
        self.item_selected.emit(index)

    def close_animated(self):
        """Slide up + fade out for smooth dismiss."""
        self._closing_internally = True
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(150)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.InCubic)

        self._slide = QPropertyAnimation(self, b"geometry")
        self._slide.setDuration(150)
        self._slide.setStartValue(self.geometry())
        end = QRectF(self.geometry())
        end.setHeight(10)
        self._slide.setEndValue(end.toRect())
        self._slide.setEasingCurve(QEasingCurve.InCubic)

        self._slide.finished.connect(self.close)
        self._fade.start()
        self._slide.start()

    def hideEvent(self, event):
        """Notify parent when popup is hidden externally (e.g. focus lost)."""
        super().hideEvent(event)
        if not self._closing_internally:
            self.item_selected.emit(-1)  # sentinel value meaning "dismissed"


# ── Main combobox widget ─────────────────────────────────────

class StyledComboBox(QWidget):
    """Styled dropdown with chevron rotation + popup animation."""

    selection_made = Signal(str)
    current_index_changed = Signal(int)

    SIZE_CONFIG = {
        "sm": {"h_pad": 10, "height": 30, "font_sz": 12, "rad": 6},
        "default": {"h_pad": 12, "height": 36, "font_sz": 13, "rad": 6},
        "lg": {"h_pad": 16, "height": 44, "font_sz": 14, "rad": 8},
    }

    def __init__(self, items: list = None, size: str = "default", align_right: bool = False, parent=None, title: str = "", flat: bool = False):
        super().__init__(parent)
        self._size = size if size in self.SIZE_CONFIG else "default"
        self._items = items or []
        self._current_index = 0
        self._open = False
        self._hover_progress = 0.0
        self._chevron_progress = 0.0  # 0→1 on open
        self._align_right = align_right
        self._app_filter_installed = False
        # 标题模式：默认项仅显示 title（如“格式”）+ 小三角；
        # 手动选择后双行显示 title / 当前项（如“格式” / “GBK”）。
        self._title = title
        # 无框模式：不绘制背景与边框，功能像普通按钮一样直接显示在顶栏。
        self._flat = flat
        # 仅显示 title 的初始默认态：用户做过一次选择后不再自动退回。
        self._title_only = True

        cfg = self.SIZE_CONFIG[self._size]
        self.setFixedHeight(self._title and 36 or cfg["height"])
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        # Hover animation
        self._hover_anim = QPropertyAnimation(self, b"hover_progress")
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Chevron rotation animation
        self._chevron_anim = QPropertyAnimation(self, b"chevron_progress")
        self._chevron_anim.setDuration(200)
        self._chevron_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._popup = None

    # ── animated properties ────────────────────────────────

    @Property(float)
    def hover_progress(self):
        return self._hover_progress

    @hover_progress.setter
    def hover_progress(self, v: float):
        self._hover_progress = v
        self.update()

    @Property(float)
    def chevron_progress(self):
        return self._chevron_progress

    @chevron_progress.setter
    def chevron_progress(self, v: float):
        self._chevron_progress = v
        self.update()

    # ── public API ─────────────────────────────────────────

    def addItems(self, items: list):
        self._items = items
        self.update()

    def setCurrentIndex(self, index: int):
        self._current_index = max(0, min(index, len(self._items) - 1))
        self.current_index_changed.emit(self._current_index)
        self.update()

    def currentText(self) -> str:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return ""

    def set_title_mode(self, title: str) -> None:
        """切换标题模式：非空 title 时默认项只显示 title，
        手动选择后双行显示 title / 当前项；传空串则恢复单行模式。"""
        self._title = title
        cfg = self.SIZE_CONFIG[self._size]
        self.setFixedHeight(self._title and 36 or cfg["height"])
        self.update()

    def set_flat(self, flat: bool) -> None:
        """切换无框模式：True 时不绘制背景与边框（配合 title 模式）。"""
        self._flat = flat
        self.update()

    def reset_title_only(self) -> None:
        """恢复初始默认显示态（新预览文件）：默认项仅显示 title。"""
        self._title_only = True
        self.update()

    # ── 内容测量（无框标题模式专用）────────────────────────────

    _SIDE = 18   # 无框标题模式两侧留白（箭头与文字整体居中所需）

    @property
    def flat(self) -> bool:
        return self._flat

    def _fonts(self) -> tuple:
        """返回 (title 小字, 值/主文本) 两组绘制字体。"""
        cfg = self.SIZE_CONFIG[self._size]
        title_font = QFont("Microsoft YaHei UI", cfg["font_sz"] - 3)
        value_font = QFont("Microsoft YaHei UI", cfg["font_sz"])
        return title_font, value_font

    def _chevron_gap(self) -> int:
        """箭头与文字之间的正常间距：约一个空格宽（4–8px）。"""
        _, value_font = self._fonts()
        fm = QFontMetrics(value_font)
        return max(4, min(int(fm.horizontalAdvance(" ")), 8))

    def showing_title_only(self) -> bool:
        """当前是否处于「仅显示 title」的初始默认态（默认项且未手动选择过）。"""
        return (
            bool(self._title)
            and self._title_only
            and self._current_index <= 0
        )

    def content_width(self) -> int:
        """无框标题模式下的紧凑宽度：较宽行文本宽 + 左右对称留白。

        文字行以控件中心为轴居中，箭头紧跟较宽行的右端，
        宽度保证左右观感对称且箭头不越界。
        """
        title_font, value_font = self._fonts()
        if self._title:
            if self.showing_title_only():
                lines = [(value_font, self._title or "")]
            else:
                lines = [
                    (title_font, self._title or ""),
                    (value_font, self.currentText() or ""),
                ]
        else:
            lines = [(value_font, self.currentText() or "")]
        maxw = 0
        for font, t in lines:
            fm = QFontMetrics(font)
            maxw = max(maxw, fm.horizontalAdvance(t))
        return max(self._SIDE * 2 + maxw, 30)

    def update_size_to_content(self) -> None:
        """按当前内容自动设置紧凑宽度（仅无框标题模式生效）。"""
        if not self._title:
            return
        self.setFixedWidth(self.content_width())
        self.update()

    def setCurrentText(self, text: str):
        if text in self._items:
            self._current_index = self._items.index(text)
            self.current_index_changed.emit(self._current_index)
            self.update()

    def count(self) -> int:
        return len(self._items)

    def sizeHint(self):
        cfg = self.SIZE_CONFIG[self._size]
        if self._title:
            return QSize(self.content_width(), self.height())
        fm = QApplication.fontMetrics()
        text = self.currentText() or "..."
        w = cfg["h_pad"] * 2 + fm.horizontalAdvance(text) + 30
        return QSize(w, cfg["height"])

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value not in self.SIZE_CONFIG:
            return
        self._size = value
        self.setFixedHeight(self.SIZE_CONFIG[value]["height"])
        self.update()

    # ── paint ──────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        cfg = self.SIZE_CONFIG[self._size]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        rad = cfg["rad"]
        accent = tm.accent

        if not self._flat:
            # Background — smooth hover transition
            # 保持 alpha，作为半透明叠加层绘制，不要变成不透明的实色块
            bg = tm.alpha_of(tm.mid, 12 + 10 * self._hover_progress)

            p.setPen(Qt.NoPen)

            p.setBrush(bg)
            p.drawRoundedRect(QRectF(0, 0, w, h), rad, rad)

            # Border
            border_default = tm.mid
            text_tertiary = tm.alpha_of(tm.mid, 60)
            if self._open:
                border = accent
            else:
                r = int(border_default.red() + (text_tertiary.red() - border_default.red()) * self._hover_progress)
                g = int(border_default.green() + (text_tertiary.green() - border_default.green()) * self._hover_progress)
                b = int(border_default.blue() + (text_tertiary.blue() - border_default.blue()) * self._hover_progress)
                border = QColor(r, g, b)

            pen = QPen(border, 1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), rad, rad)

        text = self.currentText()
        title_font, value_font = self._fonts()
        chev_cx = w - cfg["h_pad"] - 10

        if text and self._title:
            # ── 无框标题模式：无背景边框，文字行以控件中心为轴居中，
            #    小三角紧跟较宽行右端（正常间距）──
            gap = self._chevron_gap()
            sz = 5
            title_fm = QFontMetrics(title_font)
            value_fm = QFontMetrics(value_font)
            if self.showing_title_only():
                # 初始默认态：仅显示 title（如“格式”）+ 小三角
                maxw = value_fm.horizontalAdvance(self._title)
                p.setFont(value_font)
                p.setPen(tm.text)
                p.drawText(
                    QRectF(0, 0, w, h),
                    Qt.AlignVCenter | Qt.AlignHCenter,
                    self._title,
                )
            else:
                # 用户选择后：双行 title / 当前项（两行同轴居中）
                maxw = max(
                    title_fm.horizontalAdvance(self._title),
                    value_fm.horizontalAdvance(text),
                )
                p.setFont(title_font)
                p.setPen(tm.alpha_of(tm.mid, 150))
                p.drawText(
                    QRectF(0, 0, w, h * 0.5),
                    Qt.AlignVCenter | Qt.AlignHCenter,
                    self._title,
                )
                p.setFont(value_font)
                p.setPen(tm.text)
                p.drawText(
                    QRectF(0, h * 0.52, w, h * 0.48),
                    Qt.AlignVCenter | Qt.AlignHCenter,
                    text,
                )
            # 箭头：文字块右端（较宽行）右侧一个正常间距，最右留 4px
            chev_cx = min(
                w / 2.0 + maxw / 2.0 + gap + sz,
                w - 4.0,
            )
        elif text:
            arrow_x = w - cfg["h_pad"] - 22
            tw = arrow_x - cfg["h_pad"] - 4
            p.setFont(value_font)
            p.setPen(tm.text)
            p.drawText(
                QRectF(cfg["h_pad"], 0, max(tw, 0), h),
                Qt.AlignVCenter | Qt.AlignLeft,
                text,
            )

        # Chevron — rotate 180° on open
        cy = h / 2.0
        sz = 5.0

        p.save()
        p.translate(chev_cx, cy)
        angle = 180.0 * self._chevron_progress
        p.rotate(angle)
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        tri = QPolygonF([
            QPoint(-sz, -2),
            QPoint(0, sz - 1),
            QPoint(sz, -2),
        ])
        p.drawPolygon(tri)
        p.restore()

        p.end()

    # ── mouse / hover ──────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
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

    # ── popup management ───────────────────────────────────

    def _toggle(self):
        if self._open:
            self._close()
        else:
            self._open_popup()

    def _open_popup(self):
        self._open = True
        self._animate_chevron(1.0)
        self.update()

        popup = _ComboPopup(self._items, self._current_index, self._size, self.width(), self._align_right)
        popup.item_selected.connect(self._on_item_selected)
        self._popup = popup

        # Install app-level filter to detect clicks outside popup
        if not self._app_filter_installed:
            QApplication.instance().installEventFilter(self)
            self._app_filter_installed = True

        anchor = self.mapToGlobal(QPoint(0, self.height() + 2))
        popup.show_animated(anchor)

    def _close(self):
        if self._popup:
            self._popup.close_animated()
            self._popup = None
        self._open = False
        self._animate_chevron(0.0)
        self.update()

    def _on_item_selected(self, index: int):
        if index == -1:
            # Popup dismissed externally (click outside, etc.)
            self._open = False
            self._animate_chevron(0.0)
            self._popup = None
            self.update()
            return
        self._current_index = index
        # 用户在下拉中做出过选择（含再次选择默认项）后，
        # 不再退回“仅显示 title”的初始默认态。
        self._title_only = False
        self.current_index_changed.emit(index)
        self.selection_made.emit(self.currentText())
        self._close()

    def _animate_chevron(self, target: float):
        self._chevron_anim.stop()
        self._chevron_anim.setStartValue(self._chevron_progress)
        self._chevron_anim.setEndValue(target)
        self._chevron_anim.start()

    def eventFilter(self, obj, event):
        """App-level filter: close popup when clicking outside it."""
        if self._open and self._popup and event.type() in (QEvent.MouseButtonPress, QEvent.TouchBegin):
            if isinstance(event, QMouseEvent):
                global_pos = event.globalPosition().toPoint()
                # Check if click is on the trigger itself — let it through
                # so _toggle() handles the close
                if self.rect().contains(self.mapFromGlobal(global_pos)):
                    return False
                # Check if click is inside the popup — let it through
                if self._popup.rect().contains(self._popup.mapFromGlobal(global_pos)):
                    return False
                # Click is outside both — close popup
                self._close()
                return True
        return super().eventFilter(obj, event)
