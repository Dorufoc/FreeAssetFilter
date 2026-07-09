"""StyledCarousel Demo — standalone demo showcasing all carousel features."""

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
)
from PySide6.QtCore import Qt
from theme import tm

from components.styled_carousel import StyledCarousel
from components.styled_toggle import StyledToggle


# ── Helpers ────────────────────────────────────────────────────

def _make_slide(
    title: str,
    desc: str,
    bg_color: str,
    text_color: str = tm.text.name(),
) -> QWidget:
    """Create a styled slide widget with centered title + description."""
    w = QWidget()
    w.setStyleSheet(f"background-color: {bg_color};")
    layout = QVBoxLayout(w)
    layout.setAlignment(Qt.AlignCenter)
    layout.setContentsMargins(24, 16, 24, 16)

    title_label = QLabel(title)
    title_label.setStyleSheet(f"""
        font-size: 18px;
        font-weight: 600;
        color: {text_color};
        background: transparent;
    """)
    title_label.setAlignment(Qt.AlignCenter)
    layout.addWidget(title_label)

    desc_label = QLabel(desc)
    desc_label.setStyleSheet(f"""
        font-size: 13px;
        color: rgba({','.join(str(int(c)) for c in (
            QColor(text_color).red(), QColor(text_color).green(),
            QColor(text_color).blue()))}, 0.7);
        background: transparent;
    """)
    desc_label.setAlignment(Qt.AlignCenter)
    desc_label.setWordWrap(True)
    layout.addWidget(desc_label)

    return w


# We need QColor for the desc helper — import from PySide6
from PySide6.QtGui import QColor  # noqa: E402


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;")
    return line


# ── Slide data ─────────────────────────────────────────────────

SLIDE_DATA = [
    ("🌄  Mountain View", "Breathtaking panoramic views of the mountain range at sunrise.",
     "#1a2a3a"),
    ("🏖️  Beach Sunset", "Relax on golden sandy beaches with crystal clear turquoise waters.",
     "#1a3a2a"),
    ("🏙️  City Lights", "Explore the vibrant cityscape with dazzling night-time illuminations.",
     "#2a1a3a"),
    ("🌿  Forest Trail", "Discover hidden pathways through ancient, misty woodlands.",
     "#1a2a1a"),
]


class StyledCarouselDemo(QWidget):
    """Main demo window for StyledCarousel."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledCarousel Demo")
        self.resize(780, 780)

        self._carousels: list[StyledCarousel] = []
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

    def _make_carousel(
        self, variant: str = "slide", size: str = "default",
        autoplay_interval: int = 0, indicators: str = "inside",
    ) -> StyledCarousel:
        carousel = StyledCarousel(
            variant=variant,
            size=size,
            autoplay_interval=autoplay_interval,
            indicators=indicators,
        )
        for title, desc, bg in SLIDE_DATA:
            carousel.add_slide(_make_slide(title, desc, bg))
        if autoplay_interval > 0:
            carousel.start_autoplay()
        self._carousels.append(carousel)
        return carousel

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

        # ── 1. Default Slide Carousel ─────────────────────────────
        main_layout.addWidget(self._section_label("1. Default Slide Carousel"))
        main_layout.addWidget(self._section_desc(
            "Standard slide carousel with arrow navigation and inside indicators."
        ))
        c1 = self._make_carousel(variant="slide", size="default")
        main_layout.addWidget(c1)
        main_layout.addWidget(_separator())

        # ── 2. Outside Indicators ─────────────────────────────────
        main_layout.addWidget(self._section_label("2. Outside Indicators"))
        main_layout.addWidget(self._section_desc(
            "Indicators are positioned below the carousel instead of overlaid."
        ))
        c2 = self._make_carousel(variant="slide", size="default", indicators="outside")
        main_layout.addWidget(c2)
        main_layout.addWidget(_separator())

        # ── 3. Fade Variant ───────────────────────────────────────
        main_layout.addWidget(self._section_label("3. Fade Variant"))
        main_layout.addWidget(self._section_desc(
            "Slides cross-fade using opacity transitions instead of sliding."
        ))
        c3 = self._make_carousel(variant="fade", size="default")
        main_layout.addWidget(c3)
        main_layout.addWidget(_separator())

        # ── 4. Autoplay ───────────────────────────────────────────
        main_layout.addWidget(self._section_label("4. Autoplay"))
        main_layout.addWidget(self._section_desc(
            "Automatically advances every 3 seconds. Pauses on hover."
        ))
        c4 = self._make_carousel(variant="slide", size="default", autoplay_interval=3000)
        main_layout.addWidget(c4)

        autoplay_row = QHBoxLayout()
        autoplay_row.setAlignment(Qt.AlignLeft)
        self._autoplay_status = QLabel("▶  Autoplay running (pause on hover)")
        self._autoplay_status.setStyleSheet(f"""
            font-size: 12px;
            color: {tm.accent.name()};
            padding: 4px 12px;
            background-color: {tm.surface.name()};
            border-radius: 10px;
        """)
        autoplay_row.addWidget(self._autoplay_status)
        main_layout.addLayout(autoplay_row)
        main_layout.addWidget(_separator())

        # ── 5. Size Variants ──────────────────────────────────────
        main_layout.addWidget(self._section_label("5. Size Variants"))
        main_layout.addWidget(self._section_desc(
            "Small (120px), Default (200px), Large (300px) — side by side."
        ))

        size_row = QHBoxLayout()
        size_row.setSpacing(12)

        for sz, label in [("sm", "sm (120px)"), ("default", "default (200px)"), ("lg", "lg (300px)")]:
            container = QWidget()
            container.setStyleSheet(f"background-color: {tm.surface.name()}; border-radius: 8px;")
            lo = QVBoxLayout(container)
            lo.setContentsMargins(8, 8, 8, 8)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"font-size: 11px; color: {tm.alpha_of(tm.mid, 60).name()}; background: transparent;")
            lo.addWidget(lbl)
            c = self._make_carousel(variant="slide", size=sz, indicators="outside")
            lo.addWidget(c)
            size_row.addWidget(container)

        main_layout.addLayout(size_row)
        main_layout.addWidget(_separator())

        # ── 6. Signal Demo ────────────────────────────────────────
        main_layout.addWidget(self._section_label("6. Signal Demo"))
        main_layout.addWidget(self._section_desc(
            "slide_changed(index) signal fires when the active slide changes."
        ))

        signal_row = QHBoxLayout()
        c6 = self._make_carousel(variant="slide", size="default")
        c6.setFixedHeight(220)
        signal_row.addWidget(c6, stretch=1)

        self._signal_label = QLabel("Current: slide 0")
        self._signal_label.setStyleSheet(f"""
            font-size: 13px;
            color: {tm.mid.name()};
            padding: 8px 16px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
            min-width: 140px;
        """)
        self._signal_label.setAlignment(Qt.AlignCenter)
        signal_row.addWidget(self._signal_label)
        c6.slide_changed.connect(self._on_slide_changed)

        main_layout.addLayout(signal_row)
        main_layout.addWidget(_separator())

        # ── 7. Programmatic Control ───────────────────────────────
        main_layout.addWidget(self._section_label("7. Programmatic Control"))
        main_layout.addWidget(self._section_desc(
            "Use prev() / next() / set_current_index() from code."
        ))

        c7 = self._make_carousel(variant="slide", size="default")
        c7.setFixedHeight(220)
        main_layout.addWidget(c7)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        btn_row.setSpacing(12)

        for label, slot in [
            ("‹  Previous", c7.prev),
            ("Go to Slide 2", lambda: c7.set_current_index(2)),
            ("Next  ›", c7.next),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: 12px;
                    color: {tm.text.name()};
                    background-color: {tm.surface.name()};
                    border: 1px solid {tm.mid.name()};
                    border-radius: 6px;
                    padding: 6px 16px;
                }}
                QPushButton:hover {{
                    background-color: {tm.mid.name()};
                }}
                QPushButton:pressed {{
                    background-color: {tm.alpha_of(tm.mid, 40).name()};
                }}
            """)
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)

        main_layout.addLayout(btn_row)

        # Scrollable outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_slide_changed(self, index: int):
        self._signal_label.setText(f"Current: slide {index}")
        self._signal_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 600;
            color: {tm.accent.name()};
            padding: 8px 16px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
            min-width: 140px;
        """)


def main():
    app = QApplication(sys.argv)
    demo = StyledCarouselDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
