"""StyledToggle Demo - standalone demo showcasing all toggle features."""

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
    QPushButton,
    QGridLayout,
    QScrollArea,
)
from PySide6.QtCore import Qt

from components.styled_toggle import StyledToggle


class StyledToggleDemo(QWidget):
    """Main demo window for StyledToggle."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledToggle Demo")
        self.resize(700, 500)

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

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;")
        return line

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

        # Section 1: Sizes
        main_layout.addWidget(self._section_label("1. Sizes"))
        sizes_layout = QGridLayout()
        sizes_layout.setSpacing(12)

        sizes_layout.addWidget(QLabel("sm"), 0, 0, Qt.AlignVCenter)
        sizes_layout.addWidget(QLabel("default"), 1, 0, Qt.AlignVCenter)
        sizes_layout.addWidget(QLabel("lg"), 2, 0, Qt.AlignVCenter)

        # Column 1: unchecked
        unchecked_header = QLabel("Off")
        unchecked_header.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        unchecked_header.setAlignment(Qt.AlignCenter)
        sizes_layout.addWidget(unchecked_header, 0, 1)

        sizes_layout.addWidget(self._make_toggle_row_checked(False, "sm"), 0, 2)
        sizes_layout.addWidget(self._make_toggle_row_checked(False, "default"), 1, 2)
        sizes_layout.addWidget(self._make_toggle_row_checked(False, "lg"), 2, 2)

        # Column 2: checked
        checked_header = QLabel("On")
        checked_header.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        checked_header.setAlignment(Qt.AlignCenter)
        sizes_layout.addWidget(checked_header, 0, 3)

        sizes_layout.addWidget(self._make_toggle_row_checked(True, "sm"), 0, 4)
        sizes_layout.addWidget(self._make_toggle_row_checked(True, "default"), 1, 4)
        sizes_layout.addWidget(self._make_toggle_row_checked(True, "lg"), 2, 4)

        main_layout.addLayout(sizes_layout)
        main_layout.addWidget(self._separator())

        # Section 2: States
        main_layout.addWidget(self._section_label("2. States"))
        states_layout = QHBoxLayout()
        states_layout.setSpacing(24)

        state_group_style = f"""
            font-size: 12px;
            color: {tm.alpha_of(tm.mid, 60).name()};
        """

        # Enabled normal
        enabled_group = QVBoxLayout()
        enabled_group.setSpacing(8)
        label_enabled = QLabel("Enabled")
        label_enabled.setStyleSheet(state_group_style)
        label_enabled.setAlignment(Qt.AlignCenter)
        enabled_group.addWidget(label_enabled)

        toggle_enabled = StyledToggle(checked=True, enabled=True)
        toggle_enabled.setParent(self)
        enabled_container = QWidget()
        enabled_container.setLayout(QHBoxLayout())
        enabled_container.layout().setAlignment(Qt.AlignCenter)
        enabled_container.layout().addWidget(toggle_enabled)
        enabled_group.addWidget(enabled_container)
        states_layout.addLayout(enabled_group)

        # Disabled checked
        disabled_on_group = QVBoxLayout()
        disabled_on_group.setSpacing(8)
        label_disabled_on = QLabel("Disabled On")
        label_disabled_on.setStyleSheet(state_group_style)
        label_disabled_on.setAlignment(Qt.AlignCenter)
        disabled_on_group.addWidget(label_disabled_on)

        toggle_disabled_on = StyledToggle(checked=True, enabled=False)
        toggle_disabled_on.setParent(self)
        d_on_container = QWidget()
        d_on_container.setLayout(QHBoxLayout())
        d_on_container.layout().setAlignment(Qt.AlignCenter)
        d_on_container.layout().addWidget(toggle_disabled_on)
        disabled_on_group.addWidget(d_on_container)
        states_layout.addLayout(disabled_on_group)

        # Disabled unchecked
        disabled_off_group = QVBoxLayout()
        disabled_off_group.setSpacing(8)
        label_disabled_off = QLabel("Disabled Off")
        label_disabled_off.setStyleSheet(state_group_style)
        label_disabled_off.setAlignment(Qt.AlignCenter)
        disabled_off_group.addWidget(label_disabled_off)

        toggle_disabled_off = StyledToggle(checked=False, enabled=False)
        toggle_disabled_off.setParent(self)
        d_off_container = QWidget()
        d_off_container.setLayout(QHBoxLayout())
        d_off_container.layout().setAlignment(Qt.AlignCenter)
        d_off_container.layout().addWidget(toggle_disabled_off)
        disabled_off_group.addWidget(d_off_container)
        states_layout.addLayout(disabled_off_group)

        states_layout.addStretch()
        main_layout.addLayout(states_layout)
        main_layout.addWidget(self._separator())

        # Section 3: Events
        main_layout.addWidget(self._section_label("3. Events"))

        events_layout = QHBoxLayout()
        events_layout.setSpacing(16)

        self._event_toggle = StyledToggle(checked=False)
        self._event_toggle.toggled.connect(self._on_event_toggled)
        events_layout.addWidget(self._event_toggle)

        self._event_label = QLabel("OFF")
        self._event_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {tm.mid.name()};
            padding: 4px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)
        events_layout.addWidget(self._event_label, stretch=1)

        btn_toggle = QPushButton("toggle()")
        btn_toggle.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.mid.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
                color: {tm.text.name()};
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                border-color: {tm.accent.name()};
            }}
            QPushButton:pressed {{
                background-color: {tm.surface.name()};
            }}
        """)
        btn_toggle.clicked.connect(self._event_toggle.toggle)
        events_layout.addWidget(btn_toggle)

        main_layout.addLayout(events_layout)
        main_layout.addWidget(self._separator())

        # Section 4: Use Cases
        main_layout.addWidget(self._section_label("4. Use Cases"))

        cases_container = QWidget()
        cases_container.setStyleSheet(f"""
            background-color: {tm.surface.name()};
            border-radius: 8px;
        """)
        cases_layout = QVBoxLayout(cases_container)
        cases_layout.setContentsMargins(16, 12, 16, 12)
        cases_layout.setSpacing(12)

        cases = [
            ("启用通知", False),
            ("自动更新", True),
            ("暗色模式", False),
        ]

        for label_text, initial_checked in cases:
            row = QHBoxLayout()
            row.setSpacing(12)

            case_label = QLabel(label_text)
            case_label.setStyleSheet(f"""
                font-size: 14px;
                color: {tm.text.name()};
                background: transparent;
            """)
            row.addWidget(case_label)
            row.addStretch()

            case_toggle = StyledToggle(checked=initial_checked)
            case_toggle.setParent(cases_container)
            row.addWidget(case_toggle)
            cases_layout.addLayout(row)

        main_layout.addWidget(cases_container)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _make_toggle_row_checked(self, checked: bool, size: str) -> StyledToggle:
        toggle = StyledToggle(checked=checked, size=size)
        toggle.setParent(self)
        return toggle

    def _on_event_toggled(self, checked: bool):
        if checked:
            self._event_label.setText("ON")
            self._event_label.setStyleSheet(f"""
                font-size: 14px;
                font-weight: 600;
                color: {tm.accent.name()};
                padding: 4px 12px;
                background-color: {tm.surface.name()};
                border-radius: 6px;
            """)
        else:
            self._event_label.setText("OFF")
            self._event_label.setStyleSheet(f"""
                font-size: 14px;
                font-weight: 600;
                color: {tm.mid.name()};
                padding: 4px 12px;
                background-color: {tm.surface.name()};
                border-radius: 6px;
            """)


def main():
    app = QApplication(sys.argv)
    demo = StyledToggleDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
