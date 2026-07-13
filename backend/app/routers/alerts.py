from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.companies.history import get_past_mentions
from app.companies.market import infer_market
from app.models import Alert, Holding, User
from app.pipeline import decode_key_points
from app.routers.articles import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    # Anonymous requests get an empty set -> every company is in_my_holdings=False.
    held_company_ids: set[int] = set()
    if current_user is not None:
        held_company_ids = {
            h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()
        }

    alerts = db.query(Alert).order_by(Alert.created_at.desc()).all()
    return [{
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id, "title": alert.article.title, "url": alert.article.url,
            "image_url": alert.article.image_url,
        },
        "companies": [{
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale, "key_points": decode_key_points(ac),
            "basis": ac.basis, "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
            "past_mentions": get_past_mentions(db, ac.company_id, alert.created_at),
        } for ac in alert.companies],
    } for alert in alerts]
