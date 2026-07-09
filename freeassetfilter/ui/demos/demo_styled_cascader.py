"""
Demo: StyledCascader
Demonstrates multi-level cascader with geography data, single select, and disabled state.
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
    QPushButton,
)
from PySide6.QtCore import Qt
from theme import tm

from components.styled_cascader import StyledCascader


# ── 3-level geography data ─────────────────────────────────────────────────

GEO_DATA = [
    {
        "label": "Guangdong",
        "value": "gd",
        "children": [
            {
                "label": "Shenzhen",
                "value": "sz",
                "children": [
                    {"label": "Nanshan", "value": "ns"},
                    {"label": "Futian", "value": "ft"},
                    {"label": "Luohu", "value": "lh"},
                    {"label": "Bao'an", "value": "ba"},
                    {"label": "Longgang", "value": "lg"},
                ],
            },
            {
                "label": "Guangzhou",
                "value": "gz",
                "children": [
                    {"label": "Tianhe", "value": "th"},
                    {"label": "Yuexiu", "value": "yx"},
                    {"label": "Haizhu", "value": "hz"},
                    {"label": "Liwan", "value": "lw"},
                ],
            },
            {
                "label": "Dongguan",
                "value": "dg",
                "children": [
                    {"label": "Nancheng", "value": "nc"},
                    {"label": "Dongcheng", "value": "dc"},
                    {"label": "Wanjiang", "value": "wj"},
                ],
            },
        ],
    },
    {
        "label": "Zhejiang",
        "value": "zj",
        "children": [
            {
                "label": "Hangzhou",
                "value": "hz",
                "children": [
                    {"label": "Xihu", "value": "xh"},
                    {"label": "Binjiang", "value": "bj"},
                    {"label": "Yuhang", "value": "yh"},
                ],
            },
            {
                "label": "Ningbo",
                "value": "nb",
                "children": [
                    {"label": "Haishu", "value": "hs"},
                    {"label": "Jiangbei", "value": "jb"},
                ],
            },
        ],
    },
    {
        "label": "Beijing",
        "value": "bj",
        "children": [
            {
                "label": "Haidian",
                "value": "hd",
                "children": [
                    {"label": "Zhongguancun", "value": "zgc"},
                    {"label": "Wudaokou", "value": "wdk"},
                ],
            },
            {
                "label": "Chaoyang",
                "value": "cy",
                "children": [
                    {"label": "Guomao", "value": "gm"},
                    {"label": "Sanlitun", "value": "slt"},
                ],
            },
        ],
    },
]


class CascaderDemo(QWidget):
    """Main demo window for StyledCascader."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledCascader Demo")
        self.resize(720, 520)
        self.setStyleSheet(f"background-color: {tm.surface.name()}; color: {tm.text.name()};")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 28)
        main_layout.setSpacing(28)

        # ── Section: Basic ──
        main_layout.addWidget(self._build_basic_section())
        # ── Section: Disabled ──
        main_layout.addWidget(self._build_disabled_section())
        # ── Section: Events ──
        main_layout.addWidget(self._build_events_section())
        # ── Section: Programmatic Control ──
        main_layout.addWidget(self._build_control_section())

        main_layout.addStretch()

    # ── helpers ──

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {tm.text.name()};")
        return label

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 40).name()}; max-height: 1px;")
        return line

    # ── sections ──

    def _build_basic_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Basic Cascader"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(24)

        # Standard cascader
        col1 = QVBoxLayout()
        col1.addWidget(QLabel("地级市选择"))
        col1_label = QLabel("请选择省/市/区")
        col1_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        col1.addWidget(col1_label)

        basic_cascader = StyledCascader(data=GEO_DATA)
        basic_cascader.setFixedWidth(280)
        col1.addWidget(basic_cascader)
        row.addLayout(col1)

        # Cascader with pre-selected value
        col2 = QVBoxLayout()
        col2.addWidget(QLabel("预选地区"))
        col2_label = QLabel("初始已选中南山区")
        col2_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        col2.addWidget(col2_label)

        preset_cascader = StyledCascader(data=GEO_DATA)
        preset_cascader.setFixedWidth(280)
        preset_cascader.setSelectedPath([
            {"label": "Guangdong", "value": "gd"},
            {"label": "Shenzhen", "value": "sz"},
            {"label": "Nanshan", "value": "ns"},
        ])
        col2.addWidget(preset_cascader)
        row.addLayout(col2)

        row.addStretch()
        layout.addLayout(row)

        return wrapper

    def _build_disabled_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Disabled State"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(24)

        # Disabled with no selection
        col1 = QVBoxLayout()
        col1.addWidget(QLabel("禁用（未选择）"))
        col1_label = QLabel("不可交互")
        col1_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        col1.addWidget(col1_label)

        disabled_empty = StyledCascader(data=GEO_DATA)
        disabled_empty.setFixedWidth(280)
        disabled_empty.setEnabled(False)
        col1.addWidget(disabled_empty)
        row.addLayout(col1)

        # Disabled with selection
        col2 = QVBoxLayout()
        col2.addWidget(QLabel("禁用（已选择）"))
        col2_label = QLabel("显示已选项但不能修改")
        col2_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        col2.addWidget(col2_label)

        disabled_selected = StyledCascader(data=GEO_DATA)
        disabled_selected.setFixedWidth(280)
        disabled_selected.setSelectedPath([
            {"label": "Beijing", "value": "bj"},
            {"label": "Haidian", "value": "hd"},
            {"label": "Zhongguancun", "value": "zgc"},
        ])
        disabled_selected.setEnabled(False)
        col2.addWidget(disabled_selected)
        row.addLayout(col2)

        row.addStretch()
        layout.addLayout(row)

        return wrapper

    def _build_events_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Events"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(16)

        event_cascader = StyledCascader(data=GEO_DATA)
        event_cascader.setFixedWidth(280)

        self._event_label = QLabel("请选择一个地区")
        self._event_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 13px;")
        self._event_label.setWordWrap(True)

        event_cascader.path_changed.connect(self._on_path_changed)

        row.addWidget(event_cascader)
        row.addWidget(self._event_label)
        row.addStretch()

        layout.addLayout(row)

        return wrapper

    def _build_control_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Programmatic Control"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(16)

        control_cascader = StyledCascader(data=GEO_DATA)
        control_cascader.setFixedWidth(280)
        self._control_cascader = control_cascader

        reset_btn = QPushButton("清除选择")
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 6px;
                color: {tm.mid.name()};
                font-size: 13px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 50).name()};
            }}
        """)
        reset_btn.clicked.connect(lambda: control_cascader.setSelectedPath([]))

        preset_btn = QPushButton("预设: 西溪")
        preset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 6px;
                color: {tm.mid.name()};
                font-size: 13px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 50).name()};
            }}
        """)
        preset_btn.clicked.connect(self._preset_xihu)

        row.addWidget(control_cascader)
        row.addWidget(reset_btn)
        row.addWidget(preset_btn)
        row.addStretch()

        layout.addLayout(row)

        return wrapper

    # ── callbacks ──

    def _on_path_changed(self, path: list[dict]):
        if not path:
            self._event_label.setText("已清除选择")
            return
        labels = " / ".join(item.get("label", "") for item in path)
        values = ", ".join(item.get("value", "") for item in path)
        self._event_label.setText(f"选中: {labels}\n值: [{values}]")

    def _preset_xihu(self):
        self._control_cascader.setSelectedPath([
            {"label": "Zhejiang", "value": "zj"},
            {"label": "Hangzhou", "value": "hz"},
            {"label": "Xihu", "value": "xh"},
        ])


def main():
    app = QApplication(sys.argv)
    demo = CascaderDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
