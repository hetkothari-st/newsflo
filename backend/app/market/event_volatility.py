"""Subsystem D: empirical per-(stock, news-category) reaction ranges
(docs/superpowers/specs/2026-08-05-event-volatility-ranges-design.md).

Built from measured market_moves rows only -- status 'ok', non-null
excess_move_pct, non-null category. No LLM output, no estimates. Where the
data is too thin (below the config thresholds) there is simply no row, and
the UI shows nothing: omit rather than fabricate.

The table is an aggregate with no identity worth preserving, so refresh is
a full delete + reinsert -- except that empty input leaves the previous
rows intact (never clobber good data with nothing).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

from sqlalchemy.orm import Session

from app import config
from app.models import Company, EventVolatilityRange, MarketMove

SOURCE_NAME = "market_moves"


@dataclass(frozen=True)
class MoveFact:
    company_id: int
    sector: str | None
    category: str
    excess_move_pct: float
    # The alert (news event) this measurement came from. n_events counts
    # DISTINCT alert_ids in a pool, not measurement rows -- one broad alert
    # that resolves 5 same-sector companies is ONE day's cross-sectional
    # spread, not 5 independent observations of how this category behaves.
    alert_id: int


def collect_move_facts(session: Session) -> list[MoveFact]:
    """Every usable measurement, with the company's sector AT BUILD TIME --
    a company whose sector was corrected contributes to its current
    sector's pool, not its historical one. Rows with NULL category
    (pre-backfill) are excluded, never joined live to alerts: one source
    of truth per row (spec §3.2).

    Restricted to India/NORMAL companies -- same restriction as
    app.companies.resolution._is_tradeable_indian's own fan-out branch.
    Without it, a curated GLOBAL company or a RESTRICTED/SME/SUSPENDED row
    (which can still carry a measured market_move) would feed a pool whose
    every other consumer (deep dive, card back) is India/NORMAL-only."""
    rows = (
        session.query(MarketMove, Company.sector)
        .join(Company, Company.id == MarketMove.company_id)
        .filter(MarketMove.measurement_status == "ok")
        .filter(MarketMove.excess_move_pct.isnot(None))
        .filter(MarketMove.category.isnot(None))
        .filter(Company.market == "INDIA")
        .filter(Company.tradeability == "NORMAL")
        .all()
    )
    return [
        MoveFact(
            company_id=move.company_id,
            sector=sector,
            category=move.category,
            excess_move_pct=move.excess_move_pct,
            alert_id=move.alert_id,
        )
        for move, sector in rows
    ]


def _range_stats(alert_ids: set[int], moves: list[float]) -> dict:
    """min/median/max span every usable measurement in the pool; n_events
    is the count of DISTINCT alerts backing it, not the measurement count
    -- see MoveFact.alert_id."""
    return {
        "n_events": len(alert_ids),
        "min_excess_move_pct": min(moves),
        "median_excess_move_pct": median(moves),
        "max_excess_move_pct": max(moves),
    }


def compute_ranges(facts: list[MoveFact]) -> list[dict]:
    """Pure: facts in, range-row dicts out.

    Thresholds gate on DISTINCT EVENTS (alert_ids), not measurement rows:
    COMPANY rows need EVENT_VOL_COMPANY_MIN_EVENTS distinct alerts; SECTOR
    pools need EVENT_VOL_SECTOR_MIN_EVENTS distinct alerts and include
    every company's measurements (the sector row describes the sector, not
    "the leftovers"). One alert resolving 5 same-sector companies is 1
    event, not 5 -- it must not alone clear the sector threshold. For
    COMPANY rows this coincides with measurement count (market_moves has
    UNIQUE(alert_id, company_id)); implemented uniformly with SECTOR rows
    regardless. min/median/max always span ALL usable measurements in the
    pool, not just one per alert. sector 'other' or None pools nothing --
    an absence of classification is not a peer group."""
    by_company: dict[tuple[int, str], list[tuple[int, float]]] = defaultdict(list)
    by_sector: dict[tuple[str, str], list[tuple[int, float]]] = defaultdict(list)
    for fact in facts:
        by_company[(fact.company_id, fact.category)].append((fact.alert_id, fact.excess_move_pct))
        if fact.sector and fact.sector != "other":
            by_sector[(fact.sector, fact.category)].append((fact.alert_id, fact.excess_move_pct))

    rows: list[dict] = []
    for (company_id, category), pairs in sorted(by_company.items()):
        alert_ids = {alert_id for alert_id, _ in pairs}
        if len(alert_ids) < config.EVENT_VOL_COMPANY_MIN_EVENTS:
            continue
        moves = [excess for _, excess in pairs]
        rows.append({
            "level": "COMPANY", "company_id": company_id, "sector": None,
            "category": category, **_range_stats(alert_ids, moves),
        })
    for (sector, category), pairs in sorted(by_sector.items()):
        alert_ids = {alert_id for alert_id, _ in pairs}
        if len(alert_ids) < config.EVENT_VOL_SECTOR_MIN_EVENTS:
            continue
        moves = [excess for _, excess in pairs]
        rows.append({
            "level": "SECTOR", "company_id": None, "sector": sector,
            "category": category, **_range_stats(alert_ids, moves),
        })
    return rows


def apply_ranges(session: Session, rows: list[dict], as_of: date) -> dict:
    """Full rebuild in one transaction. Empty input writes nothing and
    keeps the previous rows -- a dev DB with no measured moves must not
    blank production's ranges through some future shared code path."""
    if not rows:
        return {"deleted": 0, "inserted": 0}
    deleted = session.query(EventVolatilityRange).delete()
    for row in rows:
        session.add(EventVolatilityRange(as_of=as_of, source=SOURCE_NAME, **row))
    session.commit()
    return {"deleted": deleted, "inserted": len(rows)}


def rebuild(session: Session, as_of: date) -> dict:
    facts = collect_move_facts(session)
    result = apply_ranges(session, compute_ranges(facts), as_of)
    return {"facts": len(facts), **result}


def range_payload(row: EventVolatilityRange) -> dict:
    """Serialized shape (spec §6). level travels with the numbers so the UI
    can label a pooled range -- a sector range dressed as stock-specific is
    a lie about sample identity."""
    return {
        "level": row.level,
        "n_events": row.n_events,
        "min_excess_move_pct": row.min_excess_move_pct,
        "median_excess_move_pct": row.median_excess_move_pct,
        "max_excess_move_pct": row.max_excess_move_pct,
        "as_of": row.as_of.isoformat(),
    }


def ranges_for_category(
    session: Session, category: str,
) -> tuple[dict[int, EventVolatilityRange], dict[str, EventVolatilityRange]]:
    """All stored rows for one category, keyed for O(1) per-row lookup --
    the card back iterates many companies and must not query per row."""
    rows = (
        session.query(EventVolatilityRange)
        .filter(EventVolatilityRange.category == category)
        .all()
    )
    by_company = {r.company_id: r for r in rows if r.level == "COMPANY"}
    by_sector = {r.sector: r for r in rows if r.level == "SECTOR"}
    return by_company, by_sector


def lookup_range(
    by_company: dict[int, EventVolatilityRange],
    by_sector: dict[str, EventVolatilityRange],
    company: Company,
) -> dict | None:
    """The fallback ladder against pre-fetched maps: COMPANY row, else the
    company's sector pool, else None."""
    row = by_company.get(company.id)
    if row is None and company.sector:
        row = by_sector.get(company.sector)
    return range_payload(row) if row is not None else None


def volatility_range_payload(
    session: Session, company: Company, category: str | None,
) -> dict | None:
    """Single-company convenience over the same ladder. None without a
    category -- a range is meaningless without an event type."""
    if not category:
        return None
    by_company, by_sector = ranges_for_category(session, category)
    return lookup_range(by_company, by_sector, company)
