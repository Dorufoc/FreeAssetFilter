"""StyledProgress Demo - showcases all progress bar variants."""

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
    QGroupBox,
    QScrollArea,
    QSlider,
    QPushButton,
)
from PySide6.QtCore import Qt, QTimer

from theme import tm

from components.styled_progress import StyledProgress
from components.styled_progress_circle import StyledProgressCircle


class StyledProgressDemo(QWidget):
    """Main demo window for StyledProgress components."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledProgress Demo")
        self.resize(700, 600)

        self._setup_ui()
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
            }}
        """)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: 600;
            color: {tm.text.name()};
            margin-bottom: 8px;
        """)
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;")
        return line

    def _setup_ui(self):
        # Main layout: scroll area wrapper
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {tm.surface.name()};
            }}
            QScrollBar:vertical {{
                background: {tm.surface.name()};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {tm.alpha_of(tm.mid, 60).name()};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        # Content widget
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(32, 24, 32, 24)
        content_layout.setSpacing(20)

        self._build_sections(content_layout)

        content_layout.addStretch()

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    def _build_sections(self, layout):
        """Build all demo sections."""
        # ── Section 1: Basic values ──
        layout.addWidget(self._section_label("1. Linear Progress - Basic Values"))

        for pct in [0, 30, 50, 75, 100]:
            row = QHBoxLayout()
            row.setSpacing(12)
            pct_label = QLabel(f"{pct}%")
            pct_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px; min-width: 36px;")
            pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(pct_label)

            progress = StyledProgress(value=pct / 100.0)
            row.addWidget(progress)
            layout.addLayout(row)

        layout.addWidget(self._separator())

        # ── Section 2: With Labels ──
        layout.addWidget(self._section_label("2. Linear Progress - With Labels"))

        prog_with_label1 = StyledProgress(
            value=0.5,
            label_title="上传进度",
            label_value="50%",
        )
        layout.addWidget(prog_with_label1)

        prog_with_label2 = StyledProgress(
            value=0.75,
            label_title="下载文件",
            label_value="75%",
        )
        layout.addWidget(prog_with_label2)

        layout.addWidget(self._separator())

        # ── Section 3: Inline Label ──
        layout.addWidget(self._section_label("3. Linear Progress - Inline Label"))

        prog_inline = StyledProgress(value=0.3, label_inline=True)
        layout.addWidget(prog_inline)

        layout.addWidget(self._separator())

        # ── Section 4: Color Variants ──
        layout.addWidget(self._section_label("4. Linear Progress - Color Variants"))

        for variant, label_text in [
            ("success", "Success (Green)"),
            ("warning", "Warning (Amber)"),
            ("danger", "Danger (Red)"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            var_label = QLabel(label_text)
            var_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px; min-width: 120px;")
            row.addWidget(var_label)

            progress = StyledProgress(value=0.65, variant=variant)
            row.addWidget(progress)
            layout.addLayout(row)

        layout.addWidget(self._separator())

        # ── Section 5: Size Variants ──
        layout.addWidget(self._section_label("5. Linear Progress - Size Variants"))

        for size_key in ["sm", "default", "lg"]:
            row = QHBoxLayout()
            row.setSpacing(12)
            size_label = QLabel(size_key)
            size_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px; min-width: 60px;")
            row.addWidget(size_label)

            progress = StyledProgress(value=0.65, size=size_key)
            row.addWidget(progress)
            layout.addLayout(row)

        layout.addWidget(self._separator())

        # ── Section 6: Striped / Animated ──
        layout.addWidget(self._section_label("6. Linear Progress - Striped / Animated"))

        prog_striped1 = StyledProgress(value=0.75, striped=True)
        layout.addWidget(prog_striped1)

        prog_striped2 = StyledProgress(
            value=0.85,
            variant="success",
            striped=True,
            label_title="同步中...",
            label_value="85%",
        )
        layout.addWidget(prog_striped2)

        prog_striped3 = StyledProgress(
            value=0.4,
            variant="warning",
            size="lg",
            striped=True,
        )
        layout.addWidget(prog_striped3)

        layout.addWidget(self._separator())

        # ── Section 7: Circular Progress - Basic ──
        layout.addWidget(self._section_label("7. Circular Progress - Basic Values"))

        circle_row = QHBoxLayout()
        circle_row.setSpacing(24)
        for pct in [25, 50, 75, 100]:
            circle = StyledProgressCircle(value=pct / 100.0, size="md")
            circle_row.addWidget(circle, alignment=Qt.AlignCenter)

        layout.addLayout(circle_row)

        layout.addWidget(self._separator())

        # ── Section 8: Circular Size Variants ──
        layout.addWidget(self._section_label("8. Circular Progress - Size Variants"))

        size_row = QHBoxLayout()
        size_row.setSpacing(32)
        for size_key in ["sm", "md", "lg"]:
            col = QVBoxLayout()
            col.setSpacing(8)

            circle = StyledProgressCircle(value=0.5, size=size_key)
            col.addWidget(circle, alignment=Qt.AlignCenter)

            size_lbl = QLabel(size_key)
            size_lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 11px;")
            size_lbl.setAlignment(Qt.AlignCenter)
            col.addWidget(size_lbl)

            size_row.addLayout(col)

        layout.addLayout(size_row)

        layout.addWidget(self._separator())

        # ── Section 9: Circular Color Variants ──
        layout.addWidget(self._section_label("9. Circular Progress - Color Variants"))

        color_row = QHBoxLayout()
        color_row.setSpacing(32)
        for variant, label_text in [
            ("success", "Success"),
            ("warning", "Warning"),
            ("danger", "Danger"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(8)

            val = 1.0 if variant == "success" else (0.5 if variant == "warning" else 0.25)
            circle = StyledProgressCircle(value=val, size="md", variant=variant)
            col.addWidget(circle, alignment=Qt.AlignCenter)

            var_lbl = QLabel(label_text)
            var_lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 11px;")
            var_lbl.setAlignment(Qt.AlignCenter)
            col.addWidget(var_lbl)

            color_row.addLayout(col)

        layout.addLayout(color_row)

        layout.addWidget(self._separator())

        # ── Section 10: Storage Usage Example (Web context) ──
        layout.addWidget(self._section_label("10. Storage Usage Example"))

        storage_group = QGroupBox()
        storage_group.setStyleSheet(f"""
            QGroupBox {{
                background-color: {tm.surface.name()};
                border-radius: 8px;
                padding: 16px;
                margin-top: 8px;
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
            }}
            QGroupBox::title {{
                color: {tm.text.name()};
                font-size: 14px;
                font-weight: 500;
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
                background: transparent;
            }}
            QGroupBox QLabel {{
                background: transparent;
            }}
        """)
        storage_layout = QVBoxLayout(storage_group)
        storage_layout.setSpacing(16)

        # Cloud Storage
        cloud_prog = StyledProgress(
            value=0.72,
            label_title="云端存储",
            label_value="7.2 GB / 10 GB",
        )
        storage_layout.addWidget(cloud_prog)

        # Local Cache
        cache_prog = StyledProgress(
            value=0.85,
            variant="warning",
            label_title="本地缓存",
            label_value="85%",
        )
        storage_layout.addWidget(cache_prog)

        # Backup
        backup_prog = StyledProgress(
            value=0.45,
            variant="success",
            striped=True,
            label_title="备份进度",
            label_value="正在备份...",
        )
        storage_layout.addWidget(backup_prog)

        # Sync Status
        sync_row = QHBoxLayout()
        sync_row.setSpacing(24)
        sync_circle = StyledProgressCircle(value=0.75, size="md")
        sync_row.addWidget(sync_circle)

        sync_info = QVBoxLayout()
        sync_info.setSpacing(2)
        sync_title = QLabel("同步完成度")
        sync_title.setStyleSheet(f"color: {tm.text.name()}; font-size: 13px;")
        sync_info.addWidget(sync_title)

        sync_sub = QLabel("预计剩余 3 分钟")
        sync_sub.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        sync_info.addWidget(sync_sub)

        sync_row.addLayout(sync_info)
        sync_row.addStretch()
        storage_layout.addLayout(sync_row)

        layout.addWidget(storage_group)

        layout.addWidget(self._separator())

        # ── Section 11: Interactive Dynamic Demo ──
        layout.addWidget(self._section_label("11. Interactive Dynamic Progress"))

        self._build_interactive_section(layout)

    def _build_interactive_section(self, layout):
        """Build interactive demo with real-time progress control."""
        container = QGroupBox()
        container.setStyleSheet(f"""
            QGroupBox {{
                background-color: {tm.surface.name()};
                border-radius: 8px;
                padding: 16px;
                margin-top: 8px;
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
            }}
            QGroupBox::title {{
                color: {tm.text.name()};
                font-size: 14px;
                font-weight: 500;
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
                background: transparent;
            }}
            QGroupBox QLabel {{
                background: transparent;
            }}
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(16)

        # ── Sub-section A: Slider-controlled linear progress ──
        slider_label = QLabel("Slider-Controlled Linear Progress")
        slider_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
        container_layout.addWidget(slider_label)

        self._slider_prog = StyledProgress(value=0.0, label_inline=True, size="lg")
        container_layout.addWidget(self._slider_prog)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(0)
        self._slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                width: 16px;
                height: 16px;
                margin: -5px 0;
                background: white;
                border-radius: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {tm.accent.name()};
                border-radius: 3px;
            }}
        """)
        self._slider.valueChanged.connect(self._on_slider_change)
        container_layout.addWidget(self._slider)

        # ── Sub-section B: Slider-controlled circular progress ──
        circ_label = QLabel("Slider-Controlled Circular Progress")
        circ_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
        container_layout.addWidget(circ_label)

        self._slider_circle = StyledProgressCircle(value=0.0, size="lg", variant="success")

        circ_ctrl = QHBoxLayout()
        circ_ctrl.addWidget(self._slider_circle, alignment=Qt.AlignCenter)
        circ_ctrl.addStretch()
        container_layout.addLayout(circ_ctrl)

        self._circle_slider = QSlider(Qt.Horizontal)
        self._circle_slider.setRange(0, 100)
        self._circle_slider.setValue(0)
        self._circle_slider.setStyleSheet(self._slider.styleSheet())
        self._circle_slider.valueChanged.connect(self._on_circle_slider_change)
        container_layout.addWidget(self._circle_slider)

        # ── Sub-section C: Auto-stepping demo ──
        auto_label = QLabel("Auto-Stepping Progress (Multiple Speeds)")
        auto_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
        container_layout.addWidget(auto_label)

        self._auto_rows = []

        for label_text, variant, step in [
            ("Slow (5% step)", "default", 5),
            ("Medium (10% step)", "success", 10),
            ("Fast (20% step)", "warning", 20),
            ("Instant (100% step)", "danger", 100),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)

            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 11px; min-width: 110px;")
            row.addWidget(lbl)

            prog = StyledProgress(value=0.0, variant=variant, striped=True)
            row.addWidget(prog)

            val_lbl = QLabel("0%")
            val_lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 11px; min-width: 32px;")
            row.addWidget(val_lbl)

            container_layout.addLayout(row)
            self._auto_rows.append({
                "prog": prog,
                "label": val_lbl,
                "step": step,
                "value": 0,
            })

        # Control buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._auto_start_btn = QPushButton("Start")
        self._auto_start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.accent.name()};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {tm.accent_hover.name()};
            }}
        """)
        self._auto_start_btn.setCursor(Qt.PointingHandCursor)
        self._auto_start_btn.clicked.connect(self._toggle_auto_anim)
        btn_row.addWidget(self._auto_start_btn)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                color: {tm.mid.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 5px;
                padding: 6px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                color: {tm.text.name()};
            }}
        """)
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.clicked.connect(self._reset_auto_anim)
        btn_row.addWidget(self._reset_btn)

        btn_row.addStretch()
        container_layout.addLayout(btn_row)

        # Auto animation timer
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._step_auto_anim)
        self._auto_running = False

        layout.addWidget(container)

    def _on_slider_change(self, value):
        """Update linear progress from slider."""
        v = value / 100.0
        self._slider_prog.value = v
        self._slider_prog.set_value_label(f"{value}%")

    def _on_circle_slider_change(self, value):
        """Update circular progress from slider."""
        self._slider_circle.value = value / 100.0

    def _toggle_auto_anim(self):
        """Start/stop auto-stepping animation."""
        if self._auto_running:
            self._auto_timer.stop()
            self._auto_running = False
            self._auto_start_btn.setText("Start")
        else:
            self._auto_timer.start(500)
            self._auto_running = True
            self._auto_start_btn.setText("Pause")

    def _step_auto_anim(self):
        """Step all auto progress rows."""
        for row in self._auto_rows:
            row["value"] += row["step"]
            if row["value"] > 100:
                row["value"] = 0
            v = row["value"] / 100.0
            row["prog"].value = v
            row["label"].setText(f"{row['value']}%")

    def _reset_auto_anim(self):
        """Reset all auto progress rows."""
        self._auto_timer.stop()
        self._auto_running = False
        self._auto_start_btn.setText("Start")
        for row in self._auto_rows:
            row["value"] = 0
            row["prog"].value = 0.0
            row["label"].setText("0%")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    demo = StyledProgressDemo()
    demo.show()
    sys.exit(app.exec())
