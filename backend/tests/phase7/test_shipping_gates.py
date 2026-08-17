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
    assert "primary_precision" in refused
    # the no-regression rule watches primary_precision too, so it becomes
    # unevaluable in the same breath -- and says so rather than passing
    assert refused == {"primary_precision", "no_regression"}
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
    from eval.shipping_gates import delegated_suites

    suites = delegated_suites()
    assert set(suites) == {"reducer_determinism", "market_fundamental_isolation"}
    for gate, suite in suites.items():
        assert (BACKEND / suite.path).exists(), suite.path
        assert suite.test_name


def test_the_delegated_suite_files_still_contain_the_named_tests():
    from eval.shipping_gates import delegated_suites

    for gate, suite in delegated_suites().items():
        source = (BACKEND / suite.path).read_text(encoding="utf-8")
        assert f"def {suite.test_name}" in source, (
            f"{gate} delegates to {suite.path}::{suite.test_name}, which no "
            f"longer exists")


# --- the delegated suites are RUN, not merely named -------------------------

PROBE = "tests/phase7/fixtures/delegated_probe.py"


def _delegated_only(suite, passing_metrics, **kwargs):
    """Evaluate with ONLY the delegated gate's metric withheld, so the
    outcome under test is the runner's answer and not a supplied number."""
    from eval.shipping_gates import GateSpec, evaluate_gates

    metrics = {k: v for k, v in passing_metrics.items()
               if k != "reducer_determinism"}
    specs = (GateSpec(name="reducer_determinism", comparison="==", threshold=1.0,
                      hard=False, description="probe", delegated=suite),)
    return evaluate_gates(metrics, baseline=None, specs=specs,
                          no_regression_metrics=(), **kwargs)


def test_a_delegated_gate_goes_green_when_its_suite_passes(passing):
    """The happy path, exercised for real: a pytest subprocess runs the named
    node id and its exit code becomes the gate's value."""
    from eval.shipping_gates import DelegatedSuite

    report = _delegated_only(
        DelegatedSuite(path=PROBE, test_name="test_the_probe_passes"), passing)
    outcome = {o.name: o for o in report.outcomes}["reducer_determinism"]
    assert outcome.status == "PASS"
    assert outcome.value == 1.0


def test_a_delegated_gate_fails_when_its_suite_fails(passing):
    """The path nothing in the real repo can exercise, because both real
    delegated suites pass. Without this the runner is a formality."""
    from eval.shipping_gates import DelegatedSuite

    report = _delegated_only(
        DelegatedSuite(path=PROBE, test_name="test_the_probe_fails"), passing)
    outcome = {o.name: o for o in report.outcomes}["reducer_determinism"]
    assert outcome.status == "FAIL"
    assert outcome.value == 0.0
    assert PROBE in outcome.reason and "test_the_probe_fails" in outcome.reason
    assert report.exit_code != 0


def test_a_missing_delegated_suite_file_fails_rather_than_refusing(passing):
    from eval.shipping_gates import DelegatedSuite

    report = _delegated_only(
        DelegatedSuite(path="tests/phase7/fixtures/nope.py", test_name="test_x"),
        passing)
    outcome = {o.name: o for o in report.outcomes}["reducer_determinism"]
    assert outcome.status == "FAIL"
    assert outcome.value == 0.0


def test_skipping_the_delegated_run_says_so_and_never_says_unmeasured(passing):
    """DELEGATED_NOT_RUN is its own status. "was not measured" would be a lie:
    the property is measurable in seconds and nobody asked."""
    from eval.shipping_gates import DELEGATED_NOT_RUN, DelegatedSuite

    report = _delegated_only(
        DelegatedSuite(path=PROBE, test_name="test_the_probe_passes"), passing,
        run_delegated=False)
    outcome = {o.name: o for o in report.outcomes}["reducer_determinism"]
    assert outcome.status == DELEGATED_NOT_RUN
    assert PROBE in outcome.reason
    assert "not measured" not in outcome.reason
    assert "--skip-delegated" in outcome.reason
    assert report.exit_code != 0, "a gate nobody ran is not a green gate"


def test_a_supplied_metric_beats_the_runner(passing):
    """A caller who already ran the suite (the harness does) must not pay for
    a second subprocess."""
    from eval.shipping_gates import DelegatedSuite, GateSpec, evaluate_gates

    suite = DelegatedSuite(path=PROBE, test_name="test_the_probe_fails")
    specs = (GateSpec(name="reducer_determinism", comparison="==", threshold=1.0,
                      hard=False, delegated=suite),)
    report = evaluate_gates({"reducer_determinism": 1.0}, baseline=None,
                            specs=specs, no_regression_metrics=())
    outcome = {o.name: o for o in report.outcomes}["reducer_determinism"]
    assert outcome.status == "PASS", (
        "the supplied metric was ignored and the failing probe ran instead")


def test_the_delegated_runner_pins_the_scheduler_off():
    """A delegated run is a pytest subprocess. It must inherit the same
    hermetic guarantee the suite itself has."""
    from eval.shipping_gates import delegated_environment

    assert delegated_environment()["ENABLE_SCHEDULER"] == "false"


def test_delegated_gates_run_by_default_in_the_evaluator(passing):
    """The two properties pass today and cost seconds to prove, so the
    evaluator proves them unless told not to."""
    import inspect

    from eval.shipping_gates import evaluate_gates

    assert inspect.signature(
        evaluate_gates).parameters["run_delegated"].default is True


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


def test_the_cli_cannot_exit_zero_while_the_baseline_is_absent(tmp_path, passing):
    """The deployed reality, stated as a test: a perfect metric set still
    blocks, because the no-regression rule has nothing to compare against and
    refuses rather than waving it through."""
    from eval.shipping_gates import main

    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": passing}), encoding="utf-8")
    assert main(["--metrics", str(path), "--no-baseline"]) == 1


def test_the_cli_exits_zero_when_everything_passes(tmp_path, passing, sets):
    from eval.shipping_gates import main

    baseline = {k: v for k, v in sets["baselines"]["worse_than_us"].items()
                if not k.startswith("_")}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": passing}), encoding="utf-8")
    assert main(["--metrics", str(path), "--baseline", str(baseline_path)]) == 0


def test_the_cli_refuses_an_absent_metrics_file(tmp_path):
    from eval.shipping_gates import main

    assert main(["--metrics", str(tmp_path / "nope.json")]) == 2


def test_the_cli_exits_two_on_a_relaxed_hard_zero(tmp_path, passing):
    """The config error must reach `main`'s handler, which means the config
    must NOT be read at import time -- a module that raises on import cannot
    return an exit code at all."""
    import yaml

    from eval.shipping_gates import GATES_PATH, main

    raw = yaml.safe_load(Path(GATES_PATH).read_text(encoding="utf-8"))
    for entry in raw["gates"]:
        if entry["name"] == "fabricated_numeral_rate":
            entry["threshold"] = 0.01
    relaxed = tmp_path / "relaxed.yaml"
    relaxed.write_text(yaml.safe_dump(raw), encoding="utf-8")
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps({"metrics": passing}), encoding="utf-8")
    assert main(["--metrics", str(path), "--gates", str(relaxed),
                 "--no-baseline", "--skip-delegated"]) == 2


def test_importing_the_module_reads_no_config():
    """M-2, structurally: no MODULE-LEVEL statement calls the loader, so a
    broken config is an exit code rather than an ImportError from inside
    somebody else's import."""
    import ast
    from pathlib import Path as _Path

    from tests.phase7.conftest import BACKEND

    source = (_Path(BACKEND) / "eval" / "shipping_gates.py").read_text(
        encoding="utf-8")
    module = ast.parse(source)
    top_level = [node for node in module.body
                 if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef))]
    called = {
        node.func.id
        for statement in top_level
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "load_gate_specs" not in called
    assert "delegated_suites" not in called
    assert "load_baseline" not in called


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
    assert "NOT REPORTED" in text
    assert "aggregate-only" in text
    assert "per stratum" in text.lower() and "per sector" in text.lower()


def test_the_report_surfaces_metrics_the_harness_could_not_produce(passing):
    """M-5. The three protocol-gap metrics are invisible in a gate table that
    only lists gates -- and "no expected directness exists in the corpus" is
    a finding, not a footnote."""
    from eval.shipping_gates import render_report

    text = render_report(_report(passing), unavailable={
        "directness_accuracy": "eval_label carries no expected_directness column",
        "calibration_ece": "calibration is DISABLED and structurally locked"})
    assert "UNAVAILABLE" in text
    assert "directness_accuracy" in text
    assert "no expected_directness column" in text


def test_rendering_without_an_unavailable_map_omits_the_block(passing):
    from eval.shipping_gates import render_report

    assert "UNAVAILABLE" not in render_report(_report(passing))


def test_evaluate_gates_honours_supplied_specs_without_reading_the_config(passing):
    """M-4. A caller who hands in specs must get exactly those specs -- no
    silent YAML re-read for the no-regression list."""
    from eval.shipping_gates import GateSpec, evaluate_gates

    specs = (GateSpec(name="primary_precision", comparison=">=", threshold=0.5,
                      hard=False),)
    report = evaluate_gates({"primary_precision": 0.6}, baseline=None,
                            specs=specs, no_regression_metrics=())
    assert [o.name for o in report.outcomes] == ["primary_precision",
                                                 "no_regression"]
    assert report.outcomes[0].status == "PASS"


def test_supplied_specs_do_not_have_to_carry_the_hard_zeros(passing):
    """The hard-zero REFUSAL guards the FILE, which is what people edit. A
    caller assembling specs in memory is not editing policy."""
    from eval.shipping_gates import GateSpec, evaluate_gates

    specs = (GateSpec(name="primary_precision", comparison=">=", threshold=0.95,
                      hard=False),)
    evaluate_gates({"primary_precision": 0.99}, baseline=None, specs=specs,
                   no_regression_metrics=())
