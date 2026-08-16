"""TASK 1.5 -- coverage and metrics.

Two questions a ledger owner must be able to answer without importing the
app: how much of each sector is tagged for each exposure, and how old the
ledger is getting.

  `exposure_coverage` (a VIEW, migration 0012) answers the first.
  `age_alert` / `metrics_text` answer the second.

TWO ADAPTATIONS, both recorded in the Phase 1 report:

1. MEDIAN AGE IN PYTHON. The DoD asks the coverage view for a median
   exposure age; SQLite has no median aggregate and no window-function
   percentile. The view therefore carries counts and market-cap share, and
   `coverage_rows()` computes the median over the same rows in Python.

2. PROMETHEUS TEXT, HAND-ROLLED. This repo has no `prometheus_client`
   (Phase 0's firewall metric made the same substitution). `metrics_text()`
   emits the exposition format directly, and the ledger UI serves it at
   /ledger/metrics.

An EMPTY ledger reports NO coverage rows and NO age -- never "0% of every
sector" and never "age 0". A number we have not measured is not zero.
"""
from datetime import date
from statistics import median
from typing import Sequence

from sqlalchemy import text

from app.ledger.freshness import p90_age_alert_days


def _rows(result) -> list[dict]:
    return [dict(row) for row in result.mappings().all()]


def coverage_rows(session, *, as_of: date) -> list[dict]:
    """Per (sector, exposure_tag): companies tagged, % of sector market cap
    tagged, median exposure age in days."""
    rows = _rows(session.execute(text(
        "SELECT sector, exposure_tag, companies_tagged, tagged_market_cap, "
        "       sector_market_cap FROM exposure_coverage "
        "ORDER BY sector ASC, exposure_tag ASC")))
    if not rows:
        return []

    ages: dict[tuple, list[int]] = {}
    for sector, tag, age in session.execute(text(
            "SELECT c.sector, e.exposure_tag, "
            "       CAST(julianday(:as_of) - julianday(e.as_of_date) AS INTEGER) "
            "FROM company_exposure e JOIN companies c ON c.id = e.company_id"),
            {"as_of": as_of.isoformat()}).all():
        ages.setdefault((sector, tag), []).append(int(age))

    out = []
    for row in rows:
        sector_cap = float(row["sector_market_cap"] or 0)
        tagged_cap = float(row["tagged_market_cap"] or 0)
        bucket = ages.get((row["sector"], row["exposure_tag"]), [])
        out.append({
            "sector": row["sector"],
            "exposure_tag": row["exposure_tag"],
            "companies_tagged": int(row["companies_tagged"]),
            "tagged_market_cap": tagged_cap,
            "sector_market_cap": sector_cap,
            # None, not 0.0: a sector whose market caps we do not have is a
            # sector whose coverage we cannot express as a percentage.
            "pct_sector_market_cap_tagged": (
                round(100.0 * tagged_cap / sector_cap, 4) if sector_cap else None),
            "median_exposure_age_days": (
                int(median(sorted(bucket))) if bucket else None),
        })
    return out


def extractor_quality(session) -> list[dict]:
    """Task 1.4: approve rate and edit rate per extractor version. Falling
    precision is the signal that an extraction prompt regressed."""
    out = []
    for row in _rows(session.execute(text(
            "SELECT * FROM extractor_quality ORDER BY extractor ASC"))):
        proposed = int(row["proposed"] or 0)
        approved = int(row["approved"] or 0)
        edited = int(row["edited"] or 0)
        out.append({
            "extractor": row["extractor"],
            "extractor_version": row["extractor_version"],
            "proposed": proposed,
            "approved": approved,
            "edited": edited,
            "rejected": int(row["rejected"] or 0),
            "unverbatim": int(row["unverbatim"] or 0),
            "pending": int(row["pending"] or 0),
            "approve_rate": round(approved / proposed, 6) if proposed else None,
            # Of the approvals, how many needed correcting.
            "edit_rate": round(edited / approved, 6) if approved else None,
        })
    return out


def _percentile(values: Sequence[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return int(ordered[index])


def ledger_stats(session, *, as_of: date) -> dict:
    from app.ledger.staleness import exposure_ages

    ages = exposure_ages(session, as_of=as_of)
    return {
        "exposure_rows": int(session.execute(
            text("SELECT count(*) FROM company_exposure")).scalar() or 0),
        "stale_rows": int(session.execute(text(
            "SELECT count(*) FROM company_exposure WHERE "
            "julianday(:as_of) - julianday(as_of_date) > freshness_days"),
            {"as_of": as_of.isoformat()}).scalar() or 0),
        "pending_proposals": int(session.execute(text(
            "SELECT count(*) FROM exposure_proposal "
            "WHERE status = 'PENDING_REVIEW'")).scalar() or 0),
        "unverbatim_proposals": int(session.execute(text(
            "SELECT count(*) FROM exposure_proposal "
            "WHERE status = 'REJECTED_UNVERBATIM'")).scalar() or 0),
        "age_p50_days": _percentile(ages, 0.50),
        "age_p90_days": _percentile(ages, 0.90),
        "companies_tagged": int(session.execute(text(
            "SELECT count(DISTINCT company_id) FROM company_exposure")).scalar() or 0),
    }


def age_alert(session, *, as_of: date) -> str | None:
    """Task 1.5's alert. Returns a message when p90 exposure age has crossed
    the configured threshold, else None."""
    stats = ledger_stats(session, as_of=as_of)
    threshold = p90_age_alert_days()
    p90 = stats["age_p90_days"]
    if p90 is None or p90 <= threshold:
        return None
    return (f"ledger ageing: p90 exposure age is {p90} days, over the "
            f"{threshold}-day threshold in config/freshness.yaml")


def metrics_text(session, *, as_of: date) -> str:
    """Prometheus exposition format, hand-rolled (see the module docstring).
    A metric with no measurement is OMITTED, never emitted as 0."""
    stats = ledger_stats(session, as_of=as_of)
    lines = [
        "# HELP newsflo_ledger_exposure_rows Reviewed exposure rows in the ledger.",
        "# TYPE newsflo_ledger_exposure_rows gauge",
        f"newsflo_ledger_exposure_rows {stats['exposure_rows']}",
        "# HELP newsflo_ledger_stale_exposure_rows Exposure rows past freshness_days.",
        "# TYPE newsflo_ledger_stale_exposure_rows gauge",
        f"newsflo_ledger_stale_exposure_rows {stats['stale_rows']}",
        "# HELP newsflo_ledger_companies_tagged Companies with at least one exposure.",
        "# TYPE newsflo_ledger_companies_tagged gauge",
        f"newsflo_ledger_companies_tagged {stats['companies_tagged']}",
        "# HELP newsflo_ledger_pending_proposals Proposals awaiting human review.",
        "# TYPE newsflo_ledger_pending_proposals gauge",
        f"newsflo_ledger_pending_proposals {stats['pending_proposals']}",
        "# HELP newsflo_ledger_unverbatim_proposals Proposals the verbatim gate discarded.",
        "# TYPE newsflo_ledger_unverbatim_proposals gauge",
        f"newsflo_ledger_unverbatim_proposals {stats['unverbatim_proposals']}",
    ]
    if stats["age_p50_days"] is not None:
        lines += [
            "# HELP newsflo_ledger_exposure_age_p50_days Median exposure age.",
            "# TYPE newsflo_ledger_exposure_age_p50_days gauge",
            f"newsflo_ledger_exposure_age_p50_days {stats['age_p50_days']}",
        ]
    if stats["age_p90_days"] is not None:
        lines += [
            "# HELP newsflo_ledger_exposure_age_p90_days 90th-percentile exposure age.",
            "# TYPE newsflo_ledger_exposure_age_p90_days gauge",
            f"newsflo_ledger_exposure_age_p90_days {stats['age_p90_days']}",
        ]
    return "\n".join(lines) + "\n"
