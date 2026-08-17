"""TASK 7.4 tests -- production monitoring, as functions over the database.

THIS REPO HAS NO METRICS STACK (established in Phases 0-5: no
`prometheus_client`, no Grafana, no alertmanager). Dashboards and alerting
are therefore DEFERRED with an owner in DATA_GAPS section 11, and what ships
is every signal in the Task 7.4 table computed as a function, plus a
read-only JSON route on the ledger console so a human can read them today.

THE RULE THE WHOLE FILE ENFORCES: a signal that cannot be computed says so.
An exposure staleness p90 over an empty ledger is not "0 days, healthy" --
it is "nothing to measure", and a dashboard that renders the first is a
dashboard that hides the ledger rotting. Every signal is tested twice: once
on an empty database (refusal, with a reason) and once on fixture rows
(a number, hand-checked).

A COUNT over an existing table is different from a RATE over an empty
denominator, and the tests below insist on that distinction: zero open
divergence reviews is a MEASUREMENT; a deletion rate with no sentences is
not.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from tests.phase7.conftest import FIXTURE_NOW, FIXTURE_TODAY

SIGNAL_NAMES = (
    "firewall_deletion_rate",
    "divergence_queue_volume",
    "exposure_staleness_p90",
    "policy_state_staleness",
    "calibration_drift",
    "rejection_reason_histogram",
    "coverage_gap_depth",
    "publish_latency_p95",
    "frontier_calls_per_event",
    # M-1: rung 3 is not rung 4. The frontier budget is the one section 18
    # gates, but small-model spend still has to be visible or it becomes the
    # place cost hides.
    "small_calls_per_event",
)


# ---------------------------------------------------------------------------
# every signal in the phase file's table exists
# ---------------------------------------------------------------------------

def test_every_signal_in_the_task_table_is_computed(phase7_engine):
    from eval.monitoring import all_signals

    with phase7_engine.connect() as conn:
        signals = all_signals(conn, as_of=FIXTURE_TODAY)
    assert tuple(s.name for s in signals) == SIGNAL_NAMES


def test_every_signal_on_an_empty_database_refuses_with_a_reason(phase7_engine):
    """Nine signals, nine honest silences. Not one 0.0 that reads as health."""
    from eval.monitoring import all_signals

    with phase7_engine.connect() as conn:
        signals = {s.name: s for s in all_signals(conn, as_of=FIXTURE_TODAY)}

    # rates and distributions: nothing to measure
    for name in ("firewall_deletion_rate", "exposure_staleness_p90",
                 "policy_state_staleness", "calibration_drift",
                 "rejection_reason_histogram", "publish_latency_p95",
                 "frontier_calls_per_event", "small_calls_per_event"):
        assert signals[name].value is None, name
        assert signals[name].refusal, name

    # counts over tables that exist: zero is a real measurement
    for name in ("divergence_queue_volume", "coverage_gap_depth"):
        assert signals[name].value == 0, name
        assert signals[name].refusal is None, name


def test_the_json_shape_never_hides_a_refusal(phase7_engine):
    from eval.monitoring import all_signals, as_json

    with phase7_engine.connect() as conn:
        payload = as_json(all_signals(conn, as_of=FIXTURE_TODAY))
    assert all("refusal" in entry for entry in payload)
    assert any(entry["refusal"] for entry in payload)


# ---------------------------------------------------------------------------
# each signal, measured
# ---------------------------------------------------------------------------

def test_divergence_queue_volume_counts_open_reviews_only(phase7_engine):
    from eval.monitoring import divergence_queue_volume

    with phase7_engine.begin() as conn:
        for review_id, status in (("r1", "OPEN"), ("r2", "OPEN"),
                                  ("r3", "RESOLVED")):
            conn.execute(sa.text(
                "INSERT INTO divergence_review "
                "(review_id, kind, company_id, status, created_at) "
                "VALUES (:id, 'EMPIRICAL_CONFLICT', 9801, :status, :now)"),
                {"id": review_id, "status": status, "now": FIXTURE_NOW})
    with phase7_engine.connect() as conn:
        signal = divergence_queue_volume(conn)
    assert signal.value == 2
    assert signal.detail["by_kind"]["EMPIRICAL_CONFLICT"] == 2


def test_coverage_gap_depth_counts_open_gaps(phase7_engine):
    from eval.monitoring import coverage_gap_depth

    with phase7_engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO coverage_gap (gap_id, variable, sign, industry, "
            "window_days, n, median_car, sign_consistency, p_value, priority, "
            "status, computed_at) VALUES ('g1', 'fixture_var', 'UP', "
            "'fixture_industry', 5, 12, -0.01, 0.8, 0.02, 1.0, 'OPEN', :now)"),
            {"now": FIXTURE_NOW})
    with phase7_engine.connect() as conn:
        assert coverage_gap_depth(conn).value == 1


def test_exposure_staleness_p90_is_hand_checked(phase7_engine, phase7_session):
    """Ten fixture rows aged 1..10 days.

    The percentile is Phase 1's (`app.ledger.coverage._percentile`, imported
    rather than restated): index = round(0.90 * (n - 1)) = round(8.1) = 8,
    the ninth smallest, which is 9 days. Reusing that definition is the
    point -- two definitions of p90 in one repo would eventually disagree,
    and the disagreement would surface as a phantom alert.
    """
    from app.ledger.review import review_session
    from eval.monitoring import exposure_staleness_p90

    # Phase 1's guard: the ledger is writable only inside a review session,
    # so even a fixture row goes in the way a reviewer's approval does.
    with review_session(phase7_session):
        for age in range(1, 11):
            phase7_session.execute(sa.text(
                "INSERT INTO company_exposure (exposure_id, company_id, "
                "exposure_kind, exposure_tag, share_of_base, base_kind, "
                "base_value_inr, measurement, source_type, source_url, "
                "as_of_date, freshness_days, confidence, created_by, "
                "reviewed_by, created_at) VALUES "
                "(:id, 9801, 'INPUT', 'input:crude_direct', 0.1, 'COGS', 1.0, "
                "'DISCLOSED', 'ANNUAL_REPORT', 'https://fixture.invalid', "
                ":as_of, 365, 0.9, 'fixture', 'fixture-reviewer', :now)"),
                {"id": f"e{age}", "as_of": FIXTURE_TODAY - timedelta(days=age),
                 "now": FIXTURE_NOW})
    phase7_session.commit()
    with phase7_engine.connect() as conn:
        signal = exposure_staleness_p90(conn, as_of=FIXTURE_TODAY)
    assert signal.value == 9
    assert signal.unit == "days"


def test_policy_state_staleness_counts_states_past_their_window(phase7_engine):
    from eval.monitoring import policy_state_staleness

    with phase7_engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO policy_state (state_key, state_value, as_of, "
            "freshness_days, source_url, owner) VALUES "
            "('fixture_fresh', '{}', :fresh, 30, 'https://fixture.invalid', 'owner')"),
            {"fresh": FIXTURE_TODAY - timedelta(days=5)})
        conn.execute(sa.text(
            "INSERT INTO policy_state (state_key, state_value, as_of, "
            "freshness_days, source_url, owner) VALUES "
            "('fixture_stale', '{}', :stale, 30, 'https://fixture.invalid', 'owner')"),
            {"stale": FIXTURE_TODAY - timedelta(days=90)})
    with phase7_engine.connect() as conn:
        signal = policy_state_staleness(conn, as_of=FIXTURE_TODAY)
    assert signal.value == 1
    assert signal.detail["stale_keys"] == ["fixture_stale"]
    assert signal.alert is True, (
        "a stale levy rate is a correctness bug, not a data-hygiene note")


def test_rejection_reason_histogram_is_ordered_and_complete(phase7_engine,
                                                            phase7_session):
    from eval.monitoring import rejection_reason_histogram

    _write_impacts(phase7_session, [
        ("REJECTED", "NO_MATERIAL_IMPACT"),
        ("REJECTED", "NO_MATERIAL_IMPACT"),
        ("REJECTED", "UNBOUND_CLAIM"),
        ("PRIMARY", None),
    ])
    with phase7_engine.connect() as conn:
        signal = rejection_reason_histogram(conn)
    assert signal.value == {"NO_MATERIAL_IMPACT": 2, "UNBOUND_CLAIM": 1}
    assert signal.detail["published"] == 1


def test_the_histogram_alerts_when_no_material_impact_collapses(phase7_engine,
                                                               phase7_session):
    """The phase file's own warning: "NO_MATERIAL_IMPACT collapsing toward
    zero = misconfigured threshold"."""
    from eval.monitoring import rejection_reason_histogram

    _write_impacts(phase7_session, [("REJECTED", "UNBOUND_CLAIM")] * 5)
    with phase7_engine.connect() as conn:
        signal = rejection_reason_histogram(conn)
    assert signal.alert is True
    assert "NO_MATERIAL_IMPACT" in signal.refusal_or_note


def test_firewall_deletion_rate_needs_a_denominator_the_database_does_not_hold(
        phase7_engine):
    """The `firewall_deletion` table stores DELETIONS, not sentences
    examined. A rate invented from the deletions alone would always be 1.0."""
    from eval.monitoring import firewall_deletion_rate

    with phase7_engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO firewall_deletion (event_id, company_id, sentence, "
            "reason, stage, created_at) VALUES ('fx', 9801, 'a sentence', "
            "'numeral not in record set: 90', 'STAGE_1', :now)"),
            {"now": FIXTURE_NOW})
    with phase7_engine.connect() as conn:
        signal = firewall_deletion_rate(conn)
        supplied = firewall_deletion_rate(conn, sentences_total=10)
    assert signal.value is None and signal.refusal
    assert signal.detail["deletions"] == 1
    assert supplied.value == 0.1


def _seed_llm_calls(engine, rows):
    with engine.begin() as conn:
        for stage, article in rows:
            conn.execute(sa.text(
                "INSERT INTO llm_call_usage (created_at, provider, stage, "
                "article_id, success) VALUES (:now, 'fixture', :stage, "
                ":article, 1)"),
                {"now": FIXTURE_NOW, "stage": stage, "article": article})


def test_frontier_calls_per_event_reads_only_v5_stages(phase7_engine):
    from eval.monitoring import V5_FRONTIER_STAGES, V5_LLM_STAGES, frontier_calls_per_event

    _seed_llm_calls(phase7_engine, [("FALSIFIER", 1), ("FALSIFIER", 1),
                                    ("impact_whys", 1)])
    with phase7_engine.connect() as conn:
        signal = frontier_calls_per_event(conn)
    assert V5_FRONTIER_STAGES == ("FALSIFIER",)
    assert set(V5_FRONTIER_STAGES) <= set(V5_LLM_STAGES)
    assert signal.value == 2.0
    assert signal.detail["events"] == 1


def test_the_frontier_signal_does_not_count_the_entailment_judge(phase7_engine):
    """M-1. The stage-2 judge is section 18's rung 3. Counting it in the
    FRONTIER budget would make a cheap system look like it was breaching the
    one budget the spec actually gates."""
    from eval.monitoring import frontier_calls_per_event, small_calls_per_event

    _seed_llm_calls(phase7_engine, [("FALSIFIER", 1), ("FIREWALL_JUDGE", 1),
                                    ("FIREWALL_JUDGE", 1)])
    with phase7_engine.connect() as conn:
        frontier = frontier_calls_per_event(conn)
        small = small_calls_per_event(conn)
    assert frontier.value == 1.0
    assert small.value == 2.0
    assert small.detail["stages_counted"] == ["FIREWALL_JUDGE"]


def test_small_model_spend_stays_visible(phase7_engine):
    """Removing the judge from the frontier count must not remove it from
    view -- that is how spend hides."""
    from eval.monitoring import all_signals

    _seed_llm_calls(phase7_engine, [("FIREWALL_JUDGE", 7)])
    with phase7_engine.connect() as conn:
        signals = {s.name: s for s in all_signals(conn, as_of=FIXTURE_TODAY)}
    assert signals["small_calls_per_event"].value == 1.0
    assert signals["frontier_calls_per_event"].value is None
    assert signals["frontier_calls_per_event"].refusal


def test_calibration_drift_refuses_while_calibration_is_disabled(phase7_engine):
    from eval.monitoring import calibration_drift

    with phase7_engine.connect() as conn:
        signal = calibration_drift(conn)
    assert signal.value is None
    assert "calibration" in signal.refusal.lower()


def test_publish_latency_refuses_because_nothing_times_the_v5_path(phase7_engine):
    from eval.monitoring import publish_latency_p95

    with phase7_engine.connect() as conn:
        signal = publish_latency_p95(conn)
    assert signal.value is None
    assert signal.refusal


# ---------------------------------------------------------------------------
# the console route
# ---------------------------------------------------------------------------

def test_the_console_exposes_monitoring_as_read_only_json(phase7_engine):
    from fastapi.testclient import TestClient

    from tools.ledger_ui import build_app

    client = TestClient(build_app(phase7_engine))
    response = client.get("/monitoring.json")
    assert response.status_code == 200
    payload = response.json()
    assert {entry["name"] for entry in payload["signals"]} == set(SIGNAL_NAMES)


def test_the_monitoring_route_is_read_only(phase7_engine):
    from fastapi.testclient import TestClient

    from tools.ledger_ui import build_app

    app = build_app(phase7_engine)
    routes = [r for r in app.routes if getattr(r, "path", "") == "/monitoring.json"]
    assert routes and set(routes[0].methods) <= {"GET", "HEAD"}
    client = TestClient(build_app(phase7_engine))
    assert client.post("/monitoring.json").status_code in (404, 405)


def test_nothing_under_app_imports_the_monitoring_console_page_from_tools():
    """Same rule Phases 1/3/5/6 hold to: the console is tooling, and the
    product never imports it."""
    from pathlib import Path

    from tests.phase7.conftest import BACKEND, imported_modules, package_sources

    for path in package_sources(Path(BACKEND) / "app"):
        assert "tools.ledger_ui" not in imported_modules(path), path


def test_the_monitoring_module_writes_nothing():
    from pathlib import Path

    from tests.phase7.conftest import BACKEND, code_lines

    path = Path(BACKEND) / "eval" / "monitoring.py"
    for number, line in code_lines(path):
        upper = line.upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "session.add"):
            assert verb.upper() not in upper, f"{path.name}:{number}: {line.strip()}"


# ---------------------------------------------------------------------------

def _write_impacts(session, rows):
    """Canonical rows, written through the ONLY writer (invariant 1). A test
    that inserted these directly would be testing a database the product
    cannot produce."""
    from app.core.impact_writer import reducer_session

    with reducer_session(session):
        for index, (tier, reason) in enumerate(rows):
            session.execute(sa.text(
                "INSERT INTO company_impact (event_id, company_id, "
                "analysis_version, reducer_version, reducer_run_seq, "
                "publication_tier, rejection_reason, needs_reanalysis, "
                "created_at) VALUES (:event, 9801, :version, 'r5.0.0', 0, "
                ":tier, :reason, 0, :now)"),
                {"event": f"fixture:event-{index}", "version": f"v5:fixture:{index}",
                 "tier": tier, "reason": reason, "now": FIXTURE_NOW})
    session.commit()
