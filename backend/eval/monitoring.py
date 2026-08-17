"""TASK 7.4 -- production monitoring, as functions over the database.

THIS REPO HAS NO METRICS STACK. No `prometheus_client`, no Grafana, no
alertmanager, nothing that scrapes or pages (established in Phases 0-5;
Phase 0's firewall counter and Phase 1's coverage metrics both hand-rolled
the exposition format for the same reason). Building one is not this phase's
work and pretending to have one would be worse than saying so, so:

  * every signal in the Task 7.4 table is computed HERE, as a function over
    a connection, and can be read today at `/monitoring.json` on the ledger
    console;
  * DASHBOARDS AND ALERTING ARE DEFERRED, with an owner, in DATA_GAPS
    section 11. `alert` on a signal is a computed flag, not a page.

THE RULE THIS MODULE OBEYS: a signal that cannot be computed says so.

An exposure staleness p90 over an empty ledger is not "0 days, healthy" --
it is "there is nothing to measure", and a dashboard that renders the first
is a dashboard that watches the ledger rot. So a RATE or a DISTRIBUTION over
an empty input returns `value=None` with a `refusal` naming what is missing.
A COUNT over a table that exists is different: zero open divergence reviews
is a measurement, and it is reported as 0.

THIS MODULE READS. It executes nothing but SELECT, holds no session, and a
test scans it for any write verb.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Sequence

import sqlalchemy as sa

from app.ledger.coverage import _percentile
from app.ledger.freshness import p90_age_alert_days
from app.ledger.staleness import exposure_ages

#: The stages that spend V5 model budget. `FALSIFIER` is Phase 6's adversary
#: (the only frontier caller); `FIREWALL_JUDGE` is the stage-2 entailment
#: judge. Deliberately NOT the V4 stage names in `llm_call_usage`: a V4
#: `impact_whys` call is not a V5 frontier call and counting it would make
#: the section 18 budget look breached by a system that is not running.
V5_LLM_STAGES = ("FALSIFIER", "FIREWALL_JUDGE")

#: p90 / p95, as integers -- the percentile helper takes a fraction, and a
#: bare 0.9 in this file would be a threshold nobody named.
P90 = 90
P95 = 95
PERCENT = 100

NO_MATERIAL_IMPACT = "NO_MATERIAL_IMPACT"


@dataclass(frozen=True)
class MonitoringSignal:
    name: str
    value: Any = None
    unit: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)
    #: why there is no value. None means there IS one.
    refusal: str | None = None
    #: a computed flag, not a page. Nothing in this repo delivers a page.
    alert: bool = False
    #: something worth reading even though a value exists.
    note: str = ""

    @property
    def refusal_or_note(self) -> str:
        return self.refusal or self.note


def _count(conn: sa.Connection, sql: str, **params) -> int:
    return int(conn.execute(sa.text(sql), params).scalar() or 0)


# ---------------------------------------------------------------------------
# the nine signals
# ---------------------------------------------------------------------------

def firewall_deletion_rate(conn: sa.Connection, *,
                           sentences_total: int | None = None) -> MonitoringSignal:
    """"spike = model or prompt regression".

    THE DENOMINATOR IS NOT IN THE DATABASE. `firewall_deletion` stores the
    sentences that were DELETED; nothing persists the number examined (the
    firewall counts those in-process, and `app/output/firewall.py::
    metrics_text` exposes them per-process). A rate computed from the
    deletions alone would be 1.0 forever, which would look like a
    catastrophic regression on a perfectly healthy system.

    So the count is reported, the rate is REFUSED unless a caller supplies
    the denominator it measured, and the missing counter is DATA_GAPS
    section 11.
    """
    rows = conn.execute(sa.text(
        "SELECT stage, COUNT(*) FROM firewall_deletion GROUP BY stage")).all()
    by_stage = {str(stage): int(count) for stage, count in rows}
    deletions = sum(by_stage.values())
    detail = {"deletions": deletions, "by_stage": by_stage}
    if sentences_total is None:
        return MonitoringSignal(
            "firewall_deletion_rate", None, "rate", detail,
            refusal=("the firewall persists DELETIONS but not the number of "
                     "sentences examined, so a deletion RATE cannot be computed "
                     "from the database. Pass sentences_total= to compute one, "
                     "or persist the counter (DATA_GAPS section 11). "
                     f"Deletions recorded so far: {deletions}."))
    if not sentences_total:
        return MonitoringSignal(
            "firewall_deletion_rate", None, "rate", detail,
            refusal="sentences_total is zero: no prose was examined.")
    return MonitoringSignal("firewall_deletion_rate",
                            deletions / sentences_total, "rate", detail,
                            alert=bool(deletions))


def divergence_queue_volume(conn: sa.Connection) -> MonitoringSignal:
    """"spike = broken channel, or alpha". A COUNT over a table that exists,
    so zero is a measurement and not a silence."""
    rows = conn.execute(sa.text(
        "SELECT kind, COUNT(*) FROM divergence_review WHERE status = 'OPEN' "
        "GROUP BY kind")).all()
    by_kind = {str(kind): int(count) for kind, count in rows}
    return MonitoringSignal("divergence_queue_volume", sum(by_kind.values()),
                            "reviews", {"by_kind": by_kind})


def exposure_staleness_p90(conn: sa.Connection, *, as_of: date) -> MonitoringSignal:
    """"the ledger rots silently; alert at p90".

    The percentile and the alert threshold are Phase 1's, imported rather
    than restated: two definitions of p90 in one repo would eventually
    disagree, and the disagreement would show up as a phantom alert.
    """
    ages = exposure_ages(conn, as_of=as_of)
    if not ages:
        return MonitoringSignal(
            "exposure_staleness_p90", None, "days", {"rows": 0},
            refusal=("the exposure ledger is EMPTY (DATA_GAPS section 5), so "
                     "there is no age distribution. Not 0 days -- 0 days would "
                     "read as a perfectly fresh ledger."))
    threshold = p90_age_alert_days()
    value = _percentile(ages, P90 / PERCENT)
    return MonitoringSignal(
        "exposure_staleness_p90", value, "days",
        {"rows": len(ages), "p50_days": _percentile(ages, 50 / PERCENT),
         "alert_threshold_days": threshold},
        alert=value is not None and value > threshold)


def policy_state_staleness(conn: sa.Connection, *, as_of: date) -> MonitoringSignal:
    """"a stale levy rate is a correctness bug".

    Not a data-hygiene note: a regime state past its own freshness window is
    a claim about today that nobody is maintaining, and the sensitivity
    engine will apply it anyway.
    """
    rows = conn.execute(sa.text(
        "SELECT state_key, "
        "CAST(julianday(:as_of) - julianday(as_of) AS INTEGER) AS age, "
        "freshness_days FROM policy_state"), {"as_of": as_of.isoformat()}).all()
    if not rows:
        return MonitoringSignal(
            "policy_state_staleness", None, "states", {"rows": 0},
            refusal=("no regime state is registered (DATA_GAPS section 8), so "
                     "none can be stale. Not 0 -- there is nothing being "
                     "tracked, which is a different situation from everything "
                     "being fresh."))
    stale = sorted(str(key) for key, age, window in rows
                   if age is not None and age > int(window))
    return MonitoringSignal(
        "policy_state_staleness", len(stale), "states",
        {"rows": len(rows), "stale_keys": stale}, alert=bool(stale))


def calibration_drift(conn: sa.Connection) -> MonitoringSignal:
    """"refit quarterly" -- of a model that has never been fitted.

    Phase 5 shipped calibration DISABLED and structurally locked, so there is
    no fitted model, no monthly ECE and no drift. Reporting a drift of zero
    would say the model is stable; it does not exist.
    """
    models = _count(conn, "SELECT COUNT(*) FROM calibration_model")
    return MonitoringSignal(
        "calibration_drift", None, "ece_delta", {"calibration_models": models},
        refusal=("calibration is DISABLED and structurally locked (Phase 5): "
                 f"{models} fitted model(s) exist and no record carries a "
                 "calibrated probability, so month-over-month drift is "
                 "undefined. DATA_GAPS section 9.4."))


def rejection_reason_histogram(conn: sa.Connection) -> MonitoringSignal:
    """"NO_MATERIAL_IMPACT collapsing toward zero = misconfigured threshold".

    The phase file's own warning, computed: when candidates are being
    rejected but essentially none of them for want of material impact, a
    materiality threshold has almost certainly been loosened, and the first
    visible symptom is a rise in published companies rather than an error.
    """
    rows = conn.execute(sa.text(
        "SELECT rejection_reason, COUNT(*) FROM company_impact "
        "WHERE publication_tier = 'REJECTED' GROUP BY rejection_reason")).all()
    published = _count(conn, "SELECT COUNT(*) FROM company_impact "
                             "WHERE publication_tier <> 'REJECTED'")
    histogram = {str(reason or "UNSTATED"): int(count) for reason, count in rows}
    if not histogram and not published:
        return MonitoringSignal(
            "rejection_reason_histogram", None, "records",
            {"published": 0, "rejected": 0},
            refusal=("no canonical record exists: the V5 path has never been "
                     "served (DATA_GAPS section 10.3), so there is no rejection "
                     "distribution to watch."))
    rejected = sum(histogram.values())
    collapsed = bool(rejected) and not histogram.get(NO_MATERIAL_IMPACT)
    note = ""
    if collapsed:
        note = (f"{rejected} rejection(s) and NOT ONE for "
                f"{NO_MATERIAL_IMPACT}. The phase file names this exactly: a "
                f"materiality threshold has probably been misconfigured, and "
                f"the symptom is more published companies, not an error.")
    return MonitoringSignal(
        "rejection_reason_histogram", histogram, "records",
        {"published": published, "rejected": rejected},
        alert=collapsed, note=note)


def coverage_gap_depth(conn: sa.Connection) -> MonitoringSignal:
    """"should trend down". A COUNT over a table that exists: zero open gaps
    is a measurement."""
    rows = conn.execute(sa.text(
        "SELECT status, COUNT(*) FROM coverage_gap GROUP BY status")).all()
    by_status = {str(status): int(count) for status, count in rows}
    return MonitoringSignal("coverage_gap_depth", by_status.get("OPEN", 0),
                            "gaps", {"by_status": by_status})


def publish_latency_p95(conn: sa.Connection) -> MonitoringSignal:
    """"the product promise" -- of a path nothing serves yet.

    Spec section 17.2 gates p95 publish latency at 90 seconds. Nothing times
    the V5 path because nothing runs it in production (the canonical record
    set is written in parallel and served to nobody), so there are no
    durations. A p95 of zero would say the promise is comfortably met.
    """
    return MonitoringSignal(
        "publish_latency_p95", None, "seconds", {"samples": 0},
        refusal=("nothing times the V5 publish path: it has no serving path "
                 f"and no stored duration, so p{P95} latency is unmeasured. "
                 "DATA_GAPS sections 9.6 and 11."))


def frontier_calls_per_event(conn: sa.Connection) -> MonitoringSignal:
    """"cost control; deterministic layers must eliminate >= 90% of
    candidates pre-LLM".

    Counted over V5 STAGES ONLY. The `llm_call_usage` table is full of V4
    calls; including them would measure a different system and would make the
    section 18 budget look breached by a pipeline that never ran.
    """
    placeholders = ", ".join(f":s{i}" for i in range(len(V5_LLM_STAGES)))
    params = {f"s{i}": stage for i, stage in enumerate(V5_LLM_STAGES)}
    row = conn.execute(sa.text(
        f"SELECT COUNT(*), COUNT(DISTINCT article_id) FROM llm_call_usage "
        f"WHERE stage IN ({placeholders}) "
        f"AND (cache_hit IS NULL OR cache_hit = 0)"), params).first()
    calls, events = (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)
    detail = {"calls": calls, "events": events,
              "stages_counted": list(V5_LLM_STAGES)}
    if not events:
        return MonitoringSignal(
            "frontier_calls_per_event", None, "calls_per_event", detail,
            refusal=("no V5 model call has ever been recorded: the falsifier "
                     "is deliberately unwired and the firewall's stage-2 judge "
                     "is never constructed (DATA_GAPS sections 10.2 and 10.3). "
                     "Not 0 calls per event -- 0 would read as a triumph of "
                     "cost control."))
    return MonitoringSignal("frontier_calls_per_event", calls / events,
                            "calls_per_event", detail)


# ---------------------------------------------------------------------------
# the whole board
# ---------------------------------------------------------------------------

def all_signals(conn: sa.Connection, *, as_of: date) -> tuple[MonitoringSignal, ...]:
    """Every signal in Task 7.4's table, in the order the table lists them."""
    return (
        firewall_deletion_rate(conn),
        divergence_queue_volume(conn),
        exposure_staleness_p90(conn, as_of=as_of),
        policy_state_staleness(conn, as_of=as_of),
        calibration_drift(conn),
        rejection_reason_histogram(conn),
        coverage_gap_depth(conn),
        publish_latency_p95(conn),
        frontier_calls_per_event(conn),
    )


def as_json(signals: Sequence[MonitoringSignal]) -> list[dict[str, Any]]:
    """JSON-safe, and the `refusal` key is ALWAYS present.

    A serializer that omitted it when null would let a client render `value`
    alone and never learn that a null means "unmeasured" rather than "zero".
    """
    return [{"name": s.name, "value": s.value, "unit": s.unit,
             "detail": dict(s.detail), "refusal": s.refusal, "alert": s.alert,
             "note": s.note}
            for s in signals]


def alerting_signals(signals: Sequence[MonitoringSignal]) -> tuple[str, ...]:
    return tuple(s.name for s in signals if s.alert)
