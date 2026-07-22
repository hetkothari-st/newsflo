"""Read-time measurement rollup for one Alert (news event): peak-company
excess/intensity, event verdict, and breadth -- everything Level 0/1 of the
five-level UI needs (docs/NEWS_IMPACT_APP_SPEC.md §2, §4), computed fresh
from MarketMove rows every call, never persisted. Feeds
app.routers.feed_v2 only.
"""
from sqlalchemy.orm import Session

from app.market.breadth import compute_breadth_score
from app.market.intensity import compute_intensity
from app.market.sector_indices import is_fallback_benchmark
from app.market.verdict import compute_verdict
from app.models import Alert, MarketMove


def compute_alert_measurement(session: Session, alert: Alert) -> dict | None:
    """Returns None if this alert has no company with a real measured
    excess move (measurement_status == "ok") -- an alert with nothing
    measured has no headline number to show and must be omitted from the
    Level 0 feed entirely (spec Ground Rules: never fabricate, omit
    rather than invent).

    Otherwise returns a dict with: excess_move_pct, direction
    ("bullish"|"bearish"), raw_move_pct, sector_move_pct, volume_multiple
    (float | None), benchmark_ticker, is_fallback_benchmark (bool),
    peak_ticker, peak_company_name, verdict (str), intensity
    ({"score","band","components"}), breadth_score (int).

    "Peak" is whichever measured company has the largest |excess_move_pct|
    -- the event's own headline reaction. is_unconfirmed is hardcoded False
    (the rumor/denial LLM classifier is a later phase) -- verdict can only
    resolve to COMPANY_SPECIFIC/SECTOR_WIDE until then.
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
    volume_values = [m.volume_multiple for m in moves if m.volume_multiple is not None]
    breadth_score = compute_breadth_score(excess_values)

    intensity = compute_intensity(
        excess_move_pct=peak.excess_move_pct,
        excess_peer_group=excess_values,
        volume_multiple=peak.volume_multiple or 0.0,
        volume_peer_group=volume_values or [peak.volume_multiple or 0.0],
        breadth_score=breadth_score,
    )
    verdict = compute_verdict(is_unconfirmed=False, excess_move_pct=peak.excess_move_pct)

    peak_alert_company = next(ac for ac in alert.companies if ac.company_id == peak.company_id)
    peak_company = peak_alert_company.company

    return {
        "excess_move_pct": peak.excess_move_pct,
        "direction": "bullish" if peak.excess_move_pct >= 0 else "bearish",
        "raw_move_pct": peak.raw_move_pct,
        "sector_move_pct": peak.sector_move_pct,
        "volume_multiple": peak.volume_multiple,
        "benchmark_ticker": peak.benchmark_ticker,
        "is_fallback_benchmark": is_fallback_benchmark(peak_company.sector),
        "peak_ticker": peak_company.ticker,
        "peak_company_name": peak_company.name,
        "verdict": verdict,
        "intensity": intensity,
        "breadth_score": breadth_score,
    }
