"""Standalone demo for the StyledDialog component.

Run with: .venv\Scripts\python.exe qt6-components\demos\demo_styled_dialog.py
"""

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
    QScrollArea,
)
from PySide6.QtCore import Qt

from components.styled_button import StyledButton
from components.styled_dialog import (
    create_basic_dialog,
    create_success_dialog,
    create_danger_dialog,
    create_input_dialog,
    create_small_dialog,
    create_large_dialog,
    create_progress_linear_dialog,
    create_progress_circular_dialog,
    create_progress_download_dialog,
    create_center_button_dialog,
    create_left_button_dialog,
    create_stacked_button_dialog,
    create_three_button_dialog,
    create_help_link_dialog,
    create_no_border_dialog,
    create_no_footer_dialog,
)


def _make_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"QFrame {{ color: {tm.mid.name()}; }}")
    line.setFixedHeight(1)
    return line


def _make_section_header(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"font-size: 16px; font-weight: bold; color: {tm.text.name()}; margin-top: 8px;"
    )
    return label


def _open_dialog(parent: QWidget, dialog_factory):
    """Create and show a standalone dialog window."""
    dialog_factory()


class StyledDialogDemo(QWidget):
    """Demo window showcasing all Dialog variants."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledDialog Demo")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.resize(900, 720)

        self.setStyleSheet(
            f"QWidget {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; "
            f"font-family: 'Microsoft YaHei', sans-serif; }}"
            f"QLabel {{ color: {tm.mid.name()}; font-size: 12px; }}"
        )

        self._setup_ui()

    # ── UI construction ────────────────────────────────────────────

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # Title
        title = QLabel("Dialog 对话框组件")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: 600; color: {tm.text.name()};"
        )
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.viewport().setStyleSheet("background: transparent;")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ── Row 1: Basic variants ──────────────────────────────────
        layout.addWidget(_make_section_header("基础对话框"))
        layout.addWidget(_make_separator())
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        for label, factory in [
            ("基础确认", lambda: create_basic_dialog()),
            ("成功", lambda: create_success_dialog()),
            ("危险确认", lambda: create_danger_dialog()),
            ("输入对话框", lambda: create_input_dialog()),
            ("小尺寸", lambda: create_small_dialog()),
            ("大尺寸", lambda: create_large_dialog()),
        ]:
            btn = StyledButton(label, variant="secondary")
            btn.clicked.connect(lambda _, f=factory: _open_dialog(self, f))
            row1.addWidget(btn)
        row1.addStretch()
        layout.addLayout(row1)

        # ── Row 2: Progress variants ───────────────────────────────
        layout.addWidget(_make_section_header("进度对话框"))
        layout.addWidget(_make_separator())
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        for label, factory in [
            ("条形进度", lambda: create_progress_linear_dialog()),
            ("圆形进度", lambda: create_progress_circular_dialog()),
            ("下载进度", lambda: create_progress_download_dialog()),
        ]:
            btn = StyledButton(label, variant="primary")
            btn.clicked.connect(lambda _, f=factory: _open_dialog(self, f))
            row2.addWidget(btn)
        row2.addStretch()
        layout.addLayout(row2)

        # ── Row 3: Button layout variants ──────────────────────────
        layout.addWidget(_make_section_header("按钮布局"))
        layout.addWidget(_make_separator())
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        for label, factory in [
            ("居中按钮", lambda: create_center_button_dialog()),
            ("左对齐按钮", lambda: create_left_button_dialog()),
            ("堆叠按钮", lambda: create_stacked_button_dialog()),
            ("三按钮", lambda: create_three_button_dialog()),
            ("带帮助链接", lambda: create_help_link_dialog()),
            ("无边框", lambda: create_no_border_dialog()),
            ("无底部栏", lambda: create_no_footer_dialog()),
        ]:
            btn = StyledButton(label, variant="ghost")
            btn.clicked.connect(lambda _, f=factory: _open_dialog(self, f))
            row3.addWidget(btn)
        row3.addStretch()
        layout.addLayout(row3)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Footer hint
        hint = QLabel("点击按钮打开对应的对话框，点击遮罩层或关闭按钮关闭")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        outer.addWidget(hint)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StyledDialogDemo()
    window.show()
    sys.exit(app.exec())
