"""Corrective-v4 Task 16 (spec §52, owner decision, verbatim): "/api/feed-v2
-> PRIMARY only ... SECONDARY_DEEP_DIVE should be a separate explicit
retrieval path ... A good architecture is /api/feed-v2 -> PRIMARY only;
/api/feed-v2/{id}/deep-dive -> optional PRIMARY + SECONDARY_DEEP_DIVE +
rejected-summary." Pins: the main feed never headlines on a secondary/
deep-dive company, the new explicit deep-dive endpoint, and the new
authoritative per-row fields (mechanism/materiality_grade/confidence_band/
impact_type/expected_market_sensitivity/divergence)."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import Alert, AlertCompany, Article, Company, CompanyDecisionRecord, MarketMove, utcnow
from app.routers.articles import get_db


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _seed_alert(db, url="https://ex.com/primary-only"):
    article = Article(source="s", provider="finnhub", url=url,
                      title="Crude oil spikes on supply shock", content="c",
                      status="ALERTED")
    db.add(article)
    db.commit()
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    return alert


# Blueprint Sec4 / migration 0008: `economic_effect` is the ONE
# authoritative field and `direction` is DERIVED from it. A GATED fixture
# row whose direction contradicts its own effect is now refused outright by
# the alert_companies_gated_consistency trigger (app/models.py + 0008) --
# the same DB-level guard that would have caught the live OIL.NS row -- so
# these fixtures derive the direction instead of hardcoding one that the
# callers' `economic_effect="positive"` overrides then contradict.
_DIRECTION_FROM_EFFECT = {"positive": "bullish", "negative": "bearish"}


def _add_company(db, alert, ticker, name, sector, *, direction=None,
                 economic_effect="negative", display_tier="primary",
                 gate_state="DISPLAY_ELIGIBLE", causal_parent_id="crude_price",
                 causal_parent_type="economic_node", materiality=0.7,
                 excess=None, mechanism="crude-linked input costs",
                 causal_distance=1, confidence_band="MODERATE",
                 expected_market_sensitivity="HIGH"):
    if direction is None:
        direction = _DIRECTION_FROM_EFFECT.get(economic_effect, "bearish")
    company = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
    db.add(company)
    db.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis",
        basis="direct_mention", economic_effect=economic_effect,
        display_tier=display_tier, gate_state=gate_state,
        causal_parent_type=causal_parent_type, causal_parent_id=causal_parent_id,
        materiality=materiality, causal_distance=causal_distance, mechanism=mechanism,
        confidence_band=confidence_band, expected_market_sensitivity=expected_market_sensitivity,
    )
    db.add(ac)
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="ok" if excess is not None else "no_data",
        excess_move_pct=excess, raw_move_pct=excess, sector_move_pct=0.0,
        measured_at=utcnow(), category="commodity",
    )
    db.add(move)
    db.commit()
    return company, ac


def test_secondary_only_alert_listed_as_indirect_only(client, db_session, strict_mode):
    """Owner decision 2026-08-14 (supersedes the Task 16 hide-the-rest rule
    for the no-primary case): a gated alert with zero PRIMARY but >=1
    secondary/deep-dive company appears in the feed and detail, headlined
    from its secondary movers and explicitly labeled
    exposure="indirect_only". The deep-dive surface is unchanged."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 display_tier="secondary_deep_dive", materiality=0.3, excess=-0.5)

    rows = client.get("/api/feed-v2").json()
    assert [r["id"] for r in rows] == [alert.id]
    assert rows[0]["exposure"] == "indirect_only"
    assert rows[0]["peak_ticker"] == "BLUEDART.NS"

    detail = client.get(f"/api/feed-v2/{alert.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["exposure"] == "indirect_only"
    # The card back for a no-primary alert IS the secondary section.
    tickers_on_card = [r["ticker"] for layer in body["layers"] for r in layer["rows"]]
    assert tickers_on_card == ["BLUEDART.NS"]

    response = client.get(f"/api/feed-v2/{alert.id}/deep-dive")

    assert response.status_code == 200
    body = response.json()
    assert body["primary"] == []
    assert len(body["secondary"]) == 1
    assert [r["ticker"] for r in body["secondary"][0]["rows"]] == ["BLUEDART.NS"]
    assert body["rejected_summary"] == []


def test_excluded_only_alert_still_absent_from_list(client, db_session, strict_mode):
    """The 2026-08-14 decision widens the feed to secondary tiers ONLY --
    excluded-tier rows still surface nowhere."""
    alert = _seed_alert(db_session, url="https://ex.com/excluded-only")
    _add_company(db_session, alert, "NOISE.NS", "Noise Co", "oil_gas",
                 display_tier="excluded", gate_state="REJECT_GENERIC_EXPOSURE",
                 materiality=0.2, excess=-4.0)

    assert client.get("/api/feed-v2").json() == []
    assert client.get(f"/api/feed-v2/{alert.id}").status_code == 404


def test_peak_ticker_ignores_bigger_secondary_mover(client, db_session, strict_mode):
    """Two companies on one alert: PRIMARY (ONGC, +1.0% excess) and
    SECONDARY_DEEP_DIVE (Blue Dart, -9.0% excess -- a far bigger move).
    Secondary/rejected companies can never headline (spec §52) -- the peak
    must be the primary company's, not the numerically larger secondary
    move."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 display_tier="secondary_deep_dive", materiality=0.3, excess=-9.0)

    row = client.get("/api/feed-v2").json()[0]
    assert row["peak_ticker"] == "ONGC.NS"
    assert row["excess_move_pct"] == 1.0
    assert row["exposure"] == "primary"  # primary present -> never indirect_only

    detail = client.get(f"/api/feed-v2/{alert.id}").json()
    assert detail["peak_ticker"] == "ONGC.NS"
    # The card back itself is PRIMARY only too -- no secondary section (and
    # no BLUEDART row) leaks into the normal detail response.
    tickers_on_card = [r["ticker"] for layer in detail["layers"] for r in layer["rows"]]
    assert tickers_on_card == ["ONGC.NS"]


def test_new_fields_present_including_divergence_for_apollo_case(client, db_session, strict_mode):
    """Apollo case (spec §62): negative fundamental thesis + positive
    observed reaction -- the divergence template fires, and every new
    authoritative field (Task 16) is on the row."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "APOLLOTYRE.NS", "Apollo Tyres", "auto",
                 display_tier="primary", economic_effect="negative",
                 causal_parent_id="tyre_input_cost", excess=+2.1,
                 mechanism="Crude-linked rubber costs squeeze tyre margins.",
                 confidence_band="HIGH", expected_market_sensitivity="MEDIUM")

    detail = client.get(f"/api/feed-v2/{alert.id}").json()
    row = detail["layers"][0]["rows"][0]

    assert row["ticker"] == "APOLLOTYRE.NS"
    assert row["mechanism"] == "Crude-linked rubber costs squeeze tyre margins."
    assert row["materiality_grade"] == "HIGH"  # materiality=0.7 >= 0.6 (publication_gate thresholds)
    assert row["confidence_band"] == "HIGH"
    assert row["impact_type"] == "direct"  # causal_distance == 1
    assert row["expected_market_sensitivity"] == "MEDIUM"
    assert row["reaction_direction"] == "positive"
    assert row["divergence"] == (
        "Stock is currently moving up despite a negative fundamental exposure thesis."
    )


def test_impact_type_is_indirect_for_causal_distance_two(client, db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive",
                 causal_distance=2, excess=1.0)

    detail = client.get(f"/api/feed-v2/{alert.id}").json()
    row = detail["layers"][0]["rows"][0]

    assert row["impact_type"] == "indirect"


def test_rejected_summary_is_machine_readable(client, db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    db_session.add(CompanyDecisionRecord(
        alert_id=alert.id, ticker="NOISE.NS", final_state="REJECT_GENERIC_EXPOSURE",
        display_tier="excluded", rejection_reason="REJECT_GENERIC_EXPOSURE",
        materiality_grade="LOW",
    ))
    # A row that DID clear the gate must never appear in rejected_summary --
    # only final_state starting with "REJECT_" counts.
    db_session.add(CompanyDecisionRecord(
        alert_id=alert.id, ticker="ONGC.NS", final_state="DISPLAY_ELIGIBLE",
        display_tier="primary", rejection_reason=None, materiality_grade="HIGH",
    ))
    db_session.commit()

    body = client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()

    assert body["rejected_summary"] == [
        {"ticker": "NOISE.NS", "rejection_reason": "REJECT_GENERIC_EXPOSURE", "materiality_grade": "LOW"},
    ]


def test_deep_dive_404s_on_ungated_alert(client, db_session):
    """A legacy (pre-gate) alert has no tier/rejection data to show on the
    gated-analysis-only deep-dive surface -- 404, not an empty shell."""
    article = Article(source="s", url="https://ex.com/ungated-deep-dive",
                      title="Legacy alert, no gate data", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    company = Company(ticker="LEGACY.NS", name="Legacy Co", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.commit()

    response = client.get(f"/api/feed-v2/{alert.id}/deep-dive")

    assert response.status_code == 404


def test_deep_dive_404s_on_unknown_alert(client, db_session):
    assert client.get("/api/feed-v2/999999/deep-dive").status_code == 404
