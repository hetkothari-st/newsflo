"""Entity resolution tri-state and business-model profile gate (spec §13,
corrective-v4 Task 7). Companion to test_v4_strict_gate_wiring.py -- pins
the specific behaviors Task 7 adds: a genuinely ambiguous entity link
rejects distinctly from an unknown one, and a company with no profile data
survives the BUSINESS_MODEL gate exactly when its evidence is structured
(tier A/B), never on a curated archetype prior alone."""
from datetime import date

import pytest

from app.analysis.impact_graph.publication_gate import CandidateInput, GateContext, evaluate_candidate
from app.companies.matching import aliases, matcher
from app.config import settings
from app.models import Company, CompanyDecisionRecord, SupplyLink
from app.pipeline import _gate_candidates, _persist_alert, _v3_edges, _v3_entries


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company_row(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas",
                 business_desc="Upstream oil and gas explorer"):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  business_desc=business_desc)
    db.add(row)
    db.commit()
    return row


def _graph_company(**overrides):
    from app.analysis.impact_graph.schemas import GraphCompany
    payload = dict(
        ticker="ONGC.NS", name="ONGC", direction="bullish",
        impact_strength=0.7, confidence=0.8, materiality=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node", parent_id="crude_price",
        mechanism="upstream crude realization: higher price lifts revenue per barrel",
        rationale="unhedged upstream producer with crude-linked realization",
        net_direction="bullish", economic_effect="positive", verified=True,
        # These tests exercise entity/business-model gates, not
        # COUNTERFACTUAL_VALID -- a verifier-delivered SUPPORTED keeps that
        # gate a non-factor (GraphCompany now defaults counterfactual="",
        # the "verifier never reached this company" fail-closed state).
        counterfactual="SUPPORTED",
    )
    payload.update(overrides)
    return GraphCompany(**payload)


def _graph_edge(**overrides):
    from app.analysis.impact_graph.schemas import GraphEdge
    payload = dict(
        parent_type="event", parent_id="crude_supply_shock",
        child_type="economic_node", child_id="crude_price",
        direction="bullish", economic_effect="positive",
        mechanism="supply disruption raises crude price", causal_distance=1,
        impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term",
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def _result(companies, edges=None, quality="authoritative", named_entities=None):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    return ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=named_entities or [],
        companies=companies, edges=edges if edges is not None else [_graph_edge()],
        gaps=[], ranking=[], analysis_provider="gemini", analysis_quality=quality,
        metrics={},
    )


# --- matcher tri-state (unit level) ----------------------------------------

def test_matcher_reports_ambiguous_alias_collision(db_session):
    """The matcher-level primitive Task 7 threads through the pipeline:
    two real, tradeable companies sharing one alias resolve to (None,
    ambiguous=True), not the same "absent" outcome a genuinely unknown name
    produces."""
    db_session.add_all([
        Company(ticker="TWA.NS", name="Twin Alpha Limited", sector="other",
               index_tier="OTHER", tradeability="NORMAL"),
        Company(ticker="TWB.NS", name="Twin Alpha Limited", sector="other",
               index_tier="OTHER", tradeability="NORMAL"),
    ])
    db_session.commit()
    aliases.rebuild_aliases(db_session)

    match, ambiguous = matcher.resolve_with_ambiguity(db_session, None, "Twin Alpha Limited")
    assert match is None
    assert ambiguous is True


# --- entity tri-state (gate wiring) -----------------------------------

def test_ambiguous_entity_rejected_distinctly_from_unresolved(db_session, strict_mode):
    """A GraphCompany the engine flagged entity_ambiguous must reject
    REJECT_ENTITY_AMBIGUOUS, not the generic REJECT_UNKNOWN_COMPANY --
    postmortems need to tell 'we don't know this company' apart from
    'we know two companies and can't tell which one'."""
    _company_row(db_session)
    entries = _v3_entries(db_session, _result([_graph_company(entity_ambiguous=True)]))

    assert entries[0]["gate_state"] == "REJECT_ENTITY_AMBIGUOUS"
    assert entries[0]["display_tier"] == "excluded"


def test_ambiguous_entity_decision_persists_in_record(db_session, strict_mode):
    """The rejection is not just returned -- it lands in the durable
    CompanyDecisionRecord the same way every other rejection does."""
    from app.models import Article

    _company_row(db_session)
    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="crude spikes", content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()
    result = _result([_graph_company(entity_ambiguous=True)])
    entries = _v3_entries(db_session, result)
    alert = _persist_alert(
        db_session, article, "commodity", entries, event_type="crude_oil",
        gaps=[], edges=_v3_edges(result), client=None,
        facts="crude up 5%", analysis_provider="gemini",
        analysis_quality=result.analysis_quality,
    )

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 1
    assert records[0].final_state == "REJECT_ENTITY_AMBIGUOUS"
    assert records[0].rejection_reason == "REJECT_ENTITY_AMBIGUOUS"


def test_unresolved_ticker_stays_unknown_company_not_ambiguous(db_session, strict_mode):
    """No Company row and no ambiguity flag: the honest state is 'we don't
    know this company', not 'ambiguous' -- the two must not be conflated.
    Tested at `_gate_candidates` directly: `_v3_entries` skips a company
    whose ticker never resolves to a row before it ever reaches the gate
    (pre-existing behavior, unrelated to Task 7), so REJECT_UNKNOWN_COMPANY
    itself is only observable one layer down."""
    _, _, _, decision = _gate_candidates(
        db_session, _result([_graph_company(ticker="NOPE.NS", name="Nope")]))[0]
    assert decision.final_state == "REJECT_UNKNOWN_COMPANY"


def test_resolved_ticker_with_no_ambiguity_flag_is_normal_case(db_session, strict_mode):
    """The overwhelming normal case (spec note: ticker came from an
    enum-locked candidate list) still resolves cleanly -- Task 7 must not
    regress the common path while adding the third state."""
    _company_row(db_session)
    entries = _v3_entries(db_session, _result([_graph_company()]))
    assert entries[0]["gate_state"] not in ("REJECT_ENTITY_AMBIGUOUS", "REJECT_UNKNOWN_COMPANY")


# --- business-model profile requirement --------------------------------

def test_profile_less_archetype_evidence_rejected(db_session, strict_mode):
    """A company with no business_desc and no fresh exposure row, backed
    only by a curated-archetype prior (tier D), cannot carry the claim."""
    _company_row(db_session, business_desc=None)
    entries = _v3_entries(db_session, _result(
        [_graph_company(discovery_source="archetype:tyre_input_cost")]))

    assert entries[0]["evidence_tier"] == "D"
    assert entries[0]["gate_state"] == "REJECT_INSUFFICIENT_EVIDENCE"
    assert "BUSINESS_MODEL_VALID" not in entries[0]["gates_passed"]


def test_profile_less_tier_a_evidence_passes_business_model_gate():
    """The canonical policy table's literal escape hatch: structured
    primary evidence (tier A/B) carries a claim even with zero
    business-profile data. Exercised at the gate-unit level -- classify_evidence
    (app.analysis.impact_graph.evidence) has no producer of tier A/B today
    (only C/D/E/SUBJECT/MARKET_OBS), so a pipeline-level fixture cannot
    reach this branch; the gate's own contract is what Task 7 must pin."""
    candidate = CandidateInput(
        ticker="ONGC.NS", entity_status="resolved", company_profile_present=False,
        mechanism="upstream crude realization: higher price lifts revenue per barrel",
        rationale="unhedged upstream producer with crude-linked realization",
        economic_effect="positive", causal_distance=1, materiality=0.7, confidence=0.8,
        independently_verified=True, verification_available=True,
        evidence_class="STRUCTURED_PRIMARY", evidence_tier="A",
        counterfactual="SUPPORTED", analysis_quality="authoritative",
        net_direction="bullish", trigger_shock_present=True,
    )
    decision = evaluate_candidate(candidate, GateContext())

    assert "BUSINESS_MODEL_VALID" in decision.gates_passed
    assert decision.final_state != "REJECT_INSUFFICIENT_EVIDENCE"


def test_profile_less_tier_c_relationship_evidence_still_insufficient(db_session, strict_mode):
    """Tier C (VERIFIED_RELATIONSHIP, via a real SupplyLink) is strong
    evidence for CAUSAL_PATH_VALID's d2/d3 relationship bar, but it is NOT
    one of the two tiers (A/B) the canonical policy table names as able to
    substitute for a missing business profile -- STRUCTURED_TIERS and
    RELATIONSHIP_TIERS are deliberately different sets. A profile-less
    company must still reject even with a real, sourced relationship
    behind it."""
    parent = _company_row(db_session, ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto")
    supplier = _company_row(db_session, ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                            sector="auto_components", business_desc=None)
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    d2 = _graph_company(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson", causal_distance=2, materiality=0.7,
        parent_type="company", parent_id="MARUTI.NS",
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM",
    )
    edges = [_graph_edge(child_type="company", child_id="MARUTI.NS")]
    entries = _v3_entries(db_session, _result([d2], edges=edges))

    assert entries[0]["evidence_tier"] == "C"
    assert entries[0]["gate_state"] == "REJECT_INSUFFICIENT_EVIDENCE"
    assert "BUSINESS_MODEL_VALID" not in entries[0]["gates_passed"]
