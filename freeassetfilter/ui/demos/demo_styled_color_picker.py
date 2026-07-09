"""StyledColorPicker Demo - standalone demo showcasing all color picker features."""

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
from PySide6.QtGui import QFont

from components.styled_color_picker import StyledColorPicker


class StyledColorPickerDemo(QWidget):
    """Main demo window for StyledColorPicker."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledColorPicker Demo")
        self.resize(700, 650)

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

        # Section 1: Basic Color Picker
        main_layout.addWidget(self._section_label("1. Basic Color Picker"))
        main_layout.addWidget(self._section_desc("Single color picker with default green"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        cp1 = StyledColorPicker(color="#07c160")
        cp1.color_changed.connect(lambda c: self._on_color_changed("Basic", c))
        row.addWidget(cp1)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Red"))
        cp2 = StyledColorPicker(color="#FF0000")
        row.addWidget(cp2)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Blue with alpha"))
        cp3 = StyledColorPicker(color="#0055FF")
        cp3.color_changed.connect(lambda c: self._on_color_changed("Blue", c))
        row.addWidget(cp3)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 2: Preset Colors
        main_layout.addWidget(self._section_label("2. Preset Colors"))
        main_layout.addWidget(self._section_desc("Various starting colors for the picker"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("White"))
        row.addWidget(StyledColorPicker(color="#FFFFFF"))
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Black"))
        row.addWidget(StyledColorPicker(color="#000000"))
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Purple"))
        row.addWidget(StyledColorPicker(color="#8B5CF6"))
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Orange"))
        row.addWidget(StyledColorPicker(color="#FF8800"))
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 3: Disabled State
        main_layout.addWidget(self._section_label("3. Disabled State"))
        main_layout.addWidget(self._section_desc("Disabled color picker — grayed out, no interaction"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Disabled"))
        cp_dis = StyledColorPicker(color="#07c160", enabled=False)
        row.addWidget(cp_dis)
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Disabled red"))
        cp_dis2 = StyledColorPicker(color="#FF0000", enabled=False)
        row.addWidget(cp_dis2)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 4: Events Demo
        main_layout.addWidget(self._section_label("4. Events Demo"))
        main_layout.addWidget(self._section_desc("Color change signal — pick a color to see the hex value"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Pick a color"))
        cp_evt = StyledColorPicker(color="#07c160")
        cp_evt.color_changed.connect(self._on_event_color_changed)
        row.addWidget(cp_evt)
        self._event_label = QLabel("#07C160")
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

    def _on_color_changed(self, mode: str, color: str):
        print(f"[{mode}] Color changed: {color}")

    def _on_event_color_changed(self, color: str):
        self._event_label.setText(color)
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

    demo = StyledColorPickerDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
