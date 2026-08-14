"""Claude provider configuration (provider-migration spec section 4)."""
from app.config import LLM_MODEL_PRICING_USD_PER_MTOK, Settings, settings


def test_claude_settings_defaults():
    assert settings.claude_model == "claude-opus-5"
    assert settings.claude_fact_model == "claude-haiku-4-5"
    assert settings.claude_summary_model == "claude-haiku-4-5"
    assert settings.claude_max_output_tokens == 16000
    assert settings.claude_timeout == 180.0
    assert settings.claude_max_retries == 2
    assert settings.claude_retry_backoff == 2.0
    assert settings.llm_provider_mode == "claude"
    assert settings.llm_fallback_allowed is False


def test_claude_api_key_prefers_claude_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "ck-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-1")
    assert Settings().claude_api_key == "ck-1"


def test_claude_api_key_falls_back_to_anthropic_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak-2")
    assert Settings().claude_api_key == "ak-2"


def test_claude_stage_model_override_map(monkeypatch):
    monkeypatch.setenv("CLAUDE_STAGE_MODEL_OVERRIDES",
                       "ripple_discovery=claude-haiku-4-5, map_companies=claude-opus-5")
    m = Settings().claude_stage_model_override_map
    assert m == {"ripple_discovery": "claude-haiku-4-5", "map_companies": "claude-opus-5"}


def test_claude_models_are_priced():
    for model in ("claude-opus-5", "claude-haiku-4-5"):
        pricing = LLM_MODEL_PRICING_USD_PER_MTOK[model]
        assert pricing["input"] > 0 and pricing["output"] > 0
        assert 0 < pricing["cache_read"] < pricing["input"]
