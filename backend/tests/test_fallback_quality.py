"""Quality ladder + cache-poisoning + provider-identity tests (corrective-v4
Task 15). Every LLM interaction is a fake/mock at the router or client
boundary -- no network anywhere, matching the rest of the impact-graph test
suite."""
import json as _json

import pytest

from app.analysis.impact_graph.gemini_json import GeminiJSONError
from app.analysis.impact_graph.router import StageRouter, StageRouterError
from app.config import settings
from app.models import Article, LLMStageCache


# --- provider identity -------------------------------------------------

def test_groq_is_never_authoritative():
    """Non-protected mode is Groq from the first call, by explicit
    configuration -- it must never claim "authoritative" quality, not even
    for one call before something degrades it."""
    router = StageRouter(protected=False, gemini_api_key=None, groq_client=None)
    assert router.provider == "groq"
    assert router.quality == "fallback"


def test_protected_router_starts_authoritative():
    """Sanity check on the other side of the same fact: a protected router
    with a real Gemini client starts authoritative, never fallback."""
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None)
    assert router.provider == "gemini"
    assert router.quality == "authoritative"


# --- cache poisoning -----------------------------------------------------

class _FlakyGemini:
    def __init__(self, fail_times, status=500):
        self.fail_times = fail_times
        self.calls = []

    def generate(self, *, model, **kwargs):
        self.calls.append(model)
        if len(self.calls) <= self.fail_times:
            raise GeminiJSONError("boom", status_code=500)
        return {"ok": True}


def test_degraded_result_never_cached(db_session):
    """A result served by a lower ladder rung (here: the degraded-model
    rung) must never be written to llm_stage_cache -- an absolute quality
    check, not the old before/after delta comparison that this replaces."""
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None,
                         article_id=1, session=db_session)
    router._gemini = _FlakyGemini(fail_times=3)  # pro, pro-retry, compact all fail
    result = router.call("initial_shocks", schema={"type": "object"},
                         static_prefix="s", dynamic_suffix="d", compact_suffix="c")
    assert result == {"ok": True}
    assert router.quality == "degraded"
    assert db_session.query(LLMStageCache).count() == 0


def test_compact_context_result_never_cached_under_full_key(db_session):
    """Rung 3 (compact context, same primary model) succeeding keeps
    quality "authoritative" -- but it answered a DIFFERENT, cheaper
    question than the caller's full dynamic_suffix, so it must never be
    replayed as the full-context answer. This is the cache-poisoning bug
    this task fixes: only quality=="authoritative" AND served_variant==
    "full" may write back."""
    class _CompactOnly:
        def __init__(self):
            self.calls = []

        def generate(self, *, model, dynamic_suffix, **kwargs):
            self.calls.append(dynamic_suffix)
            if dynamic_suffix != "compact":
                raise GeminiJSONError("boom", status_code=500)
            return {"ok": True}

    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None,
                         article_id=1, session=db_session)
    router._gemini = _CompactOnly()
    result = router.call("initial_shocks", schema={"type": "object"},
                         static_prefix="s", dynamic_suffix="full",
                         compact_suffix="compact")
    assert result == {"ok": True}
    assert router.quality == "authoritative"          # same model -> not degraded
    assert router.context_compacted is True             # but the metric is honest
    assert db_session.query(LLMStageCache).count() == 0  # never cached under the full key


def test_full_context_authoritative_result_is_cached(db_session):
    """The one case that MUST still cache: primary model, first attempt,
    full dynamic_suffix, quality authoritative."""
    gemini = _FlakyGemini(fail_times=0)
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None,
                         article_id=1, session=db_session)
    router._gemini = gemini
    router.call("initial_shocks", schema={"type": "object"},
               static_prefix="s", dynamic_suffix="d")
    assert db_session.query(LLMStageCache).count() == 1


def test_cache_hit_propagates_stored_quality(db_session):
    """A hit must carry the STORED quality back onto the router -- the
    envelope written by _cache_put, read back by _cache_get. Only
    authoritative results are written going forward, but the envelope
    format is forward-safe for any quality, so this pins the propagation
    with a manually-seeded lower-quality row."""
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None,
                         article_id=1, session=db_session)
    fingerprint = router._fingerprint("initial_shocks", {"type": "object"}, "s", "d")
    db_session.add(LLMStageCache(
        fingerprint=fingerprint, stage="initial_shocks", article_id=1, model="x",
        result_json=_json.dumps({"__cache_envelope": 1, "quality": "degraded",
                                 "result": {"ok": True}}),
    ))
    db_session.commit()

    gemini = _FlakyGemini(fail_times=0)
    router._gemini = gemini
    result = router.call("initial_shocks", schema={"type": "object"},
                         static_prefix="s", dynamic_suffix="d")
    assert result == {"ok": True}
    assert gemini.calls == []          # zero provider traffic -- it was a hit
    assert router.quality == "degraded"  # propagated, not silently authoritative


def test_cache_hit_of_legacy_raw_row_treated_as_authoritative(db_session):
    """A row written before this shipped has no envelope -- raw result
    JSON. Read as legacy: the result replays, and quality reads as
    "authoritative" (the documented, deliberate legacy interpretation)."""
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None,
                         article_id=1, session=db_session)
    fingerprint = router._fingerprint("initial_shocks", {"type": "object"}, "s", "d")
    db_session.add(LLMStageCache(
        fingerprint=fingerprint, stage="initial_shocks", article_id=1, model="x",
        result_json=_json.dumps({"ok": True}),
    ))
    db_session.commit()

    result = router.call("initial_shocks", schema={"type": "object"},
                         static_prefix="s", dynamic_suffix="d")
    assert result == {"ok": True}
    assert router.quality == "authoritative"


def test_fingerprint_distinguishes_compact_context():
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None)
    full_fp = router._fingerprint("stage", {"type": "object"}, "static", "seed", variant="full")
    compact_fp = router._fingerprint("stage", {"type": "object"}, "static", "seed", variant="compact")
    assert full_fp != compact_fp


def test_fingerprint_includes_policy_version_and_strict_flag(monkeypatch):
    router = StageRouter(protected=True, gemini_api_key="k", groq_client=None)
    before = router._fingerprint("stage", {"type": "object"}, "static", "seed")
    monkeypatch.setattr(settings, "impact_engine_v4_strict",
                        not settings.impact_engine_v4_strict)
    after = router._fingerprint("stage", {"type": "object"}, "static", "seed")
    assert before != after


# --- malformed groq tool args --------------------------------------------

class _BadGroq:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                from types import SimpleNamespace
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    tool_calls=[SimpleNamespace(function=SimpleNamespace(
                        name="emit", arguments="{not valid json"))],
                ))])


def test_malformed_groq_tool_args_raise_stagerroutererror():
    router = StageRouter(protected=False, gemini_api_key=None, groq_client=_BadGroq())
    with pytest.raises(StageRouterError):
        router.call("initial_shocks", schema={"type": "object"},
                    static_prefix="s", dynamic_suffix="d")


# --- free-Gemini config wiring (construction only, no network) -----------

def test_free_gemini_key_reaches_router_config(monkeypatch, db_session):
    from app import pipeline

    monkeypatch.setattr(settings, "gemini_paid_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "free-key-123")
    monkeypatch.setattr(pipeline, "grant_paid_analysis", lambda session, article: False)

    article = Article(source="test", url="https://example.com/free-gemini",
                      title="T", content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()

    router = pipeline._build_v3_router(db_session, article, groq_client=None)
    assert router._gemini is not None
    assert router._gemini._api_key == "free-key-123"
    assert router.protected is False  # paid-key-gated, unaffected by the free key


def test_paid_gemini_key_still_preferred_when_both_present(monkeypatch, db_session):
    from app import pipeline

    monkeypatch.setattr(settings, "gemini_paid_api_key", "paid-key")
    monkeypatch.setattr(settings, "gemini_api_key", "free-key")
    monkeypatch.setattr(pipeline, "grant_paid_analysis", lambda session, article: True)

    article = Article(source="test", url="https://example.com/paid-gemini",
                      title="T", content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()

    router = pipeline._build_v3_router(db_session, article, groq_client=None)
    assert router._gemini._api_key == "paid-key"
    assert router.protected is True


# --- v3 result cache: versioned key + TTL --------------------------------

def _minimal_v3_result(**overrides):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    payload = dict(category="other", analysis_provider="gemini",
                   analysis_quality="authoritative")
    payload.update(overrides)
    return ImpactGraphResult(**payload)


def test_v3_result_cache_invalidates_on_policy_bump(db_session, monkeypatch):
    from app import pipeline
    import app.analysis.impact_graph.publication_gate as publication_gate

    article = Article(source="test", url="https://example.com/policy-bump",
                      title="T", content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()

    pipeline.store_v3_cache(db_session, article, _minimal_v3_result())
    db_session.commit()
    assert pipeline.get_cached_v3(db_session, article) is not None

    monkeypatch.setattr(publication_gate, "POLICY_VERSION", "pol-2")
    assert pipeline.get_cached_v3(db_session, article) is None


def test_v3_result_cache_expires_after_ttl(db_session, monkeypatch):
    from datetime import timedelta

    from app import pipeline
    from app.models import utcnow

    article = Article(source="test", url="https://example.com/ttl",
                      title="T", content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()

    pipeline.store_v3_cache(db_session, article, _minimal_v3_result())
    db_session.commit()
    assert pipeline.get_cached_v3(db_session, article) is not None

    from app.models import AnalysisCache
    row = db_session.query(AnalysisCache).one()
    row.created_at = utcnow() - timedelta(days=pipeline.V3_CACHE_TTL_DAYS + 1)
    db_session.commit()

    assert pipeline.get_cached_v3(db_session, article) is None
