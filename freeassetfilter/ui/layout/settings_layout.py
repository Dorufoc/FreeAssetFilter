"""
设置布局 — 设置窗口的内容区域（使用 StyledSidebar）
"""

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QFrame
from PySide6.QtCore import Qt

from theme import tm
from components.styled_sidebar import StyledSidebar


class SettingsLayout(QWidget):
    """设置布局"""

    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 侧边栏（使用 StyledSidebar 组件，透明背景以显示 Mica） ──
        self._sidebar = StyledSidebar(
            title="",
            width=220,
            compact=False,
            transparent=True,  # 透明背景以显示 Mica 效果
            parent=self,
        )
        self._sidebar.add_item("通用", icon_svg="gear")
        self._sidebar.item_selected.connect(self._on_item_selected)
        main_layout.addWidget(self._sidebar)

        # ── 内容区（右侧） ──
        self._content_area = QFrame()
        self._content_area.setObjectName("SettingsContentArea")
        content_layout = QVBoxLayout(self._content_area)
        content_layout.setContentsMargins(0, 0, 24, 24)
        content_layout.setSpacing(0)

        # 圆角卡片（参考 file_selector_layout 面板样式）
        self._card = QFrame()
        self._card.setObjectName("SettingsCard")
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(12)
        card_layout.addStretch()

        content_layout.addWidget(self._card)

        # 应用初始样式
        self._refresh_styles()

        main_layout.addWidget(self._content_area, stretch=1)

        self.setLayout(main_layout)

        # 主题切换时刷新内容区背景
        tm.theme_changed.connect(self._on_theme_changed)

    def _refresh_styles(self) -> None:
        """刷新卡片样式（参考 file_selector_layout 面板样式）"""
        mid = tm.mid
        txt = tm.text
        fill_color = f"rgba({txt.red()},{txt.green()},{txt.blue()},{5 / 100})"
        border_color = f"rgba({mid.red()},{mid.green()},{mid.blue()},{50 / 100})"

        self._card.setStyleSheet(f"""
            #SettingsCard {{
                background-color: {fill_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)
        self._content_area.setStyleSheet("background-color: transparent; border: none;")

    def _on_item_selected(self, index: int, label: str) -> None:
        """侧边栏导航项选中回调"""
        pass

    def _on_theme_changed(self, _theme: str) -> None:
        """主题切换时刷新样式"""
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """公共方法：强制刷新当前主题下的所有样式"""
        self._refresh_styles()

        # 刷新侧边栏所有导航项的图标和标签颜色
        active_idx = self._sidebar._active_index
        for i, item in enumerate(self._sidebar._items):
            item._set_active(i == active_idx)

        # 刷新折叠按钮的顶部分隔线颜色
        if hasattr(self._sidebar, '_toggle_btn'):
            self._sidebar._toggle_btn.setStyleSheet(
                f"SidebarItem {{ background-color: transparent; "
                f"border-top: 1px solid {tm.alpha_of(tm.surface, 90).name()}; }}"
            )
