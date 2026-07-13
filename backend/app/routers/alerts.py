from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.companies.history import get_past_mentions
from app.companies.market import infer_market
from app.i18n import get_lang
from app.models import Alert, Holding, User
from app.pipeline import decode_key_points
from app.routers.articles import get_db
from app.translation.lookup import (
    bulk_alert_company_translations,
    bulk_article_titles,
    bulk_category_labels,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    # Anonymous requests get an empty set -> every company is in_my_holdings=False.
    held_company_ids: set[int] = set()
    if current_user is not None:
        held_company_ids = {
            h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()
        }

    alerts = db.query(Alert).order_by(Alert.created_at.desc()).all()

    # Three bulk lookups total, regardless of alert count, keyed by lang --
    # empty dicts (and every .get() below falling back to English) when
    # lang == "en" or nothing's been translated yet.
    article_titles = bulk_article_titles(db, [a.article_id for a in alerts], lang)
    ac_translations = bulk_alert_company_translations(
        db, [ac.id for a in alerts for ac in a.companies], lang
    )
    category_labels = bulk_category_labels(db, list({a.category for a in alerts}), lang)

    result = []
    for alert in alerts:
        companies = []
        for ac in alert.companies:
            rationale, key_points = ac_translations.get(ac.id, (ac.rationale, decode_key_points(ac)))
            companies.append({
                "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
                "index_tier": ac.company.index_tier, "sector": ac.company.sector, "direction": ac.direction,
                "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
                "rationale": rationale, "key_points": key_points,
                "basis": ac.basis, "confidence": ac.confidence,
                "market": infer_market(ac.company.ticker),
                "in_my_holdings": ac.company_id in held_company_ids,
                "past_mentions": get_past_mentions(db, ac.company_id, alert.created_at),
            })
        result.append({
            "id": alert.id,
            # `category` stays the raw, canonical, untranslated slug -- it's
            # a matching/storage key (watchlist filtering, color swatch
            # lookup), not just display text. `category_label` is the
            # additive, purely-for-display translated field.
            "category": alert.category,
            "category_label": category_labels.get(alert.category, alert.category),
            "created_at": alert.created_at.isoformat(),
            "article": {
                "id": alert.article.id,
                "title": article_titles.get(alert.article_id, alert.article.title),
                "url": alert.article.url,
                "image_url": alert.article.image_url,
            },
            "companies": companies,
        })
    return result
