"""Styled, bubble-based AI conversation controls.

The module keeps all chat-specific presentation in reusable controls so demo
windows only wire signals to the AI worker.  Colors and typography come from
ThemeManager, matching the rest of the component library.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QSize, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.components.styled_scroll_area import StyledScrollArea
from freeassetfilter.ui.components.styled_textarea import StyledTextarea
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from theme import tm


class StyledAIChatBubble(QFrame):
    """A single adaptive conversation bubble.

    ``role`` is one of ``user``, ``assistant``, ``reasoning``, ``system`` or
    ``tool``.  The bubble deliberately uses a constrained maximum width and
    word wrapping, which keeps long streamed answers readable on narrow panes.
    """

    copied = Signal(str)

    ROLE_LABELS = {
        "user": "你", "assistant": "AI", "reasoning": "思考中",
        "system": "系统", "tool": "工具",
    }

    def __init__(self, role: str, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role if role in self.ROLE_LABELS else "assistant"
        self._text = text
        self._streaming = False
        self._body = QLabel(self)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._body.setText(text)
        self._body.setFont(QFont("Microsoft YaHei UI", 13))
        self._body.setStyleSheet(f"color: {tm.text.name()}; background: transparent;")
        self._copy = QPushButton("复制", self)
        self._copy.setCursor(Qt.PointingHandCursor)
        self._copy.setVisible(False)
        self._copy.clicked.connect(lambda: self.copied.emit(self._text))
        self._role = QLabel(self.ROLE_LABELS[self.role], self)
        self._role.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.DemiBold))
        self._role.setStyleSheet(f"color: {self._role_color().name()}; background: transparent;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 10, 14, 10)
        self._layout.setSpacing(5)
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._role); top.addStretch(1); top.addWidget(self._copy)
        self._layout.addLayout(top); self._layout.addWidget(self._body)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setMaximumWidth(680)
        self.setAttribute(Qt.WA_Hover, True)
        self._apply_style()

    def _role_color(self) -> QColor:
        if self.role == "user": return tm.accent
        if self.role == "reasoning": return tm.warning
        if self.role == "tool": return tm.info
        if self.role == "system": return tm.mid
        return tm.accent

    def _background(self) -> QColor:
        if self.role == "user": return tm.alpha_of(tm.accent, 22)
        if self.role == "reasoning": return tm.alpha_of(tm.warning, 12)
        if self.role == "tool": return tm.alpha_of(tm.info, 12)
        return tm.alpha_of(tm.surface, 72)

    def _apply_style(self) -> None:
        border = tm.alpha_of(self._role_color(), 42).name()
        self.setStyleSheet(
            f"QFrame {{ background-color: {self._background().name()}; "
            f"border: 1px solid {border}; border-radius: 10px; }}"
        )

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        self._body.setText(text + ("▌" if self._streaming else ""))
        self._body.adjustSize(); self.adjustSize()

    def append_text(self, text: str) -> None:
        self.set_text(self._text + text)

    def set_streaming(self, streaming: bool) -> None:
        self._streaming = bool(streaming)
        self.set_text(self._text)

    def setMaximumWidth(self, width: int) -> None:  # noqa: N802 - Qt API
        super().setMaximumWidth(max(240, int(width)))
        self._body.setMaximumWidth(max(180, int(width) - 32))

    def enterEvent(self, event: object) -> None:
        self._copy.setVisible(bool(self._text))
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._copy.setVisible(False)
        super().leaveEvent(event)  # type: ignore[arg-type]

    def resizeEvent(self, event: object) -> None:
        self._body.setMaximumWidth(max(180, self.width() - 32))
        super().resizeEvent(event)  # type: ignore[arg-type]


class StyledAIMessageList(QScrollArea):
    """Scrollable bubble transcript with mobile-friendly adaptive widths."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True); self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("StyledAIMessageList")
        self._host = QWidget(); self._column = QVBoxLayout(self._host)
        self._column.setContentsMargins(8, 12, 8, 12); self._column.setSpacing(10)
        self._column.addStretch(1); self.setWidget(self._host)
        StyledScrollArea.apply_to(self)
        tm.theme_changed.connect(lambda _theme: self._refresh_bubbles())

    def _refresh_bubbles(self) -> None:
        for bubble in self._host.findChildren(StyledAIChatBubble): bubble._apply_style()

    def add_message(self, role: str, text: str) -> StyledAIChatBubble:
        bubble = StyledAIChatBubble(role, text, self._host)
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0)
        if role == "user": row.addStretch(1); row.addWidget(bubble)
        else: row.addWidget(bubble); row.addStretch(1)
        self._column.insertLayout(self._column.count() - 1, row)
        self._resize_bubbles(); self.scroll_to_bottom()
        return bubble

    def add_widget(self, widget: QWidget) -> None:
        row = QHBoxLayout(); row.setContentsMargins(0, 0, 0, 0); row.addWidget(widget); row.addStretch(1)
        self._column.insertLayout(self._column.count() - 1, row); self.scroll_to_bottom()

    def _resize_bubbles(self) -> None:
        width = max(300, self.viewport().width())
        for bubble in self._host.findChildren(StyledAIChatBubble):
            bubble.setMaximumWidth(min(680, max(240, int(width * 0.84))))

    def resizeEvent(self, event: object) -> None:
        self._resize_bubbles(); super().resizeEvent(event)  # type: ignore[arg-type]

    def scroll_to_bottom(self) -> None:
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def append_to_last(self, text: str) -> None:
        bubbles = self._host.findChildren(StyledAIChatBubble)
        if bubbles: bubbles[-1].append_text(text); self.scroll_to_bottom()


class StyledAIToolApproval(QWidget):
    approved = Signal(str)
    rejected = Signal(str)

    def __init__(self, call_id: str, name: str, arguments: str, parent: QWidget | None = None) -> None:
        super().__init__(parent); self.call_id = call_id
        layout = QVBoxLayout(self); layout.setContentsMargins(14, 10, 14, 10); layout.setSpacing(8)
        title = QLabel(f"工具请求 · {name}"); title.setStyleSheet(f"color: {tm.info.name()}; font-weight: 600;")
        details = QLabel(arguments); details.setWordWrap(True); details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        actions = QHBoxLayout(); approve = StyledButton("批准", variant="primary", size="sm"); reject = StyledButton("拒绝", variant="danger", size="sm")
        approve.clicked.connect(lambda: self.approved.emit(self.call_id)); reject.clicked.connect(lambda: self.rejected.emit(self.call_id))
        actions.addStretch(1); actions.addWidget(reject); actions.addWidget(approve)
        layout.addWidget(title); layout.addWidget(details); layout.addLayout(actions)
        self.setStyleSheet(f"background: {tm.alpha_of(tm.info, 10).name()}; border: 1px solid {tm.alpha_of(tm.info, 45).name()}; border-radius: 10px;")


class StyledAIChatPanel(QWidget):
    send_requested = Signal(str)
    cancel_requested = Signal()
    tool_approval = Signal(str, bool)

    def __init__(self, title: str = "AI 对话", parent: QWidget | None = None) -> None:
        super().__init__(parent); self._assistant_bubble: StyledAIChatBubble | None = None
        root = QVBoxLayout(self); root.setContentsMargins(14, 14, 14, 14); root.setSpacing(10)
        header = QHBoxLayout(); heading = QLabel(title); heading.setFont(QFont("Microsoft YaHei UI", 16, QFont.Weight.DemiBold)); heading.setStyleSheet(f"color: {tm.text.name()};")
        self.status = QLabel("就绪"); self.status.setStyleSheet(f"color: {tm.mid.name()}; font-size: 11px;")
        header.addWidget(heading); header.addStretch(1); header.addWidget(self.status); root.addLayout(header)
        self.messages = StyledAIMessageList(self); root.addWidget(self.messages, 1)
        self.composer = StyledTextarea(placeholder="输入问题或补充信息…", size="default", parent=self); root.addWidget(self.composer)
        actions = QHBoxLayout(); self.send_button = StyledButton("发送", variant="primary"); self.cancel_button = StyledButton("取消", variant="secondary"); self.cancel_button.setEnabled(False)
        self.send_button.clicked.connect(self._send); self.cancel_button.clicked.connect(self.cancel_requested.emit)
        actions.addStretch(1); actions.addWidget(self.cancel_button); actions.addWidget(self.send_button); root.addLayout(actions)
        tm.theme_changed.connect(lambda _theme: self._refresh_theme())

    def _refresh_theme(self) -> None:
        self.status.setStyleSheet(f"color: {tm.mid.name()}; font-size: 11px;")

    def _send(self) -> None:
        text = self.composer.text.strip()
        if not text: return
        self.messages.add_message("user", text); self.composer.text = ""
        self._assistant_bubble = None
        self.set_busy(True); self.send_requested.emit(text)

    def append_reasoning(self, text: str) -> None:
        bubbles = self.messages._host.findChildren(StyledAIChatBubble)
        bubble = bubbles[-1] if bubbles and bubbles[-1].role == "reasoning" else self.messages.add_message("reasoning", "")
        bubble.append_text(text); self.messages.scroll_to_bottom()

    def append_text(self, text: str) -> None:
        if self._assistant_bubble is None:
            self._assistant_bubble = self.messages.add_message("assistant", "")
            self._assistant_bubble.set_streaming(True)
        self._assistant_bubble.append_text(text); self.messages.scroll_to_bottom()

    def add_tool_approval(self, call_id: str, name: str, arguments: str) -> StyledAIToolApproval:
        widget = StyledAIToolApproval(call_id, name, arguments, self)
        widget.approved.connect(lambda value: self.tool_approval.emit(value, True)); widget.rejected.connect(lambda value: self.tool_approval.emit(value, False))
        self.messages.add_widget(widget); return widget

    def set_busy(self, busy: bool, status: str = "处理中…") -> None:
        self.send_button.setEnabled(not busy); self.cancel_button.setEnabled(busy); self.status.setText(status if busy else "就绪")
        if not busy and self._assistant_bubble is not None: self._assistant_bubble.set_streaming(False)

    def show_error(self, message: str) -> None:
        self.status.setText(message); self.set_busy(False, "请求失败")


__all__ = ["StyledAIChatPanel", "StyledAIMessageList", "StyledAIChatBubble", "StyledAIToolApproval"]
