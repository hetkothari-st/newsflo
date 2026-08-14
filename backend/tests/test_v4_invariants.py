"""THE AUTHORITATIVE INVARIANT INDEX (spec 2026-08-12 Appendix B,
corrective-v4 Task 19).

Exactly one test (or one explicitly named delegation) per INV-001..INV-020.
Every test here carries REAL assertions -- this file is the acceptance
backbone, not a table of contents. Where a phase suite already pins an
invariant behaviorally, this file re-pins it against the CURRENT vocabulary
and policy rather than delegating silently, so a policy change that breaks
an invariant fails HERE, by invariant id, and a postmortem never has to
guess which file owned it.

Reading order: each test's name starts with its invariant id, and its
docstring states the invariant in one line before asserting it.

Companion suites (deeper, per-phase coverage -- not substitutes):
  test_publication_gate.py         gate policy table, per-check depth
  test_v4_strict_gate_wiring.py    gate <-> pipeline wiring
  test_v4_strict_truth_model.py    measurement/fundamental separation
  test_v4_strict_sections.py       section assembly + refine wiring
  test_sections_structural.py      legacy-generator unreachability
  test_feed_primary_only.py        PRIMARY-only feed contract
  test_decision_record_audit.py    decision-record completeness
  test_evidence_records.py         evidence classification + payloads
  test_audit_bypasses.py           one test per audited bypass (Task 20)
"""
import json

import pytest

from app.analysis.impact_graph.publication_gate import (
    GATE_SEQUENCE,
    REJECTION_STATES,
    CandidateInput,
    GateContext,
    evaluate_candidate,
    finalize_alert_decisions,
)
from app.config import settings
from app.models import (
    Alert, AlertCompany, AlertRippleLayer, Article, Company, CompanyDecisionRecord,
    CompanyNodeExposure, EvidenceRecord, MarketMove, TimelineEffect, utcnow,
)

GATE_NAMES = [name for name, _ in GATE_SEQUENCE]


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


# --- shared fixtures -------------------------------------------------------

_seq = [0]


def _next() -> int:
    _seq[0] += 1
    return _seq[0]


def _candidate(**overrides) -> CandidateInput:
    """A fully-grounded d1 candidate that clears every gate as PRIMARY.
    Every gate-level test below overrides exactly the field under test, so
    a failure names one cause, never a fixture that drifted."""
    payload = dict(
        ticker="ONGC.NS", entity_status="resolved", company_profile_present=True,
        mechanism="crude realization: higher crude price lifts upstream revenue per barrel",
        rationale="upstream producer with unhedged crude realization exposure",
        economic_effect="positive", causal_distance=1, materiality=0.7,
        confidence=0.8, independently_verified=True, verification_available=True,
        evidence_class="VERIFIED_RELATIONSHIP", evidence_tier="C",
        counterfactual="SUPPORTED", analysis_quality="authoritative",
        positive_channels=["crude realization"], net_direction="bullish",
        trigger_shock_present=True,
    )
    payload.update(overrides)
    return CandidateInput(**payload)


def _company_row(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas",
                 business_desc="Upstream oil and gas explorer", verified_node=None,
                 provenance_type=None):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  market="INDIA", tradeability="NORMAL", market_cap=1e12,
                  business_desc=business_desc)
    db.add(row)
    db.commit()
    if verified_node is not None:
        db.add(CompanyNodeExposure(
            company_id=row.id, node_key=verified_node, exposure_exists=1,
            strength=0.8, mechanism="verified exposure", verified_at=utcnow(),
            provenance_type=provenance_type,
            source_url="https://crisil.example/rationale" if provenance_type else None,
        ))
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
        impact_strength=0.8, confidence=0.9, materiality=0.7, time_horizon="Short-Term",
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def _result(companies, edges=None, quality="authoritative", named_entities=None,
            ambiguous_entities=None):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    return ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=named_entities or [],
        companies=companies, edges=edges if edges is not None else [_graph_edge()],
        gaps=[], ranking=[], analysis_provider="gemini", analysis_quality=quality,
        metrics={}, ambiguous_entities=ambiguous_entities or [],
    )


def _article(db, title="crude spikes"):
    article = Article(source="s", provider="finnhub",
                      url=f"https://ex.com/inv-{_next()}", title=title,
                      content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    return article


def _persist(db, result, article=None):
    """Run the real persistence boundary: gate -> entries -> Alert rows +
    decision records."""
    from app.pipeline import _persist_alert, _v3_edges, _v3_entries

    article = article if article is not None else _article(db)
    entries = _v3_entries(db, result)
    return _persist_alert(
        db, article, "commodity", entries, event_type="crude_oil",
        gaps=[], edges=_v3_edges(result), client=None, facts="crude up 5%",
        analysis_provider=result.analysis_provider,
        analysis_quality=result.analysis_quality,
        ambiguous_entities=result.ambiguous_entities,
    )


def _seed_alert(db, category="commodity"):
    article = _article(db)
    article.status = "ALERTED"
    alert = Alert(article_id=article.id, category=category, event_type="crude_oil")
    db.add(alert)
    db.commit()
    return alert


def _add_alert_company(db, alert, ticker, name, sector="oil_gas", *, direction="bullish",
                       economic_effect="positive", display_tier="primary",
                       gate_state="DISPLAY_ELIGIBLE", causal_parent_type="economic_node",
                       causal_parent_id="crude_price", materiality=0.7, excess=None,
                       mechanism="crude-linked input costs", rationale="fundamental thesis",
                       causal_distance=1, with_move=True):
    company = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
    db.add(company)
    db.commit()
    alert_company = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale=rationale,
        key_points_json=json.dumps(["point"]), basis="direct_mention",
        economic_effect=economic_effect, display_tier=display_tier,
        gate_state=gate_state, causal_parent_type=causal_parent_type,
        causal_parent_id=causal_parent_id, materiality=materiality,
        causal_distance=causal_distance, mechanism=mechanism,
    )
    db.add(alert_company)
    if with_move:
        db.add(MarketMove(
            alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
            measurement_status="ok" if excess is not None else "no_data",
            excess_move_pct=excess, raw_move_pct=excess, sector_move_pct=0.0,
            measured_at=utcnow(), category="commodity", bar_complete=1,
        ))
    db.commit()
    return company, alert_company


# ===========================================================================
# INV-001: the measured market move never overwrites the fundamental call
# ===========================================================================

def test_inv001_measurement_never_overwrites_the_fundamental_call(
        db_session, monkeypatch, strict_mode):
    """INV-001: measurement records a SECOND truth; it never edits the
    first. A bullish fundamental call measured at -2.5% keeps its
    direction, rationale, key points and economic_effect -- both on the
    initial measurement pass and on the later remeasure pass."""
    import app.pipeline as pipeline_module
    from app.pipeline import measure_and_reconcile_alert_companies, remeasure_no_data_moves

    alert = _seed_alert(db_session)
    company, alert_company = _add_alert_company(
        db_session, alert, "RELIANCE.NS", "Reliance Industries",
        direction="bullish", economic_effect="positive", with_move=False)

    def _ok_move(session, company_row, **kwargs):
        return MarketMove(
            company_id=company_row.id, benchmark_ticker="^CNXENERGY",
            raw_move_pct=-2.0, sector_move_pct=0.5, excess_move_pct=-2.5,
            measured_at=utcnow(), measurement_status="ok")

    monkeypatch.setattr(pipeline_module, "measure_company_move", _ok_move)

    moves = measure_and_reconcile_alert_companies(db_session, alert.id, [alert_company])

    assert moves[0].excess_move_pct == -2.5          # the move IS recorded
    assert alert_company.direction == "bullish"      # ...and changes nothing
    assert alert_company.economic_effect == "positive"
    assert alert_company.rationale == "fundamental thesis"
    assert json.loads(alert_company.key_points_json) == ["point"]

    # Same discipline on the deferred remeasure path (a no_data move that
    # later resolves must not become a back-door direction rewrite).
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()
    move.measurement_status = "no_data"
    move.excess_move_pct = None
    db_session.commit()

    assert remeasure_no_data_moves(db_session) == 1
    db_session.refresh(alert_company)
    assert alert_company.direction == "bullish"
    assert alert_company.rationale == "fundamental thesis"


def test_inv001_gated_rows_survive_reconciliation_with_the_flag_OFF(
        db_session, monkeypatch, legacy_mode):
    """INV-001 is STRUCTURAL, not modal (final-review finding I1).

    Both reconciliation sites used to guard only on
    settings.impact_engine_v4_strict. The scheduler runs
    remeasure_no_data_moves continuously, so on a deployment with the flag
    OFF -- or after any flag flip -- it reached rows the publication gate
    had already ruled on and overwrote `direction` from the measured move,
    NULLing rationale and key_points_json with it. Gate output is
    authoritative once persisted (the same rule
    publication_gate.is_gated states), so the skip is now per row and
    flag-independent.

    Pinned on BOTH paths, and the legacy (ungated) row alongside it proves
    the flag-off behavior for rows that never walked the gate is
    byte-identical to before."""
    import app.pipeline as pipeline_module
    from app.pipeline import measure_and_reconcile_alert_companies, remeasure_no_data_moves

    alert = _seed_alert(db_session)
    # Gated: the gate ruled DISPLAY_ELIGIBLE / primary on a bullish call.
    _, gated = _add_alert_company(
        db_session, alert, "RELIANCE.NS", "Reliance Industries",
        direction="bullish", economic_effect="positive", with_move=False)
    # Legacy: no gate_state, no display_tier -- the pre-v4 shape.
    _, ungated = _add_alert_company(
        db_session, alert, "IOC.NS", "Indian Oil", direction="bullish",
        display_tier=None, gate_state=None, with_move=False)

    def _contradicting_move(session, company_row, **kwargs):
        return MarketMove(
            company_id=company_row.id, benchmark_ticker="^CNXENERGY",
            raw_move_pct=-2.0, sector_move_pct=0.5, excess_move_pct=-2.5,
            measured_at=utcnow(), measurement_status="ok")

    monkeypatch.setattr(pipeline_module, "measure_company_move", _contradicting_move)

    measure_and_reconcile_alert_companies(db_session, alert.id, [gated, ungated])

    # Gated row: untouched, despite a measured move contradicting it.
    assert gated.direction == "bullish"
    assert gated.rationale == "fundamental thesis"
    assert json.loads(gated.key_points_json) == ["point"]
    # Ungated row: unchanged legacy behavior -- measurement still wins.
    assert ungated.direction == "bearish"
    assert ungated.rationale is None
    assert json.loads(ungated.key_points_json) == []

    # Same on the scheduler-driven remeasure path -- the one that actually
    # destroyed gated rows in production.
    gated.direction, gated.rationale = "bullish", "fundamental thesis"
    gated.key_points_json = json.dumps(["point"])
    ungated.direction, ungated.rationale = "bullish", "fundamental thesis"
    ungated.key_points_json = json.dumps(["point"])
    for move in db_session.query(MarketMove).filter_by(alert_id=alert.id).all():
        move.measurement_status = "no_data"
        move.excess_move_pct = None
    db_session.commit()

    assert remeasure_no_data_moves(db_session) == 2
    db_session.refresh(gated)
    db_session.refresh(ungated)
    assert gated.direction == "bullish"
    assert gated.rationale == "fundamental thesis"
    assert json.loads(gated.key_points_json) == ["point"]
    assert ungated.direction == "bearish"
    assert ungated.rationale is None


# ===========================================================================
# INV-002: fundamental analysis is never derived from price
# ===========================================================================

def test_inv002_fundamental_analysis_is_never_derived_from_price(db_session, strict_mode):
    """INV-002, both halves.

    STRUCTURAL: the publication gate cannot consult the market because its
    input type carries no market field -- adding one fails here and forces
    the conversation -- and the module imports nothing that could hand it
    one (no app.market, no ORM models: prose mentioning them in a docstring
    is fine, an executable import is not).

    BEHAVIORAL: end to end, a company whose measured move is strongly
    POSITIVE but whose fundamental effect is NEGATIVE (the Apollo case,
    spec §62) renders in a NEGATIVE section. Price never picks the icon."""
    import ast
    import inspect
    from dataclasses import fields

    from app.analysis.impact_graph import publication_gate
    from app.market.ripple_layers import compute_ripple_layers

    names = {f.name for f in fields(CandidateInput)}
    forbidden = {"excess_move_pct", "raw_move_pct", "market_reaction", "price",
                 "move_pct", "reaction_direction", "return_1m", "intensity"}
    assert not (names & forbidden)

    imported: list[str] = []
    for node in ast.walk(ast.parse(inspect.getsource(publication_gate))):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(module.startswith("app.market") or module == "app.models"
                   for module in imported), imported

    alert = _seed_alert(db_session)
    _add_alert_company(db_session, alert, "APOLLOTYRE.NS", "Apollo Tyres", "auto",
                       direction="bearish", economic_effect="negative",
                       causal_parent_id="tyre_input_cost", excess=+2.1)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 1
    assert layers[0]["icon"] == "lose"
    assert layers[0]["title"].startswith("Negative")
    # The measured move still rides along, separately and unedited.
    assert layers[0]["rows"][0]["excess_move_pct"] == 2.1
    assert layers[0]["rows"][0]["reaction_direction"] == "positive"


# ===========================================================================
# INV-003: a market observation is not fundamental evidence
# ===========================================================================

def test_inv003_market_observation_is_never_fundamental_evidence(db_session, strict_mode):
    """INV-003: "the stock fell 3%" is a market fact, not evidence about
    the business. POST-TASK-4 POLICY (verified against the current gate,
    not the historical one): a MARKET_OBS candidate is not quietly demoted
    to a deep dive -- it is REJECTED, machine-readably, as
    REJECT_INSUFFICIENT_EVIDENCE. Pinned at the gate AND end to end from a
    price-movement rationale through evidence classification."""
    from app.pipeline import _v3_entries

    decision = evaluate_candidate(_candidate(
        evidence_class="ARTICLE_MARKET_OBSERVATION", evidence_tier="MARKET_OBS"),
        GateContext())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"
    assert decision.display_tier == "excluded"

    _company_row(db_session)
    mover = _graph_company(
        rationale="the stock fell 3% after the announcement",
        mechanism="shares dropped sharply on the news of the crude spike")
    entries = _v3_entries(db_session, _result([mover]))

    assert entries[0]["evidence_class"] == "ARTICLE_MARKET_OBSERVATION"
    assert entries[0]["gate_state"] == "REJECT_INSUFFICIENT_EVIDENCE"
    assert entries[0]["display_tier"] == "excluded"


# ===========================================================================
# INV-004: archetype membership (tier D) can never be a primary claim
# ===========================================================================

def test_inv004_archetype_and_tier_d_evidence_never_reach_primary(db_session, strict_mode):
    """INV-004: a curated archetype is a maintainer-reviewed HINT, never
    proof about a specific company. Tier D is displayable at best as a deep
    dive, at any materiality -- pinned at the gate and end to end through
    the archetype discovery stamp that produces CURATED_ARCHETYPE."""
    from app.pipeline import _v3_entries

    for tier, evidence_class in (("D", "CURATED_ARCHETYPE"), ("D", "MODEL_VERIFIED_PRIOR"),
                                 ("D", "LEGACY_UNVERIFIED")):
        decision = evaluate_candidate(_candidate(
            evidence_class=evidence_class, evidence_tier=tier, materiality=0.95),
            GateContext())
        assert decision.final_state == "DISPLAY_ELIGIBLE", evidence_class
        assert decision.display_tier == "secondary_ripple", evidence_class

    _company_row(db_session)
    archetype = _graph_company(discovery_source="archetype:crude_input_cost")
    entries = _v3_entries(db_session, _result([archetype]))

    assert entries[0]["evidence_class"] == "CURATED_ARCHETYPE"
    assert entries[0]["display_tier"] == "secondary_ripple"


# ===========================================================================
# INV-005: publication fails closed when a gate cannot be evaluated
# ===========================================================================

@pytest.mark.parametrize("verified", [False, True])
def test_inv005_unavailable_validator_fails_closed(db_session, strict_mode, verified):
    """INV-005: a gate that could not be evaluated REJECTS -- it never
    waves a candidate through. Three real ways the validator goes missing,
    each asserted with independently_verified True as well as False, since
    the fail-OPEN bug this invariant exists to prevent was exactly a True
    flag (an upstream default) outranking an absent verifier."""
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    from app.pipeline import _v3_entries

    # 1. The gate itself, told the verifier never ran.
    decision = evaluate_candidate(_candidate(
        independently_verified=verified, verification_available=False), GateContext())
    assert decision.final_state == "REJECT_VALIDATOR_UNAVAILABLE"
    assert decision.display_tier == "excluded"

    # 2. Budget exhaustion: verification was skipped entirely.
    _company_row(db_session, verified_node="crude_price")
    entries = _v3_entries(db_session, _result(
        [_graph_company(verified=verified)], quality="budget_exhausted"))
    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"
    assert entries[0]["display_tier"] == "excluded"

    # 3. Verifier-router outage: the run says so in metrics.
    outage = ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=[],
        companies=[_graph_company(verified=verified)], edges=[_graph_edge()],
        gaps=[], ranking=[], analysis_provider="gemini",
        analysis_quality="authoritative", metrics={"verification_unavailable": 1},
    )
    assert _v3_entries(db_session, outage)[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"


# ===========================================================================
# INV-006: DISPLAY_ELIGIBLE means every gate in the sequence passed
# ===========================================================================

def test_inv006_display_eligible_requires_exact_full_sequence(db_session, strict_mode):
    """INV-006: DISPLAY_ELIGIBLE is reachable ONLY by walking the entire
    GATE_SEQUENCE in order -- gates_passed equals the declared sequence
    exactly (not a superset, not a prefix), and the durable decision record
    persists that same list.

    MUTATION GUARD: the length assertion below is deliberate. Adding or
    removing a gate must be a CONSCIOUS act that updates this number and
    re-reads this invariant -- an accidental deletion (the failure mode
    that makes a gate silently stop running) fails here by name."""
    assert len(GATE_SEQUENCE) == 13, (
        "GATE_SEQUENCE changed. This is not a number to bump reflexively: "
        "re-read spec Appendix-B INV-006 and confirm the added/removed gate "
        "is intended, then update this guard."
    )

    decision = evaluate_candidate(_candidate(), GateContext())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.gates_passed == GATE_NAMES

    # A rejected candidate's trail is a strict PREFIX -- never the full set.
    rejected = evaluate_candidate(_candidate(independently_verified=False), GateContext())
    assert rejected.gates_passed == GATE_NAMES[:-1]
    assert rejected.final_state != "DISPLAY_ELIGIBLE"

    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([_graph_company()]))
    record = db_session.query(CompanyDecisionRecord).filter_by(
        alert_id=alert.id, final_state="DISPLAY_ELIGIBLE").one()
    assert json.loads(record.gates_passed_json) == GATE_NAMES


# ===========================================================================
# INV-007: a company never appears in a section incompatible with its effect
# ===========================================================================

def test_inv007_incompatible_effect_cannot_enter_a_section(db_session, strict_mode):
    """INV-007: section membership is derived from the company's own
    validated economic_effect, so a NEGATIVE company cannot appear under a
    POSITIVE heading -- even when it shares the causal parent (the only
    other grouping key) with positive companies. Probed directly against
    the deterministic section builder."""
    from app.market.ripple_layers import _strict_sections

    alert = _seed_alert(db_session)
    _, positive = _add_alert_company(
        db_session, alert, "ONGC.NS", "ONGC", economic_effect="positive",
        direction="bullish", causal_parent_id="crude_price")
    _, negative = _add_alert_company(
        db_session, alert, "MRF.NS", "MRF", "auto", economic_effect="negative",
        direction="bearish", causal_parent_id="crude_price")
    db_session.refresh(alert)

    rows_flat = [
        {"alert_company_id": positive.id, "ticker": "ONGC.NS"},
        {"alert_company_id": negative.id, "ticker": "MRF.NS"},
    ]
    layers = _strict_sections(alert, rows_flat)

    assert len(layers) == 2, "one effect per section, same parent notwithstanding"
    by_title = {layer["title"]: [row["ticker"] for row in layer["rows"]] for layer in layers}
    positive_sections = [t for t in by_title if t.startswith("Positive")]
    negative_sections = [t for t in by_title if t.startswith("Negative")]
    assert positive_sections and negative_sections
    assert "MRF.NS" not in by_title[positive_sections[0]]
    assert "ONGC.NS" not in by_title[negative_sections[0]]


# ===========================================================================
# INV-008: an LLM-authored section layer never renders for a gated alert
# ===========================================================================

@pytest.mark.parametrize("flag", [True, False])
def test_inv008_llm_section_layer_ignored_for_gated_alert(db_session, monkeypatch, flag):
    """INV-008: once gate output is persisted on a row, the legacy
    LLM-authored section path is STRUCTURALLY unreachable -- a persisted
    AlertRippleLayer ("Winners — upstream") never surfaces. Asserted with
    the strict flag both ON and OFF: reachability is structural, not modal,
    so flipping the flag back can never resurrect it."""
    from app.market.ripple_layers import compute_ripple_layers

    monkeypatch.setattr(settings, "impact_engine_v4_strict", flag)
    alert = _seed_alert(db_session)
    _add_alert_company(db_session, alert, "ONGC.NS", "ONGC", excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    assert "Winners — upstream" not in [layer["title"] for layer in layers]
    assert all(layer["relationship"].startswith("MECH:") or layer["relationship"] == "SECONDARY"
               for layer in layers)


# ===========================================================================
# INV-009: regeneration replaces sections, never accumulates them
# ===========================================================================

def test_inv009_regenerated_sections_replace_never_duplicate(db_session, monkeypatch):
    """INV-009: re-running refinement must not leave stale sections behind.
    Delete-before-insert is unconditional, so a second pass yields one
    layer and one timeline row, not two of each. Uses a LEGACY (ungated)
    alert because the layer-writing branch is only reachable there --
    TimelineEffect's delete-before-insert covers both."""
    from app.analysis import refinement

    alert = _seed_alert(db_session)
    _, alert_company = _add_alert_company(
        db_session, alert, "ONGC.NS", "ONGC", display_tier=None, gate_state=None,
        excess=1.0)
    article = db_session.get(Article, alert.article_id)
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()

    monkeypatch.setattr(refinement, "generate_event_summary",
                        lambda *a, **k: {"summary_short": "s", "summary_long": "l",
                                         "is_unconfirmed": False})
    monkeypatch.setattr(refinement, "generate_impact_whys", lambda *a, **k: {})
    monkeypatch.setattr(refinement, "generate_ripple_layers",
                        lambda *a, **k: [{"title": "Winners — upstream", "relationship": "DIRECT",
                                          "note": "n", "tickers": ["ONGC.NS"]}])
    monkeypatch.setattr(refinement, "generate_timeline_effects",
                        lambda *a, **k: [{"horizon": "DAYS", "description": "d"}])

    refinement.refine_alert(object(), db_session, alert, article, [alert_company], [move])
    refinement.refine_alert(object(), db_session, alert, article, [alert_company], [move])

    assert db_session.query(AlertRippleLayer).filter_by(alert_id=alert.id).count() == 1
    assert db_session.query(TimelineEffect).filter_by(alert_id=alert.id).count() == 1


# ===========================================================================
# INV-010: no company appears twice across an alert's sections
# ===========================================================================

def test_inv010_no_company_appears_twice_across_all_sections(db_session, strict_mode):
    """INV-010: the reader sees each company once. Two candidates naming
    the SAME company (the real production shape -- two mechanisms proposing
    one ticker) are deduplicated at the gate, so exactly one AlertCompany
    row exists and the ticker appears exactly once across EVERY section,
    including the trailing secondary section."""
    from app.market.ripple_layers import compute_ripple_layers

    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([
        _graph_company(materiality=0.8),
        _graph_company(materiality=0.5, rationale="second bite at the same company"),
    ]))

    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(rows) == 1

    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)
    tickers = [row["ticker"] for layer in layers for row in layer["rows"]]
    assert tickers.count("ONGC.NS") == 1
    assert len(tickers) == len(set(tickers))


# ===========================================================================
# INV-011: an unresolvable (invented) ticker is never persisted
# ===========================================================================

def test_inv011_ghost_ticker_never_becomes_a_persisted_company(db_session, strict_mode):
    """INV-011: a ticker with no Company row cannot become an
    AlertCompany, no matter how confident the model was.

    Post-Task-18 shape (verified against the current code): the ghost DOES
    leave a durable audit record -- company_id NULL, REJECT_UNKNOWN_COMPANY
    -- because "the model invented ONGX.NS" is exactly what a postmortem
    needs. The invariant is about PERSISTED COMPANIES, so both halves are
    asserted: a record exists, and no AlertCompany does."""
    from app.pipeline import _v3_entries

    ghost = _graph_company(
        ticker="GHOST.NS", name="Ghost Co",
        mechanism="entirely fabricated exposure story about a company that does not exist",
        rationale="hallucinated")
    result = _result([ghost])

    entries = _v3_entries(db_session, result)
    assert all(entry.get("company_id") is None for entry in entries)
    assert all(entry.get("display_tier") == "excluded" for entry in entries)

    alert = _persist(db_session, result)

    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 0
    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert record.company_id is None
    assert record.ticker == "GHOST.NS"
    assert record.final_state == "REJECT_UNKNOWN_COMPANY"


# ===========================================================================
# INV-012: an uncertain effect is never upgraded
# ===========================================================================

def test_inv012_uncertain_effect_is_never_upgraded(db_session, strict_mode):
    """INV-012: "uncertain" survives every stage as itself. It can never be
    graded primary, and it must not be laundered into a directional effect
    by persistence or serialization.

    The final blueprint tightens where it lands, without touching that
    invariant: §4 sends an unresolved effect to "reject from display", so an
    uncertain candidate now walks all thirteen gates and terminates in
    REJECT_BELOW_SECONDARY_POLICY instead of occupying a deep-dive slot. It
    is still never upgraded, still persisted as itself, and now also never
    laundered into a directional row by the section serializer -- because it
    produces no row at all."""
    from app.market.ripple_layers import compute_ripple_layers

    decision = evaluate_candidate(_candidate(
        economic_effect="uncertain", net_direction="uncertain"), GateContext())
    assert decision.display_tier != "primary"                  # never upgraded
    assert decision.final_state == "REJECT_BELOW_SECONDARY_POLICY"
    assert decision.display_tier == "excluded"

    from app.pipeline import _v3_entries

    _company_row(db_session, verified_node="crude_price", provenance_type="SUPPLY_LINK")
    uncertain = _graph_company(economic_effect="uncertain", net_direction="uncertain",
                               direction="neutral")
    entries = _v3_entries(db_session, _result([uncertain]))

    assert entries[0]["economic_effect"] == "uncertain"      # carried as itself
    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_BELOW_SECONDARY_POLICY"

    # ...and nothing directional was invented on the way to the reader: the
    # excluded candidate never becomes a published row at all.
    alert = _persist(db_session, _result([uncertain]))
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 0
    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)
    serialized = [r for layer in layers for r in layer["rows"]]
    assert [r["economic_effect"] for r in serialized] == []


# ===========================================================================
# INV-013: the causal-distance policy is exact
# ===========================================================================

def test_inv013_causal_distance_policy_is_exact(monkeypatch):
    """INV-013: d4+ is excluded outright with NO policy override; d3
    survives only as MACRO_CONTEXT (final blueprint §7 -- the tier it lands
    in was renamed from the single "deep dive" bucket; the DISTANCE POLICY
    itself is untouched) and only with relationship-grade evidence AND high
    materiality; d2 primary needs a relationship record, not "the article
    was about them"."""
    # d4: no evidence, materiality or owner policy rescues it.
    monkeypatch.setattr(settings, "impact_allow_low_materiality_deep_dive", True)
    monkeypatch.setattr(settings, "impact_allow_fallback_primary", True)
    for tier in ("A", "B", "C", "SUBJECT", "D"):
        far = evaluate_candidate(_candidate(
            causal_distance=4, evidence_tier=tier, materiality=0.99), GateContext())
        assert far.final_state == "REJECT_TOO_DISTANT", tier

    # d3: relationship evidence + HIGH materiality -> macro context, never
    # primary.
    d3_ok = evaluate_candidate(_candidate(
        causal_distance=3, evidence_tier="C", materiality=0.9), GateContext())
    assert d3_ok.final_state == "DISPLAY_ELIGIBLE"
    assert d3_ok.display_tier == "macro_context"
    assert d3_ok.display_tier != "primary"

    # d3 without one of the two -> machine-readable low-priority rejection.
    assert evaluate_candidate(_candidate(
        causal_distance=3, evidence_tier="D", materiality=0.9),
        GateContext()).final_state == "REJECT_LOW_PRIORITY"
    assert evaluate_candidate(_candidate(
        causal_distance=3, evidence_tier="C", materiality=0.45),
        GateContext()).final_state == "REJECT_LOW_PRIORITY"

    # d2: SUBJECT is d1-only evidence; a relationship record unlocks primary.
    assert evaluate_candidate(_candidate(
        causal_distance=2, evidence_tier="SUBJECT", materiality=0.9),
        GateContext()).display_tier == "secondary_ripple"
    assert evaluate_candidate(_candidate(
        causal_distance=2, evidence_tier="C", materiality=0.9),
        GateContext()).display_tier == "primary"


# ===========================================================================
# INV-014: explanations are closed-world
# ===========================================================================

def test_inv014_explanations_are_closed_world(db_session, monkeypatch, strict_mode):
    """INV-014: no explanation text may introduce a company or a number the
    evidence base never contained. End to end through refine_alert:

    - a summary naming a company that is neither tracked nor in the facts
      is DROPPED (not published, not "cleaned up");
    - a gated row's `why` is the gate-validated mechanism itself, with any
      percentage clause sanitized out -- never an LLM story invented for
      the measured move."""
    from app.analysis import refinement
    from app.companies.matching.normalize import normalize_name
    from app.models import CompanyAlias

    alert = _seed_alert(db_session)
    # A real, tracked company that this alert does NOT cover: naming it in
    # generated prose is the hallucination the validator exists to catch.
    foreign = _company_row(db_session, ticker="INFY.NS", name="Infosys", sector="it")
    db_session.add(CompanyAlias(company_id=foreign.id, alias="Infosys", alias_type="LEGAL",
                                normalized=normalize_name("Infosys")))
    db_session.commit()
    _, alert_company = _add_alert_company(
        db_session, alert, "MRF.NS", "MRF", "auto", economic_effect="negative",
        direction="bearish", excess=+1.0,
        mechanism=("Crude-linked rubber input costs squeeze tyre margins. "
                   "Analysts pencilled in a 40% profit hit."))
    article = db_session.get(Article, alert.article_id)
    alert.facts = "Crude oil prices rose sharply overnight."
    db_session.commit()
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()

    monkeypatch.setattr(refinement, "generate_event_summary",
                        lambda *a, **k: {"summary_short": "Infosys is expected to benefit from this.",
                                         "summary_long": "Infosys will gain on this policy shift.",
                                         "is_unconfirmed": False})
    monkeypatch.setattr(refinement, "generate_timeline_effects", lambda *a, **k: [])
    monkeypatch.setattr(refinement, "generate_impact_whys",
                        lambda *a, **k: pytest.fail("gated alert must not pay for impact_whys"))
    monkeypatch.setattr(refinement, "generate_ripple_layers",
                        lambda *a, **k: pytest.fail("gated alert must not pay for ripple_layers"))

    refinement.refine_alert(object(), db_session, alert, article, [alert_company], [move])

    assert alert.summary_short is None    # novel company -> dropped whole
    assert alert.summary_long is None
    assert alert_company.why is not None
    assert "%" not in alert_company.why
    assert "Crude-linked rubber input costs squeeze tyre margins." in alert_company.why


# ===========================================================================
# INV-015: nothing valid is silently lost
# ===========================================================================

def test_inv015_valid_analysis_is_never_silently_lost(db_session, strict_mode):
    """INV-015: a valid fundamental analysis survives both a market-data
    failure and an alert-level policy demotion.

    (a) an unmeasured gated alert is still SERVED, with every market field
        honestly null (structurally re-verified post-Task-16: the alert
        needs a PRIMARY company to headline the main feed);
    (b) primary-cap overflow DEMOTES, never deletes -- the count in equals
        the count out."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers.articles import get_db

    alert = _seed_alert(db_session)
    _add_alert_company(db_session, alert, "MRF.NS", "MRF", "auto",
                       economic_effect="negative", direction="bearish", excess=None)

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        rows = client.get("/api/feed-v2").json()
        assert [r["id"] for r in rows] == [alert.id]
        assert rows[0]["excess_move_pct"] is None
        assert rows[0]["market_reaction"]["status"] == "unavailable"
    finally:
        app.dependency_overrides.clear()

    decisions = [evaluate_candidate(_candidate(ticker=f"T{i:02d}.NS", materiality=0.9 - i * 0.01),
                                    GateContext())
                 for i in range(12)]
    finalized = finalize_alert_decisions(decisions, GateContext(max_primary_companies=10))

    assert len(finalized) == 12                                    # nothing deleted
    assert sum(d.display_tier == "primary" for d in finalized) == 10
    demoted = [d for d in finalized if d.notes == "primary_cap_overflow"]
    assert len(demoted) == 2
    assert all(d.final_state == "DISPLAY_ELIGIBLE" for d in demoted)
    assert all(d.display_tier == "secondary_ripple" for d in demoted)


# ===========================================================================
# INV-016: a degraded analysis can never speak as a primary claim
# ===========================================================================

def _narrow_router(quality, provider="gemini"):
    """A FakeRouter that drives the real narrow-path engine to ONE
    primary-capable company, with the run's provider/quality under test."""
    from tests.test_impact_graph import FACTS, FakeRouter, _edge

    return FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings", category="fmcg"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "Demand hit", "direction": "bearish",
                        "mechanism": "input cost shock", "confidence": 0.85,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.8, conf=0.85)],
        },
        "narrow_companies": {"companies": [{
            "ticker": "NARROW.NS", "name": "Narrow Co", "direction": "bearish",
            "impact_strength": 0.7, "confidence": 0.8, "materiality": 0.8,
            "time_horizon": "Short-Term", "parent_id": "fmcg",
            "mechanism": "input cost inflation compresses this company's gross margin",
            "rationale": "single-category manufacturer with no hedging",
            "net_direction": "bearish",
        }]},
        "verify_companies": {"accept": ["NARROW.NS"], "reject": [],
                             "counterfactual": {"NARROW.NS": "SUPPORTED"}},
    }, provider=provider, quality=quality)


def _supply_link_primary_result(db, quality):
    """A candidate that is genuinely PRIMARY-capable under an authoritative
    analysis: d2, Tier-C evidence from a real independently-sourced
    artifact (a SupplyLink rating rationale), HIGH materiality, verifier
    SUPPORTED. Only `analysis_quality` varies across the ladder below, so
    a tier change can have exactly one cause."""
    from datetime import date

    from app.models import SupplyLink

    parent = _company_row(db, ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto")
    supplier = _company_row(db, ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                            sector="auto_components",
                            business_desc="Wiring harness and auto components supplier")
    db.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db.commit()

    d2 = _graph_company(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson", causal_distance=2,
        materiality=0.8, parent_type="company", parent_id="MARUTI.NS",
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM")
    return _result([d2], edges=[_graph_edge(child_type="company", child_id="MARUTI.NS")],
                   quality=quality)


@pytest.mark.parametrize("quality,expected_tier,expected_state", [
    ("authoritative", "primary", "DISPLAY_ELIGIBLE"),          # the control
    ("fallback", "secondary_ripple", "DISPLAY_ELIGIBLE"),
    ("degraded", "secondary_ripple", "DISPLAY_ELIGIBLE"),
    ("budget_exhausted", "excluded", "REJECT_VALIDATOR_UNAVAILABLE"),
])
def test_inv016_analysis_quality_decides_how_loudly_a_result_speaks(
        db_session, strict_mode, quality, expected_tier, expected_state):
    """INV-016 BEHAVIORAL (this REPLACES the old prompt-substring test,
    which asserted nothing about behavior): the quality of the analysis
    that actually produced a result decides how loudly it may speak, all
    the way to the persisted row.

    One identical primary-capable candidate per rung -- only the run's
    analysis_quality differs. The authoritative row IS primary, which is
    what makes the other three assertions non-vacuous: a fallback (Groq)
    or degraded run is still eligible but never primary, and budget
    exhaustion -- verification never ran at all -- rejects outright and
    persists no company row whatsoever."""
    from app.pipeline import _v3_entries

    result = _supply_link_primary_result(db_session, quality)
    entries = _v3_entries(db_session, result)

    assert entries[0]["evidence_class"] == "VERIFIED_RELATIONSHIP"
    assert entries[0]["gate_state"] == expected_state
    assert entries[0]["display_tier"] == expected_tier

    alert = _persist(db_session, result)
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert [row.display_tier for row in rows] == ([] if expected_tier == "excluded"
                                                  else [expected_tier])


def test_inv016_groq_fallback_quality_reaches_the_gate_end_to_end(db_session, strict_mode):
    """The other half of INV-016: the ladder above is only meaningful if a
    real run's quality actually ARRIVES at the gate. A FakeRouter serving
    the whole narrow path as Groq/fallback (exactly what a Gemini outage
    produces in production) is carried through the engine onto
    ImpactGraphResult and lands in the gate's own input snapshot -- and no
    persisted row from that run is primary."""
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.pipeline import _v3_entries

    _company_row(db_session, ticker="NARROW.NS", name="Narrow Co", sector="fmcg",
                 business_desc="Single-category packaged foods manufacturer")

    result = analyze_article_v3(_narrow_router("fallback", "groq"), "t", "c",
                                session=db_session)

    assert result.analysis_provider == "groq"
    assert result.analysis_quality == "fallback"
    assert [c.ticker for c in result.companies] == ["NARROW.NS"]

    entries = _v3_entries(db_session, result)
    # The router's quality reached the gate through the entire engine --
    # asserted on the gate's OWN recorded input, not on a re-derivation.
    assert entries[0]["gate_inputs"]["analysis_quality"] == "fallback"
    assert entries[0]["gate_inputs"]["verification_available"] is True
    assert entries[0]["display_tier"] != "primary"

    alert = _persist(db_session, result)
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert all(row.display_tier != "primary" for row in rows)
    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert record.analysis_quality == "fallback"
    assert record.provider == "groq"


# ===========================================================================
# INV-017: every company-generating prompt carries the no-invention contract
# ===========================================================================

# Every prompt constant that can cause a COMPANY to enter (or stay in) the
# result set. If a new company-generating stage is added, it belongs here --
# the delivered-prompt assertions below are what stop a new stage from
# shipping without the contract.
_COMPANY_PROMPT_NAMES = [
    "DIRECT_COMPANIES_PROMPT",
    "RIPPLE_COMPANIES_PROMPT",
    "NARROW_COMPANIES_PROMPT",
    "MECHANISM_MAPPING_PROMPT",
    "ESCALATION_PROMPT",
    "VERIFY_COMPANIES_PROMPT",
]

_ABSTENTION_TOKENS = ("zero", "omit", "omission", "none", "reject")
_CANDIDATE_RESTRICTION_TOKENS = ("candidate list", "supplied", "candidates from")

# RULED (corrective-v4 Task 18 follow-up, per-stage INV-017): three of the
# six carried NO invention prohibition of their own -- only the shared
# SYSTEM_PROMPT prefix's -- confirmed by direct inspection (`"invent" in
# constant.lower()`) before this fix landed. Each now carries its own
# explicit line; this is the set the STRONGER, static_prefix-independent
# assertion below applies to. The other three (DIRECT_COMPANIES_PROMPT,
# RIPPLE_COMPANIES_PROMPT, MECHANISM_MAPPING_PROMPT) already had their own
# text and are not required to change, though they're not excluded from a
# future tightening.
_OWN_INVENTION_PROHIBITION_REQUIRED = frozenset({
    "NARROW_COMPANIES_PROMPT", "ESCALATION_PROMPT", "VERIFY_COMPANIES_PROMPT",
})


@pytest.mark.parametrize("prompt_name", _COMPANY_PROMPT_NAMES)
def test_inv017_company_prompts_forbid_invention_and_allow_abstention(prompt_name):
    """INV-017: a model asked to name companies must be told, in the text
    it actually receives, that inventing is forbidden and that returning
    nothing is a correct answer.

    Two levels, both real:
    - the DELIVERED prompt (`static_prefix(stage)`, i.e. exactly what the
      engine sends) must carry the invention prohibition. Its home is
      SYSTEM_PROMPT, which every company stage ships -- deleting that
      clause fails all six of these at once (and the guard below names it).
    - the STAGE constant's OWN text must restrict selection to the supplied
      candidate list and permit abstention/rejection. That is per-stage and
      cannot be satisfied by the shared prefix.

    A THIRD, stronger check applies to NARROW_COMPANIES_PROMPT/
    ESCALATION_PROMPT/VERIFY_COMPANIES_PROMPT specifically: their OWN text
    (not merely the delivered, SYSTEM_PROMPT-prefixed text) must carry the
    invention prohibition -- dropping the static_prefix delivery workaround
    these three used to rely on entirely, since a future stage-prompt
    refactor that changes what gets prefixed must not silently re-open
    them."""
    from app.analysis.impact_graph import prompts

    constant = getattr(prompts, prompt_name)
    delivered = prompts.static_prefix(constant).lower()
    own = constant.lower()

    assert "invent" in delivered, f"{prompt_name}: no invention prohibition reaches the model"
    if prompt_name in _OWN_INVENTION_PROHIBITION_REQUIRED:
        assert "invent" in own, (
            f"{prompt_name}: relies on the shared SYSTEM_PROMPT prefix alone -- "
            "needs its own invention prohibition line")
    assert any(token in own for token in _CANDIDATE_RESTRICTION_TOKENS), (
        f"{prompt_name}: does not restrict the model to the supplied candidates")
    assert any(token in own for token in _ABSTENTION_TOKENS), (
        f"{prompt_name}: never tells the model that naming nobody is a valid answer")


def test_inv017_shared_invention_prohibition_lives_in_the_system_prompt():
    """The guard for the assertion above: the prohibition is real text in
    SYSTEM_PROMPT (not incidentally-matching prose elsewhere), and it names
    the fabrications that actually hurt -- relationships and numbers."""
    from app.analysis.impact_graph import prompts

    system = prompts.SYSTEM_PROMPT.lower()
    assert "never invent" in system
    for fabrication in ("supplier relationships", "market shares", "cost percentages"):
        assert fabrication in system, fabrication


# ===========================================================================
# INV-018: nothing in the output is fabricated
# ===========================================================================

def test_inv018_fabricated_support_cannot_earn_anything(db_session, strict_mode):
    """INV-018, three fabrication routes, all closed BEHAVIORALLY:

    (a) self-reported `evidence_refs` cannot raise confidence -- padding
        them with invented ids scores identically to supplying none;
    (b) a percentage the facts never contained cannot reach the reader's
        `why` (sanitized at the boundary);
    (c) an EvidenceRecord is never fabricated: only a real artifact
        (SupplyLink / provenanced exposure) ever supplies a source_url or
        quoted_text, and an LLM's own invented citation never becomes a
        persisted record."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.refinement import _sanitize_mechanism
    from app.pipeline import _build_alert_company

    # (a)
    company = _company_row(db_session, ticker="RELIANCE.NS", name="Reliance", sector="oil_gas")
    article = _article(db_session)

    def _entry(evidence_refs):
        return {"company_id": company.id, "direction": "bullish", "magnitude_low": 1.0,
                "magnitude_high": 3.0, "rationale": "r", "key_points": [],
                "time_horizon": "Short-Term", "basis": "direct_mention",
                "reasons": ["one", "two", "three"], "evidence_refs": evidence_refs,
                "risks": [], "assumptions": [], "unknowns": [],
                "alternative_hypothesis": None}

    honest, _ = _build_alert_company(db_session, 1, article, "oil_gas", _entry([]))
    padded, _ = _build_alert_company(
        db_session, 1, article, "oil_gas", _entry(["FAKE_1", "FAKE_2", "FAKE_3"]))
    assert honest.confidence_score == padded.confidence_score

    # (b)
    sanitized = _sanitize_mechanism(
        "Input costs squeeze margins. Profit is expected to fall 40% this quarter.")
    assert sanitized is not None
    assert "%" not in sanitized
    assert "40" not in sanitized

    # (c) every classification path: only a real artifact carries a url.
    subject_row = _company_row(db_session, ticker="TCS.NS", name="TCS", sector="it")
    for graph_company, subjects in (
        (_graph_company(ticker="RELIANCE.NS", name="Reliance"), set()),
        (_graph_company(ticker="TCS.NS", name="TCS"), {"TCS.NS"}),
        (_graph_company(ticker="RELIANCE.NS", discovery_source="archetype:crude_input_cost"), set()),
        (_graph_company(ticker="NOBODY.NS", name="Nobody"), set()),
    ):
        evidence_class, _tier, payloads = classify_evidence(db_session, graph_company, subjects)
        for payload in payloads:
            assert payload.get("source_type"), evidence_class
            if evidence_class != "VERIFIED_RELATIONSHIP":
                assert payload.get("source_url") is None, evidence_class
                assert payload.get("quoted_text") is None, evidence_class

    # ...and an LLM-supplied citation never reaches evidence_records.
    fabricating = _graph_company(
        evidence_refs=["https://invented.example/report", "SOURCE: my own memory"])
    alert = _persist(db_session, _result([fabricating]))
    urls = [row.source_url for row in
            db_session.query(EvidenceRecord).filter_by(alert_id=alert.id).all()]
    assert all(url is None or "invented.example" not in url for url in urls)


# ===========================================================================
# INV-019: every published company has a complete decision record
# ===========================================================================

def test_inv019_accepted_primary_has_a_complete_decision_record(db_session, strict_mode):
    """INV-019: an accepted PRIMARY company's audit record answers "why was
    this shown" without re-running paid analysis -- every completeness
    column is populated, and gate_inputs_json round-trips into the exact
    CandidateInput the gate walked (not a reconstruction)."""
    from datetime import date

    from app.models import SupplyLink

    parent = _company_row(db_session, ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto")
    supplier = _company_row(db_session, ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                            sector="auto_components",
                            business_desc="Wiring harness and auto components supplier")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    d2 = _graph_company(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson", causal_distance=2,
        materiality=0.8, parent_type="company", parent_id="MARUTI.NS",
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM",
        discovery_source="relationship_cache")
    alert = _persist(db_session, _result(
        [d2], edges=[_graph_edge(child_type="company", child_id="MARUTI.NS")]))

    row = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    assert row.display_tier == "primary"

    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert record.final_state == "DISPLAY_ELIGIBLE"
    assert record.display_tier == "primary"
    assert json.loads(record.gates_passed_json) == GATE_NAMES
    assert record.evidence_class == "VERIFIED_RELATIONSHIP"
    assert record.materiality_grade == "HIGH"
    assert record.analysis_version and "/" in record.analysis_version
    assert record.provider == "gemini"
    assert record.model
    assert record.analysis_quality == "authoritative"
    assert json.loads(record.discovery_sources_json) == ["relationship_cache"]

    evidence_ids = json.loads(record.evidence_ids_json)
    assert evidence_ids, "a Tier-C claim must cite the record that earned it"
    evidence = db_session.get(EvidenceRecord, evidence_ids[0])
    assert evidence.source_url == "https://crisil.example/rationale"

    # The gate's own input, exactly as walked -- reconstructible as the
    # dataclass, not merely "some JSON".
    walked = CandidateInput(**json.loads(record.gate_inputs_json))
    assert walked.ticker == "MOTHERSON.NS"
    assert walked.evidence_tier == "C"
    assert walked.causal_distance == 2
    assert walked.materiality_grade == "HIGH"
    assert walked.counterfactual == "SUPPORTED"
    assert evaluate_candidate(walked, GateContext()).final_state == "DISPLAY_ELIGIBLE"


# ===========================================================================
# INV-020: every rejection is machine-readable, and no state is dead
# ===========================================================================

# One construction per rejection state. A state with no construction is
# dead vocabulary, and the completeness assertion below says so by name.
_REACHABILITY_CASES = {
    "REJECT_ENTITY_AMBIGUOUS": dict(entity_status="ambiguous"),
    "REJECT_UNKNOWN_COMPANY": dict(entity_status="unresolved"),
    "REJECT_GENERIC_EXPOSURE": dict(rationale="large company in the same sector",
                                    evidence_tier="D"),
    "REJECT_WEAK_MECHANISM": dict(mechanism="short"),
    "REJECT_NOT_EVENT_SPECIFIC": dict(trigger_shock_present=False),
    "REJECT_TOO_DISTANT": dict(causal_distance=4),
    "REJECT_LOW_PRIORITY": dict(causal_distance=3, evidence_tier="D"),
    "REJECT_LOW_MATERIALITY": dict(materiality=0.1),
    "REJECT_NO_MATERIAL_IMPACT": dict(economic_effect="no_material_impact",
                                      net_direction="neutral"),
    "REJECT_INSUFFICIENT_EVIDENCE": dict(evidence_tier="E"),
    "REJECT_CONTRADICTORY": dict(economic_effect="positive", net_direction="bearish"),
    "REJECT_UNVERIFIED": dict(independently_verified=False),
    "REJECT_VALIDATOR_UNAVAILABLE": dict(analysis_quality="failed"),
    # Final blueprint §6, the symmetric half of "failing PRIMARY is not
    # REJECTED": all thirteen gates green, no tier policy accepts it.
    "REJECT_BELOW_SECONDARY_POLICY": dict(economic_effect="uncertain",
                                          net_direction="uncertain"),
    "REJECT_DUPLICATE": None,   # context-driven, not candidate-driven
}


@pytest.mark.parametrize("state", sorted(REJECTION_STATES))
def test_inv020_every_rejection_state_is_reachable_and_machine_readable(state):
    """INV-020: every rejection carries a machine-readable reason drawn
    from a CLOSED vocabulary in which no state is dead. Parametrized across
    the whole vocabulary -- a state nobody can produce fails here."""
    assert state in _REACHABILITY_CASES, f"no reachability construction for {state}"
    if state == "REJECT_DUPLICATE":
        decision = evaluate_candidate(
            _candidate(), GateContext(seen_tickers=frozenset({"ONGC.NS"})))
    else:
        decision = evaluate_candidate(_candidate(**_REACHABILITY_CASES[state]), GateContext())

    assert decision.final_state == state
    assert decision.rejection_reason == state
    assert decision.rejection_reason in REJECTION_STATES
    assert decision.display_tier == "excluded"


def test_inv020_vocabulary_has_no_dead_states():
    assert set(_REACHABILITY_CASES) == set(REJECTION_STATES)


def test_inv020_rejections_reach_the_audit_trail_with_their_reason(db_session, strict_mode):
    """INV-020 at the persistence boundary: the machine-readable reason is
    DURABLE, not just returned. Four structurally different rejection paths
    -- an unresolved ticker, an unverified candidate, an alert-level
    duplicate, and an entity the matcher could not disambiguate -- each
    leave a record carrying their own reason."""
    _company_row(db_session, ticker="GOOD.NS", name="Good Co", verified_node="crude_price")
    _company_row(db_session, ticker="WEAK.NS", name="Weak Co", verified_node="crude_price")

    result = _result([
        _graph_company(ticker="GOOD.NS", name="Good Co", materiality=0.8),
        _graph_company(ticker="GOOD.NS", name="Good Co", materiality=0.5,
                       rationale="a second candidate naming the same company"),
        _graph_company(ticker="WEAK.NS", name="Weak Co", verified=False),
        _graph_company(ticker="NOPE.NS", name="Nope Co"),
    ], ambiguous_entities=["Twin Alpha Limited"])
    alert = _persist(db_session, result)

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    reasons = {(r.ticker, r.final_state) for r in records}
    assert ("NOPE.NS", "REJECT_UNKNOWN_COMPANY") in reasons
    assert ("WEAK.NS", "REJECT_UNVERIFIED") in reasons
    assert ("GOOD.NS", "REJECT_DUPLICATE") in reasons
    assert ("Twin Alpha Limited", "REJECT_ENTITY_AMBIGUOUS") in reasons
    for record in records:
        if record.final_state.startswith("REJECT_"):
            assert record.rejection_reason == record.final_state
            assert record.rejection_reason in REJECTION_STATES
            assert record.display_tier == "excluded"
