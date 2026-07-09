"""Standalone demo for the StyledInfoCard component."""

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

from components.styled_info_card import StyledInfoCard


def make_separator():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"QFrame {{ color: {tm.mid.name()}; }}")
    line.setFixedHeight(1)
    return line


def make_section_header(text):
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {tm.text.name()}; margin-top: 8px;")
    return label


def make_section_desc(text):
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 12px;")
    return label


def make_demo_container() -> QWidget:
    container = QWidget()
    container.setStyleSheet(f"background: {tm.surface.name()}; border-radius: 8px;")
    return container


class StyledInfoCardDemo(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StyledInfoCard Demo")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowTitleHint)
        self.resize(860, 720)

        self.setStyleSheet(
            f'QWidget {{ background-color: {tm.surface.name()}; color: {tm.text.name()}; font-family: "Microsoft YaHei", sans-serif; }}'
            f"QLabel {{ color: {tm.mid.name()}; font-size: 12px; }}"
        )

        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(32, 24, 32, 24)

        # ── Header ──
        header = QLabel("StyledInfoCard 信息卡片")
        header.setStyleSheet(f"font-size: 22px; font-weight: 600; color: {tm.text.name()}; margin-bottom: 4px;")
        main_layout.addWidget(header)
        main_layout.addWidget(make_section_desc("A styled info card with horizontal/vertical layout, hover overlay, and disabled state."))
        main_layout.addWidget(make_separator())

        # ── 1. Horizontal - 3 text lines ──
        main_layout.addWidget(make_section_header("水平布局 · 三行文字"))
        main_layout.addWidget(make_section_desc("Horizontal — icon + title + subtitle + description"))
        card1 = StyledInfoCard(
            layout_mode="horizontal",
            title="星标项目",
            subtitle="Starred Projects · 3 个",
            desc="您标记为收藏的常用项目将在此处显示，方便快速访问。",
            media_icon="★",
        )
        main_layout.addWidget(card1)

        # ── 2. Horizontal - 2 text lines ──
        main_layout.addWidget(make_section_header("水平布局 · 两行文字"))
        main_layout.addWidget(make_section_desc("Horizontal — icon + title + description (no subtitle)"))
        card2 = StyledInfoCard(
            layout_mode="horizontal",
            title="系统设置",
            desc="自定义应用的主题、通知偏好和语言设置选项。",
            media_icon="⚙",
        )
        card2.setFixedWidth(500)
        main_layout.addWidget(card2)

        # ── 3. Horizontal - 1 text line ──
        main_layout.addWidget(make_section_header("水平布局 · 一行文字"))
        main_layout.addWidget(make_section_desc("Horizontal — icon + title only"))
        card3 = StyledInfoCard(
            layout_mode="horizontal",
            title="收藏的页面",
            media_icon="♥",
        )
        card3.setFixedWidth(400)
        main_layout.addWidget(card3)

        # ── 4. Vertical - 3 text lines ──
        main_layout.addWidget(make_section_header("垂直布局 · 三行文字"))
        main_layout.addWidget(make_section_desc("Vertical — icon + title + subtitle + description"))
        card4 = StyledInfoCard(
            layout_mode="vertical",
            title="用户资料卡片",
            subtitle="Product Designer",
            desc="位于上海，拥有 6 年产品设计经验，专注于 B 端产品体验设计。",
            media_icon="👤",
        )
        card4.setFixedWidth(300)
        main_layout.addWidget(card4, alignment=Qt.AlignLeft)

        # ── 5. Vertical with overlay (2×2 grid) ──
        main_layout.addWidget(make_section_header("垂直布局 · 悬停操作 (2×2)"))
        main_layout.addWidget(make_section_desc("Vertical — hover to reveal 4 overlay buttons in a 2×2 grid"))
        card5 = StyledInfoCard(
            layout_mode="vertical",
            title="相册 · 旅行记忆",
            subtitle="2024 年夏季 · 42 张照片",
            desc="记录在云南大理和丽江的旅行点滴，包含风景和人文摄影作品。",
            media_icon="📷",
            overlay_enabled=True,
        )
        card5.add_action("查看", "👁")
        card5.add_action("编辑", "✎")
        card5.add_action("详情", "ℹ")
        card5.add_action("删除", "✕")
        card5.setFixedWidth(300)
        main_layout.addWidget(card5, alignment=Qt.AlignLeft)

        # ── 6. Horizontal with overlay (3 buttons) ──
        main_layout.addWidget(make_section_header("水平布局 · 悬停操作 (3 按钮)"))
        main_layout.addWidget(make_section_desc("Horizontal — hover to reveal 3 overlay buttons in a horizontal row"))
        card6 = StyledInfoCard(
            layout_mode="horizontal",
            title="消息中心",
            subtitle="3 条未读消息",
            desc="您有新的系统通知和团队 @ 提及等待查看。",
            media_icon="💬",
            overlay_enabled=True,
        )
        card6.add_action("回复", "↩")
        card6.add_action("收藏", "♥")
        card6.add_action("转发", "↗")
        main_layout.addWidget(card6)

        # ── 7. Disabled variants ──
        main_layout.addWidget(make_section_header("禁用状态"))
        main_layout.addWidget(make_section_desc("Disabled — reduced opacity, no hover effects"))

        disabled_row = QHBoxLayout()
        disabled_row.setSpacing(16)

        card7a = StyledInfoCard(
            layout_mode="horizontal",
            title="已锁定的项目",
            subtitle="需管理员权限",
            desc="该项目已被管理员锁定，暂时无法访问。",
            media_icon="🔒",
            disabled=True,
        )
        disabled_row.addWidget(card7a)

        card7b = StyledInfoCard(
            layout_mode="vertical",
            title="已禁用的账户",
            subtitle="请联系客服",
            desc="此账户已被禁用，点击了解更多详情。",
            media_icon="🚫",
            disabled=True,
        )
        card7b.setFixedWidth(300)
        disabled_row.addWidget(card7b)
        disabled_row.addStretch()

        main_layout.addLayout(disabled_row)

        main_layout.addStretch()

        scroll.setWidget(content)
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(scroll)

    def _on_action_clicked(self, action_name: str):
        """Handle action button clicks."""
        print(f"Action clicked: {action_name}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StyledInfoCardDemo()
    window.show()
    sys.exit(app.exec())
