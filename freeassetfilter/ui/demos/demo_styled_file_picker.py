"""StyledFilePicker Demo — file picker, folder picker, dropzone, sizes, states."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from theme import tm

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

from components.styled_file_picker import StyledFilePicker, StyledFileDropZone


# ── Helpers ──────────────────────────────────────────────────────────────


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"font-size: 14px; font-weight: 600; color: {tm.text.name()}; margin-top: 4px;"
    )
    return label


def _sub_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 12px; color: {tm.mid.name()}; margin-bottom: 2px;")
    return label


def _separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.HLine)
    sep.setStyleSheet(f"color: {tm.alpha_of(tm.mid, 30).name()};")
    return sep


# ── Section builders ─────────────────────────────────────────────────────


def build_modes_section() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    layout.addWidget(_sub_label("File mode — 选择文件"))
    fp = StyledFilePicker(mode="file", placeholder="选择文本文件...")
    layout.addWidget(fp)

    layout.addWidget(_sub_label("Folder mode — 选择文件夹"))
    fp2 = StyledFilePicker(mode="folder", placeholder="选择目标文件夹...")
    layout.addWidget(fp2)

    # Signal feedback
    feedback = QLabel("")
    feedback.setStyleSheet(f"font-size: 12px; color: {tm.accent.name()}; padding: 2px 0;")

    def on_file_chosen(path: str):
        feedback.setText(f"已选择: {path}")

    fp.path_chosen.connect(on_file_chosen)
    fp2.path_chosen.connect(on_file_chosen)
    layout.addWidget(feedback)

    return container


def build_sizes_section() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    layout.addWidget(_sub_label("SM — 小尺寸"))
    sm = StyledFilePicker(size="sm", placeholder="小尺寸")
    layout.addWidget(sm)

    layout.addWidget(_sub_label("Default — 默认尺寸"))
    default = StyledFilePicker(size="default", placeholder="默认尺寸")
    layout.addWidget(default)

    layout.addWidget(_sub_label("LG — 大尺寸"))
    lg = StyledFilePicker(size="lg", placeholder="大尺寸")
    layout.addWidget(lg)

    return container


def build_states_section() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    layout.addWidget(_sub_label("Normal — 正常"))
    normal = StyledFilePicker(placeholder="正常状态")
    layout.addWidget(normal)

    layout.addWidget(_sub_label("Error — 错误"))
    error = StyledFilePicker(placeholder="错误状态", error=True)
    layout.addWidget(error)

    # Interactive error toggle
    toggle_row = QHBoxLayout()
    toggle_row.setSpacing(8)
    interactive = StyledFilePicker(placeholder="点击右侧按钮切换错误状态")
    toggle_btn = QPushButton("Toggle Error")
    toggle_btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {tm.surface.name()};
            color: {tm.text.name()};
            border: 1px solid {tm.mid.name()};
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background-color: {tm.alpha_of(tm.mid, 50).name()};
        }}
    """)
    toggle_btn.clicked.connect(lambda: setattr(interactive, "error", not interactive.error))
    toggle_row.addWidget(interactive, stretch=1)
    toggle_row.addWidget(toggle_btn)
    layout.addLayout(toggle_row)

    layout.addWidget(_sub_label("Disabled — 禁用"))
    disabled = StyledFilePicker(placeholder="禁用状态")
    disabled.setEnabled(False)
    layout.addWidget(disabled)

    return container


def build_dropzone_section() -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    dz = StyledFileDropZone(
        text="拖拽文件到此处",
        hint="或点击选择文件",
    )
    dz.setFixedHeight(140)

    # Signal feedback
    feedback = QLabel("")
    feedback.setStyleSheet(f"font-size: 12px; color: {tm.accent.name()}; padding: 2px 0;")

    def on_drop(path: str):
        feedback.setText(f"已接收: {path}")

    dz.path_chosen.connect(on_drop)
    layout.addWidget(dz)
    layout.addWidget(feedback)

    return container


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(f"""
        QWidget {{
            background-color: {tm.surface.name()};
        }}
    """)

    window = QWidget()
    window.setWindowTitle("StyledFilePicker Demo")
    window.resize(640, 720)

    main_layout = QVBoxLayout(window)
    main_layout.setContentsMargins(32, 24, 32, 24)
    main_layout.setSpacing(16)

    # Section 1: Modes
    main_layout.addWidget(_section_label("1. Modes / 模式"))
    main_layout.addWidget(build_modes_section())
    main_layout.addWidget(_separator())

    # Section 2: Sizes
    main_layout.addWidget(_section_label("2. Sizes / 尺寸"))
    main_layout.addWidget(build_sizes_section())
    main_layout.addWidget(_separator())

    # Section 3: States
    main_layout.addWidget(_section_label("3. States / 状态"))
    main_layout.addWidget(build_states_section())
    main_layout.addWidget(_separator())

    # Section 4: Drop Zone
    main_layout.addWidget(_section_label("4. Drop Zone / 拖拽区"))
    main_layout.addWidget(build_dropzone_section())

    main_layout.addStretch()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
