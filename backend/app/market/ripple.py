"""Level 2 ripple data: every OTHER measured/exposed company tied to an
alert (excluding the event's own peak, already shown at Level 0/1), grouped
by relationship type (docs/NEWS_IMPACT_APP_SPEC.md §2 Level 2, §3.1
RippleLink). A company with no real measured move renders as a flagged
EXPOSURE, never a fabricated impact number (spec: "ripple companies that
have not moved... show it as a flagged relationship with no number and no
score -- never a fabricated magnitude").

Also home to get_sector_peers_for_alert (Phase 7, Level 4's "sector peers"
discovery doorway) -- the same per-company row computation as ripple,
just filtered to one company's sector instead of grouped by relationship,
since both need the exact same intensity-normalization discipline against
this alert's companies.
"""
from sqlalchemy.orm import Session

from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.models import Alert, Company, ImpactEdge, MarketMove
from app.reasoning.ripple_relationship import is_exposure_only, relation_to_ripple_relationship


def _alert_company_rows(
    session: Session, alert: Alert, exclude_company_id: int, held_company_ids: set[int],
) -> list[dict]:
    """Every AlertCompany on ``alert`` other than ``exclude_company_id``,
    each: {ticker, name, sector, direction, excess_move_pct (float|None),
    intensity (dict|None), is_exposure_only (bool), in_my_holdings (bool)}.
    excess_move_pct/intensity are None whenever is_exposure_only is True --
    never a fabricated number for an unmeasured company. Sorted by
    intensity score descending; exposure-only entries (no score) sort
    last. Shared by compute_ripple_companies (adds `relationship`, groups
    by it) and get_sector_peers_for_alert (filters by `sector`) -- the one
    place this per-company computation lives.
    """
    moves_by_company_id = {
        m.company_id: m for m in session.query(MarketMove).filter_by(alert_id=alert.id).all()
    }
    ok_excess_values = [m.excess_move_pct for m in moves_by_company_id.values() if m.measurement_status == "ok"]
    breadth_score = compute_breadth_score(ok_excess_values)

    results = []
    for alert_company in alert.companies:
        if alert_company.company_id == exclude_company_id:
            continue
        company = alert_company.company
        move = moves_by_company_id.get(alert_company.company_id)
        status = move.measurement_status if move else None
        exposure_only = is_exposure_only(status)

        entry = {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "direction": alert_company.direction,
            "excess_move_pct": None,
            "intensity": None,
            "is_exposure_only": exposure_only,
            "in_my_holdings": alert_company.company_id in held_company_ids,
        }
        if not exposure_only and move is not None and move.excess_move_pct is not None:
            entry["excess_move_pct"] = move.excess_move_pct
            entry["intensity"] = _intensity_for_company_move(session, company, move, breadth_score)
        results.append(entry)

    results.sort(key=lambda r: r["intensity"]["score"] if r["intensity"] else -1, reverse=True)
    return results


def compute_ripple_companies(
    session: Session, alert: Alert, exclude_company_id: int, held_company_ids: set[int],
) -> list[dict]:
    """Returns one entry per AlertCompany on this alert OTHER than
    exclude_company_id (the event's peak, already shown at Level 0/1),
    each: {ticker, name, relationship, direction, excess_move_pct
    (float|None), intensity (dict|None), is_exposure_only (bool),
    in_my_holdings (bool)}. Sorted by intensity score descending;
    exposure-only entries (no score) sort last.
    """
    rows = _alert_company_rows(session, alert, exclude_company_id, held_company_ids)

    edges = session.query(ImpactEdge).filter_by(alert_id=alert.id).all()
    relation_by_company_id: dict[int, str] = {}
    for edge in edges:
        for company_id in (edge.to_company_id, edge.from_company_id):
            if company_id is not None and company_id not in relation_by_company_id:
                relation_by_company_id[company_id] = edge.relation

    ticker_to_company_id = {ac.company.ticker: ac.company_id for ac in alert.companies}
    results = []
    for row in rows:
        company_id = ticker_to_company_id[row["ticker"]]
        relationship = relation_to_ripple_relationship(relation_by_company_id.get(company_id, ""))
        results.append({**row, "relationship": relationship})
    return results


def get_sector_peers_for_alert(
    session: Session, alert: Alert, company: Company, held_company_ids: set[int],
) -> list[dict]:
    """Other companies measured/exposed within THIS alert that share
    ``company``'s sector (Level 4's "sector peers" discovery doorway,
    docs/NEWS_IMPACT_APP_SPEC.md §2, §9) -- never a peer's intensity
    borrowed from some other, unrelated event (spec §9: "same news swings
    them hardest" -- the ordering only means something within one event).
    Same row shape as _alert_company_rows minus `sector` (the caller
    already knows it -- it's the filter key).
    """
    rows = _alert_company_rows(session, alert, exclude_company_id=company.id, held_company_ids=held_company_ids)
    return [
        {k: v for k, v in row.items() if k != "sector"}
        for row in rows
        if row["sector"] == company.sector
    ]
