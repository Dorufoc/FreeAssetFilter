"""StyledTabs Demo - standalone demo showcasing all tab features."""

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

from components.styled_tabs import StyledTabWidget


# ── Helpers to build simple tab content widgets ────────────────

def _make_page(text: str, color: str = None) -> QWidget:
    """Return a styled QWidget with centered label for tab content."""
    w = QWidget()
    bg = color if color is not None else tm.surface.name()
    w.setStyleSheet(f"background-color: {bg}; border-radius: 6px;")
    layout = QVBoxLayout(w)
    layout.setAlignment(Qt.AlignCenter)
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 14px; color: {tm.mid.name()}; background: transparent;")
    label.setAlignment(Qt.AlignCenter)
    layout.addWidget(label)
    return w


# ── Demo window ────────────────────────────────────────────────

class StyledTabsDemo(QWidget):
    """Main demo window for StyledTabWidget."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledTabs Demo")
        self.resize(720, 580)

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

        # ── Section 1: Default Underline ──────────────────────────
        main_layout.addWidget(self._section_label("1. Default Underline Tabs"))
        main_layout.addWidget(
            self._section_desc("Standard tabs with animated underline indicator")
        )

        underline_tabs = StyledTabWidget(variant="underline", size="default")
        underline_tabs.add_tab("Home", _make_page("🏠  Welcome to the Home tab"))
        underline_tabs.add_tab(
            "Profile", _make_page("👤  This is your Profile page")
        )
        underline_tabs.add_tab(
            "Settings", _make_page("⚙️  Adjust your preferences here")
        )
        underline_tabs.add_tab(
            "Notifications",
            _make_page("🔔  You have no new notifications"),
        )
        underline_tabs.setFixedHeight(180)
        main_layout.addWidget(underline_tabs)
        main_layout.addWidget(self._separator())

        # ── Section 2: With Disabled Tab ──────────────────────────
        main_layout.addWidget(self._section_label("2. With Disabled Tab"))
        main_layout.addWidget(
            self._section_desc(
                "The third tab ('Coming Soon') is disabled and cannot be clicked"
            )
        )

        disabled_tabs = StyledTabWidget(variant="underline", size="default")
        disabled_tabs.add_tab(
            "Available", _make_page("✅  This feature is ready")
        )
        disabled_tabs.add_tab(
            "Beta", _make_page("🧪  Beta feature — use with caution")
        )
        disabled_tabs.add_tab(
            "Coming Soon", _make_page("⏳  Not yet available"), disabled=True
        )
        disabled_tabs.add_tab(
            "Archive", _make_page("📦  Old data lives here")
        )
        disabled_tabs.setFixedHeight(180)
        main_layout.addWidget(disabled_tabs)
        main_layout.addWidget(self._separator())

        # ── Section 3: Pill Variant ───────────────────────────────
        main_layout.addWidget(self._section_label("3. Pill Variant"))
        main_layout.addWidget(
            self._section_desc(
                "Pill-style tabs with filled active background instead of underline"
            )
        )

        pill_tabs = StyledTabWidget(variant="pills", size="default")
        pill_tabs.add_tab(
            "Messages", _make_page("💬  Your message inbox")
        )
        pill_tabs.add_tab(
            "Calls", _make_page("📞  Recent call history")
        )
        pill_tabs.add_tab(
            "Contacts", _make_page("👥  Your contact list")
        )
        pill_tabs.setFixedHeight(180)
        main_layout.addWidget(pill_tabs)
        main_layout.addWidget(self._separator())

        # ── Section 4: Size Variants ──────────────────────────────
        main_layout.addWidget(self._section_label("4. Size Variants"))
        main_layout.addWidget(
            self._section_desc("Small, default, and large tab sizes side by side")
        )

        size_row = QHBoxLayout()
        size_row.setSpacing(12)

        # Small
        sm_tabs = StyledTabWidget(variant="underline", size="sm")
        sm_tabs.add_tab("One", _make_page("Small A", tm.surface.name()))
        sm_tabs.add_tab("Two", _make_page("Small B", tm.surface.name()))
        sm_tabs.add_tab("Three", _make_page("Small C", tm.surface.name()))
        sm_tabs.setFixedHeight(140)
        sm_container = QWidget()
        sm_container.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        sm_lo = QVBoxLayout(sm_container)
        sm_lo.setContentsMargins(8, 8, 8, 8)
        sm_label = QLabel("sm")
        sm_label.setStyleSheet(
            f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()}; background: transparent;"
        )
        sm_lo.addWidget(sm_label)
        sm_lo.addWidget(sm_tabs)
        size_row.addWidget(sm_container)

        # Default
        def_tabs = StyledTabWidget(variant="underline", size="default")
        def_tabs.add_tab("One", _make_page("Default A", tm.surface.name()))
        def_tabs.add_tab("Two", _make_page("Default B", tm.surface.name()))
        def_tabs.add_tab("Three", _make_page("Default C", tm.surface.name()))
        def_tabs.setFixedHeight(150)
        def_container = QWidget()
        def_container.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        def_lo = QVBoxLayout(def_container)
        def_lo.setContentsMargins(8, 8, 8, 8)
        def_label = QLabel("default")
        def_label.setStyleSheet(
            f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()}; background: transparent;"
        )
        def_lo.addWidget(def_label)
        def_lo.addWidget(def_tabs)
        size_row.addWidget(def_container)

        # Large
        lg_tabs = StyledTabWidget(variant="underline", size="lg")
        lg_tabs.add_tab("One", _make_page("Large A", tm.surface.name()))
        lg_tabs.add_tab("Two", _make_page("Large B", tm.surface.name()))
        lg_tabs.add_tab("Three", _make_page("Large C", tm.surface.name()))
        lg_tabs.setFixedHeight(160)
        lg_container = QWidget()
        lg_container.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
        lg_lo = QVBoxLayout(lg_container)
        lg_lo.setContentsMargins(8, 8, 8, 8)
        lg_label = QLabel("lg")
        lg_label.setStyleSheet(
            f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()}; background: transparent;"
        )
        lg_lo.addWidget(lg_label)
        lg_lo.addWidget(lg_tabs)
        size_row.addWidget(lg_container)

        main_layout.addLayout(size_row)
        main_layout.addWidget(self._separator())

        # ── Section 5: Signal Demo ────────────────────────────────
        main_layout.addWidget(self._section_label("5. Signal Demo"))
        main_layout.addWidget(
            self._section_desc(
                "The current_changed signal fires when switching tabs"
            )
        )

        signal_row = QHBoxLayout()
        signal_tabs = StyledTabWidget(variant="underline", size="default")
        signal_tabs.add_tab("Tab A", _make_page("Content A", tm.surface.name()))
        signal_tabs.add_tab("Tab B", _make_page("Content B", tm.surface.name()))
        signal_tabs.add_tab("Tab C", _make_page("Content C", tm.surface.name()))
        signal_tabs.setFixedHeight(160)
        signal_row.addWidget(signal_tabs, stretch=1)

        self._signal_label = QLabel("Current: Tab A (index 0)")
        self._signal_label.setStyleSheet(f"""
            font-size: 13px;
            color: {tm.mid.name()};
            padding: 8px 16px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
            min-width: 180px;
        """)
        self._signal_label.setAlignment(Qt.AlignCenter)
        signal_row.addWidget(self._signal_label)

        signal_tabs.current_changed.connect(self._on_current_changed)

        main_layout.addLayout(signal_row)
        main_layout.addWidget(self._separator())

        # ── Section 6: Pill + Disabled Mixed ──────────────────────
        main_layout.addWidget(self._section_label("6. Mixed Pill + Disabled"))
        main_layout.addWidget(
            self._section_desc(
                "Pill variant with one disabled tab to show combined state"
            )
        )

        mixed_tabs = StyledTabWidget(variant="pills", size="default")
        mixed_tabs.add_tab("Enabled", _make_page("✅  This tab works"))
        mixed_tabs.add_tab("Also Enabled", _make_page("✅  This one too"))
        mixed_tabs.add_tab(
            "Locked", _make_page("🔒  Cannot access"), disabled=True
        )
        mixed_tabs.setFixedHeight(180)
        main_layout.addWidget(mixed_tabs)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_current_changed(self, index: int):
        names = ["Tab A", "Tab B", "Tab C"]
        name = names[index] if index < len(names) else f"Tab (index {index})"
        self._signal_label.setText(f"Current: {name} (index {index})")
        self._signal_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 600;
            color: {tm.accent.name()};
            padding: 8px 16px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
            min-width: 180px;
        """)


def main():
    app = QApplication(sys.argv)
    demo = StyledTabsDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
