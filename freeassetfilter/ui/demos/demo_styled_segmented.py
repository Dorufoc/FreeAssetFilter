"""StyledSegmented Demo — showcases the segmented control (分段按钮).

Sections:
  1. Pill variant (default) — capsule indicator slides behind active option
  2. Underline variant — accent underline bar slides beneath active option
  3. Size variants (sm / default / lg)
  4. Disabled segments
  5. Icon segments
  6. Interactive — click feedback log + programmatic switching
"""

import sys
import os

# Make both the ui package (for ``theme`` / ``components`` short-path imports)
# and the project root (for ``freeassetfilter.core.*`` used by ThemeManager
# via SettingsManagerV2) importable when running this file directly.
_UI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _UI_DIR not in sys.path:
    sys.path.insert(0, _UI_DIR)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

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
from components.styled_segmented import StyledSegmented


class StyledSegmentedDemo(QWidget):
    """Main demo window for StyledSegmented."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledSegmented Demo - 分段按钮")
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
        """Return a panel for grouping examples."""
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

        # ── Section 1: Pill variant (default) ──────────────────────
        self._build_pill_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 2: Underline variant ───────────────────────────
        self._build_underline_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 3: Size variants ───────────────────────────────
        self._build_size_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 4: Disabled segments ───────────────────────────
        self._build_disabled_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 5: Icon segments ───────────────────────────────
        self._build_icon_section(main_layout)
        main_layout.addWidget(self._separator())

        # ── Section 6: Interactive ─────────────────────────────────
        self._build_interactive_section(main_layout)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Section 1: Pill variant ───────────────────────────────────

    def _build_pill_section(self, layout):
        layout.addWidget(self._section_label("1. Pill 变体（默认）"))
        layout.addWidget(
            self._section_desc("胶囊滑块平滑滑动到当前焦点选项，选中项文字为高对比色")
        )

        seg = StyledSegmented(variant="pill")
        seg.add_segment("全部")
        seg.add_segment("图片")
        seg.add_segment("视频")
        seg.add_segment("音频")
        layout.addWidget(seg)

    # ── Section 2: Underline variant ──────────────────────────────

    def _build_underline_section(self, layout):
        layout.addWidget(self._section_label("2. Underline 变体"))
        layout.addWidget(
            self._section_desc("底部强调条平滑滑动，选中项文字使用主题强调色")
        )

        seg = StyledSegmented(variant="underline")
        seg.add_segment("最近")
        seg.add_segment("今天")
        seg.add_segment("本周")
        seg.add_segment("本月")
        layout.addWidget(seg)

    # ── Section 3: Size variants ──────────────────────────────────

    def _build_size_section(self, layout):
        layout.addWidget(self._section_label("3. 尺寸变体"))
        layout.addWidget(self._section_desc("Small / Default / Large 三档尺寸"))

        for size_key, label in [("sm", "Small"), ("default", "Default"), ("lg", "Large")]:
            row = QHBoxLayout()
            row.setSpacing(12)

            size_lbl = QLabel(label)
            size_lbl.setStyleSheet(
                f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; min-width: 60px;"
            )
            size_lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            row.addWidget(size_lbl)

            seg = StyledSegmented(variant="pill", size=size_key)
            seg.add_segment("低")
            seg.add_segment("中")
            seg.add_segment("高")
            row.addWidget(seg)
            row.addStretch()

            layout.addLayout(row)

    # ── Section 4: Disabled segments ──────────────────────────────

    def _build_disabled_section(self, layout):
        layout.addWidget(self._section_label("4. 禁用段"))
        layout.addWidget(
            self._section_desc("禁用段不可点击、不可通过键盘导航，并跳过动画切换")
        )

        seg = StyledSegmented(variant="pill")
        seg.add_segment("启用")
        seg.add_segment("已禁用", disabled=True)
        seg.add_segment("启用")
        layout.addWidget(seg)

    # ── Section 5: Icon segments ──────────────────────────────────

    def _build_icon_section(self, layout):
        layout.addWidget(self._section_label("5. 带图标的段"))
        layout.addWidget(self._section_desc("图标渲染在文字左侧，随选中状态切换颜色"))

        seg = StyledSegmented(variant="pill", size="lg")
        seg.add_segment("网格", icon="grid")
        seg.add_segment("搜索", icon="search")
        seg.add_segment("设置", icon="gear")
        seg.add_segment("收藏", icon="star")
        layout.addWidget(seg)

    # ── Section 6: Interactive ────────────────────────────────────

    def _build_interactive_section(self, layout):
        layout.addWidget(self._section_label("6. 交互演示"))
        layout.addWidget(
            self._section_desc(
                "点击分段或使用左右方向键切换；底部按钮可程序化切换当前焦点。"
            )
        )

        panel = self._make_panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 12, 16, 12)
        panel_layout.setSpacing(12)

        self._iseg = StyledSegmented(variant="pill")
        self._iseg.add_segment("首页")
        self._iseg.add_segment("发现")
        self._iseg.add_segment("消息")
        self._iseg.add_segment("我的")
        panel_layout.addWidget(self._iseg)

        # Button row — programmatic switching
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._prev_btn = QPushButton("◀ 上一个")
        self._prev_btn.clicked.connect(self._go_prev)
        self._style_button(self._prev_btn, tm.mid.name())
        btn_row.addWidget(self._prev_btn)

        self._current_lbl = QLabel("当前选项：1 / 4")
        self._current_lbl.setStyleSheet(f"color: {tm.mid.name()}; font-size: 12px;")
        btn_row.addWidget(self._current_lbl)

        self._next_btn = QPushButton("下一个  ▶")
        self._next_btn.clicked.connect(self._go_next)
        self._style_button(self._next_btn, tm.accent.name())
        btn_row.addWidget(self._next_btn)

        btn_row.addStretch()
        panel_layout.addLayout(btn_row)

        # Event log
        self._event_label = QLabel("尚未点击任何分段")
        self._event_label.setStyleSheet(f"""
            font-size: 12px;
            color: {tm.alpha_of(tm.mid, 60).name()};
            padding: 8px 12px;
            background-color: {tm.surface.name()};
            border-radius: 6px;
        """)
        panel_layout.addWidget(self._event_label)

        self._iseg.current_changed.connect(self._on_current_changed)
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
        cur = self._iseg.current_index
        if cur > 0:
            self._iseg.set_current_index(cur - 1)

    def _go_next(self):
        cur = self._iseg.current_index
        if cur < self._iseg.segment_count() - 1:
            self._iseg.set_current_index(cur + 1)

    def _on_current_changed(self, index: int):
        self._current_lbl.setText(f"当前选项：{index + 1} / {self._iseg.segment_count()}")
        self._event_label.setText(f"已切换到第 {index + 1} 项 — 滑块动画进行中")


def main():
    app = QApplication(sys.argv)
    demo = StyledSegmentedDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
