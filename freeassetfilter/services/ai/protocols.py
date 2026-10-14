"""HTTP protocol adapters for OpenAI, Anthropic and DeepSeek Responses."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Iterable, Mapping

from .models import (
    AIAccountConfig, AIHTTPError, AIProtocolError, AIProvider, ChatMessage,
    StreamEvent, ToolCallRequest, ToolDefinition,
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(x.get("text", "")) for x in value if isinstance(x, dict))
    return ""


def _tool_payload(tools: Iterable[ToolDefinition]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": dict(t.parameters)}} for t in tools]


def _url(base: str, suffix: str) -> str:
    base = base.rstrip("/")
    if base.endswith(suffix.lstrip("/")):
        return base
    return base + "/" + suffix.lstrip("/")


class ProtocolAdapter(ABC):
    provider: AIProvider

    @abstractmethod
    def request(self, account: AIAccountConfig, messages: list[ChatMessage], tools: list[ToolDefinition], stream: bool = True) -> tuple[str, dict[str, str], bytes]:
        raise NotImplementedError

    @abstractmethod
    def parse_stream(self, chunks: Iterable[bytes]) -> Iterable[StreamEvent]:
        raise NotImplementedError

    def models_url(self, account: AIAccountConfig) -> str | None:
        return None


class OpenAICompatibleAdapter(ProtocolAdapter):
    provider = AIProvider.OPENAI

    def request(self, account: AIAccountConfig, messages: list[ChatMessage], tools: list[ToolDefinition], stream: bool = True) -> tuple[str, dict[str, str], bytes]:
        payload: dict[str, Any] = {"model": account.model, "messages": [m.__dict__ for m in messages], "stream": stream}
        if account.temperature is not None: payload["temperature"] = account.temperature
        if account.max_tokens: payload["max_tokens"] = account.max_tokens
        if tools: payload["tools"] = _tool_payload(tools)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {account.api_key}", **dict(account.headers)}
        return _url(account.base_url, "/chat/completions"), headers, _json_bytes(payload)

    def models_url(self, account: AIAccountConfig) -> str:
        return _url(account.base_url, "/models")

    def parse_stream(self, chunks: Iterable[bytes]) -> Iterable[StreamEvent]:
        yield from _parse_sse(chunks, self._parse_event)

    @staticmethod
    def _parse_event(data: dict[str, Any]) -> list[StreamEvent]:
        choices = data.get("choices") or []
        if not choices: return []
        delta = choices[0].get("delta") or {}
        events: list[StreamEvent] = []
        text = _content_text(delta.get("content"))
        if text: events.append(StreamEvent("text", text=text))
        for call in delta.get("tool_calls") or []:
            fn = call.get("function") or {}
            try: args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError: args = {}
            events.append(StreamEvent("tool_call", tool_call=ToolCallRequest(str(call.get("id", "")), str(fn.get("name", "")), args)))
        if choices[0].get("finish_reason"): events.append(StreamEvent("done", data={"finish_reason": choices[0]["finish_reason"], "usage": data.get("usage", {})}))
        return events


class AnthropicAdapter(ProtocolAdapter):
    provider = AIProvider.ANTHROPIC

    def request(self, account: AIAccountConfig, messages: list[ChatMessage], tools: list[ToolDefinition], stream: bool = True) -> tuple[str, dict[str, str], bytes]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body_messages = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        payload: dict[str, Any] = {"model": account.model, "messages": body_messages, "max_tokens": account.max_tokens, "stream": stream}
        if system: payload["system"] = system
        if account.temperature is not None: payload["temperature"] = account.temperature
        if tools: payload["tools"] = [{"name": t.name, "description": t.description, "input_schema": dict(t.parameters)} for t in tools]
        headers = {"Content-Type": "application/json", "x-api-key": account.api_key, "anthropic-version": "2023-06-01", **dict(account.headers)}
        return _url(account.base_url, "/v1/messages"), headers, _json_bytes(payload)

    def parse_stream(self, chunks: Iterable[bytes]) -> Iterable[StreamEvent]:
        yield from _parse_sse(chunks, self._parse_event)

    @staticmethod
    def _parse_event(data: dict[str, Any]) -> list[StreamEvent]:
        kind = data.get("type")
        if kind == "content_block_delta":
            delta = data.get("delta") or {}
            text = delta.get("text", "")
            return [StreamEvent("text", text=text)] if text else []
        if kind == "message_delta": return [StreamEvent("done", data=data.get("delta") or {})]
        if kind == "message_stop": return [StreamEvent("done")]
        if kind == "error": return [StreamEvent("error", error=AIProtocolError(str(data.get("error", data))))]
        return []


class DeepSeekResponsesAdapter(ProtocolAdapter):
    """DeepSeek Chat Completions adapter with vision and thinking support.

    The historical class name is retained for configuration compatibility; the
    DeepSeek API endpoint is ``/chat/completions``, not ``/responses``.
    """
    provider = AIProvider.DEEPSEEK_RESPONSES

    def request(self, account: AIAccountConfig, messages: list[ChatMessage], tools: list[ToolDefinition], stream: bool = True) -> tuple[str, dict[str, str], bytes]:
        payload: dict[str, Any] = {"model": account.model, "messages": [{"role": m.role, "content": m.content} for m in messages], "stream": stream}
        if account.temperature is not None: payload["temperature"] = account.temperature
        if account.max_tokens: payload["max_tokens"] = account.max_tokens
        if account.reasoning_enabled is not None:
            payload["thinking"] = {"type": "enabled" if account.reasoning_enabled else "disabled"}
        if account.reasoning_budget is not None:
            payload["thinking"]["budget_tokens"] = account.reasoning_budget
        if tools: payload["tools"] = _tool_payload(tools)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {account.api_key}", **dict(account.headers)}
        return _url(account.base_url, "/chat/completions"), headers, _json_bytes(payload)

    def parse_stream(self, chunks: Iterable[bytes]) -> Iterable[StreamEvent]:
        yield from _parse_sse(chunks, self._parse_event)

    @staticmethod
    def _parse_event(data: dict[str, Any]) -> list[StreamEvent]:
        choices = data.get("choices") or []
        if not choices: return []
        delta = choices[0].get("delta") or {}
        events: list[StreamEvent] = []
        reasoning = delta.get("reasoning_content", "")
        if reasoning: events.append(StreamEvent("reasoning", text=str(reasoning)))
        text = _content_text(delta.get("content"))
        if text: events.append(StreamEvent("text", text=text))
        for call in delta.get("tool_calls") or []:
            fn = call.get("function") or {}
            try: args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError: args = {}
            events.append(StreamEvent("tool_call", tool_call=ToolCallRequest(str(call.get("id", "")), str(fn.get("name", "")), args)))
        if choices[0].get("finish_reason"): events.append(StreamEvent("done", data={"finish_reason": choices[0]["finish_reason"], "usage": data.get("usage", {})}))
        return events


def _parse_sse(chunks: Iterable[bytes], parser: Any) -> Iterable[StreamEvent]:
    buffer = ""
    for chunk in chunks:
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
            if not data_lines: continue
            data = "\n".join(data_lines)
            if data == "[DONE]":
                yield StreamEvent("done"); continue
            try: parsed = json.loads(data)
            except json.JSONDecodeError as exc: raise AIProtocolError(f"invalid SSE JSON: {data[:200]}") from exc
            yield from parser(parsed)
    if buffer.strip() and buffer.startswith("data:"):
        data = buffer[5:].strip()
        if data != "[DONE]": yield from parser(json.loads(data))


def adapter_for(provider: AIProvider) -> ProtocolAdapter:
    if provider == AIProvider.OPENAI: return OpenAICompatibleAdapter()
    if provider == AIProvider.ANTHROPIC: return AnthropicAdapter()
    if provider == AIProvider.DEEPSEEK_RESPONSES: return DeepSeekResponsesAdapter()
    raise AIProtocolError(f"unsupported provider: {provider}")


__all__ = ["ProtocolAdapter", "OpenAICompatibleAdapter", "AnthropicAdapter", "DeepSeekResponsesAdapter", "adapter_for"]
