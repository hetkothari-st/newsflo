"""Provider policy: Claude-first, fail-closed, Groq explicit-only, Gemini
never callable (provider-migration spec sections 5, 9, 16, 19, 20)."""
import pytest

from app.analysis.impact_graph.claude_json import ClaudeJSONError
from app.analysis.impact_graph.router import StageRouter, StageRouterError
from app.config import settings


class _ClaudeOK:
    def __init__(self, payload=None):
        self.calls = 0
        self._payload = payload or {"companies": []}

    def generate(self, **kwargs):
        self.calls += 1
        return self._payload


class _ClaudeFail:
    def __init__(self, kind="transport"):
        self._kind = kind
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        raise ClaudeJSONError("boom", kind=self._kind)


class _GroqOK:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                class _TC:
                    class function:
                        name = "emit"
                        arguments = '{"companies": []}'
                class _Msg:
                    tool_calls = [_TC()]
                class _Choice:
                    message = _Msg()
                class _Resp:
                    choices = [_Choice()]
                return _Resp()


def _call(router, **over):
    kwargs = dict(stage="map_companies", schema={"type": "object"},
                  static_prefix="RULES", dynamic_suffix="FACTS")
    kwargs.update(over)
    return router.call(**kwargs)


def test_default_router_selects_claude():
    router = StageRouter(claude_api_key="k", claude_client=_ClaudeOK())
    assert router.provider == "claude"
    assert router.quality == "authoritative"
    _call(router)
    assert router.quality == "authoritative"


def test_no_key_and_no_fallback_fails_closed_at_construction(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", False)
    with pytest.raises(StageRouterError):
        StageRouter(claude_api_key=None, groq_client=_GroqOK())


def test_claude_failure_with_fallback_disabled_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", False)
    router = StageRouter(claude_api_key="k", claude_client=_ClaudeFail(),
                         groq_client=_GroqOK())
    with pytest.raises(StageRouterError):
        _call(router)
    assert router.provider == "claude"  # never silently swapped


def test_claude_failure_with_explicit_fallback_marks_fallback(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)
    router = StageRouter(claude_api_key="k", claude_client=_ClaudeFail(),
                         groq_client=_GroqOK())
    result = _call(router)
    assert result == {"companies": []}
    assert router.provider == "groq"
    assert router.quality == "fallback"


def test_fallback_result_never_cached_as_authoritative(monkeypatch, db_session):
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)
    router = StageRouter(claude_api_key="k", claude_client=_ClaudeFail(),
                         groq_client=_GroqOK(), session=db_session)
    _call(router)
    from app.models import LLMStageCache
    assert db_session.query(LLMStageCache).count() == 0


def test_schema_failure_gets_one_compact_retry(monkeypatch):
    monkeypatch.setattr(settings, "claude_retry_backoff", 0.0)

    class _SchemaThenOK:
        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs["dynamic_suffix"])
            if len(self.calls) == 1:
                raise ClaudeJSONError("bad shape", kind="schema")
            return {"companies": []}

    client = _SchemaThenOK()
    router = StageRouter(claude_api_key="k", claude_client=client)
    result = _call(router, compact_suffix="COMPACT")
    assert result == {"companies": []}
    assert client.calls == ["FACTS", "COMPACT"]
    assert router.context_compacted is True


def test_transport_failure_gets_no_compact_retry(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", False)
    client = _ClaudeFail(kind="transport")
    router = StageRouter(claude_api_key="k", claude_client=client)
    with pytest.raises(StageRouterError):
        _call(router, compact_suffix="COMPACT")
    assert client.calls == 1  # SDK already retried transients; router does not


def test_auth_failure_trips_circuit_breaker(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", False)
    client = _ClaudeFail(kind="auth")
    router = StageRouter(claude_api_key="k", claude_client=client)
    with pytest.raises(StageRouterError):
        _call(router)
    with pytest.raises(StageRouterError):
        _call(router, dynamic_suffix="OTHER FACTS")
    assert client.calls == 1  # second call never touched the API
    assert router.claude_auth_failed is True


def test_gemini_is_not_importable_from_router():
    import app.analysis.impact_graph.router as router_module
    source_names = dir(router_module)
    assert "GeminiJSONClient" not in source_names
    assert "GeminiJSONError" not in source_names


def test_wrong_provider_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider_mode", "gemini")
    with pytest.raises(StageRouterError):
        StageRouter(claude_api_key="k")


def test_fingerprint_includes_provider_and_model():
    router = StageRouter(claude_api_key="k", claude_client=_ClaudeOK())
    fp = router._fingerprint("map_companies", {"type": "object"}, "RULES", "SEED")
    other = StageRouter(claude_api_key="k", claude_client=_ClaudeOK())
    other.provider = "groq"
    assert fp != other._fingerprint("map_companies", {"type": "object"}, "RULES", "SEED")
