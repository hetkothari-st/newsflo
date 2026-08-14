import hashlib
import json
import logging
import time
from datetime import timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.impact_graph.engine import analyze_article_v3
from app.analysis.refinement import REFINEMENT_PENDING, refine_alert
from app.analysis.schemas import AnalysisOutput, CATEGORIES
from app.companies.history import bulk_past_mentions, mentions_before
from app.companies.market import infer_market
from app.companies.resolution import resolve_companies
from app.config import settings
from app.filtering.relevance import filter_new_articles
from app.market.measure import measure_company_move
from app.ingestion.full_text import fetch_pending_full_text
from app.ingestion.image_filter import repeated_image_urls, resolve_article_image
from app.ingestion.og_image import fetch_og_image
from app.models import (
    Alert, AlertCompany, AnalysisCache, Article, CascadeGap, Company, ImpactEdge, MarketMove, utcnow,
)
from app.reasoning.confidence import _band as band_for_score
from app.reasoning.confidence import compute_confidence, source_credibility
from app.reasoning.financial_context import detect_price_contradiction, get_or_fetch_financial_snapshot
from app.reasoning.rulebook import get_rule
from app.reasoning.versions import KNOWLEDGE_VERSION, PROMPT_VERSION
from app.ws.manager import manager

logger = logging.getLogger(__name__)

# How far back to look for a reusable analysis of a duplicate/republished
# story. Bounded so a months-old identical title (a rare coincidence, not a
# genuine republish) never gets silently reused with stale reasoning.
DEDUP_LOOKBACK_HOURS = 24

# TTL for the v3 (impact-graph) result cache (corrective-v4 Task 15). The
# content-hash key alone made a months-old row replay forever even after
# prompt/schema/policy versions had all moved on around it -- the versioned
# key (see _v3_cache_key) already invalidates on any of those bumps, but a
# row that matches every version AND is genuinely stale (weeks old, from a
# world where the same article text got re-ingested) still should not
# replay indefinitely. 7 days covers every real retry/dedup path with
# margin while keeping old rows from silently outliving their relevance.
V3_CACHE_TTL_DAYS = 7

# An indirect company's confidence is never higher than what the same
# evidence would produce for a direct one -- the LLM's own knowledge of a
# supplier/customer relationship is inherently less certain than a company
# actually named in the article, and each extra hop compounds that. Applied
# as a multiplier on top of the normal compute_confidence() score, not a
# separate scoring path, so an indirect entry's confidence still reflects
# real evidence/calibration signal, just discounted by distance.
LEVEL_CONFIDENCE_MULTIPLIER = {"direct": 1.0, "indirect_l1": 0.7, "indirect_l2": 0.45}

# Impact-graph v3: distances past the legacy 3-level map keep compounding
# 0.7 per hop with a hard floor -- the failure-safe direction is aggressive
# discounting, never the old `.get(level, 1.0)` default that scored an
# unknown level like a direct mention.
_DISTANCE_CONFIDENCE_FLOOR = 0.25


def _confidence_multiplier(causal_distance: int | None, impact_level: str) -> float:
    if causal_distance is not None and causal_distance >= 1:
        if causal_distance == 1:
            return 1.0
        if causal_distance == 2:
            return 0.7
        if causal_distance == 3:
            return 0.45
        return max(_DISTANCE_CONFIDENCE_FLOOR, 0.45 * (0.7 ** (causal_distance - 3)))
    return LEVEL_CONFIDENCE_MULTIPLIER.get(impact_level, 1.0)

# Minimum confidence_score for an AlertCompany row to be persisted.
#
# Applies ONLY to legacy (pre-v3-gate) entries -- ones with no "gate_state"
# key, i.e. impact_engine_v4_strict was off when they were built (see
# _persist_alert). A gated v3 entry already went through the executable
# publication gate (spec Sec5/Sec35, app.pipeline._gate_candidates) before
# reaching here: DISPLAY_ELIGIBLE/primary or DISPLAY_ELIGIBLE/secondary
# entries persist on the gate's own authority, and excluded ones never
# arrive at all (filtered out earlier in _persist_alert). Stacking this
# floor on top of that decision would let a low confidence_score silently
# override a gate that already ruled the company in -- two authorities
# disagreeing about the same row, with this one winning by accident. See
# docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/task-3-brief.md.
#
# Deliberately modest, and NOT the relevance defence. Measured on production
# data, a floor of 40 removes 20 rows of 881 -- and only 16 of 557
# sector_inference rows (2%), the exact category that produced the reported
# bug.
#
# Relevance is enforced structurally instead: basis-keyed bucketing
# (app.market.ripple_layers), candidate grounding (app.companies.candidates),
# and the per-company verification pass (app.analysis.verification). This
# floor only trims the degenerate tail.
#
# Compared against compute_confidence()'s PRE-multiplier score (see
# _build_alert_company's `pre_multiplier_score` return value), never the
# post-LEVEL_CONFIDENCE_MULTIPLIER value stored in confidence_score. The
# floor and the multiplier answer different questions -- "is this
# reasoning well-evidenced?" vs. "how far from the article is this?" -- and
# compounding them was never intended: a typical pre-multiplier score of ~69
# survives the floor fine on its own, but 69 * 0.45 (indirect_l2's
# multiplier) = 31, BELOW this floor -- so comparing the floor to the
# post-multiplier value meant no indirect_l2 row could ever be persisted,
# for any article, silently killing the entire L2 cascade stage.
CONFIDENCE_FLOOR = 40


def _decode_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    return json.loads(value)


def decode_key_points(alert_company: AlertCompany) -> list[str]:
    return _decode_json_list(alert_company.key_points_json)


def article_text(article: Article) -> str:
    return article.full_content or article.content


def _content_hash(article: Article) -> str:
    return hashlib.sha256((article.title + "\n" + article_text(article)).encode()).hexdigest()


def _v3_cache_key(article: Article) -> str:
    """Prefixed, VERSIONED hash keyspace for the v3 result cache (corrective-
    v4 Task 15). "v3:" keeps a v2 AnalysisOutput blob from ever being
    mis-parsed as a v3 result (unchanged from before); the four version
    components that follow make every prompt/schema/knowledge-registry/
    gate-policy bump an EXPLICIT cache miss, and the strict-mode flag keeps
    a v4-strict run from ever replaying a legacy-gated one's result (their
    publication semantics differ). A row keyed under the OLD two-part
    "v3:<hash>" scheme (every row written before this shipped) simply
    never matches this key -- an automatic, zero-code miss, not a
    special-cased "is this a legacy key" branch."""
    from app.analysis.impact_graph.knowledge import KNOWLEDGE_REGISTRY_VERSION
    from app.analysis.impact_graph.prompts import IMPACT_PROMPT_VERSION
    from app.analysis.impact_graph.publication_gate import POLICY_VERSION
    from app.analysis.impact_graph.schemas import IMPACT_SCHEMA_VERSION

    strict_flag = int(settings.impact_engine_v4_strict)
    return (f"v3:{POLICY_VERSION}:{IMPACT_PROMPT_VERSION}:{IMPACT_SCHEMA_VERSION}:"
            f"{KNOWLEDGE_REGISTRY_VERSION}:{strict_flag}:{_content_hash(article)}")


def get_cached_v3(session: Session, article: Article):
    """Impact-graph v3 twin of get_cached_analysis. Versioned hash keyspace
    (see _v3_cache_key) plus a TTL: a row that matches the current key but
    is older than V3_CACHE_TTL_DAYS is treated as a miss rather than
    replayed forever."""
    from app.analysis.impact_graph.schemas import ImpactGraphResult

    cached = session.query(AnalysisCache).filter_by(content_hash=_v3_cache_key(article)).one_or_none()
    if cached is None:
        return None
    created = cached.created_at
    if created is not None:
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < utcnow() - timedelta(days=V3_CACHE_TTL_DAYS):
            return None
    return ImpactGraphResult.model_validate_json(cached.output_json)


def store_v3_cache(session: Session, article: Article, result) -> None:
    session.add(AnalysisCache(content_hash=_v3_cache_key(article), output_json=result.model_dump_json()))


def get_cached_analysis(session: Session, article: Article) -> AnalysisOutput | None:
    """Look up a prior analyze_article() result for this EXACT article
    content (title + body), so a re-run (whether the live pipeline seeing
    a republished duplicate, or a one-off reanalyze_*.py script re-run)
    never has to spend a fresh LLM call to reproduce the same result --
    and always reproduces the SAME result, not a fresh one that may differ
    slightly (LLMs are not literally deterministic across calls)."""
    cached = session.query(AnalysisCache).filter_by(content_hash=_content_hash(article)).one_or_none()
    if cached is None:
        return None
    return AnalysisOutput.model_validate_json(cached.output_json)


def store_analysis_cache(session: Session, article: Article, analysis: AnalysisOutput) -> None:
    session.add(AnalysisCache(content_hash=_content_hash(article), output_json=analysis.model_dump_json()))


def clear_analysis_cache(session: Session, article: Article) -> None:
    """The only intentional way to force a fresh LLM call for content
    that's already cached -- used by reanalyze_*.py's --force flag."""
    session.query(AnalysisCache).filter_by(content_hash=_content_hash(article)).delete()


def _as_aware_utc(dt):
    """SQLite (used by the test suite) silently drops tzinfo on
    ``DateTime(timezone=True)`` columns when a row is reloaded after commit
    -- Postgres (production) does not have this quirk. Normalize so
    subtracting from ``utcnow()`` (always aware) never raises
    ``TypeError: can't subtract offset-naive and offset-aware datetimes``
    regardless of which backend produced the value.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _persist_effect(value: str | None) -> str | None:
    """Persist-boundary alias mapping (corrective plan task 2): "neutral"
    must never reach an economic_effect column -- it normalizes to
    "no_material_impact" like every other parse boundary. Absent stays
    absent (never invented into "uncertain"); this only rewrites a value
    that is actually present."""
    if not value:
        return None
    from app.analysis.impact_graph.schemas import normalize_effect
    return normalize_effect(value)


def _alert_broadcast_payload(session: Session, alert: Alert) -> dict:
    """Shape one live-push payload identical to a single GET /api/alerts entry,
    MINUS the per-viewer ``in_my_holdings`` flag.

    Known simplification: the pipeline has no viewer context at broadcast time,
    so live-pushed companies carry no holdings-match. The frontend defaults
    live-pushed companies to ``in_my_holdings: false`` and the next full
    ``GET /api/alerts`` refresh reconciles them — correct-eventually, and
    simpler than threading per-user state through the broadcast.
    """
    mentions_index = bulk_past_mentions(session, {ac.company_id for ac in alert.companies})
    return {
        "id": alert.id,
        "event_type": alert.event_type,
        "category": alert.category,
        # Translation happens on a separate, later scheduler tick (see
        # app/translation/job.py) -- it can never exist yet at broadcast
        # time, so this is always the raw English category. The client's
        # next REST refresh (GET /api/alerts?lang=...) reconciles it with a
        # real translated label once one exists, the same eventual-
        # consistency treatment already used for in_my_holdings on this same
        # broadcast path.
        "category_label": alert.category,
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id,
            "title": alert.article.title,
            "url": alert.article.url,
            "image_url": alert.article.image_url,
        },
        "companies": [{
            "company_id": ac.company_id,
            "ticker": ac.company.ticker,
            "name": ac.company.name,
            "index_tier": ac.company.index_tier,
            "sector": ac.company.sector,
            "sub_sector": ac.company.sub_sector,
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low,
            "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale,
            "key_points": decode_key_points(ac),
            "basis": ac.basis,
            "confidence": ac.confidence,
            "confidence_score": ac.confidence_score,
            "confidence_band": ac.confidence_band,
            "confidence_contributors": _decode_json_list(ac.confidence_contributors_json),
            "confidence_penalties": _decode_json_list(ac.confidence_penalties_json),
            "reasons": _decode_json_list(ac.reasons_json),
            "evidence_refs": _decode_json_list(ac.evidence_refs_json),
            "risks": _decode_json_list(ac.risks_json),
            "assumptions": _decode_json_list(ac.assumptions_json),
            "unknowns": _decode_json_list(ac.unknowns_json),
            "alternative_hypothesis": ac.alternative_hypothesis,
            "price_at_analysis": ac.price_at_analysis,
            "return_1m": ac.return_1m,
            "return_3m": ac.return_3m,
            "contradiction_note": ac.contradiction_note,
            "impact_level": ac.impact_level,
            "parent_company_id": ac.parent_company_id,
            "market": infer_market(ac.company.ticker),
            "past_mentions": mentions_before(mentions_index, ac.company_id, alert.created_at),
        } for ac in alert.companies],
    }


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def analysis_version() -> str:
    """The FULL contract version a CompanyDecisionRecord was produced
    under: prompt / schema / gate policy / knowledge registry.

    Final-review finding I4: this used to be prompt/schema only, so a bump
    to the publication gate's POLICY_VERSION or to the archetype
    KNOWLEDGE_REGISTRY_VERSION -- either of which changes what the gate
    decides and which mechanisms exist to decide about -- left the version
    string identical, and the dedup-reuse shortcut happily copied decisions
    made under the OLD contract onto a new alert. All four inputs move the
    string now.

    Written on every new record and compared in full by
    _dedup_reuse_policy_allows. Pre-existing 2-part records simply never
    match the 4-part string, so they fall through to a fresh analysis --
    the correct fail-closed direction (no attempt is made to "upgrade" an
    old string, which would be inventing a claim about a contract that was
    never checked)."""
    from app.analysis.impact_graph.knowledge import KNOWLEDGE_REGISTRY_VERSION
    from app.analysis.impact_graph.prompts import IMPACT_PROMPT_VERSION
    from app.analysis.impact_graph.publication_gate import POLICY_VERSION
    from app.analysis.impact_graph.schemas import IMPACT_SCHEMA_VERSION

    return "/".join((
        IMPACT_PROMPT_VERSION, IMPACT_SCHEMA_VERSION,
        POLICY_VERSION, KNOWLEDGE_REGISTRY_VERSION,
    ))


def _dedup_reuse_policy_allows(session: Session, alert: Alert) -> bool:
    """Dedup-reuse gate (corrective-v4 Task 12): the title-dedup shortcut
    must never resurrect an alert whose companies never passed the
    publication gate, nor one persisted under a stale gate contract --
    copying a legacy (pre-gate) alert's field-less rows onto a new alert
    would silently reintroduce exactly the gate bypass this closes.
    Reuse is allowed ONLY when:
      1. every one of the prior alert's AlertCompany rows has a non-NULL
         gate_state (an alert with no companies at all also fails: there is
         nothing gate-authoritative to reuse);
      2. the prior alert has a durable CompanyDecisionRecord audit trail
         (written only in strict mode) whose analysis_version matches the
         CURRENT analysis version -- a version mismatch means the contract
         that produced the old decision has since changed and it can't be
         trusted;
      3. the prior alert's own analysis_quality is "authoritative" (a
         degraded/fallback/budget_exhausted analysis is never reused).
    Any failure falls through to a fresh analysis, never a partial copy.
    """
    companies = alert.companies
    if not companies or any(ac.gate_state is None for ac in companies):
        return False
    if alert.analysis_quality != "authoritative":
        return False
    from app.models import CompanyDecisionRecord

    current_version = analysis_version()
    records = session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    if not records:
        return False
    return all(record.analysis_version == current_version for record in records)


def _find_reusable_alert(session: Session, article: Article) -> Alert | None:
    """Find an already-analyzed article with the EXACT same normalized
    title, fetched recently -- RSS sources frequently republish the
    identical wire story (confirmed in production: "Global Market: ..."
    titles recur verbatim across sources). Reusing that analysis instead of
    calling the LLM again produces the same result a fresh call would (it
    is the same story), while skipping the call entirely.

    Exact-match only, no fuzzy similarity -- this must never risk merging
    two genuinely different stories into one analysis. A title match whose
    alert fails _dedup_reuse_policy_allows is treated as no match at all --
    the caller falls through to a fresh analysis, never a stale/partial
    copy (corrective-v4 Task 12).
    """
    normalized = _normalize_title(article.title)
    cutoff = utcnow() - timedelta(hours=DEDUP_LOOKBACK_HOURS)
    candidates = (
        session.query(Article)
        .filter(Article.status == "ANALYZED")
        .filter(Article.id != article.id)
        .filter(Article.fetched_at >= cutoff)
        .all()
    )
    for candidate in candidates:
        if _normalize_title(candidate.title) == normalized:
            matched = session.query(Alert).filter_by(article_id=candidate.id).first()
            if matched is not None and _dedup_reuse_policy_allows(session, matched):
                return matched
            return None
    return None


def _build_alert_company(
    session: Session, alert_id: int, article: Article, category: str, entry: dict,
) -> tuple[AlertCompany, int]:
    """Build one AlertCompany row (unattached -- caller must session.add it)
    from a resolved entry dict, computing confidence fresh. Split out of
    _persist_alert so a one-off re-analysis script can attach fresh rows to
    an EXISTING alert without duplicating this logic -- see
    backend/reanalyze_cascade.py.

    Magnitude is always the deterministic value the analysis produced
    (entry["magnitude_low"]/["magnitude_high"], monotonic in impact_strength
    for v3 -- see _v3_entries), never blended with realized-outcome
    CalibrationSample stats: app.calibration.blender.get_calibrated_magnitude
    used to override it once enough samples existed, which meant how a
    company's stock actually moved after past, unrelated articles could
    silently widen or narrow THIS article's stated magnitude range. See
    docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/task-3-brief.md.
    `confidence` ("llm_estimate") documents that provenance for the reader;
    nothing currently sets it to "calibrated".

    `category` is accepted-and-unused: it fed the calibration lookups this
    function no longer makes, but stays a required positional so this
    function's call signature (also used directly by
    backend/reanalyze_cascade.py) doesn't have to change everywhere for an
    internal implementation detail.

    Returns (alert_company, pre_multiplier_score): the AlertCompany's own
    confidence_score is the LEVEL_CONFIDENCE_MULTIPLIER-discounted value
    (what's displayed/persisted); pre_multiplier_score is
    compute_confidence()'s raw score before that discount, which
    CONFIDENCE_FLOOR must be compared against (see CONFIDENCE_FLOOR's own
    comment) -- returned here rather than recomputed by the caller so this
    stays the single place that calls compute_confidence.
    """
    magnitude_low, magnitude_high = entry["magnitude_low"], entry["magnitude_high"]
    confidence = "llm_estimate"

    reasons = entry.get("reasons") or []
    evidence_refs = entry.get("evidence_refs") or []
    matched_rule_ids = [ref for ref in evidence_refs if get_rule(ref) is not None]

    company_obj = session.get(Company, entry["company_id"])
    # Fetched and persisted purely as an observational market fact (see
    # return_1m/return_3m/contradiction_note below) -- NOT read by
    # compute_confidence, which never sees this snapshot at all.
    snapshot = get_or_fetch_financial_snapshot(session, company_obj.ticker) if company_obj else None
    contradiction_note = detect_price_contradiction(
        entry["direction"], snapshot["return_1m"] if snapshot else None,
    )

    article_age_hours = (
        utcnow() - _as_aware_utc(article.published_at or article.fetched_at)
    ).total_seconds() / 3600

    result = compute_confidence(
        claim_count=len(reasons),
        # Corrective-v4 Task 5: `evidence_refs` is the LLM's own free-text
        # citation list, self-reported and never independently checked --
        # it can never be the thing that RAISES a claim's confidence.
        # `matched_rule_ids` is the subset that actually resolved against
        # the rulebook (a real, deterministic check), so ONLY that count
        # feeds the evidence-completeness component. A company that pads
        # evidence_refs with invented ids scores identically to one that
        # supplied none -- see tests/test_evidence_records.py::
        # test_llm_evidence_refs_cannot_raise_confidence.
        evidence_ref_count=len(matched_rule_ids),
        rule_matched=bool(matched_rule_ids),
        source_credibility=source_credibility(article.source),
        article_age_hours=article_age_hours,
    )

    impact_level = entry.get("impact_level") or "direct"
    level_multiplier = _confidence_multiplier(entry.get("causal_distance"), impact_level)
    confidence_score = round(result.score * level_multiplier)
    confidence_band = result.band if level_multiplier == 1.0 else band_for_score(confidence_score)

    alert_company = AlertCompany(
        alert_id=alert_id,
        company_id=entry["company_id"],
        direction=entry["direction"],
        magnitude_low=magnitude_low,
        magnitude_high=magnitude_high,
        rationale=entry["rationale"],
        key_points_json=json.dumps(entry.get("key_points") or []),
        confidence_score=confidence_score,
        time_horizon=entry["time_horizon"],
        basis=entry["basis"],
        confidence=confidence,
        reasons_json=json.dumps(reasons),
        evidence_refs_json=json.dumps(evidence_refs),
        risks_json=json.dumps(entry.get("risks") or []),
        assumptions_json=json.dumps(entry.get("assumptions") or []),
        unknowns_json=json.dumps(entry.get("unknowns") or []),
        alternative_hypothesis=entry.get("alternative_hypothesis"),
        confidence_band=confidence_band,
        confidence_contributors_json=json.dumps(result.contributors),
        confidence_penalties_json=json.dumps(result.penalties),
        rulebook_ids_json=json.dumps(matched_rule_ids),
        price_at_analysis=snapshot["price"] if snapshot else None,
        return_1m=snapshot["return_1m"] if snapshot else None,
        return_3m=snapshot["return_3m"] if snapshot else None,
        contradiction_note=contradiction_note,
        impact_level=impact_level,
        parent_company_id=entry.get("parent_company_id"),
        # Impact-graph v3 analytical fields -- None for legacy entries.
        causal_distance=entry.get("causal_distance"),
        impact_strength=entry.get("impact_strength"),
        confidence_f=entry.get("confidence_f"),
        materiality=entry.get("materiality"),
        causal_parent_type=entry.get("causal_parent_type"),
        causal_parent_id=entry.get("causal_parent_id"),
        mechanism=entry.get("mechanism"),
        channels_json=entry.get("channels_json"),
        economic_effect=_persist_effect(entry.get("economic_effect")),
        # V4 strict gate outcome -- None for legacy (ungated) entries.
        display_tier=entry.get("display_tier"),
        gate_state=entry.get("gate_state"),
        # The COMPOSITE grade the gate evaluated (final-review finding I3):
        # the SAME value that went out on CandidateInput.materiality_grade
        # and onto the decision record, not a grade re-derived from the raw
        # float. _v3_entries sets it from GateDecision.materiality_grade.
        materiality_grade=entry.get("materiality_grade"),
        # Expected market sensitivity (corrective-v4 task 10): set ONLY from
        # entry["expected_market_sensitivity"], which _v3_entries populates
        # from GraphCompany.expected_market_sensitivity directly -- never
        # from price_at_analysis/return_1m/return_3m above.
        expected_market_sensitivity=entry.get("expected_market_sensitivity"),
    )
    return alert_company, result.score


def _resolve_edge_endpoint_company_id(session: Session, node_kind: str, label: str) -> int | None:
    """label is a ticker string when node_kind=="company" -- resolve it to
    a real Company row's id via a direct exact-match query (same
    ticker-first discipline as app.companies.resolution._find_direct_company,
    but simpler since an edge label is always a ticker string, never a
    company name). Returns None (never raises, never drops the edge) if the
    node isn't a company or the ticker doesn't resolve -- the edge still
    persists with a null company id, matching this codebase's "omit rather
    than mismatch" resolution discipline applied to a link field, not the
    whole row."""
    if node_kind != "company":
        return None
    company = session.query(Company).filter_by(ticker=label).one_or_none()
    return company.id if company else None


def measure_and_reconcile_alert_companies(session: Session, alert_id: int, alert_companies: list) -> list:
    """Measure each AlertCompany's market reaction and reconcile its
    `direction` against the REAL measured move, before why-text generation
    ever reads `direction` -- the LLM's direction call happens BEFORE the
    market has actually reacted, so it is a prediction, not a fact.

    Shared by _persist_alert (fresh-analysis and dedup-reuse paths) and
    reanalyze_cascade.py's re-analysis path so the two can't drift --
    reanalyzing an alert must produce the same measurement/reconciliation
    behavior a brand-new analysis would, not a cheaper approximation of it.

    Returns the list of persisted MarketMove rows (added to the session but
    not committed -- the caller commits).
    """
    # Copied, not joined: alerts get recategorized later and the
    # volatility-range pools must not re-shuffle when they do
    # (spec 2026-08-05 §3.2). Stamped here so the fresh-analysis and
    # re-analysis paths cannot drift apart on it.
    alert_row = session.get(Alert, alert_id)
    alert_category = alert_row.category if alert_row is not None else None

    # Event time anchors the bar-vs-event ordering guard (spec §21): a
    # weekend/after-hours alert must not record the last PRE-event bar as
    # its reaction.
    event_time = _as_aware_utc(alert_row.created_at) if alert_row is not None else None
    market_moves = []
    for alert_company in alert_companies:
        company_obj = session.get(Company, alert_company.company_id)
        if company_obj is not None:
            move = measure_company_move(session, company_obj, event_time=event_time)
            move.alert_id = alert_id
            move.category = alert_category
            session.add(move)
            market_moves.append(move)

    # Reconcile each AlertCompany.direction with its own REAL measured move.
    # Measurement is the spine (spec Ground Rules): once a real reaction
    # exists, it must always win over a stale pre-measurement guess, or the
    # UI ends up showing a green "bullish"/"positively impacting" narrative
    # next to a red, negative excess-move number for the same company --
    # confirmed happening in production (a merger-news alert called
    # "bullish" while the stock's actual measured reaction was -3.1%). Only
    # overwrites when a real measurement exists (measurement_status == "ok");
    # an unmeasured/exposure-only company keeps the LLM's own call, since
    # there is no measured reality yet to defer to.
    # V4 strict (spec §2.4/§40, INV-001): market reaction is an observation,
    # never an authority over the fundamental call. `direction` and the
    # fundamental prose stay untouched; the measured move lives on the
    # MarketMove row and is serialized separately.
    if settings.impact_engine_v4_strict:
        return market_moves
    moves_by_company_id = {m.company_id: m for m in market_moves}
    for alert_company in alert_companies:
        # STRUCTURAL, not modal (final-review finding I1 -- same rule
        # app.analysis.impact_graph.publication_gate.is_gated states, applied
        # per row). The flag early-return above only protects gated rows
        # while the flag is ON; a scheduler-driven remeasure with the flag
        # OFF used to reach rows the gate had already ruled on and overwrite
        # `direction` (NULLing rationale/key_points_json with it) from a
        # market observation -- exactly the market-over-fundamental inversion
        # INV-001 forbids, destroying gate output that is authoritative once
        # persisted. A row carrying gate_state or display_tier is never
        # reconciled, whatever the flag says; a legacy (all-NULL) row keeps
        # its byte-identical pre-gate behavior.
        if alert_company.gate_state is not None or alert_company.display_tier is not None:
            continue
        move = moves_by_company_id.get(alert_company.company_id)
        if move is None or move.measurement_status != "ok" or move.excess_move_pct is None:
            continue
        measured_direction = "bullish" if move.excess_move_pct >= 0 else "bearish"
        if measured_direction != alert_company.direction:
            # The rationale and key_points argue for the direction the LLM
            # predicted, which the measured reaction has just contradicted.
            # Leaving them produces a bearish badge above bullish prose for
            # the same company. Drop the text rather than keep an argument
            # for a call that no longer stands -- refine_alert (when called)
            # generates a fresh, measurement-aware `why` for this company.
            alert_company.rationale = None
            alert_company.key_points_json = json.dumps([])
        alert_company.direction = measured_direction
    return market_moves


# How far back a no_data move is still worth re-measuring. Short on
# purpose: measure_company_move reads the LATEST daily bar, so re-measuring
# a week-old alert would record today's move as if it were the event-day
# reaction. Within this window the latest bar still IS the event's reaction
# window (persist-time measurement has the same "latest bar at measurement
# time" semantics).
_REMEASURE_WINDOW_DAYS = 3
_REMEASURE_BATCH = 40


def remeasure_no_data_moves(session: Session, limit: int = _REMEASURE_BATCH) -> int:
    """Re-measure recent MarketMove rows that are still not a trustworthy
    final reading: measurement_status in ("no_data", "stale",
    "data_invalid"), OR measurement_status == "ok" with bar_complete == 0
    (a partial intraday snapshot recorded before the session closed --
    Task 14: re-measuring it after close turns it into the real completed-
    session reaction instead of leaving the mid-session number stuck
    forever). Measurement is one-shot at persist time, so a transient
    price-fetch failure (yfinance burst rate-limit) used to orphan the
    alert forever: the feed only shows measured alerts, and nothing ever
    retried the measurement (production 2026-08-11: every alert on the
    ingestion-v2 service invisible for exactly this reason). Updates rows
    in place -- the (alert_id, company_id) unique constraint means a new
    row was never an option -- and reconciles AlertCompany.direction with
    the fresh measured move under the same rule as first-time measurement.
    Returns how many rows were updated to a fresh 'ok' status."""
    cutoff = utcnow() - timedelta(days=_REMEASURE_WINDOW_DAYS)
    pending = (
        session.query(MarketMove)
        .join(Alert, MarketMove.alert_id == Alert.id)
        .filter(
            Alert.created_at >= cutoff,
            or_(
                MarketMove.measurement_status.in_(("no_data", "stale", "data_invalid")),
                and_(MarketMove.measurement_status == "ok", MarketMove.bar_complete == 0),
            ),
        )
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    fixed = 0
    for move in pending:
        company = session.get(Company, move.company_id)
        if company is None:
            continue
        alert_row = session.get(Alert, move.alert_id)
        event_time = _as_aware_utc(alert_row.created_at) if alert_row is not None else None
        fresh = measure_company_move(session, company, event_time=event_time)
        if fresh.measurement_status != "ok":
            continue  # still not measurable -- leave the honest row alone
        for column in (
            "raw_move_pct", "sector_move_pct", "benchmark_ticker", "excess_move_pct",
            "volume", "avg_volume_20d", "volume_multiple", "vol_normalized",
            "materiality", "avg_traded_value", "measured_at", "measurement_status",
            "last_bar_date", "bar_complete", "data_quality", "session_state",
            "reaction_significance",
        ):
            setattr(move, column, getattr(fresh, column))
        # move.category keeps its persist-time stamp (recategorization safety).
        # Same reconcile rule as measure_and_reconcile_alert_companies: the
        # measured reality overrides the LLM's pre-measurement guess, and
        # prose arguing for the contradicted direction is dropped.
        # V4 strict: same separation as measure_and_reconcile_alert_companies
        # -- the late measurement updates the MarketMove row only.
        if not settings.impact_engine_v4_strict:
            alert_company = (
                session.query(AlertCompany)
                .filter_by(alert_id=move.alert_id, company_id=move.company_id)
                .one_or_none()
            )
            # Same structural gated-row skip as
            # measure_and_reconcile_alert_companies (final-review finding
            # I1): this is the scheduler-driven path that actually reached
            # gated rows in production with the flag off. Gate output is
            # authoritative once persisted -- never overwritten by a market
            # observation, whatever the flag says.
            if alert_company is not None and (
                alert_company.gate_state is not None or alert_company.display_tier is not None
            ):
                alert_company = None
            if alert_company is not None and move.excess_move_pct is not None:
                measured_direction = "bullish" if move.excess_move_pct >= 0 else "bearish"
                if measured_direction != alert_company.direction:
                    alert_company.rationale = None
                    alert_company.key_points_json = json.dumps([])
                alert_company.direction = measured_direction
        fixed += 1
    if fixed:
        session.commit()
    return fixed


def _copy_gate_audit_trail(session: Session, prior_alert_id: int, new_alert_id: int) -> None:
    """Copy a reused alert's gate audit trail onto the new alert (corrective-
    v4 Task 12, review round 2 / I2+I3): the publication gate ran exactly
    ONCE, against the prior article -- synthesizing a fresh
    CompanyDecisionRecord from the copied AlertCompany fields (the
    gated_entries branch below, built for a REAL gate run) would invent an
    audit trail for a gate walk that never happened against this alert.
    Instead, copy the prior alert's decision records (analysis_version
    PRESERVED as originally written -- it describes the gate contract that
    actually produced the decision, not "now") and the EvidenceRecord rows
    they cite, as new rows under `new_alert_id`. Evidence is copied first so
    each decision record's `candidate_json.evidence_ids` can be remapped to
    the new rows' ids rather than pointing at another alert's evidence."""
    from app.models import CompanyDecisionRecord, EvidenceRecord

    prior_evidence = (
        session.query(EvidenceRecord).filter_by(alert_id=prior_alert_id).order_by(EvidenceRecord.id).all()
    )
    evidence_id_map: dict[int, int] = {}
    for record in prior_evidence:
        copy = EvidenceRecord(
            alert_id=new_alert_id, company_id=record.company_id,
            mechanism_id=record.mechanism_id, evidence_class=record.evidence_class,
            evidence_tier=record.evidence_tier, source_type=record.source_type,
            source_name=record.source_name, source_url=record.source_url,
            source_date=record.source_date, as_of_date=record.as_of_date,
            quoted_text=record.quoted_text, fact_text=record.fact_text,
            quality=record.quality, reliability=record.reliability,
            provenance_type=record.provenance_type, supports_claim=record.supports_claim,
            supports_direction=record.supports_direction,
            supports_materiality=record.supports_materiality,
            verified_at=record.verified_at, review_after=record.review_after,
        )
        session.add(copy)
        session.flush()
        evidence_id_map[record.id] = copy.id

    prior_decisions = (
        session.query(CompanyDecisionRecord).filter_by(alert_id=prior_alert_id)
        .order_by(CompanyDecisionRecord.id).all()
    )
    for record in prior_decisions:
        candidate = json.loads(record.candidate_json) if record.candidate_json else {}
        old_evidence_ids = candidate.get("evidence_ids") or []
        # Every id here came from persist_evidence against this same
        # prior_alert_id, so it is always in evidence_id_map -- the
        # .get(eid, eid) fallback is defensive only, never dropping a
        # reference outright if that invariant is ever violated.
        candidate["evidence_ids"] = [evidence_id_map.get(eid, eid) for eid in old_evidence_ids]
        # Fix (review round, corrective-v4 Task 18 follow-up): this loop
        # used to copy only the pre-Task-18 columns, silently dropping the
        # completeness columns Task 18 added -- every reused alert's audit
        # trail lost exactly the data that task exists to preserve.
        # gate_inputs_json/discovery_sources_json/provider/model/
        # analysis_quality/correction_json describe the SAME gate walk as
        # candidate_json/analysis_version (never regenerated, same
        # reasoning as those two), so they're copied verbatim. evidence_
        # ids_json is the ONE exception: like candidate_json.evidence_ids
        # above, its ids point at EvidenceRecord rows, which get NEW ids
        # under new_alert_id -- copying it verbatim would leave it pointing
        # at another alert's (or nothing's) evidence, so it goes through
        # the SAME evidence_id_map remap, from the SAME source list, so the
        # two columns can never drift apart from each other post-copy.
        old_evidence_ids_json = (
            json.loads(record.evidence_ids_json) if record.evidence_ids_json else []
        )
        remapped_evidence_ids_json = [
            evidence_id_map.get(eid, eid) for eid in old_evidence_ids_json
        ]
        session.add(CompanyDecisionRecord(
            alert_id=new_alert_id, company_id=record.company_id, ticker=record.ticker,
            final_state=record.final_state, display_tier=record.display_tier,
            rejection_reason=record.rejection_reason,
            gates_passed_json=record.gates_passed_json,
            evidence_class=record.evidence_class,
            materiality_grade=record.materiality_grade,
            candidate_json=json.dumps(candidate),
            # PRESERVED, not regenerated (see docstring): this row
            # describes the gate run that actually produced it.
            analysis_version=record.analysis_version,
            gate_inputs_json=record.gate_inputs_json,
            evidence_ids_json=json.dumps(remapped_evidence_ids_json),
            discovery_sources_json=record.discovery_sources_json,
            provider=record.provider,
            model=record.model,
            analysis_quality=record.analysis_quality,
            correction_json=record.correction_json,
        ))
    session.flush()


def _analysis_model_for_provider(provider: str | None) -> str | None:
    """Best-effort model name for the decision-record audit trail (spec
    sec54, corrective-v4 Task 18). The router records which PROVIDER served
    an alert (app.analysis.impact_graph.router.StageRouter.provider) but not
    which specific model -- stage overrides
    (settings.claude_stage_model_override_map / the old
    settings.gemini_stage_model_override_map) can diverge per call, so
    this names the common-case reasoning-stage model for that provider,
    not a per-call-exact audit. An unrecognized provider is returned as-is
    (never invented into a guessed model name).

    Provider-migration follow-up (Task 6 review): "claude" was missing here
    -- it fell through to the `return provider` default, so every
    CompanyDecisionRecord/EvidenceRecord written under the Claude provider
    persisted model="claude" (the literal provider string, not a model id).
    settings.claude_model is the same "everything else -> high thinking"
    default model StageRouter dispatches non-fact/non-summary stages to
    (app.analysis.impact_graph.router); the per-call EXACT model (fact/
    summary stage overrides included) is separately recorded per-row in
    llm_call_usage.model (app.analysis.usage_log.CallUsage), which this
    best-effort field has never tried to replace."""
    if provider == "claude":
        return settings.claude_model
    if provider == "gemini":
        return settings.gemini_reasoning_model
    if provider == "groq":
        return settings.groq_aux_model
    return provider


def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
    gaps: list[dict] | None = None, edges: list[dict] | None = None, client=None, facts: str | None = None,
    analysis_provider: str | None = None, analysis_quality: str | None = None,
    event_cause: str | None = None, reused_from_alert_id: int | None = None,
    ambiguous_entities: list[str] | None = None,
) -> Alert:
    """Create the Alert + AlertCompany rows for one article and fan out
    notifications/broadcast. Shared by both the fresh-analysis path and the
    dedup-reuse path -- calibration AND confidence are always looked up/
    computed fresh here (not copied from a reused analysis) so a reused
    alert reflects the current calibration state exactly like a brand new
    analysis would.

    `reused_from_alert_id`: set ONLY by the dedup-reuse call site (corrective-
    v4 Task 12) to the prior alert's id -- an explicit flag, not inferred
    from entry dict shape. When set, the gate audit trail (CompanyDecision
    Record + EvidenceRecord rows) is COPIED from that prior alert via
    _copy_gate_audit_trail instead of being synthesized fresh from `entries`
    (see that function's docstring for why: the gate walk ran once, not
    twice).

    `ambiguous_entities`: ImpactGraphResult.ambiguous_entities (corrective-
    v4 Task 18, ledger parked item a) -- entity names the alias matcher
    found genuinely ambiguous and that therefore NEVER became a candidate
    at all (dropped before any mapping call could propose them, so no
    `entries` row exists for them either). Only meaningful on the fresh-
    analysis path; the dedup-reuse path leaves it None and relies on
    _copy_gate_audit_trail to carry over whatever ambiguous-entity records
    the prior alert already wrote.
    """
    # The tool schema constrains `category` to CATEGORIES, but that's a
    # request-time hint, not a guarantee -- defend against a provider that
    # doesn't strictly enforce JSON-schema enums (or a future caller that
    # bypasses the LLM path) ever persisting a value the frontend's swatch
    # maps don't recognize, same failure mode that used to let a full
    # sentence through as a "category" and break the badge's layout.
    if category not in CATEGORIES:
        category = "other"
    alert = Alert(
        article_id=article.id, category=category, event_type=event_type,
        event_cause=event_cause,
        prompt_version=PROMPT_VERSION, knowledge_version=KNOWLEDGE_VERSION,
        # Stored BEFORE refine_alert runs below -- that is the evidence base
        # it reasons from (see app.analysis.refinement.refine_alert). None
        # for a caller with no cascade output to hand over (a direct
        # _persist_alert call in a test or one-off script), which simply
        # falls refinement back to the article text.
        facts=facts,
        analysis_provider=analysis_provider,
        analysis_quality=analysis_quality,
    )
    session.add(alert)
    session.flush()

    if reused_from_alert_id is not None:
        # Dedup-reuse (Task 12 review round 2): copy the REAL prior gate
        # run's audit trail instead of synthesizing a fresh one below --
        # reused entries already carry gate_state/display_tier etc. for
        # _build_alert_company further down, but must never fabricate a
        # new CompanyDecisionRecord for a gate walk that didn't happen
        # against this alert. `entries` needs no excluded-tier filtering
        # here: the prior alert's AlertCompany rows (the source of these
        # entries) already exclude "excluded" tier by construction.
        _copy_gate_audit_trail(session, reused_from_alert_id, alert.id)
    else:
        # V4 strict publication gate (spec §5/§35): every gate-evaluated
        # entry leaves a durable decision record -- accepted or not -- and
        # excluded entries never become AlertCompany rows. Legacy entries
        # (no gate fields) skip both branches untouched.
        gated_entries = [e for e in entries if "gate_state" in e]
        if gated_entries or (settings.impact_engine_v4_strict and ambiguous_entities):
            from app.analysis.impact_graph.evidence import persist_evidence
            from app.models import CompanyDecisionRecord

            for entry in gated_entries:
                # company_id is None for a ticker that never resolved to a
                # Company row (ledger parked item b) -- session.get with a
                # None pk is invalid, so that case skips straight to None.
                company_row = (
                    session.get(Company, entry["company_id"])
                    if entry.get("company_id") is not None else None
                )
                # Turn this candidate's EvidenceRecord payloads (Task 5) into
                # real rows now that the Alert exists -- classify_evidence
                # (called earlier, pre-flush) could only hand back plain
                # dicts, never ids. Stored on the entry too so a kept entry's
                # ids survive past this loop (candidate_json below is the
                # decision record's copy).
                evidence_ids = persist_evidence(
                    session, alert.id, entry.get("company_id"), entry.get("evidence_payloads") or [])
                entry["evidence_ids"] = evidence_ids
                session.add(CompanyDecisionRecord(
                    alert_id=alert.id, company_id=entry.get("company_id"),
                    ticker=(
                        company_row.ticker if company_row
                        else (entry.get("ticker") or str(entry.get("company_id")))
                    ),
                    final_state=entry["gate_state"], display_tier=entry["display_tier"],
                    rejection_reason=entry.get("rejection_reason"),
                    gates_passed_json=json.dumps(entry.get("gates_passed") or []),
                    evidence_class=entry.get("evidence_class"),
                    materiality_grade=entry.get("materiality_grade"),
                    candidate_json=json.dumps({
                        "economic_effect": _persist_effect(entry.get("economic_effect")),
                        "causal_distance": entry.get("causal_distance"),
                        "materiality": entry.get("materiality"),
                        "confidence_f": entry.get("confidence_f"),
                        "mechanism": entry.get("mechanism"),
                        "rationale": entry.get("rationale"),
                        # Alert-level finalization note (primary_cap_overflow,
                        # duplicate_company) -- no column of its own until the
                        # decision-record schema work, but never dropped.
                        "decision_notes": entry.get("decision_notes"),
                        "evidence_ids": evidence_ids,
                    }),
                    analysis_version=analysis_version(),
                    # Decision-record completeness (spec sec54, corrective-v4
                    # Task 18).
                    gate_inputs_json=json.dumps(entry.get("gate_inputs") or {}),
                    evidence_ids_json=json.dumps(evidence_ids),
                    discovery_sources_json=json.dumps([entry.get("discovery_source") or "unknown"]),
                    provider=analysis_provider,
                    model=_analysis_model_for_provider(analysis_provider),
                    analysis_quality=analysis_quality,
                    correction_json=(
                        json.dumps(entry["applied_correction"])
                        if entry.get("applied_correction") else None
                    ),
                ))
            entries = [e for e in entries if e.get("display_tier") != "excluded"]

            # Ledger parked item (a), corrective-v4 Task 18: entities the
            # alias matcher found genuinely ambiguous never seed a
            # candidate at all -- they are dropped in
            # engine._subject_companies_ex before any mapping call could
            # ever propose them, so no `entries` row (and no REJECT_
            # ENTITY_AMBIGUOUS from the loop above, which only covers a
            # ticker that DID reach a GraphCompany) exists for them. This
            # is the one durable record of that invisible drop, keyed by
            # the entity's own name since there is no ticker or company_id
            # to attach to.
            if ambiguous_entities:
                for name in ambiguous_entities:
                    session.add(CompanyDecisionRecord(
                        alert_id=alert.id, company_id=None, ticker=(name or "")[:64],
                        final_state="REJECT_ENTITY_AMBIGUOUS", display_tier="excluded",
                        rejection_reason="REJECT_ENTITY_AMBIGUOUS",
                        analysis_version=analysis_version(),
                        provider=analysis_provider,
                        model=_analysis_model_for_provider(analysis_provider),
                        analysis_quality=analysis_quality,
                    ))

    alert_companies = []
    kept_entries = []
    for entry in entries:
        alert_company, pre_multiplier_score = _build_alert_company(session, alert.id, article, category, entry)
        # A gated (v3) entry already passed (or was filtered out for
        # failing) the executable publication gate above -- that gate is
        # the SOLE persistence authority for it (spec Sec5/Sec35; see
        # CONFIDENCE_FLOOR's own comment). Re-applying a confidence-score
        # floor on top would let a low fundamental-evidence score silently
        # veto a row the gate already ruled DISPLAY_ELIGIBLE, or vice
        # versa keep a row the gate already excluded -- two authorities
        # deciding the same question. Only a legacy (ungated) entry, which
        # never went through the gate at all, still needs this floor as
        # its only persistence check.
        if "gate_state" not in entry and pre_multiplier_score < CONFIDENCE_FLOOR:
            logger.info(
                "dropping company_id=%s from alert_id=%s: confidence %s below floor %s",
                entry["company_id"], alert.id, pre_multiplier_score, CONFIDENCE_FLOOR,
            )
            continue
        session.add(alert_company)
        alert_companies.append(alert_company)
        kept_entries.append(entry)
    entries = kept_entries

    market_moves = measure_and_reconcile_alert_companies(session, alert.id, alert_companies)

    if client is not None:
        if settings.refinement_mode == "deferred":
            # Deferred refinement (cost-optimization phase 5): nothing below
            # this point, and nothing user-facing, reads the fields
            # refine_alert writes -- the alert is broadcast, matched to
            # holdings and served with them null already, which is exactly
            # what a failed inline refinement has always produced. So the
            # four calls move off this run's critical path and a later
            # batch pass (refinement.run_pending_refinements) fills them in.
            alert.refinement_status = REFINEMENT_PENDING
        else:
            try:
                refine_alert(client, session, alert, article, alert_companies, market_moves)
            except Exception:
                logger.exception(
                    "refine_alert failed for alert_id=%s; persisting without LLM refinement fields", alert.id,
                )

    for gap in (gaps or []):
        session.add(CascadeGap(
            alert_id=alert.id, sector=gap["sector"], impact_level=gap["impact_level"],
            parent_ticker=gap.get("parent_ticker"), attempts=gap["attempts"], last_error=gap.get("last_error"),
        ))

    for edge in (edges or []):
        from_company_id = _resolve_edge_endpoint_company_id(session, edge["from"]["kind"], edge["from"]["label"])
        to_company_id = _resolve_edge_endpoint_company_id(session, edge["to"]["kind"], edge["to"]["label"])
        from_label = edge["from"]["label"]
        # A sector->company attachment edge (app.analysis.cascade.
        # _sector_attachment_edges) labels the sector node with the
        # CompanyMention's own per-call sector classification, which can
        # diverge from the company's actual, authoritative Company.sector
        # (e.g. a cascade stage bucketing a company under "other" while its
        # real DB sector is "defense") -- every other chart (Cascade Levels,
        # Sector Tree) reads company.sector directly, so this edge's label
        # must match that same ground truth rather than the LLM's transient
        # classification, or the graph shows a different sector than the
        # rest of the page for the same company.
        if edge["from"]["kind"] == "sector" and edge["to"]["kind"] == "company" and to_company_id is not None:
            company = session.get(Company, to_company_id)
            if company is not None and company.sector:
                from_label = company.sector
        session.add(ImpactEdge(
            alert_id=alert.id,
            from_company_id=from_company_id,
            from_node_kind=edge["from"]["kind"], from_label=from_label,
            to_company_id=to_company_id,
            to_node_kind=edge["to"]["kind"], to_label=edge["to"]["label"],
            relation=edge["relation"], direction=edge["direction"], note=edge["note"], source=edge["source"],
            # Impact-graph v3 typed-edge fields -- absent (None) on legacy
            # cascade edges, carried through when the v3 adapter built them.
            parent_type=edge.get("parent_type"), child_type=edge.get("child_type"),
            causal_distance=edge.get("causal_distance"),
            impact_strength=edge.get("impact_strength"), confidence_f=edge.get("confidence_f"),
            materiality=edge.get("materiality"), time_horizon=edge.get("time_horizon"),
            verification_status=edge.get("verification_status"),
            economic_effect=_persist_effect(edge.get("economic_effect")),
        ))

    # Prefer a real story photo: a missing OR generic (publisher-logo)
    # provided image triggers an og:image fetch from the article's own
    # page -- see app.ingestion.image_filter.resolve_article_image. The
    # repetition signal feeds in too: boilerplate with a clean filename
    # (e.g. GlobeNewswire's default banner) must still get the re-fetch.
    repeated_images = repeated_image_urls(session, [article.image_url] if article.image_url else [])
    article.image_url = resolve_article_image(
        article.url, article.image_url, fetch=fetch_og_image,
        provided_is_generic=article.image_url in repeated_images,
        headline=article.title,
    )

    article.status = "ANALYZED"
    article.category = category
    session.commit()

    new_notifications = match_alert_to_holdings(session, alert)
    send_pending_notifications(session, new_notifications)
    manager.broadcast_sync(_alert_broadcast_payload(session, alert))
    return alert


def build_anchor_sub_sectors(session: Session, companies: list) -> dict[str, set[str]]:
    """Anchor each sector's fan-out to the sub-sectors of the companies the
    model actually named there -- see resolve_companies.

    Extracted out of process_new_articles so reanalyze_cascade.py (and any
    other caller re-running analysis outside the live pipeline) builds the
    exact same map rather than a hand-rolled copy that can drift -- a
    duplicated version of this loop is exactly the failure mode that let the
    fmcg/Eternal sector fan-out bug slip through in the first place.
    """
    anchor_sub_sectors: dict[str, set[str]] = {}
    for mention in companies:
        if not (mention.is_direct and mention.ticker and mention.sector):
            continue
        company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
        if company is not None and company.sub_sector:
            anchor_sub_sectors.setdefault(mention.sector, set()).add(company.sub_sector)
    return anchor_sub_sectors


# Per-tick cap on Pulse og:image scrapes -- serial HTTP GETs, so bound the
# work each cycle; the tail catches up next tick.
_PULSE_IMAGE_BATCH = 15


def backfill_pulse_images(session: Session) -> None:
    """Pulse's RSS carries no images but the app's cards require one --
    scrape each pulse article's publisher page for its og:image, newest
    first. A failed scrape stores "" (attempted-and-failed sentinel, so
    it is never rescraped every tick); serializers already treat empty as
    image-less and _persist_alert's own og fallback only fires on None,
    so the sentinel never causes a duplicate fetch there either."""
    articles = (
        session.query(Article)
        .filter(Article.provider == "pulse_zerodha", Article.image_url.is_(None))
        .order_by(Article.published_at.desc().nullslast())
        .limit(_PULSE_IMAGE_BATCH)
        .all()
    )
    for article in articles:
        article.image_url = fetch_og_image(article.url) or ""
        session.commit()


def grant_paid_analysis(session: Session, article: Article) -> bool:
    """Impact-graph v3's boolean twin of select_analysis_client's budget
    logic: True when THIS article may run its analysis on the paid Gemini
    chain. Same accounting rows, same IST-day window, same retry-proof
    same-day reuse, same stale-grant refusal -- one implementation, used by
    both entry points."""
    from app.ist_time import day_utc_window, today_ist
    from app.models import GeminiPaidUsage

    if article.provider not in settings.gemini_paid_provider_set:
        return False
    day_start, _ = day_utc_window(today_ist())
    existing = session.query(GeminiPaidUsage).filter_by(article_id=article.id).one_or_none()
    if existing is not None:
        return _as_aware_utc(existing.used_at) >= day_start
    used_today = session.query(GeminiPaidUsage).filter(GeminiPaidUsage.used_at >= day_start).count()
    if used_today >= settings.gemini_paid_daily_article_budget:
        return False
    session.add(GeminiPaidUsage(article_id=article.id))
    session.commit()
    return True


def select_analysis_client(session: Session, article: Article, claude_client):
    """The client this article's cascade may use. The PAID Gemini chain
    (CallRoutedClient) is granted ONLY to articles from an eligible
    provider (settings.gemini_paid_providers, default: pulse_zerodha) and
    ONLY within today's article budget
    (settings.gemini_paid_daily_article_budget) -- everything else gets
    the router's free default chain. Budget accounting is retry-proof: an
    article that already holds a gemini_paid_usage row reuses its grant
    instead of consuming budget again.

    A granted article gets the router's ``granted`` variant (cheap stages
    keep Groq primary but degrade to the paid key instead of failing --
    see build_client) so a dead free-tier quota cannot void the grant.
    The budget day is the IST day, matching what "today's feed" means
    everywhere else in the app."""
    from app.analysis.claude_client import CallRoutedClient

    if not isinstance(claude_client, CallRoutedClient):
        return claude_client
    if grant_paid_analysis(session, article):
        return claude_client.granted or claude_client
    return claude_client._default


# --- Impact-graph v3 adapters (spec 2026-08-11) ---------------------------

def _v3_legacy_level(distance: int | None) -> str:
    if distance is None or distance <= 1:
        return "direct"
    if distance == 2:
        return "indirect_l1"
    # Distances >= 3 reuse indirect_l2 for the legacy UI label: the frontend
    # coerces unknown values to "direct" (impactLevels.ts) -- rendering a
    # deep ripple as DIRECT is the confidently-wrong failure this cap
    # avoids. causal_distance carries the truth.
    return "indirect_l2"


def _roots_in_event(result, company) -> bool:
    """Counterfactual proxy (spec §14): the candidate's causal chain must
    trace back to this event's own graph. A parent that never appears as a
    child of anything -- including the event -- is a dangling macro story."""
    parent_of = {}
    for edge in result.edges:
        parent_of.setdefault((edge.child_type, edge.child_id),
                             (edge.parent_type, edge.parent_id))
    node = (company.parent_type, company.parent_id)
    for _ in range(12):
        if node[0] == "event":
            return True
        if node not in parent_of:
            return False
        node = parent_of[node]
    return False


def _company_profile_supports_mechanism(
    session: Session, row, company, fresh_cache_tickers: frozenset[str] = frozenset(),
) -> bool:
    """BUSINESS_MODEL_VALID's input (canonical policy table): can the system
    say anything grounded about this company's business at the mechanism's
    own dimension? A plain-language business description qualifies, and so
    does a FRESH verified exposure row for the parent node -- an exposure
    record IS a statement about the business at exactly this dimension, and
    a company can easily have one without ever getting a description.

    SELF-ECHO GUARD (final-review finding I2), the SECOND reader of
    CompanyNodeExposure in this module. `app.analysis.impact_graph.evidence.
    classify_evidence` has carried this guard since Task 18; this function
    did not, and it reads the same table for the same node in the same
    session. `_write_exposure_cache` (engine.py) refreshes an existing row
    IN PLACE -- via SQLAlchemy's identity map, an EXPIRED row this run's own
    verifier just re-stamped reads back as fresh here, so a candidate could
    clear BUSINESS_MODEL_VALID on the strength of its own acceptance rather
    than any independent prior. `fresh_cache_tickers` is exactly the set of
    tickers this run wrote a row for (ImpactGraphResult.fresh_cache_tickers,
    the same input classify_evidence receives); for those, the exposure
    branch is skipped entirely and only a real business description counts.
    Default-empty so the legacy/test callers that pass three arguments keep
    their existing behavior."""
    if row is None:
        return False
    if (row.business_desc or "").strip():
        return True
    if company.ticker in fresh_cache_tickers:
        return False
    from app.analysis.impact_graph.exposure import exposure_row_is_fresh
    from app.models import CompanyNodeExposure

    exposure = (
        session.query(CompanyNodeExposure)
        .filter_by(company_id=row.id, node_key=company.parent_id, exposure_exists=1)
        .one_or_none()
    )
    return exposure is not None and exposure_row_is_fresh(exposure, row)


def _gate_candidates(session: Session, result) -> list[tuple[str, str, list, object]]:
    """Evaluate every graph company through the publication gate (strict
    mode only). Returns [(evidence_class, evidence_tier, evidence_payloads,
    GateDecision)] positionally aligned with `result.companies` -- a list,
    not a ticker-keyed dict, so that two candidates resolving to ONE
    company both survive to finalize_alert_decisions and the duplicate is
    decided there instead of being silently swallowed by dict keying.
    `evidence_payloads` are EvidenceRecord payload dicts (Task 5) -- not
    yet persisted, since no Alert id exists at this point; see
    app.analysis.impact_graph.evidence.persist_evidence."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.analysis.impact_graph.materiality import materiality_grade as composite_materiality_grade
    from app.analysis.impact_graph.publication_gate import CandidateInput, GateContext, evaluate_candidate

    # Subject/ambiguity resolution (Task 7's alias-matcher pass) -- reused
    # from analyze_article_v3's own single resolution when the result
    # carries it (corrective-v4 Task 18 follow-up, MINOR finding: this used
    # to unconditionally re-run the SAME matcher pass from scratch here,
    # even though engine._GraphState.subjects_cache had already computed it
    # once). `result.subject_tickers is None` is the honest fallback for a
    # result serialized BEFORE that field existed (get_cached_v3 can replay
    # an ImpactGraphResult up to V3_CACHE_TTL_DAYS old) -- recompute exactly
    # as before rather than treating "field absent" as "no subjects".
    # `ambiguous_entity_names` holds entities the matcher found genuinely
    # ambiguous (Task 7); the ONLY safe cross-reference back to a specific
    # GraphCompany is exact name equality -- this module's whole design
    # rejects substring/fuzzy matching as a false-confidence hazard (see
    # matcher.py), so a GraphCompany's own `entity_ambiguous` flag (set by
    # its producer) is the primary signal and this is a defensive fallback,
    # not the main path.
    if result.subject_tickers is not None:
        subject_tickers = set(result.subject_tickers)
        ambiguous_entity_names = set(result.ambiguous_entities)
    else:
        from app.analysis.impact_graph.engine import _subject_companies_ex
        from app.analysis.impact_graph.schemas import EventFacts

        subject_facts = EventFacts(
            event="", facts="", category=result.category,
            event_type=result.event_type or "",
            named_entities=list(result.named_entities or []),
        )
        subjects, ambiguous_entity_names = _subject_companies_ex(session, subject_facts)
        subject_tickers = {row.ticker for row in subjects}
    # Self-echo guard input (owner-ruled cross-finding, see
    # app.analysis.impact_graph.evidence.classify_evidence's docstring):
    # exactly the tickers _write_exposure_cache wrote a fresh
    # CompanyNodeExposure row for THIS run (engine._GraphState.
    # fresh_cache_tickers, threaded out on the result) -- NOT every
    # verified=True ticker, which would also catch the narrow path's
    # low-risk in-call self-check (verified=True, cache never touched) and
    # every test fixture that hand-builds an already-verified candidate
    # alongside a genuinely independent prior row.
    fresh_cache_tickers = frozenset(result.fresh_cache_tickers or [])
    # Budget exhaustion means the verifier never ran (existing behavior) AND
    # the analysis itself is degraded -- both truths, separately stated. A
    # "failed" analysis is the same story from a different failure mode
    # (Task 9): whatever companies made it into `result.companies` came out
    # of a pipeline run that could not complete, so nothing about their
    # verification can be trusted either.
    budget_exhausted = result.analysis_quality == "budget_exhausted"
    analysis_failed = (result.analysis_quality or "").strip().lower() == "failed"
    verification_available = not budget_exhausted and not analysis_failed and not (
        result.metrics or {}).get("verification_unavailable")
    analysis_quality = _gate_quality(result.analysis_quality)
    context = GateContext()
    decisions = []
    for company in result.companies:
        row = session.query(Company).filter_by(ticker=company.ticker).one_or_none()
        evidence_class, evidence_tier, evidence_payloads = classify_evidence(
            session, company, subject_tickers, fresh_cache_tickers)
        # Entity tri-state (Task 7): the ticker resolving to a real Company
        # row is the normal case (GraphCompany.ticker comes from an
        # enum-locked candidate list). `entity_ambiguous` is the one signal
        # that overrides "resolved"/"unresolved" with a third, more honest
        # state -- the matcher found MULTIPLE real companies for the entity
        # that named this candidate and could not tell them apart.
        entity_ambiguous = bool(company.entity_ambiguous) or (
            company.name in ambiguous_entity_names)
        entity_status = (
            "ambiguous" if entity_ambiguous
            else "resolved" if row is not None
            else "unresolved"
        )
        # Materiality composite (Task 8): the gate must never see the naked
        # LLM float. exposure_level is the company's own CompanyExposure
        # ordinal for the mechanism's dimension when one exists; None (no
        # prior on file) applies no cap, per materiality_grade()'s contract.
        grade = composite_materiality_grade(
            company.materiality,
            _exposure_level_for_candidate(session, row, company),
            evidence_tier,
            # Reserved for Task 10 (event magnitude extraction) -- no
            # producer of a real shock-magnitude verdict exists yet, and
            # inventing one here would be the same sin materiality.py exists
            # to prevent.
            False,
        )
        decisions.append((evidence_class, evidence_tier, evidence_payloads, evaluate_candidate(CandidateInput(
            ticker=company.ticker,
            # Resolved-company identity: the dedup key finalize uses, so two
            # tickers naming one company collapse to one published row.
            company_key=str(row.id) if row is not None else "",
            entity_status=entity_status,
            company_profile_present=_company_profile_supports_mechanism(
                session, row, company, fresh_cache_tickers),
            mechanism=company.mechanism or "",
            rationale=company.rationale or "",
            economic_effect=_persist_effect(company.economic_effect) or "",
            causal_distance=company.causal_distance,
            materiality=company.materiality,
            materiality_grade=grade,
            confidence=company.confidence,
            independently_verified=bool(company.verified),
            verification_available=bool(verification_available),
            evidence_class=evidence_class,
            evidence_tier=evidence_tier,
            # Semantic counterfactual verdict (Task 9): the verifier's real
            # per-company answer, carried through corrections/omission
            # handling in app.analysis.impact_graph.engine._verify_companies.
            # "" (verifier never reached this company at all) is a distinct,
            # more severe state than "UNCERTAIN" (verifier ran, no answer for
            # this ticker) -- the gate's SAFE semantics already treat both as
            # non-primary, and "" additionally fails closed entirely.
            counterfactual=company.counterfactual or "",
            analysis_quality=analysis_quality,
            positive_channels=list(company.positive_channels or []),
            negative_channels=list(company.negative_channels or []),
            net_direction=company.net_direction or "",
            trigger_shock_present=_roots_in_event(result, company),
        ), context)))
    return decisions


def _exposure_level_for_candidate(session: Session, row, company) -> str | None:
    """CompanyExposure ordinal for the mechanism's own dimension (Task 8's
    materiality composite input). The mechanism_id rides on
    `discovery_source` ("archetype:<mechanism_id>") -- the only place a
    candidate carries it today; the dynamic mapping path and the
    subject-fallback path carry no mechanism_id at all. Either "no
    mechanism_id" or "no exposure row at that dimension" honestly means "no
    prior on file" -- None, which materiality_grade() treats as no cap
    rather than inventing a NONE-exposure claim nobody made."""
    if row is None:
        return None
    source = company.discovery_source or ""
    if not source.startswith("archetype:"):
        return None
    from app.analysis.impact_graph.knowledge import MECHANISM_DIMENSIONS
    from app.models import CompanyExposure

    mechanism_id = source[len("archetype:"):]
    dimension = MECHANISM_DIMENSIONS.get(mechanism_id)
    if dimension is None:
        return None
    exposure = (
        session.query(CompanyExposure)
        .filter_by(company_id=row.id, dimension=dimension)
        .one_or_none()
    )
    return exposure.level if exposure is not None else None


def _gate_quality(analysis_quality: str | None) -> str:
    """ImpactGraphResult quality -> the gate's canonical four-way. Budget
    exhaustion is a degraded analysis (and separately kills verification).
    An unrecognized value fails closed as `failed` rather than being
    charitably rounded up."""
    quality = (analysis_quality or "").strip().lower()
    if quality == "budget_exhausted":
        return "degraded"
    if quality in ("authoritative", "fallback", "degraded", "failed"):
        return quality
    return "failed"


def _v3_entries(session: Session, result) -> list[dict]:
    """ImpactGraphResult.companies -> the entry dicts _persist_alert
    consumes. Companies are already candidate-grounded, so resolution is a
    direct ticker lookup; a ticker that no longer resolves is skipped
    (omit rather than mismatch). In strict mode every entry additionally
    carries its publication-gate decision (spec §5)."""
    gate_decisions = (
        _gate_candidates(session, result) if settings.impact_engine_v4_strict else []
    )
    if gate_decisions:
        # Alert-level policy the per-candidate walk cannot decide alone:
        # duplicate companies and the primary cap (spec canonical policy
        # table). Demotion, never deletion (INV-015).
        from app.analysis.impact_graph.publication_gate import finalize_alert_decisions

        finalized = finalize_alert_decisions(
            [decision for _, _, _, decision in gate_decisions])
        gate_decisions = [
            (evidence_class, evidence_tier, evidence_payloads, decision)
            for (evidence_class, evidence_tier, evidence_payloads, _), decision
            in zip(gate_decisions, finalized)
        ]
    entries = []
    for company_index, company in enumerate(result.companies):
        row = session.query(Company).filter_by(ticker=company.ticker).one_or_none()
        gated = gate_decisions[company_index] if gate_decisions else None
        if row is None:
            logger.warning("v3 company %s did not resolve to a Company row; skipped", company.ticker)
            # Ledger parked item (b), corrective-v4 Task 18: the ticker
            # still walked the gate above (ENTITY_VALID rejects it with
            # entity_status="unresolved" -> REJECT_UNKNOWN_COMPANY) --
            # that decision must stay durable even though no AlertCompany
            # row can ever exist for a company_id that doesn't resolve. A
            # minimal company_id=None entry carries just enough for
            # _persist_alert's decision-record write; REJECT_UNKNOWN_
            # COMPANY always yields display_tier "excluded", so the
            # `!= "excluded"` filter below drops it before
            # _build_alert_company ever sees it.
            if gated is not None:
                evidence_class, evidence_tier, evidence_payloads, decision = gated
                entries.append({
                    "company_id": None, "ticker": company.ticker,
                    "display_tier": decision.display_tier,
                    "gate_state": decision.final_state,
                    "gates_passed": decision.gates_passed,
                    "rejection_reason": decision.rejection_reason,
                    "materiality_grade": decision.materiality_grade,
                    "evidence_class": evidence_class, "evidence_tier": evidence_tier,
                    "evidence_payloads": evidence_payloads,
                    "decision_notes": decision.notes,
                    "gate_inputs": decision.candidate_snapshot,
                    "economic_effect": _persist_effect(company.economic_effect),
                    "causal_distance": company.causal_distance,
                    "materiality": company.materiality, "confidence_f": company.confidence,
                    "mechanism": company.mechanism, "rationale": company.rationale,
                    "discovery_source": company.discovery_source,
                    "applied_correction": company.applied_correction,
                })
            continue
        parent_company_id = None
        if company.parent_type == "company":
            parent = session.query(Company).filter_by(ticker=company.parent_id).one_or_none()
            parent_company_id = parent.id if parent else None
        # Magnitude band derived monotonically from impact_strength -- the
        # value that is actually persisted, full stop. It used to be a
        # placeholder the calibration blender (app.calibration.blender.
        # get_calibrated_magnitude) overrode with measured realized-outcome
        # stats once enough samples existed; that override is removed (see
        # docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/
        # task-3-brief.md) so this formula is the whole story now, not a
        # fallback.
        magnitude_high = round(0.5 + 4.5 * company.impact_strength, 1)
        magnitude_low = round(max(0.1, magnitude_high / 3), 1)
        # Legacy coercion: pre-strict consumers assume direction is binary,
        # so neutral historically flattened to bullish at this boundary.
        # Strict mode persists the truthful value (spec §19: mixed/uncertain
        # must survive every stage; they render as direction "neutral").
        if settings.impact_engine_v4_strict:
            persisted_direction = company.direction
        else:
            persisted_direction = company.direction if company.direction != "neutral" else "bullish"
        entries.append({
            "company_id": row.id, "direction": persisted_direction,
            "magnitude_low": magnitude_low, "magnitude_high": magnitude_high,
            "rationale": company.rationale, "key_points": company.key_points,
            "confidence_score": round(company.confidence * 100), "time_horizon": company.time_horizon,
            "basis": "direct_mention", "reasons": company.reasons,
            "evidence_refs": company.evidence_refs, "risks": [],
            "assumptions": company.assumptions, "unknowns": company.unknowns,
            "alternative_hypothesis": None,
            "impact_level": _v3_legacy_level(company.causal_distance),
            "parent_company_id": parent_company_id,
            "causal_distance": company.causal_distance,
            "impact_strength": company.impact_strength,
            "confidence_f": company.confidence, "materiality": company.materiality,
            "causal_parent_type": company.parent_type, "causal_parent_id": company.parent_id,
            "mechanism": company.mechanism,
            "economic_effect": _persist_effect(company.economic_effect),
            "channels_json": json.dumps({
                "positive_channels": company.positive_channels,
                "negative_channels": company.negative_channels,
                "offsetting_channels": company.offsetting_channels,
                "net_direction": company.net_direction or company.direction,
                "relative_beneficiary": company.relative_beneficiary,
                # Multi-channel merge (corrective-v4 task 11): the other
                # mechanism(s) a competing candidate contributed, preserved
                # instead of silently discarded by the old best-wins merge.
                "secondary_mechanisms": company.secondary_mechanisms,
            }) if (company.positive_channels or company.negative_channels
                   or company.net_direction or company.secondary_mechanisms) else None,
            # Expected market sensitivity (task 10): straight from
            # GraphCompany.expected_market_sensitivity -- set by the
            # mapping-stage model's own judgment, never derived from any
            # measured price move (app.market.measure runs later and
            # separately).
            "expected_market_sensitivity": company.expected_market_sensitivity,
            # Decision-record completeness (spec sec54, corrective-v4 Task
            # 18): carried on every entry (not only gated ones) so
            # _persist_alert's gated branch can read them without a second
            # pass over result.companies.
            "discovery_source": company.discovery_source,
            "applied_correction": company.applied_correction,
        })
        # Positional, not ticker-keyed: two candidates can name one company
        # and each keeps its own decision (one of them REJECT_DUPLICATE).
        if gated is not None:
            evidence_class, evidence_tier, evidence_payloads, decision = gated
            entries[-1].update({
                "display_tier": decision.display_tier,
                "gate_state": decision.final_state,
                "gates_passed": decision.gates_passed,
                "rejection_reason": decision.rejection_reason,
                "materiality_grade": decision.materiality_grade,
                "evidence_class": evidence_class,
                "evidence_tier": evidence_tier,
                # Not-yet-persisted EvidenceRecord payload dicts (Task 5):
                # no Alert id exists yet at this point in the pipeline.
                # _persist_alert turns these into real rows via
                # app.analysis.impact_graph.evidence.persist_evidence and
                # sets "evidence_ids" (the resulting row ids) alongside.
                "evidence_payloads": evidence_payloads,
                "decision_notes": decision.notes,
                # Full CandidateInput the gate walked (Task 18) -- the
                # decision record's gate_inputs_json.
                "gate_inputs": decision.candidate_snapshot,
            })
    return entries


def _v3_edges(result) -> list[dict]:
    """GraphEdge list -> the edge dicts _persist_alert persists. Legacy
    columns get the closest legacy vocabulary (charts keep working); the
    typed v3 fields carry the graph truth. Company attachment edges (node ->
    selected company) are appended deterministically so relation-keyed
    consumers (ripple_layers' notes, the deck's graphs) see every company
    connected."""
    def _kind(node_type: str) -> str:
        if node_type in ("company", "sector"):
            return node_type
        return "mechanism"

    def _edge_direction(direction: str) -> str:
        # Same boundary rule as _v3_entries: strict mode persists the
        # truthful value; legacy consumers get the historical coercion.
        if settings.impact_engine_v4_strict:
            return direction
        return direction if direction != "neutral" else "bullish"

    edges = []
    for edge in result.edges:
        edges.append({
            "from": {"kind": _kind(edge.parent_type), "label": edge.parent_id},
            "to": {"kind": _kind(edge.child_type), "label": edge.child_id},
            "relation": "demand" if edge.child_type == "company" else "correlation",
            "direction": _edge_direction(edge.direction),
            "note": edge.mechanism, "source": "llm_only",
            "parent_type": edge.parent_type, "child_type": edge.child_type,
            "causal_distance": edge.causal_distance,
            "impact_strength": edge.impact_strength, "confidence_f": edge.confidence,
            "materiality": edge.materiality, "time_horizon": edge.time_horizon,
            "verification_status": edge.verification_status,
            "economic_effect": _persist_effect(edge.economic_effect),
        })
    for company in result.companies:
        edges.append({
            "from": {"kind": _kind(company.parent_type), "label": company.parent_id},
            "to": {"kind": "company", "label": company.ticker},
            "relation": "demand",
            "direction": _edge_direction(company.direction),
            "note": company.mechanism or company.rationale, "source": "llm_only",
            "parent_type": company.parent_type, "child_type": "company",
            "causal_distance": company.causal_distance,
            "impact_strength": company.impact_strength, "confidence_f": company.confidence,
            "materiality": company.materiality, "time_horizon": company.time_horizon,
            "verification_status": "verified" if company.verified else "unverified",
            "economic_effect": _persist_effect(company.economic_effect),
        })
    return edges


def _build_v3_router(session: Session, article: Article, groq_client):
    """One StageRouter per article. Claude is the authoritative provider for
    EVERY article (provider-migration 2026-08-14) -- the old paid-Gemini
    grant gate no longer selects providers; the per-article ArticleBudget is
    the cost bound. Groq is reachable only under the explicit
    LLM_FALLBACK_ALLOWED opt-in."""
    from app.analysis.impact_graph.budget import ArticleBudget
    from app.analysis.impact_graph.router import StageRouter

    return StageRouter(
        claude_api_key=settings.claude_api_key or None,
        # Unreachable by construction unless the opt-in is set: the router
        # cannot fall back to a client it was never handed.
        groq_client=groq_client if settings.llm_fallback_allowed else None,
        article_id=article.id,
        budget=ArticleBudget(article_id=article.id),
        # Durable stage cache: retries replay completed stages for free.
        session=session,
    )


def _build_v3_groq_client():
    from app.analysis.claude_client import GROQ_BASE_URL, GroqAdapter, RotatingClient

    keys = settings.groq_api_keys
    if not keys:
        return None
    return GroqAdapter(RotatingClient(keys, base_url=GROQ_BASE_URL))


def process_new_articles(session: Session, claude_client, throttle_seconds: float = 0) -> int:
    """Run the filter -> analyze -> resolve -> alert pipeline over every
    CATEGORIZED article.

    ``throttle_seconds`` sleeps between each article's analysis call (and
    before each retry) to stay under a rate-limited provider's requests-per-
    minute cap -- a real free-tier limit, not a hypothetical one: an
    unthrottled run over a backlog of ~50 articles previously blew through
    Groq's free-tier rate limit and failed nearly every one of them. Defaults
    to 0 (no delay) so the test suite, which always uses a mocked/instant
    client, is not slowed down; the scheduler passes a real value.
    """
    fetch_pending_full_text(session)
    backfill_pulse_images(session)
    filter_new_articles(session, claude_client, throttle_seconds)

    alerts_created = 0
    # Newest first, same reasoning as filter_new_articles's ordering: a
    # backlog must never make current news queue behind stale news.
    pending = (
        session.query(Article)
        .filter_by(status="CATEGORIZED")
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
        .all()
    )
    # ...but paid-eligible (pulse) articles jump the whole queue. During a
    # provider quota storm the newest-first order makes dozens of newer,
    # doomed-to-fail articles each burn retry time ahead of the five
    # granted articles (measured 2026-08-11: one pulse alert in six hours
    # while 83 re-queued articles starved the rest). Stable sort: order
    # within each group stays newest-first.
    pending.sort(key=lambda a: a.provider not in settings.gemini_paid_provider_set)

    # Built lazily on first uncached article -- the test suite's mocked
    # runs never construct a real Groq client.
    v3_groq_client = None

    for article in pending:
        reusable_alert = _find_reusable_alert(session, article)
        if reusable_alert is not None:
            # Same story, already analyzed under a different article row (a
            # republished RSS item) -- reuse its direction/rationale/basis
            # verbatim (that reasoning is about the same underlying news, so
            # it is exactly what a fresh call would have produced) without
            # spending another LLM call. Calibration is still looked up
            # fresh inside _persist_alert.
            entries = [{
                "company_id": ac.company_id, "direction": ac.direction,
                "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
                "rationale": ac.rationale, "key_points": decode_key_points(ac), "basis": ac.basis,
                "time_horizon": ac.time_horizon,
                "reasons": _decode_json_list(ac.reasons_json),
                "evidence_refs": _decode_json_list(ac.evidence_refs_json),
                "risks": _decode_json_list(ac.risks_json),
                "assumptions": _decode_json_list(ac.assumptions_json),
                "unknowns": _decode_json_list(ac.unknowns_json),
                "alternative_hypothesis": ac.alternative_hypothesis,
                "impact_level": ac.impact_level,
                "parent_company_id": ac.parent_company_id,
                "expected_market_sensitivity": ac.expected_market_sensitivity,
                # V4/gate fields (corrective-v4 Task 12): _find_reusable_alert
                # only hands back an alert whose companies are ALL
                # gate-authoritative (see _dedup_reuse_policy_allows), so
                # copy that decision verbatim -- letting a reused row
                # silently regress to "ungated" (gate_state/display_tier
                # NULL) would make it structurally indistinguishable from a
                # legacy alert and re-open the gate bypass this closes.
                "display_tier": ac.display_tier, "gate_state": ac.gate_state,
                "economic_effect": ac.economic_effect,
                "causal_distance": ac.causal_distance, "impact_strength": ac.impact_strength,
                "confidence_f": ac.confidence_f, "materiality": ac.materiality,
                "causal_parent_type": ac.causal_parent_type, "causal_parent_id": ac.causal_parent_id,
                "mechanism": ac.mechanism, "channels_json": ac.channels_json,
            } for ac in reusable_alert.companies]
            # The reused alert's own distilled facts carry over too: this
            # is the SAME underlying story, so its facts are exactly what a
            # fresh _extract_facts call would have produced -- and without
            # them this alert's refinement would silently fall back to
            # re-reading the raw article, the very cost this removes.
            # analysis_provider/analysis_quality also carry over (I3c,
            # review round 2): reuse is transitive -- a THIRD republish of
            # the same story reuses off THIS alert next, so its own
            # provenance/quality marks must be honest, not silently NULL'd
            # out, or _dedup_reuse_policy_allows' analysis_quality ==
            # "authoritative" check would wrongly refuse the next reuse.
            _persist_alert(
                session, article, reusable_alert.category, entries,
                event_type=reusable_alert.event_type, client=claude_client,
                facts=reusable_alert.facts,
                event_cause=reusable_alert.event_cause,
                analysis_provider=reusable_alert.analysis_provider,
                analysis_quality=reusable_alert.analysis_quality,
                reused_from_alert_id=reusable_alert.id,
            )
            alerts_created += 1
            continue

        # --- Impact-graph v3: the ONE authoritative analysis path (spec
        # 2026-08-11). The legacy cascade (analysis.cascade.analyze_article)
        # is no longer wired here.
        result = get_cached_v3(session, article)
        if result is None:
            if v3_groq_client is None:
                v3_groq_client = _build_v3_groq_client()
            router = _build_v3_router(session, article, v3_groq_client)
            for attempt in range(2):  # try once, retry once (router retries internally per stage too)
                try:
                    result = analyze_article_v3(
                        router, article.title, article_text(article),
                        session=session, article_id=article.id,
                    )
                    break
                except Exception:
                    # Logged, not swallowed silently -- a burst of
                    # ANALYSIS_FAILED articles with no trace made a
                    # provider rate-limit storm undiagnosable in
                    # production.
                    logger.exception(
                        "analyze_article_v3 attempt %s failed for article_id=%s", attempt + 1, article.id,
                    )
                    if attempt == 0:
                        time.sleep(throttle_seconds)
                    continue
            time.sleep(throttle_seconds)  # stay under the provider's rate limit before the next article

            if result is None:
                article.status = "ANALYSIS_FAILED"
                session.commit()
                continue

            store_v3_cache(session, article, result)

        # Never-fail contract (2026-08-11): a persist-layer crash must cost
        # exactly ONE article one retry cycle -- never the whole tick. The
        # retry replays every completed LLM stage free (llm_stage_cache),
        # so re-persisting after a transient DB/measurement error is cheap.
        try:
            entries = _v3_entries(session, result)
            _persist_alert(
                session, article, result.category, entries,
                event_type=result.event_type, gaps=result.gaps, edges=_v3_edges(result),
                client=claude_client, facts=result.facts,
                analysis_provider=result.analysis_provider, analysis_quality=result.analysis_quality,
                event_cause=result.event_cause,
                ambiguous_entities=result.ambiguous_entities,
            )
        except Exception:
            logger.exception("persist failed for article_id=%s; marked for retry", article.id)
            session.rollback()
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue
        alerts_created += 1

    return alerts_created
