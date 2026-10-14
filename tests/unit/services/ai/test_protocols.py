from freeassetfilter.services.ai.models import AIAccountConfig, AIProvider, ChatMessage
from freeassetfilter.services.ai.protocols import AnthropicAdapter, DeepSeekResponsesAdapter, OpenAICompatibleAdapter


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


def test_deepseek_responses_request():
    adapter = DeepSeekResponsesAdapter()
    url, _, body = adapter.request(account(AIProvider.DEEPSEEK_RESPONSES), [ChatMessage("user", "u")], [])
    assert url.endswith("/chat/completions") and b'"messages"' in body and b'"max_tokens"' in body


def test_deepseek_reasoning_stream():
    adapter = DeepSeekResponsesAdapter()
    events = list(adapter.parse_stream([b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n']))
    assert events[0].kind == "reasoning" and events[0].text == "think"

