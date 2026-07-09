"""Standalone demo for the StyledButton component."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QGridLayout,
    QPushButton,
)
from PySide6.QtCore import Qt
from theme import tm
from components.styled_button import StyledButton


def make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"QFrame {{ color: {tm.alpha_of(tm.mid, 40).name()}; }}")
    line.setFixedHeight(1)
    return line


def make_section_header(text):
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {tm.text.name()}; margin-top: 8px;")
    return label


def make_button_label(text):
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-top: 2px;")
    return label


class StyledButtonDemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledButton Demo")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.resize(900, 700)

        self.setStyleSheet(
            f'QWidget {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; font-family: "Microsoft YaHei", sans-serif; }}'
            f"QLabel {{ color: {tm.mid.name()}; font-size: 12px; }}"
        )

        self._click_count = 0
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # ---- Variants ----
        main_layout.addWidget(make_section_header("Variants"))
        main_layout.addWidget(make_separator())
        variants_layout = QHBoxLayout()
        variants_layout.setSpacing(12)
        variants = ["primary", "secondary", "ghost", "danger", "info"]
        for v in variants:
            col = QVBoxLayout()
            col.setSpacing(4)
            btn = StyledButton(text=v.capitalize(), variant=v)
            col.addWidget(btn, alignment=Qt.AlignCenter)
            col.addWidget(make_button_label(v))
            variants_layout.addLayout(col)
        variants_layout.addStretch()
        main_layout.addLayout(variants_layout)

        # ---- Sizes (Primary) ----
        main_layout.addWidget(make_section_header("Sizes (Primary)"))
        main_layout.addWidget(make_separator())
        sizes_primary = QHBoxLayout()
        sizes_primary.setSpacing(12)
        for s in ["sm", "default", "lg"]:
            col = QVBoxLayout()
            col.setSpacing(4)
            btn = StyledButton(text=s.capitalize(), variant="primary", size=s)
            col.addWidget(btn, alignment=Qt.AlignCenter)
            col.addWidget(make_button_label(s))
            sizes_primary.addLayout(col)
        sizes_primary.addStretch()
        main_layout.addLayout(sizes_primary)

        # ---- Sizes (Secondary) ----
        main_layout.addWidget(make_section_header("Sizes (Secondary)"))
        main_layout.addWidget(make_separator())
        sizes_secondary = QHBoxLayout()
        sizes_secondary.setSpacing(12)
        for s in ["sm", "default", "lg"]:
            col = QVBoxLayout()
            col.setSpacing(4)
            btn = StyledButton(text=s.capitalize(), variant="secondary", size=s)
            col.addWidget(btn, alignment=Qt.AlignCenter)
            col.addWidget(make_button_label(s))
            sizes_secondary.addLayout(col)
        sizes_secondary.addStretch()
        main_layout.addLayout(sizes_secondary)

        # ---- States ----
        main_layout.addWidget(make_section_header("States"))
        main_layout.addWidget(make_separator())
        states_layout = QHBoxLayout()
        states_layout.setSpacing(12)

        col1 = QVBoxLayout()
        col1.setSpacing(4)
        btn_normal = StyledButton(text="Normal", variant="primary")
        col1.addWidget(btn_normal, alignment=Qt.AlignCenter)
        col1.addWidget(make_button_label("normal"))
        states_layout.addLayout(col1)

        col2 = QVBoxLayout()
        col2.setSpacing(4)
        btn_disabled = StyledButton(text="Disabled", variant="primary")
        btn_disabled.setEnabled(False)
        col2.addWidget(btn_disabled, alignment=Qt.AlignCenter)
        col2.addWidget(make_button_label("disabled"))
        states_layout.addLayout(col2)

        col3 = QVBoxLayout()
        col3.setSpacing(4)
        btn_loading = StyledButton(text="Loading", variant="primary", loading=True)
        col3.addWidget(btn_loading, alignment=Qt.AlignCenter)
        col3.addWidget(make_button_label("loading"))
        states_layout.addLayout(col3)

        states_layout.addStretch()
        main_layout.addLayout(states_layout)

        # ---- Icon Buttons ----
        main_layout.addWidget(make_section_header("Icon Buttons"))
        main_layout.addWidget(make_separator())
        icons_layout = QHBoxLayout()
        icons_layout.setSpacing(12)

        for v in ["primary", "ghost"]:
            for s in ["sm", "default", "lg"]:
                col = QVBoxLayout()
                col.setSpacing(4)
                btn = StyledButton(text="+", icon="+", variant=v, size=s)
                col.addWidget(btn, alignment=Qt.AlignCenter)
                col.addWidget(make_button_label(f"{v} {s}"))
                icons_layout.addLayout(col)

        icons_layout.addStretch()
        main_layout.addLayout(icons_layout)

        # ---- Block Buttons ----
        main_layout.addWidget(make_section_header("Block Buttons"))
        main_layout.addWidget(make_separator())
        block_layout = QVBoxLayout()
        block_layout.setSpacing(4)
        btn_block = StyledButton(text="Block Button (Full Width)", variant="primary", block=True)
        block_layout.addWidget(btn_block)
        block_layout.addWidget(make_button_label("block=True"))
        main_layout.addLayout(block_layout)

        # ---- Events ----
        main_layout.addWidget(make_section_header("Events"))
        main_layout.addWidget(make_separator())
        events_layout = QHBoxLayout()
        events_layout.setSpacing(12)

        col_ev = QVBoxLayout()
        col_ev.setSpacing(4)
        btn_events = StyledButton(text="Click Me", variant="primary")
        col_ev.addWidget(btn_events, alignment=Qt.AlignCenter)
        col_ev.addWidget(make_button_label("click counter"))
        events_layout.addLayout(col_ev)
        events_layout.addStretch()

        main_layout.addLayout(events_layout)

        self._click_label = QLabel("Click count: 0")
        self._click_label.setStyleSheet(f"font-size: 13px; color: {tm.mid.name()}; margin-top: 4px;")
        main_layout.addWidget(self._click_label)

        btn_events.clicked.connect(self._on_event_click)

        main_layout.addStretch()

    def _on_event_click(self):
        self._click_count += 1
        self._click_label.setText(f"Click count: {self._click_count}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StyledButtonDemo()
    window.show()
    sys.exit(app.exec())
