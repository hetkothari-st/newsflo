"""Discovery paths (spec v2 §6): surfacing mid/small/micro caps the
headlines miss. Three entry paths, each computed fresh from today's
alerts + MarketMove rows -- ranked by impact signals, never by headline
prominence ("headline-ranked feeds inherit the media's large-cap bias
and kill discovery").

Framing stays factual -- "most affected by news", never "best to buy"
(spec §6, §9). Every small/micro surface carries its liquidity tag;
low-delivery and thin-trading warnings fire where applicable (spec §11).
"""
from sqlalchemy.orm import Session, selectinload

from app import config
from app.companies.branding import logo_url
from app.ist_time import day_utc_window, today_ist
from app.market.cap_tier import cap_tier_map
from app.market.liquidity import compute_liquidity_tier
from app.models import Alert, AlertCompany, Holding, MarketMove, User

RESULT_LIMIT = 20


def _today_measured_rows(session: Session) -> list[tuple[AlertCompany, MarketMove, Alert]]:
    """Every (AlertCompany, MarketMove, Alert) triple for today's alerts
    with a real measured move (measurement_status == 'ok')."""
    start_utc, end_utc = day_utc_window(today_ist())
    return (
        session.query(AlertCompany, MarketMove, Alert)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(
            MarketMove,
            (MarketMove.alert_id == AlertCompany.alert_id)
            & (MarketMove.company_id == AlertCompany.company_id),
        )
        .options(selectinload(AlertCompany.company), selectinload(AlertCompany.parent_company))
        .filter(
            Alert.created_at >= start_utc,
            Alert.created_at < end_utc,
            MarketMove.measurement_status == "ok",
        )
        .all()
    )


def _cap_tiers(session: Session) -> dict[str, str]:
    # Staleness- and market-aware (spec §6.3): a company whose cap is too
    # old to rank honestly is absent from the map and renders as no-data.
    return cap_tier_map(session)


def _entry(alert_company: AlertCompany, move: MarketMove, alert: Alert, cap_tiers: dict[str, str]) -> dict:
    company = alert_company.company
    return {
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "cap_tier": cap_tiers.get(company.ticker),
        "liquidity_tier": compute_liquidity_tier(move.avg_traded_value),
        "excess_move_pct": move.excess_move_pct,
        "volume_multiple": move.volume_multiple,
        "delivery_pct": move.delivery_pct,
        "materiality": move.materiality,
        "why": alert_company.why or alert.summary_short,
        "alert_id": alert.id,
        "headline": alert.article.title,
        "via_ticker": None,
        "logo_url": logo_url(company),
        "low_delivery": (
            move.delivery_pct is not None and move.delivery_pct < config.LOW_DELIVERY_WARNING_PCT
        ),
        "thin_trading": compute_liquidity_tier(move.avg_traded_value) == "LOW",
    }


def compute_materiality_feed(session: Session) -> list[dict]:
    """Path 1 (spec §6): rank by news-size-vs-company-size, not price move
    -- floats micro/small caps where an event is transformational. Rows
    without a computed materiality are omitted (nothing to rank them by),
    never given an invented score."""
    cap_tiers = _cap_tiers(session)
    entries = [
        _entry(ac, move, alert, cap_tiers)
        for ac, move, alert in _today_measured_rows(session)
        if move.materiality is not None
    ]
    entries.sort(key=lambda e: e["materiality"], reverse=True)
    return entries[:RESULT_LIMIT]


def compute_related_to_holdings(session: Session, current_user: User | None) -> list[dict]:
    """Path 2 (spec §6): start from a stock the user owns -> surface the
    smaller suppliers, users, substitutes and pure-play peers the same
    news touches (the cascade's parent_company chain). Held companies
    themselves are excluded -- this is discovery, not the portfolio view.
    Anonymous users get an empty list (the UI explains why)."""
    if current_user is None:
        return []
    held_company_ids = {
        h.company_id for h in session.query(Holding).filter_by(user_id=current_user.id).all()
    }
    if not held_company_ids:
        return []
    cap_tiers = _cap_tiers(session)
    entries = []
    for alert_company, move, alert in _today_measured_rows(session):
        if alert_company.company_id in held_company_ids:
            continue
        if alert_company.parent_company_id not in held_company_ids:
            continue
        entry = _entry(alert_company, move, alert, cap_tiers)
        entry["via_ticker"] = (
            alert_company.parent_company.ticker if alert_company.parent_company else None
        )
        entries.append(entry)
    entries.sort(
        key=lambda e: abs(e["excess_move_pct"]) if e["excess_move_pct"] is not None else 0,
        reverse=True,
    )
    return entries[:RESULT_LIMIT]


def compute_unusual_activity(session: Session) -> list[dict]:
    """Path 3 (spec §6): small/micro caps with abnormal volume today, each
    flagged by whether the delivery data makes the move trustworthy or
    speculative (low_delivery / thin_trading flags on every entry)."""
    cap_tiers = _cap_tiers(session)
    entries = []
    for alert_company, move, alert in _today_measured_rows(session):
        tier = cap_tiers.get(alert_company.company.ticker)
        if tier not in ("SMALL", "MICRO"):
            continue
        if move.volume_multiple is None or move.volume_multiple < config.UNUSUAL_VOLUME_MULTIPLE:
            continue
        entries.append(_entry(alert_company, move, alert, cap_tiers))
    entries.sort(key=lambda e: e["volume_multiple"], reverse=True)
    return entries[:RESULT_LIMIT]
