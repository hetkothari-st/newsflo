"""Materiality composite (spec §15, corrective-v4 Task 8): the gate must
never evaluate the naked LLM float. `materiality_grade` in
app.analysis.impact_graph.materiality is the single deterministic place
that caps it against exposure prior and evidence tier -- one test per rule
row, pinned exactly as the task brief states them."""
import pytest

from app.analysis.impact_graph.materiality import materiality_grade
from app.config import settings
from app.models import Company, CompanyExposure
from app.pipeline import _v3_entries


def test_none_materiality_is_unknown():
    assert materiality_grade(None, "HIGH", "A", False) == "UNKNOWN"


def test_high_float_with_no_cap_is_high():
    assert materiality_grade(0.7, "HIGH", "A", False) == "HIGH"


def test_medium_float_with_no_cap_is_medium():
    assert materiality_grade(0.5, "HIGH", "A", False) == "MEDIUM"


def test_low_float_with_no_cap_is_low():
    assert materiality_grade(0.2, "HIGH", "A", False) == "LOW"


def test_high_float_capped_by_low_exposure_to_medium():
    assert materiality_grade(0.7, "LOW", "A", False) == "MEDIUM"


def test_high_float_capped_by_none_exposure_to_medium():
    assert materiality_grade(0.7, "NONE", "A", False) == "MEDIUM"


def test_medium_float_capped_by_tier_e_to_low():
    assert materiality_grade(0.5, "HIGH", "E", False) == "LOW"


def test_high_float_with_exposure_level_none_prior_is_uncapped():
    """`exposure_level=None` means "no prior on file", NOT "verified NONE
    exposure" -- absence of a record must never be read as evidence of
    absence, so no cap applies and the float's own grade stands."""
    assert materiality_grade(0.7, None, "A", False) == "HIGH"


# --- boundary + combination coverage ---------------------------------------

def test_grade_thresholds_are_inclusive_at_the_low_end():
    assert materiality_grade(0.6, None, "A", False) == "HIGH"
    assert materiality_grade(0.35, None, "A", False) == "MEDIUM"
    assert materiality_grade(0.34999, None, "A", False) == "LOW"


def test_tier_e_cap_and_low_exposure_cap_compose_to_the_lowest():
    """Both caps active at once: LOW exposure caps to MEDIUM, tier E caps
    to LOW -- the tighter of the two caps must win, not the first applied."""
    assert materiality_grade(0.9, "LOW", "E", False) == "LOW"


def test_caps_never_raise_an_already_low_grade():
    assert materiality_grade(0.1, "HIGH", "A", False) == "LOW"


def test_shock_magnitude_known_is_accepted_but_not_yet_load_bearing():
    """Reserved for Task 10 -- passing True today must not change the
    result, since no producer of a real magnitude verdict exists yet."""
    assert materiality_grade(0.7, "HIGH", "A", True) == materiality_grade(0.7, "HIGH", "A", False)


# --- end-to-end pipeline wiring ---------------------------------------------

@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def test_archetype_candidate_with_low_exposure_caps_naked_high_float(db_session, strict_mode):
    """spec exact scenario: an archetype-discovered candidate (tier D) whose
    company has a LOW CompanyExposure on the mechanism's own dimension and
    an LLM materiality of 0.9 -- naked-float grading would call this HIGH;
    the composite must cap it to MEDIUM, and the entry must carry that
    capped grade, not the float's own claim."""
    from app.analysis.impact_graph.knowledge import MECHANISM_DIMENSIONS
    from app.analysis.impact_graph.schemas import GraphCompany, GraphEdge, ImpactGraphResult

    dimension = MECHANISM_DIMENSIONS["tyre_input_cost"]
    row = Company(name="Apollo Tyres", ticker="APOLLOTYRE.NS", sector="auto",
                  index_tier="NIFTY50", business_desc="Tyre manufacturer")
    db_session.add(row)
    db_session.commit()
    db_session.add(CompanyExposure(
        company_id=row.id, dimension=dimension, level="LOW", source="archetype:v1"))
    db_session.commit()

    edge = GraphEdge(
        parent_type="event", parent_id="rubber_supply_shock",
        child_type="economic_node", child_id="crude_linked_inputs",
        direction="bearish", economic_effect="negative",
        mechanism="rubber cost spike squeezes tyre input costs", causal_distance=1,
        impact_strength=0.7, confidence=0.8, materiality=0.6, time_horizon="Short-Term",
    )
    company = GraphCompany(
        ticker="APOLLOTYRE.NS", name="Apollo Tyres", direction="bearish",
        impact_strength=0.7, confidence=0.8, materiality=0.9, causal_distance=2,
        time_horizon="Short-Term", parent_type="economic_node", parent_id="crude_linked_inputs",
        mechanism="tyre input cost pressure from the rubber price spike",
        rationale="rubber-intensive tyre maker facing higher input costs",
        net_direction="bearish", economic_effect="negative", verified=True,
        discovery_source="archetype:tyre_input_cost",
    )
    result = ImpactGraphResult(
        category="commodity", event_type="rubber", facts="rubber prices spike",
        event_label="rubber supply shock", named_entities=[],
        companies=[company], edges=[edge], gaps=[], ranking=[],
        analysis_provider="gemini", analysis_quality="authoritative", metrics={},
    )

    entries = _v3_entries(db_session, result)

    assert len(entries) == 1
    assert entries[0]["materiality_grade"] == "MEDIUM"
    assert entries[0]["display_tier"] != "primary"


# --- the composite must be PERSISTED and SERVED, not re-derived ------------
# Final-review finding I3: the gate evaluated the composite, but nothing
# stored it. app.market.ripple_layers then re-derived a grade from
# AlertCompany.materiality -- the NAKED float -- so the exact candidate the
# test above proves the gate capped to MEDIUM was served to the reader as
# HIGH: a grade no gate decision ever accepted. Migration 0007 adds
# alert_companies.materiality_grade; these pin the whole path.

def _capped_archetype_result():
    """The scenario above, factored out: LLM materiality 0.9 (HIGH on the
    naked float) capped to MEDIUM by a LOW CompanyExposure on the
    mechanism's own dimension."""
    from app.analysis.impact_graph.schemas import GraphCompany, GraphEdge, ImpactGraphResult

    edge = GraphEdge(
        parent_type="event", parent_id="rubber_supply_shock",
        child_type="economic_node", child_id="crude_linked_inputs",
        direction="bearish", economic_effect="negative",
        mechanism="rubber cost spike squeezes tyre input costs", causal_distance=1,
        impact_strength=0.7, confidence=0.8, materiality=0.6, time_horizon="Short-Term",
    )
    company = GraphCompany(
        ticker="APOLLOTYRE.NS", name="Apollo Tyres", direction="bearish",
        impact_strength=0.7, confidence=0.8, materiality=0.9, causal_distance=2,
        time_horizon="Short-Term", parent_type="economic_node", parent_id="crude_linked_inputs",
        mechanism="tyre input cost pressure from the rubber price spike",
        rationale="rubber-intensive tyre maker facing higher input costs",
        net_direction="bearish", economic_effect="negative", verified=True,
        discovery_source="archetype:tyre_input_cost",
        # The verifier's real per-company verdict -- without it the
        # candidate fails COUNTERFACTUAL_VALID (GraphCompany defaults to
        # "", the fail-closed "verifier never reached this company"
        # state) and never reaches persistence at all, which is not the
        # scenario under test here.
        counterfactual="SUPPORTED",
    )
    return ImpactGraphResult(
        category="commodity", event_type="rubber", facts="rubber prices spike",
        event_label="rubber supply shock", named_entities=[],
        companies=[company], edges=[edge], gaps=[], ranking=[],
        analysis_provider="gemini", analysis_quality="authoritative", metrics={},
    )


def _seed_capped_company(db_session):
    from app.analysis.impact_graph.knowledge import MECHANISM_DIMENSIONS

    row = Company(name="Apollo Tyres", ticker="APOLLOTYRE.NS", sector="auto",
                  index_tier="NIFTY50", business_desc="Tyre manufacturer")
    db_session.add(row)
    db_session.commit()
    db_session.add(CompanyExposure(
        company_id=row.id, dimension=MECHANISM_DIMENSIONS["tyre_input_cost"],
        level="LOW", source="archetype:v1"))
    db_session.commit()
    return row


def test_composite_grade_is_persisted_on_the_alert_company_row(db_session, strict_mode):
    """The AlertCompany row must carry the SAME grade the gate evaluated --
    MEDIUM -- and NOT the naked float's HIGH. The composite is not
    recoverable from `materiality` alone, which is why the column exists."""
    from app.models import Alert, AlertCompany, Article
    from app.pipeline import _persist_alert, _v3_edges, _v3_entries

    _seed_capped_company(db_session)
    result = _capped_archetype_result()

    article = Article(source="s", url="https://ex.com/i3-persist", title="rubber spikes",
                      content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()
    entries = _v3_entries(db_session, result)
    assert entries[0]["materiality_grade"] == "MEDIUM"

    alert = _persist_alert(
        db_session, article, "commodity", entries, event_type="rubber",
        gaps=[], edges=_v3_edges(result), client=None, facts="rubber up",
        analysis_provider="gemini", analysis_quality="authoritative",
        ambiguous_entities=[])
    assert isinstance(alert, Alert)

    alert_company = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    assert alert_company.materiality == 0.9          # the raw float is still recorded
    assert alert_company.materiality_grade == "MEDIUM"  # ...the GRADE is the composite


def test_serialized_row_serves_the_composite_grade_not_the_float_grade(db_session, strict_mode):
    """End of the path: the reader must see MEDIUM. Before this fix
    ripple_layers re-derived `materiality_grade(alert_company.materiality)`
    -> HIGH from the 0.9 float, publishing a grade the gate had explicitly
    capped."""
    from app.market.ripple_layers import compute_ripple_layers
    from app.models import AlertCompany, Article
    from app.pipeline import _persist_alert, _v3_edges, _v3_entries

    _seed_capped_company(db_session)
    result = _capped_archetype_result()
    article = Article(source="s", url="https://ex.com/i3-serve", title="rubber spikes",
                      content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()
    alert = _persist_alert(
        db_session, article, "commodity", _v3_entries(db_session, result),
        event_type="rubber", gaps=[], edges=_v3_edges(result), client=None,
        facts="rubber up", analysis_provider="gemini",
        analysis_quality="authoritative", ambiguous_entities=[])

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)
    rows = [row for layer in layers for row in layer["rows"]]
    assert rows, "the capped candidate must still be served, just not as HIGH"
    served = next(row for row in rows if row["ticker"] == "APOLLOTYRE.NS")
    assert served["materiality_grade"] == "MEDIUM"
    assert served["materiality_grade"] != "HIGH"


def test_legacy_gated_row_without_a_stored_grade_falls_back_to_the_float(db_session, strict_mode):
    """Rows persisted BEFORE 0007 carry materiality_grade NULL. They keep
    being served exactly the naked-float grade they always were -- never
    blanked, never guessed at. A fallback, not the primary path."""
    from app.market.ripple_layers import compute_ripple_layers
    from app.models import Alert, AlertCompany, Article, utcnow

    row = Company(name="Legacy Co", ticker="LEGACY.NS", sector="auto",
                  index_tier="NIFTY50", business_desc="Maker of things")
    db_session.add(row)
    article = Article(source="s", url="https://ex.com/i3-legacy", title="t",
                      content="c", status="ALERTED")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="auto", created_at=utcnow())
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=row.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        display_tier="primary", gate_state="DISPLAY_ELIGIBLE",
        causal_parent_type="economic_node", causal_parent_id="crude_linked_inputs",
        causal_distance=2, mechanism="input cost pressure",
        economic_effect="negative", materiality=0.9,
        materiality_grade=None))  # pre-0007 shape
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)
    served = next(r for layer in layers for r in layer["rows"] if r["ticker"] == "LEGACY.NS")
    assert served["materiality_grade"] == "HIGH"
