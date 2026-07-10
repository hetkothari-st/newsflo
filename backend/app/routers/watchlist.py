from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models import Company, User, UserWatchlistCategory, UserWatchlistCompany
from app.routers.articles import get_db

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistRequest(BaseModel):
    categories: list[str]
    company_ids: list[int]


def _serialize_watchlist(db: Session, user_id: int) -> dict:
    categories = [
        row.category
        for row in db.query(UserWatchlistCategory).filter_by(user_id=user_id).all()
    ]
    company_rows = (
        db.query(UserWatchlistCompany, Company)
        .join(Company, UserWatchlistCompany.company_id == Company.id)
        .filter(UserWatchlistCompany.user_id == user_id)
        .all()
    )
    companies = [
        {"company_id": company.id, "ticker": company.ticker, "name": company.name}
        for _, company in company_rows
    ]
    return {"categories": sorted(categories), "companies": companies}


@router.get("")
def get_watchlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _serialize_watchlist(db, current_user.id)


@router.put("")
def put_watchlist(
    payload: WatchlistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Replace-all semantics: wipe this user's selection, then insert the new set.
    # set(...) dedupes any repeats in the body so the unique constraints hold.
    db.query(UserWatchlistCategory).filter_by(user_id=current_user.id).delete()
    db.query(UserWatchlistCompany).filter_by(user_id=current_user.id).delete()
    for category in set(payload.categories):
        db.add(UserWatchlistCategory(user_id=current_user.id, category=category))
    for company_id in set(payload.company_ids):
        db.add(UserWatchlistCompany(user_id=current_user.id, company_id=company_id))
    db.commit()
    return _serialize_watchlist(db, current_user.id)
