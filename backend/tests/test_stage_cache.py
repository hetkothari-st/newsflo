"""Durable stage-result cache (retry-burn fix 2026-08-11): a retried
analysis must replay completed stage calls from the DB with zero provider
traffic; failures are never cached; input drift is a plain miss.

Provider-migration 2026-08-14: the fake provider is now an injected Claude
client (`claude_client=`) -- the cache contract itself is unchanged."""
import json
from datetime import timedelta

import pytest

from app.analysis.impact_graph.claude_json import ClaudeJSONError
from app.analysis.impact_graph.router import StageRouter, StageRouterError
from app.config import settings
from app.models import LLMStageCache, utcnow


class _CountingClaude:
    def __init__(self, fail_first=0):
        self.calls = 0
        self.fail_first = fail_first

    def generate(self, *, model, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ClaudeJSONError("boom", status_code=500, kind="transport")
        return {"ok": self.calls}


def _router(db, claude):
    return StageRouter(claude_api_key="k", claude_client=claude, groq_client=None,
                       article_id=7, session=db)


def _call(router, suffix="dynamic"):
    return router.call("initial_shocks", schema={"type": "object"},
                       static_prefix="static", dynamic_suffix=suffix)


def test_identical_retry_replays_from_cache_with_zero_calls(db_session):
    claude = _CountingClaude()
    first = _call(_router(db_session, claude))
    assert claude.calls == 1

    # Same call from a FRESH router (a retry / post-deploy re-run).
    second_claude = _CountingClaude()
    router2 = _router(db_session, second_claude)
    second = _call(router2)
    assert second == first
    assert second_claude.calls == 0  # zero provider traffic
    assert router2.stage_cache_hits == 1


def test_failures_are_never_cached(db_session):
    claude = _CountingClaude(fail_first=99)
    router = _router(db_session, claude)
    with pytest.raises(StageRouterError):
        _call(router)
    assert db_session.query(LLMStageCache).count() == 0


def test_input_drift_is_a_miss(db_session):
    claude = _CountingClaude()
    router = _router(db_session, claude)
    _call(router, suffix="dynamic-one")
    _call(router, suffix="dynamic-two")
    assert claude.calls == 2
    assert db_session.query(LLMStageCache).count() == 2


def test_expired_rows_ignored_and_swept(db_session):
    claude = _CountingClaude()
    router = _router(db_session, claude)
    _call(router)
    row = db_session.query(LLMStageCache).one()
    row.created_at = utcnow() - timedelta(days=10)
    db_session.commit()

    fresh_claude = _CountingClaude()
    router2 = _router(db_session, fresh_claude)
    _call(router2)
    assert fresh_claude.calls == 1  # expired row did not serve
    assert db_session.query(LLMStageCache).count() == 1  # old row swept on write


def test_no_session_means_no_caching_but_working_calls():
    claude = _CountingClaude()
    router = StageRouter(claude_api_key="k", claude_client=claude, groq_client=None)
    assert _call(router) == {"ok": 1}
    assert _call(router) == {"ok": 2}  # no cache without a session


# --- Task 15: cache poisoning fix -----------------------------------------

def test_cached_row_is_stored_as_a_quality_envelope(db_session):
    """Forward-safety format (corrective-v4 Task 15): a freshly written row
    carries its quality alongside the result, not just the bare result."""
    router = _router(db_session, _CountingClaude())
    _call(router)
    row = db_session.query(LLMStageCache).one()
    stored = json.loads(row.result_json)
    assert stored == {"__cache_envelope": 1, "quality": "authoritative", "result": {"ok": 1}}


def test_groq_by_configuration_router_never_populates_the_stage_cache(
        db_session, monkeypatch):
    """A router that starts on Groq -- which now requires the EXPLICIT
    LLM_FALLBACK_ALLOWED opt-in plus a missing Claude key -- is
    quality="fallback" from construction (Task 15), so its calls can never
    satisfy the absolute quality=="authoritative" cache-write guard:
    llm_stage_cache stays empty across a run that never touched Claude."""
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)

    class _GroqOK:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    from types import SimpleNamespace
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                        tool_calls=[SimpleNamespace(function=SimpleNamespace(
                            name="emit", arguments=json.dumps({"ok": True})))],
                    ))])

    router = StageRouter(claude_api_key=None, groq_client=_GroqOK(),
                         article_id=9, session=db_session)
    result = _call(router)
    assert result == {"ok": True}
    assert router.provider == "groq"
    assert router.quality == "fallback"
    assert db_session.query(LLMStageCache).count() == 0
