"""CAR (Cumulative Abnormal Return) review endpoints (docs/
NEWS_IMPACT_APP_SPEC.md §4.6) -- an internal, any-logged-in-user tool
(this app has no admin/staff tier; adding one is out of scope for a
single internal screen, confirmed at plan time). Shows whether flagged
reactions held or reversed once the market has actually traded far
enough past each alert -- the data this build's whole measurement spine
gets back-validated against.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import config
from app.auth.dependencies import get_current_user
from app.models import Alert, AlertCompany, CarOutcome, User
from app.outcomes.car import compute_car_outcome_label
from app.routers.articles import get_db

router = APIRouter(prefix="/api/car-review", tags=["car-review"])

OUTCOMES_LIMIT = 200


def _serialize(outcome: CarOutcome, alert_company: AlertCompany) -> dict:
    company = alert_company.company
    alert = alert_company.alert
    return {
        "id": outcome.id,
        "ticker": company.ticker,
        "company_name": company.name,
        "category": outcome.category,
        "article_title": alert.article.title,
        "article_url": alert.article.url,
        "alert_created_at": alert.created_at.isoformat(),
        "day0_excess_move_pct": outcome.day0_excess_move_pct,
        "car_pct": outcome.car_pct,
        "outcome_label": compute_car_outcome_label(outcome.day0_excess_move_pct, outcome.car_pct),
    }


@router.get("")
def list_car_review(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(CarOutcome, AlertCompany)
        .join(AlertCompany, CarOutcome.alert_company_id == AlertCompany.id)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .order_by(Alert.created_at.desc())
        .limit(OUTCOMES_LIMIT)
        .all()
    )
    return [_serialize(outcome, alert_company) for outcome, alert_company in rows]


@router.get("/summary")
def get_car_review_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    outcomes = db.query(CarOutcome).all()
    sample_count = len(outcomes)

    if sample_count < config.CAR_SUMMARY_SAMPLE_THRESHOLD:
        return {"sample_count": sample_count, "hold_rate": None, "mean_car_pct": None, "by_category": []}

    held_count = sum(
        1 for o in outcomes if compute_car_outcome_label(o.day0_excess_move_pct, o.car_pct) == "HELD"
    )
    hold_rate = held_count / sample_count
    mean_car_pct = sum(o.car_pct for o in outcomes) / sample_count

    by_category_outcomes: dict[str, list[CarOutcome]] = {}
    for o in outcomes:
        by_category_outcomes.setdefault(o.category, []).append(o)

    by_category = []
    for category, cat_outcomes in sorted(by_category_outcomes.items()):
        cat_count = len(cat_outcomes)
        if cat_count < config.CAR_SUMMARY_SAMPLE_THRESHOLD:
            by_category.append({"category": category, "sample_count": cat_count, "hold_rate": None, "mean_car_pct": None})
            continue
        cat_held = sum(
            1 for o in cat_outcomes if compute_car_outcome_label(o.day0_excess_move_pct, o.car_pct) == "HELD"
        )
        by_category.append({
            "category": category,
            "sample_count": cat_count,
            "hold_rate": cat_held / cat_count,
            "mean_car_pct": sum(o.car_pct for o in cat_outcomes) / cat_count,
        })

    return {
        "sample_count": sample_count,
        "hold_rate": hold_rate,
        "mean_car_pct": mean_car_pct,
        "by_category": by_category,
    }
