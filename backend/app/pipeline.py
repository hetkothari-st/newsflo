import hashlib
import json
import logging
import time
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.impact_graph.engine import analyze_article_v3
from app.analysis.refinement import REFINEMENT_PENDING, refine_alert
from app.analysis.schemas import AnalysisOutput, CATEGORIES
from app.calibration.blender import get_calibrated_magnitude, get_calibration_health
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
# Deliberately modest, and NOT the relevance defence. Measured on production
# data, a floor of 40 removes 20 rows of 881 -- and only 16 of 557
# sector_inference rows (2%), the exact category that produced the reported
# bug. Median confidence_score is 50 at every impact level because
# calibration (weight 0.30) and rulebook match (0.20) contribute 0.0 for
# nearly every row, so half the weight is inert and scores cluster. Raising
# the floor to 50 would cut correct direct_mention rows at the median while
# still keeping half the fan-out.
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
# compounding them was never intended: with calibration contributing 0.0 for
# nearly every row, a typical pre-multiplier score of ~69 survives the floor
# fine on its own, but 69 * 0.45 (indirect_l2's multiplier) = 31, BELOW this
# floor -- so comparing the floor to the post-multiplier value meant no
# indirect_l2 row could ever be persisted, for any article, silently killing
# the entire L2 cascade stage.
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


def get_cached_v3(session: Session, article: Article):
    """Impact-graph v3 twin of get_cached_analysis. Prefixed hash keyspace
    so a v2 AnalysisOutput blob can never be mis-parsed as a v3 result."""
    from app.analysis.impact_graph.schemas import ImpactGraphResult

    cached = session.query(AnalysisCache).filter_by(content_hash="v3:" + _content_hash(article)).one_or_none()
    if cached is None:
        return None
    return ImpactGraphResult.model_validate_json(cached.output_json)


def store_v3_cache(session: Session, article: Article, result) -> None:
    session.add(AnalysisCache(content_hash="v3:" + _content_hash(article), output_json=result.model_dump_json()))


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


def _find_reusable_alert(session: Session, article: Article) -> Alert | None:
    """Find an already-analyzed article with the EXACT same normalized
    title, fetched recently -- RSS sources frequently republish the
    identical wire story (confirmed in production: "Global Market: ..."
    titles recur verbatim across sources). Reusing that analysis instead of
    calling the LLM again produces the same result a fresh call would (it
    is the same story), while skipping the call entirely.

    Exact-match only, no fuzzy similarity -- this must never risk merging
    two genuinely different stories into one analysis.
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
            return session.query(Alert).filter_by(article_id=candidate.id).first()
    return None


def _build_alert_company(
    session: Session, alert_id: int, article: Article, category: str, entry: dict,
) -> tuple[AlertCompany, int]:
    """Build one AlertCompany row (unattached -- caller must session.add it)
    from a resolved entry dict, computing calibration/confidence fresh. Split
    out of _persist_alert so a one-off re-analysis script can attach fresh
    rows to an EXISTING alert without duplicating this calibration logic --
    see backend/reanalyze_cascade.py.

    Returns (alert_company, pre_multiplier_score): the AlertCompany's own
    confidence_score is the LEVEL_CONFIDENCE_MULTIPLIER-discounted value
    (what's displayed/persisted); pre_multiplier_score is
    compute_confidence()'s raw score before that discount, which
    CONFIDENCE_FLOOR must be compared against (see CONFIDENCE_FLOOR's own
    comment) -- returned here rather than recomputed by the caller so this
    stays the single place that calls compute_confidence.
    """
    calibrated = get_calibrated_magnitude(session, category=category, company_id=entry["company_id"])
    if calibrated is not None:
        magnitude_low, magnitude_high = calibrated
        confidence = "calibrated"
    else:
        magnitude_low, magnitude_high = entry["magnitude_low"], entry["magnitude_high"]
        confidence = "llm_estimate"

    reasons = entry.get("reasons") or []
    evidence_refs = entry.get("evidence_refs") or []
    matched_rule_ids = [ref for ref in evidence_refs if get_rule(ref) is not None]
    health = get_calibration_health(session, category=category, company_id=entry["company_id"])

    company_obj = session.get(Company, entry["company_id"])
    snapshot = get_or_fetch_financial_snapshot(session, company_obj.ticker) if company_obj else None
    contradiction_note = detect_price_contradiction(
        entry["direction"], snapshot["return_1m"] if snapshot else None,
    )

    article_age_hours = (
        utcnow() - _as_aware_utc(article.published_at or article.fetched_at)
    ).total_seconds() / 3600

    result = compute_confidence(
        calibration_sample_count=health["sample_count"],
        calibration_hit_rate=health["hit_rate"],
        claim_count=len(reasons),
        evidence_ref_count=len(evidence_refs),
        rule_matched=bool(matched_rule_ids),
        source_credibility=source_credibility(article.source),
        reasoning_consistent=contradiction_note is None,
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

    market_moves = []
    for alert_company in alert_companies:
        company_obj = session.get(Company, alert_company.company_id)
        if company_obj is not None:
            move = measure_company_move(session, company_obj)
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
    moves_by_company_id = {m.company_id: m for m in market_moves}
    for alert_company in alert_companies:
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
    """Re-measure recent MarketMove rows stuck at measurement_status=
    'no_data'. Measurement is one-shot at persist time, so a transient
    price-fetch failure (yfinance burst rate-limit) used to orphan the
    alert forever: the feed only shows measured alerts, and nothing ever
    retried the measurement (production 2026-08-11: every alert on the
    ingestion-v2 service invisible for exactly this reason). Updates rows
    in place -- the (alert_id, company_id) unique constraint means a new
    row was never an option -- and reconciles AlertCompany.direction with
    the fresh measured move under the same rule as first-time measurement.
    Returns how many rows became 'ok'."""
    cutoff = utcnow() - timedelta(days=_REMEASURE_WINDOW_DAYS)
    pending = (
        session.query(MarketMove)
        .join(Alert, MarketMove.alert_id == Alert.id)
        .filter(MarketMove.measurement_status == "no_data", Alert.created_at >= cutoff)
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    fixed = 0
    for move in pending:
        company = session.get(Company, move.company_id)
        if company is None:
            continue
        fresh = measure_company_move(session, company)
        if fresh.measurement_status != "ok":
            continue  # still no data -- leave the honest no_data row alone
        for column in (
            "raw_move_pct", "sector_move_pct", "benchmark_ticker", "excess_move_pct",
            "volume", "avg_volume_20d", "volume_multiple", "vol_normalized",
            "materiality", "avg_traded_value", "measured_at", "measurement_status",
        ):
            setattr(move, column, getattr(fresh, column))
        # move.category keeps its persist-time stamp (recategorization safety).
        # Same reconcile rule as measure_and_reconcile_alert_companies: the
        # measured reality overrides the LLM's pre-measurement guess, and
        # prose arguing for the contradicted direction is dropped.
        alert_company = (
            session.query(AlertCompany)
            .filter_by(alert_id=move.alert_id, company_id=move.company_id)
            .one_or_none()
        )
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


def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
    gaps: list[dict] | None = None, edges: list[dict] | None = None, client=None, facts: str | None = None,
    analysis_provider: str | None = None, analysis_quality: str | None = None,
) -> Alert:
    """Create the Alert + AlertCompany rows for one article and fan out
    notifications/broadcast. Shared by both the fresh-analysis path and the
    dedup-reuse path -- calibration AND confidence are always looked up/
    computed fresh here (not copied from a reused analysis) so a reused
    alert reflects the current calibration state exactly like a brand new
    analysis would.
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

    alert_companies = []
    kept_entries = []
    for entry in entries:
        alert_company, pre_multiplier_score = _build_alert_company(session, alert.id, article, category, entry)
        # Floor check is against the PRE-multiplier score, not the
        # LEVEL_CONFIDENCE_MULTIPLIER-discounted alert_company.confidence_score
        # -- see CONFIDENCE_FLOOR's own comment. Compounding the two meant no
        # indirect_l2 row (0.45x) could ever clear the floor.
        if pre_multiplier_score < CONFIDENCE_FLOOR:
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


def _v3_entries(session: Session, result) -> list[dict]:
    """ImpactGraphResult.companies -> the entry dicts _persist_alert
    consumes. Companies are already candidate-grounded, so resolution is a
    direct ticker lookup; a ticker that no longer resolves is skipped
    (omit rather than mismatch)."""
    entries = []
    for company in result.companies:
        row = session.query(Company).filter_by(ticker=company.ticker).one_or_none()
        if row is None:
            logger.warning("v3 company %s did not resolve to a Company row; skipped", company.ticker)
            continue
        parent_company_id = None
        if company.parent_type == "company":
            parent = session.query(Company).filter_by(ticker=company.parent_id).one_or_none()
            parent_company_id = parent.id if parent else None
        # Magnitude band derived monotonically from impact_strength -- a
        # placeholder the calibration blender overrides with measured
        # event-volatility data wherever that exists (same override path
        # the old cascade's LLM magnitudes went through).
        magnitude_high = round(0.5 + 4.5 * company.impact_strength, 1)
        magnitude_low = round(max(0.1, magnitude_high / 3), 1)
        entries.append({
            "company_id": row.id, "direction": company.direction if company.direction != "neutral" else "bullish",
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

    edges = []
    for edge in result.edges:
        edges.append({
            "from": {"kind": _kind(edge.parent_type), "label": edge.parent_id},
            "to": {"kind": _kind(edge.child_type), "label": edge.child_id},
            "relation": "demand" if edge.child_type == "company" else "correlation",
            "direction": edge.direction if edge.direction != "neutral" else "bullish",
            "note": edge.mechanism, "source": "llm_only",
            "parent_type": edge.parent_type, "child_type": edge.child_type,
            "causal_distance": edge.causal_distance,
            "impact_strength": edge.impact_strength, "confidence_f": edge.confidence,
            "materiality": edge.materiality, "time_horizon": edge.time_horizon,
            "verification_status": edge.verification_status,
        })
    for company in result.companies:
        edges.append({
            "from": {"kind": _kind(company.parent_type), "label": company.parent_id},
            "to": {"kind": "company", "label": company.ticker},
            "relation": "demand",
            "direction": company.direction if company.direction != "neutral" else "bullish",
            "note": company.mechanism or company.rationale, "source": "llm_only",
            "parent_type": company.parent_type, "child_type": "company",
            "causal_distance": company.causal_distance,
            "impact_strength": company.impact_strength, "confidence_f": company.confidence,
            "materiality": company.materiality, "time_horizon": company.time_horizon,
            "verification_status": "verified" if company.verified else "unverified",
        })
    return edges


def _build_v3_router(session: Session, article: Article, groq_client):
    """One StageRouter per article: protected (paid-Gemini-owned) when the
    article holds a paid grant, Groq-served otherwise -- same stage
    contracts either way (spec doc 2 §2)."""
    from app.analysis.impact_graph.budget import ArticleBudget
    from app.analysis.impact_graph.router import StageRouter

    protected = grant_paid_analysis(session, article) and bool(settings.gemini_paid_api_key)
    return StageRouter(
        protected=protected, gemini_api_key=settings.gemini_paid_api_key or None,
        groq_client=groq_client, article_id=article.id,
        budget=ArticleBudget(article_id=article.id),
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
            } for ac in reusable_alert.companies]
            # The reused alert's own distilled facts carry over too: this
            # is the SAME underlying story, so its facts are exactly what a
            # fresh _extract_facts call would have produced -- and without
            # them this alert's refinement would silently fall back to
            # re-reading the raw article, the very cost this removes.
            _persist_alert(
                session, article, reusable_alert.category, entries,
                event_type=reusable_alert.event_type, client=claude_client,
                facts=reusable_alert.facts,
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

        entries = _v3_entries(session, result)
        _persist_alert(
            session, article, result.category, entries,
            event_type=result.event_type, gaps=result.gaps, edges=_v3_edges(result),
            client=claude_client, facts=result.facts,
            analysis_provider=result.analysis_provider, analysis_quality=result.analysis_quality,
        )
        alerts_created += 1

    return alerts_created
