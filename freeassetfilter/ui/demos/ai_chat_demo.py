"""AI chat flow demo with provider/account settings.

Run: ``python -m freeassetfilter.ui.demos.ai_chat_demo``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QSpinBox, QTabWidget, QDoubleSpinBox, QVBoxLayout, QWidget,
)

from freeassetfilter.services.ai import AIAccountConfig, AIAgentService, AIConfigStore, AIProvider, AIWorker, ChatMessage
from freeassetfilter.ui.components.styled_ai_chat import StyledAIChatPanel
from freeassetfilter.ui.components.styled_button import StyledButton
from freeassetfilter.ui.theme.app_stylesheet import apply_app_stylesheet


class AISettingsPage(QWidget):
    saved = __import__("PySide6.QtCore", fromlist=["Signal"]).Signal(object)

    def __init__(self, store: AIConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        form = QFormLayout(self); form.setContentsMargins(24, 24, 24, 24); form.setSpacing(12)
        self.account_name = QLineEdit("Demo")
        self.provider = QComboBox(); self.provider.addItem("OpenAI 通用接口", AIProvider.OPENAI.value); self.provider.addItem("Anthropic Messages", AIProvider.ANTHROPIC.value); self.provider.addItem("DeepSeek Chat Completions", AIProvider.DEEPSEEK_CHAT.value); self.provider.addItem("DeepSeek Responses", AIProvider.DEEPSEEK_RESPONSES.value)
        self.base_url = QLineEdit("https://api.openai.com/v1")
        self.model = QLineEdit("gpt-4o-mini")
        self.api_key = QLineEdit(); self.api_key.setEchoMode(QLineEdit.Password); self.api_key.setPlaceholderText("保存时使用 Windows DPAPI 加密")
        self.temperature = QDoubleSpinBox(); self.temperature.setRange(0, 2); self.temperature.setSingleStep(0.1); self.temperature.setValue(0.2)
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(1, 200000); self.max_tokens.setValue(4096)
        self.timeout = QSpinBox(); self.timeout.setRange(5, 600); self.timeout.setValue(90)
        self.reasoning = QCheckBox("启用思考内容"); self.reasoning.setChecked(False)
        self.reasoning_budget = QSpinBox(); self.reasoning_budget.setRange(1, 100000); self.reasoning_budget.setValue(4096)
        for label, widget in (("账号名称", self.account_name), ("服务商", self.provider), ("Base URL", self.base_url), ("模型", self.model), ("API Key", self.api_key), ("Temperature", self.temperature), ("最大 Token", self.max_tokens), ("超时（秒）", self.timeout), ("思考模式", self.reasoning), ("思考预算", self.reasoning_budget)): form.addRow(label, widget)
        row = QHBoxLayout(); self.save_button = StyledButton("保存配置", variant="primary"); self.reload_button = StyledButton("读取已保存账号", variant="secondary"); self.message = QLabel("API Key 不会以明文写入磁盘"); row.addWidget(self.save_button); row.addWidget(self.reload_button); row.addWidget(self.message, 1); form.addRow(row)
        self.save_button.clicked.connect(self._save); self.reload_button.clicked.connect(self._load)
        self.provider.currentIndexChanged.connect(self._provider_changed)

    def _provider_changed(self, index: int) -> None:
        provider = self.provider.itemData(index)
        defaults = {AIProvider.OPENAI.value: ("https://api.openai.com/v1", "gpt-4o-mini"), AIProvider.ANTHROPIC.value: ("https://api.anthropic.com", "claude-3-5-sonnet-latest"), AIProvider.DEEPSEEK_CHAT.value: ("https://api.deepseek.com", "deepseek-flash"), AIProvider.DEEPSEEK_RESPONSES.value: ("https://api.deepseek.com", "deepseek-flash")}
        base, model = defaults[provider]; self.base_url.setText(base); self.model.setText(model)

    def _save(self) -> None:
        account = AIAccountConfig("demo", self.account_name.text().strip() or "Demo", AIProvider(self.provider.currentData()), self.base_url.text().strip(), self.model.text().strip(), self.api_key.text(), self.temperature.value(), self.max_tokens.value(), self.timeout.value(), {}, self.reasoning.isChecked() if self.provider.currentData() in {AIProvider.DEEPSEEK_CHAT.value, AIProvider.DEEPSEEK_RESPONSES.value} else None, self.reasoning_budget.value() if self.reasoning.isChecked() else None)
        try:
            self.store.save([account], "demo"); self.message.setText("已保存（DPAPI 加密）"); self.saved.emit(account)
        except Exception as exc: self.message.setText(f"保存失败：{exc}")

    def _load(self) -> None:
        try:
            accounts = self.store.accounts()
            if not accounts: self.message.setText("暂无已保存账号"); return
            account = accounts[0]; self.account_name.setText(account.name); self.provider.setCurrentIndex(self.provider.findData(account.provider.value)); self.base_url.setText(account.base_url); self.model.setText(account.model); self.api_key.setText(account.api_key); self.temperature.setValue(account.temperature or 0); self.max_tokens.setValue(account.max_tokens); self.timeout.setValue(int(account.timeout)); self.reasoning.setChecked(bool(account.reasoning_enabled)); self.reasoning_budget.setValue(account.reasoning_budget or 4096); self.message.setText("已读取已保存账号")
        except Exception as exc: self.message.setText(f"读取失败：{exc}")


class AIChatDemoWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__(); self.setWindowTitle("AI Agent 对话流 Demo"); self.resize(820, 760); self.store = AIConfigStore(); self.worker: AIWorker | None = None
        tabs = QTabWidget(); self.panel = StyledAIChatPanel("AI Agent 文件问答"); self.settings = AISettingsPage(self.store); tabs.addTab(self.panel, "对话"); tabs.addTab(self.settings, "服务商配置"); self.setCentralWidget(tabs)
        self.panel.send_requested.connect(self._start_request); self.panel.cancel_requested.connect(self._cancel_request); self.settings.saved.connect(self._saved_account)

    def _saved_account(self, _account: object) -> None: self.panel.status.setText("配置已保存，可开始对话")

    def _account(self) -> AIAccountConfig:
        accounts = self.store.accounts()
        if accounts: return accounts[0]
        provider = AIProvider(os.getenv("FAF_AI_PROVIDER", "openai")); defaults = {AIProvider.OPENAI: "https://api.openai.com/v1", AIProvider.ANTHROPIC: "https://api.anthropic.com", AIProvider.DEEPSEEK_CHAT: "https://api.deepseek.com", AIProvider.DEEPSEEK_RESPONSES: "https://api.deepseek.com"}
        return AIAccountConfig("demo", "Demo", provider, os.getenv("FAF_AI_BASE_URL", defaults[provider]), os.getenv("FAF_AI_MODEL", "gpt-4o-mini"), os.getenv("FAF_AI_API_KEY", ""))

    def _start_request(self, text: str) -> None:
        try: account = self._account()
        except Exception as exc: self.panel.show_error(str(exc)); return
        if not account.api_key: self.panel.show_error("请先在“服务商配置”页面填写 API Key"); return
        self.worker = AIWorker(AIAgentService(account), [ChatMessage("user", text)]); self.worker.signals.event.connect(self._on_event); self.worker.signals.finished.connect(lambda _: self.panel.set_busy(False, "完成")); self.worker.signals.failed.connect(lambda error: self.panel.show_error(str(error))); self.worker.start()

    def _on_event(self, event: object) -> None:
        if getattr(event, "kind", "") == "reasoning": self.panel.append_reasoning(getattr(event, "text", "")); self.panel.status.setText("思考中…")
        elif getattr(event, "kind", "") == "text": self.panel.append_text(getattr(event, "text", "")); self.panel.status.setText("生成中…")
        elif getattr(event, "kind", "") == "tool_approval": self.panel.status.setText("等待工具审批")

    def _cancel_request(self) -> None:
        if self.worker is not None: self.worker.cancel()


def main() -> int:
    app = QApplication(sys.argv); apply_app_stylesheet(); window = AIChatDemoWindow(); window.show(); return app.exec()


if __name__ == "__main__": raise SystemExit(main())
