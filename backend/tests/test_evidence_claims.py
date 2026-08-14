"""Curated evidence records + company-claim hygiene (final-blueprint Task
8, spec §16/§17).

Two invariants live here:

1. EVERY row a reader can see carries at least one EvidenceRecord. Tier
   C (SupplyLink / provenanced exposure) and SUBJECT rows already produced
   one at classification time; tier D rows (CURATED_ARCHETYPE,
   MODEL_VERIFIED_PRIOR, LEGACY_UNVERIFIED) produced NONE, so a displayed
   D row used to be a published claim with an empty evidence list. It now
   gets a deterministic record citing the curated registry mechanism it
   actually rests on -- no LLM call, no invented URL.

2. §16's hallucination list ("fuel is largest cost line", "weak balance
   sheet amplifies...", "highest marketing-to-refining ratio") is a
   COMPANY-SPECIFIC claim class. Such a claim may only be DISPLAYED when
   the row has company-specific support; otherwise the displayed text
   falls back to the curated registry string (never invented text, never
   a paraphrase), while the model's own words survive verbatim in the
   audit trail.
"""
import ast
import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.config import settings
from app.models import (
    Alert, AlertCompany, Article, Company, CompanyDecisionRecord,
    CompanyNodeExposure, EvidenceRecord, SupplyLink, utcnow,
)
from app.pipeline import _persist_alert, _v3_edges, _v3_entries


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company_row(db, ticker, name, sector="oil_gas",
                 business_desc="Operating company with a described business",
                 verified_node=None, provenance_type=None):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  business_desc=business_desc)
    db.add(row)
    db.commit()
    if verified_node is not None:
        db.add(CompanyNodeExposure(
            company_id=row.id, node_key=verified_node, exposure_exists=1,
            strength=0.8, mechanism="verified exposure", verified_at=utcnow(),
            provenance_type=provenance_type))
        db.commit()
    return row


def _graph_company(**overrides):
    from app.analysis.impact_graph.schemas import GraphCompany
    payload = dict(
        ticker="INDIGO.NS", name="InterGlobe Aviation", direction="bearish",
        impact_strength=0.7, confidence=0.8, materiality=0.7, causal_distance=2,
        time_horizon="Short-Term",
        parent_type="economic_node", parent_id="aviation_fuel_cost",
        mechanism="ATF cost rises with crude, compressing airline operating margin",
        rationale="domestic-heavy carrier with unhedged fuel exposure",
        net_direction="bearish", economic_effect="negative", verified=True,
        counterfactual="SUPPORTED", discovery_source="archetype:aviation_fuel_cost",
    )
    payload.update(overrides)
    return GraphCompany(**payload)


def _graph_edge(**overrides):
    from app.analysis.impact_graph.schemas import GraphEdge
    payload = dict(
        parent_type="event", parent_id="crude_supply_shock",
        child_type="economic_node", child_id="aviation_fuel_cost",
        direction="bearish", economic_effect="negative",
        mechanism="supply disruption raises crude price", causal_distance=1,
        impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term",
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def _result(companies, edges=None, **overrides):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    payload = dict(
        category="commodity", event_type="crude_oil", facts="crude up sharply",
        event_label="crude supply shock", named_entities=[],
        companies=companies, edges=[_graph_edge()] if edges is None else edges,
        gaps=[], ranking=[], analysis_provider="gemini",
        analysis_quality="authoritative", metrics={}, ambiguous_entities=[],
    )
    payload.update(overrides)
    return ImpactGraphResult(**payload)


def _persist(db, result):
    article = Article(source="s", provider="finnhub",
                      url=f"https://ex.com/{id(result)}", title="crude spikes",
                      content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    entries = _v3_entries(db, result)
    alert = _persist_alert(
        db, article, "commodity", entries, event_type="crude_oil", gaps=[],
        edges=_v3_edges(result), client=None, facts=result.facts,
        analysis_provider="gemini", analysis_quality=result.analysis_quality,
        ambiguous_entities=[],
    )
    return entries, alert


def _registry_text(mechanism_id):
    from app.analysis.impact_graph.knowledge import MECHANISMS
    return MECHANISMS[mechanism_id]["mechanism"]


# --- 1. curated evidence records for displayed D-tier rows -----------------

def test_displayed_d_tier_row_persists_a_curated_registry_record(db_session, strict_mode):
    """A displayed row whose evidence class is a curated/model prior (tier
    D, zero artifacts) still leaves a real EvidenceRecord naming the
    registry mechanism it rests on."""
    company = _company_row(db_session, "INDIGO.NS", "InterGlobe Aviation",
                           sector="railways_transport",
                           verified_node="aviation_fuel_cost")
    entries, alert = _persist(db_session, _result([_graph_company()]))

    entry = entries[0]
    assert entry["display_tier"] in ("primary", "secondary_ripple", "macro_context")
    assert entry["evidence_tier"] == "D"

    records = (db_session.query(EvidenceRecord)
               .filter_by(alert_id=alert.id, company_id=company.id).all())
    assert len(records) == 1
    record = records[0]
    assert record.source_type == "curated_registry"
    assert record.source_name == "aviation_fuel_cost"
    assert record.mechanism_id == "aviation_fuel_cost"
    assert record.quoted_text == _registry_text("aviation_fuel_cost")
    # The RECORD's class describes THE RECORD (review round 1, M2): it is a
    # curated registry citation whatever the ROW classified as, so a
    # MODEL_VERIFIED_PRIOR / LEGACY_UNVERIFIED row never stamps its own
    # class onto a curated_registry artifact.
    assert entry["evidence_class"] == "LEGACY_UNVERIFIED"
    assert record.evidence_class == "CURATED_ARCHETYPE"
    assert record.evidence_tier == "D"
    assert record.provenance_type == "CURATED"
    # The registry is code in this repo, not a fetched artifact.
    assert record.source_url is None


def test_curated_record_id_lands_on_the_decision_record(db_session, strict_mode):
    """The curated record joins the SAME flow the SupplyLink records use:
    evidence_ids_json on the row's CompanyDecisionRecord."""
    _company_row(db_session, "INDIGO.NS", "InterGlobe Aviation",
                 sector="railways_transport", verified_node="aviation_fuel_cost")
    _, alert = _persist(db_session, _result([_graph_company()]))

    record = (db_session.query(CompanyDecisionRecord)
              .filter_by(alert_id=alert.id, ticker="INDIGO.NS").one())
    ids = json.loads(record.evidence_ids_json)
    assert ids, "displayed D-tier row left an empty evidence_ids_json"
    assert json.loads(record.candidate_json)["evidence_ids"] == ids
    assert db_session.get(EvidenceRecord, ids[0]) is not None


def test_curated_record_comes_from_the_archetype_tag_when_the_parent_is_not_a_mechanism(
        db_session, strict_mode):
    """CURATED_ARCHETYPE rows are discovered by an exposure rule; the
    mechanism id rides on `discovery_source` even when the persisted causal
    parent id is not itself a registry key."""
    _company_row(db_session, "MRF.NS", "MRF", sector="auto_components",
                 verified_node="crude_price_up")
    entries, alert = _persist(db_session, _result(
        [_graph_company(
            ticker="MRF.NS", name="MRF", parent_type="economic_node",
            parent_id="crude_price_up",
            discovery_source="archetype:tyre_input_cost",
            mechanism="crude-linked inputs raise tyre production cost",
        )],
        edges=[_graph_edge(child_id="crude_price_up")]))
    assert entries[0]["display_tier"] in (
        "primary", "secondary_ripple", "macro_context")

    record = db_session.query(EvidenceRecord).filter_by(alert_id=alert.id).one()
    assert record.source_name == "tyre_input_cost"
    assert record.quoted_text == _registry_text("tyre_input_cost")


def test_excluded_row_gets_no_curated_record(db_session, strict_mode):
    """Curated backing exists to support a PUBLISHED claim. A row nobody
    sees must not manufacture evidence for itself."""
    _company_row(db_session, "NOBODY.NS", "Nobody Ltd", sector="oil_gas",
                 business_desc=None)
    entries, alert = _persist(db_session, _result([_graph_company(
        ticker="NOBODY.NS", name="Nobody Ltd", materiality=0.05,
        discovery_source="archetype:aviation_fuel_cost",
    )]))
    assert entries[0]["display_tier"] == "excluded"
    assert db_session.query(EvidenceRecord).filter_by(alert_id=alert.id).count() == 0


def test_c_tier_supply_link_record_still_flows(db_session, strict_mode):
    """Regression guard on the pre-existing path: a C-tier row's SupplyLink
    record is what gets persisted -- the curated fallback must never
    displace or duplicate it."""
    parent = _company_row(db_session, "MARUTI.NS", "Maruti Suzuki", sector="auto")
    supplier = _company_row(db_session, "MOTHERSON.NS", "Samvardhana Motherson",
                            sector="auto_components")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    entries, alert = _persist(db_session, _result(
        [_graph_company(
            ticker="MOTHERSON.NS", name="Samvardhana Motherson",
            parent_type="company", parent_id="MARUTI.NS", causal_distance=2,
            mechanism="volume cut at the OEM reduces component offtake",
            rationale="tier-1 supplier to the affected OEM",
            discovery_source="relationship_cache",
        )],
        edges=[_graph_edge(child_type="company", child_id="MARUTI.NS")]))
    assert entries[0]["evidence_tier"] == "C"
    records = db_session.query(EvidenceRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 1
    assert records[0].source_type == "rating_rationale"
    assert records[0].source_url == "https://crisil.example/rationale"


# --- 2. claim hygiene -------------------------------------------------------

@pytest.mark.parametrize("text", [
    "fuel is 40% of the airline's cost base",
    "raw materials are about sixty per cent of decorative cost",
    "the reset lands as a 180 basis point margin hit",
    "the company carries Rs 12,000 crore of borrowings",
    "capacity is 2.5x the nearest peer",
])
def test_sanitize_detects_quantitative_claims(text):
    from app.analysis.impact_graph.evidence import contains_company_specific_claim
    assert contains_company_specific_claim(text) is True


@pytest.mark.parametrize("text", [
    "fuel is the largest cost line for this carrier",
    "it runs the highest marketing-to-refining ratio in the sector",
    "the biggest domestic flat-product capacity competes with imports",
    "the smallest refining footprint among the OMCs",
    "the most churn-prone subscriber cohort sits here",
    "the least hedged of the listed carriers",
])
def test_sanitize_detects_superlative_claims(text):
    from app.analysis.impact_graph.evidence import contains_company_specific_claim
    assert contains_company_specific_claim(text) is True


@pytest.mark.parametrize("text", [
    "a weak balance sheet amplifies the input-cost shock",
    "high debt leaves no room to absorb the increase",
    "the shock converts directly into cash burn",
    "elevated leverage makes the repricing painful",
    "thin liquidity limits its ability to ride the cycle",
])
def test_sanitize_detects_balance_sheet_claims(text):
    from app.analysis.impact_graph.evidence import contains_company_specific_claim
    assert contains_company_specific_claim(text) is True


@pytest.mark.parametrize("text", [
    # Review round 1, I2: financial prose -- and this repo's own regression
    # corpus -- writes quantities as WORDS, which every digit-anchored
    # pattern missed.
    "an eleven dollar decline widens the spread",
    "rose to eighty-nine dollars a barrel",
    "twelve thousand crore of borrowings",
    "revenue of five thousand crore",
    "volumes doubled versus the prior year",
])
def test_sanitize_detects_spelled_out_quantities(text):
    from app.analysis.impact_graph.evidence import contains_company_specific_claim
    assert contains_company_specific_claim(text) is True


@pytest.mark.parametrize("text", [
    "ATF tracks crude, so airline operating margin compresses",
    "base-oil input costs rise until price hikes catch up",
    "the duty restores realisation per tonne on unchanged volumes",
    "",
    # Clean negatives in the SPELLED-OUT register: a bare currency or scale
    # noun with no numeral in front of it is a business-model statement, not
    # a quantity. The first is a real corpus mechanism (fx_depreciation /
    # INFY) and must keep passing.
    "revenue is billed in dollars and euros while the cost base is rupee",
    "one of the domestic carriers competes on the same trunk routes",
    "thousands of retail outlets sell the notified product",
    "the crore-scale capex programme is unchanged",
])
def test_sanitize_passes_clean_text(text):
    from app.analysis.impact_graph.evidence import contains_company_specific_claim
    assert contains_company_specific_claim(text) is False


def test_sanitize_keeps_text_when_the_row_has_specific_evidence():
    from app.analysis.impact_graph.evidence import sanitize_company_claim
    claim = "fuel is the largest cost line for this carrier"
    assert sanitize_company_claim(claim, True, registry_text="curated") == claim


def test_sanitize_falls_back_to_the_registry_string_only():
    from app.analysis.impact_graph.evidence import sanitize_company_claim
    claim = "fuel is the largest cost line and its weak balance sheet amplifies the hit"
    curated = _registry_text("aviation_fuel_cost")
    assert sanitize_company_claim(claim, False, registry_text=curated) == curated


def test_sanitize_returns_none_when_no_registry_text_resolves():
    """Never invent: with no curated string to stand in, the unsupported
    specific is withheld rather than displayed."""
    from app.analysis.impact_graph.evidence import sanitize_company_claim
    claim = "fuel is the largest cost line for this carrier"
    assert sanitize_company_claim(claim, False, registry_text=None) is None


def test_unsupported_claim_on_evidence_less_row_falls_back_to_registry_text(
        db_session, strict_mode):
    """§16's exact failure shape, end to end: the displayed explanation
    becomes the curated registry string; the model's own sentence survives
    untouched in the audit trail."""
    company = _company_row(db_session, "INDIGO.NS", "InterGlobe Aviation",
                           sector="railways_transport",
                           verified_node="aviation_fuel_cost")
    llm_claim = ("Fuel is the largest cost line for this carrier and its weak "
                 "balance sheet amplifies the shock")
    llm_rationale = "domestic-heavy carrier with no hedging on the domestic leg"
    entries, alert = _persist(db_session, _result([_graph_company(
        mechanism=llm_claim, rationale=llm_rationale)]))

    entry = entries[0]
    assert entry["display_tier"] in ("primary", "secondary_ripple", "macro_context")
    curated = _registry_text("aviation_fuel_cost")
    assert entry["mechanism"] == curated

    row = (db_session.query(AlertCompany)
           .filter_by(alert_id=alert.id, company_id=company.id).one())
    assert row.mechanism == curated
    # Audit copies -- the LLM text is preserved, never displayed as fact.
    assert row.rationale == llm_rationale
    record = (db_session.query(CompanyDecisionRecord)
              .filter_by(alert_id=alert.id, ticker="INDIGO.NS").one())
    assert json.loads(record.gate_inputs_json)["mechanism"] == llm_claim


def test_supported_row_keeps_its_own_explanation(db_session, strict_mode):
    """A row backed by an independently-sourced relationship (tier C) is
    allowed to say something company-specific -- that is what the evidence
    is for."""
    parent = _company_row(db_session, "MARUTI.NS", "Maruti Suzuki", sector="auto")
    supplier = _company_row(db_session, "MOTHERSON.NS", "Samvardhana Motherson",
                            sector="auto_components")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    claim = "the OEM is the largest single customer of this supplier"
    entries, alert = _persist(db_session, _result(
        [_graph_company(
            ticker="MOTHERSON.NS", name="Samvardhana Motherson",
            parent_type="company", parent_id="MARUTI.NS", causal_distance=2,
            mechanism=claim, rationale="tier-1 supplier to the affected OEM",
            discovery_source="relationship_cache",
        )],
        edges=[_graph_edge(child_type="company", child_id="MARUTI.NS")]))
    assert entries[0]["evidence_tier"] == "C"
    row = (db_session.query(AlertCompany)
           .filter_by(alert_id=alert.id, company_id=supplier.id).one())
    assert row.mechanism == claim


def test_registry_text_is_withheld_when_it_contradicts_the_row(db_session, strict_mode):
    """The registry writes each mechanism for its CANONICAL trigger
    direction. An inverted event (crude DOWN) flips the effect but not the
    prose, so borrowing the string there would publish a bearish sentence
    on a bullish row -- withheld instead."""
    from app.analysis.impact_graph.evidence import sanitize_company_claim, displayed_claim_for_entry

    claim = "ATF is the largest operating cost line, so the decline widens spread"
    entry = {
        "display_tier": "secondary_ripple", "evidence_tier": "D",
        "causal_distance": 2, "economic_effect": "positive",
        "causal_parent_type": "economic_node", "causal_parent_id": "aviation_fuel_cost",
        "discovery_source": "archetype:aviation_fuel_cost", "mechanism": claim,
    }
    assert displayed_claim_for_entry(entry) is None
    # Same entry with the matching effect keeps the curated string.
    entry["economic_effect"] = "negative"
    assert displayed_claim_for_entry(entry) == _registry_text("aviation_fuel_cost")
    assert sanitize_company_claim(claim, False, registry_text=None) is None


def test_excluded_rows_keep_their_raw_text_for_audit(db_session, strict_mode):
    """Hygiene is a DISPLAY rule. A rejected row's verbatim model text is
    the whole point of its audit record."""
    from app.analysis.impact_graph.evidence import displayed_claim_for_entry

    claim = "fuel is the largest cost line for this carrier"
    entry = {
        "display_tier": "excluded", "evidence_tier": "D", "causal_distance": 2,
        "economic_effect": "negative", "causal_parent_type": "economic_node",
        "causal_parent_id": "aviation_fuel_cost",
        "discovery_source": "archetype:aviation_fuel_cost", "mechanism": claim,
    }
    assert displayed_claim_for_entry(entry) == claim


# --- 3. no-fabrication proof ------------------------------------------------

_APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _python_sources():
    return sorted(_APP_DIR.rglob("*.py"))


def test_evidence_records_are_only_constructed_in_known_places():
    """Grep proof: exactly two call sites construct an EvidenceRecord --
    evidence.persist_evidence (from classifier/registry payloads) and
    pipeline._copy_gate_audit_trail (a field-for-field copy of an ALREADY
    persisted record). A new construction site anywhere else is a new
    fabrication surface and must fail this test until it is reviewed."""
    # `class EvidenceRecord(Base)` in models.py is a definition, not a
    # construction -- everything else that opens a paren on the name is.
    pattern = re.compile(r"(?<!class )\bEvidenceRecord\s*\(")
    found = {
        str(path.relative_to(_APP_DIR)).replace("\\", "/")
        for path in _python_sources()
        if pattern.search(path.read_text(encoding="utf-8"))
    }
    assert found == {"analysis/impact_graph/evidence.py", "pipeline.py"}, found


def _source_url_values(tree):
    """Every value WRITTEN to a source_url: the "source_url" key of a dict
    literal (evidence.py builds EvidenceRecord payloads as dict literals)
    and the `source_url=` keyword of an EvidenceRecord(...) construction.
    Reads (`payload.get("source_url")`, `filter_by(source_url=...)`) are
    not writes and are deliberately out of scope."""
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "source_url":
                    values.append(value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "EvidenceRecord":
            for keyword in node.keywords:
                if keyword.arg == "source_url":
                    values.append(keyword.value)
    return values


def _is_artifact_sourced(value):
    """A source_url may only be None, or read straight off a persisted
    artifact row (`link.source_url`, `cached.source_url`, `record.
    source_url`) -- never an LLM-supplied string, f-string, or dict lookup
    on model output."""
    if isinstance(value, ast.Constant) and value.value is None:
        return True
    return isinstance(value, ast.Attribute) and value.attr == "source_url"


def test_no_evidence_record_source_url_is_llm_provided():
    for relative in ("analysis/impact_graph/evidence.py", "pipeline.py"):
        path = _APP_DIR / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for value in _source_url_values(tree):
            assert _is_artifact_sourced(value), (
                f"{relative}: source_url is set from {ast.dump(value)[:120]} -- "
                "only None or a persisted artifact's own attribute is allowed")


def test_curated_payload_never_carries_a_url_or_llm_text(db_session):
    """The curated registry payload quotes the registry VERBATIM and cites
    no URL, whatever the model wrote on the candidate."""
    from app.analysis.impact_graph.evidence import curated_registry_payload

    payload = curated_registry_payload({
        "display_tier": "secondary_ripple", "evidence_class": "CURATED_ARCHETYPE",
        "evidence_tier": "D", "causal_parent_type": "economic_node",
        "causal_parent_id": "aviation_fuel_cost",
        "discovery_source": "archetype:aviation_fuel_cost",
        "mechanism": "http://evil.example/invented-source says fuel is 90% of cost",
        "rationale": "https://another.example/made-up",
    })
    assert payload["source_url"] is None
    assert payload["quoted_text"] == _registry_text("aviation_fuel_cost")
    assert "http" not in json.dumps(payload)


def test_unknown_mechanism_yields_no_curated_payload():
    from app.analysis.impact_graph.evidence import curated_registry_payload

    assert curated_registry_payload({
        "display_tier": "primary", "evidence_tier": "D",
        "causal_parent_type": "sector", "causal_parent_id": "cement",
        "discovery_source": "sector_pool", "mechanism": "sector exposure",
    }) is None
