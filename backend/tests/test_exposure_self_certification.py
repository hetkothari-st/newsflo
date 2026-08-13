"""Corrective-v4 Task 6: breaks the exposure self-certification loop.

Before this task, a CompanyNodeExposure row written after ONE LLM verifier
acceptance became a standing "verified" fact: it auto-accepted the same
candidate on every future event (engine._verify_companies' relationship-
cache bypass) AND could be read back as VERIFIED_RELATIONSHIP evidence at
the publication gate. Prior LLM acceptance certified itself forever,
without ever facing a current event's verification again.

These tests pin the fix: every candidate faces THIS event's verification
regardless of cache history; a cached row is a PRIOR (candidacy + prompt
hint only), never itself evidence, unless it carries real independent
provenance (SUPPLY_LINK/MANUAL/CURATED); and a prior expires (review_after)
so acceptance cannot compound indefinitely."""
from datetime import date, timedelta

import pytest

from app.config import settings
from app.models import Company, CompanyNodeExposure, utcnow


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas", **kw):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50", **kw)
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
    )
    payload.update(overrides)
    return GraphCompany(**payload)


# --- gate-level: a prior LLM acceptance cannot re-certify a new candidate --

def test_prior_llm_acceptance_cannot_self_certify(db_session, strict_mode):
    """A MODEL_VERIFIED row written by an earlier event's verifier must not
    substitute for THIS event's verification. A fresh candidate on the same
    node that the current-event verifier did NOT accept (verified=False)
    must be rejected -- and must never earn VERIFIED_RELATIONSHIP evidence
    from the cache row alone."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.pipeline import _v3_entries

    row = _company(db_session, business_desc="Upstream oil and gas explorer")
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure",
        provenance_type="MODEL_VERIFIED", verified_at=utcnow()))
    db_session.commit()

    company = _graph_company(verified=False)
    evidence_class, _tier, _payloads = classify_evidence(db_session, company, set())
    assert evidence_class != "VERIFIED_RELATIONSHIP"

    from app.analysis.impact_graph.schemas import ImpactGraphResult
    result = ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=[],
        companies=[company],
        edges=[_edge_from_event_to("crude_price")],
        gaps=[], ranking=[], analysis_provider="gemini",
        analysis_quality="authoritative", metrics={},
    )
    entries = _v3_entries(db_session, result)
    assert entries[0]["gate_state"] == "REJECT_UNVERIFIED"


def _edge_from_event_to(node_id):
    from app.analysis.impact_graph.schemas import GraphEdge
    return GraphEdge(
        parent_type="event", parent_id="crude_supply_shock",
        child_type="economic_node", child_id=node_id,
        direction="bullish", economic_effect="positive",
        mechanism="supply disruption raises crude price", causal_distance=1,
        impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term",
    )


# --- engine-level: the cache no longer flips verified=True by itself -----

def test_cached_row_no_longer_flips_verified_true(db_session):
    """Before Task 6, a positive relationship-cache row auto-accepted the
    candidate without ever calling the verifier. Now the verifier is
    always called, and its verdict -- not the cache -- decides."""
    from tests.test_impact_graph import FakeRouter, _company as _co, _company_entry
    from tests.test_impact_graph_optimization import _direct_sector_setup
    from app.analysis.impact_graph.engine import analyze_article_v3

    row = _co(db_session, "CACHED.NS", "Cached Co", "oil_gas")
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="oil_gas", exposure_exists=1, strength=0.7,
        mechanism="crude input exposure", provenance_type="MODEL_VERIFIED",
        verified_at=utcnow()))
    db_session.commit()

    router = FakeRouter(_direct_sector_setup({
        "map_companies": {"companies": [_company_entry("CACHED.NS", "Cached Co")]},
        "verify_companies": {"accept": [], "reject": [
            {"ticker": "CACHED.NS", "reason": "not material for this specific event"},
        ]},
    }))
    result = analyze_article_v3(router, "t", "c", session=db_session)

    # The verifier ran (no bypass) and its rejection was honored, not
    # overridden by the cache's earlier positive verdict.
    assert "verify_companies" in router.calls
    assert result.companies == []


# --- freshness: review_after expiry downgrades a row exactly like staleness

def test_review_after_expiry_downgrades_row(db_session, strict_mode):
    """A MODEL_VERIFIED row past its own review_after checkpoint is
    unusable, the same as a row invalidated by metadata staleness -- the
    self-certification fix must not compound forever even within the
    freshness window's own bookkeeping."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.impact_graph.exposure import exposure_row_is_fresh

    row = _company(db_session)
    cached = CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure",
        provenance_type="MODEL_VERIFIED",
        verified_at=utcnow() - timedelta(days=100),
        review_after=utcnow() - timedelta(days=10))
    db_session.add(cached)
    db_session.commit()

    assert exposure_row_is_fresh(cached, row) is False

    company = _graph_company()
    evidence_class, _tier, payloads = classify_evidence(db_session, company, set())
    # The row exists but is stale -- classify_evidence falls through
    # exactly as if there were no row at all.
    assert evidence_class != "MODEL_VERIFIED_PRIOR"
    assert evidence_class != "VERIFIED_RELATIONSHIP"
    assert payloads == []


# --- legacy NULL-provenance rows are priors, not permanent authority -----

def test_legacy_null_provenance_is_not_permanently_authoritative(db_session, strict_mode):
    """A row from before provenance shipped (provenance_type NULL) is
    classified LEGACY_UNVERIFIED -- Tier D, candidacy-only -- never
    VERIFIED_RELATIONSHIP, no matter how long it has stood unquestioned."""
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure", verified_at=utcnow()))
    db_session.commit()

    company = _graph_company()
    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert evidence_class == "LEGACY_UNVERIFIED"
    assert evidence_tier == "D"
    assert payloads == []
    assert evidence_class != "VERIFIED_RELATIONSHIP"


# --- the provenanced-row Tier-C escape itself (review finding) -----------
# The tests above pin that MODEL_VERIFIED / NULL provenance can NEVER reach
# Tier C. These pin the one branch that CAN: a CompanyNodeExposure row
# whose provenance_type names an independently-sourced relationship
# (SUPPLY_LINK/MANUAL/CURATED) -- evidence.py:124-137. Every existing
# Tier-C test in this codebase exercises the separate SupplyLink-TABLE
# branch (a JOIN against app.models.SupplyLink); none of them touch this
# CompanyNodeExposure-column branch at all.

def test_provenanced_exposure_row_yields_real_tier_c_payload(db_session, strict_mode):
    """A fresh SUPPLY_LINK-provenanced CompanyNodeExposure row (in review_
    after, not yet expired) is the ONE thing that can carry a company-node
    exposure to Tier C. The payload must cite the row's own fields
    verbatim -- nothing fabricated (INV: no invented citation, same
    discipline as SupplyLink evidence)."""
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session)
    cached = CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="CRISIL rating rationale: upstream crude realization",
        provenance_type="SUPPLY_LINK",
        source_url="https://crisil.example/ongc-rationale",
        source_date=date(2026, 6, 1),
        verified_at=utcnow(), review_after=utcnow() + timedelta(days=90))
    db_session.add(cached)
    db_session.commit()

    company = _graph_company()
    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert evidence_class == "VERIFIED_RELATIONSHIP"
    assert evidence_tier == "C"
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["source_url"] == cached.source_url
    assert payload["source_date"] == cached.source_date
    assert payload["fact_text"] == cached.mechanism
    assert payload["source_name"] == "SUPPLY_LINK"
    assert payload["supports_claim"] is True


def test_stale_provenanced_row_does_not_yield_tier_c(db_session, strict_mode):
    """The SAME provenanced row, but past its own review_after: staleness
    (spec §8, unified via exposure_row_is_fresh) gates entry into the
    whole exposure branch, provenanced or not -- a stale row is not usable
    evidence at all, so classify_evidence falls through exactly as if
    there were no row (it does NOT downgrade to the MODEL_VERIFIED_PRIOR/D
    label, which would misrepresent an expired independently-sourced row
    as the model's own weaker prior)."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.impact_graph.exposure import exposure_row_is_fresh

    row = _company(db_session)
    cached = CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="CRISIL rating rationale: upstream crude realization",
        provenance_type="SUPPLY_LINK",
        source_url="https://crisil.example/ongc-rationale",
        source_date=date(2026, 6, 1),
        verified_at=utcnow() - timedelta(days=100),
        review_after=utcnow() - timedelta(days=1))
    db_session.add(cached)
    db_session.commit()

    assert exposure_row_is_fresh(cached, row) is False

    company = _graph_company()
    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert evidence_class != "VERIFIED_RELATIONSHIP"
    assert evidence_tier != "C"
    assert evidence_class != "MODEL_VERIFIED_PRIOR"  # falls through, not downgraded
    assert payloads == []


@pytest.mark.parametrize("provenance_type", ["MANUAL", "CURATED"])
def test_other_provenanced_types_also_yield_tier_c(db_session, strict_mode, provenance_type):
    """The escape is not SUPPLY_LINK-specific -- any independently-sourced
    provenance value (MANUAL, CURATED) earns the same Tier C."""
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="analyst-confirmed exposure",
        provenance_type=provenance_type, source_url="https://example.com/source",
        source_date=date(2026, 6, 1), verified_at=utcnow(),
        review_after=utcnow() + timedelta(days=90)))
    db_session.commit()

    company = _graph_company()
    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert evidence_class == "VERIFIED_RELATIONSHIP"
    assert evidence_tier == "C"
    assert payloads[0]["source_name"] == provenance_type


def test_provenanced_exposure_row_reaches_gate_as_primary_at_d2(db_session, strict_mode):
    """End-to-end: the escape must not just classify as Tier C in
    isolation -- it must actually reach the publication gate and unlock
    primary at causal distance 2 (RELATIONSHIP_TIERS + HIGH materiality,
    publication_gate._primary_authorized), the same authority a SupplyLink-
    table row has. This is the CompanyNodeExposure-column escape, not the
    separate SupplyLink-table join classify_evidence also supports."""
    from app.analysis.impact_graph.schemas import GraphEdge, ImpactGraphResult
    from app.pipeline import _v3_entries

    parent = _company(db_session, ticker="PARENT.NS", name="Parent Co", sector="auto")
    supplier = _company(db_session, ticker="SUPPLIER.NS", name="Supplier Co",
                        sector="auto_components")
    # node_key = the parent ticker: the same row both (a) satisfies
    # BUSINESS_MODEL_VALID for the supplier candidate (exposure_row_is_fresh
    # via app.pipeline._company_profile_supports_mechanism) and (b) is what
    # classify_evidence reads back as Tier C evidence -- one real row, two
    # honest readers.
    db_session.add(CompanyNodeExposure(
        company_id=supplier.id, node_key="PARENT.NS", exposure_exists=1,
        strength=0.8, mechanism="rating-agency confirmed tier-1 supplier exposure",
        provenance_type="SUPPLY_LINK", source_url="https://crisil.example/rationale",
        source_date=date(2026, 6, 1), verified_at=utcnow(),
        review_after=utcnow() + timedelta(days=90)))
    db_session.commit()

    d2 = _graph_company(
        ticker="SUPPLIER.NS", name="Supplier Co", causal_distance=2, materiality=0.8,
        parent_type="company", parent_id="PARENT.NS",
        mechanism="volume cut at Parent reduces component offtake",
        rationale="tier-1 supplier to the affected OEM",
    )
    edges = [GraphEdge(
        parent_type="event", parent_id="demand_shock", child_type="company",
        child_id="PARENT.NS", direction="bearish", economic_effect="negative",
        mechanism="demand shock hits Parent's volumes", causal_distance=1,
        impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term",
    )]
    result = ImpactGraphResult(
        category="auto", event_type="demand_shock", facts="parent demand shock",
        event_label="parent demand shock", named_entities=[],
        companies=[d2], edges=edges, gaps=[], ranking=[],
        analysis_provider="gemini", analysis_quality="authoritative", metrics={},
    )
    entries = _v3_entries(db_session, result)

    assert entries[0]["evidence_class"] == "VERIFIED_RELATIONSHIP"
    assert entries[0]["display_tier"] == "primary"
    assert entries[0]["gate_state"] == "DISPLAY_ELIGIBLE"


# --- prompt annotation must not overclaim -----------------------------

def test_prompt_prior_label_does_not_claim_verified():
    """The candidate-profile line the model sees for a cached row must be
    honest about what the cache actually is: MODEL_VERIFIED/NULL rows are
    an unconfirmed prior the model itself produced, never a "verified"
    fact -- only a provenanced row (SUPPLY_LINK/MANUAL/CURATED) may use
    that word."""
    from types import SimpleNamespace

    from app.analysis.impact_graph.engine import _candidate_profile_lines

    candidate = SimpleNamespace(
        ticker="ONGC.NS", name="ONGC", sub_sector=None, business_desc=None)

    model_prior = SimpleNamespace(
        mechanism="crude realization uplift", provenance_type="MODEL_VERIFIED")
    lines = _candidate_profile_lines([candidate], {"ONGC.NS": model_prior})
    assert "PRIOR EXPOSURE (model-derived, unconfirmed)" in lines
    assert "KNOWN BASE EXPOSURE" not in lines
    assert "verified:" not in lines.lower()

    legacy_null = SimpleNamespace(mechanism="legacy row", provenance_type=None)
    lines_legacy = _candidate_profile_lines([candidate], {"ONGC.NS": legacy_null})
    assert "PRIOR EXPOSURE (model-derived, unconfirmed)" in lines_legacy
    assert "verified:" not in lines_legacy.lower()

    provenanced = SimpleNamespace(
        mechanism="rating-agency confirmed exposure", provenance_type="SUPPLY_LINK")
    lines_provenanced = _candidate_profile_lines([candidate], {"ONGC.NS": provenanced})
    assert "VERIFIED EXPOSURE (provenanced)" in lines_provenanced
