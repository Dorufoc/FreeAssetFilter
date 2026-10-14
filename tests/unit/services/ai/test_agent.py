from freeassetfilter.services.ai.agent import AIAgentService
from freeassetfilter.services.ai.models import AIAccountConfig, AIProvider, ChatMessage, StreamEvent, ToolCallRequest, ToolDefinition


class FakeAdapter:
    def request(self, *args, **kwargs): return "url", {}, b""
    def parse_stream(self, chunks): return iter(chunks)
    def models_url(self, account): return None


class FakeTransport:
    def __init__(self): self.count = 0
    def post_stream(self, *args, **kwargs):
        self.count += 1
        if self.count == 1:
            return [StreamEvent("tool_call", tool_call=ToolCallRequest("c1", "sum", {"n": 2}))]
        return [StreamEvent("text", text="done")]


def test_tool_call_requires_approval_and_returns_result():
    account = AIAccountConfig("a", "a", AIProvider.OPENAI, "https://x", "m")
    service = AIAgentService(account, FakeTransport())
    service.adapter = FakeAdapter()
    tools = [ToolDefinition("sum", "sum", {"type": "object"}, lambda args: args["n"] + 1)]
    events = list(service.stream([ChatMessage("user", "go")], tools=tools, approve=lambda call: True))
    assert any(event.kind == "tool_result" for event in events)
    assert events[-1].text == "done"


def test_tool_rejected_without_approval():
    account = AIAccountConfig("a", "a", AIProvider.OPENAI, "https://x", "m")
    service = AIAgentService(account, FakeTransport())
    service.adapter = FakeAdapter()
    events = list(service.stream([ChatMessage("user", "go")], tools=[ToolDefinition("sum", "sum", {})]))
    result = next(event for event in events if event.kind == "tool_result")
    assert result.data["result"]["error"] == "tool call rejected by user"
