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
    other companies the same news touches. Two link signals, strongest
    first per row:

    1. The cascade's parent_company chain (kept where it exists) -- but
       the v3 engine's causal parents are economic nodes/sectors, not
       companies, so parent_company_id is almost never set anymore
       (3 rows in the whole production DB); relying on it alone left the
       tab permanently empty.
    2. Co-affection (the v3-era signal): a non-held company in the SAME
       alert as a held one, via_ticker = the held company that links it.

    Held companies themselves are excluded -- this is discovery, not the
    portfolio view. Anonymous users get an empty list (the UI explains
    why)."""
    if current_user is None:
        return []
    held_company_ids = {
        h.company_id for h in session.query(Holding).filter_by(user_id=current_user.id).all()
    }
    if not held_company_ids:
        return []
    cap_tiers = _cap_tiers(session)
    rows = _today_measured_rows(session)

    # Which alerts touch a holding, and through which held company --
    # scan ALL of today's alert companies (not only measured ones): a
    # held large cap with a failed measurement still links its alert.
    start_utc, end_utc = day_utc_window(today_ist())
    held_rows = (
        session.query(AlertCompany)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .options(selectinload(AlertCompany.company))
        .filter(
            Alert.created_at >= start_utc,
            Alert.created_at < end_utc,
            AlertCompany.company_id.in_(held_company_ids),
        )
        .all()
    )
    held_ticker_by_alert: dict[int, str] = {}
    for held in held_rows:
        held_ticker_by_alert.setdefault(held.alert_id, held.company.ticker)

    entries = []
    for alert_company, move, alert in rows:
        if alert_company.company_id in held_company_ids:
            continue
        via_ticker = None
        if alert_company.parent_company_id in held_company_ids:
            via_ticker = (
                alert_company.parent_company.ticker if alert_company.parent_company else None
            )
        elif alert.id in held_ticker_by_alert:
            via_ticker = held_ticker_by_alert[alert.id]
        else:
            continue
        entry = _entry(alert_company, move, alert, cap_tiers)
        entry["via_ticker"] = via_ticker
        entries.append(entry)
    entries.sort(
        key=lambda e: abs(e["excess_move_pct"]) if e["excess_move_pct"] is not None else 0,
        reverse=True,
    )
    return entries[:RESULT_LIMIT]


# Fallback floor for the unusual tab: relative volume below this is
# ordinary churn, not worth surfacing even on a quiet day.
FALLBACK_VOLUME_MULTIPLE = 1.5


def compute_unusual_activity(session: Session) -> list[dict]:
    """Path 3 (spec §6): small/micro caps with abnormal volume today, each
    flagged by whether the delivery data makes the move trustworthy or
    speculative (low_delivery / thin_trading flags on every entry).

    Production reality (measured 2026-08-13): the feed skews large-cap
    and quiet days top out below the 2.0x threshold, so the strict filter
    rendered the tab permanently empty. When nothing clears the strict
    bar, fall back to today's highest-relative-volume movers -- any cap
    tier, still at least FALLBACK_VOLUME_MULTIPLE -- rather than showing
    nothing. Honest empty only when nothing traded unusually at all."""
    cap_tiers = _cap_tiers(session)
    rows = _today_measured_rows(session)

    strict, fallback = [], []
    for alert_company, move, alert in rows:
        if move.volume_multiple is None:
            continue
        tier = cap_tiers.get(alert_company.company.ticker)
        if tier in ("SMALL", "MICRO") and move.volume_multiple >= config.UNUSUAL_VOLUME_MULTIPLE:
            strict.append(_entry(alert_company, move, alert, cap_tiers))
        elif move.volume_multiple >= FALLBACK_VOLUME_MULTIPLE:
            fallback.append(_entry(alert_company, move, alert, cap_tiers))

    entries = strict if strict else fallback
    entries.sort(key=lambda e: e["volume_multiple"], reverse=True)
    return entries[:RESULT_LIMIT]
