"""StyledRadio Demo - standalone demo showcasing all radio features."""

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
from components.styled_radio import StyledRadio


class StyledRadioDemo(QWidget):
    """Main demo window for StyledRadio."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledRadio Demo")
        self.resize(700, 580)

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

        # Section 1: Language Selection (default size)
        main_layout.addWidget(self._section_label("1. Language Selection"))
        main_layout.addWidget(self._section_desc("Mutually exclusive radio group"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Language"))
        r1 = StyledRadio(checked=True, text="Follow system", group_name="lang")
        row.addWidget(r1)
        r2 = StyledRadio(checked=False, text="Simplified Chinese", group_name="lang")
        row.addWidget(r2)
        r3 = StyledRadio(checked=False, text="English", group_name="lang")
        row.addWidget(r3)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 2: Small Size
        main_layout.addWidget(self._section_label("2. Small Size"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Small"))
        rs1 = StyledRadio(checked=False, size="sm", text="Option A", group_name="size-sm")
        row.addWidget(rs1)
        rs2 = StyledRadio(checked=True, size="sm", text="Option B", group_name="size-sm")
        row.addWidget(rs2)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 3: Large Size
        main_layout.addWidget(self._section_label("3. Large Size"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Large"))
        rl1 = StyledRadio(checked=False, size="lg", text="Option A", group_name="size-lg")
        row.addWidget(rl1)
        rl2 = StyledRadio(checked=True, size="lg", text="Option B", group_name="size-lg")
        row.addWidget(rl2)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 4: Theme Selection
        main_layout.addWidget(self._section_label("4. Theme Selection"))
        main_layout.addWidget(self._section_desc("Large radio group for theme"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Theme"))
        rt1 = StyledRadio(checked=False, size="lg", text="Light mode", group_name="theme")
        row.addWidget(rt1)
        rt2 = StyledRadio(checked=True, size="lg", text="Dark mode", group_name="theme")
        row.addWidget(rt2)
        rt3 = StyledRadio(checked=False, size="lg", text="Follow system", group_name="theme")
        row.addWidget(rt3)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 5: No Label
        main_layout.addWidget(self._section_label("5. No Label"))
        main_layout.addWidget(self._section_desc("Radio buttons without text labels"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("No label"))
        row.addWidget(StyledRadio(checked=False, group_name="nolabel"))
        row.addWidget(StyledRadio(checked=True, group_name="nolabel"))
        row.addWidget(StyledRadio(checked=False, group_name="nolabel"))
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 6: Disabled
        main_layout.addWidget(self._section_label("6. Disabled"))
        main_layout.addWidget(self._section_desc("Mixed enabled/disabled states"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Disabled"))
        rd1 = StyledRadio(checked=False, text="Available option", group_name="dis")
        row.addWidget(rd1)
        rd2 = StyledRadio(checked=False, enabled=False, text="Disabled option", group_name="dis")
        row.addWidget(rd2)
        rd3 = StyledRadio(checked=True, enabled=False, text="Selected (disabled)", group_name="dis")
        row.addWidget(rd3)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 7: Events
        main_layout.addWidget(self._section_label("7. Events"))
        main_layout.addWidget(self._section_desc("Toggle and state change signal"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Events"))
        self._event_r1 = StyledRadio(checked=False, text="Option 1", group_name="event")
        self._event_r1.toggled.connect(lambda v: self._on_event_toggled("1", v))
        row.addWidget(self._event_r1)
        self._event_r2 = StyledRadio(checked=True, text="Option 2", group_name="event")
        self._event_r2.toggled.connect(lambda v: self._on_event_toggled("2", v))
        row.addWidget(self._event_r2)
        self._event_label = QLabel("Option 2 selected")
        self._event_label.setStyleSheet(f"""
            font-size: 13px;
            color: {tm.accent.name()};
            padding: 4px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)
        row.addWidget(self._event_label, stretch=1)
        main_layout.addLayout(row)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_event_toggled(self, option: str, checked: bool):
        if checked:
            self._event_label.setText(f"Option {option} selected")
            self._event_label.setStyleSheet(f"""
                font-size: 13px;
                font-weight: 600;
                color: {tm.accent.name()};
                padding: 4px 12px;
                background-color: {tm.surface.name()};
                border-radius: 6px;
            """)


def main():
    app = QApplication(sys.argv)
    demo = StyledRadioDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
