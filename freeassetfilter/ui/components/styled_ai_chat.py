"""Reusable styled AI chat panel for embedding in existing layouts."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.components.styled_textarea import StyledTextarea
from freeassetfilter.ui.theme.app_stylesheet import register_widget_qss
from theme import tm


class StyledAIMessageList(QListWidget):
    def add_message(self, role: str, text: str) -> QListWidgetItem:
        item = QListWidgetItem(f"{role}: {text}")
        item.setData(Qt.UserRole, role)
        self.addItem(item)
        self.scrollToBottom()
        return item

    def append_to_last(self, text: str) -> None:
        if self.count():
            item = self.item(self.count() - 1)
            item.setText(item.text() + text)
            self.scrollToBottom()


class StyledAIToolApproval(QWidget):
    approved = Signal(str)
    rejected = Signal(str)

    def __init__(self, call_id: str, name: str, arguments: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.call_id = call_id
        layout = QHBoxLayout(self)
        label = QLabel(f"工具请求：{name}\n{arguments}")
        approve = StyledButton("批准", variant="primary", size="sm")
        reject = StyledButton("拒绝", variant="danger", size="sm")
        approve.clicked.connect(lambda: self.approved.emit(self.call_id))
        reject.clicked.connect(lambda: self.rejected.emit(self.call_id))
        layout.addWidget(label, 1); layout.addWidget(approve); layout.addWidget(reject)


class StyledAIChatPanel(QWidget):
    send_requested = Signal(str)
    cancel_requested = Signal()
    tool_approval = Signal(str, bool)

    def __init__(self, title: str = "AI 对话", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._assistant_item: QListWidgetItem | None = None
        root = QVBoxLayout(self); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(8)
        header = QLabel(title); header.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {tm.text.name()};")
        root.addWidget(header)
        self.messages = StyledAIMessageList(self); self.messages.setObjectName("StyledAIMessageList"); root.addWidget(self.messages, 1)
        self.composer = StyledTextarea(placeholder="输入问题或补充信息…", size="default", parent=self); root.addWidget(self.composer)
        actions = QHBoxLayout(); self.status = QLabel("就绪"); self.send_button = StyledButton("发送", variant="primary"); self.cancel_button = StyledButton("取消", variant="secondary"); self.cancel_button.setEnabled(False)
        self.send_button.clicked.connect(self._send); self.cancel_button.clicked.connect(self.cancel_requested.emit)
        actions.addWidget(self.status, 1); actions.addWidget(self.cancel_button); actions.addWidget(self.send_button); root.addLayout(actions)
        register_widget_qss(self, f"#StyledAIMessageList {{ background: {tm.alpha_of(tm.surface, 35).name()}; border: 1px solid {tm.control_border.name()}; border-radius: 6px; color: {tm.text.name()}; }}")

    def _send(self) -> None:
        text = self.composer.text.strip()
        if not text: return
        self.messages.add_message("你", text); self.composer.text = ""; self._assistant_item = self.messages.add_message("AI", ""); self.set_busy(True); self.send_requested.emit(text)

    def append_reasoning(self, text: str) -> None:
        """Append model reasoning to a separate collapsible-style transcript item."""
        item = self.messages.item(self.messages.count() - 1) if self.messages.count() else None
        if item is None or item.data(Qt.UserRole) != "思考":
            item = self.messages.add_message("思考", "")
            item.setData(Qt.UserRole, "思考")
        item.setText(item.text() + text)
        self.messages.scrollToBottom()

    def append_text(self, text: str) -> None:
        if self._assistant_item is None: self._assistant_item = self.messages.add_message("AI", "")
        self._assistant_item.setText(self._assistant_item.text() + text); self.messages.scrollToBottom()

    def add_tool_approval(self, call_id: str, name: str, arguments: str) -> StyledAIToolApproval:
        widget = StyledAIToolApproval(call_id, name, arguments, self)
        widget.approved.connect(lambda value: self.tool_approval.emit(value, True)); widget.rejected.connect(lambda value: self.tool_approval.emit(value, False))
        item = QListWidgetItem(); item.setSizeHint(widget.sizeHint()); self.messages.addItem(item); self.messages.setItemWidget(item, widget); self.messages.scrollToBottom(); return widget

    def set_busy(self, busy: bool, status: str = "处理中…") -> None:
        self.send_button.setEnabled(not busy); self.cancel_button.setEnabled(busy); self.status.setText(status if busy else "就绪")

    def show_error(self, message: str) -> None:
        self.status.setText(message); self.set_busy(False)


__all__ = ["StyledAIChatPanel", "StyledAIMessageList", "StyledAIToolApproval"]
