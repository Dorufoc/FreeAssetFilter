"""Standalone demo for the StyledDrawer component.

Run with: .venv\Scripts\python.exe qt6-components\demos\demo_styled_drawer.py
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
from PySide6.QtCore import Qt, QTimer

from components.styled_button import StyledButton
from components.styled_drawer import StyledDrawer


# ── Helpers ──────────────────────────────────────────────────────────

def _make_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"QFrame {{ color: {tm.alpha_of(tm.mid, 40).name()}; }}")
    line.setFixedHeight(1)
    return line


def _make_section_header(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"font-size: 16px; font-weight: bold; color: {tm.text.name()}; margin-top: 8px;"
    )
    return label


def _make_dummy_content(line_count: int = 8) -> QWidget:
    """Produce a QWidget with placeholder text for drawer body."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    for i in range(line_count):
        label = QLabel(
            f"这是抽屉中的第 {i + 1} 行内容。抽屉组件支持滚动，"
            "当内容超出可见区域时会自动显示滚动条。"
        )
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: 13px; color: {tm.mid.name()}; background: transparent;")
        layout.addWidget(label)

    layout.addStretch()
    return w


# ── Demo Window ──────────────────────────────────────────────────────

class StyledDrawerDemo(QWidget):
    """Demo window showcasing all Drawer orientations and size variants."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledDrawer Demo")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.resize(900, 720)

        self.setStyleSheet(
            f"QWidget {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; "
            f"font-family: 'Microsoft YaHei', sans-serif; }}"
            f"QLabel {{ color: {tm.mid.name()}; font-size: 12px; }}"
        )

        self._drawers: list[StyledDrawer] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # Title
        title = QLabel("Drawer 抽屉组件")
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {tm.text.name()};")
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

        # ── Row 1: Orientation variants ─────────────────────────
        layout.addWidget(_make_section_header("方向变体"))
        layout.addWidget(_make_separator())
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        for label, orient in [
            ("右侧抽屉 (400px)", "right"),
            ("左侧抽屉 (400px)", "left"),
            ("顶部抽屉 (300px)", "top"),
        ]:
            btn = StyledButton(label, variant="secondary")
            btn.clicked.connect(lambda _, o=orient: self._open_drawer(o))
            row1.addWidget(btn)
        row1.addStretch()
        layout.addLayout(row1)

        # ── Row 2: Size variants ────────────────────────────────
        layout.addWidget(_make_section_header("尺寸变体 (右侧)"))
        layout.addWidget(_make_separator())
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        for label, sz in [
            ("小尺寸 (sm, 280px)", "sm"),
            ("默认尺寸 (default, 400px)", "default"),
            ("大尺寸 (lg, 560px)", "lg"),
        ]:
            btn = StyledButton(label, variant="primary")
            btn.clicked.connect(lambda _, s=sz: self._open_drawer("right", s))
            row2.addWidget(btn)
        row2.addStretch()
        layout.addLayout(row2)

        # ── Row 3: Left + Top with sizes ────────────────────────
        layout.addWidget(_make_section_header("更多变体"))
        layout.addWidget(_make_separator())
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        for label, orient, sz in [
            ("左侧 小尺寸 (sm)", "left", "sm"),
            ("左侧 大尺寸 (lg)", "left", "lg"),
            ("顶部 小尺寸 (sm)", "top", "sm"),
            ("顶部 大尺寸 (lg)", "top", "lg"),
        ]:
            btn = StyledButton(label, variant="ghost")
            btn.clicked.connect(lambda _, o=orient, s=sz: self._open_drawer(o, s))
            row3.addWidget(btn)
        row3.addStretch()
        layout.addLayout(row3)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Footer hint
        hint = QLabel(
            "点击按钮打开抽屉。点击遮罩层、关闭按钮或按 Escape 键关闭。"
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()};")
        outer.addWidget(hint)

    def _open_drawer(
        self, orientation: str = "right", size: str = "default"
    ) -> None:
        """Create, populate, and open a drawer with the given params."""
        content = _make_dummy_content(8)

        drawer = StyledDrawer(
            orientation=orientation,
            size=size,
            title=f"{orientation.title()} Drawer ({size})",
            body_widget=content,
            parent=self,  # constrain within the demo window
        )

        # Add footer buttons
        close_btn = StyledButton("关闭", variant="ghost")
        close_btn.clicked.connect(drawer.close_drawer)
        drawer.footer_layout.addWidget(close_btn)

        action_btn = StyledButton("确定", variant="primary")
        action_btn.clicked.connect(
            lambda: print(f"[Drawer] '{orientation}' confirmed")
        )
        drawer.footer_layout.addWidget(action_btn)

        # Connect signals
        drawer.opened.connect(lambda: print(f"[Drawer] '{orientation}' opened"))
        drawer.closed.connect(lambda: print(f"[Drawer] '{orientation}' closed"))

        # Clean up after close (delete on close)
        drawer.closed.connect(drawer.deleteLater)

        self._drawers.append(drawer)
        drawer.open_drawer()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StyledDrawerDemo()
    window.show()
    sys.exit(app.exec())
