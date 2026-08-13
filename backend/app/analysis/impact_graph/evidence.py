"""Deterministic evidence classification (corrective-v4 Task 5, spec §9/§10
/§18). Replaces the old string-only `_classify_evidence` with a producer
that also builds the EvidenceRecord payloads a class/tier claim is backed
by -- a candidate's evidence class is no longer just a label, it is a
label PLUS the artifact (or explicit absence of one) that earned it.

`classify_evidence` returns EvidenceRecord PAYLOADS (plain dicts), not
persisted ids. This is a deliberate deviation from the plan's literal
`-> list[int]` signature: at classification time (inside
app.pipeline._gate_candidates, which runs before the Alert row is
flushed) there is no alert id yet to stamp onto a row. `persist_evidence`
turns these payloads into real, deduplicated EvidenceRecord rows once
app.pipeline._persist_alert has an alert id, and returns their ids --
see task-5-report.md for the full rationale.
"""
from sqlalchemy.orm import Session

# Phrases that mark a rationale/mechanism as grounded in the observed
# stock move rather than in economics (spec §10, INV-003): such a candidate
# carries market-observation evidence, which can never authorize primary.
# Owned here (not app.pipeline) now that evidence classification has its
# own module; app.pipeline no longer defines its own copy.
_MARKET_OBSERVATION_PHRASES = (
    "stock fell", "stock rose", "stock dropped", "stock declined",
    "stock jumped", "stock surged", "shares fell", "shares rose",
    "shares dropped", "shares declined", "shares jumped", "shares surged",
)

# Provenance values that name an independently-sourced relationship, never
# the system's own accepted prior (corrective-v4 Task 6, spec §8/§9). This
# is the ONLY escape a CompanyNodeExposure row has to Tier C -- MODEL_VERIFIED
# (what the verifier writes) and NULL (pre-provenance legacy rows) never
# qualify, no matter how many times a model has re-confirmed them.
_PROVENANCED_EXPOSURE_TYPES = ("SUPPLY_LINK", "MANUAL", "CURATED")


def classify_evidence(
    session: Session, company, subject_tickers: set[str],
) -> tuple[str, str, list[dict]]:
    """Deterministic evidence class + tier + backing EvidenceRecord
    payloads for the publication gate. Order matters -- each check either
    terminates the walk or falls through to a weaker class, never the
    reverse:

    1. A price-movement argument taints the candidate before any stronger
       class can rescue it -- the cure is a real economic rationale, not a
       cache row (ARTICLE_MARKET_OBSERVATION / MARKET_OBS, no record: there
       is nothing to cite, the rationale itself is the problem).
    2. A SupplyLink match is the ONLY thing this function can produce that
       is backed by an independently-sourced, verbatim-quoted artifact --
       it is therefore the sole producer of Tier C (VERIFIED_RELATIONSHIP).
       Evidence classification only: the graph proposed the candidate, the
       link never does (no-auto-attribution stays intact).
    3. A CompanyNodeExposure row is normally a PRIOR the system itself
       computed and cached (app.analysis.impact_graph.engine.
       _write_exposure_cache writes provenance_type=MODEL_VERIFIED) -- not
       independent verification, so it earns only MODEL_VERIFIED_PRIOR / D.
       A NULL-provenance row (written before provenance shipped) is the
       same non-evidence, labeled LEGACY_UNVERIFIED / D instead so an old
       row is never mistaken for a reviewed one. The ONE escape (Task 6,
       spec §8/§9): provenance_type in (SUPPLY_LINK, MANUAL, CURATED) names
       an independently-sourced relationship a human or a linked artifact
       established, not the model re-confirming itself -- that alone earns
       VERIFIED_RELATIONSHIP / C, with a real payload citing the source.
       Staleness (incl. review_after expiry) still applies to every case --
       a stale row is not usable evidence at all, so it falls through
       exactly like "no row".
    4. The article's own subject list is genuine evidence about the
       company at distance 1 -- ARTICLE_SUBJECT / SUBJECT, with a record
       documenting that the article named the company as its subject.
    5. A curated archetype match is a maintainer-reviewed template, not a
       fabricated citation -- CURATED_ARCHETYPE / D, no record (the
       archetype registry is code, not a sourced artifact).
    6. Everything else is the model's own inference: MODEL_INFERENCE / E,
       never authorizing, no record.
    """
    text = f"{company.rationale or ''} {company.mechanism or ''}".lower()
    if any(phrase in text for phrase in _MARKET_OBSERVATION_PHRASES):
        return "ARTICLE_MARKET_OBSERVATION", "MARKET_OBS", []

    from app.models import Company, CompanyNodeExposure, SupplyLink

    row = session.query(Company).filter_by(ticker=company.ticker).one_or_none()

    if row is not None and company.parent_type == "company":
        parent_row = session.query(Company).filter_by(ticker=company.parent_id).one_or_none()
        if parent_row is not None:
            linked = (
                session.query(SupplyLink)
                .filter(
                    ((SupplyLink.company_id == parent_row.id)
                     & (SupplyLink.counterparty_company_id == row.id))
                    | ((SupplyLink.company_id == row.id)
                       & (SupplyLink.counterparty_company_id == parent_row.id))
                )
                .first()
            )
            if linked is not None:
                payload = {
                    "source_type": "rating_rationale",
                    "source_name": linked.source_agency,
                    "source_url": linked.source_url,
                    "quoted_text": linked.evidence,
                    "fact_text": (
                        f"{linked.relation.title()} relationship between "
                        f"{row.ticker} and {parent_row.ticker} per {linked.source_agency}'s "
                        f"rating rationale"
                    ),
                    "as_of_date": linked.as_of,
                    "evidence_class": "VERIFIED_RELATIONSHIP",
                    "evidence_tier": "C",
                    "supports_claim": True,
                }
                return "VERIFIED_RELATIONSHIP", "C", [payload]

    if row is not None:
        from app.analysis.impact_graph.exposure import exposure_row_is_fresh

        cached = (
            session.query(CompanyNodeExposure)
            .filter_by(company_id=row.id, node_key=company.parent_id, exposure_exists=1)
            .one_or_none()
        )
        if cached is not None and exposure_row_is_fresh(cached, row):
            provenance = cached.provenance_type
            if provenance in _PROVENANCED_EXPOSURE_TYPES:
                payload = {
                    "source_type": "provenanced_exposure",
                    "source_name": provenance,
                    "source_url": cached.source_url,
                    "source_date": cached.source_date,
                    "fact_text": cached.mechanism or "provenanced exposure",
                    "evidence_class": "VERIFIED_RELATIONSHIP",
                    "evidence_tier": "C",
                    "supports_claim": True,
                }
                return "VERIFIED_RELATIONSHIP", "C", [payload]
            if provenance is None:
                return "LEGACY_UNVERIFIED", "D", []
            return "MODEL_VERIFIED_PRIOR", "D", []

    if company.ticker in subject_tickers:
        payload = {
            "source_type": "article",
            "source_name": "article",
            "fact_text": "named subject of the article",
            "evidence_class": "ARTICLE_COMPANY_MENTION",
            "evidence_tier": "SUBJECT",
            "supports_claim": True,
        }
        return "ARTICLE_SUBJECT", "SUBJECT", [payload]

    if (getattr(company, "discovery_source", "") or "").startswith("archetype:"):
        return "CURATED_ARCHETYPE", "D", []

    return "MODEL_INFERENCE", "E", []


def persist_evidence(
    session: Session, alert_id: int, company_id: int | None, payloads: list[dict],
) -> list[int]:
    """Turn classify_evidence's payloads into real EvidenceRecord rows now
    that the Alert exists. Deduplicated on (alert, company, source_url,
    fact_text): a row matching an existing one is reused (its id returned)
    rather than inserted again, so persisting the same candidate's evidence
    twice within one alert (e.g. a duplicate-company second occurrence, or
    a caller re-deriving the same payload) never stacks duplicate rows."""
    from app.models import EvidenceRecord

    ids: list[int] = []
    for payload in payloads:
        existing = (
            session.query(EvidenceRecord)
            .filter_by(
                alert_id=alert_id, company_id=company_id,
                source_url=payload.get("source_url"), fact_text=payload.get("fact_text"),
            )
            .one_or_none()
        )
        if existing is not None:
            ids.append(existing.id)
            continue
        record = EvidenceRecord(alert_id=alert_id, company_id=company_id, **payload)
        session.add(record)
        session.flush()
        ids.append(record.id)
    return ids
