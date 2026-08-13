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
        # These tests exercise the exposure-cache self-certification gates,
        # not COUNTERFACTUAL_VALID -- a verifier-delivered SUPPORTED keeps
        # that gate a non-factor (GraphCompany now defaults
        # counterfactual="", the "verifier never reached this company"
        # fail-closed state, corrective-v4 Task 9).
        counterfactual="SUPPORTED",
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


# --- self-echo guard (owner-ruled cross-finding, T19/T20 audit) ----------
# CompanyNodeExposure rows are read BEFORE the ARTICLE_SUBJECT check
# (evidence.py step 3 precedes step 4), and _write_exposure_cache stamps a
# fresh MODEL_VERIFIED row for every candidate _verify_companies accepts --
# in the SAME session, BEFORE app.pipeline._gate_candidates ever calls
# classify_evidence. Without the guard below, an accepted, article-central
# candidate could self-echo straight to Tier D and could never classify
# ARTICLE_SUBJECT (SUBJECT, primary-capable).
#
# The signal is `fresh_cache_tickers` -- exactly the tickers `_write_
# exposure_cache` touched THIS run (engine._GraphState.fresh_cache_
# tickers, threaded via ImpactGraphResult) -- NOT `company.verified`
# generally. That broader flag was the plan round's first suggestion but
# measured wrong against this very test file: `_graph_company(verified=
# True)` paired with a CompanyNodeExposure row set up directly by the test
# (as every other test in this file does, to simulate a genuine prior) is
# the standard fixture shape here, and it never calls `_write_exposure_
# cache` at all -- using `.verified` as the signal would have wrongly
# excluded every one of those rows too.

def test_fresh_cache_ticker_subject_classifies_article_subject_not_prior(db_session, strict_mode):
    """A ticker THIS run's `_write_exposure_cache` actually wrote to (so
    the row sitting here may well BE that exact write) must classify by
    what it actually IS -- the article's own named subject -- not by its
    own just-written self-echo."""
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session, business_desc="Upstream oil and gas explorer")
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure",
        provenance_type="MODEL_VERIFIED", verified_at=utcnow()))
    db_session.commit()

    company = _graph_company(verified=True)
    evidence_class, evidence_tier, payloads = classify_evidence(
        db_session, company, subject_tickers={"ONGC.NS"},
        fresh_cache_tickers=frozenset({"ONGC.NS"}))

    assert evidence_class == "ARTICLE_SUBJECT"
    assert evidence_tier == "SUBJECT"
    assert payloads and payloads[0]["fact_text"] == "named subject of the article"
    assert evidence_class != "MODEL_VERIFIED_PRIOR"


def test_genuinely_prior_row_still_classifies_as_d_prior(db_session, strict_mode):
    """A row `_write_exposure_cache` did NOT just touch this run -- a
    different, older alert's acceptance -- is unaffected by the guard:
    still classifies MODEL_VERIFIED_PRIOR / D exactly as before the fix.
    `fresh_cache_tickers` deliberately does NOT contain this ticker,
    modeling "some OTHER candidate's cache write happened this run, not
    this one" (this row genuinely predates the current analysis)."""
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session, business_desc="Upstream oil and gas explorer")
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure",
        provenance_type="MODEL_VERIFIED", verified_at=utcnow(),
        source_alert_id=4242))  # an older, unrelated alert
    db_session.commit()

    company = _graph_company(verified=True)
    # This ticker is NOT a subject and NOT in fresh_cache_tickers this run
    # (a different candidate's cache write happened instead) -- the
    # genuinely prior row still stands.
    evidence_class, evidence_tier, payloads = classify_evidence(
        db_session, company, subject_tickers=set(),
        fresh_cache_tickers=frozenset({"SOMEOTHER.NS"}))

    assert evidence_class == "MODEL_VERIFIED_PRIOR"
    assert evidence_tier == "D"
    assert payloads == []

    # And the default call (no fresh_cache_tickers argument at all --
    # every pre-existing caller/test in this module, including every OTHER
    # test in this very file) is unaffected too.
    evidence_class_default, _tier, _payloads = classify_evidence(db_session, company, set())
    assert evidence_class_default == "MODEL_VERIFIED_PRIOR"


def test_engine_level_fresh_write_threads_through_to_gate_as_subject(db_session, strict_mode):
    """End-to-end (not just the classify_evidence unit): a REAL
    analyze_article_v3 run that verifies and cache-writes a company which
    is ALSO the article's own subject reaches the publication gate
    classified ARTICLE_SUBJECT, not MODEL_VERIFIED_PRIOR -- the fix as it
    actually operates through the full pipeline, not only via a hand-fed
    `fresh_cache_tickers` argument."""
    from tests.test_impact_graph import FACTS, FakeRouter, _company as _co, _company_entry
    from tests.test_impact_graph_optimization import _direct_sector_setup
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.pipeline import _v3_entries

    _co(db_session, "CACHED.NS", "Cached Co", "oil_gas")

    router = FakeRouter(_direct_sector_setup({
        "extract_facts": dict(FACTS, named_entities=["Cached Co"]),
        "map_companies": {"companies": [_company_entry("CACHED.NS", "Cached Co")]},
        "verify_companies": {"accept": ["CACHED.NS"], "reject": [],
                             "counterfactual": {"CACHED.NS": "SUPPORTED"}},
    }))
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert result.companies and result.companies[0].verified is True
    assert "CACHED.NS" in result.fresh_cache_tickers, (
        "the verifier accepted this company -- _write_exposure_cache must have run for it")

    entries = _v3_entries(db_session, result)
    assert entries[0]["evidence_class"] == "ARTICLE_SUBJECT"
    assert entries[0]["evidence_class"] != "MODEL_VERIFIED_PRIOR"


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


def _naive_utc(value):
    """SQLite round-trips DateTime(timezone=True) as NAIVE UTC, so a value
    read back from the DB cannot be compared against an aware utcnow()
    directly. Normalise both sides to naive UTC rather than asserting on
    string equality."""
    return value.replace(tzinfo=None) if getattr(value, "tzinfo", None) else value


# --- protected provenance is READ-ONLY to the cache writer ---------------
# Corrective-v4 Task 21 review, owner ruling. _write_exposure_cache used to
# stamp provenance_type="MODEL_VERIFIED" over EVERY existing row on upsert,
# including the SUPPLY_LINK/MANUAL/CURATED rows that are the only kind
# classify_evidence may grant Tier C for. Because the writer runs inside the
# engine and app.pipeline._gate_candidates runs after it, a curated row was
# already downgraded by the time the gate read it -- AND the ticker was in
# fresh_cache_tickers, so the self-echo guard skipped the row entirely. Net
# effect: a curated exposure record could not survive one analysis pass, and
# SupplyLink was the only Tier-C route that worked in practice.

@pytest.mark.parametrize("provenance_type", ["SUPPLY_LINK", "MANUAL", "CURATED"])
def test_protected_row_survives_a_verified_model_run_untouched(db_session, provenance_type):
    """A curated/manual/supply-link row is left EXACTLY as it was: same
    provenance, same recorded terms, and -- importantly -- the same
    review_after, since a model run must not extend a curated row's review
    life."""
    from app.analysis.impact_graph.engine import _write_exposure_cache

    row = _company(db_session, business_desc="Upstream oil and gas explorer")
    curated_at = utcnow() - timedelta(days=30)
    curated_review = curated_at + timedelta(days=365)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.9, mechanism="curated: crude realization exposure",
        provenance_type=provenance_type, source_url="https://curated.example/note",
        verified_at=curated_at, review_after=curated_review,
        verification_version="curated-v1"))
    db_session.commit()

    wrote = _write_exposure_cache(
        db_session, _graph_company(impact_strength=0.1,
                                   mechanism="model's own per-event wording"),
        exposure_exists=True, alert_id=99)
    db_session.commit()

    assert wrote is False, "a protected row must report that nothing was written"
    cached = db_session.query(CompanyNodeExposure).one()
    assert cached.provenance_type == provenance_type
    assert cached.strength == 0.9
    assert cached.mechanism == "curated: crude realization exposure"
    assert cached.verification_version == "curated-v1"
    assert cached.source_alert_id is None
    # Review life is NOT extended by an automated pass.
    assert _naive_utc(cached.review_after) == _naive_utc(curated_review)
    assert _naive_utc(cached.verified_at) == _naive_utc(curated_at)


def test_protected_row_still_classifies_tier_c_after_a_verified_run(db_session, strict_mode):
    """The point of the fix, stated as the outcome that matters: run the
    writer exactly as _verify_companies does for an accepted company, then
    classify -- the row must still be VERIFIED_RELATIONSHIP / C."""
    from app.analysis.impact_graph.engine import _write_exposure_cache
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session, business_desc="Upstream oil and gas explorer")
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.9, mechanism="curated: crude realization exposure",
        provenance_type="CURATED", source_url="https://curated.example/note",
        verified_at=utcnow(), review_after=utcnow() + timedelta(days=365)))
    db_session.commit()

    company = _graph_company()
    _write_exposure_cache(db_session, company, exposure_exists=True, alert_id=7)
    db_session.commit()

    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert (evidence_class, evidence_tier) == ("VERIFIED_RELATIONSHIP", "C")
    assert payloads and payloads[0]["source_name"] == "CURATED"


def test_model_verified_and_null_rows_still_update_as_before(db_session):
    """The fix is narrow: an ordinary MODEL_VERIFIED row (and a legacy
    NULL-provenance one) keeps being refreshed exactly as it always was."""
    from app.analysis.impact_graph.engine import _write_exposure_cache

    row = _company(db_session)
    stale_at = utcnow() - timedelta(days=80)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.2, mechanism="old wording", provenance_type="MODEL_VERIFIED",
        verified_at=stale_at, review_after=stale_at + timedelta(days=90)))
    db_session.commit()

    wrote = _write_exposure_cache(
        db_session, _graph_company(impact_strength=0.77, mechanism="fresh wording"),
        exposure_exists=True, alert_id=42)
    db_session.commit()

    assert wrote is True
    cached = db_session.query(CompanyNodeExposure).one()
    assert cached.strength == 0.77
    assert cached.mechanism == "fresh wording"
    assert cached.provenance_type == "MODEL_VERIFIED"
    assert cached.source_alert_id == 42
    assert _naive_utc(cached.verified_at) > _naive_utc(stale_at)
    assert _naive_utc(cached.review_after) > _naive_utc(stale_at + timedelta(days=90))

    # A legacy NULL-provenance row is a prior too, not protected: it is
    # upgraded to MODEL_VERIFIED on the next write, unchanged behaviour.
    other = _company(db_session, ticker="LEGACY.NS", name="Legacy Co")
    db_session.add(CompanyNodeExposure(
        company_id=other.id, node_key="crude_price", exposure_exists=1,
        strength=0.3, mechanism="legacy", provenance_type=None, verified_at=stale_at))
    db_session.commit()

    assert _write_exposure_cache(
        db_session, _graph_company(ticker="LEGACY.NS", name="Legacy Co"),
        exposure_exists=True, alert_id=43) is True
    db_session.commit()
    legacy = (db_session.query(CompanyNodeExposure)
              .filter_by(company_id=other.id).one())
    assert legacy.provenance_type == "MODEL_VERIFIED"


def test_negative_write_cannot_kill_a_curated_relationship(db_session):
    """A structural verifier rejection writes exposure_exists=0, which
    _exposure_cache reads as "do not even offer this company as a candidate"
    on future events. One model rejection must not be able to delete a
    human-established relationship: the model judged THIS event's claim, not
    the existence of the link."""
    from app.analysis.impact_graph.engine import _write_exposure_cache

    row = _company(db_session)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.9, mechanism="curated: crude realization exposure",
        provenance_type="SUPPLY_LINK", verified_at=utcnow(),
        review_after=utcnow() + timedelta(days=365)))
    db_session.commit()

    wrote = _write_exposure_cache(db_session, _graph_company(),
                                  exposure_exists=False, alert_id=11)
    db_session.commit()

    assert wrote is False
    cached = db_session.query(CompanyNodeExposure).one()
    assert cached.exposure_exists == 1
    assert cached.provenance_type == "SUPPLY_LINK"
    assert cached.strength == 0.9


def test_skipped_protected_write_is_not_recorded_as_a_self_echo(db_session, strict_mode):
    """End-to-end through the real engine: an accepted company whose only
    cache row is CURATED must NOT land in fresh_cache_tickers -- that set
    exists to discount the writes THIS RUN made, and no write happened. The
    consequence is the whole point: classify_evidence still reads the row,
    so the candidate keeps its Tier-C evidence instead of falling through to
    model inference."""
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.pipeline import _v3_entries
    from tests.test_impact_graph import FACTS, FakeRouter, _company as _co, _company_entry
    from tests.test_impact_graph_optimization import _direct_sector_setup

    row = _co(db_session, "CURATED.NS", "Curated Co", "oil_gas")
    row.business_desc = "Upstream oil and gas explorer"
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="oil_gas", exposure_exists=1,
        strength=0.9, mechanism="curated: crude realization exposure",
        provenance_type="CURATED", source_url="https://curated.example/note",
        verified_at=utcnow(), review_after=utcnow() + timedelta(days=365)))
    db_session.commit()

    router = FakeRouter(_direct_sector_setup({
        "map_companies": {"companies": [_company_entry("CURATED.NS", "Curated Co")]},
        "verify_companies": {"accept": ["CURATED.NS"], "reject": [],
                             "counterfactual": {"CURATED.NS": "SUPPORTED"}},
    }))
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert result.companies and result.companies[0].verified is True
    assert "CURATED.NS" not in result.fresh_cache_tickers, (
        "no write happened, so there is no self-echo to guard against")

    cached = db_session.query(CompanyNodeExposure).one()
    assert cached.provenance_type == "CURATED"

    entries = _v3_entries(db_session, result)
    assert entries[0]["evidence_class"] == "VERIFIED_RELATIONSHIP"
    assert entries[0]["evidence_tier"] == "C"


# --- self-echo guard at the SECOND reader (final-review finding I2) --------
# `app.pipeline._company_profile_supports_mechanism` is the other reader of
# CompanyNodeExposure in the gate path -- it feeds BUSINESS_MODEL_VALID.
# classify_evidence has carried the guard since Task 18; this one did not,
# and `_write_exposure_cache` refreshes an existing row IN PLACE. Via
# SQLAlchemy's identity map, an EXPIRED row this run's own verifier just
# re-stamped therefore reads back as FRESH here, so a candidate with no
# business description at all could clear the business-model gate on the
# strength of its own acceptance.

def test_refreshed_expired_row_cannot_satisfy_business_model_gate(db_session, strict_mode):
    """Expired (review_after in the past), curated-free row + a same-run
    verifier acceptance that refreshes it in place -> BUSINESS_MODEL's
    input must be False. The row is fresh by then, so only the guard can
    tell it apart from an independent prior."""
    from app.pipeline import _company_profile_supports_mechanism

    row = _company(db_session, business_desc=None)
    exposure = CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="model-verified crude exposure",
        provenance_type="MODEL_VERIFIED", verified_at=utcnow() - timedelta(days=200),
        review_after=utcnow() - timedelta(days=110))  # EXPIRED
    db_session.add(exposure)
    db_session.commit()

    company = _graph_company(verified=True)
    # Expired: not usable evidence for anyone, guard or no guard.
    assert _company_profile_supports_mechanism(db_session, row, company) is False

    # This run's `_write_exposure_cache` re-stamps the SAME row in place --
    # exactly what engine.py does on a verifier acceptance.
    exposure.verified_at = utcnow()
    exposure.review_after = utcnow() + timedelta(days=90)
    exposure.provenance_type = "MODEL_VERIFIED"
    db_session.commit()

    # Without the guard the refreshed row now reads as an independent
    # prior -- this is the hole.
    assert _company_profile_supports_mechanism(db_session, row, company) is True
    # With this run's write declared, the row is the candidate's own echo
    # and cannot ground the business-model claim.
    assert _company_profile_supports_mechanism(
        db_session, row, company, frozenset({"ONGC.NS"})) is False


def test_guard_leaves_a_real_business_description_alone(db_session, strict_mode):
    """The guard only discounts the EXPOSURE branch. A company with an
    actual business description still satisfies BUSINESS_MODEL_VALID even
    when this run wrote its cache row -- the description is not a
    self-echo, and refusing it would reject genuinely grounded
    candidates."""
    from app.pipeline import _company_profile_supports_mechanism

    row = _company(db_session, business_desc="Upstream oil and gas explorer")
    company = _graph_company(verified=True)

    assert _company_profile_supports_mechanism(
        db_session, row, company, frozenset({"ONGC.NS"})) is True


def test_guard_leaves_an_independent_prior_row_alone(db_session, strict_mode):
    """A fresh row for a ticker this run did NOT write (some other
    candidate's write happened instead) is a genuine prior and still
    grounds the business-model claim -- byte-identical to pre-fix
    behavior."""
    from app.pipeline import _company_profile_supports_mechanism

    row = _company(db_session, business_desc=None)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="model-verified crude exposure",
        provenance_type="MODEL_VERIFIED", verified_at=utcnow(),
        review_after=utcnow() + timedelta(days=90), source_alert_id=4242))
    db_session.commit()

    company = _graph_company(verified=True)
    assert _company_profile_supports_mechanism(
        db_session, row, company, frozenset({"SOMEOTHER.NS"})) is True
