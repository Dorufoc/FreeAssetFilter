"""Styled Pagination component - matches web pagination exactly."""

from typing import Optional

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QComboBox
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPaintEvent

from theme import tm


SIZE_CONFIG = {
    "sm": {"btn_size": 26, "font_size": 11, "prev_pad": 10, "info_font": 11, "radius": 4},
    "default": {"btn_size": 32, "font_size": 13, "prev_pad": 12, "info_font": 12, "radius": 6},
    "lg": {"btn_size": 40, "font_size": 15, "prev_pad": 14, "info_font": 13, "radius": 8},
}

PAGE_SIZE_OPTIONS = [10, 20, 50, 100]


class _PageButton(QPushButton):
    """Internal page number button with custom QPainter rendering."""

    def __init__(
        self,
        text: str,
        page: int = 0,
        is_active: bool = False,
        is_ellipsis: bool = False,
        btn_size: int = 32,
        font_size: int = 13,
        radius: int = 6,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self._page = page
        self._is_active = is_active
        self._is_ellipsis = is_ellipsis
        self._btn_size = btn_size
        self._font_size = font_size
        self._radius = radius
        self._hovered = False

        self.setFixedSize(btn_size, btn_size)
        self.setFlat(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.ArrowCursor if is_ellipsis else Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

    # ── Theme color properties ─────────────────────────────────

    @property
    def _color_bg(self): return tm.alpha_of(tm.mid, 40)

    @property
    def _color_bg_hover(self): return tm.alpha_of(tm.mid, 50)

    @property
    def _color_bg_active(self): return tm.accent

    @property
    def _color_text(self): return tm.mid

    @property
    def _color_text_hover(self): return tm.text

    @property
    def _color_text_active(self): return tm.text

    @property
    def _color_text_ellipsis(self): return tm.alpha_of(tm.mid, 60)

    # ── Properties ───────────────────────────────────────────────

    @property
    def page(self) -> int:
        return self._page

    @property
    def is_active(self) -> bool:
        return self._is_active

    def set_active(self, active: bool) -> None:
        self._is_active = active
        self.update()

    # ── Events ───────────────────────────────────────────────────

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ── Paint ────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._is_ellipsis:
            self._paint_ellipsis(painter)
        else:
            self._paint_button(painter)

    def _paint_ellipsis(self, painter: QPainter):
        w, h = self.width(), self.height()
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(0, 0, w, h), self._radius, self._radius)
        painter.setPen(self._color_text_ellipsis)
        font = QFont("Microsoft YaHei UI", self._font_size, QFont.Normal)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self.text())

    def _paint_button(self, painter: QPainter):
        w, h = self.width(), self.height()

        if not self.isEnabled():
            painter.setOpacity(0.4)

        if self._is_active:
            bg = self._color_bg_active
            text_color = self._color_text_active
            font_weight = QFont.Medium
        elif self._hovered:
            bg = self._color_bg_hover
            text_color = self._color_text_hover
            font_weight = QFont.Normal
        else:
            bg = self._color_bg
            text_color = self._color_text
            font_weight = QFont.Normal

        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(0, 0, w, h), self._radius, self._radius)

        font = QFont("Microsoft YaHei UI", self._font_size, font_weight)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, self.text())


class StyledPagination(QWidget):
    """Pagination component matching the web design exactly.

    Provides page navigation with smart ellipsis, previous/next buttons,
    optional info text (e.g. "Showing 1-10 of 100"), and an optional
    page size selector (QComboBox).

    Signals:
        page_changed(page: int)        — emitted when the active page changes
        page_size_changed(size: int)   — emitted when the page size selection changes
    """

    page_changed = Signal(int)
    page_size_changed = Signal(int)

    # ── Theme color properties ─────────────────────────────────
    @property
    def COLOR_BG(self): return tm.alpha_of(tm.mid, 40)

    @property
    def COLOR_BG_HOVER(self): return tm.alpha_of(tm.mid, 50)

    @property
    def COLOR_BG_ACTIVE(self): return tm.accent

    @property
    def COLOR_TEXT(self): return tm.mid

    @property
    def COLOR_TEXT_HOVER(self): return tm.text

    @property
    def COLOR_TEXT_ACTIVE(self): return tm.text

    @property
    def COLOR_TEXT_ELLIPSIS(self): return tm.alpha_of(tm.mid, 60)

    def __init__(
        self,
        total_pages: int = 1,
        current_page: int = 1,
        total_items: int = 0,
        page_size: int = 10,
        size: str = "default",
        show_info: bool = True,
        show_size_selector: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._total_pages = max(1, total_pages)
        self._current_page = max(1, min(current_page, self._total_pages))
        self._total_items = total_items
        self._page_size = page_size if page_size in PAGE_SIZE_OPTIONS else PAGE_SIZE_OPTIONS[0]
        self._size = size if size in SIZE_CONFIG else "default"
        self._show_info = show_info
        self._show_size_selector = show_size_selector

        self.setAttribute(Qt.WA_StyledBackground, False)

        # ── Info label ───────────────────────────────────────────
        self._info_label = QLabel()
        self._info_label.setVisible(False)

        # ── Page size combo ──────────────────────────────────────
        self._size_combo = QComboBox()
        self._size_combo.addItems([str(s) for s in PAGE_SIZE_OPTIONS])
        self._size_combo.setCurrentText(str(self._page_size))
        self._size_combo.currentTextChanged.connect(self._on_page_size_changed)

        # ── Layout ───────────────────────────────────────────────
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self._style_size_combo()
        self._rebuild()

    # ── Public API ───────────────────────────────────────────────

    @property
    def current_page(self) -> int:
        return self._current_page

    @current_page.setter
    def current_page(self, value: int):
        value = max(1, min(value, self._total_pages))
        if value != self._current_page:
            self._current_page = value
            self._rebuild()
            self.page_changed.emit(self._current_page)

    @property
    def total_pages(self) -> int:
        return self._total_pages

    @total_pages.setter
    def total_pages(self, value: int):
        value = max(1, value)
        if value != self._total_pages:
            self._total_pages = value
            self._current_page = max(1, min(self._current_page, self._total_pages))
            self._rebuild()

    @property
    def page_size(self) -> int:
        return self._page_size

    @page_size.setter
    def page_size(self, value: int):
        if value in PAGE_SIZE_OPTIONS and value != self._page_size:
            self._page_size = value
            self._size_combo.blockSignals(True)
            self._size_combo.setCurrentText(str(value))
            self._size_combo.blockSignals(False)
            self._rebuild()

    @property
    def size_variant(self) -> str:
        return self._size

    @size_variant.setter
    def size_variant(self, value: str):
        if value in SIZE_CONFIG and value != self._size:
            self._size = value
            self._style_size_combo()
            self._rebuild()

    @property
    def total_items(self) -> int:
        return self._total_items

    @total_items.setter
    def total_items(self, value: int):
        self._total_items = value
        self._update_info_text()

    @property
    def show_info(self) -> bool:
        return self._show_info

    @show_info.setter
    def show_info(self, value: bool):
        self._show_info = value
        self._update_info_text()

    @property
    def show_size_selector(self) -> bool:
        return self._show_size_selector

    @show_size_selector.setter
    def show_size_selector(self, value: bool):
        self._show_size_selector = value
        self._size_combo.setVisible(value)

    # ── Widget sizing ────────────────────────────────────────────

    def minimumSizeHint(self):
        return self.sizeHint()

    def sizeHint(self):
        config = SIZE_CONFIG[self._size]
        btn_w = config["btn_size"]
        total_btn_count = min(self._total_pages + 2, 9)  # pages + prev/next + ellipsis
        info_w = 0
        combo_w = 0

        if self._show_info and self._total_items > 0:
            info_w = 160
        if self._show_size_selector:
            combo_w = 80

        total_w = (
            total_btn_count * (btn_w + 4)  # 4px gap
            + info_w
            + combo_w
            + 4  # spacing between sections
        )
        return total_w, btn_w + 8

    # ── Internal helpers ─────────────────────────────────────────

    def _style_size_combo(self):
        config = SIZE_CONFIG[self._size]
        fs = config["info_font"]
        h = max(config["btn_size"] - 8, 20)
        bg = tm.surface.name()
        text = self.COLOR_TEXT.name()
        border = self.COLOR_TEXT.name()
        hover_border = self.COLOR_TEXT_ELLIPSIS.name()
        hover_bg = tm.alpha_of(tm.surface, 90).name()
        popup_bg = tm.surface.name()
        popup_selection_bg = self.COLOR_BG.name()
        popup_selection_text = self.COLOR_TEXT_HOVER.name()
        self._size_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 2px 20px 2px 8px;
                font-size: {fs}px;
                font-family: "Microsoft YaHei UI", sans-serif;
                min-height: {h}px;
            }}
            QComboBox:hover {{
                border-color: {hover_border};
                background-color: {hover_bg};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 18px;
            }}
            QComboBox::down-arrow {{
                width: 8px;
                height: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {popup_bg};
                color: {text};
                border: 1px solid {border};
                selection-background-color: {popup_selection_bg};
                selection-color: {popup_selection_text};
                font-size: {fs}px;
                font-family: "Microsoft YaHei UI", sans-serif;
                outline: none;
            }}
        """)

    def _get_page_numbers(self) -> list[tuple[str, Optional[int]]]:
        """Compute the list of page items with smart ellipsis.

        Returns a list of (type, value) tuples:
            - ("page", int)      — clickable page number button
            - ("ellipsis", None) — ellipsis indicator (not clickable)

        Strategy: always show first page, last page, and ±2 around
        the current page. Insert ellipsis markers where gaps > 1.
        """
        total = self._total_pages
        cur = self._current_page

        if total <= 7:
            # No ellipsis needed — show all pages
            return [("page", p) for p in range(1, total + 1)]

        items: list[tuple[str, Optional[int]]] = [("page", 1)]

        # Determine the visible window around current page
        window_start = max(2, cur - 2)
        window_end = min(total - 1, cur + 2)

        # Gap between page 1 and the window start
        if window_start > 2:
            items.append(("ellipsis", None))
        elif window_start == 2:
            items.append(("page", 2))

        # Window pages
        for p in range(window_start, window_end + 1):
            if 1 < p < total:
                items.append(("page", p))

        # Gap between window end and last page
        if window_end < total - 1:
            items.append(("ellipsis", None))
        elif window_end == total - 1 and total > 2:
            items.append(("page", total - 1))

        items.append(("page", total))
        return items

    def _update_info_text(self):
        config = SIZE_CONFIG[self._size]
        if self._show_info and self._total_items > 0:
            start = (self._current_page - 1) * self._page_size + 1
            end = min(self._current_page * self._page_size, self._total_items)
            self._info_label.setText(f"Showing {start}–{end} of {self._total_items}")
            info_color = self.COLOR_TEXT_ELLIPSIS.name()
            self._info_label.setStyleSheet(
                f"color: {info_color}; font-size: {config['info_font']}px; "
                f"font-family: 'Microsoft YaHei UI', sans-serif; "
                f"margin-left: 8px;"
            )
            self._info_label.setVisible(True)
        else:
            self._info_label.setVisible(False)

    def _rebuild(self):
        """Recreate all pagination buttons and re-append info/size widgets."""
        config = SIZE_CONFIG[self._size]
        self._layout.setSpacing(4)

        # Remove all widgets from layout; keep _info_label and _size_combo alive
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            w = item.widget()
            if w and w not in (self._info_label, self._size_combo):
                self._layout.removeItem(item)
                w.deleteLater()

        # ── Previous button ──────────────────────────────────────
        prev_btn = _PageButton(
            "‹", page=0, is_active=False, is_ellipsis=False,
            btn_size=config["btn_size"], font_size=config["font_size"] + 2,
            radius=config["radius"],
        )
        prev_btn.setEnabled(self._current_page > 1)
        prev_btn.clicked.connect(lambda: self._go_to_page(self._current_page - 1))
        prev_w = config["btn_size"] + config["prev_pad"] * 2
        prev_btn.setFixedWidth(prev_w)
        self._layout.addWidget(prev_btn)

        # ── Page buttons ─────────────────────────────────────────
        for item_type, page_num in self._get_page_numbers():
            if item_type == "ellipsis":
                btn = _PageButton(
                    "…", page=0, is_active=False, is_ellipsis=True,
                    btn_size=config["btn_size"], font_size=config["font_size"],
                    radius=config["radius"],
                )
                self._layout.addWidget(btn)
            else:
                is_active = page_num == self._current_page
                btn = _PageButton(
                    str(page_num), page=page_num, is_active=is_active,
                    btn_size=config["btn_size"], font_size=config["font_size"],
                    radius=config["radius"],
                )
                btn.clicked.connect(lambda checked, p=page_num: self._go_to_page(p))
                self._layout.addWidget(btn)

        # ── Next button ──────────────────────────────────────────
        next_btn = _PageButton(
            "›", page=0, is_active=False, is_ellipsis=False,
            btn_size=config["btn_size"], font_size=config["font_size"] + 2,
            radius=config["radius"],
        )
        next_btn.setEnabled(self._current_page < self._total_pages)
        next_btn.clicked.connect(lambda: self._go_to_page(self._current_page + 1))
        next_btn.setFixedWidth(prev_w)
        self._layout.addWidget(next_btn)

        # ── Info text & size selector ────────────────────────────
        self._update_info_text()
        self._layout.addWidget(self._info_label)
        self._layout.addWidget(self._size_combo)
        self._size_combo.setVisible(self._show_size_selector)
        self._layout.addStretch()

    def _go_to_page(self, page: int):
        """Navigate to *page* (1-indexed); clamps to valid range."""
        clamped = max(1, min(page, self._total_pages))
        if clamped != self._current_page:
            self._current_page = clamped
            self._rebuild()
            self.page_changed.emit(self._current_page)

    def _on_page_size_changed(self, text: str):
        new_size = int(text)
        if new_size != self._page_size:
            self._page_size = new_size
            self._rebuild()
            self.page_size_changed.emit(self._page_size)
