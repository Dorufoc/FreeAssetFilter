"""StyledSteps Demo — showcases all step-progress features.

Sections:
  1. Horizontal 4-step default variant
  2. Vertical step flow
  3. Dot variant
  4. Icon variant
  5. Size variants (sm / default / lg)
  6. Interactive — step navigation via buttons
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QPushButton,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from theme import tm
from components.styled_steps import StyledSteps


class StyledStepsDemo(QWidget):
    """Main demo window for StyledSteps."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledSteps Demo")
        self.resize(820, 780)

        self._setup_ui()
        self._apply_theme()

    # ── Theme ──────────────────────────────────────────────────────

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
        """)

    # ── UI helpers ─────────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 600;
            color: {tm.text.name()};
            margin-top: 8px;
            margin-bottom: 4px;
        """)
        return lbl

    def _section_desc(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;")
        return lbl

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(
            f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;"
        )
        return line

    def _make_panel(self) -> QWidget:
        """Return a dark panel for grouping examples."""
        p = QWidget()
        p.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        return p

    # ── Setup UI ───────────────────────────────────────────────────

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

        # ── Section 1: Horizontal 4-step (default) ────────────────
        self._build_horizontal_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 2: Vertical ────────────────────────────────────
        self._build_vertical_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 3: Dot variant ─────────────────────────────────
        self._build_dot_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 4: Icon variant ────────────────────────────────
        self._build_icon_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 5: Size variants ───────────────────────────────
        self._build_size_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 6: Interactive — step navigation ───────────────
        self._build_interactive_section(main_layout)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Section 1: Horizontal 4-step default ──────────────────────

    def _build_horizontal_section(self, layout):
        layout.addWidget(self._section_label("1. Horizontal 4-Step (Default)"))
        layout.addWidget(
            self._section_desc("Numbered indicators with completed/current/pending/error states")
        )

        steps = StyledSteps()
        steps.add_step("Account", "Create your account", state="completed")
        steps.add_step("Profile", "Fill in your details", state="current")
        steps.add_step("Payment", "Set up billing", state="pending")
        steps.add_step("Confirm", "Review and submit", state="pending")
        layout.addWidget(steps)

    # ── Section 2: Vertical ────────────────────────────────────────

    def _build_vertical_section(self, layout):
        layout.addWidget(self._section_label("2. Vertical Step Flow"))
        layout.addWidget(
            self._section_desc("Vertical orientation with connector lines")
        )

        vsteps = StyledSteps()
        vsteps.orientation = "vertical"
        vsteps.add_step("Cart Review", "Check items in your cart", state="completed")
        vsteps.add_step("Shipping", "Enter delivery address", state="completed")
        vsteps.add_step("Payment", "Choose payment method", state="current")
        vsteps.add_step("Order Placed", "Confirmation details", state="pending")
        vsteps.setFixedWidth(380)
        layout.addWidget(vsteps, alignment=Qt.AlignLeft)

    # ── Section 3: Dot variant ─────────────────────────────────────

    def _build_dot_section(self, layout):
        layout.addWidget(self._section_label("3. Dot Variant"))
        layout.addWidget(
            self._section_desc("Small circular indicators, no numbers")
        )

        dsteps = StyledSteps()
        dsteps.variant = "dot"
        dsteps.add_step("Discover", "Explore options", state="completed")
        dsteps.add_step("Compare", "Review choices", state="current")
        dsteps.add_step("Select", "Make your pick", state="pending")
        dsteps.add_step("Done", "Complete", state="pending")
        layout.addWidget(dsteps)

    # ── Section 4: Icon variant ────────────────────────────────────

    def _build_icon_section(self, layout):
        layout.addWidget(self._section_label("4. Icon Variant"))
        layout.addWidget(
            self._section_desc("Indicators render icons instead of numbers")
        )

        isteps = StyledSteps()
        isteps.variant = "icon"
        isteps.icon_name = "user"
        isteps.add_step("Account", "Login details", state="completed")
        isteps.icon_name = "search"
        isteps.add_step("Verify", "Confirm identity", state="current")
        isteps.icon_name = "bell"
        isteps.add_step("Notify", "Set preferences", state="pending")
        isteps.icon_name = "checkmark"
        isteps.add_step("Done", "All set", state="pending")
        layout.addWidget(isteps)

    # ── Section 5: Size variants ───────────────────────────────────

    def _build_size_section(self, layout):
        layout.addWidget(self._section_label("5. Size Variants"))
        layout.addWidget(
            self._section_desc("Small, default, and large step sizes")
        )

        for size_key, label in [("sm", "Small"), ("default", "Default"), ("lg", "Large")]:
            row = QHBoxLayout()
            row.setSpacing(12)

            size_lbl = QLabel(label)
            size_lbl.setStyleSheet(
                f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 60px;"
            )
            size_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            row.addWidget(size_lbl)

            s = StyledSteps()
            s.size = size_key
            s.add_step("One", "First step", state="completed")
            s.add_step("Two", "Second step", state="current")
            s.add_step("Three", "Third step", state="pending")
            row.addWidget(s)

            layout.addLayout(row)

    # ── Section 6: Interactive ─────────────────────────────────────

    def _build_interactive_section(self, layout):
        layout.addWidget(self._section_label("6. Interactive — Step Navigation"))
        layout.addWidget(
            self._section_desc(
                "Click a step to jump to it, or use the navigation buttons. "
                "Step index is emitted via step_clicked signal."
            )
        )

        panel = self._make_panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 12, 16, 12)
        panel_layout.setSpacing(12)

        self._isteps = StyledSteps()
        self._isteps.add_step("Step 1", "Order received", state="completed")
        self._isteps.add_step("Step 2", "Processing payment", state="current")
        self._isteps.add_step("Step 3", "Preparing shipment", state="pending")
        self._isteps.add_step("Step 4", "Delivered", state="pending")
        panel_layout.addWidget(self._isteps)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._prev_btn = QPushButton("◀  Previous")
        self._prev_btn.clicked.connect(self._go_prev)
        self._style_button(self._prev_btn, tm.mid.name())
        btn_row.addWidget(self._prev_btn)

        self._current_lbl = QLabel("Current step: 2 (of 4)")
        self._current_lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
        btn_row.addWidget(self._current_lbl)

        self._next_btn = QPushButton("Next  ▶")
        self._next_btn.clicked.connect(self._go_next)
        self._style_button(self._next_btn, tm.accent.name())
        btn_row.addWidget(self._next_btn)

        btn_row.addStretch()
        panel_layout.addLayout(btn_row)

        # Event log
        self._event_label = QLabel("No step clicked yet")
        self._event_label.setStyleSheet(f"""
            font-size: 12px;
            color: {tm.alpha_of(tm.mid, 60).name()};
            padding: 8px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)
        panel_layout.addWidget(self._event_label)

        # Connect signal
        self._isteps.step_clicked.connect(self._on_step_clicked)

        layout.addWidget(panel)

    def _style_button(self, btn: QPushButton, accent: str):
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {accent};
            }}
            QPushButton:disabled {{
                background-color: {tm.mid.name()};
                color: {tm.alpha_of(tm.mid, 60).name()};
            }}
        """)
        btn.setCursor(Qt.PointingHandCursor)

    def _go_prev(self):
        cur = self._isteps.current_step
        if cur > 0:
            self._isteps.current_step = cur - 1
            self._update_interactive_labels()

    def _go_next(self):
        cur = self._isteps.current_step
        n = len(self._isteps._steps)
        if cur < n - 1:
            self._isteps.current_step = cur + 1
            self._update_interactive_labels()

    def _update_interactive_labels(self):
        cur = self._isteps.current_step
        total = len(self._isteps._steps)
        self._current_lbl.setText(f"Current step: {cur + 1} (of {total})")

    def _on_step_clicked(self, index: int):
        # Also update current_step so the visual state reflects the click
        self._isteps.current_step = index
        self._update_interactive_labels()
        self._event_label.setText(f"Step {index + 1} clicked — jumped to step {index + 1}")


def main():
    app = QApplication(sys.argv)
    demo = StyledStepsDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
