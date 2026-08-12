"""Read-time measurement rollup for one Alert (news event): peak-company
excess/intensity, event verdict, and breadth -- everything Level 0/1 of the
five-level UI needs (docs/NEWS_IMPACT_APP_SPEC.md §2, §4), computed fresh
from MarketMove rows every call, never persisted. Feeds
app.routers.feed_v2 only.
"""
from sqlalchemy.orm import Session

from app.companies.branding import logo_url
from app.ist_time import day_utc_window, today_ist
from app.market.breadth import compute_breadth_score
from app.market.intensity import compute_intensity
from app.market.measure import classify_reaction
from app.market.sector_indices import NIFTY50_TICKER, is_fallback_benchmark
from app.market.verdict import compute_verdict
from app.models import Alert, Company, MarketMove


def _sector_peer_moves(session: Session, sector: str) -> list[MarketMove]:
    """Every measured (status='ok') MarketMove today for companies in the
    given sector, across ALL of today's alerts -- not just one event. This
    is the real comparison population for intensity's within-sector
    normalization (spec §4.2): a single-company event's own excess move is
    trivially the max of a group containing only itself, so a peer group
    must reach beyond one event to be a meaningful comparison, or every
    single-company alert scores 100/High regardless of real magnitude.
    """
    start_utc, end_utc = day_utc_window(today_ist())
    return (
        session.query(MarketMove)
        .join(Company, MarketMove.company_id == Company.id)
        .join(Alert, MarketMove.alert_id == Alert.id)
        .filter(
            Company.sector == sector,
            MarketMove.measurement_status == "ok",
            Alert.created_at >= start_utc,
            Alert.created_at < end_utc,
        )
        .all()
    )


def _intensity_for_company_move(session: Session, company: Company, move: MarketMove, breadth_score: int) -> dict:
    """Compute intensity for one (company, move) pair, normalized against
    every measured company in the same sector across today's alerts (see
    _sector_peer_moves). Shared by compute_alert_measurement (for the
    event's peak company) and app.market.ripple.compute_ripple_companies
    (for every other measured company in the event's ripple) -- the exact
    same normalization discipline applies to both, so this is the one
    place that logic lives.

    Six-signal blend (spec v2 §4.2): excess, volume, delivery,
    materiality, vol_norm (fundamental is advisory-tier, not wired).
    Signals a row genuinely lacks (delivery has no data source yet; old
    rows predate materiality/vol_norm) get their weight renormalized away
    inside compute_intensity -- never counted as zero. ``breadth_score``
    is no longer an intensity component (it's an event-level metric,
    spec §4.4) -- parameter kept so callers stay unchanged.
    """
    del breadth_score  # event-level metric now, not an intensity signal (spec v2 §4.2)
    sector_moves = _sector_peer_moves(session, company.sector)
    excess_peer_group = [m.excess_move_pct for m in sector_moves] or [move.excess_move_pct]
    sector_volume_values = [m.volume_multiple for m in sector_moves if m.volume_multiple is not None]
    materiality_values = [m.materiality for m in sector_moves if m.materiality is not None]
    vol_norm_values = [m.vol_normalized for m in sector_moves if m.vol_normalized is not None]
    return compute_intensity(
        excess_move_pct=move.excess_move_pct,
        excess_peer_group=excess_peer_group,
        volume_multiple=move.volume_multiple,
        volume_peer_group=sector_volume_values or None,
        delivery_pct=move.delivery_pct,
        materiality=move.materiality,
        materiality_peer_group=materiality_values or None,
        vol_normalized=move.vol_normalized,
        vol_norm_peer_group=vol_norm_values or None,
    )


def compute_alert_measurement(session: Session, alert: Alert) -> dict | None:
    """Returns None if this alert has no company with a real measured
    excess move (measurement_status == "ok") -- an alert with nothing
    measured has no headline number to show and must be omitted from the
    Level 0 feed entirely (spec Ground Rules: never fabricate, omit
    rather than invent). Also returns None if a measured MarketMove exists
    but no AlertCompany row on `alert` matches its company_id -- an orphaned
    MarketMove (e.g. left behind by a script that deleted AlertCompany rows
    without also deleting their MarketMove rows) is exactly as unusable as
    no measurement at all: there is no company row to name as the peak, so
    the peak is meaningless and this degrades the same way as the
    `not moves` case above rather than raising.

    Otherwise returns a dict with: excess_move_pct, direction
    ("bullish"|"bearish"), raw_move_pct, sector_move_pct, volume_multiple
    (float | None), benchmark_ticker, is_fallback_benchmark (bool),
    peak_ticker, peak_company_id, peak_company_name, verdict (str),
    intensity ({"score","band","components"}), breadth_score (int).

    "Peak" is whichever measured company has the largest |excess_move_pct|
    -- the event's own headline reaction. breadth_score is event-scoped
    (spec §4.4: how widely THIS event rippled). is_unconfirmed comes from
    Alert.is_unconfirmed (refinement LLM rumor/denial classification,
    spec v2 §4.3); NULL reads as confirmed.
    """
    moves = (
        session.query(MarketMove)
        .filter(MarketMove.alert_id == alert.id, MarketMove.measurement_status == "ok")
        .all()
    )
    if not moves:
        return None

    peak = max(moves, key=lambda m: abs(m.excess_move_pct))
    excess_values = [m.excess_move_pct for m in moves]
    breadth_score = compute_breadth_score(excess_values)

    peak_alert_company = next((ac for ac in alert.companies if ac.company_id == peak.company_id), None)
    if peak_alert_company is None:
        return None
    peak_company = peak_alert_company.company

    intensity = _intensity_for_company_move(session, peak_company, peak, breadth_score)
    # is_unconfirmed comes from the refinement LLM's rumor/denial
    # classification (spec v2 §4.3); NULL (pre-feature alerts) reads as
    # confirmed.
    verdict = compute_verdict(
        is_unconfirmed=bool(alert.is_unconfirmed), excess_move_pct=peak.excess_move_pct,
    )

    return {
        "excess_move_pct": peak.excess_move_pct,
        "direction": "bullish" if peak.excess_move_pct >= 0 else "bearish",
        "raw_move_pct": peak.raw_move_pct,
        "sector_move_pct": peak.sector_move_pct,
        "volume_multiple": peak.volume_multiple,
        "benchmark_ticker": peak.benchmark_ticker,
        # Honest flag (2026-08-12 fix): derived from the benchmark ACTUALLY
        # used, not from the sector's default mapping -- the stale-sector-
        # index degrade (app.market.measure) can swap a sector-indexed
        # company onto ^NSEI, and the sector-derived flag then lied
        # ("vs sector index") about a Nifty-measured move.
        "is_fallback_benchmark": (
            peak.benchmark_ticker == NIFTY50_TICKER
            or is_fallback_benchmark(peak_company.sector)
        ),
        "peak_ticker": peak_company.ticker,
        "peak_company_id": peak_company.id,
        "peak_company_name": peak_company.name,
        "verdict": verdict,
        "intensity": intensity,
        "breadth_score": breadth_score,
        # Independent market-reaction object (spec §20/§22): classified
        # through the dead zone, never a re-labeling of fundamentals.
        "market_reaction": {
            "status": "ok",
            "direction": classify_reaction(peak.excess_move_pct),
            "bar_complete": peak.bar_complete,
        },
    }


def compute_impact_companies(session: Session, alert: Alert) -> list[dict]:
    """Every directly-affected company for this alert (spec §1 layer 2,
    "Impact core") -- AlertCompany.impact_level == "direct" AND a real
    measured excess move (measurement_status == "ok"). Distinct from
    compute_alert_measurement's single "peak" company: this returns the
    FULL set (peak included), each with its own excess_move_pct, direction,
    and why (refine_alert-populated causal text, None if that LLM call
    never succeeded -- never fabricated). indirect_l1/indirect_l2 companies
    are excluded -- those are cascade companies, surfaced only by
    app.market.ripple.compute_ripple_companies, not here. Note:
    compute_ripple_companies is NOT scoped to indirect companies only --
    it includes every non-peak AlertCompany (direct and indirect), so a
    non-peak direct company appears in both this function's result AND in
    ripple. That overlap is intentional, not a bug: two lenses on the same
    company (this = named + why, ripple = grouped by relationship type),
    not deduplicated. Sorted by |excess_move_pct| descending, same
    ordering discipline as the rest of this module. Never raises; returns
    [] when nothing qualifies (omit rather than fabricate).
    """
    moves_by_company_id = {
        m.company_id: m
        for m in session.query(MarketMove)
        .filter(MarketMove.alert_id == alert.id, MarketMove.measurement_status == "ok")
        .all()
    }

    results = []
    for alert_company in alert.companies:
        if alert_company.impact_level != "direct":
            continue
        move = moves_by_company_id.get(alert_company.company_id)
        if move is None or move.excess_move_pct is None:
            continue
        results.append({
            "ticker": alert_company.company.ticker,
            "name": alert_company.company.name,
            "direction": alert_company.direction,
            "excess_move_pct": move.excess_move_pct,
            "why": alert_company.why,
            "logo_url": logo_url(alert_company.company),
        })

    results.sort(key=lambda r: abs(r["excess_move_pct"]), reverse=True)
    return results
