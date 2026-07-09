"""StyledBreadcrumb Demo - standalone demo showcasing all breadcrumb features."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from theme import tm

from components.styled_breadcrumb import StyledBreadcrumb


class StyledBreadcrumbDemo(QWidget):
    """Main demo window for StyledBreadcrumb."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledBreadcrumb Demo")
        self.resize(720, 620)

        self._setup_ui()
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
        """)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 600;
            color: {tm.text.name()};
            margin-top: 8px;
            margin-bottom: 4px;
        """)
        return label

    def _section_desc(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;")
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;")
        return line

    def _row_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 60px;")
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        return label

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

        # ── Section 1: Default ─────────────────────────────────
        main_layout.addWidget(self._section_label("1. Default"))
        main_layout.addWidget(self._section_desc("3-level breadcrumb with default size"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        bc1 = StyledBreadcrumb()
        bc1.add_item("Home", callback=lambda: print("Clicked: Home"))
        bc1.add_item("Products", callback=lambda: print("Clicked: Products"))
        bc1.add_item("Category")
        row.addWidget(bc1)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 2: Size Variants ───────────────────────────
        main_layout.addWidget(self._section_label("2. Size Variants"))
        main_layout.addWidget(self._section_desc("Small, default, and large sizes"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Small"))
        bc_sm = StyledBreadcrumb(size="sm")
        bc_sm.add_item("Home", callback=lambda: print("[sm] Clicked: Home"))
        bc_sm.add_item("Products", callback=lambda: print("[sm] Clicked: Products"))
        bc_sm.add_item("Category")
        row.addWidget(bc_sm)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        bc_def = StyledBreadcrumb(size="default")
        bc_def.add_item("Home", callback=lambda: print("[default] Clicked: Home"))
        bc_def.add_item("Products", callback=lambda: print("[default] Clicked: Products"))
        bc_def.add_item("Category")
        row.addWidget(bc_def)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Large"))
        bc_lg = StyledBreadcrumb(size="lg")
        bc_lg.add_item("Home", callback=lambda: print("[lg] Clicked: Home"))
        bc_lg.add_item("Products", callback=lambda: print("[lg] Clicked: Products"))
        bc_lg.add_item("Category")
        row.addWidget(bc_lg)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 3: Background Variant ──────────────────────
        main_layout.addWidget(self._section_label("3. Background Variant"))
        main_layout.addWidget(self._section_desc("Breadcrumb with background container and border"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Background"))
        bc_bg = StyledBreadcrumb(background=True)
        bc_bg.add_item("Home", callback=lambda: print("[bg] Clicked: Home"))
        bc_bg.add_item("Products", callback=lambda: print("[bg] Clicked: Products"))
        bc_bg.add_item("Category")
        row.addWidget(bc_bg)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 4: Icon Support ────────────────────────────
        main_layout.addWidget(self._section_label("4. Icon Support"))
        main_layout.addWidget(self._section_desc("Breadcrumb items with home and folder icons"))

        # Inline SVG path data strings — home icon (house) and folder icon
        HOME_ICON = "M12 3L2 12h3v8h6v-6h2v6h6v-8h3L12 3z"
        FOLDER_ICON = (
            "M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16"
            "c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"
        )

        row = QHBoxLayout()
        row.addWidget(self._row_label("With Icons"))
        bc_icon = StyledBreadcrumb()
        bc_icon.add_item("Home", callback=lambda: print("[icon] Clicked: Home"), icon=HOME_ICON)
        bc_icon.add_item("Documents", callback=lambda: print("[icon] Clicked: Documents"), icon=FOLDER_ICON)
        bc_icon.add_item("Reports", callback=lambda: print("[icon] Clicked: Reports"), icon=FOLDER_ICON)
        bc_icon.add_item("Q4 2026")
        row.addWidget(bc_icon)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 5: Event Demo ──────────────────────────────
        main_layout.addWidget(self._section_label("5. Event Demo"))
        main_layout.addWidget(self._section_desc(
            "Breadcrumb with navigated signal connected to status label"
        ))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Events"))
        self._event_bc = StyledBreadcrumb(background=True)
        self._event_bc.add_item("Home", callback=lambda: print("[event] Clicked: Home"))
        self._event_bc.add_item("Products", callback=lambda: print("[event] Clicked: Products"))
        self._event_bc.add_item("Accessories", callback=lambda: print("[event] Clicked: Accessories"))
        self._event_bc.add_item("Headphones")
        self._event_bc.navigated.connect(self._on_navigated)
        row.addWidget(self._event_bc)
        row.addStretch()
        main_layout.addLayout(row)

        self._status_label = QLabel("Click a breadcrumb item...")
        self._status_label.setStyleSheet(f"""
            font-size: 13px;
            color: {tm.mid.name()};
            padding: 4px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)
        main_layout.addWidget(self._status_label)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_navigated(self, index: int, text: str):
        self._status_label.setText(f"Navigated to: {text}")
        self._status_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 600;
            color: {tm.accent.name()};
            padding: 4px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)


def main():
    app = QApplication(sys.argv)
    demo = StyledBreadcrumbDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
