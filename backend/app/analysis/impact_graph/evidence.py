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
import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

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


# ===========================================================================
# Curated-registry backing + company-claim hygiene (final-blueprint Task 8,
# spec §16/§17)
# ===========================================================================
#
# §16's charge sheet from the first real run -- "fuel is largest cost line",
# "weak balance sheet amplifies...", "highest marketing-to-refining ratio"
# -- is one failure with two halves:
#
#   (a) the row was PUBLISHED with an empty evidence list, because tier D
#       (curated archetype / model-verified prior / legacy unverified) is
#       the one displayable class classify_evidence produces NO payload for;
#   (b) the SENTENCE made a company-specific quantitative assertion that
#       nothing in the system could support.
#
# The two halves are fixed together and deterministically, with no LLM call
# in either path: (a) a displayed row with no artifact of its own persists a
# record citing the curated registry mechanism it actually rests on, and
# (b) an unsupported company-specific claim is not displayed -- the reader
# gets the curated registry string instead, and the model's own wording
# survives verbatim in the audit trail (CompanyDecisionRecord.
# gate_inputs_json holds the CandidateInput the gate walked, mechanism and
# rationale included; AlertCompany.rationale keeps the LLM rationale, which
# no v4 surface displays).

# Blueprint §6/§7 display tiers. Spelled out rather than imported at module
# scope so this module keeps its "no heavy imports at import time" shape;
# `displayed_claim_for_entry` cross-checks against publication_gate's own
# DISPLAYABLE_TIERS in tests, not here.
DISPLAYED_TIERS = ("primary", "secondary_ripple", "macro_context")

# §17 tiers that constitute COMPANY-SPECIFIC support. A/B/C are the spec's
# own answer ("A = primary source, B = trusted structured source, C =
# independently verified relationship").
SPECIFIC_EVIDENCE_TIERS = frozenset({"A", "B", "C"})

# Deliberate, documented widening of the brief's literal "A/B/C" rule (see
# task-8-report.md). publication_gate.STRONG_TIERS already rules -- as an
# owner ruling, Task 4 review finding I1 -- that "ARTICLE_SUBJECT is strong
# evidence about the company AT DISTANCE 1 ONLY... Two hops out, 'the
# article was about them' says nothing about the transmission chain, so
# SUBJECT at d2/d3 behaves like tier D". A d1 subject row's specifics are
# the ARTICLE'S OWN specifics (and refinement's closed-world validator
# already checks any percentage in them against the extracted facts), so
# they are company-specific support in exactly §16's sense. Measured on the
# regression corpus, treating SUBJECT-at-d1 as unsupported would have
# replaced the explanation on 15 of 18 published primaries with generic
# registry prose -- a breadth regression §1 forbids, for claims the article
# itself makes.
_SUBJECT_TIER = "SUBJECT"

# --- §16 company-specific claim detection ---------------------------------
# Precision-first and deliberately over-inclusive: a false positive costs
# one row a specific sentence it may not have earned; a false negative
# publishes an invented company fact, which is the failure this section
# exists to prevent.
_CLAIM_PATTERNS = (
    # Percentages, spelled out or not ("six and a half per cent" carries no
    # digit at all, which is exactly how the first real run smuggled figures
    # past digit-only checks).
    re.compile(r"\d+(?:[.,]\d+)?\s*%"),
    re.compile(r"\bper\s?cent(?:age)?\b|\bpercent(?:age)?\b", re.I),
    # Money, scale words, multiples, basis points.
    re.compile(r"(?:₹|rs\.?|inr|usd|\$)\s*\d", re.I),
    re.compile(r"\d[\d,.]*\s*(?:crore|cr\b|lakh|lakhs|billion|bn\b|million|mn\b|trillion|tn\b)", re.I),
    re.compile(r"\d+(?:[.,]\d+)?\s*(?:x\b|times\b|fold\b)", re.I),
    re.compile(r"\d[\d,.]*\s*(?:bps\b|basis\s+points?\b)", re.I),
    re.compile(r"\bbasis\s+points?\b", re.I),
    # Superlatives -- a ranking claim about one company against a peer set
    # is company-specific by construction. "lowest" rides with "highest"
    # for symmetry; §16's own examples are "largest" and "highest".
    re.compile(r"\b(?:largest|biggest|highest|lowest|smallest|most|least)\b", re.I),
    # Balance-sheet / financial-position terms: §16 lists "weak balance
    # sheet amplifies..." verbatim as a hallucination, and this class of
    # statement is never derivable from an article about a commodity price.
    re.compile(r"\b(?:debt|debts|indebted|leverage[d]?|liquidity|balance[-\s]sheet|gearing)\b", re.I),
    re.compile(r"\bcash\b", re.I),
)


def contains_company_specific_claim(text: str | None) -> bool:
    """True when `text` makes the kind of assertion §16 requires
    company-specific support for: a quantity, a superlative ranking, or a
    balance-sheet/financial-position statement about the company."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CLAIM_PATTERNS)


def has_specific_evidence(evidence_tier: str | None,
                          causal_distance: int | None = None) -> bool:
    """Does this row carry company-specific support (§16)? A/B/C always;
    ARTICLE_SUBJECT only at distance 1 (publication_gate's own I1 ruling --
    see _SUBJECT_TIER above). Everything else (D, E, MARKET_OBS, unknown)
    is generic or absent support."""
    tier = str(evidence_tier or "").strip().upper()
    if tier in SPECIFIC_EVIDENCE_TIERS:
        return True
    return tier == _SUBJECT_TIER and causal_distance == 1


def sanitize_company_claim(text: str, has_specific_evidence: bool,
                           registry_text: str | None = None) -> str | None:
    """The §16 display filter for one row's explanation.

    Returns `text` unchanged when the row may carry a company-specific
    claim (or makes none). Otherwise returns `registry_text` -- the CURATED
    REGISTRY STRING, verbatim, and nothing else: this function never
    paraphrases, never trims, never composes. With no registry string to
    stand in (`None`), it returns None so the caller withholds the
    explanation entirely; an unsupported specific is worse than silence.

    `has_specific_evidence` shadows the module function of the same name on
    purpose -- the plan pins this parameter name, and the caller is the one
    that resolves the tier.
    """
    if not text:
        return text or None
    if has_specific_evidence:
        return text
    if not contains_company_specific_claim(text):
        return text
    return registry_text or None


# --- curated registry resolution -------------------------------------------

_MECHANISM_PARENT_TYPES = ("", "economic_node", "commodity", "policy")
_MECHANISM_ALIASES: dict[str, str] | None = None


def _mechanism_alias_map() -> dict[str, str]:
    """normalized node id -> registry mechanism id. The archetype path
    persists `normalize_node_id(mechanism_id)` as the candidate's
    causal_parent_id, which singularizes a handful of ids ("paints_input_
    cost" lands as "paint_input_cost"), so a direct MECHANISMS lookup
    misses exactly those. Mirrors app.pipeline._mechanism_alias_map; kept
    local because importing app.pipeline from here would invert the
    existing (pipeline -> evidence) dependency direction."""
    global _MECHANISM_ALIASES
    if _MECHANISM_ALIASES is None:
        from app.analysis.impact_graph.knowledge import MECHANISMS
        from app.analysis.impact_graph.normalize import normalize_node_id

        _MECHANISM_ALIASES = {normalize_node_id(mid): mid for mid in MECHANISMS}
    return _MECHANISM_ALIASES


def _candidate_mechanism_ids(parent_type, parent_id, discovery_source) -> list[str]:
    """Registry ids to try for one row, best first: the causal parent it
    actually hangs off, then the archetype tag that discovered it. A
    sector/company parent is NEVER looked up as a mechanism (a sector named
    "cement" must not borrow the cement mechanism)."""
    ids: list[str] = []
    node_id = str(parent_id or "").strip()
    if node_id and str(parent_type or "").strip().lower() in _MECHANISM_PARENT_TYPES:
        ids.append(node_id)
        aliased = _mechanism_alias_map().get(node_id)
        if aliased:
            ids.append(aliased)
    tag = str(discovery_source or "").strip()
    if tag.lower().startswith("archetype:"):
        tagged = tag.split(":", 1)[1].strip()
        if tagged:
            ids.append(tagged)
            aliased = _mechanism_alias_map().get(tagged)
            if aliased:
                ids.append(aliased)
    return ids


def resolve_registry_mechanism(parent_type: str | None, parent_id: str | None,
                               discovery_source: str | None = None) -> tuple[str, str] | None:
    """(mechanism_id, curated mechanism text) for a row whose causal parent
    or archetype tag names a knowledge-registry mechanism; None otherwise.

    `mechanism_meta` is the existence gate (it is the registry's own public
    lookup and the one the rest of the blueprint work reads); the prose
    itself lives on the MECHANISMS entry, which mechanism_meta does not
    expose. Nothing here can return a string the registry did not write."""
    from app.analysis.impact_graph.knowledge import MECHANISMS, mechanism_meta

    for mechanism_id in _candidate_mechanism_ids(parent_type, parent_id, discovery_source):
        if mechanism_meta(mechanism_id) is None:
            continue
        text = (MECHANISMS[mechanism_id].get("mechanism") or "").strip()
        if text:
            return mechanism_id, text
    return None


def _registry_text_for_entry(entry: dict) -> str | None:
    """The curated string a row may borrow as its DISPLAYED explanation, or
    None.

    Direction guard: the registry writes each mechanism's prose for its
    CANONICAL trigger direction (`crude_price_up`), and `oriented_
    mechanisms` flips the EFFECT without rewriting the sentence. Lending
    "margins compress quickly" to a row whose economic effect is positive
    would publish a §24 contradiction manufactured by this very function,
    so the borrow is allowed only when the row's effect matches the
    mechanism's canonical effect -- or when the canonical effect is
    "mixed", whose text explicitly takes no side ("never automatically
    bullish or bearish"). Anything else: no text, and the caller withholds
    the explanation."""
    resolved = resolve_registry_mechanism(
        entry.get("causal_parent_type"), entry.get("causal_parent_id"),
        entry.get("discovery_source"))
    if resolved is None:
        return None
    mechanism_id, text = resolved

    from app.analysis.impact_graph.knowledge import mechanism_meta

    canonical = (mechanism_meta(mechanism_id) or {}).get("effect")
    effect = entry.get("economic_effect")
    if canonical == "mixed" or canonical == effect:
        return text
    logger.info(
        "registry mechanism %s withheld as display text: canonical effect %s "
        "contradicts row effect %s", mechanism_id, canonical, effect)
    return None


def displayed_claim_for_entry(entry: dict) -> str | None:
    """The §16-clean explanation for one pipeline entry, or None.

    A no-op for anything the reader never sees: an excluded row's verbatim
    model text IS its audit record. For a displayed row, the claim survives
    only if the row has company-specific support or makes no
    company-specific claim; otherwise it is replaced by the curated
    registry string for the mechanism the row hangs off."""
    text = entry.get("mechanism")
    if entry.get("display_tier") not in DISPLAYED_TIERS:
        return text
    supported = has_specific_evidence(
        entry.get("evidence_tier"), entry.get("causal_distance"))
    if supported or not contains_company_specific_claim(text):
        return text
    return sanitize_company_claim(
        text, supported, registry_text=_registry_text_for_entry(entry))


def curated_registry_payload(entry: dict) -> dict | None:
    """A deterministic EvidenceRecord payload citing the curated registry
    mechanism a displayed, artifact-less row rests on (§17 tier D: "curated
    domain knowledge"). No LLM call, no network, no URL -- the registry is
    source code in this repository, so `source_url` is structurally None
    and `quoted_text` is the registry's own sentence, byte for byte.

    None when the row's causal parent resolves to no registry mechanism:
    "curated domain knowledge" is a claim about a specific, reviewable
    registry entry, and inventing a citation for a row that has none is the
    exact failure §16 names."""
    resolved = resolve_registry_mechanism(
        entry.get("causal_parent_type"), entry.get("causal_parent_id"),
        entry.get("discovery_source"))
    if resolved is None:
        return None
    mechanism_id, text = resolved
    return {
        "mechanism_id": mechanism_id,
        "source_type": "curated_registry",
        "source_name": mechanism_id,
        "source_url": None,
        "quoted_text": text,
        # Deduplication key alongside source_url (see persist_evidence), so
        # it must be stable AND distinct per mechanism.
        "fact_text": f"curated registry mechanism {mechanism_id}",
        "evidence_class": entry.get("evidence_class") or "CURATED_ARCHETYPE",
        "evidence_tier": entry.get("evidence_tier") or "D",
        # Existing vocabulary (_PROVENANCED_EXPOSURE_TYPES above): a
        # maintainer-reviewed registry entry, not a model re-confirmation.
        "provenance_type": "CURATED",
        "supports_claim": True,
    }


def evidence_payloads_for_persist(entry: dict) -> list[dict]:
    """The payloads app.pipeline._persist_alert should turn into rows for
    one gated entry (§16: every displayed row carries at least one
    EvidenceRecord).

    Rows that classified with a real artifact (SupplyLink / provenanced
    exposure / article subject) already have theirs -- untouched, and never
    supplemented, so a C-tier row's citation stays the artifact and not a
    curated template sitting next to it. Only a DISPLAYED row that
    classified with nothing at all (tier D) picks up the curated registry
    record."""
    payloads = list(entry.get("evidence_payloads") or [])
    if payloads or entry.get("display_tier") not in DISPLAYED_TIERS:
        return payloads
    curated = curated_registry_payload(entry)
    if curated is None:
        logger.info(
            "displayed row %s (%s) persisted with no evidence record: no "
            "registry mechanism resolves for parent %s/%s",
            entry.get("ticker"), entry.get("display_tier"),
            entry.get("causal_parent_type"), entry.get("causal_parent_id"))
        return []
    return [curated]
