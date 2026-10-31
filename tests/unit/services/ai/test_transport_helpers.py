from sopeek.services.ai.models import AIAccountConfig, AIProvider
from sopeek.services.ai.transport import HTTPTransport


def test_deepseek_management_urls(monkeypatch):
    account = AIAccountConfig("a", "a", AIProvider.DEEPSEEK_CHAT, "https://api.deepseek.com", "deepseek-flash", "k")
    transport = HTTPTransport(account)
    calls = []
    monkeypatch.setattr(transport, "request_json", lambda method, url, headers, body=None: calls.append((method, url)) or {})
    transport.list_files(); transport.get_file("file-api-x"); transport.delete_file("file-api-x"); transport.get_balance()
    assert calls == [("GET", "https://api.deepseek.com/files"), ("GET", "https://api.deepseek.com/files/file-api-x"), ("DELETE", "https://api.deepseek.com/files/file-api-x"), ("GET", "https://api.deepseek.com/user/balance")]
