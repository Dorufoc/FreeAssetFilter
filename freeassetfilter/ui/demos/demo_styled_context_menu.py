"""StyledContextMenu Demo — showcases all menu item types."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from theme import tm

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, QPoint

from components.styled_context_menu import StyledContextMenu


class StyledContextMenuDemo(QWidget):
    """Main demo window for StyledContextMenu."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledContextMenu Demo")
        self.resize(640, 520)

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

    # ── UI helpers ───────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 15px; font-weight: 600;"
            f" color: {tm.text.name()}; margin-top: 8px; margin-bottom: 4px;"
        )
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

    def _log(self, msg: str):
        self._log_label.setText(f"Log: {msg}")

    # ── Menu builders ────────────────────────────────────────────

    def _build_basic_menu(self) -> StyledContextMenu:
        """Menu with basic edit actions — shortcuts and separator."""
        menu = StyledContextMenu()
        menu.add_item(
            "Copy", shortcut="Ctrl+C",
            callback=lambda: self._log("Copy"),
        )
        menu.add_item(
            "Cut", shortcut="Ctrl+X",
            callback=lambda: self._log("Cut"),
        )
        menu.add_item(
            "Paste", shortcut="Ctrl+V",
            callback=lambda: self._log("Paste"),
        )
        menu.add_separator()
        menu.add_item(
            "Undo", shortcut="Ctrl+Z",
            callback=lambda: self._log("Undo"),
        )
        menu.add_item(
            "Redo", shortcut="Ctrl+Y",
            callback=lambda: self._log("Redo"),
        )
        return menu

    def _build_export_menu(self) -> StyledContextMenu:
        """Menu with a nested submenu (Export as…)."""
        menu = StyledContextMenu()
        menu.add_item(
            "Rename", shortcut="F2",
            callback=lambda: self._log("Rename"),
        )
        menu.add_separator()

        sub = StyledContextMenu()
        sub.add_item(
            "PDF",
            callback=lambda: self._log("Export PDF"),
        )
        sub.add_item(
            "PNG", callback=lambda: self._log("Export PNG"),
        )
        sub.add_item(
            "SVG",
            callback=lambda: self._log("Export SVG"),
        )
        menu.add_submenu("Export as…", sub)

        menu.add_item(
            "Share", shortcut="Ctrl+S",
            callback=lambda: self._log("Share"),
        )
        return menu

    def _build_view_menu(self) -> StyledContextMenu:
        """Menu with checkable items."""
        menu = StyledContextMenu()
        menu.add_item(
            "Show Grid", checkable=True, checked=True,
            callback=lambda: self._log("Toggle Grid"),
        )
        menu.add_item(
            "Show Ruler", checkable=True, checked=True,
            callback=lambda: self._log("Toggle Ruler"),
        )
        menu.add_item(
            "Show Guides", checkable=True,
            callback=lambda: self._log("Toggle Guides"),
        )
        menu.add_separator()
        menu.add_item(
            "Full-Screen Preview",
            callback=lambda: self._log("Full Screen"),
        )
        return menu

    def _build_file_menu(self) -> StyledContextMenu:
        """Menu with disabled + danger items."""
        menu = StyledContextMenu()
        menu.add_item(
            "Open", shortcut="Ctrl+O",
            callback=lambda: self._log("Open"),
        )
        menu.add_item(
            "Save As", shortcut="Ctrl+S",
            callback=lambda: self._log("Save As"),
        )
        menu.add_separator()
        menu.add_item(
            "Print", disabled=True,
        )
        menu.add_separator()
        menu.add_item(
            "Delete", shortcut="Del",
            danger=True, callback=lambda: self._log("Delete"),
        )
        return menu

    def _build_align_menu(self) -> StyledContextMenu:
        """Menu with radio-style items (group label + exclusive choices)."""
        menu = StyledContextMenu()

        # Group label (non-interactive item styled as a section header)
        header = menu.add_item(
            "ALIGNMENT",
            disabled=True,
        )

        # Radio-group items — only one active at a time via a shared callback
        self._align_value = "left"

        def set_align(val: str):
            self._align_value = val
            self._log(f"Align: {val}")

        menu.add_item(
            "Left", checkable=True,
            checked=self._align_value == "left",
            callback=lambda: set_align("left"),
        )
        menu.add_item(
            "Center", checkable=True,
            checked=self._align_value == "center",
            callback=lambda: set_align("center"),
        )
        menu.add_item(
            "Right", checkable=True,
            checked=self._align_value == "right",
            callback=lambda: set_align("right"),
        )
        return menu

    # ── Setup UI ─────────────────────────────────────────────────

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

        # ── Title ──────────────────────────────────────────────
        title = QLabel("StyledContextMenu Demo")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {tm.text.name()};"
        )
        main_layout.addWidget(title)

        desc = QLabel(
            "Click any button to open a context menu. "
            "Each menu demonstrates a different item type."
        )
        desc.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        main_layout.addWidget(desc)

        # ── Section 1: Basic items ─────────────────────────────
        main_layout.addWidget(self._section_label("1. Basic Items"))
        main_layout.addWidget(self._section_desc(
            "Keyboard shortcuts and separators"
        ))

        row1 = QHBoxLayout()
        btn_basic = QPushButton("Basic Menu")
        btn_basic.setStyleSheet(self._button_style())
        basic_menu = self._build_basic_menu()
        btn_basic.clicked.connect(
            lambda: basic_menu.exec(
                btn_basic.mapToGlobal(QPoint(0, btn_basic.height()))
            )
        )
        row1.addWidget(btn_basic)

        btn_export = QPushButton("Submenu")
        btn_export.setStyleSheet(self._button_style())
        export_menu = self._build_export_menu()
        btn_export.clicked.connect(
            lambda: export_menu.exec(
                btn_export.mapToGlobal(QPoint(0, btn_export.height()))
            )
        )
        row1.addWidget(btn_export)
        row1.addStretch()
        main_layout.addLayout(row1)
        main_layout.addWidget(self._separator())

        # ── Section 2: Checkable items ─────────────────────────
        main_layout.addWidget(self._section_label("2. Checkable Items"))
        main_layout.addWidget(self._section_desc(
            "Toggle items with checkable=True (checkmark indicator)"
        ))

        row2 = QHBoxLayout()
        btn_view = QPushButton("View Menu")
        btn_view.setStyleSheet(self._button_style())
        view_menu = self._build_view_menu()
        btn_view.clicked.connect(
            lambda: view_menu.exec(
                btn_view.mapToGlobal(QPoint(0, btn_view.height()))
            )
        )
        row2.addWidget(btn_view)
        row2.addStretch()
        main_layout.addLayout(row2)
        main_layout.addWidget(self._separator())

        # ── Section 3: Disabled & Danger ───────────────────────
        main_layout.addWidget(self._section_label("3. Disabled & Danger Items"))
        main_layout.addWidget(self._section_desc(
            "Disabled item (gray, non-interactive), "
            "danger item (red text #ef4444)"
        ))

        row3 = QHBoxLayout()
        btn_file = QPushButton("File Menu")
        btn_file.setStyleSheet(self._button_style())
        file_menu = self._build_file_menu()
        btn_file.clicked.connect(
            lambda: file_menu.exec(
                btn_file.mapToGlobal(QPoint(0, btn_file.height()))
            )
        )
        row3.addWidget(btn_file)

        btn_align = QPushButton("Align")
        btn_align.setStyleSheet(self._button_style())
        align_menu = self._build_align_menu()
        btn_align.clicked.connect(
            lambda: align_menu.exec(
                btn_align.mapToGlobal(QPoint(0, btn_align.height()))
            )
        )
        row3.addWidget(btn_align)
        row3.addStretch()
        main_layout.addLayout(row3)
        main_layout.addWidget(self._separator())

        # ── Section 4: Right-click area ────────────────────────
        main_layout.addWidget(self._section_label("4. Right-click Area"))
        main_layout.addWidget(self._section_desc(
            "Right-click the dark area below to open the basic menu"
        ))

        area = QFrame()
        area.setStyleSheet(f"""
            QFrame {{
                background-color: {tm.surface.name()};
                border: 1px dashed {tm.mid.name()};
                border-radius: 8px;
            }}
        """)
        area.setMinimumHeight(120)
        area.setContextMenuPolicy(Qt.CustomContextMenu)
        area.customContextMenuRequested.connect(
            lambda pos: self._build_basic_menu().exec(
                area.mapToGlobal(pos)
            )
        )

        area_layout = QVBoxLayout(area)
        area_layout.setAlignment(Qt.AlignCenter)
        area_label = QLabel("Right-click here to open context menu")
        area_label.setAlignment(Qt.AlignCenter)
        area_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 13px; border: none;")
        area_layout.addWidget(area_label)
        main_layout.addWidget(area)
        main_layout.addWidget(self._separator())

        # ── Log ────────────────────────────────────────────────
        self._log_label = QLabel("Log: waiting for action…")
        self._log_label.setStyleSheet(
            f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; padding: 4px 0;"
        )
        main_layout.addWidget(self._log_label)
        main_layout.addStretch()

        # Outer scroll layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _button_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                border: 1px solid {tm.mid.name()};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
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


def main():
    app = QApplication(sys.argv)
    demo = StyledContextMenuDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
