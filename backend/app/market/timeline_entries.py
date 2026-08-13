"""Level 3 timeline data: every TimelineEffect row for an alert, in a
fixed horizon order (docs/NEWS_IMPACT_APP_SPEC.md §2 Level 3, §3.1). Only
horizons the LLM refinement layer found genuine content for exist as rows
at all (see app.analysis.refinement.generate_timeline_effects) -- nothing
here decides whether a horizon "has content", it only orders what already
exists.
"""
from sqlalchemy.orm import Session

from app.models import Alert, TimelineEffect

HORIZON_ORDER = ["TODAY", "DAYS", "WEEKS", "MONTHS", "QUARTERS"]


def get_timeline_entries(session: Session, alert: Alert) -> list[dict]:
    """One entry per horizon, newest generation wins. refine_alert used to
    APPEND rows on every re-run (no delete-before-insert until 2026-08-12)
    and reanalyze never deleted them, so older alerts carry stacked
    generations of near-identical entries -- collapsing at read time keeps
    every historical alert clean without a data migration. Highest id =
    most recent generation."""
    rows = session.query(TimelineEffect).filter_by(alert_id=alert.id).all()
    latest_by_horizon: dict[str, TimelineEffect] = {}
    for row in sorted(rows, key=lambda r: r.id):
        latest_by_horizon[row.horizon] = row
    ordered = sorted(
        latest_by_horizon.values(),
        key=lambda r: HORIZON_ORDER.index(r.horizon) if r.horizon in HORIZON_ORDER else len(HORIZON_ORDER),
    )
    return [{"horizon": r.horizon, "description": r.description} for r in ordered]
