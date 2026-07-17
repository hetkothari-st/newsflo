import json
import time
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.analysis.schemas import CATEGORIES
from app.calibration.blender import get_calibrated_magnitude, get_calibration_health
from app.companies.history import bulk_past_mentions, mentions_before
from app.companies.market import infer_market
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.ingestion.full_text import fetch_pending_full_text
from app.ingestion.og_image import fetch_og_image
from app.models import Alert, AlertCompany, Article, Company, utcnow
from app.reasoning.confidence import _band as band_for_score
from app.reasoning.confidence import compute_confidence, source_credibility
from app.reasoning.financial_context import detect_price_contradiction, get_or_fetch_financial_snapshot
from app.reasoning.rulebook import get_rule
from app.reasoning.versions import KNOWLEDGE_VERSION, PROMPT_VERSION
from app.ws.manager import manager

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


def _decode_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    return json.loads(value)


def decode_key_points(alert_company: AlertCompany) -> list[str]:
    return _decode_json_list(alert_company.key_points_json)


def article_text(article: Article) -> str:
    return article.full_content or article.content


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


def _persist_alert(
    session: Session, article: Article, category: str, entries: list[dict], event_type: str | None = None,
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
    )
    session.add(alert)
    session.flush()

    article_age_hours = (
        utcnow() - _as_aware_utc(article.published_at or article.fetched_at)
    ).total_seconds() / 3600

    for entry in entries:
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
        level_multiplier = LEVEL_CONFIDENCE_MULTIPLIER.get(impact_level, 1.0)
        confidence_score = round(result.score * level_multiplier)
        confidence_band = result.band if level_multiplier == 1.0 else band_for_score(confidence_score)

        session.add(AlertCompany(
            alert_id=alert.id,
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
        ))

    if article.image_url is None:
        article.image_url = fetch_og_image(article.url)

    article.status = "ANALYZED"
    article.category = category
    session.commit()

    new_notifications = match_alert_to_holdings(session, alert)
    send_pending_notifications(session, new_notifications)
    manager.broadcast_sync(_alert_broadcast_payload(session, alert))
    return alert


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
    filter_new_articles(session)

    alerts_created = 0
    pending = session.query(Article).filter_by(status="CATEGORIZED").all()

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
            _persist_alert(session, article, reusable_alert.category, entries, event_type=reusable_alert.event_type)
            alerts_created += 1
            continue

        analysis = None
        for attempt in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article_text(article))
                break
            except Exception:
                if attempt == 0:
                    time.sleep(throttle_seconds)
                continue
        time.sleep(throttle_seconds)  # stay under the provider's rate limit before the next article

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)
        _persist_alert(session, article, analysis.category, resolved, event_type=analysis.event_type)
        alerts_created += 1

    return alerts_created
