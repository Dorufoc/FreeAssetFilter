import json
from sopeek.services.ai.models import AIAccountConfig, AIProvider, ChatMessage
from sopeek.services.ai.protocols import DeepSeekChatAdapter, DeepSeekResponsesAdapter


def test_chat_docs_parameters_and_non_stream_response():
    account = AIAccountConfig("a", "a", AIProvider.DEEPSEEK_CHAT, "https://api.deepseek.com", "deepseek-flash", "k", reasoning_enabled=True, reasoning_effort="high", response_format={"type": "json_object"}, tool_choice="auto", top_p=0.95, user="u")
    adapter = DeepSeekChatAdapter()
    url, _, body = adapter.request(account, [ChatMessage("system", "json output"), ChatMessage("user", "json")], [])
    payload = json.loads(body)
    assert url.endswith("/chat/completions")
    assert payload["thinking"]["type"] == "enabled"
    assert payload["reasoning_effort"] == "high"
    assert payload["response_format"] == {"type": "json_object"}
    events = adapter.parse_response({"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}], "usage": {"total_tokens": 2}})
    assert any(e.kind == "done" for e in events)


def test_responses_docs_non_stream_and_reasoning_event():
    adapter = DeepSeekResponsesAdapter()
    events = adapter.parse_response({"output": [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "think"}]}, {"type": "message", "content": [{"type": "output_text", "text": "answer"}]}], "usage": {"input_tokens": 1}})
    assert [event.kind for event in events[:2]] == ["reasoning", "text"]
    assert events[-1].kind == "done"
