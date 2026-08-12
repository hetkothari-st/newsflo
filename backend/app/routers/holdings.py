from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.holdings.csv_loader import load_holdings_from_csv
from app.holdings.import_parse import parse_and_match
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


@router.post("/import")
def import_holdings(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Provider-agnostic import: any Indian broker's holdings CSV export
    (Zerodha console, Groww, Upstox, Angel One, ...). Rows resolve by
    ISIN first, then NSE/BSE ticker; unmatched rows come back in the
    report instead of being silently dropped."""
    matches, report = parse_and_match(db, file.file.read())
    for company, quantity in matches:
        _upsert_holding(db, current_user.id, company.id, quantity)
        report.imported.append({
            "ticker": company.ticker, "name": company.name, "quantity": quantity,
        })
    return report.as_dict()


@router.delete("/{ticker}", status_code=204)
def delete_holding(
    ticker: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = db.query(Company).filter_by(ticker=ticker).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Unknown ticker")
    holding = (
        db.query(Holding)
        .filter_by(user_id=current_user.id, company_id=company.id)
        .one_or_none()
    )
    if holding is None:
        raise HTTPException(status_code=404, detail="Not held")
    db.delete(holding)
    db.commit()


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
