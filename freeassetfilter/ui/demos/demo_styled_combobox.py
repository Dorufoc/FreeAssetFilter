"""
Demo: StyledComboBox
Demonstrates all features of the StyledComboBox component.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from theme import tm

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QGridLayout,
    QPushButton,
)
from PySide6.QtCore import Qt

from components.styled_combobox import StyledComboBox


class ComboboxDemo(QWidget):
    """Main demo window for StyledComboBox."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledComboBox Demo")
        self.resize(700, 500)
        self.setStyleSheet(f"background-color: {tm.surface.name()}; color: {tm.text.name()};")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 28)
        main_layout.setSpacing(28)

        # ── Section: Sizes ──
        main_layout.addWidget(self._build_sizes_section())
        # ── Section: With Divider ──
        main_layout.addWidget(self._build_divider_section())
        # ── Section: Right Aligned ──
        main_layout.addWidget(self._build_right_align_section())
        # ── Section: Many Items ──
        main_layout.addWidget(self._build_many_items_section())
        # ── Section: Events ──
        main_layout.addWidget(self._build_events_section())
        # ── Section: Use Cases ──
        main_layout.addWidget(self._build_use_cases_section())

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

    def _build_sizes_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Sizes"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(16)

        items = ["选项 A", "选项 B", "选项 C", "选项 D", "选项 E"]

        sm_combo = StyledComboBox(items=items, size="sm")
        sm_combo.setFixedWidth(160)
        sm_label = QLabel("sm")
        sm_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        sm_col = QVBoxLayout()
        sm_col.addWidget(sm_label)
        sm_col.addWidget(sm_combo)
        row.addLayout(sm_col)

        default_combo = StyledComboBox(items=items, size="default")
        default_combo.setFixedWidth(160)
        default_label = QLabel("default")
        default_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        default_col = QVBoxLayout()
        default_col.addWidget(default_label)
        default_col.addWidget(default_combo)
        row.addLayout(default_col)

        lg_combo = StyledComboBox(items=items, size="lg")
        lg_combo.setFixedWidth(160)
        lg_label = QLabel("lg")
        lg_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        lg_col = QVBoxLayout()
        lg_col.addWidget(lg_label)
        lg_col.addWidget(lg_combo)
        row.addLayout(lg_col)

        row.addStretch()
        layout.addLayout(row)

        return wrapper

    def _build_divider_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("With Divider"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(16)

        # Theme selector with divider
        theme_items = ["浅色模式", "深色模式", "---", "系统跟随"]
        theme_combo = StyledComboBox(items=theme_items, size="default")
        theme_combo.setFixedWidth(180)
        theme_combo.setCurrentIndex(1)
        
        theme_label = QLabel("主题")
        theme_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        theme_col = QVBoxLayout()
        theme_col.addWidget(theme_label)
        theme_col.addWidget(theme_combo)
        row.addLayout(theme_col)

        # Language selector with divider
        lang_items = ["简体中文", "English", "---", "日本語", "한국어"]
        lang_combo = StyledComboBox(items=lang_items, size="default")
        lang_combo.setFixedWidth(180)
        lang_combo.setCurrentIndex(0)
        
        lang_label = QLabel("语言")
        lang_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        lang_col = QVBoxLayout()
        lang_col.addWidget(lang_label)
        lang_col.addWidget(lang_combo)
        row.addLayout(lang_col)

        row.addStretch()
        layout.addLayout(row)

        return wrapper

    def _build_right_align_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Right Aligned"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(16)

        items = ["选项 A", "选项 B", "选项 C"]

        # Left aligned (default)
        left_combo = StyledComboBox(items=items, size="default", align_right=False)
        left_combo.setFixedWidth(180)
        left_combo.setCurrentIndex(0)
        
        left_label = QLabel("左对齐")
        left_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        left_col = QVBoxLayout()
        left_col.addWidget(left_label)
        left_col.addWidget(left_combo)
        row.addLayout(left_col)

        # Right aligned
        right_combo = StyledComboBox(items=items, size="default", align_right=True)
        right_combo.setFixedWidth(180)
        right_combo.setCurrentIndex(0)
        
        right_label = QLabel("右对齐")
        right_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        right_col = QVBoxLayout()
        right_col.addWidget(right_label)
        right_col.addWidget(right_combo)
        row.addLayout(right_col)

        row.addStretch()
        layout.addLayout(row)

        return wrapper

    def _build_many_items_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("With Many Items"))
        layout.addWidget(self._separator())

        many_items = [f"Item {i}" for i in range(1, 21)]
        many_combo = StyledComboBox(items=many_items, size="default")
        many_combo.setFixedWidth(200)
        many_combo.setCurrentIndex(0)

        layout.addWidget(many_combo)

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

        event_combo = StyledComboBox(
            items=["选项 A", "选项 B", "选项 C", "选项 D", "选项 E"],
            size="default",
        )
        event_combo.setFixedWidth(180)

        self._event_label = QLabel("当前选择: 选项 A")
        self._event_label.setStyleSheet(f"color: {tm.mid.name()}; font-size: 13px;")

        event_combo.selection_made.connect(
            lambda text: self._event_label.setText(f"当前选择: {text}")
        )

        reset_btn = QPushButton("重置为索引 0")
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.mid.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 6px;
                color: {tm.mid.name()};
                font-size: 13px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                background-color: {tm.mid.name()};
            }}
        """)
        reset_btn.clicked.connect(lambda: event_combo.setCurrentIndex(0))

        row.addWidget(event_combo)
        row.addWidget(self._event_label)
        row.addWidget(reset_btn)
        row.addStretch()

        layout.addLayout(row)

        return wrapper

    def _build_use_cases_section(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("Use Cases"))
        layout.addWidget(self._separator())

        row = QHBoxLayout()
        row.setSpacing(24)

        # Language selector
        lang_col = QVBoxLayout()
        lang_label = QLabel("语言")
        lang_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        lang_combo = StyledComboBox(
            items=["简体中文", "English", "日本語"],
            size="default",
        )
        lang_combo.setFixedWidth(180)
        lang_combo.setCurrentText("简体中文")
        lang_col.addWidget(lang_label)
        lang_col.addWidget(lang_combo)
        row.addLayout(lang_col)

        # Theme selector
        theme_col = QVBoxLayout()
        theme_label = QLabel("主题")
        theme_label.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 60).name()}; font-size: 12px;")
        theme_combo = StyledComboBox(
            items=["浅色", "深色", "跟随系统"],
            size="default",
        )
        theme_combo.setFixedWidth(180)
        theme_combo.setCurrentText("深色")
        theme_col.addWidget(theme_label)
        theme_col.addWidget(theme_combo)
        row.addLayout(theme_col)

        row.addStretch()
        layout.addLayout(row)

        return wrapper


def main():
    app = QApplication(sys.argv)
    demo = ComboboxDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
