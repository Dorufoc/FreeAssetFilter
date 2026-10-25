# -*- coding: utf-8 -*-
"""AI 聊天窗口 / 输入器 / 欢迎态 / 侧边栏的冒烟测试。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

# 组件模块内部使用短路径导入（from theme import tm），要求 ui 目录在 sys.path。
_UI_ROOT: str = str(Path(__file__).resolve().parents[4] / "freeassetfilter" / "ui")
if _UI_ROOT not in sys.path:
    sys.path.insert(0, _UI_ROOT)

from freeassetfilter.ui.components.styled_ai_chat import (  # noqa: E402
    StyledAIChatWindow,
)
from freeassetfilter.ui.components.styled_ai_chat_sidebar import (  # noqa: E402
    COMPACT_WIDTH,
    AIConversationItem,
    ConversationEntry,
    StyledAIChatSidebar,
)
from freeassetfilter.ui.components.styled_ai_composer import (  # noqa: E402
    StyledAIComposer,
)
from freeassetfilter.ui.components.styled_ai_welcome import (  # noqa: E402
    StyledAIWelcome,
)
from freeassetfilter.ui.components.styled_icon_button import (  # noqa: E402
    StyledIconButton,
)
from theme import tm  # noqa: E402

pytestmark = pytest.mark.unit


def _show_offscreen(widget: QWidget, width: int = 800, height: int = 600) -> QWidget:
    """以离屏方式显示控件并泵一次事件。

    Args:
        widget: 待显示控件。
        width: 宽度。
        height: 高度。

    Returns:
        同一控件。
    """
    widget.setAttribute(Qt.WA_DontShowOnScreen, True)
    widget.resize(width, height)
    widget.show()
    QApplication.processEvents()
    return widget


def test_icon_button_states_and_theme(qapp: Any) -> None:
    """图标按钮尺寸、选中态与主题切换。"""
    button = StyledIconButton("paperclip", size="lg", variant="accent", checkable=True)
    _show_offscreen(button, 40, 40)
    assert button.size().width() == 32
    button.setChecked(True)
    assert button.isChecked()
    tm.set_theme("light")
    QApplication.processEvents()
    tm.set_theme("dark")
    QApplication.processEvents()
    button.setEnabled(False)
    assert not button.isEnabled()


def test_composer_enter_shift_enter_and_auto_grow(qapp: Any) -> None:
    """输入器 Enter 发送、Shift+Enter 换行、最多 6 行。"""
    composer = StyledAIComposer()
    _show_offscreen(composer, 640, 220)
    sent: List[str] = []
    composer.send_requested.connect(sent.append)

    composer.set_text("第一行")
    QTest.keyClick(composer._editor, Qt.Key_Return)
    QApplication.processEvents()
    assert sent == ["第一行"]
    assert composer.text() == ""

    composer.set_text("第一行")
    QTest.keyClick(composer._editor, Qt.Key_Return, Qt.ShiftModifier)
    QApplication.processEvents()
    assert "第一行" in composer.text()
    assert sent == ["第一行"]

    composer.set_text("\n".join(str(i) for i in range(8)))
    QApplication.processEvents()
    one_line = composer._editor.fontMetrics().lineSpacing()
    assert composer._editor.height() <= one_line * 6 + 20


def test_welcome_suggestion_click(qapp: Any) -> None:
    """点击建议卡片发出建议文本。"""
    welcome = StyledAIWelcome()
    _show_offscreen(welcome, 720, 480)
    received: List[str] = []
    welcome.suggestion_selected.connect(received.append)
    cards = welcome.suggestions()
    assert cards
    cards[0].click()
    QApplication.processEvents()
    assert received == [cards[0].prompt()]


def test_sidebar_filter_and_collapse(qapp: Any) -> None:
    """侧边栏搜索过滤、选中与折叠宽度。"""
    sidebar = StyledAIChatSidebar()
    _show_offscreen(sidebar, 240, 620)
    sidebar.set_conversations(
        [
            ConversationEntry("a", "设计素材归档", "预览", "14:30"),
            ConversationEntry("b", "旅行照片整理", "预览", "13:10"),
        ]
    )
    QApplication.processEvents()
    assert sidebar.current_id() == "a"

    sidebar.filter("素材")
    QApplication.processEvents()
    visible_ids = [
        item.entry.id
        for item in sidebar.findChildren(AIConversationItem)
        if not item.isHidden()
    ]
    assert visible_ids == ["a"]

    sidebar.set_collapsed(True)
    QTest.qWait(300)
    assert sidebar.is_collapsed()
    assert sidebar.width() == COMPACT_WIDTH


def test_chat_window_embed_and_send(qapp: Any) -> None:
    """无标题栏嵌入模式、欢迎态切换与发送信号。"""
    window = StyledAIChatWindow(show_title_bar=False)
    _show_offscreen(window, 760, 640)
    assert window.title_bar is None
    assert window.is_welcome_visible()

    sent: List[str] = []
    window.send_requested.connect(sent.append)
    window.composer.set_text("你好")
    QTest.keyClick(window.composer._editor, Qt.Key_Return)
    QApplication.processEvents()
    assert sent == ["你好"]
    assert not window.is_welcome_visible()

    window.clear_conversation()
    assert window.is_welcome_visible()
