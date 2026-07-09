"""StyledCheckbox Demo - standalone demo showcasing all checkbox features."""

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

from components.styled_checkbox import StyledCheckbox


class StyledCheckboxDemo(QWidget):
    """Main demo window for StyledCheckbox."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledCheckbox Demo")
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

        # Section 1: Default
        main_layout.addWidget(self._section_label("1. Default"))
        main_layout.addWidget(self._section_desc("Unchecked and checked states"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        row.addWidget(StyledCheckbox(checked=False))
        row.addWidget(StyledCheckbox(checked=True))
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 2: With Labels
        main_layout.addWidget(self._section_label("2. With Labels"))
        main_layout.addWidget(self._section_desc("Checkbox with text labels"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("With label"))
        cb1 = StyledCheckbox(checked=False, text="Remember selection")
        row.addWidget(cb1)
        cb2 = StyledCheckbox(checked=True, text="Auto save")
        row.addWidget(cb2)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 3: Indeterminate
        main_layout.addWidget(self._section_label("3. Indeterminate State"))
        main_layout.addWidget(self._section_desc("Partial selection state"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Indeterminate"))
        cb_ind = StyledCheckbox(checked=False, text="Partial selected", indeterminate=True)
        row.addWidget(cb_ind)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 4: Sizes
        main_layout.addWidget(self._section_label("4. Size Variants"))
        main_layout.addWidget(self._section_desc("Small, default, and large sizes"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Small"))
        row.addWidget(StyledCheckbox(checked=False, size="sm", text="Small"))
        row.addWidget(StyledCheckbox(checked=True, size="sm", text="Small checked"))
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Default"))
        row.addWidget(StyledCheckbox(checked=False, size="default", text="Default"))
        row.addWidget(StyledCheckbox(checked=True, size="default", text="Default checked"))
        row.addStretch()
        main_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(self._row_label("Large"))
        row.addWidget(StyledCheckbox(checked=False, size="lg", text="Large"))
        row.addWidget(StyledCheckbox(checked=True, size="lg", text="Large checked"))
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 5: Disabled
        main_layout.addWidget(self._section_label("5. Disabled"))
        main_layout.addWidget(self._section_desc("Disabled unchecked and checked states"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Disabled"))
        row.addWidget(StyledCheckbox(checked=False, enabled=False, text="Disabled"))
        row.addWidget(StyledCheckbox(checked=True, enabled=False, text="Disabled checked"))
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 6: Group Example
        main_layout.addWidget(self._section_label("6. Group Example"))
        main_layout.addWidget(self._section_desc("Checkbox group for notification settings"))

        card = QWidget()
        card.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)

        cb_email = StyledCheckbox(checked=True, text="Receive email notifications")
        card_layout.addWidget(cb_email)
        cb_sms = StyledCheckbox(checked=True, text="Receive SMS notifications")
        card_layout.addWidget(cb_sms)
        cb_push = StyledCheckbox(checked=False, text="Receive push notifications")
        card_layout.addWidget(cb_push)
        cb_phone = StyledCheckbox(checked=False, enabled=False, text="Phone notifications (unavailable)")
        card_layout.addWidget(cb_phone)

        main_layout.addWidget(card)
        main_layout.addWidget(self._separator())

        # Section 7: Events
        main_layout.addWidget(self._section_label("7. Events"))
        main_layout.addWidget(self._section_desc("Toggle and state change signal"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Events"))
        self._event_cb = StyledCheckbox(checked=False, text="Click me")
        self._event_cb.toggled.connect(self._on_event_toggled)
        row.addWidget(self._event_cb)
        self._event_label = QLabel("Unchecked")
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

    def _on_event_toggled(self, checked: bool):
        if checked:
            self._event_label.setText("Checked")
            self._event_label.setStyleSheet(f"""
                font-size: 13px;
                font-weight: 600;
                color: {tm.accent.name()};
                padding: 4px 12px;
                background-color: {tm.surface.name()};
                border-radius: 6px;
            """)
        else:
            self._event_label.setText("Unchecked")
            self._event_label.setStyleSheet(f"""
                font-size: 13px;
                color: {tm.mid.name()};
                padding: 4px 12px;
                background-color: {tm.surface.name()};
                border-radius: 6px;
            """)


def main():
    app = QApplication(sys.argv)
    demo = StyledCheckboxDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
