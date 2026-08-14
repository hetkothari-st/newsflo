"""Corrective-v4 Task 12: full controlled taxonomy + structural
unreachability of the legacy section generator for gate-validated alerts +
a dedup-reuse policy that cannot resurrect ungated data.

Owner-locked invariant (verbatim): "gate_state/display_tier != NULL ->
legacy section generator must be structurally unreachable. Not merely 'we
prefer not to call it.'" This file pins that as executable behavior: the
structural gate reads AlertCompany.gate_state directly, never
settings.impact_engine_v4_strict, so a flag flip after gated rows were
persisted can never resurrect the legacy renderer for them."""
import json

import pytest

from app.config import settings
from app.market.ripple_layers import OTHER_LABEL, _TAXONOMY_LABELS, compute_ripple_layers
from app.models import (
    Alert, AlertCompany, AlertRippleLayer, Article, Company, MarketMove, utcnow,
)


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


_alert_seq = [0]


def _seed_alert(db):
    _alert_seq[0] += 1
    article = Article(source="s", provider="finnhub", url=f"https://ex.com/{id(db)}-{_alert_seq[0]}",
                      title="crude spikes", content="c", status="ALERTED")
    db.add(article)
    db.commit()
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    return alert


_ticker_seq = [0]


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
                 causal_parent_type="economic_node", parent_company_id=None,
                 materiality=0.7, excess=None, mechanism="crude-linked input costs"):
    if direction is None:
        direction = _DIRECTION_FROM_EFFECT.get(economic_effect, "bearish")
    _ticker_seq[0] += 1
    company = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
    db.add(company)
    db.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis",
        basis="direct_mention", economic_effect=economic_effect,
        display_tier=display_tier, gate_state=gate_state,
        causal_parent_type=causal_parent_type, causal_parent_id=causal_parent_id,
        parent_company_id=parent_company_id,
        materiality=materiality, causal_distance=1, mechanism=mechanism,
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


def test_gated_alert_never_renders_legacy_layers(db_session, strict_mode):
    """A persisted legacy AlertRippleLayer ("Winners — upstream") must never
    surface once any company on the alert carries a gate_state -- the
    legacy tier-1 generated-layer path is structurally unreachable, not
    merely skipped by preference."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price", excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    titles = [layer["title"] for layer in layers]
    assert "Winners — upstream" not in titles
    assert all(
        layer["relationship"].startswith("MECH:") or layer["relationship"] == "SECONDARY"
        for layer in layers
    )


def test_gated_alert_legacy_unreachable_even_flag_off(db_session, legacy_mode):
    """gate_state set + impact_engine_v4_strict False -- STILL strict
    sections. The reachability check is structural (reads gate_state), not
    modal (reads the flag): a flag flip must never resurrect the legacy
    renderer for rows that were already gated."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price", excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    titles = [layer["title"] for layer in layers]
    assert "Winners — upstream" not in titles
    assert any(layer["relationship"].startswith("MECH:") for layer in layers)


def test_ungated_alert_keeps_three_tier(db_session):
    """Every AlertCompany.gate_state NULL -> the locked 3-tier path renders
    unchanged (owner decision #1: all three tiers stay intact for
    legacy/ungated alerts)."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier=None, gate_state=None, excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    assert layers[0]["title"] == "Winners — upstream"  # tier-1 LLM layer used


def test_unknown_mechanism_uses_controlled_fallback_label(db_session, strict_mode):
    """A causal_parent_id with no taxonomy entry (a novel/LLM-authored node)
    renders with the controlled fallback label, never the raw node id."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="weird_llm_node_id", excess=1.0)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 1
    assert OTHER_LABEL in layers[0]["title"]
    assert "weird_llm_node_id" not in layers[0]["title"]


def test_all_42_mechanisms_have_labels():
    from app.analysis.impact_graph.knowledge import MECHANISMS
    from app.analysis.impact_graph.normalize import normalize_node_id

    missing = [m for m in MECHANISMS if normalize_node_id(m) not in _TAXONOMY_LABELS]
    assert missing == []


def test_heterogeneous_section_has_no_single_company_note(db_session, strict_mode):
    """Two companies land in the same section (same effect + causal_parent_id)
    but carry DIFFERENT mechanism strings -- the section note must be None,
    never one company's mechanism text presented as if it applied to both."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price",
                 mechanism="Upstream realization improves revenue economics.",
                 excess=1.0)
    _add_company(db_session, alert, "OIL.NS", "Oil India", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price",
                 mechanism="A completely different mechanism sentence.",
                 excess=0.8)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 1
    assert layers[0]["note"] is None
    assert {r["ticker"] for r in layers[0]["rows"]} == {"ONGC.NS", "OIL.NS"}


def test_sector_parent_section_gets_sector_label(db_session, strict_mode):
    """causal_parent_type == "sector" resolves through the legacy
    _SECTOR_LABELS map, not the mechanism taxonomy (I5, review round 2)."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "RELIANCE.NS", "Reliance", "oil_gas",
                 economic_effect="positive", causal_parent_type="sector",
                 causal_parent_id="oil_gas", excess=1.0)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 1
    assert "oil & gas" in layers[0]["title"]


def test_company_parent_section_gets_linked_to_label(db_session, strict_mode):
    """causal_parent_type == "company" resolves to "linked to <name>",
    looking the parent company's name up among the alert's own rows -- no
    extra DB query (I5, review round 2)."""
    alert = _seed_alert(db_session)
    parent, _ = _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                             economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "OILFIELD.NS", "Oilfield Services", "oil_gas",
                 economic_effect="positive", causal_parent_type="company",
                 causal_parent_id=parent.ticker, parent_company_id=parent.id,
                 excess=0.4)

    layers = compute_ripple_layers(db_session, alert, set())

    linked = next(layer for layer in layers if "linked to ONGC" in layer["title"])
    assert any(row["ticker"] == "OILFIELD.NS" for row in linked["rows"])


def test_two_distinct_unknown_parents_merge_into_one_other_section(db_session, strict_mode):
    """Two DIFFERENT unrecognized causal_parent_id values, same effect, both
    fall back to OTHER_LABEL -- they must render as ONE merged section, not
    two duplicate-titled ones (I5, review round 2)."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "AAA.NS", "AAA Co", "oil_gas",
                 economic_effect="positive", causal_parent_id="weird_node_a",
                 mechanism="mechanism a", excess=1.0)
    _add_company(db_session, alert, "BBB.NS", "BBB Co", "oil_gas",
                 economic_effect="positive", causal_parent_id="weird_node_b",
                 mechanism="mechanism b", excess=0.9)

    layers = compute_ripple_layers(db_session, alert, set())

    other_layers = [layer for layer in layers if OTHER_LABEL in layer["title"]]
    assert len(other_layers) == 1
    assert {r["ticker"] for r in other_layers[0]["rows"]} == {"AAA.NS", "BBB.NS"}
    # Merged sections are necessarily heterogeneous (two distinct real
    # mechanisms) -- no single-company note gets presented as if it
    # applied to both.
    assert other_layers[0]["note"] is None


def test_note_pin_single_member_and_identical_multi_member(db_session, strict_mode):
    """I6 (review round 2): a single-member section keeps its own mechanism
    as the note; a multi-member section where every mechanism string is
    IDENTICAL also keeps it -- only a heterogeneous section loses the
    note (already covered by test_heterogeneous_section_has_no_single_
    company_note above)."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "SOLO.NS", "Solo Co", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price",
                 mechanism="Solo mechanism text.", excess=1.0)

    layers = compute_ripple_layers(db_session, alert, set())
    assert len(layers) == 1
    assert layers[0]["note"] == "Solo mechanism text."

    twin_alert = _seed_alert(db_session)
    _add_company(db_session, twin_alert, "TWIN1.NS", "Twin One", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price",
                 mechanism="Shared mechanism text.", excess=1.0)
    _add_company(db_session, twin_alert, "TWIN2.NS", "Twin Two", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price",
                 mechanism="Shared mechanism text.", excess=0.5)

    twin_layers = compute_ripple_layers(db_session, twin_alert, set())
    assert len(twin_layers) == 1
    assert twin_layers[0]["note"] == "Shared mechanism text."
    assert {r["ticker"] for r in twin_layers[0]["rows"]} == {"TWIN1.NS", "TWIN2.NS"}


def test_legacy_secondary_spellings_stay_isolated_from_the_renamed_tiers(
        db_session, strict_mode):
    """Blueprint §32 scenario 16 -- LEGACY SECTION ISOLATION, stated in the
    RENAMED tier vocabulary (§3): `primary` / `secondary_ripple` /
    `macro_context`. A persisted row may still carry either dead secondary
    spelling ("secondary_deep_dive", "secondary"); those rows must keep
    rendering, and they must render as RIPPLE sections beside the canonical
    `secondary_ripple` -- never leaking into a MECH: section (which would
    launder a weaker claim into the primary frame) and never into a MACRO:
    one (which is reserved for `macro_context` alone).

    The membership rule under test is `is_secondary_tier`, the single place
    read-compat for the dead spellings lives; a consumer that regressed to a
    literal `== "secondary_ripple"` compare would drop the two legacy rows
    from the card back entirely, and this test would see a two-row ripple
    section instead of a four-row one.
    """
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "PRIM.NS", "Primary Co", "oil_gas",
                 economic_effect="negative", display_tier="primary",
                 causal_parent_id="crude_price", materiality=0.8)
    _add_company(db_session, alert, "RIPPLE.NS", "Ripple Co", "oil_gas",
                 economic_effect="negative", display_tier="secondary_ripple",
                 causal_parent_id="crude_price", materiality=0.7)
    _add_company(db_session, alert, "LEGACY1.NS", "Legacy Deep Dive Co", "oil_gas",
                 economic_effect="negative", display_tier="secondary_deep_dive",
                 causal_parent_id="crude_price", materiality=0.6)
    _add_company(db_session, alert, "LEGACY2.NS", "Legacy Secondary Co", "oil_gas",
                 economic_effect="negative", display_tier="secondary",
                 causal_parent_id="crude_price", materiality=0.5)
    _add_company(db_session, alert, "MACRO.NS", "Macro Context Co", "oil_gas",
                 economic_effect="negative", display_tier="macro_context",
                 causal_parent_id="crude_price", materiality=0.4)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    by_kind = {}
    for layer in layers:
        kind = layer["relationship"].split(":")[0]
        by_kind.setdefault(kind, set()).update(r["ticker"] for r in layer["rows"])

    assert by_kind["MECH"] == {"PRIM.NS"}
    assert by_kind["RIPPLE"] == {"RIPPLE.NS", "LEGACY1.NS", "LEGACY2.NS"}
    assert by_kind["MACRO"] == {"MACRO.NS"}
    # The dead "SECONDARY" single-bucket relationship is gone for good
    # (§12): legacy-spelled rows render under the mechanism taxonomy like
    # every other ripple row, not in an anonymous blob.
    assert "SECONDARY" not in by_kind


def test_dedup_reuse_cannot_bypass_gate(db_session, monkeypatch):
    """A prior LEGACY (gate_state NULL) alert must never be reused via the
    title-dedup shortcut -- that would silently copy field-less rows onto a
    new alert, exactly the gate bypass this task closes. A duplicate-titled
    article must take the fresh-analysis path instead."""
    import app.pipeline as pipeline_module
    from app.analysis.impact_graph.schemas import GraphCompany, ImpactGraphResult

    # Prior alert: analyzed, legacy shape -- no gate fields at all.
    prior_article = Article(source="test", url="https://example.com/dedup-prior",
                            title="Crude oil prices surge on Gulf tension",
                            content="c", status="ANALYZED")
    db_session.add(prior_article)
    db_session.commit()
    prior_alert = Alert(article_id=prior_article.id, category="oil_gas")
    db_session.add(prior_alert)
    db_session.commit()
    company = Company(ticker="ONGC.NS", name="ONGC", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=prior_alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct", display_tier=None, gate_state=None,
    ))
    db_session.commit()

    # A duplicate-titled article, categorized and ready to analyze.
    new_article = Article(source="test", url="https://example.com/dedup-new",
                          title="Crude oil prices surge on Gulf tension",
                          content="c", status="CATEGORIZED")
    db_session.add(new_article)
    db_session.commit()

    # The pre-fix bug let _find_reusable_alert hand this alert straight
    # back regardless of its gate shape; assert directly that the policy
    # gate now refuses it.
    assert pipeline_module._find_reusable_alert(db_session, new_article) is None

    called = {"n": 0}

    def fake_analyze(router, title, content, session=None, article_id=None):
        called["n"] += 1
        return ImpactGraphResult(category="oil_gas", companies=[GraphCompany(
            ticker="ONGC.NS", name="ONGC", direction="bearish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="fresh analysis mechanism",
            rationale="fresh call", reasons=["r1"],
        )])
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", fake_analyze)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)

    created = pipeline_module.process_new_articles(db_session, claude_client=object())

    assert created == 1
    assert called["n"] == 1  # the LLM WAS called -- no field-less copy
    new_alert = db_session.query(Alert).filter_by(article_id=new_article.id).one()
    new_ac = db_session.query(AlertCompany).filter_by(alert_id=new_alert.id).one()
    # The fresh analysis's own direction/mechanism, not the prior legacy
    # alert's (which never set a mechanism at all).
    assert new_ac.direction == "bearish"
