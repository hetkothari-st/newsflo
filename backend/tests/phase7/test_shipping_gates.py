"""TASK 7.3 tests -- the shipping gates.

THERE IS NO CI IN THIS REPO. The phase file says "CI-enforced. A PR failing
any gate cannot merge", and there is no CI system to enforce it with
(controller adaptation). So the deliverable is a RUNNABLE EVALUATOR that
exits non-zero, plus this suite, which is the thing that actually runs today.
`backend/eval/shipping_gates.py`'s header says where to wire it when CI
exists, and DATA_GAPS section 11 names the owner.

WHAT THIS FILE INSISTS ON:

  * every gate in spec section 17.2 is EVALUATED. A gate nobody evaluates is
    a gate nobody has;
  * every gate BITES, proven with a fixture metric set that violates exactly
    that gate and passes everything else;
  * the three hard zeros exit HARD, and the loader REFUSES a config that
    relaxes one. "Do not relax a hard-zero gate to unblock a release" is the
    phase file's fourth DO NOT, and a rule that lives only in a document is a
    rule that will be edited;
  * a metric that is MISSING is REFUSED, never treated as a pass. The empty
    corpus makes most of them missing today, which is exactly why this
    matters;
  * the no-regression rule compares against a stored baseline, and REFUSES
    with a named reason when the baseline is absent -- which is the deployed
    state (`eval/baselines/main.json` ships absent, because no corpus has
    ever been scored).
"""
import json
from pathlib import Path

import pytest

from tests.phase7.conftest import BACKEND, load_fixture

GATE_NAMES = (
    "primary_precision",
    "primary_wrong_direction_rate",
    "primary_false_positives_on_null_events",
    "secondary_ripple_recall",
    "secondary_ripple_precision",
    "ripple_family_recall",
    "fabricated_numeral_rate",
    "firewall_deletion_rate_primary_prose",
    "internal_contradiction_rate",
    "calibration_ece",
    "section_assignment_accuracy",
    "reducer_determinism",
    "market_fundamental_isolation",
    "p95_publish_latency_seconds",
)

HARD_ZEROS = (
    "primary_false_positives_on_null_events",
    "fabricated_numeral_rate",
    "internal_contradiction_rate",
)


@pytest.fixture()
def sets():
    return load_fixture("gate_metric_sets.json")


@pytest.fixture()
def passing(sets):
    return {k: v for k, v in sets["passing"].items() if not k.startswith("_")}


def _report(metrics, **kwargs):
    from eval.shipping_gates import evaluate_gates

    kwargs.setdefault("baseline", {"metrics": {"primary_precision": 0.0,
                                               "ripple_family_recall": 0.0}})
    return evaluate_gates(metrics, **kwargs)


# ---------------------------------------------------------------------------
# coverage: every gate in the spec table
# ---------------------------------------------------------------------------

def test_every_gate_in_the_spec_table_is_evaluated(passing):
    report = _report(passing)
    assert {o.name for o in report.outcomes} >= set(GATE_NAMES)


def test_the_gate_thresholds_match_the_spec_table():
    from eval.shipping_gates import load_gate_specs

    specs = {s.name: s for s in load_gate_specs()}
    assert (specs["primary_precision"].comparison,
            specs["primary_precision"].threshold) == (">=", 0.95)
    assert (specs["primary_wrong_direction_rate"].comparison,
            specs["primary_wrong_direction_rate"].threshold) == ("<=", 0.02)
    assert (specs["secondary_ripple_recall"].comparison,
            specs["secondary_ripple_recall"].threshold) == (">=", 0.70)
    assert (specs["secondary_ripple_precision"].comparison,
            specs["secondary_ripple_precision"].threshold) == (">=", 0.80)
    assert (specs["ripple_family_recall"].comparison,
            specs["ripple_family_recall"].threshold) == (">=", 0.80)
    assert (specs["calibration_ece"].comparison,
            specs["calibration_ece"].threshold) == ("<=", 0.05)
    assert (specs["section_assignment_accuracy"].comparison,
            specs["section_assignment_accuracy"].threshold) == (">=", 0.98)
    assert (specs["p95_publish_latency_seconds"].comparison,
            specs["p95_publish_latency_seconds"].threshold) == ("<=", 90.0)
    assert (specs["firewall_deletion_rate_primary_prose"].comparison,
            specs["firewall_deletion_rate_primary_prose"].threshold) == ("==", 0.0)


def test_a_fully_passing_metric_set_passes_every_gate(passing):
    report = _report(passing)
    assert report.failures == (), [o.name for o in report.failures]
    assert report.refusals == (), [o.name for o in report.refusals]
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# every gate bites -- both directions, one parametrized case per gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gate", GATE_NAMES)
def test_each_gate_bites(gate, passing, sets):
    violating = dict(passing)
    violating.update({k: v for k, v in sets["violations"][gate].items()
                      if not k.startswith("_")})
    report = _report(violating)
    failing = {o.name for o in report.failures}
    assert failing == {gate}, (
        f"expected exactly {gate} to fail; got {sorted(failing)}")
    assert report.exit_code != 0


@pytest.mark.parametrize("gate", HARD_ZEROS)
def test_a_hard_zero_violation_exits_hard(gate, passing, sets):
    violating = dict(passing)
    violating.update({k: v for k, v in sets["violations"][gate].items()
                      if not k.startswith("_")})
    report = _report(violating)
    assert {o.name for o in report.hard_violations} == {gate}
    assert report.exit_code == 3, (
        "a hard-zero violation must exit with its own code -- 'the definition "
        "of defensible' cannot share an exit status with a quality miss")


@pytest.mark.parametrize("gate", HARD_ZEROS)
def test_the_hard_zeros_are_declared_hard_in_config(gate):
    from eval.shipping_gates import load_gate_specs

    spec = {s.name: s for s in load_gate_specs()}[gate]
    assert spec.hard is True
    assert spec.threshold == 0
    assert spec.comparison == "=="


def test_a_config_that_relaxes_a_hard_zero_is_refused(tmp_path):
    """The phase file's fourth DO NOT, enforced by the loader rather than by
    a comment nobody reads."""
    import yaml

    from eval.shipping_gates import GateConfigError, GATES_PATH, load_gate_specs

    raw = yaml.safe_load(Path(GATES_PATH).read_text(encoding="utf-8"))
    for entry in raw["gates"]:
        if entry["name"] == "fabricated_numeral_rate":
            entry["threshold"] = 0.01
    relaxed = tmp_path / "relaxed.yaml"
    relaxed.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(GateConfigError) as excinfo:
        load_gate_specs(relaxed)
    assert "fabricated_numeral_rate" in str(excinfo.value)


def test_a_config_that_demotes_a_hard_zero_to_soft_is_refused(tmp_path):
    import yaml

    from eval.shipping_gates import GateConfigError, GATES_PATH, load_gate_specs

    raw = yaml.safe_load(Path(GATES_PATH).read_text(encoding="utf-8"))
    for entry in raw["gates"]:
        if entry["name"] == "internal_contradiction_rate":
            entry["hard"] = False
    relaxed = tmp_path / "soft.yaml"
    relaxed.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(GateConfigError):
        load_gate_specs(relaxed)


def test_a_config_that_drops_a_hard_zero_entirely_is_refused(tmp_path):
    import yaml

    from eval.shipping_gates import GateConfigError, GATES_PATH, load_gate_specs

    raw = yaml.safe_load(Path(GATES_PATH).read_text(encoding="utf-8"))
    raw["gates"] = [g for g in raw["gates"]
                    if g["name"] != "primary_false_positives_on_null_events"]
    dropped = tmp_path / "dropped.yaml"
    dropped.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(GateConfigError):
        load_gate_specs(dropped)


# ---------------------------------------------------------------------------
# missing metrics are refused, not passed
# ---------------------------------------------------------------------------

def test_a_missing_metric_is_refused_not_passed(passing):
    metrics = dict(passing)
    metrics["primary_precision"] = None
    report = _report(metrics)
    refused = {o.name for o in report.refusals}
    assert refused == {"primary_precision"}
    assert report.failures == ()
    assert report.exit_code != 0, "a gate nobody could evaluate is not a green gate"


def test_a_metric_absent_from_the_set_is_refused_with_a_named_reason(passing):
    metrics = dict(passing)
    del metrics["section_assignment_accuracy"]
    report = _report(metrics)
    outcome = {o.name: o for o in report.outcomes}["section_assignment_accuracy"]
    assert outcome.status == "REFUSED"
    assert outcome.reason


def test_a_refused_hard_zero_does_not_exit_hard(passing):
    """A hard-zero we could not MEASURE is not a hard-zero we VIOLATED. It
    still blocks (exit non-zero) and it is still reported as unmeasured."""
    metrics = dict(passing)
    metrics["fabricated_numeral_rate"] = None
    report = _report(metrics)
    assert report.hard_violations == ()
    assert report.exit_code == 1


# ---------------------------------------------------------------------------
# the delegated suites
# ---------------------------------------------------------------------------

def test_the_delegated_suites_are_named_not_assumed():
    """Reducer determinism (10k permutations) and market/fundamental
    isolation are proven by Phase 0's suites, not recomputed here. The
    evaluator must SAY which suite answers each gate."""
    from eval.shipping_gates import DELEGATED_SUITES

    assert set(DELEGATED_SUITES) == {"reducer_determinism",
                                     "market_fundamental_isolation"}
    for gate, suite in DELEGATED_SUITES.items():
        assert (BACKEND / suite.path).exists(), suite.path
        assert suite.test_name


def test_the_delegated_suite_files_still_contain_the_named_tests():
    from eval.shipping_gates import DELEGATED_SUITES

    for gate, suite in DELEGATED_SUITES.items():
        source = (BACKEND / suite.path).read_text(encoding="utf-8")
        assert f"def {suite.test_name}" in source, (
            f"{gate} delegates to {suite.path}::{suite.test_name}, which no "
            f"longer exists")


# ---------------------------------------------------------------------------
# the no-regression rule
# ---------------------------------------------------------------------------

def test_the_baseline_file_ships_absent():
    from eval.shipping_gates import BASELINE_PATH

    assert not Path(BASELINE_PATH).exists(), (
        "a baseline exists -- either a corpus was scored (update this test and "
        "DATA_GAPS section 11) or a placeholder baseline was invented, which "
        "would make the no-regression rule compare against fiction")


def test_an_absent_baseline_refuses_the_comparison_with_a_named_reason(passing):
    from eval.shipping_gates import evaluate_gates

    report = evaluate_gates(passing, baseline=None)
    regression = {o.name: o for o in report.outcomes}["no_regression"]
    assert regression.status == "REFUSED"
    assert "baseline" in regression.reason.lower()
    assert "main.json" in regression.reason
    assert report.exit_code != 0


def test_a_regression_against_the_baseline_fails(passing, sets):
    from eval.shipping_gates import evaluate_gates

    baseline = {k: v for k, v in sets["baselines"]["better_than_us"].items()
                if not k.startswith("_")}
    report = evaluate_gates(passing, baseline=baseline)
    regression = {o.name: o for o in report.outcomes}["no_regression"]
    assert regression.status == "FAIL"
    assert "primary_precision" in regression.reason
    assert report.exit_code != 0


def test_no_regression_passes_when_the_metrics_improved(passing, sets):
    from eval.shipping_gates import evaluate_gates

    baseline = {k: v for k, v in sets["baselines"]["worse_than_us"].items()
                if not k.startswith("_")}
    report = evaluate_gates(passing, baseline=baseline)
    regression = {o.name: o for o in report.outcomes}["no_regression"]
    assert regression.status == "PASS"
    assert report.exit_code == 0


def test_no_regression_watches_exactly_the_two_metrics_the_rule_names(sets):
    """"no merge may reduce PRIMARY precision or ripple recall versus the
    current main branch baseline, even if absolute gates still pass"."""
    from eval.shipping_gates import NO_REGRESSION_METRICS

    assert NO_REGRESSION_METRICS == ("primary_precision", "ripple_family_recall")


def test_a_regression_fails_even_when_every_absolute_gate_passes(passing, sets):
    from eval.shipping_gates import evaluate_gates

    baseline = {"metrics": {"primary_precision": 0.98,
                            "ripple_family_recall": 0.80}}
    report = evaluate_gates(passing, baseline=baseline)
    assert {o.name for o in report.failures} == {"no_regression"}


# ---------------------------------------------------------------------------
# the runnable evaluator
# ---------------------------------------------------------------------------

def test_the_cli_exits_nonzero_on_a_violating_metrics_file(tmp_path, passing, sets):
    from eval.shipping_gates import main

    metrics = dict(passing)
    metrics.update(sets["violations"]["primary_precision"])
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    assert main(["--metrics", str(path), "--no-baseline"]) == 1


def test_the_cli_exits_three_on_a_hard_zero(tmp_path, passing, sets):
    from eval.shipping_gates import main

    metrics = dict(passing)
    metrics.update(sets["violations"]["internal_contradiction_rate"])
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    assert main(["--metrics", str(path), "--no-baseline"]) == 3


def test_the_cli_exits_zero_when_everything_passes(tmp_path, passing):
    from eval.shipping_gates import main

    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": passing}), encoding="utf-8")
    assert main(["--metrics", str(path), "--no-baseline"]) == 0


def test_the_cli_refuses_an_absent_metrics_file(tmp_path):
    from eval.shipping_gates import main

    assert main(["--metrics", str(tmp_path / "nope.json")]) == 2


def test_the_module_header_says_where_to_wire_this_into_ci():
    import eval.shipping_gates as module

    assert "CI" in (module.__doc__ or "")
    assert "DATA_GAPS" in (module.__doc__ or "")


def test_the_report_renders_per_stratum_not_only_aggregate(passing):
    """Task 7.3 inherits Task 7.2's DO NOT: never report only aggregate."""
    from eval.shipping_gates import render_report

    report = _report(passing)
    text = render_report(report, per_stratum={
        "commodity": {"primary_precision": 0.99},
        "policy_regulatory": {"primary_precision": 0.91}})
    assert "commodity" in text and "policy_regulatory" in text
    assert "0.91" in text


def test_rendering_without_a_breakdown_says_so(passing):
    from eval.shipping_gates import render_report

    text = render_report(_report(passing), per_stratum=None)
    assert "per-stratum" in text.lower()
