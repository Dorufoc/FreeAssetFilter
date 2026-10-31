from sopeek.services.ai.models import AIAccountConfig, AIProvider
from sopeek.services.ai.config_store import AIConfigStore

def test_config_store_does_not_store_plaintext_secret(tmp_path):
    store = AIConfigStore(str(tmp_path))
    account = AIAccountConfig("id", "n", AIProvider.OPENAI, "https://x", "m", "secret")
    store.save([account])
    assert "secret" not in store.path.read_text(encoding="utf-8")
    assert store.accounts()[0].api_key == "secret"
