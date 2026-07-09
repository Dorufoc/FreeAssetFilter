"""StyledBadge Demo - standalone demo showcasing all badge features."""

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
    QPushButton,
)
from PySide6.QtCore import Qt
from theme import tm

from components.styled_badge import StyledBadge, BadgeWrapper


class StyledBadgeDemo(QWidget):
    """Main demo window for StyledBadge."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledBadge Demo")
        self.resize(720, 660)

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
        label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 72px;")
        label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        return label

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

        # Section 1: Solid - all color variants
        main_layout.addWidget(self._section_label("1. Solid Variant"))
        main_layout.addWidget(self._section_desc("All color variants (default, primary, warning, danger, info, purple)"))

        colors = ["default", "primary", "warning", "danger", "info", "purple"]
        color_labels = {
            "default": "Default",
            "primary": "Primary",
            "warning": "Warning",
            "danger": "Danger",
            "info": "Info",
            "purple": "Purple",
        }

        row = QHBoxLayout()
        row.addWidget(self._row_label("Solid"))
        for c in colors:
            badge = StyledBadge(text=color_labels[c], variant="solid", color=c)
            row.addWidget(badge)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 2: Size Variants
        main_layout.addWidget(self._section_label("2. Size Variants"))
        main_layout.addWidget(self._section_desc("Small, default, and large sizes with primary color"))

        for s, s_label in [("sm", "Small"), ("default", "Default"), ("lg", "Large")]:
            row = QHBoxLayout()
            row.addWidget(self._row_label(s_label))
            for c in ["primary", "warning", "danger"]:
                badge = StyledBadge(text=c.capitalize(), variant="solid", color=c, size=s)
                row.addWidget(badge)
            row.addStretch()
            main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 3: Dot Variant
        main_layout.addWidget(self._section_label("3. Dot Variant"))
        main_layout.addWidget(self._section_desc("8x8 circular dot indicators"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Dot"))
        for c in colors:
            badge = StyledBadge(variant="dot", color=c)
            row.addWidget(badge)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 4: Outline Variant
        main_layout.addWidget(self._section_label("4. Outline Variant"))
        main_layout.addWidget(self._section_desc("Transparent background with 1px border"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Outline"))
        for c in colors:
            badge = StyledBadge(text=color_labels[c], variant="outline", color=c)
            row.addWidget(badge)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 5: BadgeWrapper Overlay
        main_layout.addWidget(self._section_label("5. BadgeWrapper Overlay"))
        main_layout.addWidget(self._section_desc("Badge wrapper overlay on buttons (top-right, -4px offset)"))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Overlay"))

        # Notification button with badge count
        btn1 = QPushButton("Notifications")
        btn1.setStyleSheet(self._button_style())
        badge1 = StyledBadge(text="3", variant="solid", color="danger")
        wrapper1 = BadgeWrapper(btn1, badge1)
        row.addWidget(wrapper1)

        # Inbox button with badge
        btn2 = QPushButton("Inbox")
        btn2.setStyleSheet(self._button_style())
        badge2 = StyledBadge(text="12", variant="solid", color="primary")
        wrapper2 = BadgeWrapper(btn2, badge2)
        row.addWidget(wrapper2)

        # Settings button with dot badge
        btn3 = QPushButton("Settings")
        btn3.setStyleSheet(self._button_style())
        badge3 = StyledBadge(variant="dot", color="warning")
        wrapper3 = BadgeWrapper(btn3, badge3)
        row.addWidget(wrapper3)

        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # Section 6: Mixed Content Card
        main_layout.addWidget(self._section_label("6. Mixed Examples"))
        main_layout.addWidget(self._section_desc("Various badge combinations"))

        card = QWidget()
        card.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(10)

        # Row of solid badges in different sizes
        badges_row1 = QHBoxLayout()
        badges_row1.setSpacing(8)
        badges_row1.addWidget(QLabel("Tags:"))
        badges_row1.addWidget(StyledBadge(text="New", variant="solid", color="primary", size="sm"))
        badges_row1.addWidget(StyledBadge(text="Updated", variant="solid", color="warning", size="sm"))
        badges_row1.addWidget(StyledBadge(text="Deprecated", variant="solid", color="danger", size="sm"))
        badges_row1.addStretch()
        card_layout.addLayout(badges_row1)

        # Row of outline badges
        badges_row2 = QHBoxLayout()
        badges_row2.setSpacing(8)
        badges_row2.addWidget(QLabel("Status:"))
        badges_row2.addWidget(StyledBadge(text="Active", variant="outline", color="primary", size="default"))
        badges_row2.addWidget(StyledBadge(text="Pending", variant="outline", color="warning", size="default"))
        badges_row2.addWidget(StyledBadge(text="Error", variant="outline", color="danger", size="default"))
        badges_row2.addStretch()
        card_layout.addLayout(badges_row2)

        # Dot indicators row
        badges_row3 = QHBoxLayout()
        badges_row3.setSpacing(12)
        badges_row3.addWidget(QLabel("Status dot:"))
        for c, label in [("primary", "Online"), ("warning", "Away"), ("danger", "Busy"), ("default", "Offline")]:
            inner = QHBoxLayout()
            inner.setSpacing(4)
            inner.addWidget(StyledBadge(variant="dot", color=c))
            l = QLabel(label)
            l.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()};")
            inner.addWidget(l)
            badges_row3.addLayout(inner)
        badges_row3.addStretch()
        card_layout.addLayout(badges_row3)

        main_layout.addWidget(card)

        # Scrollable outer layout
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
                background-color: {tm.alpha_of(tm.surface, 90).name()};
            }}
        """


def main():
    app = QApplication(sys.argv)
    demo = StyledBadgeDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
