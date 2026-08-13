"""Phase 4 (spec §7/§8/§9): exposure provenance, staleness discipline, and
de-circularization. The exposure registry proposes; only evidence
authorizes. Every CompanyNodeExposure reader must apply the same staleness
rule, archetype-sourced candidates carry their provenance into the gate,
and the SupplyLink corpus (the repo's only verbatim-evidence store)
finally reaches the live path -- as evidence, never as a proposer."""
from datetime import date, timedelta

import pytest

from app.config import settings
from app.models import Company, CompanyNodeExposure, SupplyLink, utcnow


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas", **kw):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50", **kw)
    db.add(row)
    db.commit()
    return row


def _exposure(db, company, node_key="crude_price", verified_at=None, **kw):
    row = CompanyNodeExposure(
        company_id=company.id, node_key=node_key, exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure",
        verified_at=verified_at or utcnow(), **kw)
    db.add(row)
    db.commit()
    return row


# --- knowledge registry integrity (bug: dead archetype) -------------------

def test_event_archetype_event_types_exist_in_enum():
    """Every EVENT_ARCHETYPES event_type must be a member of the facts
    stage's EVENT_TYPES enum -- a stale token silently kills the archetype
    (production bug: 'geopolitical_conflict' vs 'geopolitics')."""
    from app.analysis.impact_graph.knowledge import EVENT_ARCHETYPES
    from app.analysis.schemas import EVENT_TYPES

    for name, archetype in EVENT_ARCHETYPES.items():
        for event_type in archetype["event_types"]:
            assert event_type in EVENT_TYPES, (
                f"{name} references unknown event_type {event_type!r}")


def test_broad_event_types_exist_in_enum():
    from app.analysis.schemas import EVENT_TYPES
    from app.config import IMPACT_BROAD_EVENT_TYPES

    for event_type in IMPACT_BROAD_EVENT_TYPES:
        assert event_type in EVENT_TYPES, (
            f"IMPACT_BROAD_EVENT_TYPES references unknown event_type {event_type!r}")


def test_geopolitics_matches_supply_disruption_archetype():
    from app.analysis.impact_graph.knowledge import match_event_archetype
    from app.analysis.impact_graph.schemas import EventFacts

    facts = EventFacts(
        event="Strait of Hormuz blockade",
        facts="Strait of Hormuz blockade disrupts shipping and crude supply",
        category="commodity", event_type="geopolitics")
    match = match_event_archetype(facts)
    assert match is not None
    archetype_id, _direction = match
    assert archetype_id == "GEOPOLITICAL_SUPPLY_DISRUPTION"


# --- staleness applied by EVERY reader (bug: 1 of 4) ----------------------

def test_cached_exposed_companies_skips_stale_rows(db_session):
    """A row verified before the company's business description changed is
    unusable everywhere -- not only in the one reader that checked."""
    from app.analysis.impact_graph.exposure import cached_exposed_companies

    fresh = _company(db_session, ticker="FRESH.NS", name="Fresh Co")
    stale = _company(db_session, ticker="STALE.NS", name="Stale Co",
                     business_desc_as_of=date.today())
    _exposure(db_session, fresh)
    _exposure(db_session, stale, verified_at=utcnow() - timedelta(days=30))

    tickers = [c.ticker for c in cached_exposed_companies(db_session, "crude_price")]
    assert "FRESH.NS" in tickers
    assert "STALE.NS" not in tickers


def test_evidence_classification_skips_stale_rows(db_session, strict_mode):
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.impact_graph.schemas import GraphCompany

    stale = _company(db_session, ticker="STALE.NS", name="Stale Co",
                     business_desc_as_of=date.today())
    _exposure(db_session, stale, verified_at=utcnow() - timedelta(days=30))
    company = GraphCompany(
        ticker="STALE.NS", name="Stale Co", direction="bullish",
        impact_strength=0.7, confidence=0.8, materiality=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node",
        parent_id="crude_price", mechanism="crude realization uplift mechanism",
        rationale="upstream producer", net_direction="bullish",
        economic_effect="positive", verified=True)

    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())
    assert (evidence_class, evidence_tier, payloads) == ("MODEL_INFERENCE", "E", [])


# --- provenance on exposure writes ----------------------------------------

def test_exposure_cache_write_stamps_provenance(db_session):
    """New CompanyNodeExposure rows record how they were established.
    provenance_type is MODEL_VERIFIED (corrective-v4 Task 6): this row is
    the verifier's own acceptance of one candidate for one event, never an
    independently-sourced fact -- VERIFIED_RELATIONSHIP is reserved for
    provenance a SupplyLink or other real artifact establishes."""
    from app.analysis.impact_graph.engine import _write_exposure_cache
    from app.analysis.impact_graph.schemas import GraphCompany

    row = _company(db_session)
    company = GraphCompany(
        ticker="ONGC.NS", name="ONGC", direction="bullish",
        impact_strength=0.7, confidence=0.8, materiality=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node",
        parent_id="crude_price", mechanism="crude realization uplift mechanism",
        rationale="upstream producer", verified=True)
    _write_exposure_cache(db_session, company, exposure_exists=True, alert_id=7)

    stored = db_session.query(CompanyNodeExposure).filter_by(company_id=row.id).one()
    assert stored.provenance_type == "MODEL_VERIFIED"
    assert stored.source_alert_id == 7
    assert stored.review_after is not None


# --- archetype provenance reaches the gate --------------------------------

def test_archetype_discovery_source_classifies_as_curated(db_session, strict_mode):
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.impact_graph.schemas import GraphCompany

    _company(db_session, ticker="MRF.NS", name="MRF", sector="auto")
    company = GraphCompany(
        ticker="MRF.NS", name="MRF", direction="bearish",
        impact_strength=0.7, confidence=0.8, materiality=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node",
        parent_id="tyre_input_cost", mechanism="crude-linked rubber and carbon black input costs",
        rationale="tyre maker with crude-derived input basket",
        net_direction="bearish", economic_effect="negative", verified=True,
        discovery_source="archetype:tyre_input_cost")

    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())
    assert (evidence_class, evidence_tier, payloads) == ("CURATED_ARCHETYPE", "D", [])


# --- exposure seed actually runs (bug: never called in production) --------

def test_ensure_exposure_seed_populates_and_is_idempotent(db_session):
    """seed_company_exposures existed but had no production caller, so the
    company_exposures table was empty and the archetype eligibility gate
    silently no-oped. ensure_exposure_seed seeds once per registry
    version and is a cheap no-op afterwards."""
    from app.analysis.impact_graph.knowledge import ensure_exposure_seed
    from app.models import CompanyExposure

    _company(db_session, ticker="IOC.NS", name="Indian Oil Corporation",
             sector="oil_gas", sub_sector="refining_marketing")

    first = ensure_exposure_seed(db_session)
    assert first > 0
    assert db_session.query(CompanyExposure).count() > 0

    assert ensure_exposure_seed(db_session) == 0  # second call: no-op


# --- SupplyLink as Tier-A evidence (dark corpus wired in) -----------------

def test_supply_link_evidence_upgrades_company_parent_candidates(db_session, strict_mode):
    """A candidate hanging off a parent COMPANY with a verbatim-evidence
    SupplyLink between the two carries Tier-A relationship evidence
    (spec §9). Evidence only -- the graph proposed the candidate, the
    link never does (no-auto-attribution preserved)."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.impact_graph.schemas import GraphCompany

    parent = _company(db_session, ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto")
    supplier = _company(db_session, ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                        sector="auto_components")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    company = GraphCompany(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson", direction="bearish",
        impact_strength=0.6, confidence=0.8, materiality=0.6, causal_distance=2,
        time_horizon="Short-Term", parent_type="company", parent_id="MARUTI.NS",
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM",
        net_direction="bearish", economic_effect="negative", verified=True)

    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())
    assert evidence_class == "VERIFIED_RELATIONSHIP"
    assert evidence_tier == "C"
    assert len(payloads) == 1
    assert payloads[0]["source_url"] == "https://crisil.example/rationale"
