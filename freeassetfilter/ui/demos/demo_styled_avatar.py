"""StyledAvatar Demo - standalone demo showcasing all avatar features."""

import sys
import os

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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

from components.styled_avatar import StyledAvatar, AvatarGroup


class StyledAvatarDemo(QWidget):
    """Main demo window for StyledAvatar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledAvatar Demo")
        self.resize(780, 720)

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

    # ── UI helpers ───────────────────────────────────────────────────────

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

    # ── Setup UI ────────────────────────────────────────────────────────

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

        # ── Section 1: Size Variants ─────────────────────────────────
        main_layout.addWidget(self._section_label("1. Size Variants"))
        main_layout.addWidget(self._section_desc(
            "sm (28px), default (36px), lg (48px), xl (64px)"
        ))

        for s, s_label in [
            ("sm", "Small"),
            ("default", "Default"),
            ("lg", "Large"),
            ("xl", "Extra Large"),
        ]:
            row = QHBoxLayout()
            row.addWidget(self._row_label(s_label))
            row.addWidget(StyledAvatar(text="JD", size=s, color="blue"))
            row.addWidget(StyledAvatar(text="AB", size=s, color="purple"))
            row.addStretch()
            main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 2: Color Variants ────────────────────────────────
        main_layout.addWidget(self._section_label("2. Color Variants"))
        main_layout.addWidget(self._section_desc(
            "green, blue, purple, orange, default (gray)"
        ))

        colors = ["green", "blue", "purple", "orange", "default"]
        color_labels = {
            "green": "Gr",
            "blue": "Bl",
            "purple": "Pu",
            "orange": "Or",
            "default": "Df",
        }

        row = QHBoxLayout()
        row.addWidget(self._row_label("Colors"))
        for c in colors:
            avatar = StyledAvatar(text=color_labels[c], color=c)
            row.addWidget(avatar)
        row.addStretch()

        # Color name labels below
        row_labels = QHBoxLayout()
        row_labels.addWidget(self._row_label(""))
        for c in colors:
            lbl = QLabel(c.capitalize())
            lbl.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};")
            lbl.setAlignment(Qt.AlignCenter)
            row_labels.addWidget(lbl)
        row_labels.addStretch()

        main_layout.addLayout(row)
        main_layout.addLayout(row_labels)
        main_layout.addWidget(self._separator())

        # ── Section 3: Shape Variants ────────────────────────────────
        main_layout.addWidget(self._section_label("3. Shape Variants"))
        main_layout.addWidget(self._section_desc(
            "Circle (default, radius=50%) and Square (radius=6px)"
        ))

        shapes = [
            ("circle", "Circle"),
            ("square", "Square"),
        ]
        for shape_val, shape_label in shapes:
            row = QHBoxLayout()
            row.addWidget(self._row_label(shape_label))
            row.addWidget(
                StyledAvatar(text="JD", shape=shape_val, color="green")
            )
            row.addWidget(
                StyledAvatar(text="AB", shape=shape_val, color="blue")
            )
            row.addWidget(
                StyledAvatar(text="MK", shape=shape_val, color="purple")
            )
            row.addStretch()
            main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 4: Icon Avatars ──────────────────────────────────
        main_layout.addWidget(self._section_label("4. Icon Avatars"))
        main_layout.addWidget(self._section_desc(
            "Avatars with SVG icons instead of initials"
        ))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Icons"))
        for c, icon_name in [
            ("green", "user"),
            ("blue", "bell"),
            ("purple", "star"),
            ("orange", "heart"),
        ]:
            avatar = StyledAvatar(icon=icon_name, color=c)
            row.addWidget(avatar)
        row.addStretch()

        # Icon name labels below
        row_labels = QHBoxLayout()
        row_labels.addWidget(self._row_label(""))
        for _, icon_name in [
            ("green", "user"),
            ("blue", "bell"),
            ("purple", "star"),
            ("orange", "heart"),
        ]:
            lbl = QLabel(icon_name.capitalize())
            lbl.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()};")
            lbl.setAlignment(Qt.AlignCenter)
            row_labels.addWidget(lbl)
        row_labels.addStretch()

        main_layout.addLayout(row)
        main_layout.addLayout(row_labels)
        main_layout.addWidget(self._separator())

        # ── Section 5: Placeholder ───────────────────────────────────
        main_layout.addWidget(self._section_label("5. Placeholder"))
        main_layout.addWidget(self._section_desc(
            "Avatar with no text, icon, or image — just background + border"
        ))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Empty"))
        for c in ["green", "blue", "purple", "orange", "default"]:
            avatar = StyledAvatar(color=c)
            row.addWidget(avatar)
        row.addStretch()
        main_layout.addLayout(row)
        main_layout.addWidget(self._separator())

        # ── Section 6: AvatarGroup ───────────────────────────────────
        main_layout.addWidget(self._section_label("6. AvatarGroup"))
        main_layout.addWidget(self._section_desc(
            "Overlapping avatar stack (reverse order, -8px overlap, 2px border)"
        ))

        row = QHBoxLayout()
        row.addWidget(self._row_label("Group"))
        group = AvatarGroup()
        group.addAvatar(StyledAvatar(text="JD", color="blue"))
        group.addAvatar(StyledAvatar(text="AB", color="purple"))
        group.addAvatar(StyledAvatar(text="MK", color="green"))
        group.addAvatar(StyledAvatar(text="SL", color="orange"))
        row.addWidget(group)
        row.addStretch()
        main_layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(self._row_label(""))
        group2 = AvatarGroup()
        group2.addAvatar(StyledAvatar(text="AL", color="blue"))
        group2.addAvatar(StyledAvatar(text="BK", color="green"))
        group2.addAvatar(StyledAvatar(text="CM", color="purple"))
        row2.addWidget(group2)
        row2.addStretch()
        main_layout.addLayout(row2)
        main_layout.addWidget(self._separator())

        # ── Section 7: Mixed Card ────────────────────────────────────
        main_layout.addWidget(self._section_label("7. Mixed Examples"))
        main_layout.addWidget(self._section_desc(
            "Various avatar combinations in a card"
        ))

        card = QWidget()
        card.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(10)

        # Row 1: Team members with initials
        team_row = QHBoxLayout()
        team_row.setSpacing(8)
        name_label_1 = QLabel("Team:")
        name_label_1.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()};")
        team_row.addWidget(name_label_1)
        for name, c in [
            ("AL", "blue"),
            ("BK", "green"),
            ("CM", "purple"),
            ("DN", "orange"),
            ("EO", "default"),
        ]:
            team_row.addWidget(StyledAvatar(text=name, size="sm", color=c))
        team_row.addStretch()
        card_layout.addLayout(team_row)

        # Row 2: All sizes in one color
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        name_label_2 = QLabel("Sizes:")
        name_label_2.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()};")
        size_row.addWidget(name_label_2)
        size_row.addWidget(StyledAvatar(text="SM", size="sm", color="blue"))
        size_row.addWidget(StyledAvatar(text="DF", size="default", color="blue"))
        size_row.addWidget(StyledAvatar(text="LG", size="lg", color="blue"))
        size_row.addWidget(StyledAvatar(text="XL", size="xl", color="blue"))
        size_row.addStretch()
        card_layout.addLayout(size_row)

        # Row 3: Icon avatars in a group
        icon_row = QHBoxLayout()
        icon_row.setSpacing(8)
        name_label_3 = QLabel("Icons:")
        name_label_3.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()};")
        icon_row.addWidget(name_label_3)
        icon_row.addWidget(StyledAvatar(icon="user", color="green", size="sm"))
        icon_row.addWidget(StyledAvatar(icon="bell", color="blue", size="sm"))
        icon_row.addWidget(StyledAvatar(icon="star", color="purple", size="sm"))
        icon_row.addStretch()
        card_layout.addLayout(icon_row)

        main_layout.addWidget(card)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)


def main():
    app = QApplication(sys.argv)
    demo = StyledAvatarDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
