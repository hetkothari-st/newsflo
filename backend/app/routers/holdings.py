from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.holdings.csv_loader import load_holdings_from_csv
from app.models import Company, Holding, User
from app.routers.articles import get_db

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


class HoldingRequest(BaseModel):
    ticker: str
    quantity: float


def _upsert_holding(db: Session, user_id: int, company_id: int, quantity: float) -> Holding:
    existing = db.query(Holding).filter_by(user_id=user_id, company_id=company_id).one_or_none()
    if existing is not None:
        existing.quantity = quantity
        holding = existing
    else:
        holding = Holding(user_id=user_id, company_id=company_id, quantity=quantity)
        db.add(holding)
    db.commit()
    db.refresh(holding)
    return holding


@router.post("")
def add_holding(
    payload: HoldingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = db.query(Company).filter_by(ticker=payload.ticker).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Unknown ticker")
    holding = _upsert_holding(db, current_user.id, company.id, payload.quantity)
    return {
        "company_id": company.id, "ticker": company.ticker,
        "name": company.name, "quantity": holding.quantity,
    }


@router.post("/csv")
def upload_holdings_csv(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loaded = load_holdings_from_csv(db, current_user.id, file.file)
    return {"loaded": loaded}


@router.get("")
def list_holdings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Holding, Company)
        .join(Company, Holding.company_id == Company.id)
        .filter(Holding.user_id == current_user.id)
        .all()
    )
    return [{
        "company_id": company.id, "ticker": company.ticker,
        "name": company.name, "quantity": holding.quantity,
    } for holding, company in rows]
