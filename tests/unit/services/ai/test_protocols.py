from freeassetfilter.services.ai.models import AIAccountConfig, AIProvider, ChatMessage
from freeassetfilter.services.ai.protocols import AnthropicAdapter, DeepSeekChatAdapter, DeepSeekResponsesAdapter, OpenAICompatibleAdapter


def account(provider):
    return AIAccountConfig("id", "n", provider, "https://example.test/v1", "model", "key")


def test_openai_request_and_sse():
    adapter = OpenAICompatibleAdapter()
    url, headers, body = adapter.request(account(AIProvider.OPENAI), [ChatMessage("user", "hi")], [])
    assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer key"
    events = list(adapter.parse_stream([b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n']))
    assert [event.kind for event in events] == ["text", "done"] and events[0].text == "ok"


def test_anthropic_system_and_event():
    adapter = AnthropicAdapter()
    _, headers, body = adapter.request(account(AIProvider.ANTHROPIC), [ChatMessage("system", "s"), ChatMessage("user", "u")], [])
    assert headers["x-api-key"] == "key" and b'"system":"s"' in body
    assert list(adapter.parse_stream([b'data: {"type":"content_block_delta","delta":{"text":"x"}}\n\n']))[0].text == "x"


def test_deepseek_chat_request_and_reasoning_stream():
    adapter = DeepSeekChatAdapter()
    deepseek = AIAccountConfig("id", "n", AIProvider.DEEPSEEK_CHAT, "https://example.test", "deepseek-flash", "key", reasoning_enabled=True, reasoning_effort="medium", response_format={"type": "json_object"})
    url, _, body = adapter.request(deepseek, [ChatMessage("user", "return json")], [])
    assert url.endswith("/chat/completions") and b'"thinking":{"type":"enabled"}' in body and b'"reasoning_effort":"high"' in body and b'"response_format"' in body
    events = list(adapter.parse_stream([b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n']))
    assert events[0].kind == "reasoning" and events[0].text == "think"


def test_deepseek_responses_request_and_semantic_stream():
    adapter = DeepSeekResponsesAdapter()
    url, _, body = adapter.request(account(AIProvider.DEEPSEEK_RESPONSES), [ChatMessage("user", "u")], [])
    assert url.endswith("/responses") and b'"input"' in body and b'"max_output_tokens"' in body
    events = list(adapter.parse_stream([b'data: {"type":"response.output_text.delta","delta":"ok"}\n\n']))
    assert events[0].kind == "text" and events[0].text == "ok"

