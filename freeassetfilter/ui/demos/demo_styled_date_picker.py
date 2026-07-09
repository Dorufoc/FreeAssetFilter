"""StyledDatePicker Demo - standalone demo showcasing all date picker features."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from theme import tm

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
from PySide6.QtGui import QFont

from components.styled_date_picker import StyledDatePicker, StyledTimePicker


class StyledDatePickerDemo(QWidget):
    """Main demo window for StyledDatePicker."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledDatePicker Demo")
        self.resize(700, 750)

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
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 80px;")
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

        # Section 1: Basic Date Picker
        main_layout.addWidget(self._section_label("1. Basic Date Picker"))
        main_layout.addWidget(self._section_desc("Single date selection with default state"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        dp1 = StyledDatePicker(date="2024-01-15")
        dp1.date_changed.connect(lambda d: self._on_date_changed("Basic", d))
        row.addWidget(dp1)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Empty"))
        dp2 = StyledDatePicker()
        row.addWidget(dp2)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 2: Size Variants
        main_layout.addWidget(self._section_label("2. Size Variants"))
        main_layout.addWidget(self._section_desc("Small, default, and large sizes"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Small"))
        dp_sm = StyledDatePicker(date="2024-03-08", size="sm")
        row.addWidget(dp_sm)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        dp_md = StyledDatePicker(date="2024-06-15", size="default")
        row.addWidget(dp_md)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Large"))
        dp_lg = StyledDatePicker(date="2024-12-25", size="lg")
        row.addWidget(dp_lg)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 3: Range Picker
        main_layout.addWidget(self._section_label("3. Date Range Picker"))
        main_layout.addWidget(self._section_desc("Select start and end dates"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Range"))
        dp_range = StyledDatePicker(is_range=True)
        dp_range.set_range("2024-02-10", "2024-02-20")
        dp_range.range_changed.connect(lambda s, e: self._on_range_changed(s, e))
        row.addWidget(dp_range)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 4: DateTime Picker
        main_layout.addWidget(self._section_label("4. DateTime Picker"))
        main_layout.addWidget(self._section_desc("Date selection with time input"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("DateTime"))
        dp_dt = StyledDatePicker(date="2024-04-15 14:30", is_datetime=True)
        dp_dt.setFixedWidth(240)
        dp_dt.date_changed.connect(lambda d: self._on_date_changed("DateTime", d))
        row.addWidget(dp_dt)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 5: Month Picker
        main_layout.addWidget(self._section_label("5. Month Picker"))
        main_layout.addWidget(self._section_desc("Select a specific month"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Month"))
        dp_month = StyledDatePicker(date="2024-06", is_month_picker=True)
        dp_month.date_changed.connect(lambda d: self._on_date_changed("Month", d))
        row.addWidget(dp_month)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 6: Time Picker
        main_layout.addWidget(self._section_label("6. Time Picker"))
        main_layout.addWidget(self._section_desc("Select hours and minutes"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Time"))
        tp1 = StyledTimePicker(time="14:30")
        tp1.time_changed.connect(lambda t: self._on_date_changed("Time", t))
        row.addWidget(tp1)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Empty"))
        tp2 = StyledTimePicker()
        row.addWidget(tp2)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 7: Disabled State
        main_layout.addWidget(self._section_label("7. Disabled State"))
        main_layout.addWidget(self._section_desc("Disabled date picker"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Disabled"))
        dp_dis = StyledDatePicker(date="2024-01-15", enabled=False)
        row.addWidget(dp_dis)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 8: Events Demo
        main_layout.addWidget(self._section_label("8. Events Demo"))
        main_layout.addWidget(self._section_desc("Click to see date change events"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Events"))
        dp_evt = StyledDatePicker(placeholder="Select a date...")
        dp_evt.date_changed.connect(self._on_event_date_changed)
        row.addWidget(dp_evt)
        self._event_label = QLabel("No selection")
        self._event_label.setStyleSheet(f"""
            font-size: 13px;
            color: {tm.mid.name()};
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

    def _on_date_changed(self, mode: str, date: str):
        print(f"[{mode}] Date changed: {date}")

    def _on_range_changed(self, start: str, end: str):
        print(f"[Range] Range changed: {start} to {end}")

    def _on_event_date_changed(self, date: str):
        self._event_label.setText(f"Selected: {date}")
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
    
    # Set default font with anti-aliasing
    font = app.font()
    font.setFamily("Segoe UI, Microsoft YaHei, sans-serif")
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    
    demo = StyledDatePickerDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
