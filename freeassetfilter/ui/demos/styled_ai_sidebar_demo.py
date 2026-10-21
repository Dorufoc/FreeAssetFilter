# -*- coding: utf-8 -*-
"""独立会话侧边栏 Demo。

运行（仓库根目录）：

    python -m freeassetfilter.ui.demos.styled_ai_sidebar_demo

窗口只包含 :class:`StyledAIChatSidebar`，用于独立验证会话导航布局；不包含
聊天区。侧边栏后续可与 :class:`StyledAIChatWindow` 并排组合使用。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QPaintEvent, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from freeassetfilter.ui.components.styled_ai_chat_sidebar import (
    ConversationEntry,
    StyledAIChatSidebar,
)
from freeassetfilter.ui.components.styled_chat_bubble import window_fill_color
from freeassetfilter.ui.components.styled_dialog import (
    create_basic_dialog,
    create_input_dialog,
)

#: 窗口尺寸。
WINDOW_SIZE = (260, 780)


def default_entries() -> List[ConversationEntry]:
    """返回示例会话数据。

    Returns:
        会话列表。
    """
    return [
        ConversationEntry(
            "pinned-1",
            "设计素材归档",
            "图片和文件都收到了",
            "14:30",
            "置顶",
            pinned=True,
        ),
        ConversationEntry("today-1", "旅行照片整理", "按城市和日期分类", "13:12"),
        ConversationEntry("today-2", "PPT 大纲优化", "先讲结论再展开", "10:48"),
        ConversationEntry("yesterday-1", "接口文档摘要", "返回字段说明", "昨天"),
        ConversationEntry("older-1", "项目周报草稿", "本周完成事项", "更早", "更早"),
    ]


class SidebarDemoWindow(QWidget):
    """只承载侧边栏的独立窗口。

    Args:
        parent: 父控件。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("会话导航侧边栏 Demo")
        self.resize(*WINDOW_SIZE)
        self.setMinimumSize(240, 520)

        self._sidebar = StyledAIChatSidebar(self)
        self._sidebar.set_conversations(default_entries())
        self._sidebar.conversation_selected.connect(self._on_selected)
        self._sidebar.new_chat_requested.connect(self._on_new_chat)
        self._sidebar.rename_requested.connect(self._on_rename)
        self._sidebar.delete_requested.connect(self._on_delete)
        self._sidebar.search_changed.connect(self._on_search)
        self._sidebar.collapsed_changed.connect(self._on_collapsed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar)
        layout.addStretch(1)

    def paintEvent(self, event: QPaintEvent) -> None:
        """填充窗口底色。

        Args:
            event: Qt 绘制事件。
        """
        painter = QPainter(self)
        painter.fillRect(self.rect(), window_fill_color())
        painter.end()

    def _set_status(self, text: str) -> None:
        """把交互结果写入窗口标题。

        Args:
            text: 状态文案。
        """
        self.setWindowTitle(f"会话导航侧边栏 Demo — {text}")

    def _on_selected(self, conversation_id: str) -> None:
        self._set_status(f"选中 {conversation_id}")

    def _on_new_chat(self) -> None:
        index = len(self._sidebar.conversations()) + 1
        self._sidebar.add_conversation(
            ConversationEntry(f"new-{index}", f"新对话 {index}", "", "刚刚", "今天")
        )
        self._set_status("已新建会话")

    def _on_rename(self, conversation_id: str) -> None:
        current = next(
            (
                entry
                for entry in self._sidebar.conversations()
                if entry.id == conversation_id
            ),
            None,
        )
        if current is None:
            return
        dialog = create_input_dialog(
            title="重命名会话",
            message="请输入新的会话名称：",
            placeholder=current.title,
        )
        dialog._input_field.setText(current.title)

        def apply(result: int) -> None:
            if result != 1:
                return
            title = dialog._input_field.text().strip()
            if not title:
                return
            current.title = title
            self._sidebar.update_conversation(current)
            self._set_status(f"已重命名为 {title}")

        dialog.finished.connect(apply)

    def _on_delete(self, conversation_id: str) -> None:
        dialog = create_basic_dialog(
            title="删除会话",
            message="确定要删除这个会话吗？此操作无法撤销。",
            confirm_text="删除",
        )

        def apply(result: int) -> None:
            if result != 1:
                return
            self._sidebar.remove_conversation(conversation_id)
            self._set_status("已删除会话")

        dialog.finished.connect(apply)

    def _on_search(self, text: str) -> None:
        self._set_status(f"搜索“{text}”")

    def _on_collapsed(self, collapsed: bool) -> None:
        self._set_status("已折叠" if collapsed else "已展开")


def main() -> int:
    """Demo 独立入口。

    Returns:
        应用退出码。
    """
    app = QApplication(sys.argv)
    app.setApplicationName("FreeAsset AI Sidebar Demo")
    window = SidebarDemoWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
