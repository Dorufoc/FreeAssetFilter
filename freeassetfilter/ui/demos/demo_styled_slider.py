"""StyledSlider Demo - standalone demo showcasing all slider features."""

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
    QGridLayout,
)
from PySide6.QtCore import Qt

from theme import tm

from components.styled_slider import StyledSlider


class StyledSliderDemo(QWidget):
    """Main demo window for StyledSlider."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledSlider Demo")
        self.resize(800, 600)

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

    def _make_value_label(self) -> QLabel:
        label = QLabel("0.50")
        label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 13px;")
        label.setMinimumWidth(48)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return label

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 24, 32, 24)
        main_layout.setSpacing(16)

        # ── Section 1: Sizes ──
        main_layout.addWidget(self._section_label("1. Sizes"))

        sizes_layout = QGridLayout()
        sizes_layout.setSpacing(8)

        for row_idx, size_key in enumerate(["sm", "default", "lg"]):
            name_lbl = QLabel(size_key)
            name_lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
            sizes_layout.addWidget(name_lbl, row_idx, 0, Qt.AlignVCenter)

            slider = StyledSlider(value=0.5, size=size_key)
            sizes_layout.addWidget(slider, row_idx, 1)

            val_lbl = self._make_value_label()
            val_lbl.setText(f"{slider.value:.2f}")
            slider.value_changed.connect(lambda v, lbl=val_lbl: lbl.setText(f"{v:.2f}"))
            sizes_layout.addWidget(val_lbl, row_idx, 2)

        main_layout.addLayout(sizes_layout)
        main_layout.addWidget(self._separator())

        # ── Section 2: With Ticks ──
        main_layout.addWidget(self._section_label("2. With Ticks"))

        ticks_layout = QGridLayout()
        ticks_layout.setSpacing(8)

        # tick_count=5
        ticks_layout.addWidget(QLabel("5 ticks"), 0, 0, Qt.AlignVCenter)
        slider_t5 = StyledSlider(value=0.4, tick_count=5)
        ticks_layout.addWidget(slider_t5, 0, 1)
        val_t5 = self._make_value_label()
        val_t5.setText(f"{slider_t5.value:.2f}")
        slider_t5.value_changed.connect(lambda v, lbl=val_t5: lbl.setText(f"{v:.2f}"))
        ticks_layout.addWidget(val_t5, 0, 2)

        # tick_count=10
        ticks_layout.addWidget(QLabel("10 ticks"), 1, 0, Qt.AlignVCenter)
        slider_t10 = StyledSlider(value=0.6, tick_count=10)
        ticks_layout.addWidget(slider_t10, 1, 1)
        val_t10 = self._make_value_label()
        val_t10.setText(f"{slider_t10.value:.2f}")
        slider_t10.value_changed.connect(lambda v, lbl=val_t10: lbl.setText(f"{v:.2f}"))
        ticks_layout.addWidget(val_t10, 1, 2)

        main_layout.addLayout(ticks_layout)
        main_layout.addWidget(self._separator())

        # ── Section 3: With Labels ──
        main_layout.addWidget(self._section_label("3. With Labels"))

        labels_layout = QVBoxLayout()
        labels_layout.setSpacing(12)

        # Chinese quality labels
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Rating"))
        slider_zh = StyledSlider(
            value=0.5, tick_count=5,
            labels=["很低", "低", "中", "高", "很高"],
        )
        row1.addWidget(slider_zh)
        val_zh = self._make_value_label()
        val_zh.setText(f"{slider_zh.value:.2f}")
        slider_zh.value_changed.connect(lambda v, lbl=val_zh: lbl.setText(f"{v:.2f}"))
        row1.addWidget(val_zh)
        labels_layout.addLayout(row1)

        # Numeric labels 1-10
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Level"))
        slider_num = StyledSlider(
            value=0.5,
            labels=["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        )
        row2.addWidget(slider_num)
        val_num = self._make_value_label()
        val_num.setText(f"{slider_num.value:.2f}")
        slider_num.value_changed.connect(lambda v, lbl=val_num: lbl.setText(f"{v:.2f}"))
        row2.addWidget(val_num)
        labels_layout.addLayout(row2)

        main_layout.addLayout(labels_layout)
        main_layout.addWidget(self._separator())

        # ── Section 4: States ──
        main_layout.addWidget(self._section_label("4. States"))

        states_layout = QGridLayout()
        states_layout.setSpacing(8)

        states_layout.addWidget(QLabel("Enabled"), 0, 0, Qt.AlignVCenter)
        slider_enabled = StyledSlider(value=0.7)
        states_layout.addWidget(slider_enabled, 0, 1)
        val_en = self._make_value_label()
        val_en.setText(f"{slider_enabled.value:.2f}")
        slider_enabled.value_changed.connect(lambda v, lbl=val_en: lbl.setText(f"{v:.2f}"))
        states_layout.addWidget(val_en, 0, 2)

        states_layout.addWidget(QLabel("Disabled"), 1, 0, Qt.AlignVCenter)
        slider_disabled = StyledSlider(value=0.3)
        slider_disabled.setEnabled(False)
        states_layout.addWidget(slider_disabled, 1, 1)
        val_dis = self._make_value_label()
        val_dis.setText(f"{slider_disabled.value:.2f}")
        states_layout.addWidget(val_dis, 1, 2)

        main_layout.addLayout(states_layout)
        main_layout.addWidget(self._separator())

        # ── Section 5: Volume ──
        main_layout.addWidget(self._section_label("5. Volume"))

        volume_layout = QHBoxLayout()
        volume_layout.setSpacing(12)

        speaker_label = QLabel("\U0001F50A")
        speaker_label.setStyleSheet(f"font-size: 22px; color: {tm.mid.name()}; background: transparent;")
        volume_layout.addWidget(speaker_label)

        volume_slider = StyledSlider(value=0.75)
        volume_layout.addWidget(volume_slider)

        vol_val = self._make_value_label()
        vol_val.setText(f"{volume_slider.value:.2f}")
        volume_slider.value_changed.connect(lambda v, lbl=vol_val: lbl.setText(f"{v:.2f}"))
        volume_layout.addWidget(vol_val)

        volume_layout.addStretch()

        main_layout.addLayout(volume_layout)
        main_layout.addStretch()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    demo = StyledSliderDemo()
    demo.show()
    sys.exit(app.exec())
