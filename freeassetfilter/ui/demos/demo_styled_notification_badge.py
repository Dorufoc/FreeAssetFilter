"""NotificationBadge Demo — standalone demo showcasing all features.

Shows:
  - 3 notification items with different icon colors (success, warning, info)
  - Mixed unread / read items with pulse animation on unread dots
  - Empty state
  - Footer "查看全部" link
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QPushButton, QFrame,
)
from PySide6.QtCore import Qt

from theme import tm

from components.styled_notification_badge import (
    NotificationItem,
    NotificationBadgeList,
)


class NotificationBadgeDemo(QWidget):
    """Main demo window for NotificationBadge."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NotificationBadge Demo")
        self.resize(520, 600)

        self._setup_ui()
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
        """)

    # ── UI helpers ───────────────────────────────────────────────

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {tm.text.name()};"
            f" margin-top: 8px; margin-bottom: 4px; background: transparent; border: none;"
        )
        return label

    def _section_desc(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: 12px; color: {tm.alpha_of(tm.mid, 60).name()}; margin-bottom: 8px;"
            f" background: transparent; border: none;"
        )
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(
            f"background-color: {tm.alpha_of(tm.mid, 30).name()}; max-height: 1px; border: none;"
        )
        return line

    # ── Setup UI ─────────────────────────────────────────────────

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")

        content = QWidget()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(content)
        main_layout.setContentsMargins(32, 24, 32, 24)
        main_layout.setSpacing(16)

        # ── Section: NotificationBadgeList ──
        main_layout.addWidget(self._section_label("NotificationBadgeList"))
        main_layout.addWidget(
            self._section_desc("3 items, mixed read/unread, 4 colour variants")
        )

        self._badge_list = NotificationBadgeList()

        # Item 1: success — 系统更新
        item1 = NotificationItem(
            icon_name="download",
            title="系统更新已完成",
            description="v2.4.1 已成功安装，新增了多项功能优化。",
            time_str="2 分钟前",
            color_variant="success",
            unread=True,
            index=0,
        )

        # Item 2: warning — 存储警告
        item2 = NotificationItem(
            icon_name="warning",
            title="存储空间不足",
            description="可用空间仅剩 1.2 GB，建议清理缓存文件。",
            time_str="15 分钟前",
            color_variant="warning",
            unread=True,
            index=1,
        )

        # Item 3: info — 好友请求
        item3 = NotificationItem(
            icon_name="user",
            title="新的好友请求",
            description="用户「小明」请求添加你为好友。",
            time_str="1 小时前",
            color_variant="info",
            unread=False,
            index=2,
        )

        self._badge_list.add_item(item1)
        self._badge_list.add_item(item2)
        self._badge_list.add_item(item3)

        # Container to centre the list in the demo
        list_container = QWidget()
        list_container.setStyleSheet("background: transparent;")
        list_layout = QHBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self._badge_list)
        list_layout.addStretch()
        main_layout.addWidget(list_container)

        main_layout.addWidget(self._separator())

        # ── Interaction controls ──
        main_layout.addWidget(self._section_label("Interactions"))
        main_layout.addWidget(
            self._section_desc("Click items to trigger item_clicked signal")
        )

        self._status_label = QLabel("Click a notification item above.")
        self._status_label.setStyleSheet(
            f"font-size: 12px; color: {tm.mid.name()}; padding: 8px 0;"
            f" background: transparent; border: none;"
        )
        main_layout.addWidget(self._status_label)

        # Buttons row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        add_btn = QPushButton("+ Add Item")
        add_btn.setStyleSheet(self._btn_style())
        add_btn.clicked.connect(self._on_add_item)
        btn_layout.addWidget(add_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.setStyleSheet(self._btn_style())
        clear_btn.clicked.connect(self._on_clear_items)
        btn_layout.addWidget(clear_btn)

        toggle_btn = QPushButton("Toggle Unread")
        toggle_btn.setStyleSheet(self._btn_style())
        toggle_btn.clicked.connect(self._on_toggle_unread)
        btn_layout.addWidget(toggle_btn)

        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        main_layout.addStretch()

        # Outer layout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Connect signals
        self._badge_list.item_clicked.connect(self._on_item_clicked)
        self._badge_list.view_all_clicked.connect(self._on_view_all)

    # ── Signal handlers ──────────────────────────────────────────

    def _on_item_clicked(self, index: int):
        self._status_label.setText(f"Item #{index} clicked!")

    def _on_view_all(self):
        self._status_label.setText("「查看全部」clicked!")

    def _on_add_item(self):
        count = self._badge_list.item_count()
        variants = ["success", "warning", "error", "info"]
        icons = ["bell", "clock", "star", "heart"]
        item = NotificationItem(
            icon_name=icons[count % len(icons)],
            title=f"通知 #{count + 1}",
            description=f"这是第 {count + 1} 条通知的详细描述内容。",
            time_str="刚刚",
            color_variant=variants[count % len(variants)],
            unread=True,
            index=count,
        )
        self._badge_list.add_item(item)

    def _on_clear_items(self):
        self._badge_list.clear_items()
        self._status_label.setText("All items cleared — empty state shown.")

    def _on_toggle_unread(self):
        """Toggle the first item's unread state for demo purposes."""
        count = self._badge_list.item_count()
        if count > 0:
            layout = self._badge_list._items_layout
            for i in range(layout.count()):
                item_w = layout.itemAt(i)
                if item_w and item_w.widget():
                    widget = item_w.widget()
                    if isinstance(widget, NotificationItem):
                        widget.is_unread = not widget.is_unread
                        self._status_label.setText(
                            f"Toggled unread for item #{widget.item_index}"
                        )
                        return

    def _btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {tm.surface.name()};
                color: {tm.text.name()};
                border: 1px solid {tm.alpha_of(tm.mid, 40).name()};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }}
            QPushButton:hover {{
                background-color: {tm.alpha_of(tm.mid, 40).name()};
                border-color: {tm.alpha_of(tm.mid, 40).name()};
            }}
            QPushButton:pressed {{
                background-color: {tm.surface.name()};
            }}
        """


def main():
    app = QApplication(sys.argv)
    demo = NotificationBadgeDemo()
    demo.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
