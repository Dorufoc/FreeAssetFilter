"""StyledTooltip Demo — showcases all four arrow placements."""

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
from PySide6.QtCore import Qt

from components.styled_tooltip import StyledTooltip


class StyledTooltipDemo(QWidget):
    """Main demo window for StyledTooltip."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledTooltip Demo")
        self.resize(640, 480)

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

    # UI helpers

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

    # Setup UI

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

        # Title
        title = QLabel("StyledTooltip Demo")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {tm.text.name()};")
        main_layout.addWidget(title)

        desc = QLabel(
            "Hover each button to see the tooltip appear. "
            "Tooltips auto-flip if near a screen edge."
        )
        desc.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        main_layout.addWidget(desc)

        # Section 1: Four placemants
        main_layout.addWidget(self._section_label("1. Placements"))
        main_layout.addWidget(self._section_desc(
            "Top (default), bottom, left, and right arrow positions"
        ))

        # Centre-aligned grid with four buttons around a centre label
        grid_container = QWidget()
        grid_container.setStyleSheet("background: transparent; border: none;")
        grid_layout = QVBoxLayout(grid_container)
        grid_layout.setAlignment(Qt.AlignCenter)

        # Row 1 - top
        top_row = QHBoxLayout()
        top_row.setAlignment(Qt.AlignCenter)
        btn_top = QPushButton("Top")
        btn_top.setStyleSheet(self._button_style())
        StyledTooltip(btn_top, "This is a top tooltip", placement="top")
        top_row.addWidget(btn_top)
        grid_layout.addLayout(top_row)

        # Row 2 - left / centre / right
        mid_row = QHBoxLayout()
        mid_row.setAlignment(Qt.AlignCenter)

        btn_left = QPushButton("Left")
        btn_left.setStyleSheet(self._button_style())
        StyledTooltip(btn_left, "This is a left tooltip", placement="left")
        mid_row.addWidget(btn_left)

        centre = QLabel("Centre Element")
        centre.setStyleSheet(
            f"background-color: {tm.surface.name()};"
            f" border: 1px solid {tm.mid.name()};"
            f" border-radius: 8px;"
            f" padding: 24px 32px;"
            f" font-size: 14px;"
            f" color: {tm.text.name()};"
        )
        mid_row.addSpacing(16)
        mid_row.addWidget(centre)
        mid_row.addSpacing(16)

        btn_right = QPushButton("Right")
        btn_right.setStyleSheet(self._button_style())
        StyledTooltip(btn_right, "This is a right tooltip", placement="right")
        mid_row.addWidget(btn_right)

        grid_layout.addLayout(mid_row)

        # Row 3 - bottom
        bottom_row = QHBoxLayout()
        bottom_row.setAlignment(Qt.AlignCenter)
        btn_bottom = QPushButton("Bottom")
        btn_bottom.setStyleSheet(self._button_style())
        StyledTooltip(btn_bottom, "This is a bottom tooltip", placement="bottom")
        bottom_row.addWidget(btn_bottom)
        grid_layout.addLayout(bottom_row)

        main_layout.addWidget(grid_container)
        main_layout.addWidget(self._separator())

        # Section 2: Various contexts
        main_layout.addWidget(self._section_label("2. Contexts"))
        main_layout.addWidget(self._section_desc("Tooltips on different button labels"))

        row2 = QHBoxLayout()
        buttons_text = [
            ("Save", "Save current changes"),
            ("Delete", "Permanently delete this item"),
            ("Refresh", "Reload the current page"),
            ("Settings", "Open application settings"),
        ]
        for label, tip in buttons_text:
            btn = QPushButton(label)
            btn.setStyleSheet(self._button_style())
            StyledTooltip(btn, tip, placement="top")
            row2.addWidget(btn)
        row2.addStretch()
        main_layout.addLayout(row2)
        main_layout.addWidget(self._separator())

        # Section 3: Long text
        main_layout.addWidget(self._section_label("3. Longer Text"))
        main_layout.addWidget(self._section_desc("Tooltip with more verbose description"))

        row3 = QHBoxLayout()
        btn_long_top = QPushButton("Top (long)")
        btn_long_top.setStyleSheet(self._button_style())
        StyledTooltip(
            btn_long_top,
            "This tooltip has a much longer description text to demonstrate "
            "how the bubble handles wider content.",
            placement="top",
        )
        row3.addWidget(btn_long_top)

        btn_long_bottom = QPushButton("Bottom (long)")
        btn_long_bottom.setStyleSheet(self._button_style())
        StyledTooltip(
            btn_long_bottom,
            "This is a long tooltip on the bottom with plenty of text to show.",
            placement="bottom",
        )
        row3.addWidget(btn_long_bottom)

        btn_long_left = QPushButton("Left (long)")
        btn_long_left.setStyleSheet(self._button_style())
        StyledTooltip(
            btn_long_left,
            "A longer tooltip on the left side.",
            placement="left",
        )
        row3.addWidget(btn_long_left)

        btn_long_right = QPushButton("Right (long)")
        btn_long_right.setStyleSheet(self._button_style())
        StyledTooltip(
            btn_long_right,
            "A longer tooltip on the right side.",
            placement="right",
        )
        row3.addWidget(btn_long_right)

        row3.addStretch()
        main_layout.addLayout(row3)
        main_layout.addWidget(self._separator())

        # Section 4: Info area
        main_layout.addWidget(self._section_label("4. On Info Icon"))
        main_layout.addWidget(self._section_desc(
            "Hover the question-mark area to see its tooltip"
        ))

        info_container = QWidget()
        info_container.setStyleSheet("background: transparent; border: none;")
        info_layout = QHBoxLayout(info_container)
        info_layout.setAlignment(Qt.AlignCenter)

        info_label = QLabel("ⓘ Hover me for info")
        info_label.setStyleSheet(
            f"font-size: 14px;"
            f" color: {tm.info.name()};"
            f" padding: 12px 20px;"
            f" border: 1px dashed {tm.info.name()};"
            f" border-radius: 6px;"
        )
        StyledTooltip(
            info_label,
            "This shows additional information about the feature.",
            placement="top",
        )
        info_layout.addWidget(info_label)
        main_layout.addWidget(info_container)
        main_layout.addWidget(self._separator())

        # Usage hint
        hint = QLabel(
            'Usage: StyledTooltip(button, "My text", placement="top")\n'
            "The tooltip attaches to the widget and handles show/hide automatically."
        )
        hint.setStyleSheet(
            f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};"
            f" padding: 8px 12px;"
            f" background-color: {tm.surface.name()};"
            f" border-radius: 6px;"
            f" border: 1px solid {tm.surface.name()};"
        )
        main_layout.addWidget(hint)

        main_layout.addStretch()

        # Outer scroll layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


def main():
    app = QApplication(sys.argv)
    demo = StyledTooltipDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
