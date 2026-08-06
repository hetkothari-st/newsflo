"""Level 0/1 feed endpoints for the measurement-first UI rebuild
(docs/NEWS_IMPACT_APP_SPEC.md §2, §9) -- a new, parallel set of routes
alongside the existing GET /api/alerts (kept untouched; see this plan's
Global Constraints). Returns only alerts with at least one measured
company (excess_move_pct computed, measurement_status == "ok") -- an
alert with nothing measured has no headline number and is omitted
entirely (Ground Rules: never fabricate, omit rather than invent).
"""
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user, get_current_user_optional
from app.config import settings
from app.companies.branding import logo_url
from app.filtering.language_gate import is_english_text
from app.i18n import get_lang
from app.ingestion.image_filter import displayable_image_url, repeated_image_urls
from app.translation.lookup import (
    bulk_alert_company_whys,
    bulk_alert_summaries,
    bulk_article_titles,
    bulk_category_labels,
)
from app.ist_time import day_utc_window, today_ist
from app.market.alert_measurement import compute_alert_measurement
from app.market.discovery import (
    compute_materiality_feed,
    compute_related_to_holdings,
    compute_unusual_activity,
)
from app.market.cap_tier import cap_tier_map
from app.market.ripple_layers import compute_ripple_layers
from app.market.timeline_entries import get_timeline_entries
from app.models import Alert, AlertCompany, Article, Company, Holding, User
from app.routers.articles import get_db

# -- COMMENTED OUT (superseded by compute_ripple_layers, spec v2 §5/§7's
# layered card back -- the flat ripple list + separate impact_companies
# split is the old, pre-swipe-card UI's shape):
# from app.market.alert_measurement import compute_impact_companies
# from app.market.ripple import compute_ripple_companies

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])

ALERTS_LIMIT = 200


def _held_company_ids(db: Session, current_user: User | None) -> set[int]:
    if current_user is None:
        return set()
    return {h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()}


def _serialize(
    alert: Alert,
    measurement: dict,
    held_company_ids: set[int],
    repeated_images: set[str],
    translations: dict | None = None,
) -> dict:
    """``translations`` (optional): {"titles": {article_id: str},
    "summaries": {alert_id: (short, long)}, "categories": {category: str}}
    -- the bulk-lookup results for the request's lang; every field falls
    back silently to English (same discipline as routers/alerts.py)."""
    translations = translations or {}
    translated_title = translations.get("titles", {}).get(alert.article_id)
    summary_short, summary_long = translations.get("summaries", {}).get(
        alert.id, (None, None),
    )
    in_my_holdings = any(ac.company_id in held_company_ids for ac in alert.companies)
    return {
        "id": alert.id,
        "category": alert.category,
        # Translated display label for the category chip; English slug
        # (prettified frontend-side) when no translation exists.
        "category_label": translations.get("categories", {}).get(alert.category),
        "created_at": alert.created_at.isoformat(),
        "summary_short": summary_short or alert.summary_short,
        "summary_long": summary_long or alert.summary_long,
        "article": {
            "id": alert.article.id,
            # Generic publisher artwork (wire-service logos, newspaper
            # default banners) is nulled out -- the card shows no image
            # rather than a wrong one. See app.ingestion.image_filter.
            "image_url": displayable_image_url(alert.article.image_url, repeated_images),
            "title": translated_title or alert.article.title,
            "url": alert.article.url,
            "source": alert.article.source,
            "published_at": alert.article.published_at.isoformat() if alert.article.published_at else None,
        },
        "in_my_holdings": in_my_holdings,
        **measurement,
    }


def _query_with_relations(db: Session):
    return db.query(Alert).options(
        selectinload(Alert.article),
        selectinload(Alert.companies).selectinload(AlertCompany.company),
    )


def _bulk_translations(db: Session, alerts: list[Alert], lang: str) -> dict:
    """Three bulk lookups total regardless of alert count (same pattern as
    routers/alerts.py) -- all empty (silent English) when lang == 'en'."""
    return {
        "titles": bulk_article_titles(db, [a.article_id for a in alerts], lang),
        "summaries": bulk_alert_summaries(db, [a.id for a in alerts], lang),
        "categories": bulk_category_labels(db, list({a.category for a in alerts}), lang),
    }


@router.get("")
def list_feed_v2_alerts(
    date: str | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    """The card feed. ``date`` (YYYY-MM-DD, IST day) reopens a previous
    day's news -- the calendar mechanism (spec v2 keeps it: any day is a
    complete feed). Defaults to today."""
    if date is not None:
        try:
            day = date_cls.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    else:
        day = today_ist()
    start_utc, end_utc = day_utc_window(day)
    query = (
        _query_with_relations(db)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
    )
    # Demo-seeded stories (seed_feed_v2_demo.py's URL marker) never reach
    # the production feed. ALLOW_DEMO_FEED=true opts a non-production
    # service (e.g. a UI-preview deployment sharing this database) back
    # in for testing.
    if not settings.allow_demo_feed:
        query = query.join(Alert.article).filter(~Article.url.like("https://demo.feed-v2.local/%"))
    alerts = query.order_by(Alert.created_at.desc()).limit(ALERTS_LIMIT).all()
    held_company_ids = _held_company_ids(db, current_user)
    translations = _bulk_translations(db, alerts, lang)

    # Peak company's cap tier -- drives the top-bar cap filter on the card
    # feed (spec v2 §6: "Provide a cap-tier filter (All / Large / Mid /
    # Small / Micro)") without computing full layers per alert. One ranking
    # pass for the whole list, derived fresh (spec §3.2).
    cap_tiers = cap_tier_map(db)

    repeated_images = repeated_image_urls(db, [a.article.image_url for a in alerts if a.article.image_url])

    results = []
    for alert in alerts:
        # English-only feed (the base language is uniform; other languages
        # come from the user's translation picker) -- drops the foreign-
        # language wire mirrors ingested before the language gate shipped.
        if not is_english_text(alert.article.title):
            continue
        measurement = compute_alert_measurement(db, alert)
        if measurement is not None:
            row = _serialize(alert, measurement, held_company_ids, repeated_images, translations)
            row["peak_cap_tier"] = cap_tiers.get(measurement["peak_ticker"])
            # Distinct tiers across ALL tagged companies -- the top-bar cap
            # filter shows a story when any affected company sits in the
            # chosen tier, not only the peak mover. Companies without an
            # honest tier (stale/absent cap) contribute nothing.
            row["cap_tiers"] = sorted(
                {tier for ac in alert.companies if (tier := cap_tiers.get(ac.company.ticker))}
            )
            results.append(row)
    # PREVIEW-ONLY (this branch): in-memory demo stories appended when
    # ALLOW_DEMO_FEED=true -- set only on the newsflo-v2 preview service.
    # No demo rows exist in the shared database; the main service never
    # sets the flag and master never carries this code path.
    if settings.allow_demo_feed and date is None:
        from app.routers.feed_v2_demo_inject import demo_feed_rows

        results.extend(demo_feed_rows(db))
    return results


# NOTE: static paths (/discovery/..., /portfolio) are declared BEFORE the
# catch-all /{alert_id} route -- FastAPI matches in declaration order, and
# "/portfolio" would otherwise 422 against the int alert_id parser.
@router.get("/discovery/{tab}")
def get_discovery(
    tab: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Discovery paths (spec v2 §6): materiality / holdings / unusual.
    Factual framing only -- "most affected by news", never "best to buy"."""
    if tab == "materiality":
        return compute_materiality_feed(db)
    if tab == "holdings":
        return compute_related_to_holdings(db, current_user)
    if tab == "unusual":
        return compute_unusual_activity(db)
    raise HTTPException(status_code=404, detail="Unknown discovery tab")


@router.get("/portfolio")
def get_portfolio_overlay(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Portfolio overlay (spec v2 §2 portfolio dot / §8): the user's
    holdings and which of today's alerts touches each. Requires login --
    holdings are sensitive (spec §9)."""
    start_utc, end_utc = day_utc_window(today_ist())
    holdings = (
        db.query(Holding, Company)
        .join(Company, Holding.company_id == Company.id)
        .filter(Holding.user_id == current_user.id)
        .order_by(Company.name.asc())
        .all()
    )
    todays_alert_companies = (
        db.query(AlertCompany, Alert)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .all()
    )
    latest_alert_by_company_id: dict[int, Alert] = {}
    for alert_company, alert in todays_alert_companies:
        latest_alert_by_company_id.setdefault(alert_company.company_id, alert)

    results = []
    for holding, company in holdings:
        alert = latest_alert_by_company_id.get(company.id)
        results.append({
            "ticker": company.ticker,
            "name": company.name,
            "quantity": holding.quantity,
            "logo_url": logo_url(company),
            "affected_alert_id": alert.id if alert else None,
            "affected_headline": (alert.summary_short or alert.article.title) if alert else None,
        })
    return {
        "holdings": results,
        "affected_count": sum(1 for r in results if r["affected_alert_id"] is not None),
    }


@router.get("/{alert_id}")
def get_feed_v2_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    # PREVIEW-ONLY (this branch): negative ids are in-memory demo alerts.
    if alert_id < 0 and settings.allow_demo_feed:
        from app.routers.feed_v2_demo_inject import demo_alert_detail

        payload = demo_alert_detail(db, alert_id)
        if payload is not None:
            return payload
    alert = _query_with_relations(db).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    measurement = compute_alert_measurement(db, alert)
    if measurement is None:
        raise HTTPException(status_code=404, detail="Alert has no measured companies")

    held_company_ids = _held_company_ids(db, current_user)
    repeated_images = repeated_image_urls(
        db, [alert.article.image_url] if alert.article.image_url else [],
    )
    translations = _bulk_translations(db, [alert], lang)
    result = _serialize(alert, measurement, held_company_ids, repeated_images, translations)
    # Layered card back (spec v2 §5/§7): every affected company, grouped by
    # relationship into ordered winners/losers layers.
    result["layers"] = compute_ripple_layers(db, alert, held_company_ids)
    # Translated per-company `why` overlay (silent English fallback).
    whys = bulk_alert_company_whys(
        db, [row["alert_company_id"] for layer in result["layers"] for row in layer["rows"]], lang,
    )
    for layer in result["layers"]:
        for row in layer["rows"]:
            translated_why = whys.get(row["alert_company_id"])
            if translated_why and row["why"]:
                row["why"] = translated_why
    result["timeline"] = get_timeline_entries(db, alert)
    # -- COMMENTED OUT (superseded by result["layers"] above -- the old flat
    # ripple + impact_companies split served the pre-swipe-card UI):
    # result["ripple"] = compute_ripple_companies(
    #     db, alert, exclude_company_id=measurement["peak_company_id"], held_company_ids=held_company_ids,
    # )
    # result["impact_companies"] = compute_impact_companies(db, alert)
    return result
