"""StyledDivider Demo - standalone demo showcasing all divider variants."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
    QSizePolicy,
)
from PySide6.QtCore import Qt

from components.styled_divider import StyledDivider


class StyledDividerDemo(QWidget):
    """Main demo window for StyledDivider."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledDivider Demo")
        self.resize(700, 620)

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

        # Section 1: Horizontal Divider (default)
        main_layout.addWidget(self._section_label("1. Horizontal Divider"))
        main_layout.addWidget(
            self._section_desc("Default 1px solid line across full width")
        )

        main_layout.addWidget(StyledDivider())
        main_layout.addWidget(self._separator())

        # Section 2: Horizontal with Text
        main_layout.addWidget(self._section_label("2. With Text"))
        main_layout.addWidget(
            self._section_desc("Text centered between two line segments")
        )

        main_layout.addWidget(StyledDivider(text="OR"))
        main_layout.addWidget(StyledDivider(text="CONTINUE"))
        main_layout.addWidget(StyledDivider(text="LOADING..."))
        main_layout.addWidget(self._separator())

        # Section 3: Thick Variant
        main_layout.addWidget(self._section_label("3. Thick Variant"))
        main_layout.addWidget(
            self._section_desc("2px line instead of 1px")
        )

        main_layout.addWidget(StyledDivider(thick=True))
        main_layout.addWidget(StyledDivider(text="OR", thick=True))
        main_layout.addWidget(self._separator())

        # Section 4: Dashed Variant
        main_layout.addWidget(self._section_label("4. Dashed Variant"))
        main_layout.addWidget(
            self._section_desc("Dashed line (Qt.DashLine, pattern 4,4)")
        )

        main_layout.addWidget(StyledDivider(dashed=True))
        main_layout.addWidget(StyledDivider(text="DASHED", dashed=True))
        main_layout.addWidget(StyledDivider(text="THICK DASHED", thick=True, dashed=True))
        main_layout.addWidget(self._separator())

        # Section 5: Vertical Divider
        main_layout.addWidget(self._section_label("5. Vertical Divider"))
        main_layout.addWidget(
            self._section_desc("Vertical line between buttons, inline with text")
        )

        row = QHBoxLayout()
        row.addWidget(QPushButton("Left"))
        row.addWidget(StyledDivider(orientation="vertical"))
        row.addWidget(QPushButton("Center"))
        row.addWidget(StyledDivider(orientation="vertical", thick=True))
        row.addWidget(QPushButton("Right"))
        main_layout.addLayout(row)

        # Vertical divider with text label
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Before divider"))
        row2.addWidget(StyledDivider(orientation="vertical"))
        label = QLabel("In between")
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        row2.addWidget(label)
        row2.addWidget(StyledDivider(orientation="vertical", dashed=True))
        row2.addWidget(QLabel("After divider"))
        main_layout.addLayout(row2)
        main_layout.addWidget(self._separator())

        # Section 6: All Variants Gallery
        main_layout.addWidget(self._section_label("6. All Variants Gallery"))

        card = QWidget()
        card.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(12)

        card_layout.addWidget(QLabel("Default horizontal divider:"))
        card_layout.addWidget(StyledDivider())

        card_layout.addWidget(QLabel("With text:"))
        card_layout.addWidget(StyledDivider(text="OR"))

        card_layout.addWidget(QLabel("Thick:"))
        card_layout.addWidget(StyledDivider(thick=True))

        card_layout.addWidget(QLabel("Dashed:"))
        card_layout.addWidget(StyledDivider(dashed=True))

        card_layout.addWidget(QLabel("Thick + Dashed with text:"))
        card_layout.addWidget(StyledDivider(text="END", thick=True, dashed=True))

        main_layout.addWidget(card)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


def main():
    app = QApplication(sys.argv)
    demo = StyledDividerDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
