"""Decision-record completeness + internal read path (corrective-v4 Task
18, spec sec54). Companion to test_v4_strict_gate_wiring.py and
test_entity_business_validation.py -- this file pins that EVERY candidate
reaching the publication boundary leaves a durable CompanyDecisionRecord
(including excluded, duplicate, unresolved-ticker and ambiguous-entity
candidates that never became an AlertCompany row at all), that the new
completeness columns (gate_inputs_json, evidence_ids_json,
discovery_sources_json, provider, model, analysis_quality, correction_json)
are populated honestly, and the internal read path (GET /api/internal/
decisions/{alert_id}) requires BOTH the debug flag and an authenticated
user (final-review finding I11 -- the flag alone used to be the whole
protection, leaving the full audit trail of every alert readable by
anyone who knew the path)."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.analysis.impact_graph.publication_gate import CandidateInput
from app.config import settings
from app.main import app
from app.models import (
    Alert, AlertCompany, Article, Company, CompanyDecisionRecord, CompanyNodeExposure,
    EvidenceRecord, SupplyLink, User, utcnow,
)
from app.pipeline import _gate_candidates, _persist_alert, _v3_edges, _v3_entries
from app.routers.articles import get_db


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company_row(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas",
                 business_desc="Upstream oil and gas explorer", verified_node=None):
    # verified_node: adds a CompanyNodeExposure row for that node key, the
    # same fixture pattern test_v4_strict_gate_wiring.py uses -- WITHOUT
    # it, a candidate with no company-specific evidence sits at tier E
    # (MODEL_INFERENCE, evidence.classify_evidence's fallback), which
    # NON_AUTHORIZING_TIERS rejects at EVIDENCE_VALID no matter how
    # complete its business profile is. Tests that need a real DISPLAY_
    # ELIGIBLE candidate pass verified_node="crude_price" (the default
    # GraphCompany fixture's own parent_id) to land on tier D instead.
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  business_desc=business_desc)
    db.add(row)
    db.commit()
    if verified_node is not None:
        db.add(CompanyNodeExposure(
            company_id=row.id, node_key=verified_node, exposure_exists=1,
            strength=0.8, mechanism="verified exposure", verified_at=utcnow()))
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
        impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term",
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def _result(companies, edges=None, quality="authoritative", ambiguous_entities=None, named_entities=None):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    return ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=named_entities or [],
        companies=companies, edges=edges if edges is not None else [_graph_edge()],
        gaps=[], ranking=[], analysis_provider="gemini", analysis_quality=quality,
        metrics={}, ambiguous_entities=ambiguous_entities or [],
    )


def _persist(db, entries_result):
    article = Article(source="s", provider="finnhub", url=f"https://ex.com/{id(entries_result)}",
                      title="crude spikes", content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    entries = _v3_entries(db, entries_result)
    return _persist_alert(
        db, article, "commodity", entries, event_type="crude_oil",
        gaps=[], edges=_v3_edges(entries_result), client=None,
        facts="crude up 5%", analysis_provider="gemini",
        analysis_quality=entries_result.analysis_quality,
        ambiguous_entities=entries_result.ambiguous_entities,
    )


# --- every candidate reaching the boundary -> a record ---------------------

def test_display_eligible_candidate_gets_a_record(db_session, strict_mode):
    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([_graph_company()]))

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 1
    assert records[0].final_state == "DISPLAY_ELIGIBLE"


def test_excluded_candidate_gets_a_record_and_no_alert_company(db_session, strict_mode):
    _company_row(db_session, business_desc=None)  # no profile -> BUSINESS_MODEL_VALID rejects
    alert = _persist(db_session, _result([_graph_company()]))

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 1
    assert records[0].final_state == "REJECT_INSUFFICIENT_EVIDENCE"
    assert records[0].display_tier == "excluded"
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 0


def test_duplicate_candidate_both_get_records_no_unique_violation(db_session, strict_mode):
    """LEDGER RULING: no unique constraint on company_decision_records --
    a REJECT_DUPLICATE row for the same ticker twice in one alert is part
    of the audit trail, not an integrity violation."""
    _company_row(db_session, verified_node="crude_price")
    result = _result([_graph_company(), _graph_company(confidence=0.5)])
    alert = _persist(db_session, result)

    records = (
        db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id)
        .order_by(CompanyDecisionRecord.id).all()
    )
    assert len(records) == 2
    states = sorted(r.final_state for r in records)
    assert states == ["DISPLAY_ELIGIBLE", "REJECT_DUPLICATE"]
    # Only the winner becomes an AlertCompany row.
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 1


def test_unresolved_ticker_gets_a_null_company_id_record(db_session, strict_mode):
    """Ledger parked item (b): _v3_entries used to skip a ticker that never
    resolved to a Company row BEFORE it reached the gate, so its
    REJECT_UNKNOWN_COMPANY decision never became a durable record. It now
    does, with company_id NULL."""
    result = _result([_graph_company(ticker="NOPE.NS", name="Nope Co")])
    alert = _persist(db_session, result)

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 1
    record = records[0]
    assert record.company_id is None
    assert record.ticker == "NOPE.NS"
    assert record.final_state == "REJECT_UNKNOWN_COMPANY"
    assert record.display_tier == "excluded"
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 0


def test_ambiguous_entity_gets_a_decision_record(db_session, strict_mode):
    """Ledger parked item (a): an entity the alias matcher found genuinely
    ambiguous never becomes a candidate at all (dropped in
    engine._subject_companies_ex before any mapping call could propose
    it), so it needs its own durable record keyed by the entity NAME, not
    a ticker."""
    _company_row(db_session)
    result = _result([_graph_company()], ambiguous_entities=["Twin Alpha Limited"])
    alert = _persist(db_session, result)

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    by_ticker = {r.ticker: r for r in records}
    assert "Twin Alpha Limited" in by_ticker
    ambiguous_record = by_ticker["Twin Alpha Limited"]
    assert ambiguous_record.company_id is None
    assert ambiguous_record.final_state == "REJECT_ENTITY_AMBIGUOUS"
    assert ambiguous_record.display_tier == "excluded"
    assert ambiguous_record.rejection_reason == "REJECT_ENTITY_AMBIGUOUS"
    assert ambiguous_record.analysis_version


def test_ambiguous_entity_name_truncated_to_64_chars(db_session, strict_mode):
    long_name = "A" * 100
    result = _result([], ambiguous_entities=[long_name])
    alert = _persist(db_session, result)

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 1
    assert records[0].ticker == "A" * 64


def test_no_ambiguous_entities_writes_nothing_extra(db_session, strict_mode):
    _company_row(db_session)
    alert = _persist(db_session, _result([_graph_company()]))
    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert all(r.final_state != "REJECT_ENTITY_AMBIGUOUS" for r in records)


# --- decision-record completeness (spec sec54) ------------------------------

def test_gate_inputs_json_round_trips_candidate_input(db_session, strict_mode):
    _company_row(db_session)
    alert = _persist(db_session, _result([_graph_company()]))

    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    snapshot = json.loads(record.gate_inputs_json)
    # Every field CandidateInput declares round-trips -- this IS the exact
    # input the gate walked, not a reconstruction from other columns.
    candidate = CandidateInput(**snapshot)
    assert candidate.ticker == "ONGC.NS"
    assert candidate.entity_status == "resolved"
    assert candidate.mechanism == "upstream crude realization: higher price lifts revenue per barrel"
    assert candidate.economic_effect == "positive"


def test_excluded_candidate_completeness_fields_populated(db_session, strict_mode):
    _company_row(db_session, business_desc=None)
    alert = _persist(db_session, _result([_graph_company()], quality="authoritative"))

    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert record.provider == "gemini"
    assert record.model  # best-effort model name, never blank for a known provider
    assert record.analysis_quality == "authoritative"
    # _graph_company() never sets discovery_source -- the honest default
    # ("" on the GraphCompany itself) is recorded as "unknown", never
    # invented into a guessed pool name.
    assert json.loads(record.discovery_sources_json) == ["unknown"]
    assert json.loads(record.evidence_ids_json) == []
    assert json.loads(record.gate_inputs_json)["ticker"] == "ONGC.NS"


def test_discovery_sources_json_carries_engine_stamp(db_session, strict_mode):
    _company_row(db_session)
    company = _graph_company(discovery_source="archetype:tyre_input_cost")
    alert = _persist(db_session, _result([company]))

    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert json.loads(record.discovery_sources_json) == ["archetype:tyre_input_cost"]


def test_correction_json_persisted_when_applied_correction_present(db_session, strict_mode):
    _company_row(db_session)
    company = _graph_company(applied_correction={"materiality": 0.55})
    alert = _persist(db_session, _result([company]))

    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert json.loads(record.correction_json) == {"materiality": 0.55}


def test_correction_json_null_when_no_correction(db_session, strict_mode):
    _company_row(db_session)
    alert = _persist(db_session, _result([_graph_company()]))

    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert record.correction_json is None


# --- T5-deferred: persist_evidence ids reach candidate_json end to end -----

def test_evidence_ids_pin_end_to_end(db_session, strict_mode):
    """Deferred from Task 5's own test suite (ledger item c): a candidate
    whose evidence classification produces a REAL EvidenceRecord (a
    SupplyLink match, Tier C) must have that record's id show up in BOTH
    CompanyDecisionRecord.evidence_ids_json and candidate_json.evidence_ids
    -- not just persisted evidence.persist_evidence's own return value."""
    parent = Company(name="Maruti Suzuki", ticker="MARUTI.NS", sector="auto", index_tier="NIFTY50")
    supplier = Company(name="Samvardhana Motherson", ticker="MOTHERSON.NS",
                       sector="auto_components", index_tier="NIFTY50",
                       business_desc="Auto components and wiring harness supplier")
    db_session.add_all([parent, supplier])
    db_session.commit()
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    company = _graph_company(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson",
        parent_type="company", parent_id="MARUTI.NS", causal_distance=2,
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM",
    )
    alert = _persist(db_session, _result([company]))

    from app.models import EvidenceRecord

    evidence_row = db_session.query(EvidenceRecord).filter_by(alert_id=alert.id).one()
    record = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).one()
    assert record.evidence_class == "VERIFIED_RELATIONSHIP"
    assert json.loads(record.evidence_ids_json) == [evidence_row.id]
    assert json.loads(record.candidate_json)["evidence_ids"] == [evidence_row.id]


# --- engine: discovery_source stamping + applied_correction retention -----

def test_apply_company_correction_retains_raw_correction():
    from app.analysis.impact_graph.engine import _apply_company_correction

    company = _graph_company()
    assert company.applied_correction is None

    correction = {"ticker": "ONGC.NS", "direction": "bearish", "materiality": 0.4}
    _apply_company_correction(company, correction)

    assert company.applied_correction == {"direction": "bearish", "materiality": 0.4}
    assert company.direction == "bearish"


def test_analyze_article_v3_threads_ambiguous_entities(db_session):
    """Ledger parked item (a)'s source: analyze_article_v3 resolves
    named_entities exactly once up front (_subject_companies_ex) and
    carries the ambiguous set out on ImpactGraphResult.ambiguous_entities
    -- the ONLY surviving record of an entity the alias matcher could not
    tiebreak, since it never seeds a candidate at all."""
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.companies.matching import aliases
    from tests.test_impact_graph import FACTS, FakeRouter

    db_session.add_all([
        Company(ticker="TWA.NS", name="Twin Alpha Limited", sector="other",
               index_tier="OTHER", tradeability="NORMAL"),
        Company(ticker="TWB.NS", name="Twin Alpha Limited", sector="other",
               index_tier="OTHER", tradeability="NORMAL"),
    ])
    db_session.commit()
    aliases.rebuild_aliases(db_session)

    router = FakeRouter({
        # event_type "earnings" (not in IMPACT_BROAD_EVENT_TYPES) routes to
        # the narrow single-call path -- cheapest way to reach the
        # subject-resolution step this test cares about.
        "extract_facts": dict(FACTS, event_type="earnings", named_entities=["Twin Alpha Limited"]),
        "narrow_graph": {"shocks": [], "edges": []},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert result.ambiguous_entities == ["Twin Alpha Limited"]


def test_candidate_pool_tags_source_by_ticker(db_session):
    """Corrective-v4 Task 18: `_candidate_pool` (the broad path's per-node
    candidate assembly) tags each returned ticker by which of its three
    pools produced it -- sector/exposure-ontology hint ("sector_pool"),
    the cross-sector relationship cache ("relationship_cache"), or the
    article's own named subjects ("subject", which overrides whatever tag
    the ticker already carried from the other two pools)."""
    from app.analysis.impact_graph.engine import _GraphState, _Node, _candidate_pool
    from app.analysis.impact_graph.schemas import EventFacts
    from app.models import CompanyNodeExposure

    sector_only = Company(ticker="SECTORONLY.NS", name="Sector Only Co", sector="oil_gas",
                          index_tier="NIFTY50", market="INDIA", tradeability="NORMAL", market_cap=1.0)
    subject_co = Company(ticker="SUBJECTCO.NS", name="Subject Co", sector="oil_gas",
                         index_tier="NIFTY50", market="INDIA", tradeability="NORMAL", market_cap=1.0)
    cached_co = Company(ticker="CACHEDCO.NS", name="Cached Co", sector="fmcg",
                        index_tier="NIFTY50", market="INDIA", tradeability="NORMAL", market_cap=1.0)
    db_session.add_all([sector_only, subject_co, cached_co])
    db_session.commit()
    db_session.add(CompanyNodeExposure(
        company_id=cached_co.id, node_key="crude_supply_shock", exposure_exists=1,
        strength=0.9, mechanism="verified exposure", verified_at=utcnow()))
    db_session.commit()

    facts = EventFacts(event="e", facts="f", category="oil_gas", event_type="geopolitics",
                       named_entities=["Subject Co"])
    state = _GraphState()
    # No sector -> the exposure-ontology hint path; "crude" in the node id
    # hints oil_gas (among others), which is where sector_only/subject_co
    # live.
    node = _Node(node_id="crude_supply_shock", node_type="economic_node",
                label="Crude supply shock", distance=1, materiality=0.8, confidence=0.8, sector=None)

    candidates, source_by_ticker = _candidate_pool(db_session, facts, state, node)

    tickers = {c.ticker for c in candidates}
    assert {"SECTORONLY.NS", "SUBJECTCO.NS", "CACHEDCO.NS"} <= tickers
    assert source_by_ticker["SECTORONLY.NS"] == "sector_pool"
    assert source_by_ticker["CACHEDCO.NS"] == "relationship_cache"
    # Subject identity wins even though this ticker is ALSO in the sector
    # pool.
    assert source_by_ticker["SUBJECTCO.NS"] == "subject"


def test_map_companies_for_node_relabels_sector_pool_to_frontier_on_ripple(db_session, monkeypatch):
    """A ripple/recursive call (node.distance >= 2) relabels the generic
    pool's "sector_pool" tag to "frontier" -- the pool was reached via
    _expand_frontier, not the anchor distance-1 mapping call."""
    import app.config as config
    from app.analysis.impact_graph.engine import _map_companies_for_node, _GraphState, _Node
    from app.analysis.impact_graph.schemas import EventFacts

    monkeypatch.setattr(config, "IMPACT_KNOWLEDGE_MODE", False)
    company = Company(ticker="RIPPLECO.NS", name="Ripple Co", sector="oil_gas",
                      index_tier="NIFTY50", market="INDIA", tradeability="NORMAL", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    facts = EventFacts(event="e", facts="f", category="oil_gas", event_type="geopolitics")
    from tests.test_impact_graph import FakeRouter

    router = FakeRouter({
        "map_companies": {"companies": [
            {"ticker": "RIPPLECO.NS", "name": "Ripple Co", "direction": "bearish",
             "impact_strength": 0.6, "confidence": 0.7, "materiality": 0.6,
             "time_horizon": "Short-Term", "mechanism": "m", "rationale": "r",
             "net_direction": "bearish"},
        ]},
    })
    state = _GraphState()
    node = _Node(node_id="oil_gas", node_type="sector", label="Oil & Gas",
                distance=2, materiality=0.7, confidence=0.7, sector="oil_gas")
    _map_companies_for_node(router, db_session, facts, state, node)

    assert "RIPPLECO.NS" in state.companies
    assert state.companies["RIPPLECO.NS"].discovery_source == "frontier"


def test_subject_fallback_stamps_discovery_source(db_session):
    from app.analysis.impact_graph.engine import _narrow_single_call, _GraphState
    from app.analysis.impact_graph.budget import ArticleBudget
    from app.analysis.impact_graph.schemas import EventFacts
    from tests.test_impact_graph import FakeRouter

    _company_row(db_session, ticker="LONER.NS", name="Loner Co", sector="fmcg")
    facts = EventFacts(
        event="Loner Co downgraded", event_status="confirmed", facts="rating cut",
        category="fmcg", event_type="earnings", named_entities=["Loner Co"],
    )
    router = FakeRouter({
        # A single shock (no edges) is needed so a distance-1 node exists
        # for the ARTICLE SUBJECT COMPANIES block to attach to -- with zero
        # nodes at all, _narrow_single_call short-circuits at its own
        # "no_candidates" skip before ever reaching the narrow_companies
        # call or the subject-fallback block below it. An empty
        # narrow_companies response is what actually triggers the
        # fallback: the mapping call ran and named nobody.
        "narrow_graph": {
            "shocks": [{"shock_id": "rating_cut", "label": "Rating cut",
                        "direction": "bearish", "mechanism": "m",
                        "confidence": 0.8, "materiality": 0.6, "impact_strength": 0.5}],
            "edges": [],
        },
        "narrow_companies": {"companies": []},
    })
    state = _GraphState()
    _narrow_single_call(router, db_session, facts, state, ArticleBudget(), None)

    assert state.companies, "subject fallback should have persisted the named company"
    company = state.companies["LONER.NS"]
    assert company.discovery_source == "subject_fallback"


# --- internal read path ----------------------------------------------------

_auth_seq = [0]


def _auth_headers(db) -> dict:
    """A real, persisted user + a real signed token -- the endpoint resolves
    the token against the DB, so a hand-made JWT for a nonexistent user is
    correctly rejected."""
    from app.auth.security import hash_password
    from app.auth.tokens import create_access_token

    _auth_seq[0] += 1
    user = User(email=f"auditor{_auth_seq[0]}@example.com",
                hashed_password=hash_password("pw12345"))
    db.add(user)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_audit_endpoint_404_when_flag_off(db_session, monkeypatch, strict_mode):
    monkeypatch.setattr(settings, "debug_audit_api", False)
    _company_row(db_session)
    alert = _persist(db_session, _result([_graph_company()]))

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.get(f"/api/internal/decisions/{alert.id}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_audit_endpoint_200_when_flag_on_with_parsed_json(db_session, monkeypatch, strict_mode):
    monkeypatch.setattr(settings, "debug_audit_api", True)
    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([_graph_company()]))

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.get(f"/api/internal/decisions/{alert.id}",
                              headers=_auth_headers(db_session))
        assert response.status_code == 200
        body = response.json()
        assert body["alert_id"] == alert.id
        assert len(body["decisions"]) == 1
        decision = body["decisions"][0]
        assert decision["final_state"] == "DISPLAY_ELIGIBLE"
        assert decision["ticker"] == "ONGC.NS"
        # JSON columns arrive PARSED, not as raw strings.
        assert isinstance(decision["gate_inputs"], dict)
        assert isinstance(decision["discovery_sources"], list)
    finally:
        app.dependency_overrides.clear()


def test_audit_endpoint_ordered_by_final_state_then_ticker(db_session, monkeypatch, strict_mode):
    monkeypatch.setattr(settings, "debug_audit_api", True)
    _company_row(db_session, ticker="AAA.NS", name="AAA Co", verified_node="crude_price")
    _company_row(db_session, ticker="BBB.NS", name="BBB Co", business_desc=None)
    result = _result([
        _graph_company(ticker="BBB.NS", name="BBB Co"),  # excluded (no profile)
        _graph_company(ticker="AAA.NS", name="AAA Co"),  # eligible
    ])
    alert = _persist(db_session, result)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    try:
        body = client.get(f"/api/internal/decisions/{alert.id}",
                          headers=_auth_headers(db_session)).json()
        states = [d["final_state"] for d in body["decisions"]]
        assert states == sorted(states)
    finally:
        app.dependency_overrides.clear()


# --- review-round fix: reuse copies the FULL completeness column set ------

def test_reuse_copies_gate_audit_trail_completeness_columns(db_session, strict_mode):
    """Review-round finding (CRITICAL): _copy_gate_audit_trail (the dedup-
    reuse path's audit-trail copy, corrective-v4 Task 12) was written
    before Task 18 added 7 completeness columns to CompanyDecisionRecord
    and never updated -- every reused alert's decision records silently
    lost gate_inputs_json/discovery_sources_json/evidence_ids_json/
    provider/model/analysis_quality/correction_json (left NULL). Now
    copied: the first 6 verbatim (they describe the SAME gate walk as
    candidate_json/analysis_version, which were already preserved
    verbatim); evidence_ids_json REMAPPED through the same evidence_id_map
    as candidate_json.evidence_ids, since its ids point at EvidenceRecord
    rows that get new ids under the new alert."""
    from app.pipeline import _copy_gate_audit_trail

    prior_article = Article(source="s", url="https://ex.com/prior-copy", title="t",
                            content="c", status="ANALYZED")
    db_session.add(prior_article)
    db_session.commit()
    prior_alert = Alert(article_id=prior_article.id, category="commodity")
    db_session.add(prior_alert)
    db_session.commit()
    evidence = EvidenceRecord(
        alert_id=prior_alert.id, company_id=None, source_type="article", source_name="article",
        fact_text="named subject of the article", evidence_class="ARTICLE_COMPANY_MENTION",
        evidence_tier="SUBJECT", supports_claim=True)
    db_session.add(evidence)
    db_session.commit()

    db_session.add(CompanyDecisionRecord(
        alert_id=prior_alert.id, company_id=None, ticker="ONGC.NS",
        final_state="DISPLAY_ELIGIBLE", display_tier="primary",
        rejection_reason=None, gates_passed_json=json.dumps(["ENTITY_VALID"]),
        evidence_class="ARTICLE_SUBJECT", materiality_grade="HIGH",
        candidate_json=json.dumps({"mechanism": "m", "evidence_ids": [evidence.id]}),
        analysis_version="kg-6/schema-1",
        gate_inputs_json=json.dumps({"ticker": "ONGC.NS", "entity_status": "resolved"}),
        evidence_ids_json=json.dumps([evidence.id]),
        discovery_sources_json=json.dumps(["subject"]),
        provider="gemini", model="gemini-3.1-pro-preview", analysis_quality="authoritative",
        correction_json=json.dumps({"materiality": 0.5}),
    ))
    db_session.commit()

    new_article = Article(source="s", url="https://ex.com/new-copy", title="t",
                          content="c", status="ANALYZED")
    db_session.add(new_article)
    db_session.commit()
    new_alert = Alert(article_id=new_article.id, category="commodity")
    db_session.add(new_alert)
    db_session.commit()

    _copy_gate_audit_trail(db_session, prior_alert.id, new_alert.id)

    prior = db_session.query(CompanyDecisionRecord).filter_by(alert_id=prior_alert.id).one()
    copied = db_session.query(CompanyDecisionRecord).filter_by(alert_id=new_alert.id).one()

    assert copied.gate_inputs_json == prior.gate_inputs_json
    assert copied.discovery_sources_json == prior.discovery_sources_json
    assert copied.provider == prior.provider
    assert copied.model == prior.model
    assert copied.analysis_quality == prior.analysis_quality
    assert copied.correction_json == prior.correction_json

    # evidence_ids_json is REMAPPED (new EvidenceRecord ids), never
    # literally byte-identical to the prior's -- it must resolve to a
    # real, freshly-copied row carrying the SAME content, and must never
    # be left pointing at the prior alert's own evidence.
    new_evidence_ids = json.loads(copied.evidence_ids_json)
    assert new_evidence_ids != json.loads(prior.evidence_ids_json)
    new_evidence = db_session.get(EvidenceRecord, new_evidence_ids[0])
    assert new_evidence.alert_id == new_alert.id
    assert new_evidence.fact_text == evidence.fact_text
    # candidate_json's own evidence_ids must point at the SAME copied
    # row -- the two columns never drift apart from each other post-copy.
    assert json.loads(copied.candidate_json)["evidence_ids"] == new_evidence_ids


# --- final-review finding I11: the flag is not authorization ---------------

def test_audit_endpoint_401_when_flag_on_but_unauthenticated(db_session, monkeypatch, strict_mode):
    """Flag ON is not authorization. These rows are full CandidateInput
    dumps, rationale text and mechanism prose -- an anonymous caller who
    knows the path must get 401, not the audit trail."""
    monkeypatch.setattr(settings, "debug_audit_api", True)
    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([_graph_company()]))

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.get(f"/api/internal/decisions/{alert.id}")
        assert response.status_code == 401
        assert "decisions" not in response.json()
    finally:
        app.dependency_overrides.clear()


def test_audit_endpoint_401_on_a_garbage_token(db_session, monkeypatch, strict_mode):
    """An unparseable/expired bearer token is not authentication either --
    get_current_user_optional resolves it to None and the endpoint refuses,
    rather than treating "a header was present" as good enough."""
    monkeypatch.setattr(settings, "debug_audit_api", True)
    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([_graph_company()]))

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.get(f"/api/internal/decisions/{alert.id}",
                              headers={"Authorization": "Bearer not-a-real-token"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_audit_endpoint_still_404s_for_an_authenticated_user_when_flag_off(
        db_session, monkeypatch, strict_mode):
    """ORDER PIN: the flag check runs FIRST, so a flag-off deployment reads
    identically to "this route does not exist" -- for authenticated and
    anonymous callers alike. If the auth check ever moves ahead of it (e.g.
    by becoming a declared Depends), an anonymous 401 would tell the world
    the endpoint exists; this test and the 404 test above fail together."""
    monkeypatch.setattr(settings, "debug_audit_api", False)
    _company_row(db_session, verified_node="crude_price")
    alert = _persist(db_session, _result([_graph_company()]))

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    try:
        headers = _auth_headers(db_session)
        assert client.get(f"/api/internal/decisions/{alert.id}",
                          headers=headers).status_code == 404
        assert client.get(f"/api/internal/decisions/{alert.id}").status_code == 404
    finally:
        app.dependency_overrides.clear()
