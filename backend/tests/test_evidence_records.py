"""Structured evidence records (corrective-v4 Task 5, spec §18): the
publication gate's evidence class/tier is no longer a bare string the
caller invents -- app.analysis.impact_graph.evidence.classify_evidence
derives it deterministically and hands back the EvidenceRecord payload(s)
that earned it (or none, when there is nothing to cite). Free-text LLM
`evidence_refs` are demoted: only rulebook-MATCHED refs may ever raise
compute_confidence's score."""
from datetime import date

import pytest

from app.models import (
    Article, Company, CompanyNodeExposure, EvidenceRecord, SupplyLink, utcnow,
)


def _company(db, ticker, name, sector="auto", **kw):
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


# --- SupplyLink -> real Tier-C record --------------------------------------

def test_supply_link_yields_tier_c_with_real_record(db_session):
    from app.analysis.impact_graph.evidence import classify_evidence, persist_evidence

    parent = _company(db_session, "MARUTI.NS", "Maruti Suzuki", sector="auto")
    supplier = _company(db_session, "MOTHERSON.NS", "Samvardhana Motherson", sector="auto_components")
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
    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert evidence_class == "VERIFIED_RELATIONSHIP"
    assert evidence_tier == "C"
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["source_url"] == "https://crisil.example/rationale"
    assert payload["quoted_text"] == (
        "Samvardhana Motherson supplies wiring harnesses for our vehicle programmes")
    assert payload["source_name"] == "CRISIL"
    assert payload["supports_claim"] is True

    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="Maruti volumes cut", content="c", status="CATEGORIZED")
    db_session.add(article)
    db_session.commit()
    from app.models import Alert
    alert = Alert(article_id=article.id, category="auto")
    db_session.add(alert)
    db_session.commit()

    ids = persist_evidence(db_session, alert.id, supplier.id, payloads)
    assert len(ids) == 1
    record = db_session.get(EvidenceRecord, ids[0])
    assert record.evidence_class == "VERIFIED_RELATIONSHIP"
    assert record.evidence_tier == "C"
    assert record.source_url == "https://crisil.example/rationale"
    assert record.quoted_text is not None
    assert record.alert_id == alert.id
    assert record.company_id == supplier.id


# --- cache prior is D, never a fabricated "verified" C ---------------------

def test_model_verified_cache_row_is_tier_d_prior_not_verified(db_session):
    """A CompanyNodeExposure row is a PRIOR the system computed and cached
    for itself -- not an independent verification. It must never earn the
    VERIFIED_RELATIONSHIP class no matter how it was written (Task 6 adds
    a real provenance-based escape hatch later)."""
    from app.analysis.impact_graph.evidence import classify_evidence

    row = _company(db_session, "ONGC.NS", "ONGC", sector="oil_gas")
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure",
        provenance_type="MODEL_VERIFIED", verified_at=utcnow()))
    db_session.commit()

    company = _graph_company()
    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())

    assert (evidence_class, evidence_tier) == ("MODEL_VERIFIED_PRIOR", "D")
    assert payloads == []


# --- no fabricated citations -------------------------------------------

def test_no_evidence_record_is_ever_fabricated(db_session):
    """Every payload classify_evidence returns names a real source_type,
    and quoted_text/source_url are populated ONLY when a real artifact
    (a SupplyLink) supplied them -- never invented for a class that has
    no artifact behind it."""
    from app.analysis.impact_graph.evidence import classify_evidence

    parent = _company(db_session, "MARUTI.NS", "Maruti Suzuki", sector="auto")
    supplier = _company(db_session, "MOTHERSON.NS", "Samvardhana Motherson", sector="auto_components")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    prior_row = _company(db_session, "ONGC.NS", "ONGC", sector="oil_gas")
    db_session.add(CompanyNodeExposure(
        company_id=prior_row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure", verified_at=utcnow()))
    subject_row = _company(db_session, "TCS.NS", "TCS", sector="it")
    db_session.commit()

    scenarios = [
        # (company, subject_tickers)
        (_graph_company(ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                        parent_type="company", parent_id="MARUTI.NS"), set()),
        (_graph_company(), set()),  # ONGC.NS -> cached exposure prior
        (_graph_company(ticker="TCS.NS", name="TCS"), {"TCS.NS"}),  # article subject
        (_graph_company(ticker="NEWCO.NS", name="NewCo",
                        discovery_source="archetype:tyre_input_cost"), set()),  # curated
        (_graph_company(ticker="NOBODY.NS", name="Nobody"), set()),  # bare inference
        (_graph_company(rationale="the stock fell 3% after the announcement"), set()),  # market obs
    ]

    for company, subject_tickers in scenarios:
        evidence_class, evidence_tier, payloads = classify_evidence(
            db_session, company, subject_tickers)
        for payload in payloads:
            assert payload.get("source_type"), (
                f"{evidence_class} record has no source_type")
            if evidence_class != "VERIFIED_RELATIONSHIP":
                assert payload.get("source_url") is None, (
                    f"{evidence_class} fabricated a source_url")
                assert payload.get("quoted_text") is None, (
                    f"{evidence_class} fabricated quoted_text")


# --- LLM evidence_refs demoted: cannot raise confidence ---------------------

def _entry(company_id, evidence_refs):
    return {
        "company_id": company_id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 3.0,
        "rationale": "test rationale", "key_points": [],
        "time_horizon": "Short-Term", "basis": "direct_mention",
        "reasons": ["reason one", "reason two", "reason three"],
        "evidence_refs": evidence_refs, "risks": [],
        "assumptions": [], "unknowns": [], "alternative_hypothesis": None,
    }


def test_llm_evidence_refs_cannot_raise_confidence(db_session):
    from app.pipeline import _build_alert_company

    company = _company(db_session, "RELIANCE.NS", "Reliance Industries", sector="oil_gas")
    article = Article(source="test", url="https://example.com/evidence",
                      title="Oil prices spike", content="crude oil markets react")
    db_session.add(article)
    db_session.commit()

    honest, _ = _build_alert_company(
        db_session, alert_id=1, article=article, category="oil_gas",
        entry=_entry(company.id, []))
    padded, _ = _build_alert_company(
        db_session, alert_id=1, article=article, category="oil_gas",
        entry=_entry(company.id, ["FAKE_REF_1", "FAKE_REF_2", "FAKE_REF_3"]))

    assert honest.confidence_score == padded.confidence_score
