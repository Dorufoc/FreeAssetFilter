"""StyledAccordion Demo - standalone demo showcasing all accordion features."""

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

from components.styled_accordion import StyledAccordion
from components.styled_checkbox import StyledCheckbox


class StyledAccordionDemo(QWidget):
    """Main demo window for StyledAccordion."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledAccordion Demo")
        self.resize(700, 700)

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

    def _make_content(self, text: str) -> QWidget:
        """Create a simple content widget with styled label."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"""
            font-size: 13px;
            color: {tm.mid.name()};
            line-height: 1.6;
            background: transparent;
        """)
        layout.addWidget(label)
        return w

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

        # ── Section 1: Single-open mode ──────────────────────────────
        main_layout.addWidget(self._section_label("1. Single-Open Mode"))
        main_layout.addWidget(self._section_desc(
            "Only one item open at a time (default). Click an item to expand; "
            "other items auto-close."
        ))

        accordion1 = StyledAccordion()
        accordion1.accordion_mode = True
        accordion1.add_item(
            "Accordion Item One",
            self._make_content(
                "This is the content area for item one. Only one item can be "
                "open at a time when the accordion is in single-open mode."
            ),
        )
        accordion1.add_item(
            "Accordion Item Two",
            self._make_content(
                "Content for item two. Opening this item will automatically "
                "close item one (or any other open item)."
            ),
        )
        accordion1.add_item(
            "Accordion Item Three",
            self._make_content(
                "Content for item three. Try clicking between items to see "
                "the auto-close behavior in action."
            ),
        )
        main_layout.addWidget(accordion1)
        main_layout.addWidget(self._separator())

        # ── Section 2: Multi-open mode ───────────────────────────────
        main_layout.addWidget(self._section_label("2. Multi-Open Mode"))
        main_layout.addWidget(self._section_desc(
            "Multiple items can be open simultaneously."
        ))

        accordion2 = StyledAccordion()
        accordion2.accordion_mode = False
        accordion2.add_item(
            "Settings",
            self._make_content(
                "General settings panel. You can keep this open while "
                "exploring other sections."
            ),
        )
        accordion2.add_item(
            "Notifications",
            self._make_content(
                "Configure notification preferences, including email, SMS, "
                "and push notification channels."
            ),
        )
        accordion2.add_item(
            "Privacy",
            self._make_content(
                "Privacy and security settings. Manage data sharing, "
                "cookie preferences, and account privacy."
            ),
        )
        main_layout.addWidget(accordion2)
        main_layout.addWidget(self._separator())

        # ── Section 3: Bordered Variant ──────────────────────────────
        main_layout.addWidget(self._section_label("3. Bordered Variant"))
        main_layout.addWidget(self._section_desc(
            "Each item has a border, border-radius, and margin-bottom."
        ))

        accordion3 = StyledAccordion()
        accordion3.accordion_mode = True
        accordion3.bordered = True
        accordion3.add_item(
            "Profile",
            self._make_content(
                "Manage your profile information, avatar, and display "
                "preferences."
            ),
        )
        accordion3.add_item(
            "Account",
            self._make_content(
                "Account details, subscription plan, and billing "
                "information."
            ),
        )
        accordion3.add_item(
            "Security",
            self._make_content(
                "Password, two-factor authentication, and login history."
            ),
        )
        main_layout.addWidget(accordion3)
        main_layout.addWidget(self._separator())

        # ── Section 4: Disabled Item ─────────────────────────────────
        main_layout.addWidget(self._section_label("4. Disabled Item"))
        main_layout.addWidget(self._section_desc(
            "Disabled items appear grayed out and do not respond to clicks."
        ))

        accordion4 = StyledAccordion()
        accordion4.accordion_mode = True
        accordion4.add_item(
            "Available Section",
            self._make_content("This section is active and can be expanded."),
        )
        accordion4.add_item(
            "Locked Section",
            self._make_content("This content is locked."),
            disabled=True,
        )
        accordion4.add_item(
            "Another Active Section",
            self._make_content("This section is also active and expandable."),
        )
        main_layout.addWidget(accordion4)
        main_layout.addWidget(self._separator())

        # ── Section 5: Events ────────────────────────────────────────
        main_layout.addWidget(self._section_label("5. Events"))
        main_layout.addWidget(self._section_desc(
            "section_toggled signal emits index and open state."
        ))

        accordion5 = StyledAccordion()
        accordion5.accordion_mode = True
        accordion5.add_item(
            "Toggle Me",
            self._make_content("Watch the event output below when toggling this item."),
        )
        accordion5.add_item(
            "Toggle Me Too",
            self._make_content("Each toggle fires section_toggled(index, open)."),
        )

        self._event_label = QLabel("No events yet — click an item above")
        self._event_label.setStyleSheet(f"""
            font-size: 12px;
            color: {tm.alpha_of(tm.mid, 60).name()};
            padding: 8px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)
        accordion5.section_toggled.connect(self._on_section_toggled)

        main_layout.addWidget(accordion5)
        main_layout.addWidget(self._event_label)
        main_layout.addWidget(self._separator())

        # ── Section 6: Real examples ─────────────────────────────────
        main_layout.addWidget(self._section_label("6. Real Example — FAQ"))
        main_layout.addWidget(self._section_desc(
            "Accordion commonly used for FAQ sections."
        ))

        accordion6 = StyledAccordion()
        accordion6.accordion_mode = True
        accordion6.add_item(
            "How do I reset my password?",
            self._make_content(
                "Go to Settings > Account and click 'Reset Password'. "
                "A verification email will be sent to your registered "
                "email address containing a secure link. Follow the "
                "instructions in the email to set a new password."
            ),
        )
        accordion6.add_item(
            "Can I change my username?",
            self._make_content(
                "Usernames can be changed once every 30 days. Navigate to "
                "your Profile page and click the edit icon next to your "
                "username. Type your new username and confirm the change."
            ),
        )
        accordion6.add_item(
            "How do I delete my account?",
            self._make_content(
                "Account deletion is permanent and cannot be undone. To "
                "delete your account, go to Settings > Account > Delete "
                "Account. You will be asked to confirm your decision "
                "before the deletion is processed."
            ),
        )
        main_layout.addWidget(accordion6)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_section_toggled(self, index: int, open: bool):
        state = "opened" if open else "closed"
        self._event_label.setText(f"Item {index + 1} {state}")
        color = tm.accent.name() if open else tm.mid.name()
        bg = tm.surface.name() if open else tm.surface.name()
        self._event_label.setStyleSheet(f"""
            font-size: 12px;
            color: {color};
            padding: 8px 12px;
            background-color: {bg};
            border-radius: 6px;
        """)


def main():
    app = QApplication(sys.argv)
    demo = StyledAccordionDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
