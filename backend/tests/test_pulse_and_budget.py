"""Pulse fast-lane, the paid-Gemini article budget, the llama salvage
repair, and the raw pulse-live feed."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.analysis.cascade import _salvage_rejected_company_call
from app.analysis.claude_client import CallRoutedClient
from app.config import settings
from app.filtering.relevance import filter_new_articles
from app.main import app
from app.models import Article, GeminiPaidUsage
from app.pipeline import backfill_pulse_images, process_new_articles, select_analysis_client
from app.routers.articles import get_db


def _article(db, provider="pulse_zerodha", url="https://ex.com/a", **kw):
    row = Article(source=provider, url=url, title=kw.pop("title", "RBI raises repo rate 25bps"),
                  content=kw.pop("content", "policy body"), provider=provider, status=kw.pop("status", "NEW"), **kw)
    db.add(row)
    db.commit()
    return row


# --- pulse fast-lane ---

def test_pulse_articles_skip_the_llm_relevance_gate(db_session):
    _article(db_session)
    exploding_client = object()  # any LLM call would AttributeError

    filter_new_articles(db_session, exploding_client)

    assert db_session.query(Article).one().status == "CATEGORIZED"


def test_pulse_articles_still_hit_deterministic_gates(db_session):
    _article(db_session, title="Form 8.3 - ABC PLC", content="dealing disclosure")

    filter_new_articles(db_session, object())

    assert db_session.query(Article).one().status == "FILTERED"


# --- paid budget ---

class _Chain:
    def __init__(self, name):
        self.name = name


def _routed():
    return CallRoutedClient(_Chain("paid"), _Chain("free"), frozenset({"extract_facts"}))


def test_budget_grants_paid_only_to_eligible_provider(db_session, monkeypatch):
    monkeypatch.setattr(settings, "gemini_paid_providers", "pulse_zerodha")
    routed = _routed()
    pulse = _article(db_session, url="https://ex.com/p")
    other = _article(db_session, provider="livemint", url="https://ex.com/l")

    assert select_analysis_client(db_session, pulse, routed) is routed
    assert select_analysis_client(db_session, other, routed) is routed._default


def test_budget_caps_daily_paid_articles(db_session, monkeypatch):
    monkeypatch.setattr(settings, "gemini_paid_providers", "pulse_zerodha")
    monkeypatch.setattr(settings, "gemini_paid_daily_article_budget", 2)
    routed = _routed()
    articles = [_article(db_session, url=f"https://ex.com/{i}") for i in range(3)]

    grants = [select_analysis_client(db_session, a, routed) for a in articles]

    assert grants[0] is routed and grants[1] is routed
    assert grants[2] is routed._default
    assert db_session.query(GeminiPaidUsage).count() == 2


def test_budget_is_retry_proof_per_article(db_session, monkeypatch):
    monkeypatch.setattr(settings, "gemini_paid_providers", "pulse_zerodha")
    monkeypatch.setattr(settings, "gemini_paid_daily_article_budget", 1)
    routed = _routed()
    article = _article(db_session)

    first = select_analysis_client(db_session, article, routed)
    retry = select_analysis_client(db_session, article, routed)

    assert first is routed and retry is routed
    assert db_session.query(GeminiPaidUsage).count() == 1


def test_plain_client_passes_through_untouched(db_session):
    plain = object()
    assert select_analysis_client(db_session, _article(db_session), plain) is plain


def test_stale_grant_from_a_previous_day_gets_no_gemini_at_all(db_session, monkeypatch):
    """The 5-article cap is per IST day, STRICTLY (user rule): an article
    granted on a previous day must not ride the paid key again today
    without counting against today's budget -- and since its unique usage
    row already exists, it cannot be re-granted, so it runs the free
    chain. No paid Gemini beyond today's five, ever."""
    from datetime import timedelta
    from app.models import utcnow

    monkeypatch.setattr(settings, "gemini_paid_providers", "pulse_zerodha")
    routed = _routed()
    routed.granted = CallRoutedClient(_Chain("paid"), _Chain("free+paid"), frozenset({"extract_facts"}))
    article = _article(db_session)
    db_session.add(GeminiPaidUsage(article_id=article.id, used_at=utcnow() - timedelta(days=2)))
    db_session.commit()

    assert select_analysis_client(db_session, article, routed) is routed._default
    assert db_session.query(GeminiPaidUsage).count() == 1  # no re-grant


def test_granted_article_gets_the_granted_router(db_session, monkeypatch):
    """A budget-granted pulse article must run its WHOLE cascade on the
    granted router (cheap stages carry the paid-Gemini backstop) -- with
    the plain router, a Groq daily-quota exhaustion kills the 5 paid
    articles at their first non-protected stage (production 2026-08-11)."""
    monkeypatch.setattr(settings, "gemini_paid_providers", "pulse_zerodha")
    routed = _routed()
    routed.granted = CallRoutedClient(_Chain("paid"), _Chain("free+paid"), frozenset({"extract_facts"}))
    pulse = _article(db_session, url="https://ex.com/granted")
    other = _article(db_session, provider="livemint", url="https://ex.com/plain")

    assert select_analysis_client(db_session, pulse, routed) is routed.granted
    # Retry keeps the grant -- and the granted router with it.
    assert select_analysis_client(db_session, pulse, routed) is routed.granted
    assert select_analysis_client(db_session, other, routed) is routed._default


def test_paid_eligible_articles_analyze_before_the_backlog(db_session, monkeypatch):
    """Pulse (paid-eligible) articles must jump the analysis queue: the
    pipeline runs newest-first, so during a provider quota storm dozens of
    newer, doomed-to-fail articles each burn retry time ahead of the five
    granted articles -- measured 2026-08-11: one pulse alert in six hours
    while 83 re-queued articles starved the rest."""
    import app.pipeline as pipeline_module
    from datetime import datetime, timezone
    from app.analysis.schemas import AnalysisOutput

    monkeypatch.setattr(settings, "gemini_paid_providers", "pulse_zerodha")
    old_pulse = _article(db_session, url="https://ex.com/pulse-old", status="CATEGORIZED",
                         title="older pulse story",
                         published_at=datetime(2026, 8, 11, 4, 30, tzinfo=timezone.utc))
    newer_other = _article(db_session, provider="livemint", url="https://ex.com/other-new",
                           status="CATEGORIZED", title="newer wire story",
                           published_at=datetime(2026, 8, 11, 6, 0, tzinfo=timezone.utc))

    analyzed_order = []

    def fake_analyze(client, title, content, session=None):
        analyzed_order.append(title)
        return AnalysisOutput(category="macro_policy", companies=[])

    monkeypatch.setattr(pipeline_module, "analyze_article", fake_analyze)
    monkeypatch.setattr(pipeline_module, "filter_new_articles", lambda *a, **k: None)
    monkeypatch.setattr(pipeline_module, "fetch_pending_full_text", lambda s: None)
    monkeypatch.setattr(pipeline_module, "backfill_pulse_images", lambda s: None)

    process_new_articles(db_session, claude_client=object())

    assert analyzed_order == ["older pulse story", "newer wire story"]


# --- llama salvage ---

def _bad_request(failed_generation):
    exc = Exception()
    exc.body = {"error": {"failed_generation": failed_generation}}
    return exc


def test_salvage_repairs_llama_violations():
    generation = "<function=record_sector_companies>" + json.dumps({
        "sector_companies": [{"sector": "oil_gas", "companies": [
            {"name": "Indian Oil Corporation Ltd.", "ticker": "IOC.NS", "direction": "bearish",
             "rationale": "import costs rise", "time_horizon": "Short-Term",
             "key_points": "tariffs -> costs"},  # string, no magnitudes
            {"name": "", "direction": "bearish"},  # unsalvageable -> dropped
        ]}],
    }) + "</function>"

    salvaged = _salvage_rejected_company_call(_bad_request(generation))

    companies = salvaged["sector_companies"][0]["companies"]
    assert len(companies) == 1
    assert companies[0]["key_points"] == ["tariffs -> costs"]
    assert companies[0]["magnitude_low"] == 1.0
    assert companies[0]["magnitude_high"] == 3.0


def test_salvage_returns_none_when_nothing_usable():
    assert _salvage_rejected_company_call(_bad_request("")) is None
    assert _salvage_rejected_company_call(_bad_request("not json")) is None


# --- pulse-live endpoint + image backfill ---

def test_pulse_live_returns_newest_first_without_llm(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    from datetime import datetime, timezone
    _article(db_session, url="https://ex.com/1", title="older",
             published_at=datetime(2026, 8, 10, 9, tzinfo=timezone.utc))
    _article(db_session, url="https://ex.com/2", title="newer",
             published_at=datetime(2026, 8, 10, 11, tzinfo=timezone.utc), image_url="")
    _article(db_session, provider="livemint", url="https://ex.com/other", title="not pulse")
    client = TestClient(app)

    body = client.get("/api/pulse-live").json()

    assert [item["title"] for item in body] == ["newer", "older"]
    assert body[0]["image_url"] is None  # "" sentinel serialized as null
    app.dependency_overrides.clear()


def test_backfill_pulse_images_marks_failures_with_sentinel(db_session, monkeypatch):
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "fetch_og_image", lambda url: None)
    _article(db_session)

    backfill_pulse_images(db_session)

    assert db_session.query(Article).one().image_url == ""
