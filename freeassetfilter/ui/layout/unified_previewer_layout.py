"""
统一预览器布局 — 两个可拖拽调整比例的内容区（默认 1:1）+ 底栏
"""

from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QSplitter
from PySide6.QtCore import Qt

from theme import tm
from components.styled_button import StyledButton


class UnifiedPreviewerLayout(QWidget):
    """统一预览器布局（右侧栏）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 可拖拽分割的两个内容区
        self._splitter = QSplitter(Qt.Vertical)
        self._splitter.setHandleWidth(10)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: transparent;
                height: 6px;
            }
        """)

        # 内容区 1（上方）
        self._content_top = QFrame()
        self._content_top.setObjectName("PreviewerTop")
        self._splitter.addWidget(self._content_top)

        # 内容区 2（下方）
        self._content_bottom = QFrame()
        self._content_bottom.setObjectName("PreviewerBottom")
        self._splitter.addWidget(self._content_bottom)

        # 默认 1:1 比例
        self._splitter.setSizes([1, 1])

        layout.addWidget(self._splitter, stretch=1)

        # 底栏（固定高度）
        self._bottom_bar = QFrame()
        self._bottom_bar.setObjectName("PreviewerBottomBar")
        self._bottom_bar.setFixedHeight(48)
        self._build_bottom_bar()
        layout.addWidget(self._bottom_bar)

        self.setLayout(layout)

        # 主题切换时刷新颜色
        tm.theme_changed.connect(self._on_theme_changed)

    def _build_bottom_bar(self) -> None:
        """构建底栏：share + 打开方式 + 定位目录 + close"""
        icons_dir = Path(__file__).resolve().parent.parent.parent / "icons"
        bottom_layout = QHBoxLayout(self._bottom_bar)
        bottom_layout.setContentsMargins(10, 6, 10, 6)
        bottom_layout.setSpacing(6)

        # 图标按钮 — share.svg
        share_icon = str(icons_dir / "share.svg")
        self._share_btn = StyledButton("", variant="ghost", size="sm", icon=share_icon)
        self._share_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._share_btn)

        # 次选按钮 — 使用系统默认方式打开
        self._open_default_btn = StyledButton(
            "使用系统默认方式打开", variant="secondary", size="sm"
        )
        bottom_layout.addWidget(self._open_default_btn)

        # 强调按钮 — 定位到所在目录
        self._locate_btn = StyledButton(
            "定位到所在目录", variant="primary", size="sm"
        )
        bottom_layout.addWidget(self._locate_btn)

        # 图标按钮 — close.svg
        close_icon = str(icons_dir / "close.svg")
        self._close_btn = StyledButton("", variant="ghost", size="sm", icon=close_icon)
        self._close_btn.setFixedSize(32, 32)
        bottom_layout.addWidget(self._close_btn)

    def set_section_styles(self, fill_color: str, border_color: str) -> None:
        """应用面板样式到内容区、底栏（主题切换时由 MainWindow 调用）"""
        section_style = f"""
            background-color: {fill_color};
            border: 1px solid {border_color};
            border-radius: 8px;
        """
        self._content_top.setStyleSheet(section_style)
        self._content_bottom.setStyleSheet(section_style)
        self._bottom_bar.setStyleSheet(section_style)

    def _on_theme_changed(self, theme: str) -> None:
        """主题切换时占位（样式由 MainWindow 统一刷新）"""
        pass
