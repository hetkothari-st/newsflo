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


def test_refusal_gets_no_compact_retry(monkeypatch):
    """A refusal is a decision about the CONTENT, not a malformed answer:
    re-asking with a shortened context is the same request minus facts, so
    the router must spend exactly one call and fail closed. Contrast with
    test_schema_failure_gets_one_compact_retry, where the compact rung is
    the whole point."""
    monkeypatch.setattr(settings, "llm_fallback_allowed", False)
    client = _ClaudeFail(kind="refusal")
    router = StageRouter(claude_api_key="k", claude_client=client)
    with pytest.raises(StageRouterError):
        _call(router, compact_suffix="COMPACT")
    assert client.calls == 1


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
    # `_primary` (the dispatch target) is the provider identity the cache is
    # keyed on -- NOT the mutable `.provider` honesty field. See
    # test_fallback_does_not_repoint_later_cache_keys_at_groq.
    other._primary = "groq"
    assert fp != other._fingerprint("map_companies", {"type": "object"}, "RULES", "SEED")


# --- mid-run fallback: the two security-critical traces ------------------

class _ClaudeFailThenOK:
    """Fails stage A, serves stage B -- the mid-run fallback sequence."""

    def __init__(self, fail_stages, kind="transport"):
        self._fail_stages = set(fail_stages)
        self._kind = kind
        self.calls = []

    def generate(self, **kwargs):
        stage = kwargs.get("stage")
        self.calls.append(stage)
        if stage in self._fail_stages:
            raise ClaudeJSONError("boom", kind=self._kind)
        return {"companies": [], "served_by": "claude"}


def test_later_claude_stage_after_a_fallback_is_never_cached(monkeypatch, db_session):
    """The run-level quality watermark is what protects the cache: once ANY
    stage fell back to Groq, quality is "fallback" for the whole run, so a
    LATER stage that Claude serves perfectly well still must not be written
    back (the absolute cache-put guard, not a per-call delta). Dispatch,
    meanwhile, keeps going to Claude -- one transient failure may not demote
    the rest of the run."""
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)
    from app.models import LLMStageCache

    client = _ClaudeFailThenOK(fail_stages={"stage_a"})
    router = StageRouter(claude_api_key="k", claude_client=client,
                         groq_client=_GroqOK(), session=db_session, article_id=3)

    # Stage A: claude fails -> groq serves, run is now quality="fallback".
    assert _call(router, stage="stage_a") == {"companies": []}
    assert router.provider == "groq"
    assert router.quality == "fallback"

    # Stage B: dispatched to CLAUDE (not stuck on groq) and served by it...
    result = _call(router, stage="stage_b", dynamic_suffix="OTHER FACTS")
    assert result == {"companies": [], "served_by": "claude"}
    assert client.calls == ["stage_a", "stage_b"]
    # ...but the run is still tainted, so nothing is cached and the
    # watermark never recovers to "authoritative".
    assert router.quality == "fallback"
    assert db_session.query(LLMStageCache).count() == 0


def test_fallback_does_not_repoint_later_cache_keys_at_groq(monkeypatch, db_session):
    """Regression (fix round 1): `_fingerprint`/`_fingerprint_model` key on
    the DISPATCH target, not the mutated `.provider`. Hashing the mutable
    field made every post-fallback stage look up a groq-keyed fingerprint --
    a guaranteed miss for the rest of the run and no replay on retry."""
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)

    client = _ClaudeFailThenOK(fail_stages={"stage_a"})
    router = StageRouter(claude_api_key="k", claude_client=client,
                         groq_client=_GroqOK(), session=db_session, article_id=4)
    before = router._fingerprint("stage_b", {"type": "object"}, "RULES", "SEED")

    _call(router, stage="stage_a")
    assert router.provider == "groq"  # honesty field flipped

    after = router._fingerprint("stage_b", {"type": "object"}, "RULES", "SEED")
    assert after == before  # ...but the lookup key did NOT move
    assert router._fingerprint_model("stage_b") == settings.claude_model
    assert router._fingerprint_model("stage_b") != settings.groq_aux_model


def test_auth_breaker_still_allows_the_explicit_groq_fallback(monkeypatch):
    """Breaker + opt-in: the second call must not touch the Claude API at
    all, yet must still be served by Groq and marked quality="fallback" --
    the breaker saves calls on a dead key, it does not disable the fallback
    the operator explicitly opted into."""
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)
    client = _ClaudeFail(kind="auth")
    router = StageRouter(claude_api_key="k", claude_client=client,
                         groq_client=_GroqOK())

    assert _call(router) == {"companies": []}  # groq served stage 1
    assert router.claude_auth_failed is True
    assert client.calls == 1

    result = _call(router, dynamic_suffix="OTHER FACTS")
    assert result == {"companies": []}
    assert client.calls == 1  # second call never touched the API
    assert router.provider == "groq"
    assert router.quality == "fallback"
