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
    # Task 6: the deep-dive split keys on T5's section KIND prefix, so a
    # RIPPLE: section lands in "secondary" -- it used to fall into
    # "primary", because the old split tested `relationship != "SECONDARY"`
    # against a bucket T5 deleted.
    assert body["primary"] == []
    assert len(body["secondary"]) == 1
    assert body["secondary"][0]["relationship"].startswith("RIPPLE:")
    assert [r["ticker"] for r in body["secondary"][0]["rows"]] == ["BLUEDART.NS"]
    assert body["macro"] == []
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


# ===========================================================================
# Task 6 -- three-way deep-dive split, macro-context routing, event_scope,
# and the §24 pre-serve consistency gate
# ===========================================================================

def test_deep_dive_kinds_match_ripple_layers():
    """app.routers.feed_v2 restates T5's section-kind prefixes as literals
    (importing another module's privates into a request handler is worse).
    This is the pin that keeps the two from drifting: rename a kind in the
    producer and this fails immediately, instead of the deep dive silently
    filing every section under the wrong key."""
    from app.market import ripple_layers
    from app.routers import feed_v2

    assert feed_v2._KIND_PRIMARY == ripple_layers._KIND_PRIMARY
    assert feed_v2._KIND_RIPPLE == ripple_layers._KIND_RIPPLE
    assert feed_v2._KIND_MACRO == ripple_layers._KIND_MACRO


def test_deep_dive_splits_primary_ripple_and_macro(client, db_session, strict_mode):
    """Blueprint §7/§12: three tiers, three families, three keys. "primary"
    is the MECH: sections, "secondary" the (plural) RIPPLE: ones, and the
    new "macro" key the MACRO: family -- which exists precisely so broad
    economic context is never presented as a company-specific claim."""
    alert = _seed_alert(db_session, url="https://ex.com/three-way")
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 display_tier="secondary_ripple", causal_parent_id="road_freight_fuel_cost",
                 causal_distance=2, materiality=0.5, excess=-1.5)
    _add_company(db_session, alert, "HDFCBANK.NS", "HDFC Bank", "banking",
                 display_tier="macro_context", causal_parent_id="crude_inflation_pressure",
                 causal_distance=3, materiality=0.4, excess=-0.2)

    body = client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()

    assert [s["relationship"].split(":")[0] for s in body["primary"]] == ["MECH"]
    assert [s["relationship"].split(":")[0] for s in body["secondary"]] == ["RIPPLE"]
    assert [s["relationship"].split(":")[0] for s in body["macro"]] == ["MACRO"]
    assert [r["ticker"] for r in body["primary"][0]["rows"]] == ["ONGC.NS"]
    assert [r["ticker"] for r in body["secondary"][0]["rows"]] == ["BLUEDART.NS"]
    assert [r["ticker"] for r in body["macro"][0]["rows"]] == ["HDFCBANK.NS"]
    # Canonical tier spellings ride on every row of every family.
    assert body["primary"][0]["rows"][0]["publication_tier"] == "primary"
    assert body["secondary"][0]["rows"][0]["publication_tier"] == "secondary_ripple"
    assert body["macro"][0]["rows"][0]["publication_tier"] == "macro_context"


def test_macro_only_alert_absent_from_list_but_served_on_detail(client, db_session, strict_mode):
    """Blueprint §7 / ruling R1: macro context "must not become a company
    impact". An alert whose ONLY gate output is macro context has no
    company-specific claim to headline, so it never enters the feed LIST
    (and its macro row can never supply the peak ticker) -- but it is not
    hidden: detail and deep-dive serve it as context, with an honestly
    unavailable measurement."""
    alert = _seed_alert(db_session, url="https://ex.com/macro-only")
    _add_company(db_session, alert, "HDFCBANK.NS", "HDFC Bank", "banking",
                 display_tier="macro_context", causal_parent_id="crude_inflation_pressure",
                 causal_distance=3, materiality=0.4, excess=-6.0)

    assert client.get("/api/feed-v2").json() == []

    detail = client.get(f"/api/feed-v2/{alert.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["exposure"] is None            # neither a primary nor an indirect claim
    assert body["peak_ticker"] is None         # a macro row never headlines
    assert body["market_reaction"]["status"] == "unavailable"
    assert [r["ticker"] for layer in body["layers"] for r in layer["rows"]] == ["HDFCBANK.NS"]
    assert body["layers"][0]["relationship"].startswith("MACRO:")

    deep_dive = client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()
    assert deep_dive["primary"] == [] and deep_dive["secondary"] == []
    assert [r["ticker"] for r in deep_dive["macro"][0]["rows"]] == ["HDFCBANK.NS"]


def test_event_scope_multi_sector_when_macro_context_present(client, db_session, strict_mode):
    """§15's controlled descriptor: any macro-context row makes the story
    multi-sector by definition, and the label is identical on the list row,
    the detail payload and the deep dive."""
    alert = _seed_alert(db_session, url="https://ex.com/scope-macro")
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "HDFCBANK.NS", "HDFC Bank", "banking",
                 display_tier="macro_context", causal_parent_id="crude_inflation_pressure",
                 causal_distance=3, materiality=0.4, excess=-0.2)

    assert client.get("/api/feed-v2").json()[0]["event_scope"] == "multi_sector"
    assert client.get(f"/api/feed-v2/{alert.id}").json()["event_scope"] == "multi_sector"
    assert client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()["event_scope"] == "multi_sector"


def test_event_scope_multi_sector_across_two_taxonomies(client, db_session, strict_mode):
    """Two distinct mechanism taxonomies (crude-linked primaries + freight
    fuel costs) is the other half of §15's rule -- no macro row needed."""
    alert = _seed_alert(db_session, url="https://ex.com/scope-two-labels")
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 display_tier="secondary_ripple", causal_parent_id="road_freight_fuel_cost",
                 causal_distance=2, materiality=0.5, excess=-1.5)

    assert client.get("/api/feed-v2").json()[0]["event_scope"] == "multi_sector"


def test_event_scope_none_for_one_taxonomy(client, db_session, strict_mode):
    """Two companies, ONE mechanism -- a focused story, not a multi-sector
    one. None (not "single_sector"): the vocabulary has one member, and the
    frontend chooses the copy."""
    alert = _seed_alert(db_session, url="https://ex.com/scope-one-label")
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "OIL.NS", "Oil India", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=0.8)

    assert client.get("/api/feed-v2").json()[0]["event_scope"] is None


def test_event_scope_labels_match_the_rendered_section_labels(client, db_session, strict_mode):
    """`_event_scope` counts taxonomy labels WITHOUT assembling sections
    (the list route must stay one measurement pass per alert), so it
    resolves labels through ripple_layers' own tables. This pins that the
    two really do agree: the labels it counts are exactly the ones the
    rendered sections are titled with."""
    from app.routers.feed_v2 import _taxonomy_label

    alert = _seed_alert(db_session, url="https://ex.com/label-mirror")
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 display_tier="secondary_ripple", causal_parent_id="road_freight_fuel_cost",
                 causal_distance=2, materiality=0.5, excess=-1.5)
    _add_company(db_session, alert, "HDFCBANK.NS", "HDFC Bank", "banking",
                 display_tier="macro_context", causal_parent_id="crude_inflation_pressure",
                 causal_distance=3, materiality=0.4, excess=-0.2)

    body = client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()
    rendered = {
        section["title"].split(" — ")[1]
        for key in ("primary", "secondary", "macro") for section in body[key]
    }

    assert rendered == {_taxonomy_label(ac) for ac in alert.companies}
    assert len(rendered) == 3


def test_detail_drops_a_hand_corrupted_row_and_logs_loudly(
        client, db_session, strict_mode, caplog):
    """Blueprint §24, serving half: the consistency gate runs again over the
    SERIALIZED rows, and a row whose served claim contradicts itself is
    withheld -- loudly -- while the rest of the alert still serves.

    DOCUMENTED BYPASS. Migration 0008's `alert_companies_gated_consistency*`
    triggers make this row impossible to write through any normal path, so
    the fixture drops them, INSERTs the corrupted row with raw SQL, then
    re-installs them. That is the whole point of the test: the pre-serve
    check exists for rows that arrive from OUTSIDE the guarded paths -- a
    stale worker binary, a hand-edited row, a restore from a pre-0008
    backup -- and it must hold even when the DB-level backstop did not.
    """
    from sqlalchemy import text

    from app.models import emit_gated_row_triggers

    alert = _seed_alert(db_session, url="https://ex.com/corrupted-row")
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier="primary", economic_effect="positive", excess=1.0)
    corrupt = Company(name="Oil India", ticker="OIL.NS", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(corrupt)
    db_session.commit()

    db_session.execute(text("DROP TRIGGER IF EXISTS alert_companies_gated_consistency_insert"))
    db_session.execute(text("DROP TRIGGER IF EXISTS alert_companies_gated_consistency"))
    db_session.execute(
        text("""
            INSERT INTO alert_companies (
                alert_id, company_id, direction, magnitude_low, magnitude_high,
                rationale, confidence_score, time_horizon, basis, confidence,
                impact_level, economic_effect, display_tier, gate_state,
                causal_parent_type, causal_parent_id, causal_distance,
                materiality, mechanism
            ) VALUES (
                :alert_id, :company_id, 'bearish', 1.0, 3.0,
                'thesis', 50, 'Short-Term', 'direct_mention', 'llm_estimate',
                'direct', 'positive', 'primary', 'DISPLAY_ELIGIBLE',
                'economic_node', 'crude_price', 1,
                0.7, 'crude-linked upstream realization'
            )
        """),
        {"alert_id": alert.id, "company_id": corrupt.id},
    )
    db_session.commit()
    emit_gated_row_triggers(db_session.connection())   # backstop restored
    db_session.expire_all()

    with caplog.at_level("ERROR"):
        body = client.get(f"/api/feed-v2/{alert.id}").json()

    served = [r["ticker"] for layer in body["layers"] for r in layer["rows"]]
    assert served == ["ONGC.NS"]                       # the rest still serves
    assert "OIL.NS" not in served
    assert "PRE-SERVE CONSISTENCY VIOLATION" in caplog.text
    assert "DIRECTION_NOT_DERIVED" in caplog.text
    assert "OIL.NS" in caplog.text


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
