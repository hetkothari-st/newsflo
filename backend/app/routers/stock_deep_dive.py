"""Level 4 stock deep-dive endpoint (docs/NEWS_IMPACT_APP_SPEC.md §2, §9) --
"what is this company & how hard hit?". Reached either WITH an alert_id
(from a ripple/peer row tap, within one news event's context: shows that
event's measured excess/intensity for this company plus its same-alert
sector peers) or WITHOUT one (from the Directory, browsing with no news
context: company facts only -- name, sector, cap tier, business_desc,
market cap, PE -- no excess/intensity/peers, since none of those mean
anything without a specific event to measure against). Never fabricates a
number for either path (see this phase's Global Constraints).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.companies.price_series import fetch_pe_ratio
from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.market.cap_tier import compute_cap_tier_for_ticker
from app.market.ripple import get_sector_peers_for_alert
from app.models import Alert, AlertCompany, Company, MarketMove, User
from app.routers.articles import get_db
from app.routers.feed_v2 import _held_company_ids

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])


def _company_facts(session: Session, company: Company, held_company_ids: set[int]) -> dict:
    return {
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "cap_tier": compute_cap_tier_for_ticker(session, company.ticker),
        "business_desc": company.business_desc,
        "market_cap": company.market_cap,
        "pe": fetch_pe_ratio(company.ticker),
        "in_my_holdings": company.id in held_company_ids,
        "excess_move_pct": None,
        "raw_move_pct": None,
        "sector_move_pct": None,
        "volume_multiple": None,
        "intensity": None,
        "is_exposure_only": None,
        "peers": [],
    }


@router.get("/stock/{ticker}")
def get_stock_deep_dive(
    ticker: str,
    alert_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    company = db.query(Company).filter(Company.ticker == ticker).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Stock not found")

    held_company_ids = _held_company_ids(db, current_user)
    result = _company_facts(db, company, held_company_ids)

    if alert_id is None:
        return result

    alert = db.query(Alert).filter(Alert.id == alert_id).one_or_none()
    if alert is None:
        return result

    alert_company = (
        db.query(AlertCompany)
        .filter(AlertCompany.alert_id == alert_id, AlertCompany.company_id == company.id)
        .one_or_none()
    )
    if alert_company is None:
        return result

    move = (
        db.query(MarketMove)
        .filter(MarketMove.alert_id == alert_id, MarketMove.company_id == company.id)
        .one_or_none()
    )
    peers = get_sector_peers_for_alert(db, alert, company, held_company_ids)
    result["peers"] = peers

    if move is None or move.measurement_status != "ok" or move.excess_move_pct is None:
        result["is_exposure_only"] = True
        return result

    ok_excess_values = [
        m.excess_move_pct
        for m in db.query(MarketMove).filter_by(alert_id=alert_id).all()
        if m.measurement_status == "ok"
    ]
    breadth_score = compute_breadth_score(ok_excess_values)

    result["is_exposure_only"] = False
    result["excess_move_pct"] = move.excess_move_pct
    result["raw_move_pct"] = move.raw_move_pct
    result["sector_move_pct"] = move.sector_move_pct
    result["volume_multiple"] = move.volume_multiple
    result["intensity"] = _intensity_for_company_move(db, company, move, breadth_score)
    return result
