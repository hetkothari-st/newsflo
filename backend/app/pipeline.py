import json
import time
from datetime import timedelta

from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.calibration.blender import get_calibrated_magnitude
from app.companies.history import get_past_mentions
from app.companies.market import infer_market
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.ingestion.og_image import fetch_og_image
from app.models import Alert, AlertCompany, Article, utcnow
from app.ws.manager import manager

# How far back to look for a reusable analysis of a duplicate/republished
# story. Bounded so a months-old identical title (a rare coincidence, not a
# genuine republish) never gets silently reused with stale reasoning.
DEDUP_LOOKBACK_HOURS = 24


def decode_key_points(alert_company: AlertCompany) -> list[str]:
    if not alert_company.key_points_json:
        return []
    return json.loads(alert_company.key_points_json)


def _alert_broadcast_payload(session: Session, alert: Alert) -> dict:
    """Shape one live-push payload identical to a single GET /api/alerts entry,
    MINUS the per-viewer ``in_my_holdings`` flag.

    Known simplification: the pipeline has no viewer context at broadcast time,
    so live-pushed companies carry no holdings-match. The frontend defaults
    live-pushed companies to ``in_my_holdings: false`` and the next full
    ``GET /api/alerts`` refresh reconciles them — correct-eventually, and
    simpler than threading per-user state through the broadcast.
    """
    return {
        "id": alert.id,
        "category": alert.category,
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
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low,
            "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale,
            "key_points": decode_key_points(ac),
            "basis": ac.basis,
            "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
            "past_mentions": get_past_mentions(session, ac.company_id, alert.created_at),
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


def _persist_alert(session: Session, article: Article, category: str, entries: list[dict]) -> Alert:
    """Create the Alert + AlertCompany rows for one article and fan out
    notifications/broadcast. Shared by both the fresh-analysis path and the
    dedup-reuse path -- calibration is always looked up fresh here (not
    copied from a reused analysis) so a reused alert reflects the current
    calibration state exactly like a brand new analysis would.
    """
    alert = Alert(article_id=article.id, category=category)
    session.add(alert)
    session.flush()

    for entry in entries:
        calibrated = get_calibrated_magnitude(session, category=category, company_id=entry["company_id"])
        if calibrated is not None:
            magnitude_low, magnitude_high = calibrated
            confidence = "calibrated"
        else:
            magnitude_low, magnitude_high = entry["magnitude_low"], entry["magnitude_high"]
            confidence = "llm_estimate"
        session.add(AlertCompany(
            alert_id=alert.id,
            company_id=entry["company_id"],
            direction=entry["direction"],
            magnitude_low=magnitude_low,
            magnitude_high=magnitude_high,
            rationale=entry["rationale"],
            key_points_json=json.dumps(entry.get("key_points") or []),
            basis=entry["basis"],
            confidence=confidence,
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
            } for ac in reusable_alert.companies]
            _persist_alert(session, article, reusable_alert.category, entries)
            alerts_created += 1
            continue

        analysis = None
        for attempt in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article.content)
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
        _persist_alert(session, article, analysis.category, resolved)
        alerts_created += 1

    return alerts_created
