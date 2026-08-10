"""Level 4 stock deep-dive endpoint (docs/NEWS_IMPACT_APP_SPEC.md §2, §9) --
"what is this company & how hard hit?". Reached either WITH an alert_id
(from a ripple/peer row tap, within one news event's context: shows that
event's measured excess/intensity for this company plus its same-alert
sector peers) or WITHOUT one (from the Directory, browsing with no news
context: company facts only -- name, sector, cap tier, fundamentals,
market cap, PE -- no excess/intensity/peers, since none of those mean
anything without a specific event to measure against). Never fabricates a
number for either path (see this phase's Global Constraints).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.companies.branding import logo_url
from app.companies.descriptions import sourced_description
from app.companies.fundamentals import fundamentals_payload, ratio_or_none
from app.companies.price_series import fetch_pe_ratio
from app.i18n import get_lang
from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.market.cap_tier import cap_tier_map, resolve_cap_tier
from app.market.event_volatility import volatility_range_payload
from app.market.liquidity import compute_liquidity_tier
from app.market.ripple import get_sector_peers_for_alert
from app.market.ripple_layers import compute_ripple_layers
from app.models import Alert, AlertCompany, Company, MarketMove, User
from app.routers.articles import get_db
from app.routers.feed_v2 import _held_company_ids
from app.translation.lookup import bulk_alert_company_translations, bulk_alert_company_whys

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])


def _company_facts(session: Session, company: Company, held_company_ids: set[int]) -> dict:
    return {
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "cap_tier": (resolved := resolve_cap_tier(session, company)) and resolved.tier,
        # Sourced descriptions only -- the legacy LLM-invented values stay
        # withheld. The URL is the CC BY-SA attribution and must travel with
        # the text.
        "business_desc": (_desc := sourced_description(company))[0],
        "business_desc_source_url": _desc[1],
        "fundamentals": fundamentals_payload(company),
        "logo_url": logo_url(company),
        "market_cap": company.market_cap,
        "pe": fetch_pe_ratio(company.ticker),
        "in_my_holdings": company.id in held_company_ids,
        "excess_move_pct": None,
        "raw_move_pct": None,
        "sector_move_pct": None,
        "volume_multiple": None,
        # Spec v2 §4.6 / §6 risk cues -- populated only in alert context
        # (they derive from that alert's MarketMove row).
        "liquidity_tier": None,
        "delivery_pct": None,
        "intensity": None,
        "is_exposure_only": None,
        # Per-story reasoning (alert context only): why THIS company sits
        # in THAT card-back section for THIS news -- the causal one-liner
        # (why), the analysis rationale, and the section it renders under.
        "why": None,
        "rationale": None,
        "section_title": None,
        "peers": [],
        # Subsystem D: only meaningful within an event context -- populated
        # on the alert path below, never for Directory browsing.
        "volatility_range": None,
    }


@router.get("/stock/{ticker}")
def get_stock_deep_dive(
    ticker: str,
    alert_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
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

    # Per-story reasoning block (rendered below "What they do"): the causal
    # why (translated when available), the analysis rationale, and which
    # card-back section this company renders under for this alert.
    translated_why = bulk_alert_company_whys(db, [alert_company.id], lang).get(alert_company.id)
    translated = bulk_alert_company_translations(db, [alert_company.id], lang).get(alert_company.id)
    result["why"] = translated_why or alert_company.why
    result["rationale"] = (translated[0] if translated and translated[0] else None) or alert_company.rationale
    result["volatility_range"] = volatility_range_payload(db, company, alert.category)
    for layer in compute_ripple_layers(db, alert, held_company_ids):
        if any(row["ticker"] == company.ticker for row in layer["rows"]):
            result["section_title"] = layer["title"]
            break

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
    result["liquidity_tier"] = compute_liquidity_tier(move.avg_traded_value)
    result["delivery_pct"] = move.delivery_pct
    result["intensity"] = _intensity_for_company_move(db, company, move, breadth_score)
    return result


@router.get("/directory")
def get_directory(
    cap_tier: str | None = None,
    sector: str | None = None,
    db: Session = Depends(get_db),
):
    tiers = cap_tier_map(db)

    query = db.query(Company).filter(Company.market_cap.isnot(None))
    if sector is not None:
        query = query.filter(Company.sector == sector)
    companies = query.order_by(Company.ticker.asc()).all()

    results = []
    for company in companies:
        tier = tiers.get(company.ticker)
        if cap_tier is not None and tier != cap_tier:
            continue
        results.append({
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "cap_tier": tier,
            "logo_url": logo_url(company),
            # Raw rupees (normalize.py stores BSE crore * 1e7); the client
            # formats to crore for display.
            "market_cap": company.market_cap,
            "index_tier": company.index_tier,
            "sub_sector": company.sub_sector,
            "pe": ratio_or_none(company.pe),
            "pb": ratio_or_none(company.pb),
            "roe": ratio_or_none(company.roe),
        })
    return results
