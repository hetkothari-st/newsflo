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


def collect_move_facts(session: Session) -> list[MoveFact]:
    """Every usable measurement, with the company's sector AT BUILD TIME --
    a company whose sector was corrected contributes to its current
    sector's pool, not its historical one. Rows with NULL category
    (pre-backfill) are excluded, never joined live to alerts: one source
    of truth per row (spec §3.2)."""
    rows = (
        session.query(MarketMove, Company.sector)
        .join(Company, Company.id == MarketMove.company_id)
        .filter(MarketMove.measurement_status == "ok")
        .filter(MarketMove.excess_move_pct.isnot(None))
        .filter(MarketMove.category.isnot(None))
        .all()
    )
    return [
        MoveFact(
            company_id=move.company_id,
            sector=sector,
            category=move.category,
            excess_move_pct=move.excess_move_pct,
        )
        for move, sector in rows
    ]


def _range_stats(moves: list[float]) -> dict:
    return {
        "n_events": len(moves),
        "min_excess_move_pct": min(moves),
        "median_excess_move_pct": median(moves),
        "max_excess_move_pct": max(moves),
    }


def compute_ranges(facts: list[MoveFact]) -> list[dict]:
    """Pure: facts in, range-row dicts out.

    COMPANY rows need EVENT_VOL_COMPANY_MIN_EVENTS; SECTOR pools need
    EVENT_VOL_SECTOR_MIN_EVENTS and include every company's measurements
    (the sector row describes the sector, not "the leftovers"). sector
    'other' or None pools nothing -- an absence of classification is not a
    peer group."""
    by_company: dict[tuple[int, str], list[float]] = defaultdict(list)
    by_sector: dict[tuple[str, str], list[float]] = defaultdict(list)
    for fact in facts:
        by_company[(fact.company_id, fact.category)].append(fact.excess_move_pct)
        if fact.sector and fact.sector != "other":
            by_sector[(fact.sector, fact.category)].append(fact.excess_move_pct)

    rows: list[dict] = []
    for (company_id, category), moves in sorted(by_company.items()):
        if len(moves) < config.EVENT_VOL_COMPANY_MIN_EVENTS:
            continue
        rows.append({
            "level": "COMPANY", "company_id": company_id, "sector": None,
            "category": category, **_range_stats(moves),
        })
    for (sector, category), moves in sorted(by_sector.items()):
        if len(moves) < config.EVENT_VOL_SECTOR_MIN_EVENTS:
            continue
        rows.append({
            "level": "SECTOR", "company_id": None, "sector": sector,
            "category": category, **_range_stats(moves),
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
