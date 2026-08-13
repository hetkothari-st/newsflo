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
#
# Matching is lowercase SUBSTRING matching over "<rationale> <mechanism>",
# so an entry also catches its compound forms ("rallied" covers "has
# rallied hard"). The second block (corrective-v4 Task 20) closes the
# paraphrase bypass the audit found: the original list matched only the
# textbook English phrasings, so the identical argument written in Indian
# market vernacular -- "the scrip slid 3%", "the counter tanked" -- read as
# ordinary fundamental evidence and could authorize a primary claim.
#
# DELIBERATELY OVER-INCLUSIVE (precision-first): a few of these verbs
# ("rallied", "surged", "plunged") could in principle appear inside a
# genuine mechanism sentence about a COMMODITY rather than the stock. That
# error costs a demotion to deep dive; the error this list exists to
# prevent -- a price move published as a fundamental finding -- costs the
# product's credibility. The cheap direction wins. Pinned phrase by phrase
# in tests/test_audit_bypasses.py::test_bypass_market_observation_paraphrase,
# alongside a companion test that genuine cost/margin/demand language is
# NOT swallowed.
_MARKET_OBSERVATION_PHRASES = (
    "stock fell", "stock rose", "stock dropped", "stock declined",
    "stock jumped", "stock surged", "shares fell", "shares rose",
    "shares dropped", "shares declined", "shares jumped", "shares surged",
    # Paraphrases (Task 20).
    "scrip fell", "scrip rose", "scrip slid",
    "price fell", "price rose", "sold off",
    "stock slid", "shares slid", "stock is down", "stock is up",
    "tanked", "plunged", "rallied", "surged", "cracked", "tumbled",
)

# Provenance values that name an independently-sourced relationship, never
# the system's own accepted prior (corrective-v4 Task 6, spec §8/§9). This
# is the ONLY escape a CompanyNodeExposure row has to Tier C -- MODEL_VERIFIED
# (what the verifier writes) and NULL (pre-provenance legacy rows) never
# qualify, no matter how many times a model has re-confirmed them.
_PROVENANCED_EXPOSURE_TYPES = ("SUPPLY_LINK", "MANUAL", "CURATED")


def classify_evidence(
    session: Session, company, subject_tickers: set[str],
    fresh_cache_tickers: frozenset[str] = frozenset(),
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

       SELF-ECHO GUARD (owner-ruled cross-finding, T19/T20 audit,
       corrective-v4 Task 18 follow-up): `fresh_cache_tickers` is the set
       of tickers `_write_exposure_cache` (engine.py) ACTUALLY UPSERTED a
       CompanyNodeExposure row for in THIS run -- populated from
       `_GraphState.fresh_cache_tickers`, filled in exactly where
       `_verify_companies` calls `_write_exposure_cache(..., exposure_
       exists=True, ...)`, nowhere else. For any such ticker, this branch
       is SKIPPED entirely -- read on for why.

       `_write_exposure_cache` upserts that row in the SAME run, BEFORE
       app.pipeline._gate_candidates ever calls this function (still
       pre-Alert-flush, same DB session). Without this guard, an accepted
       candidate's own just-written row -- not any independent history --
       is what classify_evidence reads back, so a verified, article-
       central candidate could self-echo straight to Tier D and could
       never classify as ARTICLE_SUBJECT (SUBJECT, primary-capable) even
       when it plainly was the article's own subject: the narrow path
       could essentially never produce a primary claim this way, since
       MODEL_VERIFIED_PRIOR is capped at secondary_deep_dive.

       Deliberately NOT `company.verified` (every GraphCompany.verified
       True ticker in the result) despite that being the plan-round
       suggestion -- measured against the actual test suite, that coarser
       signal wrongly excludes the single most common fixture pattern
       used throughout this codebase's OWN tests (a hand-built, already-
       `verified=True` GraphCompany paired with a CompanyNodeExposure row
       set up directly by the test to simulate a genuine, independent
       PRIOR -- never a self-write at all, since these tests never call
       `_write_exposure_cache`). `company.verified=True` also does not
       imply a cache row was ever written this run in the first place:
       the narrow path's low-risk branch sets it from the in-call self-
       check alone, without `_verify_companies` (and therefore `_write_
       exposure_cache`) ever running. Tracking the ACTUAL cache-write set
       instead of the broader verified set is exact (no guessing about
       what MIGHT have been written) and leaves every existing "prior
       exposure row + independently verified candidate" test fixture
       byte-for-byte unaffected -- it only fires for a ticker this run's
       own `_write_exposure_cache` genuinely touched. A row for a
       DIFFERENT, older alert (nobody wrote to it this run) is unaffected
       and still classifies MODEL_VERIFIED_PRIOR / D exactly as before.
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
                # Independently sourced (a human or a linked artifact
                # wrote this, never `_write_exposure_cache` -- see
                # _PROVENANCED_EXPOSURE_TYPES) -- genuine evidence
                # regardless of whether this run's verifier also accepted
                # the same candidate, so the self-echo guard below does
                # not apply here.
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
            # Self-echo guard (see docstring): MODEL_VERIFIED/LEGACY_
            # UNVERIFIED rows are never independent evidence to begin with
            # -- they are the system's own prior. For a ticker THIS run's
            # verifier just accepted, the row sitting here may well BE
            # that exact acceptance's own write; fall through to the
            # weaker classes instead of crediting a candidate with its own
            # say-so.
            if company.ticker not in fresh_cache_tickers:
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
