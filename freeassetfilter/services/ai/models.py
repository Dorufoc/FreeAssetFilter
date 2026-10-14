"""AI Agent shared data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class AIProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK_RESPONSES = "deepseek_responses"


class AIError(RuntimeError):
    """Base error exposed by the AI service layer."""


class AIConfigError(AIError):
    pass


class AIHTTPError(AIError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class AIProtocolError(AIError):
    pass


class AITimeoutError(AIError):
    pass


class AICancelledError(AIError):
    pass


@dataclass(frozen=True)
class AIAccountConfig:
    account_id: str
    name: str
    provider: AIProvider
    base_url: str
    model: str
    api_key: str = ""
    temperature: float | None = 0.2
    max_tokens: int = 4096
    timeout: float = 90.0
    headers: Mapping[str, str] = field(default_factory=dict)
    reasoning_enabled: bool | None = None
    reasoning_budget: int | None = None


@dataclass
class ChatMessage:
    role: str
    content: str | list[dict[str, Any]] = ""
    reasoning_content: str = ""
    name: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class FileContext:
    path: str
    name: str
    suffix: str
    text: str
    encoding: str
    truncated: bool = False
    error: str = ""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any]], Any] | None = None


@dataclass(frozen=True)
class ToolCallRequest:
    call_id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    text: str = ""
    tool_call: ToolCallRequest | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    error: AIError | None = None


@dataclass(frozen=True)
class ChatResult:
    message: ChatMessage
    usage: Mapping[str, Any] = field(default_factory=dict)
    rounds: int = 1


__all__ = [
    "AIProvider", "AIError", "AIConfigError", "AIHTTPError", "AIProtocolError",
    "AITimeoutError", "AICancelledError", "AIAccountConfig", "ChatMessage",
    "FileContext", "ToolDefinition", "ToolCallRequest", "StreamEvent", "ChatResult",
]
