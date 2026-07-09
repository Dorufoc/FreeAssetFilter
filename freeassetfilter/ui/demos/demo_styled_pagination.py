"""StyledPagination Demo — standalone demo showcasing all pagination features."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QSizePolicy,
    QPushButton,
    QScrollArea,
)
from PySide6.QtCore import Qt

from theme import tm

from components.styled_pagination import StyledPagination, SIZE_CONFIG


class StyledPaginationDemo(QWidget):
    """Main demo window for StyledPagination."""

    DEMO_TOTAL_ITEMS   = 100
    DEMO_PAGE_SIZE     = 10

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledPagination Demo")
        self.resize(820, 620)
        self._setup_ui()
        self._apply_theme()

    # ── Theme ────────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
        """)

    # ── UI helpers ───────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {tm.text.name()}; "
            f"margin-top: 8px; margin-bottom: 4px;"
        )
        return label

    def _section_desc(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;")
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(
            f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;"
        )
        return line

    def _row_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 60px;"
        )
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        return label

    # ── Signal display helpers ───────────────────────────────────

    def _make_log_area(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(2)
        return layout

    def _log_signal(self, text: str):
        log = QLabel(text)
        log.setStyleSheet(
            f"font-size: 12px; color: {tm.accent.name()}; padding: 1px 0px;"
        )
        self._signal_log_layout.addWidget(log)
        # Auto-scroll: remove oldest entries if too many
        while self._signal_log_layout.count() > 20:
            item = self._signal_log_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ── Build UI ─────────────────────────────────────────────────

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")

        content = QWidget()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(32, 24, 32, 24)
        main_layout.setSpacing(16)

        # ── Section 1: Basic pagination (10 pages, sm) ──────────
        main_layout.addWidget(self._section_label("1. Size: sm (10 pages, 100 items)"))
        main_layout.addWidget(
            self._section_desc(
                "Prev/Next, page buttons with smart ellipsis, info text, size selector"
            )
        )

        row1 = QHBoxLayout()
        row1.addWidget(self._row_label("sm"))
        self._pagination_sm = StyledPagination(
            total_pages=self.DEMO_TOTAL_ITEMS // self.DEMO_PAGE_SIZE,
            current_page=1,
            total_items=self.DEMO_TOTAL_ITEMS,
            page_size=self.DEMO_PAGE_SIZE,
            size="sm",
            show_info=True,
            show_size_selector=True,
        )
        self._pagination_sm.page_changed.connect(
            lambda p: self._on_page_changed("sm", p)
        )
        self._pagination_sm.page_size_changed.connect(
            lambda s: self._on_page_size_changed("sm", s)
        )
        row1.addWidget(self._pagination_sm)
        row1.addStretch()
        main_layout.addLayout(row1)
        main_layout.addWidget(self._separator())

        # ── Section 2: Default size ──────────────────────────────
        main_layout.addWidget(self._section_label("2. Size: default (10 pages, 100 items)"))
        main_layout.addWidget(
            self._section_desc("Default 32px buttons, 13px font")
        )

        row2 = QHBoxLayout()
        row2.addWidget(self._row_label("default"))
        self._pagination_default = StyledPagination(
            total_pages=self.DEMO_TOTAL_ITEMS // self.DEMO_PAGE_SIZE,
            current_page=5,
            total_items=self.DEMO_TOTAL_ITEMS,
            page_size=self.DEMO_PAGE_SIZE,
            size="default",
            show_info=True,
            show_size_selector=True,
        )
        self._pagination_default.page_changed.connect(
            lambda p: self._on_page_changed("default", p)
        )
        self._pagination_default.page_size_changed.connect(
            lambda s: self._on_page_size_changed("default", s)
        )
        row2.addWidget(self._pagination_default)
        row2.addStretch()
        main_layout.addLayout(row2)
        main_layout.addWidget(self._separator())

        # ── Section 3: Large size ────────────────────────────────
        main_layout.addWidget(self._section_label("3. Size: lg (10 pages, 100 items)"))
        main_layout.addWidget(
            self._section_desc("Large 40px buttons, 15px font")
        )

        row3 = QHBoxLayout()
        row3.addWidget(self._row_label("lg"))
        self._pagination_lg = StyledPagination(
            total_pages=self.DEMO_TOTAL_ITEMS // self.DEMO_PAGE_SIZE,
            current_page=10,
            total_items=self.DEMO_TOTAL_ITEMS,
            page_size=self.DEMO_PAGE_SIZE,
            size="lg",
            show_info=True,
            show_size_selector=True,
        )
        self._pagination_lg.page_changed.connect(
            lambda p: self._on_page_changed("lg", p)
        )
        self._pagination_lg.page_size_changed.connect(
            lambda s: self._on_page_size_changed("lg", s)
        )
        row3.addWidget(self._pagination_lg)
        row3.addStretch()
        main_layout.addLayout(row3)
        main_layout.addWidget(self._separator())

        # ── Section 4: Edge cases ────────────────────────────────
        main_layout.addWidget(self._section_label("4. Edge Cases"))
        main_layout.addWidget(
            self._section_desc("Minimal (1 page), hidden info, hidden size selector")
        )

        # Single page (no navigation needed)
        row4a = QHBoxLayout()
        row4a.addWidget(self._row_label("1 page"))
        pagination_1 = StyledPagination(
            total_pages=1, current_page=1, total_items=3, page_size=3,
            size="default",
        )
        row4a.addWidget(pagination_1)
        row4a.addStretch()
        main_layout.addLayout(row4a)

        # No info text
        row4b = QHBoxLayout()
        row4b.addWidget(self._row_label("no info"))
        pagination_no_info = StyledPagination(
            total_pages=5, current_page=3, total_items=50, page_size=10,
            size="default",
            show_info=False,
        )
        row4b.addWidget(pagination_no_info)
        row4b.addStretch()
        main_layout.addLayout(row4b)

        # No size selector
        row4c = QHBoxLayout()
        row4c.addWidget(self._row_label("no size"))
        pagination_no_size = StyledPagination(
            total_pages=5, current_page=3, total_items=50, page_size=10,
            size="default",
            show_size_selector=False,
        )
        row4c.addWidget(pagination_no_size)
        row4c.addStretch()
        main_layout.addLayout(row4c)

        # Many pages (smart ellipsis showcase)
        row4d = QHBoxLayout()
        row4d.addWidget(self._row_label("20 pages"))
        pagination_20 = StyledPagination(
            total_pages=20, current_page=10, total_items=200, page_size=10,
            size="sm",
        )
        row4d.addWidget(pagination_20)
        row4d.addStretch()
        main_layout.addLayout(row4d)

        # Page 1 of many
        row4e = QHBoxLayout()
        row4e.addWidget(self._row_label("pg 1/20"))
        pagination_start = StyledPagination(
            total_pages=20, current_page=1, total_items=200, page_size=10,
            size="sm",
        )
        row4e.addWidget(pagination_start)
        row4e.addStretch()
        main_layout.addLayout(row4e)

        # Last page of many
        row4f = QHBoxLayout()
        row4f.addWidget(self._row_label("pg 20/20"))
        pagination_end = StyledPagination(
            total_pages=20, current_page=20, total_items=200, page_size=10,
            size="sm",
        )
        row4f.addWidget(pagination_end)
        row4f.addStretch()
        main_layout.addLayout(row4f)

        main_layout.addWidget(self._separator())

        # ── Section 5: Interactive controls ──────────────────────
        main_layout.addWidget(self._section_label("5. Interactive Controls"))
        main_layout.addWidget(
            self._section_desc(
                "Use buttons to programmatically change the demo pagination"
            )
        )

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)

        self._page_input_label = QLabel("Go to page:")
        self._page_input_label.setStyleSheet(
            f"font-size: 12px; color: {tm.mid.name()};"
        )
        controls_row.addWidget(self._page_input_label)

        self._page_input = QPushButton("5")
        self._page_input.setFixedWidth(50)
        self._page_input.setStyleSheet(self._mini_button_style())
        self._page_input.clicked.connect(self._on_jump_to_page)
        controls_row.addWidget(self._page_input)

        btn_prev_page = QPushButton("Prev Page")
        btn_prev_page.setStyleSheet(self._mini_button_style())
        btn_prev_page.clicked.connect(self._on_prev_page)
        controls_row.addWidget(btn_prev_page)

        btn_next_page = QPushButton("Next Page")
        btn_next_page.setStyleSheet(self._mini_button_style())
        btn_next_page.clicked.connect(self._on_next_page)
        controls_row.addWidget(btn_next_page)

        btn_change_total = QPushButton("Set 3 pages")
        btn_change_total.setStyleSheet(self._mini_button_style())
        btn_change_total.clicked.connect(self._on_set_three_pages)
        controls_row.addWidget(btn_change_total)

        btn_reset = QPushButton("Reset")
        btn_reset.setStyleSheet(self._mini_button_style())
        btn_reset.clicked.connect(self._on_reset)
        controls_row.addWidget(btn_reset)

        controls_row.addStretch()
        main_layout.addLayout(controls_row)

        main_layout.addWidget(self._separator())

        # ── Section 6: Signal log ────────────────────────────────
        main_layout.addWidget(self._section_label("6. Signal Log"))
        main_layout.addWidget(
            self._section_desc("Emitted page_changed / page_size_changed signals")
        )

        self._signal_log_layout = self._make_log_area()
        main_layout.addLayout(self._signal_log_layout)
        self._log_signal("← Ready. Click a page button or use controls above.")

        main_layout.addStretch()

        # Outer scroll layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Button style for controls ────────────────────────────────

    def _mini_button_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                border-color: {tm.alpha_of(tm.mid, 40).name()};
            }}
            QPushButton:pressed {{
                background-color: {tm.surface.name()};
            }}
        """

    # ── Signal handlers ──────────────────────────────────────────

    def _on_page_changed(self, size_label: str, page: int):
        self._log_signal(
            f"[{size_label}] page_changed({page})"
        )

    def _on_page_size_changed(self, size_label: str, size: int):
        self._log_signal(
            f"[{size_label}] page_size_changed({size})  —  page reset to 1"
        )

    def _on_jump_to_page(self):
        # Jump the default-size pagination to the button's text value
        try:
            page = int(self._page_input.text())
        except ValueError:
            page = 1
        self._pagination_default.current_page = page

    def _on_prev_page(self):
        self._pagination_default.current_page = (
            self._pagination_default.current_page - 1
            if self._pagination_default.current_page > 1
            else 1
        )

    def _on_next_page(self):
        self._pagination_default.current_page = (
            self._pagination_default.current_page + 1
            if self._pagination_default.current_page < self._pagination_default.total_pages
            else self._pagination_default.total_pages
        )

    def _on_set_three_pages(self):
        self._pagination_default.total_pages = 3

    def _on_reset(self):
        self._pagination_sm.current_page = 1
        self._pagination_default.current_page = 5
        self._pagination_lg.current_page = 10
        self._log_signal("← Reset all paginations to defaults")


def main():
    app = QApplication(sys.argv)
    demo = StyledPaginationDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
