"""Protocol-neutral AI Agent orchestration with approval-gated tools."""
from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .context import render_file_context
from .models import (
    AIAccountConfig, AICancelledError, AIConfigError, ChatMessage, ChatResult,
    FileContext, StreamEvent, ToolCallRequest, ToolDefinition,
)
from .protocols import adapter_for
from .transport import HTTPTransport


class AIAgentService:
    def __init__(self, account: AIAccountConfig, transport: HTTPTransport | None = None, max_tool_rounds: int = 4, max_tool_result_chars: int = 20_000) -> None:
        self.account = account
        self.adapter = adapter_for(account.provider)
        self.transport = transport or HTTPTransport(account)
        self.max_tool_rounds = max_tool_rounds
        self.max_tool_result_chars = max_tool_result_chars

    def stream(self, messages: list[ChatMessage], files: Iterable[FileContext] = (), extra: str = "", image_paths: Iterable[str] = (), tools: Iterable[ToolDefinition] = (), approve: Callable[[ToolCallRequest], bool] | None = None, cancel: threading.Event | None = None) -> Iterable[StreamEvent]:
        tool_list = list(tools)
        history = list(messages)
        context = render_file_context(files, extra)
        if context:
            history.append(ChatMessage("user", context))
        image_paths = list(image_paths)
        if image_paths:
            from .context import AIFileContextService
            history.append(ChatMessage("user", AIFileContextService().vision_message("请分析这些图像。", image_paths)["content"]))
        for round_no in range(self.max_tool_rounds + 1):
            if cancel is not None and cancel.is_set(): raise AICancelledError("AI 请求已取消")
            url, headers, body = self.adapter.request(self.account, history, tool_list, stream=True)
            text_parts: list[str] = []
            calls: list[ToolCallRequest] = []
            for event in self.adapter.parse_stream(self.transport.post_stream(url, headers, body, cancel)):
                if event.kind == "text": text_parts.append(event.text)
                if event.kind == "tool_call" and event.tool_call is not None: calls.append(event.tool_call)
                yield event
            if not calls: return
            assistant = ChatMessage("assistant", "".join(text_parts), tool_calls=[{"id": c.call_id, "name": c.name, "arguments": dict(c.arguments)} for c in calls])
            history.append(assistant)
            for call in calls:
                yield StreamEvent("tool_approval", tool_call=call)
                if approve is None or not approve(call):
                    result = {"error": "tool call rejected by user"}
                else:
                    definition = next((tool for tool in tool_list if tool.name == call.name), None)
                    if definition is None or definition.handler is None:
                        result = {"error": f"unknown tool: {call.name}"}
                    else:
                        try: result = definition.handler(call.arguments)
                        except Exception as exc: result = {"error": str(exc)}
                encoded = json.dumps(result, ensure_ascii=False)[: self.max_tool_result_chars]
                history.append(ChatMessage("tool", encoded, name=call.name, tool_call_id=call.call_id))
                yield StreamEvent("tool_result", tool_call=call, data={"result": result})
        raise AIConfigError("工具调用超过最大轮数")

    def discover_models(self) -> list[str]:
        """Return server models when the configured adapter exposes a catalog."""
        url = self.adapter.models_url(self.account)
        if not url:
            return [self.account.model]
        headers = {"Authorization": f"Bearer {self.account.api_key}"}
        payload = self.transport.get_json(url, headers)
        values = payload.get("data", [])
        return [str(item.get("id")) for item in values if isinstance(item, dict) and item.get("id")] or [self.account.model]

    def ask(self, messages: list[ChatMessage], **kwargs: Any) -> ChatResult:
        text = ""
        usage: Mapping[str, Any] = {}
        for event in self.stream(messages, **kwargs):
            if event.kind == "text": text += event.text
            usage = event.data.get("usage", usage)
        return ChatResult(ChatMessage("assistant", text), usage)


__all__ = ["AIAgentService"]
