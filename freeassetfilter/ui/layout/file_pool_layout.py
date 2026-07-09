"""
文件池布局 — 内容区（自适应拉伸）+ 底栏（固定高度）
"""

from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel

from theme import tm
from components.styled_button import StyledButton


class FilePoolLayout(QWidget):
    """文件池布局（中间栏）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 内容区（自适应拉伸）
        self._content_area = QFrame()
        self._content_area.setObjectName("FilePoolContent")
        layout.addWidget(self._content_area, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("FilePoolBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)

        # 主题切换时刷新标签文字颜色
        tm.theme_changed.connect(self._on_theme_changed)

    def _build_bottom_bar(self) -> None:
        """构建底栏：导入/导出数据 + 导出文件 + 删除"""
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(6)

        # 左侧文字标签（纵向排列）
        info_container = QWidget()
        info_container.setFixedHeight(32)
        info_container.setStyleSheet("background: transparent; border: none;")
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)

        self._count_label = QLabel("0个条目")
        self._count_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px; font-weight: 600;"
        )
        info_layout.addWidget(self._count_label)

        self._size_label = QLabel("0.00MB")
        self._size_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 10px;"
        )
        info_layout.addWidget(self._size_label)

        bottom_layout.addWidget(info_container)

        # 竖分割线
        self._separator = QFrame()
        self._separator.setFrameShape(QFrame.VLine)
        self._separator.setFrameShadow(QFrame.Sunken)
        self._update_separator_color()
        self._separator.setFixedWidth(1)
        self._separator.setFixedHeight(20)
        bottom_layout.addWidget(self._separator)

        # 将按钮区域推到右侧
        bottom_layout.addStretch(1)

        # 图标按钮 — trash.svg
        trash_icon = str(icons_dir / "trash.svg")
        self._trash_btn = StyledButton("", variant="ghost", size="sm", icon=trash_icon)
        self._trash_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._trash_btn)

        # 次要按钮 — 导入/导出数据
        self._import_export_btn = StyledButton(
            "导入/导出数据", variant="secondary", size="sm"
        )
        bottom_layout.addWidget(self._import_export_btn)

        # 强调按钮 — 导出文件
        self._export_btn = StyledButton(
            "导出文件", variant="primary", size="sm"
        )
        bottom_layout.addWidget(self._export_btn)

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式到内容区、底栏（主题切换时由 MainWindow 调用）"""
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        self._content_area.setStyleSheet(section_style)
        self._bottom_bar.setStyleSheet(section_style)

    def _update_separator_color(self) -> None:
        """刷新竖分割线颜色"""
        mid = tm.mid
        self._separator.setStyleSheet(
            f"background: transparent; border: none; border-left: 1px solid rgba({mid.red()},{mid.green()},{mid.blue()},0.25);"
        )

    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时刷新标签文字颜色"""
        self._update_separator_color()
        self._count_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.text.name()}; font-size: 12px; font-weight: 600;"
        )
        self._size_label.setStyleSheet(
            "background: transparent; border: none;"
            f"color: {tm.mid.name()}; font-size: 10px;"
        )
