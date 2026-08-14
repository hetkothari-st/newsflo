"""Cache isolation: Gemini-era rows can never serve Claude; degraded/
malformed/fallback output never enters the authoritative cache
(provider-migration spec sections 8, 16.11-16.15)."""
import hashlib
import json

import pytest

from app.analysis.impact_graph.claude_json import ClaudeJSONError
from app.analysis.impact_graph.publication_gate import POLICY_VERSION
from app.analysis.impact_graph.router import StageRouter
from app.config import settings
from app.models import LLMStageCache


class _ClaudeOK:
    def __init__(self, payload=None):
        self.calls = 0
        self._payload = payload or {"ok": True}

    def generate(self, **kwargs):
        self.calls += 1
        return self._payload


def _legacy_gemini_fingerprint(stage, schema, static_prefix, seed):
    """Byte-reconstruct what the pre-migration fingerprint was: NO provider
    component, gemini model names. Proves structural non-collision."""
    from app.analysis.impact_graph.knowledge import KNOWLEDGE_REGISTRY_VERSION
    from app.analysis.impact_graph.prompts import IMPACT_PROMPT_VERSION
    from app.analysis.impact_graph.schemas import IMPACT_SCHEMA_VERSION
    payload = "\x1f".join([
        stage, "gemini-3.1-pro-preview", IMPACT_PROMPT_VERSION, IMPACT_SCHEMA_VERSION,
        KNOWLEDGE_REGISTRY_VERSION, static_prefix, seed,
        json.dumps(schema, sort_keys=True),
        str(int(settings.impact_engine_v4_strict)), POLICY_VERSION, "full",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_gemini_era_cache_row_never_matches_claude_fingerprint(db_session):
    schema = {"type": "object"}
    legacy_fp = _legacy_gemini_fingerprint("map_companies", schema, "RULES", "SEED")
    db_session.add(LLMStageCache(
        fingerprint=legacy_fp, stage="map_companies", article_id=1,
        model="gemini-3.1-pro-preview",
        result_json=json.dumps({"__cache_envelope": 1, "quality": "authoritative",
                                "result": {"poisoned": True}}),
    ))
    db_session.commit()
    client = _ClaudeOK({"fresh": True})
    router = StageRouter(claude_api_key="k", claude_client=client, session=db_session)
    result = router.call(stage="map_companies", schema=schema,
                         static_prefix="RULES", dynamic_suffix="SEED")
    assert result == {"fresh": True}
    assert client.calls == 1  # the legacy row was a miss, not a hit


def test_duplicate_claude_call_served_from_cache(db_session):
    client = _ClaudeOK({"v": 1})
    router = StageRouter(claude_api_key="k", claude_client=client, session=db_session)
    kwargs = dict(stage="verify", schema={"type": "object"},
                  static_prefix="R", dynamic_suffix="F")
    first = router.call(**kwargs)
    second = router.call(**kwargs)
    assert first == second == {"v": 1}
    assert client.calls == 1
    assert router.stage_cache_hits == 1


def test_malformed_response_is_never_cached(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", False)

    class _Malformed:
        def generate(self, **kwargs):
            raise ClaudeJSONError("no emit block", kind="schema")

    router = StageRouter(claude_api_key="k", claude_client=_Malformed(),
                         session=db_session)
    with pytest.raises(Exception):
        router.call(stage="verify", schema={}, static_prefix="R", dynamic_suffix="F")
    assert db_session.query(LLMStageCache).count() == 0


def test_compact_variant_result_not_cached(db_session, monkeypatch):
    monkeypatch.setattr(settings, "claude_retry_backoff", 0.0)

    class _SchemaThenOK:
        def __init__(self):
            self.n = 0

        def generate(self, **kwargs):
            self.n += 1
            if self.n == 1:
                raise ClaudeJSONError("bad", kind="schema")
            return {"ok": True}

    router = StageRouter(claude_api_key="k", claude_client=_SchemaThenOK(),
                         session=db_session)
    router.call(stage="verify", schema={}, static_prefix="R",
                dynamic_suffix="F", compact_suffix="C")
    assert db_session.query(LLMStageCache).count() == 0  # compact never cached
