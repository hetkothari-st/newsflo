"""Final blueprint §12-§15 / §27 (Task 5): the section engine.

Secondary rows are no longer swept into ONE generic "indirect exposure"
bucket -- they group on the SAME (effect, mechanism-taxonomy label) grain as
primary rows, so a reader sees *which* ripple they belong to. `macro_context`
rows get their own trailing sections and are never presented as a
company-specific claim. Section labels come from the mechanism registry
(T1 `section_label_for`), never from a raw node id, and section notes prefer
the registry's curated mechanism text over any single company's LLM
rationale.

The legacy (ungated) 3-tier generator is untouched -- see
test_sections_structural.py for that path.
"""
import pathlib

import pytest

from app.analysis.impact_graph.knowledge import MECHANISMS
from app.analysis.impact_graph.publication_gate import (
    TIER_MACRO_CONTEXT, TIER_PRIMARY, TIER_SECONDARY_RIPPLE,
)
from app.config import settings
from app.market.ripple_layers import (
    OTHER_LABEL, _assert_section_invariants, compute_ripple_layers,
)
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

# The generic single-bucket title this task DELETES. Kept as a literal here
# (and only here) so the repo-wide absence assertion has something to grep.
GENERIC_SECONDARY_TITLE = "Secondary — indirect exposure"


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _seed_alert(db):
    article = Article(source="s", provider="finnhub", url="https://ex.com/taxonomy",
                      title="crude spikes", content="c", status="ALERTED")
    db.add(article)
    db.commit()
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    return alert


# Blueprint §4 / migration 0008: `economic_effect` is authoritative and
# `direction` is DERIVED from it -- a gated row that contradicts itself is
# refused by the alert_companies_gated_consistency trigger, so fixtures
# derive rather than hardcode.
_DIRECTION_FROM_EFFECT = {"positive": "bullish", "negative": "bearish"}


def _add_company(db, alert, ticker, name, sector, *, economic_effect="negative",
                 display_tier=TIER_PRIMARY, causal_parent_type="economic_node",
                 causal_parent_id="crude_price", materiality=0.7, excess=None,
                 mechanism="an LLM-authored rationale sentence"):
    company = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
    db.add(company)
    db.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id,
        direction=_DIRECTION_FROM_EFFECT.get(economic_effect, "neutral"),
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis",
        basis="direct_mention", economic_effect=economic_effect,
        display_tier=display_tier, gate_state="DISPLAY_ELIGIBLE",
        causal_parent_type=causal_parent_type, causal_parent_id=causal_parent_id,
        materiality=materiality, causal_distance=2, mechanism=mechanism,
    )
    db.add(ac)
    db.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="ok" if excess is not None else "no_data",
        excess_move_pct=excess, raw_move_pct=excess, sector_move_pct=0.0,
        measured_at=utcnow(), category="commodity",
    ))
    db.commit()
    return company, ac


def _titles(layers):
    return [layer["title"] for layer in layers]


# --- (a) secondary rows group by mechanism taxonomy -----------------------

def test_two_secondary_parents_render_two_taxonomy_sections(db_session, strict_mode):
    """Two secondary_ripple rows whose causal parents map to DIFFERENT
    registry labels render as two distinct "Secondary — <label>" sections,
    each carrying the registry's curated mechanism text as its note -- not
    one flat "indirect exposure" blob."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ASIANPAINT.NS", "Asian Paints", "chemicals",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="paint_input_cost", materiality=0.4, excess=-0.4)
    _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="tyre_input_cost", materiality=0.35, excess=-0.2)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert len(layers) == 2, _titles(layers)
    assert set(_titles(layers)) == {
        "Secondary — Paints & chemicals", "Secondary — Tyres & rubber"}
    assert {layer["relationship"] for layer in layers} == {
        "RIPPLE:Paints & chemicals", "RIPPLE:Tyres & rubber"}
    assert GENERIC_SECONDARY_TITLE not in _titles(layers)

    by_title = {layer["title"]: layer for layer in layers}
    assert by_title["Secondary — Paints & chemicals"]["note"] == \
        MECHANISMS["paints_input_cost"]["mechanism"]
    assert by_title["Secondary — Tyres & rubber"]["note"] == \
        MECHANISMS["tyre_input_cost"]["mechanism"]
    # ... and never the company's own LLM sentence.
    assert all("an LLM-authored rationale sentence" != layer["note"] for layer in layers)


def test_generic_secondary_bucket_absent_repo_wide():
    """The single-bucket title is DELETED from the application source -- a
    regression that reintroduces it would silently flatten the taxonomy
    again. Comment lines are skipped (same convention as
    test_audit_bypasses' tier-literal scan): the deletion is recorded in
    ripple_layers' own prose so the next reader knows why the bucket is
    gone, and a comment emits nothing to the UI."""
    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if GENERIC_SECONDARY_TITLE in stripped:
                offenders.append(f"{path.relative_to(app_dir)}:{number}: {stripped}")
    assert offenders == [], offenders


def test_secondary_sections_follow_all_primary_sections(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="upstream_realization",
                 materiality=0.9, excess=1.0)
    _add_company(db_session, alert, "IOC.NS", "Indian Oil", "oil_gas",
                 economic_effect="negative", causal_parent_id="lubricant_base_oil_cost",
                 materiality=0.8, excess=-0.3)
    _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="tyre_input_cost", materiality=0.95, excess=-0.2)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    kinds = [layer["relationship"].split(":")[0] for layer in layers]
    assert kinds == ["MECH", "MECH", "RIPPLE"], _titles(layers)
    # A high-materiality SECONDARY row never outranks a primary section.
    assert layers[-1]["title"] == "Secondary — Tyres & rubber"


@pytest.mark.parametrize("legacy_tier", ["secondary_deep_dive", "secondary"])
def test_legacy_secondary_spellings_still_group_by_taxonomy(
        db_session, strict_mode, legacy_tier):
    """Pre-0008 rows persisted under a dead tier spelling render identically
    -- read-compat lives in the gate's is_secondary_tier, not in a literal
    compare here."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 display_tier=legacy_tier, economic_effect="negative",
                 causal_parent_id="road_freight_fuel_cost", materiality=0.3, excess=-0.2)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert _titles(layers) == ["Secondary — Logistics & freight"]
    assert layers[0]["relationship"] == "RIPPLE:Logistics & freight"


# --- (b) macro_context sections -------------------------------------------

def test_macro_context_row_renders_trailing_macro_section(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="upstream_realization",
                 materiality=0.9, excess=1.0)
    _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="tyre_input_cost", materiality=0.5, excess=-0.2)
    _add_company(db_session, alert, "HINDUNILVR.NS", "HUL", "fmcg",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="crude_inflation_pressure", materiality=0.99,
                 excess=-0.1)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert [layer["relationship"].split(":")[0] for layer in layers] == \
        ["MECH", "RIPPLE", "MACRO"]
    macro = layers[-1]
    assert macro["title"] == "Macro context — Imported inflation & consumer demand"
    assert macro["relationship"] == "MACRO:Imported inflation & consumer demand"
    assert macro["icon"] == "side"
    assert [row["ticker"] for row in macro["rows"]] == ["HINDUNILVR.NS"]


def test_macro_rows_with_distinct_labels_get_one_section_each(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "HINDUNILVR.NS", "HUL", "fmcg",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="crude_inflation_pressure", materiality=0.6,
                 excess=-0.1)
    _add_company(db_session, alert, "TITAN.NS", "Titan", "consumer_durables",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="discretionary_demand_squeeze", materiality=0.5,
                 excess=-0.2)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert _titles(layers) == [
        "Macro context — Imported inflation & consumer demand",
        "Macro context — Discretionary consumer demand",
    ]


# --- (c) invariants (§13) -------------------------------------------------

def _layer(title, relationship, rows, icon="lose"):
    return {"title": title, "relationship": relationship, "icon": icon,
            "note": None, "rows": rows}


def _row(ticker, effect="negative", tier=TIER_PRIMARY):
    return {"ticker": ticker, "economic_effect": effect, "display_tier": tier}


def test_invariant_ticker_in_two_sections_raises():
    layers = [
        _layer("Negative — Tyres & rubber", "MECH:Tyres & rubber", [_row("MRF.NS")]),
        _layer("Negative — Paints & chemicals", "MECH:Paints & chemicals",
               [_row("MRF.NS")]),
    ]
    with pytest.raises(AssertionError, match="MRF.NS"):
        _assert_section_invariants(layers)


def test_invariant_mixed_effects_in_one_mechanism_section_raises():
    layers = [
        _layer("Negative — Tyres & rubber", "MECH:Tyres & rubber",
               [_row("MRF.NS", "negative"), _row("CEAT.NS", "positive")]),
    ]
    with pytest.raises(AssertionError, match="effect"):
        _assert_section_invariants(layers)


def test_invariant_mixed_effect_section_may_hold_mixed_rows():
    layers = [
        _layer("Mixed — Oil marketing & refining", "MECH:Oil marketing & refining",
               [_row("BPCL.NS", "mixed"), _row("IOC.NS", "mixed")], icon="side"),
    ]
    _assert_section_invariants(layers)  # does not raise


def test_invariant_secondary_row_in_primary_section_raises():
    layers = [
        _layer("Negative — Tyres & rubber", "MECH:Tyres & rubber",
               [_row("MRF.NS", tier=TIER_SECONDARY_RIPPLE)]),
    ]
    with pytest.raises(AssertionError, match="tier"):
        _assert_section_invariants(layers)


def test_invariant_primary_row_in_ripple_section_raises():
    layers = [
        _layer("Secondary — Tyres & rubber", "RIPPLE:Tyres & rubber",
               [_row("MRF.NS", tier=TIER_PRIMARY)]),
    ]
    with pytest.raises(AssertionError, match="tier"):
        _assert_section_invariants(layers)


def test_invariant_non_macro_row_in_macro_section_raises():
    layers = [
        _layer("Macro context — Imported inflation & consumer demand",
               "MACRO:Imported inflation & consumer demand",
               [_row("HINDUNILVR.NS", tier=TIER_SECONDARY_RIPPLE)], icon="side"),
    ]
    with pytest.raises(AssertionError, match="tier"):
        _assert_section_invariants(layers)


def test_real_sections_satisfy_their_own_invariants(db_session, strict_mode):
    """The generator's own output must pass the checker -- otherwise the
    checker is decoration. _strict_sections calls it on every build, so this
    test failing means either the grouping or the checker is wrong."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="upstream_realization",
                 materiality=0.9, excess=1.0)
    _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="tyre_input_cost", materiality=0.5, excess=-0.2)
    _add_company(db_session, alert, "HINDUNILVR.NS", "HUL", "fmcg",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="crude_inflation_pressure", materiality=0.4,
                 excess=-0.1)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    _assert_section_invariants(layers)


# --- (d) unknown parents never leak a raw node id -------------------------

def test_unknown_secondary_parent_falls_back_to_other_label(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "WEIRD.NS", "Weird Co", "other",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="some_llm_invented_node_id", materiality=0.3,
                 excess=-0.1)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert _titles(layers) == [f"Secondary — {OTHER_LABEL}"]
    assert layers[0]["relationship"] == f"RIPPLE:{OTHER_LABEL}"
    assert "some_llm_invented_node_id" not in layers[0]["title"]


def test_unknown_macro_parent_falls_back_to_other_label(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "WEIRD.NS", "Weird Co", "other",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="another_invented_node", materiality=0.3, excess=-0.1)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert _titles(layers) == [f"Macro context — {OTHER_LABEL}"]
    assert "another_invented_node" not in layers[0]["title"]


def test_no_section_title_ever_contains_a_raw_node_id(db_session, strict_mode):
    """A raw engine/LLM node id is snake_case; a controlled label never is.
    An underscore anywhere in a title means a raw id leaked to the UI."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="upstream_realization",
                 materiality=0.9, excess=1.0)
    _add_company(db_session, alert, "WEIRD.NS", "Weird Co", "other",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="some_llm_invented_node_id", materiality=0.3,
                 excess=-0.1)
    _add_company(db_session, alert, "ODD.NS", "Odd Co", "other",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="yet_another_node", materiality=0.2, excess=-0.1)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert layers, "expected sections"
    assert all("_" not in layer["title"] for layer in layers), _titles(layers)


# --- (e) include_secondary=False (feed card-back contract) ----------------

def test_include_secondary_false_drops_ripple_and_macro(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="upstream_realization",
                 materiality=0.9, excess=1.0)
    _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                 display_tier=TIER_SECONDARY_RIPPLE, economic_effect="negative",
                 causal_parent_id="tyre_input_cost", materiality=0.5, excess=-0.2)
    _add_company(db_session, alert, "HINDUNILVR.NS", "HUL", "fmcg",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="crude_inflation_pressure", materiality=0.4,
                 excess=-0.1)

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=False)

    tickers = [row["ticker"] for layer in layers for row in layer["rows"]]
    assert tickers == ["ONGC.NS"]
    assert all(layer["relationship"].startswith("MECH:") for layer in layers)


def test_macro_only_alert_renders_nothing_without_secondary(db_session, strict_mode):
    """No primary row at all -- the card back's primary-only contract is an
    empty section list, never a macro section promoted into it."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "HINDUNILVR.NS", "HUL", "fmcg",
                 display_tier=TIER_MACRO_CONTEXT, economic_effect="negative",
                 causal_parent_id="crude_inflation_pressure", materiality=0.4,
                 excess=-0.1)

    assert compute_ripple_layers(db_session, alert, set(), include_secondary=False) == []


# --- (f) primary rows prefer the registry label ---------------------------

def test_primary_section_title_uses_registry_label(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="upstream_realization",
                 materiality=0.9, excess=1.0)

    layers = compute_ripple_layers(db_session, alert, set())

    assert _titles(layers) == ["Positive — Upstream oil producers"]
    assert layers[0]["relationship"] == "MECH:Upstream oil producers"
    assert layers[0]["note"] == MECHANISMS["upstream_realization"]["mechanism"]


def test_renormalized_registry_id_still_resolves(db_session, strict_mode):
    """`causal_parent_id` is persisted as normalize_node_id(mechanism_id),
    and 9 of the 42 registry ids change under that rewrite ("paints_input_cost"
    -> "paint_input_cost"). A naive MECHANISMS[parent_id] lookup misses every
    one of them and silently falls back to the legacy table."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ASIANPAINT.NS", "Asian Paints", "chemicals",
                 economic_effect="negative", causal_parent_id="paint_input_cost",
                 materiality=0.7, excess=-0.5)

    layers = compute_ripple_layers(db_session, alert, set())

    assert _titles(layers) == ["Negative — Paints & chemicals"]


def test_unknown_parent_note_falls_back_to_shared_llm_mechanism(db_session, strict_mode):
    """Registry text is PREFERRED, not required: an unknown parent whose
    members all share one LLM mechanism string keeps the existing §14 rule."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "WEIRD.NS", "Weird Co", "other",
                 economic_effect="negative", causal_parent_id="novel_node",
                 mechanism="Both members share this exact sentence.",
                 materiality=0.5, excess=-0.1)
    _add_company(db_session, alert, "ODD.NS", "Odd Co", "other",
                 economic_effect="negative", causal_parent_id="novel_node",
                 mechanism="Both members share this exact sentence.",
                 materiality=0.4, excess=-0.2)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 1
    assert layers[0]["note"] == "Both members share this exact sentence."


def test_sector_parent_still_resolves_through_sector_labels(db_session, strict_mode):
    """The registry deliberately does NOT own "sector"/"company" parents
    (T1's ownership split) -- those keep resolving locally."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "RELIANCE.NS", "Reliance", "oil_gas",
                 economic_effect="positive", causal_parent_type="sector",
                 causal_parent_id="oil_gas", materiality=0.7, excess=1.0)

    layers = compute_ripple_layers(db_session, alert, set())

    assert _titles(layers) == ["Positive — oil & gas"]
