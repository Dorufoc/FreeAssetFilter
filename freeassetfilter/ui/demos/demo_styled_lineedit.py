"""StyledLineEdit Demo - standalone demo for all line edit variants."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

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

from theme import tm

from components.styled_lineedit import StyledLineEdit, InputWrapper


def make_section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"font-size: 14px; font-weight: 600; color: {tm.text.name()}; margin-top: 4px;"
    )
    return label


def make_sub_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; margin-bottom: 2px;")
    return label


def build_sizes_section() -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    sm = StyledLineEdit(size="sm")
    sm.setPlaceholderText("SM - 小尺寸")

    default = StyledLineEdit(size="default")
    default.setPlaceholderText("Default - 默认尺寸")

    lg = StyledLineEdit(size="lg")
    lg.setPlaceholderText("LG - 大尺寸")

    layout.addWidget(sm)
    layout.addWidget(default)
    layout.addWidget(lg)
    return container


def build_states_section() -> QWidget:
    container = QWidget()
    grid = QGridLayout(container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(8)

    normal = StyledLineEdit(size="default")
    normal.setPlaceholderText("Normal - 正常状态")
    grid.addWidget(make_sub_label("Normal"), 0, 0)
    grid.addWidget(normal, 1, 0)

    disabled = StyledLineEdit(size="default")
    disabled.setPlaceholderText("Disabled - 禁用状态")
    disabled.setEnabled(False)
    grid.addWidget(make_sub_label("Disabled"), 0, 1)
    grid.addWidget(disabled, 1, 1)

    error = StyledLineEdit(size="default", error=True)
    error.setPlaceholderText("Error - 错误状态")
    grid.addWidget(make_sub_label("Error"), 2, 0)
    grid.addWidget(error, 2, 1)

    readonly = StyledLineEdit(size="default")
    readonly.setPlaceholderText("ReadOnly - 只读状态")
    readonly.setReadOnly(True)
    grid.addWidget(make_sub_label("ReadOnly"), 3, 0)
    grid.addWidget(readonly, 3, 1)

    return container


def build_icons_section() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    sizes = ["sm", "default", "lg"]
    for sz in sizes:
        wrapper = InputWrapper(
            placeholder=f"InputWrapper {sz.upper()} - 带图标输入框",
            size=sz,
        )
        layout.addWidget(wrapper)

    return container


def build_events_section() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    row = QHBoxLayout()
    row.setSpacing(12)

    line_edit = StyledLineEdit(size="default")
    line_edit.setPlaceholderText("输入文本查看实时变化...")
    row.addWidget(line_edit)

    toggle_btn = QPushButton("Toggle Error")
    toggle_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {tm.alpha_of(tm.mid, 40).name()};
            color: {tm.text.name()};
            border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {tm.surface.name()};
        }}
    """)
    row.addWidget(toggle_btn)

    layout.addLayout(row)

    output_label = QLabel("当前输入:（空）")
    output_label.setStyleSheet(
        f"font-size: 13px; color: {tm.accent.name()}; padding: 6px 0;"
    )

    def on_text_changed(text: str):
        output_label.setText(f"当前输入: {text}" if text else "当前输入:（空）")

    def on_toggle():
        line_edit.error = not line_edit.error
        toggle_btn.setText("Error ON" if line_edit.error else "Error OFF")

    line_edit.textChanged.connect(on_text_changed)
    toggle_btn.clicked.connect(on_toggle)

    layout.addWidget(output_label)
    return container


def main():
    app = QApplication(sys.argv)

    app.setStyleSheet(f"""
        QWidget {{
            background-color: {tm.surface.name()};
        }}
    """)

    window = QWidget()
    window.setWindowTitle("StyledLineEdit Demo")
    window.resize(800, 600)

    main_layout = QVBoxLayout(window)
    main_layout.setContentsMargins(32, 24, 32, 24)
    main_layout.setSpacing(16)

    # Section 1: Sizes
    main_layout.addWidget(make_section_label("1. Sizes / 尺寸"))
    main_layout.addWidget(build_sizes_section())

    # Separator
    sep1 = QFrame()
    sep1.setFrameShape(QFrame.HLine)
    sep1.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep1)

    # Section 2: States
    main_layout.addWidget(make_section_label("2. States / 状态"))
    main_layout.addWidget(build_states_section())

    # Separator
    sep2 = QFrame()
    sep2.setFrameShape(QFrame.HLine)
    sep2.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep2)

    # Section 3: With Icons
    main_layout.addWidget(make_section_label("3. With Icons / 带图标"))
    main_layout.addWidget(build_icons_section())

    # Separator
    sep3 = QFrame()
    sep3.setFrameShape(QFrame.HLine)
    sep3.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    main_layout.addWidget(sep3)

    # Section 4: Events
    main_layout.addWidget(make_section_label("4. Events / 事件"))
    main_layout.addWidget(build_events_section())

    main_layout.addStretch()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
