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


def _tool_payload(tools: Iterable[ToolDefinition], strict_default: bool = False) -> list[dict[str, Any]]:
    result = []
    for tool in tools:
        function = {"name": tool.name, "description": tool.description, "parameters": dict(tool.parameters)}
        if strict_default or tool.strict:
            function["strict"] = True
        result.append({"type": "function", "function": function})
    return result


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

    def parse_response(self, payload: Mapping[str, Any]) -> list[StreamEvent]:
        return []


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

    def parse_response(self, payload: Mapping[str, Any]) -> list[StreamEvent]:
        return self._parse_event(dict(payload))

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


class DeepSeekChatAdapter(ProtocolAdapter):
    """DeepSeek OpenAI-compatible Chat Completions adapter."""
    provider = AIProvider.DEEPSEEK_CHAT

    @staticmethod
    def _message_payload(message: ChatMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.name: payload["name"] = message.name
        if message.tool_calls: payload["tool_calls"] = message.tool_calls
        if message.tool_call_id: payload["tool_call_id"] = message.tool_call_id
        if message.reasoning_content: payload["reasoning_content"] = message.reasoning_content
        if message.prefix: payload["prefix"] = True
        return payload

    def request(self, account: AIAccountConfig, messages: list[ChatMessage], tools: list[ToolDefinition], stream: bool = True) -> tuple[str, dict[str, str], bytes]:
        payload: dict[str, Any] = {"model": account.model, "messages": [self._message_payload(m) for m in messages], "stream": stream}
        # DeepSeek thinking mode ignores sampling knobs; omit them to match docs.
        thinking = account.reasoning_enabled is not None
        if account.temperature is not None and not thinking: payload["temperature"] = account.temperature
        if account.top_p is not None: payload["top_p"] = account.top_p
        if account.max_tokens: payload["max_tokens"] = account.max_tokens
        if thinking: payload["thinking"] = {"type": "enabled" if account.reasoning_enabled else "disabled"}
        if account.reasoning_effort: payload["reasoning_effort"] = self._normalize_effort(account.reasoning_effort)
        if account.response_format is not None: payload["response_format"] = dict(account.response_format)
        if account.tool_choice is not None: payload["tool_choice"] = account.tool_choice
        if account.user: payload["user"] = account.user
        if tools: payload["tools"] = _tool_payload(tools, account.strict_tools)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {account.api_key}", **dict(account.headers)}
        return _url(account.base_url, "/chat/completions"), headers, _json_bytes(payload)

    @staticmethod
    def _normalize_effort(value: str) -> str:
        normalized = value.lower()
        if normalized in {"low", "medium", "high"}: return "high"
        if normalized in {"xhigh", "max"}: return "max"
        raise AIProtocolError("DeepSeek reasoning_effort must be high or max")

    def parse_response(self, payload: Mapping[str, Any]) -> list[StreamEvent]:
        return self._parse_event(dict(payload))

    def parse_stream(self, chunks: Iterable[bytes]) -> Iterable[StreamEvent]:
        yield from _parse_sse(chunks, self._parse_event)

    @staticmethod
    def _parse_event(data: dict[str, Any]) -> list[StreamEvent]:
        choices = data.get("choices") or []
        if not choices: return []
        choice = choices[0]; delta = choice.get("delta") or {}; events: list[StreamEvent] = []
        reasoning = delta.get("reasoning_content", "")
        if reasoning: events.append(StreamEvent("reasoning", text=str(reasoning)))
        text = _content_text(delta.get("content"))
        if text: events.append(StreamEvent("text", text=text))
        for call in delta.get("tool_calls") or []:
            fn = call.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try: args = json.loads(raw_args)
            except json.JSONDecodeError: args = {"_raw": raw_args}
            events.append(StreamEvent("tool_call", tool_call=ToolCallRequest(str(call.get("id", "")), str(fn.get("name", "")), args)))
        if choice.get("finish_reason") is not None: events.append(StreamEvent("done", data={"finish_reason": choice["finish_reason"], "usage": data.get("usage", {})}))
        return events


class DeepSeekResponsesAdapter(ProtocolAdapter):
    """DeepSeek Responses API adapter with semantic SSE events."""
    provider = AIProvider.DEEPSEEK_RESPONSES

    def request(self, account: AIAccountConfig, messages: list[ChatMessage], tools: list[ToolDefinition], stream: bool = True) -> tuple[str, dict[str, str], bytes]:
        instructions = "\\n\\n".join(m.content for m in messages if m.role == "system" and isinstance(m.content, str))
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system": continue
            content = message.content
            if isinstance(content, str):
                input_items.append({"role": message.role, "content": content})
            else:
                blocks = []
                for block in content:
                    if block.get("type") == "text": blocks.append({"type": "input_text", "text": block.get("text", "")})
                    elif block.get("type") == "image_url": blocks.append({"type": "input_image", "image_url": block.get("image_url", {}).get("url", ""), "detail": block.get("image_url", {}).get("detail", "auto")})
                input_items.append({"role": message.role, "content": blocks})
        payload: dict[str, Any] = {"model": account.model, "input": input_items, "stream": stream}
        if instructions: payload["instructions"] = instructions
        if account.temperature is not None: payload["temperature"] = account.temperature
        if account.top_p is not None: payload["top_p"] = account.top_p
        if account.max_tokens: payload["max_output_tokens"] = account.max_tokens
        if account.reasoning_effort: payload["reasoning"] = {"effort": DeepSeekChatAdapter._normalize_effort(account.reasoning_effort)}
        if account.tool_choice is not None: payload["tool_choice"] = account.tool_choice
        if tools: payload["tools"] = _tool_payload(tools, account.strict_tools)
        if account.user: payload["user"] = account.user
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {account.api_key}", **dict(account.headers)}
        return _url(account.base_url, "/responses"), headers, _json_bytes(payload)

    def parse_response(self, payload: Mapping[str, Any]) -> list[StreamEvent]:
        output = payload.get("output", [])
        events: list[StreamEvent] = []
        for item in output if isinstance(output, list) else []:
            for block in item.get("content", []) if isinstance(item, dict) else []:
                if block.get("type") in {"output_text", "reasoning_text"}:
                    events.append(StreamEvent("reasoning" if block["type"] == "reasoning_text" else "text", text=str(block.get("text", ""))))
            if item.get("type") == "function_call":
                try: args = json.loads(item.get("arguments", "{}"))
                except json.JSONDecodeError: args = {}
                events.append(StreamEvent("tool_call", tool_call=ToolCallRequest(str(item.get("call_id", "")), str(item.get("name", "")), args)))
        events.append(StreamEvent("done", data=payload))
        return events

    def parse_stream(self, chunks: Iterable[bytes]) -> Iterable[StreamEvent]:
        yield from _parse_sse_events(chunks, self._parse_event)

    @staticmethod
    def _parse_event(data: dict[str, Any]) -> list[StreamEvent]:
        typ = data.get("type", "")
        if typ == "response.reasoning_text.delta": return [StreamEvent("reasoning", text=str(data.get("delta", "")))]
        if typ == "response.output_text.delta": return [StreamEvent("text", text=str(data.get("delta", "")))]
        if typ == "response.function_call_arguments.done":
            try: args = json.loads(data.get("arguments", "{}"))
            except json.JSONDecodeError: args = {}
            return [StreamEvent("tool_call", tool_call=ToolCallRequest(str(data.get("call_id", "")), str(data.get("name", "")), args))]
        if typ in {"response.completed", "response.incomplete"}: return [StreamEvent("done", data=data.get("response", data))]
        if typ == "response.failed": return [StreamEvent("error", error=AIProtocolError(str(data.get("response", data))))]
        return []


def _parse_sse_events(chunks: Iterable[bytes], parser: Any) -> Iterable[StreamEvent]:
    """Parse SSE blocks where event type is part of the JSON data."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            data = "\n".join(line[5:].strip() for line in block.splitlines() if line.startswith("data:"))
            if not data: continue
            try: yield from parser(json.loads(data))
            except json.JSONDecodeError as exc: raise AIProtocolError(f"invalid Responses SSE JSON: {data[:200]}") from exc
    if buffer.strip() and buffer.startswith("data:"):
        try: yield from parser(json.loads(buffer[5:].strip()))
        except json.JSONDecodeError as exc: raise AIProtocolError("invalid Responses SSE JSON") from exc


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
    if provider == AIProvider.DEEPSEEK_CHAT: return DeepSeekChatAdapter()
    if provider == AIProvider.DEEPSEEK_RESPONSES: return DeepSeekResponsesAdapter()
    raise AIProtocolError(f"unsupported provider: {provider}")


__all__ = ["ProtocolAdapter", "OpenAICompatibleAdapter", "AnthropicAdapter", "DeepSeekChatAdapter", "DeepSeekResponsesAdapter", "adapter_for"]
