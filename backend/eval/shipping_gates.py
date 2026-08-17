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
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

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

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2
EXIT_HARD_ZERO = 3


class GateConfigError(ValueError):
    """A shipping-gate config that must not be loaded."""


@dataclass(frozen=True)
class DelegatedSuite:
    """A gate answered by an existing test rather than by a metric.

    Reducer determinism over 10,000 permutations and market/fundamental
    isolation are already proven by Phase 0's suites. Recomputing them here
    would be a second implementation of the same property that could drift
    from the first; NAMING the suite keeps one answer and makes the
    delegation visible instead of implicit.
    """
    path: str
    test_name: str


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
    def hard_violations(self) -> tuple[GateOutcome, ...]:
        return tuple(o for o in self.failures if o.hard)

    @property
    def exit_code(self) -> int:
        if self.hard_violations:
            return EXIT_HARD_ZERO
        if self.failures or self.refusals:
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


#: gate name -> the suite that answers it.
DELEGATED_SUITES: dict[str, DelegatedSuite] = {
    spec.name: spec.delegated for spec in load_gate_specs() if spec.delegated}


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------

_COMPARISONS = {
    ">=": lambda value, threshold: value >= threshold,
    "<=": lambda value, threshold: value <= threshold,
    "==": lambda value, threshold: value == threshold,
}


def _evaluate_one(spec: GateSpec, metrics: Mapping[str, Any]) -> GateOutcome:
    if spec.name not in metrics or metrics[spec.name] is None:
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
                   gates_path: Path | str | None = None) -> GateReport:
    """Evaluate EVERY gate. Nothing is skipped for being unmeasurable -- an
    unmeasurable gate is reported as REFUSED, which blocks."""
    resolved = tuple(specs) if specs is not None else load_gate_specs(gates_path)
    outcomes = [_evaluate_one(spec, metrics) for spec in resolved]
    outcomes.append(_evaluate_no_regression(
        metrics, baseline, _no_regression_metrics(gates_path)))
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
                  per_sector: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """The gate table, then the breakdowns.

    Task 7.2's DO NOT is inherited here: never report only aggregate. When a
    breakdown is absent this SAYS SO rather than quietly printing the
    aggregate alone, because an aggregate presented as the whole answer is
    how "excellent on crude, useless on policy" stays invisible.
    """
    lines = ["SHIPPING GATES", "=" * 60]
    for outcome in report.outcomes:
        mark = {PASS: "PASS  ", FAIL: "FAIL  ", REFUSED: "REFUSE"}[outcome.status]
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
        report = evaluate_gates(metrics, baseline=baseline)
    except GateConfigError as exc:
        print(f"REFUSING TO EVALUATE: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    print(render_report(report, per_stratum=payload.get("per_stratum"),
                        per_sector=payload.get("per_sector")))
    if report.hard_violations:
        print("\nHARD ZERO VIOLATED -- this is an integrity failure, not a "
              "quality miss. Do not relax the gate.", file=sys.stderr)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
