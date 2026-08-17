"""TASK 7.3 -- the shipping gates, as a runnable evaluator.

    python -m eval.shipping_gates --metrics metrics.json

    exit 0  every gate passed
    exit 1  a quality gate failed, or a gate could not be evaluated
    exit 2  the evaluator could not run (no metrics file, unreadable config)
    exit 3  A HARD ZERO WAS VIOLATED

WIRE THIS INTO CI WHEN CI EXISTS. The phase file says "CI-enforced. A PR
failing any gate cannot merge", and this repo has no CI system at all -- no
`.github/workflows`, no pipeline, nothing that runs on a push. So what ships
is a script that exits non-zero and a test suite that runs it. The wiring is
recorded as an open item with an owner in DATA_GAPS section 11; when a
pipeline exists, one step running this command is the whole change.

THREE RULES THIS MODULE DOES NOT BEND:

  * a HARD ZERO cannot be relaxed. `load_gate_specs` refuses a config that
    raises one above zero, demotes one to soft, or drops one. The rule lives
    in the loader because a rule that lives in a document gets edited;
  * a MISSING metric is REFUSED, not passed. The corpus is empty, so most
    metrics are missing today -- and a build that went green on an empty
    corpus would be the worst possible outcome of this phase;
  * a REFUSED hard zero is not a VIOLATED hard zero. Not being able to
    measure integrity blocks the release (exit 1) without claiming integrity
    was breached (exit 3). Conflating them would train everyone to ignore
    exit 3.

DELEGATED GATES ARE RUN, NOT NAMED (review round 1, I-1). Two gates --
reducer determinism over 10,000 permutations, and market/fundamental
isolation -- are properties already proven by Phase 0's suites. Naming the
suite and stopping there left both gates permanently REFUSED with the reason
"was not measured", which was false twice over: the properties hold today,
and they cost seconds to prove. So the evaluator RUNS the named node id in a
pytest subprocess (`ENABLE_SCHEDULER=false`, like the suite itself) and turns
its exit code into 1.0 or 0.0. `--skip-delegated` opts out and produces a
DISTINCT status, `DELEGATED_NOT_RUN`, which names the suite that was skipped
and still blocks. It never says "not measured": that reason belongs to
metrics nobody can compute, and these are not those.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

BACKEND = Path(__file__).resolve().parents[1]
GATES_PATH = BACKEND / "config" / "shipping_gates.yaml"
BASELINE_PATH = BACKEND / "eval" / "baselines" / "main.json"

#: Section 17.2's three. Named HERE as well as in the config, so deleting one
#: from the file is a failure rather than a silent narrowing.
HARD_ZERO_GATES = (
    "primary_false_positives_on_null_events",
    "fabricated_numeral_rate",
    "internal_contradiction_rate",
)

#: "No merge may reduce PRIMARY precision or ripple recall versus the current
#: main branch baseline, even if absolute gates still pass."
NO_REGRESSION_METRICS = ("primary_precision", "ripple_family_recall")
NO_REGRESSION_GATE = "no_regression"

PASS, FAIL, REFUSED = "PASS", "FAIL", "REFUSED"
#: A delegated gate nobody asked to run. NOT `REFUSED`: refused means the
#: metric cannot be computed, and this one can -- in about a second.
DELEGATED_NOT_RUN = "DELEGATED_NOT_RUN"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2
EXIT_HARD_ZERO = 3

#: A delegated suite is a local pytest run. Generous, because the reducer
#: determinism gate really does reduce 10,000 permutations.
DELEGATED_TIMEOUT_SECONDS = 900

#: How a delegated suite's PASS/FAIL is expressed as a gate value. Not
#: thresholds -- the threshold is `== 1.0` and lives in
#: `config/shipping_gates.yaml` like every other one. These are the two
#: points of a boolean domain, named so they cannot be read as a bar someone
#: chose.
SUITE_PASSED = 1.0
SUITE_FAILED = 0.0


class GateConfigError(ValueError):
    """A shipping-gate config that must not be loaded."""


@dataclass(frozen=True)
class DelegatedSuite:
    """A gate answered by RUNNING an existing test rather than by a metric.

    Reducer determinism over 10,000 permutations and market/fundamental
    isolation are already proven by Phase 0's suites. Reimplementing either
    here would be a second version of the same property, free to drift from
    the first; running the original keeps one answer.
    """
    path: str
    test_name: str

    @property
    def node_id(self) -> str:
        return f"{self.path}::{self.test_name}"


@dataclass(frozen=True)
class GateSpec:
    name: str
    comparison: str
    threshold: float
    hard: bool
    description: str = ""
    delegated: DelegatedSuite | None = None


@dataclass(frozen=True)
class GateOutcome:
    name: str
    status: str
    value: Any = None
    threshold: Any = None
    comparison: str = ""
    hard: bool = False
    reason: str = ""


@dataclass(frozen=True)
class GateReport:
    outcomes: tuple[GateOutcome, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failures(self) -> tuple[GateOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == FAIL)

    @property
    def refusals(self) -> tuple[GateOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status == REFUSED)

    @property
    def not_run(self) -> tuple[GateOutcome, ...]:
        """Delegated gates nobody asked to run. Separate from `refusals`
        because the fix is different: a refusal needs data that does not
        exist, and this needs a flag dropped."""
        return tuple(o for o in self.outcomes if o.status == DELEGATED_NOT_RUN)

    @property
    def hard_violations(self) -> tuple[GateOutcome, ...]:
        return tuple(o for o in self.failures if o.hard)

    @property
    def exit_code(self) -> int:
        if self.hard_violations:
            return EXIT_HARD_ZERO
        if self.failures or self.refusals or self.not_run:
            return EXIT_FAILED
        return EXIT_OK


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def load_gate_specs(path: Path | str | None = None) -> tuple[GateSpec, ...]:
    """Read the gate policy, and REFUSE it if a hard zero has been softened."""
    import yaml

    source = Path(path or GATES_PATH)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    specs: list[GateSpec] = []
    for entry in raw.get("gates") or ():
        delegated = entry.get("delegated_to")
        specs.append(GateSpec(
            name=str(entry["name"]),
            comparison=str(entry["comparison"]),
            threshold=entry["threshold"],
            hard=bool(entry.get("hard", False)),
            description=str(entry.get("description") or "").strip(),
            delegated=(DelegatedSuite(path=str(delegated["path"]),
                                      test_name=str(delegated["test"]))
                       if delegated else None)))

    by_name = {spec.name: spec for spec in specs}
    for name in HARD_ZERO_GATES:
        spec = by_name.get(name)
        if spec is None:
            raise GateConfigError(
                f"the hard-zero gate {name!r} is missing from {source}. The "
                f"three hard zeros are the definition of defensible (spec "
                f"section 17.2) and deleting one is not a configuration "
                f"change.")
        if not spec.hard:
            raise GateConfigError(
                f"the hard-zero gate {name!r} is declared soft in {source}. "
                f"Task 7.3: do not relax a hard-zero gate to unblock a "
                f"release.")
        if spec.comparison != "==" or float(spec.threshold) != 0:
            raise GateConfigError(
                f"the hard-zero gate {name!r} is set to "
                f"'{spec.comparison} {spec.threshold}' in {source}; it must be "
                f"'== 0'. Task 7.3: do not relax a hard-zero gate to unblock a "
                f"release.")
    return tuple(specs)


def _no_regression_metrics(path: Path | str | None = None) -> tuple[str, ...]:
    import yaml

    raw = yaml.safe_load(Path(path or GATES_PATH).read_text(encoding="utf-8")) or {}
    return tuple(raw.get("no_regression") or NO_REGRESSION_METRICS)


def delegated_suites(path: Path | str | None = None) -> dict[str, DelegatedSuite]:
    """gate name -> the suite that answers it.

    A FUNCTION, not a module constant (review round 1, M-2). Reading the
    config at import time meant a `GateConfigError` -- a relaxed hard zero,
    say -- surfaced as an ImportError from inside somebody's `import`, where
    `main` could not catch it and return the documented exit 2. A module that
    raises on import cannot report an exit code at all.
    """
    return {spec.name: spec.delegated
            for spec in load_gate_specs(path) if spec.delegated}


# ---------------------------------------------------------------------------
# running a delegated suite
# ---------------------------------------------------------------------------

def delegated_environment() -> dict[str, str]:
    """The environment a delegated pytest run gets.

    `ENABLE_SCHEDULER=false` is not optional: `app/main.py` starts a real
    BackgroundScheduler at import time when it is true, and half the suite
    imports `app.main`. A gate check that woke a live feed poller would be a
    measurement with side effects.
    """
    env = dict(os.environ)
    env["ENABLE_SCHEDULER"] = "false"
    env["PYTHONUTF8"] = "1"
    return env


def run_delegated_suite(suite: DelegatedSuite, *,
                        backend: Path | None = None) -> tuple[float, str]:
    """Run one delegated node id. -> (1.0 | 0.0, detail).

    Exit code IS the answer: pytest exits 0 only when the named test passed.
    A missing file, a renamed test and a genuine regression all exit
    non-zero, and all three mean the same thing here -- the property is not
    currently proven -- so all three produce 0.0 rather than a refusal. A
    gate whose evidence has gone missing is not a gate in an unknown state.
    """
    root = Path(backend or BACKEND)
    command = [sys.executable, "-m", "pytest", suite.node_id, "-q",
               "--no-header", "-p", "no:cacheprovider"]
    try:
        completed = subprocess.run(
            command, cwd=str(root), env=delegated_environment(),
            capture_output=True, text=True,
            timeout=DELEGATED_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return SUITE_FAILED, (f"{suite.node_id} did not finish within "
                     f"{DELEGATED_TIMEOUT_SECONDS}s")
    if completed.returncode == 0:
        return SUITE_PASSED, f"{suite.node_id} passed"
    tail = (completed.stdout or completed.stderr or "").strip().splitlines()
    summary = tail[-1] if tail else f"exit {completed.returncode}"
    return SUITE_FAILED, f"{suite.node_id} did NOT pass ({summary})"


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

_COMPARISONS = {
    ">=": lambda value, threshold: value >= threshold,
    "<=": lambda value, threshold: value <= threshold,
    "==": lambda value, threshold: value == threshold,
}


def _evaluate_one(spec: GateSpec, metrics: Mapping[str, Any], *,
                  run_delegated: bool = True,
                  runner: Callable[[DelegatedSuite], tuple[float, str]] | None = None
                  ) -> GateOutcome:
    supplied = metrics.get(spec.name)
    detail = ""
    if spec.delegated is not None and supplied is None:
        # A caller who already ran the suite supplies the metric and is
        # believed; nobody should pay for a second subprocess.
        if not run_delegated:
            return GateOutcome(
                spec.name, DELEGATED_NOT_RUN, None, spec.threshold,
                spec.comparison, spec.hard,
                reason=(f"{spec.name} is answered by running "
                        f"{spec.delegated.node_id}, and this run skipped it "
                        f"(--skip-delegated). Not a green gate and NOT an "
                        f"unmeasurable one: drop the flag and it takes "
                        f"seconds."))
        value, detail = (runner or run_delegated_suite)(spec.delegated)
        metrics = {**metrics, spec.name: value}
        supplied = value

    if spec.name not in metrics or supplied is None:
        return GateOutcome(
            spec.name, REFUSED, None, spec.threshold, spec.comparison, spec.hard,
            reason=(f"{spec.name} was not measured. It is REFUSED, not passed: "
                    f"a gate nobody could evaluate is not a green gate. "
                    f"{spec.description}"))
    value = metrics[spec.name]
    compare = _COMPARISONS.get(spec.comparison)
    if compare is None:
        return GateOutcome(spec.name, REFUSED, value, spec.threshold,
                           spec.comparison, spec.hard,
                           reason=f"unknown comparison {spec.comparison!r}")
    passed = compare(float(value), float(spec.threshold))
    reason = "" if passed else (
        f"{spec.name} = {value} violates {spec.comparison} {spec.threshold}"
        + (" -- HARD ZERO." if spec.hard else ""))
    if detail:
        # The node id belongs in the outcome whichever way it went: a green
        # delegated gate that did not say what it ran is indistinguishable
        # from one nobody ran.
        reason = f"{reason} {detail}".strip() if reason else detail
    return GateOutcome(spec.name, PASS if passed else FAIL, value,
                       spec.threshold, spec.comparison, spec.hard, reason)


def _evaluate_no_regression(metrics: Mapping[str, Any],
                            baseline: Mapping[str, Any] | None,
                            watched: Sequence[str]) -> GateOutcome:
    if not baseline:
        return GateOutcome(
            NO_REGRESSION_GATE, REFUSED, hard=False,
            reason=(f"no stored baseline at {BASELINE_PATH.name} "
                    f"({BASELINE_PATH}), so the no-regression rule cannot be "
                    f"evaluated. It ships absent because no corpus has ever "
                    f"been scored (DATA_GAPS sections 1 and 11). Refused, not "
                    f"passed."))
    stored = baseline.get("metrics") or {}
    regressions: list[str] = []
    unmeasured: list[str] = []
    for name in watched:
        before, after = stored.get(name), metrics.get(name)
        if before is None or after is None:
            unmeasured.append(name)
            continue
        if float(after) < float(before):
            regressions.append(f"{name}: {before} -> {after}")
    if regressions:
        return GateOutcome(
            NO_REGRESSION_GATE, FAIL, hard=False,
            reason=("regression against the stored baseline "
                    f"({baseline.get('commit', 'unknown commit')}): "
                    + "; ".join(regressions)))
    if unmeasured:
        return GateOutcome(
            NO_REGRESSION_GATE, REFUSED, hard=False,
            reason=("the no-regression rule could not be evaluated for "
                    + ", ".join(unmeasured)
                    + " -- either this run or the baseline does not carry it."))
    return GateOutcome(NO_REGRESSION_GATE, PASS, hard=False)


def evaluate_gates(metrics: Mapping[str, Any], *,
                   baseline: Mapping[str, Any] | None,
                   specs: Sequence[GateSpec] | None = None,
                   gates_path: Path | str | None = None,
                   no_regression_metrics: Sequence[str] | None = None,
                   run_delegated: bool = True,
                   delegated_runner: Callable[[DelegatedSuite],
                                              tuple[float, str]] | None = None
                   ) -> GateReport:
    """Evaluate EVERY gate.

    Nothing is skipped for being unmeasurable -- an unmeasurable gate is
    REFUSED, which blocks. Delegated gates are RUN by default: they cost
    seconds and the alternative is a gate with no path to green.

    `specs` is honoured FULLY (review round 1, M-4): supplying it means the
    caller has assembled the policy in memory, so the config file is not read
    at all -- not for the specs, and not for the no-regression list either.
    A hidden YAML read behind an explicit argument is the kind of thing that
    makes a test pass for the wrong reason.
    """
    if specs is not None:
        resolved = tuple(specs)
        watched = tuple(no_regression_metrics
                        if no_regression_metrics is not None
                        else NO_REGRESSION_METRICS)
    else:
        resolved = load_gate_specs(gates_path)
        watched = tuple(no_regression_metrics
                        if no_regression_metrics is not None
                        else _no_regression_metrics(gates_path))
    outcomes = [_evaluate_one(spec, metrics, run_delegated=run_delegated,
                              runner=delegated_runner)
                for spec in resolved]
    outcomes.append(_evaluate_no_regression(metrics, baseline, watched))
    return GateReport(tuple(outcomes), dict(metrics))


def load_baseline(path: Path | str | None = None) -> Mapping[str, Any] | None:
    source = Path(path or BASELINE_PATH)
    if not source.exists():
        return None
    return json.loads(source.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_report(report: GateReport,
                  per_stratum: Mapping[str, Mapping[str, Any]] | None = None,
                  per_sector: Mapping[str, Mapping[str, Any]] | None = None,
                  unavailable: Mapping[str, str] | None = None) -> str:
    """The gate table, the metrics nobody could produce, then the breakdowns.

    Task 7.2's DO NOT is inherited here: never report only aggregate. When a
    breakdown is absent this SAYS SO rather than quietly printing the
    aggregate alone, because an aggregate presented as the whole answer is
    how "excellent on crude, useless on policy" stays invisible.

    `unavailable` (review round 1, M-5) is the harness's own list of metrics
    the corpus protocol cannot express -- expected directness, distance,
    evidence grade, section, and calibration. They correspond to no gate, so
    a gate table alone renders them nowhere, and "the corpus carries no
    expected directness" is a finding rather than a footnote.
    """
    lines = ["SHIPPING GATES", "=" * 60]
    marks = {PASS: "PASS  ", FAIL: "FAIL  ", REFUSED: "REFUSE",
             DELEGATED_NOT_RUN: "NOTRUN"}
    for outcome in report.outcomes:
        mark = marks[outcome.status]
        value = "unmeasured" if outcome.value is None else outcome.value
        # The no-regression rule is a COMPARISON against a stored baseline,
        # not a threshold, so it carries neither -- and printing "( None)"
        # after it would read as a bar nobody set.
        bar = (f" ({outcome.comparison} {outcome.threshold})"
               if outcome.comparison else "")
        lines.append(f"{mark} {outcome.name}: {value}{bar}")
        if outcome.reason:
            lines.append(f"        {outcome.reason}")
    lines.append("")
    lines.append(f"exit code: {report.exit_code}")

    if unavailable:
        lines.append("")
        lines.append("UNAVAILABLE METRICS (no gate reads these; nobody can "
                     "compute them)")
        lines.append("-" * 60)
        for name in sorted(unavailable):
            lines.append(f"  {name}")
            lines.append(f"        {unavailable[name]}")

    for title, breakdown in (("PER STRATUM", per_stratum),
                             ("PER SECTOR", per_sector)):
        lines.append("")
        lines.append(title)
        lines.append("-" * 60)
        if not breakdown:
            lines.append(
                f"  NOT REPORTED. This run supplied no {title.lower()} "
                f"breakdown, so these gates are aggregate-only -- which is "
                f"exactly what a {title.lower()} table exists to prevent "
                f"(Task 7.2: an aggregate number hides that you are excellent "
                f"on crude and useless on policy).")
            continue
        for key in sorted(breakdown):
            body = ", ".join(f"{name}={_render_value(value)}"
                             for name, value in sorted(breakdown[key].items()))
            lines.append(f"  {key}: {body}")
    return "\n".join(lines)


def _render_value(value: Any) -> str:
    if value is None:
        return "unmeasured"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


# ---------------------------------------------------------------------------
# the runnable evaluator
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the V5 shipping gates. Non-zero exit blocks a "
                    "release; exit 3 means a hard zero was violated.")
    parser.add_argument("--metrics", required=True,
                        help="JSON file: {\"metrics\": {...}} as produced by "
                             "eval.harness.MetricReport.gate_metrics()")
    parser.add_argument("--baseline", default=None,
                        help=f"baseline JSON (default: {BASELINE_PATH})")
    parser.add_argument("--no-baseline", action="store_true",
                        help="evaluate without the no-regression comparison; it "
                             "is then REFUSED, never passed")
    parser.add_argument("--gates", default=None,
                        help=f"gate policy YAML (default: {GATES_PATH})")
    parser.add_argument("--skip-delegated", action="store_true",
                        help="do not run the delegated Phase 0 suites. They "
                             "become DELEGATED_NOT_RUN, which still blocks -- "
                             "this is a speed switch, not a way to pass")
    args = parser.parse_args(argv)

    source = Path(args.metrics)
    if not source.exists():
        print(f"REFUSING TO EVALUATE: no metrics file at {source}. Run the "
              f"harness first (eval.harness) -- and note that it refuses to "
              f"score an empty corpus, which is the deployed state "
              f"(DATA_GAPS section 1).", file=sys.stderr)
        return EXIT_CANNOT_RUN

    payload = json.loads(source.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", payload)

    try:
        baseline = None if args.no_baseline else load_baseline(args.baseline)
        report = evaluate_gates(metrics, baseline=baseline,
                                gates_path=args.gates,
                                run_delegated=not args.skip_delegated)
    except GateConfigError as exc:
        print(f"REFUSING TO EVALUATE: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    print(render_report(report, per_stratum=payload.get("per_stratum"),
                        per_sector=payload.get("per_sector"),
                        unavailable=payload.get("unavailable")))
    if report.hard_violations:
        print("\nHARD ZERO VIOLATED -- this is an integrity failure, not a "
              "quality miss. Do not relax the gate.", file=sys.stderr)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
