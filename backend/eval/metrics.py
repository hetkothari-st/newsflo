"""TASK 7.2 -- the metric suite. Pure functions over (labels, V5 outputs).

EVERY METRIC HERE OBEYS ONE RULE: a rate with a zero denominator is `None`.
Not 0.0, not 1.0. "We measured nothing" and "we measured perfectly" are
different sentences, and a harness that renders the first as the second is
the most expensive bug this phase could ship -- it would make an empty
corpus look like a passing one.

TWO HELPERS ARE BORROWED, NOT REIMPLEMENTED. Cohen's kappa and the numeral
tokenizer live in Session 0's `scripts/score_baseline.py`; two
implementations of one statistic is two answers to one question. The rest of
that scorer is untouched: it scores the V4 system for Gate Zero and reads
`alert_companies`, while everything here reads the V5 record set.

REPORTING IS PER STRATUM AND PER SECTOR, ALWAYS. `MetricReport` cannot be
constructed without both breakdowns -- Task 7.2's "an aggregate number hides
that you are excellent on crude and useless on policy", expressed as a
required constructor argument rather than as advice.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.analysis.calibration import metrics as _calibration
from scripts.score_baseline import numerals as _numeral_tokens

TIER_PRIMARY = "PRIMARY"
TIER_SECONDARY = "SECONDARY_RIPPLE"
TIER_ABSENT = "ABSENT"

#: The label vocabulary (Session 0's `DIRECTIONS`) mapped onto the record's
#: own `net_effect` vocabulary. MIXED and UNCERTAIN map to themselves and are
#: deliberately NOT directions: invariant 9 forbids collapsing MIXED into one.
DIRECTION_MAP = {
    "bullish": "POSITIVE",
    "bearish": "NEGATIVE",
    "mixed": "MIXED",
    "uncertain": "UNCERTAIN",
}
DIRECTIONAL = ("POSITIVE", "NEGATIVE")


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rate:
    """A measurement AND its denominator. The denominator travels with the
    value because a precision of 1.0 over two events and over three hundred
    are not the same claim."""
    numerator: float
    denominator: float

    @property
    def value(self) -> float | None:
        if not self.denominator:
            return None
        return self.numerator / self.denominator

    def describe(self) -> str:
        if not self.denominator:
            return "no denominator (0 of 0) -- nothing was measured"
        return f"{self.value:.4f} ({self.numerator:g} of {self.denominator:g})"


@dataclass(frozen=True)
class PrecisionRecall:
    tp: int
    fp: int
    fn: int
    excluded: int = 0

    @property
    def precision(self) -> Rate:
        return Rate(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Rate:
        return Rate(self.tp, self.tp + self.fn)


@dataclass(frozen=True)
class ScoredPair:
    """One (event, company) comparison.

    `expected_tier is None` means the pair is EXCLUDED -- DISPUTED, or a
    disagreement nobody adjudicated. It is counted in `excluded` and enters
    no numerator and no denominator (Task 7.1: "excluded from precision
    denominators ... tracked separately").
    """
    event_id: str
    stratum: str
    sector: str | None
    company_ref: str
    expected_tier: str | None
    published_tier: str
    expected_direction: str | None = None
    published_direction: str | None = None
    expected_mechanism: str | None = None
    published_mechanism: str | None = None
    expected_materiality: str | None = None
    published_materiality: str | None = None
    expected_section: str | None = None
    published_section: str | None = None
    expected_directness: str | None = None
    published_directness: str | None = None
    expected_distance: Any = None
    published_distance: Any = None
    expected_evidence: str | None = None
    published_evidence: str | None = None
    #: True when the objection that examined this company came from a
    #: different model than the generator (section 12.4). None when nothing
    #: verified it -- which is the deployed state (DATA_GAPS section 10.2).
    cross_model: bool | None = None


def group_by(pairs: Sequence[ScoredPair], attribute: str,
             metric: Callable[[Sequence[ScoredPair]], Any]) -> dict[str, Any]:
    """Split by `stratum` or `sector` and apply `metric` to each group."""
    buckets: dict[str, list[ScoredPair]] = defaultdict(list)
    for pair in pairs:
        buckets[str(getattr(pair, attribute))].append(pair)
    return {key: metric(buckets[key]) for key in sorted(buckets)}


# ---------------------------------------------------------------------------
# tier precision / recall
# ---------------------------------------------------------------------------

def tier_precision_recall(pairs: Sequence[ScoredPair], tier: str) -> PrecisionRecall:
    tp = fp = fn = excluded = 0
    for pair in pairs:
        if pair.expected_tier is None:
            excluded += 1
            continue
        expected = pair.expected_tier == tier
        published = pair.published_tier == tier
        if expected and published:
            tp += 1
        elif published:
            fp += 1
        elif expected:
            fn += 1
    return PrecisionRecall(tp=tp, fp=fp, fn=fn, excluded=excluded)


def verification_precision_split(pairs: Sequence[ScoredPair],
                                 tier: str = TIER_PRIMARY) -> dict[str, PrecisionRecall]:
    """Section 12.4's split. A falsifier running on the generator's own model
    is a weaker check than one running on a different model, and the only
    honest way to say so is to report the two precisions separately."""
    classes = {"CROSS_MODEL": True, "SAME_MODEL": False, "UNVERIFIED": None}
    return {name: tier_precision_recall(
        [p for p in pairs if p.cross_model is flag], tier)
        for name, flag in classes.items()}


# ---------------------------------------------------------------------------
# direction and the accuracy family
# ---------------------------------------------------------------------------

def _expected_effect(pair: ScoredPair) -> str | None:
    if not pair.expected_direction:
        return None
    return DIRECTION_MAP.get(str(pair.expected_direction).lower())


def wrong_direction_rate(pairs: Sequence[ScoredPair],
                         tier: str = TIER_PRIMARY) -> Rate:
    """Among published records of `tier` where BOTH sides state a DIRECTION,
    the share that point opposite ways.

    A MIXED or UNCERTAIN answer on either side leaves the denominator: it is
    not a wrong direction, it is a refusal to give one, and scoring it as an
    error would push the system toward guessing (invariant 9).
    """
    wrong = total = 0
    for pair in pairs:
        if pair.expected_tier is None or pair.published_tier != tier:
            continue
        expected = _expected_effect(pair)
        published = pair.published_direction
        if expected not in DIRECTIONAL or published not in DIRECTIONAL:
            continue
        total += 1
        if expected != published:
            wrong += 1
    return Rate(wrong, total)


def economic_effect_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    """The FULL effect vocabulary, MIXED and UNCERTAIN included. This is the
    metric that notices a system quietly converting every MIXED into a
    direction; `wrong_direction_rate` by construction cannot."""
    hit = total = 0
    for pair in pairs:
        if pair.expected_tier is None:
            continue
        expected = _expected_effect(pair)
        if expected is None or pair.published_direction is None:
            continue
        total += 1
        if expected == pair.published_direction:
            hit += 1
    return Rate(hit, total)


def _attribute_accuracy(pairs: Sequence[ScoredPair], expected_field: str,
                        published_field: str) -> Rate:
    """Counts ONLY pairs whose label states the attribute.

    A label that says nothing about a mechanism is not evidence that the
    published mechanism is right, and it is not evidence that it is wrong.
    It is silence, and silence belongs in neither the numerator nor the
    denominator.
    """
    hit = total = 0
    for pair in pairs:
        if pair.expected_tier is None:
            continue
        expected = getattr(pair, expected_field)
        if expected is None or expected == "":
            continue
        total += 1
        if _canonical(expected) == _canonical(getattr(pair, published_field)):
            hit += 1
    return Rate(hit, total)


def _canonical(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().upper()


def mechanism_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    return _attribute_accuracy(pairs, "expected_mechanism", "published_mechanism")


def materiality_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    return _attribute_accuracy(pairs, "expected_materiality", "published_materiality")


def directness_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    return _attribute_accuracy(pairs, "expected_directness", "published_directness")


def distance_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    return _attribute_accuracy(pairs, "expected_distance", "published_distance")


def evidence_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    return _attribute_accuracy(pairs, "expected_evidence", "published_evidence")


def section_accuracy(pairs: Sequence[ScoredPair]) -> Rate:
    return _attribute_accuracy(pairs, "expected_section", "published_section")


# ---------------------------------------------------------------------------
# the null slice
# ---------------------------------------------------------------------------

NULL_STRATUM = "null_event"


def abstention_precision(events: Iterable[Mapping[str, Any]]) -> Rate:
    """Of the null events, the share on which the system published NOTHING
    at PRIMARY. Task 7.1: "the only thing that measures whether the system
    can say nothing"."""
    nulls = [e for e in events if e.get("stratum") == NULL_STRATUM]
    silent = sum(1 for e in nulls if not int(e.get("primary_count") or 0))
    return Rate(silent, len(nulls))


def null_event_primary_false_positives(events: Iterable[Mapping[str, Any]]) -> int:
    """A COUNT, deliberately. The hard-zero gate is `== 0`, and a rate would
    make one false positive in three hundred events look like 0.003 instead
    of like the integrity failure it is."""
    return sum(int(e.get("primary_count") or 0)
               for e in events if e.get("stratum") == NULL_STRATUM)


# ---------------------------------------------------------------------------
# ripple families
# ---------------------------------------------------------------------------

def ripple_family_recall(entries: Iterable[Mapping[str, Any]]) -> Rate:
    """Expected families (the labelers' event-level statement) that the
    published record set actually reached. Pooled across events, so a wide
    event and a narrow one weigh by the number of families each expected."""
    hit = total = 0
    for entry in entries:
        expected = {str(f).strip().lower() for f in entry.get("expected") or ()}
        published = {str(f).strip().lower() for f in entry.get("published") or ()}
        total += len(expected)
        hit += len(expected & published)
    return Rate(hit, total)


# ---------------------------------------------------------------------------
# integrity metrics
# ---------------------------------------------------------------------------

def firewall_deletion_rate(outputs: Iterable[Mapping[str, Any]],
                           tier: str = TIER_PRIMARY) -> Rate:
    """Deleted sentences over sentences examined, on the named tier. Spec
    section 17.2 gates this at exactly 0 for PRIMARY prose: a deletion means
    a compiled sentence said something the records did not."""
    deletions = examined = 0
    for output in outputs:
        if output.get("publication_tier") != tier:
            continue
        deletions += int(output.get("deletions") or 0)
        examined += int(output.get("sentences_total") or 0)
    return Rate(deletions, examined)


def fabricated_numerals(text: str | None,
                        record_numerals: Iterable[Any]) -> list[str]:
    """Numeral TOKENS in `text` that are not in the record set.

    SET MEMBERSHIP, not substring containment -- Session 0's fix, reused
    rather than rewritten: `37` is not "in" `1370`, and a containment check
    would let a fabricated figure through whenever some longer unrelated
    number happened to carry its digits. This feeds a HARD-ZERO gate, so a
    false negative here is the most expensive bug in the harness.
    """
    known: set[str] = set()
    for value in record_numerals:
        known.update(_numeral_tokens(str(value)))
    return [token for token in _numeral_tokens(text) if token not in known]


def fabricated_numeral_rate(outputs: Iterable[Mapping[str, Any]]) -> Rate:
    """Share of published records whose prose carries a numeral the record
    set does not. Per RECORD, not per numeral: one fabricated figure ruins
    the record it is in, and averaging it over the honest numerals beside it
    would make a fabrication look small."""
    bad = total = 0
    for output in outputs:
        total += 1
        if fabricated_numerals(output.get("prose"),
                               output.get("record_numerals") or ()):
            bad += 1
    return Rate(bad, total)


def _directional_claim_floor() -> float:
    from app.core.config_loader import load_sensitivity_policy

    return float(load_sensitivity_policy().directional_claim_min)


def internal_contradictions(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Every way one canonical record can disagree with itself.

    Each is NAMED. A contradiction rate is a number nobody can act on; a
    histogram of named contradictions points at the stage that produced one.
    """
    found: list[str] = []
    tier = str(record.get("publication_tier") or "")
    net_effect = str(record.get("net_effect") or "")
    reason = record.get("rejection_reason")

    if net_effect in DIRECTIONAL:
        consistency = record.get("sign_consistency")
        if consistency is not None and float(consistency) < _directional_claim_floor():
            found.append("DIRECTIONAL_CLAIM_BELOW_SIGN_CONSISTENCY")

    if tier and tier != "REJECTED" and reason:
        found.append("PUBLISHED_WITH_A_REJECTION_REASON")
    if tier == "REJECTED" and not reason:
        found.append("REJECTED_WITHOUT_A_REASON")

    if net_effect in DIRECTIONAL:
        opposite = "POSITIVE" if net_effect == "NEGATIVE" else "NEGATIVE"
        for entry in (record.get("direction_by_horizon") or {}).values():
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("direction") or "") == opposite:
                found.append("HEADLINE_CONTRADICTS_ITS_HORIZONS")
                break

    return tuple(found)


def internal_contradiction_rate(records: Sequence[Mapping[str, Any]]) -> Rate:
    """Share of records carrying at least one contradiction. Per RECORD: a
    record with two contradictions is one broken record, and counting them
    twice would make the hard-zero gate depend on how many ways we happen to
    check."""
    bad = sum(1 for record in records if internal_contradictions(record))
    return Rate(bad, len(records))


# ---------------------------------------------------------------------------
# calibration -- machinery only; calibration itself is DISABLED (Phase 5)
# ---------------------------------------------------------------------------

def _split(pairs: Sequence[tuple[float, int]]) -> tuple[list[float], list[int]]:
    return [float(p) for p, _ in pairs], [int(y) for _, y in pairs]


def calibration_ece(pairs: Sequence[tuple[float, int]], *, bins: int = 10) -> float | None:
    """Expected calibration error over (probability, outcome) pairs.

    Returns None over an empty set. `calibrated_p` is null on every record in
    this repo (Phase 5 disabled and locked calibration), so the deployed
    answer is None and the harness reports it as UNAVAILABLE.
    """
    if not pairs:
        return None
    probs, labels = _split(pairs)
    return _calibration.expected_calibration_error(probs, labels, bins=bins)


def calibration_brier(pairs: Sequence[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    probs, labels = _split(pairs)
    return _calibration.brier_score(probs, labels)


calibration_ece.__wrapped_metric__ = _calibration.expected_calibration_error
calibration_brier.__wrapped_metric__ = _calibration.brier_score


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

#: gate-config spelling -> report spelling. Mostly identical; the one
#: divergence is deliberate. The METRIC is "section accuracy" (how often a
#: record is where the labels say it belongs) and the GATE is spelled
#: "section assignment accuracy" in spec section 17.2. Renaming either to
#: match the other would edit a frozen document; mapping them is honest and
#: keeps both readable in their own context.
GATE_METRIC_KEYS = {
    "primary_precision": "primary_precision",
    "primary_wrong_direction_rate": "primary_wrong_direction_rate",
    "primary_false_positives_on_null_events":
        "primary_false_positives_on_null_events",
    "secondary_ripple_recall": "secondary_ripple_recall",
    "secondary_ripple_precision": "secondary_ripple_precision",
    "ripple_family_recall": "ripple_family_recall",
    "fabricated_numeral_rate": "fabricated_numeral_rate",
    "firewall_deletion_rate_primary_prose": "firewall_deletion_rate_primary_prose",
    "internal_contradiction_rate": "internal_contradiction_rate",
    "calibration_ece": "calibration_ece",
    "section_assignment_accuracy": "section_accuracy",
}


@dataclass(frozen=True)
class MetricReport:
    """Aggregate AND both breakdowns. `per_stratum` and `per_sector` have no
    defaults on purpose: a report that could be built without them is a
    report somebody will build without them (Task 7.2's DO NOT)."""
    aggregate: Mapping[str, Any]
    per_stratum: Mapping[str, Mapping[str, Any]]
    per_sector: Mapping[str, Mapping[str, Any]]
    #: metric name -> why it could not be computed. Never a number.
    unavailable: Mapping[str, str] = field(default_factory=dict)
    #: labeled events with no V5 output at all -- in no metric above.
    unscored: tuple[str, ...] = ()
    #: (event_id, company_ref) pairs excluded as DISPUTED or unadjudicated.
    excluded_pairs: tuple[tuple[str, str], ...] = ()
    events_scored: int = 0

    def gate_metrics(self) -> dict[str, Any]:
        """The metric set the shipping-gate evaluator reads. Absent keys stay
        absent (the evaluator REFUSES them); nothing is defaulted to a
        passing value."""
        out: dict[str, Any] = {}
        for gate_key, report_key in GATE_METRIC_KEYS.items():
            if report_key in self.aggregate:
                out[gate_key] = self.aggregate[report_key]
        return out
