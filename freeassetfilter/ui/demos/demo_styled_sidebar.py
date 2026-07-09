"""Standalone demo for the StyledSidebar component."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
)
from PySide6.QtCore import Qt

from theme import tm
from components.styled_sidebar import StyledSidebar


class StyledSidebarDemo(QMainWindow):
    """Main demo window for StyledSidebar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledSidebar Demo")
        self.resize(800, 550)
        self.setMinimumSize(600, 400)

        self._apply_theme()
        self._setup_ui()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {tm.surface.name()};
            }}
            QWidget {{
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
        """)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- Left: StyledSidebar ----
        self._sidebar = StyledSidebar(width=240, title="D-Fronted")
        self._sidebar.add_item("账号与存储", icon_svg="user")
        self._sidebar.add_item("通用", icon_svg="gear")
        self._sidebar.add_item("快捷键", icon_svg="keyboard")
        self._sidebar.add_item("通知", icon_svg="bell", badge="3")
        self._sidebar.add_item("插件", icon_svg="plugins")
        self._sidebar.add_item("关于", icon_svg="info")
        self._sidebar.item_selected.connect(self._on_item_selected)
        main_layout.addWidget(self._sidebar)

        # ---- Right: Content panel ----
        panel = QWidget()
        panel.setStyleSheet(f"background-color: {tm.surface.name()};")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # Header bar
        header = QFrame()
        header.setFixedHeight(62)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {tm.surface.name()};
                border-bottom: 1px solid {tm.alpha_of(tm.mid, 30).name()};
            }}
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 18, 16, 16)
        header_layout.setSpacing(12)

        self._content_title = QLabel("账号与存储")
        self._content_title.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {tm.text.name()};")
        header_layout.addWidget(self._content_title, stretch=1)

        self._compact_btn = QPushButton("紧凑模式")
        self._compact_btn.setCheckable(True)
        self._compact_btn.setFixedSize(90, 28)
        self._compact_btn.setCursor(Qt.PointingHandCursor)
        self._compact_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {tm.mid.name()};
                border: 1px solid {tm.mid.name()};
                border-radius: 6px;
                font-size: 12px;
                font-weight: 500;
                color: {tm.mid.name()};
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                color: {tm.text.name()};
            }}
            QPushButton:checked {{
                background-color: {tm.accent.name()};
                border-color: {tm.accent.name()};
                color: #fff;
            }}
        """)
        self._compact_btn.clicked.connect(self._on_toggle_compact)
        header_layout.addWidget(self._compact_btn)

        panel_layout.addWidget(header)

        # Content area
        self._content_area = QWidget()
        self._content_area.setStyleSheet(f"background-color: {tm.surface.name()};")
        content_layout = QVBoxLayout(self._content_area)
        content_layout.setContentsMargins(32, 32, 32, 32)
        content_layout.setSpacing(16)

        self._selection_label = QLabel("当前未选择任何项目")
        self._selection_label.setStyleSheet(
            f"font-size: 14px; color: {tm.mid.name()};")
        self._selection_label.setAlignment(Qt.AlignCenter)
        content_layout.addStretch()
        content_layout.addWidget(self._selection_label)
        content_layout.addStretch()

        panel_layout.addWidget(self._content_area, stretch=1)
        main_layout.addWidget(panel, stretch=1)

    def _on_item_selected(self, index: int, label: str):
        self._content_title.setText(label)
        self._selection_label.setText(f'当前选择："{label}" (索引 {index})')

    def _on_toggle_compact(self, checked: bool):
        if checked:
            self._sidebar.set_compact(True)
            self._compact_btn.setText("标准模式")
        else:
            self._sidebar.set_compact(False)
            self._compact_btn.setText("紧凑模式")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("StyledSidebar Demo")

    window = StyledSidebarDemo()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
