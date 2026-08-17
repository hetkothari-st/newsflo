"""TASKS 7.1 / 7.2 -- the evaluation harness.

WHAT IT DOES. Given a labeled event and the stage outputs for that event, it
runs the V5 canonical path -- falsifier (optional, injected client) ->
reducer -> publication gate -> section engine -> compiler -> entailment
firewall -- and scores what came out against what the labelers expected, per
stratum and per sector.

IT RUNS ENTIRELY OFFLINE. The two stages that would call a model take an
INJECTED client and are simply absent when nobody injects one, so "zero API
calls" is a property of the code rather than of a mock. Nothing here opens a
socket, constructs a provider client, or reads a clock.

IT IS NOT SESSION 0'S SCORER, and the two must not be merged.
`scripts/score_baseline.py` scores the V4 system for Gate Zero: it reads
`alert_companies`, applies the V4 tier derivation, and writes `BASELINE.md`.
This scores the V5 canonical path: `company_impact`, the V5 gate, the V5
section engine. Two scorers, one corpus, both documented. What IS shared is
deliberate and minimal: Cohen's kappa and the numeral tokenizer are imported
from Session 0 rather than reimplemented, because two implementations of one
statistic is two answers to one question.

THE CORPUS IS EMPTY. Every entry point here refuses loudly on an empty
corpus (`HarnessRefusal`) instead of returning a rate over zero events. A
precision of 1.0 over nothing is the single most dangerous number this file
could produce, because it looks exactly like success.

WHAT CANNOT BE MEASURED IS NAMED. Session 0's `eval_label` (unmodified,
per this phase's constraints) carries an expected tier, direction, mechanism
and materiality -- and no expected directness, distance, evidence grade or
section. Those four metrics therefore exist as functions, are unit-tested,
and are reported as UNAVAILABLE with the reason. Reporting them as 100%
because nothing disagreed would be a lie with a decimal point on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import sqlalchemy as sa

from app.core.claims import Claim, Evidence
from app.core.config_loader import load_gate_config
from app.core.reducer import (
    CompanyImpact, EventContext, ReducerConfig, reduce_company_impact,
    serialize_company_impact,
)
from app.core.signals import make_signal
from app.eval import store
from app.eval.families import load_family_map, normalize_family, resolve_family
from app.eval.schema import STRATA
from app.output import compiler, firewall
from app.output.section_config import load_section_taxonomy
from app.output.sections import (
    build_sections, render_zero_primary, section_key_for, serialize_sections,
    zero_primary_state,
)
from eval import metrics as M
from eval.cost_ledger import FRONTIER, CallLedger, StageCache
from scripts.score_baseline import cohens_kappa, kappa_over_corpus

HARNESS_VERSION = "h7.0.0"

#: Task 7.1's stratification.
REQUIRED_EVENTS = 300
REQUIRED_NULL_EVENTS = 50
MIN_LABELERS = 2
NULL_STRATUM = "null_event"

#: The harness synthesizes signals (the falsifier's objections) and every
#: signal carries a timestamp. It must not read a clock -- two runs of one
#: bundle have to produce byte-identical records -- so synthesized signals
#: carry this constant instead. It is not a claim about when anything
#: happened; it is the absence of one.
HARNESS_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)

TIER_PRIMARY = "PRIMARY"
TIER_SECONDARY = "SECONDARY_RIPPLE"
TIER_REJECTED = "REJECTED"
TIER_ABSENT = "ABSENT"

METRIC_NAMES = (
    "primary_precision", "primary_recall",
    "secondary_ripple_precision", "secondary_ripple_recall",
    "primary_wrong_direction_rate", "economic_effect_accuracy",
    "mechanism_accuracy", "directness_accuracy", "distance_accuracy",
    "materiality_accuracy", "evidence_accuracy", "section_accuracy",
    "abstention_precision", "primary_false_positives_on_null_events",
    "calibration_ece", "calibration_brier", "ripple_family_recall",
    "firewall_deletion_rate_primary_prose", "fabricated_numeral_rate",
    "internal_contradiction_rate",
    "cross_model_primary_precision", "same_model_primary_precision",
)

#: metric -> why the deployed system cannot produce it. Each of these is a
#: MISSING INPUT with a named owner, not a bug and not a zero.
UNAVAILABLE_REASONS = {
    "directness_accuracy":
        "eval_label carries no expected_directness column (Session 0's schema, "
        "unmodified). Nobody has ever labeled a causal directness, so there is "
        "nothing to be accurate against. DATA_GAPS section 11.",
    "distance_accuracy":
        "eval_label carries no expected graph_distance column (Session 0's "
        "schema, unmodified). DATA_GAPS section 11.",
    "evidence_accuracy":
        "eval_label carries no expected evidence grade column (Session 0's "
        "schema, unmodified). DATA_GAPS section 11.",
    "section_accuracy":
        "a section key is (tier, effect, mechanism, horizon bucket) and "
        "eval_label states no expected horizon, so no expected section can be "
        "formed from the labels this repo holds. DATA_GAPS section 11.",
    "calibration_ece":
        "calibration is DISABLED and structurally locked (Phase 5): every "
        "record's calibrated probability is null, so there are no "
        "(probability, outcome) pairs to bin. DATA_GAPS section 9.4.",
    "calibration_brier":
        "calibration is DISABLED and structurally locked (Phase 5): no "
        "calibrated probability exists on any record. DATA_GAPS section 9.4.",
}


class HarnessRefusal(Exception):
    """An input the harness will not turn into a number."""


# ---------------------------------------------------------------------------
# TASK 7.1 -- corpus integrity
# ---------------------------------------------------------------------------

_EMPTY_CORPUS = (
    "the Gate Zero corpus is EMPTY: {what}. Load one "
    "(backend/tools/eval_import.py) or label one (backend/tools/eval_ui.py) "
    "before measuring anything. No metric was computed -- a precision over "
    "zero events is not a small number, it is no number, and reporting one "
    "would be worse than reporting nothing. See DATA_GAPS.md section 1."
)


@dataclass(frozen=True)
class Requirement:
    name: str
    required: Any
    actual: Any
    met: bool
    detail: str = ""


@dataclass(frozen=True)
class CorpusIntegrity:
    events_total: int
    per_stratum: Mapping[str, int]
    null_events: int
    strata_missing: tuple[str, ...]
    under_labeled: tuple[tuple[str, int], ...]
    disputed_pairs: tuple[tuple[str, str], ...]
    kappa: float | None
    kappa_pairs: int
    kappa_note: str
    requirements: tuple[Requirement, ...]

    @property
    def meets_requirements(self) -> bool:
        return all(r.met for r in self.requirements)


def _refuse_if_empty(conn: sa.Connection) -> list[dict[str, Any]]:
    events = store.all_events(conn)
    if not events:
        raise HarnessRefusal(_EMPTY_CORPUS.format(
            what="eval_event holds no events"))
    labels = conn.execute(sa.text("SELECT COUNT(*) FROM eval_label")).scalar()
    event_labels = conn.execute(
        sa.text("SELECT COUNT(*) FROM eval_event_label")).scalar()
    if not labels and not event_labels:
        raise HarnessRefusal(_EMPTY_CORPUS.format(
            what=f"{len(events)} event(s) are loaded but eval_label and "
                 f"eval_event_label hold no label at all"))
    return events


def corpus_integrity(conn: sa.Connection) -> CorpusIntegrity:
    """Task 7.1's rules, evaluated and REPORTED rather than assumed.

    Every rule that fails comes back as an unmet `Requirement` naming what is
    required and what is there. The report is the honest form of "the corpus
    is not ready": a boolean would hide which of the four rules failed, and
    the four have different owners and different costs.
    """
    events = _refuse_if_empty(conn)
    per_stratum = {stratum: 0 for stratum in STRATA}
    for event in events:
        per_stratum[event["stratum"]] = per_stratum.get(event["stratum"], 0) + 1

    under_labeled: list[tuple[str, int]] = []
    disputed: list[tuple[str, str]] = []
    for event in events:
        event_id = event["event_id"]
        labelers = store.labelers_for_event(conn, event_id)
        if len(labelers) < MIN_LABELERS:
            under_labeled.append((event_id, len(labelers)))
        for company_ref, entry in store.adjudications_for_event(conn, event_id).items():
            if entry["resolution"] == "DISPUTED":
                disputed.append((event_id, company_ref))

    kappa, pairs, note = kappa_over_corpus(conn)
    if kappa is None and not note:
        note = ("kappa is undefined over this corpus: with no variance in the "
                "expected tiers, chance agreement is 1 and the statistic "
                "carries no information. Reported as undefined rather than "
                "as 1.0.")

    missing = tuple(s for s in STRATA if not per_stratum.get(s))
    requirements = (
        Requirement("event_count", REQUIRED_EVENTS, len(events),
                    len(events) >= REQUIRED_EVENTS),
        Requirement("null_event_count", REQUIRED_NULL_EVENTS,
                    per_stratum.get(NULL_STRATUM, 0),
                    per_stratum.get(NULL_STRATUM, 0) >= REQUIRED_NULL_EVENTS,
                    detail="the only stratum that measures whether the system "
                           "can say nothing"),
        Requirement("every_stratum_represented", len(STRATA),
                    len(STRATA) - len(missing), not missing,
                    detail=", ".join(missing)),
        Requirement("two_labelers_per_event", MIN_LABELERS, len(under_labeled),
                    not under_labeled,
                    detail="events with fewer than two independent labelers: "
                           + ", ".join(e for e, _ in under_labeled)),
        Requirement("kappa_reported", "a number", kappa, kappa is not None,
                    detail=note),
    )
    return CorpusIntegrity(
        events_total=len(events), per_stratum=per_stratum,
        null_events=per_stratum.get(NULL_STRATUM, 0), strata_missing=missing,
        under_labeled=tuple(under_labeled), disputed_pairs=tuple(disputed),
        kappa=kappa, kappa_pairs=pairs, kappa_note=note,
        requirements=requirements)


# ---------------------------------------------------------------------------
# expectations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventExpectation:
    event_id: str
    stratum: str
    article_ref: str
    labelers: tuple[str, ...]
    #: company_ref -> expected tier, for pairs the labelers RESOLVED.
    expected_tiers: Mapping[str, str]
    directions: Mapping[str, str]
    mechanisms: Mapping[str, str]
    materialities: Mapping[str, str]
    #: adjudicated DISPUTED -- honest ambiguity, excluded from denominators.
    disputed: frozenset[str]
    #: disagreed and never adjudicated -- also excluded, tracked separately,
    #: because "we disagree" and "we have not looked" are different states.
    unresolved: frozenset[str]
    #: the families BOTH labelers expected (intersection, Session 0's rule).
    ripple_families: frozenset[str]


def load_expectations(conn: sa.Connection) -> tuple[EventExpectation, ...]:
    """Resolve two labelers' opinions into one expectation per event.

    An event with fewer than two labelers produces NO expectation at all
    (Task 7.1's second DO NOT: never a single labeler). A company the two
    labelers disagreed about produces no expected tier: it is DISPUTED if an
    adjudicator said so and UNRESOLVED if nobody has looked, and either way
    it leaves the precision denominator rather than being decided by
    whichever labeler is listed first.
    """
    events = _refuse_if_empty(conn)
    out: list[EventExpectation] = []
    for event in events:
        event_id = event["event_id"]
        labelers = store.labelers_for_event(conn, event_id)
        if len(labelers) < MIN_LABELERS:
            continue
        primary_two = tuple(labelers[:MIN_LABELERS])
        adjudications = store.adjudications_for_event(conn, event_id)

        by_company: dict[str, dict[str, dict[str, Any]]] = {}
        for row in store.labels_for_event(conn, event_id):
            by_company.setdefault(row["company_ref"], {})[row["labeler"]] = row

        tiers: dict[str, str] = {}
        directions: dict[str, str] = {}
        mechanisms: dict[str, str] = {}
        materialities: dict[str, str] = {}
        disputed: set[str] = set()
        unresolved: set[str] = set()

        for company_ref, rows in by_company.items():
            present = [who for who in primary_two if who in rows]
            stated = {rows[who]["expected_tier"] for who in present}
            # A labeler who did not name this company, on an event they DID
            # label, is asserting ABSENT for it -- that is precisely what a
            # correct null label looks like, and reading it as silence would
            # make the null slice unmeasurable.
            if len(present) < len(primary_two):
                stated |= {TIER_ABSENT}
            adjudication = adjudications.get(company_ref)
            resolution = adjudication["resolution"] if adjudication else None
            if resolution == "DISPUTED":
                disputed.add(company_ref)
                continue
            if resolution in ("LABELER_A", "LABELER_B"):
                who = primary_two[0 if resolution == "LABELER_A" else 1]
                row = rows.get(who)
                if row is None:
                    unresolved.add(company_ref)
                    continue
                tiers[company_ref] = row["expected_tier"]
            elif len(stated) == 1:
                tiers[company_ref] = next(iter(stated))
            else:
                unresolved.add(company_ref)
                continue
            _agree_into(directions, company_ref, rows, primary_two,
                        "expected_direction")
            _agree_into(mechanisms, company_ref, rows, primary_two,
                        "expected_mechanism")
            _agree_into(materialities, company_ref, rows, primary_two,
                        "expected_materiality")

        families = _agreed_families(conn, event_id, primary_two)
        out.append(EventExpectation(
            event_id=event_id, stratum=event["stratum"],
            article_ref=event["article_ref"], labelers=primary_two,
            expected_tiers=tiers, directions=directions, mechanisms=mechanisms,
            materialities=materialities, disputed=frozenset(disputed),
            unresolved=frozenset(unresolved), ripple_families=families))
    return tuple(out)


def _agree_into(target: dict[str, str], company_ref: str,
                rows: Mapping[str, Mapping[str, Any]],
                labelers: Sequence[str], column: str) -> None:
    """Record an attribute only when the labelers who stated it AGREE.

    Two labelers naming different mechanisms is not an expectation, it is a
    disagreement, and scoring against either one would be picking a winner by
    row order.
    """
    stated = {rows[who][column] for who in labelers
              if who in rows and rows[who].get(column)}
    if len(stated) == 1:
        target[company_ref] = next(iter(stated))


def _agreed_families(conn: sa.Connection, event_id: str,
                     labelers: Sequence[str]) -> frozenset[str]:
    """The INTERSECTION of the two labelers' family sets -- Session 0's rule,
    reused: a family only one of them expected is ambiguity, not an
    expectation, and it belongs in the disputed count rather than in a recall
    denominator."""
    sets = [{normalize_family(f) for f in row["ripple_families"]}
            for row in store.event_labels_for_event(conn, event_id)
            if row["labeler"] in labelers]
    if len(sets) < MIN_LABELERS:
        return frozenset()
    return frozenset(set.intersection(*sets))


# ---------------------------------------------------------------------------
# the offline V5 path
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StageBundle:
    """One event's stage outputs, offline -- the same JSON shape Phase 0's
    fixture uses, so a bundle is readable and diffable by a human."""
    event_id: str
    analysis_version: str
    event_context: Mapping[str, Any]
    signals: tuple[Mapping[str, Any], ...]
    claims: tuple[Mapping[str, Any], ...] = ()
    evidence: tuple[Mapping[str, Any], ...] = ()
    stratum: str | None = None
    sectors: Mapping[int, str] = field(default_factory=dict)
    sub_sectors: Mapping[int, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "StageBundle":
        return cls(
            event_id=str(raw["event_id"]),
            analysis_version=str(raw["analysis_version"]),
            event_context=dict(raw.get("event_context") or {}),
            signals=tuple(raw.get("signals") or ()),
            claims=tuple(raw.get("claims") or ()),
            evidence=tuple(raw.get("evidence") or ()),
            stratum=raw.get("stratum"),
            sectors={int(k): v for k, v in (raw.get("sectors") or {}).items()},
            sub_sectors={int(k): v
                         for k, v in (raw.get("sub_sectors") or {}).items()})

    @property
    def company_ids(self) -> tuple[int, ...]:
        return tuple(sorted({int(s["company_id"]) for s in self.signals
                             if s.get("company_id") is not None}))


@dataclass(frozen=True)
class CompanyRecord:
    """One company's V5 answer, flattened to what the metrics read."""
    company_id: int | None
    ticker: str | None
    publication_tier: str
    rejection_reason: str | None
    net_effect: str
    sign_consistency: float
    materiality_bucket: str
    mechanism_id: str | None
    directness: str | None
    graph_distance: int | None
    discovery_source: str | None
    evidence_grade: str | None
    direction_by_horizon: Mapping[str, Any]
    section_key: str | None
    prose: str
    sentences_total: int
    deletions: int
    record_numerals: tuple[str, ...]
    cross_model: bool | None
    sector: str | None
    sub_sector: str | None
    impact: Any = None

    def as_contradiction_input(self) -> dict[str, Any]:
        return {
            "publication_tier": self.publication_tier,
            "net_effect": self.net_effect,
            "sign_consistency": self.sign_consistency,
            "rejection_reason": self.rejection_reason,
            "direction_by_horizon": self.direction_by_horizon,
        }


@dataclass(frozen=True)
class EventOutput:
    event_id: str
    stratum: str | None
    records: tuple[CompanyRecord, ...]
    sections: tuple[Any, ...]
    ledger: CallLedger

    @property
    def published(self) -> tuple[CompanyRecord, ...]:
        return tuple(r for r in self.records
                     if r.publication_tier in (TIER_PRIMARY, TIER_SECONDARY))

    @property
    def primary_count(self) -> int:
        return sum(1 for r in self.records if r.publication_tier == TIER_PRIMARY)

    @property
    def rejections(self) -> tuple[tuple[str | None, str | None], ...]:
        return tuple((r.ticker, r.rejection_reason) for r in self.records
                     if r.publication_tier == TIER_REJECTED)

    @property
    def published_families(self) -> frozenset[str]:
        """Families the RIPPLE half of the answer reached.

        SECONDARY_RIPPLE only, matching Session 0's scorer exactly. A family
        reached solely by a PRIMARY company is usually a company the article
        named, and counting it here would let the metric be satisfied by the
        very behaviour it exists to measure -- V4's failure was surfacing
        mentioned companies and missing exposed ones.
        """
        out: set[str] = set()
        for record in self.records:
            if record.publication_tier != TIER_SECONDARY:
                continue
            for value in (record.sub_sector, record.sector):
                if value:
                    out.add(normalize_family(value))
        return frozenset(out)

    @property
    def zero_primary_state(self) -> dict[str, Any]:
        return zero_primary_state([r.impact for r in self.records], self.sections)

    def render_zero_primary(self) -> str:
        return render_zero_primary(self.zero_primary_state, load_section_taxonomy())

    def serialize_sections(self) -> list[dict]:
        return serialize_sections(self.sections)


def _signals_for(bundle: StageBundle, company_id: int):
    return [make_signal(event_id=bundle.event_id, company_id=item["company_id"],
                        stage=item["stage"], kind=item["kind"],
                        payload=item["payload"], created_by=item["created_by"],
                        analysis_version=bundle.analysis_version,
                        created_at=HARNESS_EPOCH)
            for item in bundle.signals
            if item.get("company_id") == company_id]


def _claims_for(bundle: StageBundle, company_id: int) -> list[Claim]:
    return [Claim(claim_id=item["claim_id"], event_id=bundle.event_id,
                  company_id=item["company_id"], claim_type=item["claim_type"],
                  fact_class=item["fact_class"], structured=item["structured"],
                  evidence_ids=tuple(item["evidence_ids"]),
                  created_by=item["created_by"])
            for item in bundle.claims if item.get("company_id") == company_id]


def _evidence_for(bundle: StageBundle) -> list[Evidence]:
    return [Evidence(evidence_id=item["evidence_id"],
                     source_type=item["source_type"],
                     source_name=item["source_name"],
                     source_date=item["source_date"],
                     company_ids=tuple(item["company_ids"]),
                     quoted_text=item["quoted_text"],
                     fact_text=item["fact_text"])
            for item in bundle.evidence]


def _reducer_config(bundle: StageBundle) -> ReducerConfig:
    context = bundle.event_context
    return ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(
            event_status=context.get("event_status"),
            shock_magnitude_confidence=context.get("shock_magnitude_confidence"),
            exposure_stale=bool(context.get("exposure_stale")),
            policy_state_stale=bool(context.get("policy_state_stale"))))


def run_v5_path(bundle: StageBundle, *, falsifier_client: Any = None,
                judge: Any = None, ledger: CallLedger | None = None,
                cache: StageCache | None = None) -> EventOutput:
    """Reduce, gate, section, compile and firewall one event -- offline.

    THE FALSIFIER RUNS ONLY ON PRIMARY-ELIGIBLE DRAFTS, which is section 18's
    rung 4 and not an optimisation invented here: the adversary is the
    expensive stage and the strongest claim is the one worth attacking. A
    draft is reduced once, and only if it reaches PRIMARY is it argued with
    and reduced again with the objections folded in.

    With no client injected, no model is called and the objections are simply
    whatever the bundle already carried. That is a complete system, not a
    degraded one -- it is the deployed state (DATA_GAPS section 10.3).
    """
    ledger = ledger if ledger is not None else CallLedger()
    config = _reducer_config(bundle)
    evidence = _evidence_for(bundle)
    taxonomy = load_section_taxonomy()

    records: list[CompanyRecord] = []
    impacts: list[CompanyImpact] = []
    for company_id in bundle.company_ids:
        signals = _signals_for(bundle, company_id)
        claims = _claims_for(bundle, company_id)
        impact = reduce_company_impact(signals, config)

        cross_model: bool | None = None
        if falsifier_client is not None and impact.publication_tier == TIER_PRIMARY:
            objections, cross_model = _falsify(
                bundle, impact, company_id, falsifier_client, ledger, cache)
            if objections:
                impact = reduce_company_impact(signals + list(objections), config)

        impacts.append(impact)
        records.append(_record(bundle, impact, claims, evidence, judge,
                               cross_model, taxonomy))

    sections = build_sections(impacts, taxonomy)
    return EventOutput(event_id=bundle.event_id, stratum=bundle.stratum,
                       records=tuple(records), sections=sections, ledger=ledger)


def _falsify(bundle: StageBundle, impact: CompanyImpact, company_id: int,
             client: Any, ledger: CallLedger, cache: StageCache | None):
    from app.analysis.falsifier.config import load_falsifier_config
    from app.analysis.falsifier.engine import Falsifier

    policy = load_falsifier_config()
    counted = ledger.wrap(client, tier=FRONTIER, stage="FALSIFIER",
                          model_id=policy.model_id,
                          prompt_version=policy.prompt_lineage, cache=cache)
    falsifier = Falsifier(client=counted, policy=policy)
    result = falsifier.run(serialize_company_impact(impact))
    signals = falsifier.signals(result, event_id=bundle.event_id,
                                company_id=company_id,
                                analysis_version=bundle.analysis_version,
                                created_at=HARNESS_EPOCH)
    return signals, result.discipline.cross_model


def _record(bundle: StageBundle, impact: CompanyImpact, claims, evidence,
            judge, cross_model: bool | None, taxonomy) -> CompanyRecord:
    record_set = firewall.record_set_from(impact, claims, evidence)
    sentences = compiler.compile_prose(impact, claims)
    result = firewall.firewall(sentences, record_set, judge=judge,
                               fallback_text=compiler.fallback_text(impact, claims))
    key = section_key_for(impact)
    return CompanyRecord(
        company_id=impact.company_id, ticker=impact.ticker,
        publication_tier=impact.publication_tier,
        rejection_reason=impact.rejection_reason, net_effect=impact.net_effect,
        sign_consistency=impact.sign_consistency,
        materiality_bucket=impact.materiality_bucket,
        mechanism_id=impact.mechanism_id, directness=impact.directness,
        graph_distance=impact.graph_distance,
        discovery_source=impact.discovery_source,
        evidence_grade=impact.evidence_grade,
        direction_by_horizon=impact.direction_by_horizon,
        section_key="|".join(str(part) for part in key.as_tuple()),
        prose=result.text, sentences_total=result.sentences_total,
        deletions=len(result.deletions),
        record_numerals=tuple(str(n) for n in record_set.numerals),
        cross_model=cross_model,
        sector=bundle.sectors.get(int(impact.company_id or -1)),
        sub_sector=bundle.sub_sectors.get(int(impact.company_id or -1)),
        impact=impact)


def stored_event_output(conn: sa.Connection,
                        expectation: EventExpectation) -> EventOutput:
    """Read an event's ALREADY PERSISTED canonical records.

    The other half of the harness: `run_v5_path` measures what the pipeline
    WOULD produce from a bundle; this measures what it DID produce and
    stored. Both are needed -- the first can be run on any labeled event, the
    second is the only thing that can score a production run.
    """
    from app.core.impact_writer import event_id_for_article

    article = store.resolve_article(conn, expectation.article_ref)
    if article is None:
        raise HarnessRefusal(
            f"event {expectation.event_id} references article "
            f"{expectation.article_ref!r}, which is not in this database. "
            f"Reported rather than scored as a miss.")
    event_id = event_id_for_article(int(article["id"]))
    rows = conn.execute(sa.text(
        "SELECT company_id, ticker, publication_tier, rejection_reason, "
        "net_effect, sign_consistency, materiality_bucket, mechanism_id, "
        "directness, graph_distance, discovery_source, evidence_grade "
        "FROM company_impact WHERE event_id = :event"),
        {"event": event_id}).mappings().all()
    sectors = _sector_index(conn)
    records = tuple(
        CompanyRecord(
            company_id=row["company_id"], ticker=row["ticker"],
            publication_tier=row["publication_tier"],
            rejection_reason=row["rejection_reason"],
            net_effect=row["net_effect"] or "",
            sign_consistency=row["sign_consistency"] or 0,
            materiality_bucket=row["materiality_bucket"] or "",
            mechanism_id=row["mechanism_id"], directness=row["directness"],
            graph_distance=row["graph_distance"],
            discovery_source=row["discovery_source"],
            evidence_grade=row["evidence_grade"], direction_by_horizon={},
            section_key=None, prose="", sentences_total=0, deletions=0,
            record_numerals=(), cross_model=None,
            sector=sectors.get(row["company_id"], (None, None))[0],
            sub_sector=sectors.get(row["company_id"], (None, None))[1])
        for row in rows)
    return EventOutput(event_id=event_id, stratum=expectation.stratum,
                       records=records, sections=(), ledger=CallLedger())


def _sector_index(conn: sa.Connection) -> dict[int, tuple[str | None, str | None]]:
    return {row[0]: (row[1], row[2]) for row in conn.execute(
        sa.text("SELECT id, sector, sub_sector FROM companies"))}


# ---------------------------------------------------------------------------
# TASK 7.2 -- scoring
# ---------------------------------------------------------------------------

def build_pairs(conn: sa.Connection, expectation: EventExpectation,
                output: EventOutput) -> tuple[M.ScoredPair, ...]:
    """Join one event's labels to one event's records, by canonical ticker.

    The join is Session 0's: both sides are reduced to one spelling
    (`canonical_company_ref`, then `company_aliases`), because a labeler
    types RELIANCE and the universe stores RELIANCE.NS -- and without that,
    every expectation becomes a false negative and every publication a false
    positive, with real-looking denominators.

    A company that was published but never labeled is scored as expected
    ABSENT. That is the closed-world assumption the corpus protocol requires
    (labelers enumerate the expected set), and it is exactly what makes a
    false positive countable. It does NOT apply to a company the labelers
    disagreed about: that stays excluded.
    """
    index = store.load_company_index(conn)
    sectors_by_ticker = _sector_by_canonical(conn)

    published: dict[str, CompanyRecord] = {}
    for record in output.records:
        if record.publication_tier == TIER_REJECTED:
            continue
        published[store.canonical_company_ref(record.ticker or "")] = record

    excluded = expectation.disputed | expectation.unresolved
    company_refs = set(expectation.expected_tiers) | set(published) | excluded

    pairs: list[M.ScoredPair] = []
    for ref in sorted(company_refs):
        resolved, _reason = store.resolve_ref(index, ref)
        key = resolved or store.canonical_company_ref(ref)
        record = published.get(key) or published.get(ref)
        if ref in excluded:
            expected_tier = None
        else:
            expected_tier = expectation.expected_tiers.get(ref, TIER_ABSENT)
        sector = (record.sector if record and record.sector
                  else sectors_by_ticker.get(key, (None, None))[0])
        pairs.append(M.ScoredPair(
            event_id=expectation.event_id, stratum=expectation.stratum,
            sector=sector, company_ref=ref, expected_tier=expected_tier,
            published_tier=record.publication_tier if record else TIER_ABSENT,
            expected_direction=expectation.directions.get(ref),
            published_direction=record.net_effect if record else None,
            expected_mechanism=expectation.mechanisms.get(ref),
            published_mechanism=record.mechanism_id if record else None,
            expected_materiality=expectation.materialities.get(ref),
            published_materiality=record.materiality_bucket if record else None,
            published_section=record.section_key if record else None,
            published_directness=record.directness if record else None,
            published_distance=record.graph_distance if record else None,
            published_evidence=record.evidence_grade if record else None,
            cross_model=record.cross_model if record else None))
    return tuple(pairs)


def _sector_by_canonical(conn: sa.Connection) -> dict[str, tuple[str | None, str | None]]:
    return {store.canonical_company_ref(row[0] or ""): (row[1], row[2])
            for row in conn.execute(
                sa.text("SELECT ticker, sector, sub_sector FROM companies"))}


def _pair_metrics(pairs: Sequence[M.ScoredPair]) -> dict[str, Any]:
    primary = M.tier_precision_recall(pairs, TIER_PRIMARY)
    secondary = M.tier_precision_recall(pairs, TIER_SECONDARY)
    split = M.verification_precision_split(pairs, TIER_PRIMARY)
    return {
        "primary_precision": primary.precision.value,
        "primary_recall": primary.recall.value,
        "secondary_ripple_precision": secondary.precision.value,
        "secondary_ripple_recall": secondary.recall.value,
        "primary_wrong_direction_rate": M.wrong_direction_rate(pairs).value,
        "economic_effect_accuracy": M.economic_effect_accuracy(pairs).value,
        "mechanism_accuracy": M.mechanism_accuracy(pairs).value,
        "materiality_accuracy": M.materiality_accuracy(pairs).value,
        "directness_accuracy": M.directness_accuracy(pairs).value,
        "distance_accuracy": M.distance_accuracy(pairs).value,
        "evidence_accuracy": M.evidence_accuracy(pairs).value,
        "section_accuracy": M.section_accuracy(pairs).value,
        "cross_model_primary_precision": split["CROSS_MODEL"].precision.value,
        "same_model_primary_precision": split["SAME_MODEL"].precision.value,
    }


@dataclass(frozen=True)
class _EventSummary:
    stratum: str
    primary_count: int


def score(conn: sa.Connection, expectations: Sequence[EventExpectation],
          outputs: Mapping[str, EventOutput]) -> M.MetricReport:
    """Every metric Task 7.2 names, per stratum and per sector."""
    if not expectations:
        raise HarnessRefusal(_EMPTY_CORPUS.format(
            what="no event carries two independent labelers, so there is "
                 "nothing to score"))

    vocabulary = store.load_family_vocabulary(conn)
    family_map = load_family_map()

    pairs: list[M.ScoredPair] = []
    events: list[dict[str, Any]] = []
    family_entries: list[dict[str, Any]] = []
    prose_records: list[dict[str, Any]] = []
    contradiction_records: list[dict[str, Any]] = []
    excluded_pairs: list[tuple[str, str]] = []
    unscored: list[str] = []

    for expectation in expectations:
        output = outputs.get(expectation.event_id)
        if output is None:
            unscored.append(expectation.event_id)
            continue
        pairs.extend(build_pairs(conn, expectation, output))
        events.append({"stratum": expectation.stratum,
                       "primary_count": output.primary_count})
        family_entries.append({
            "event_id": expectation.event_id,
            "expected": _resolvable_families(expectation, vocabulary, family_map),
            "published": tuple(output.published_families)})
        for ref in sorted(expectation.disputed | expectation.unresolved):
            excluded_pairs.append((expectation.event_id, ref))
        for record in output.records:
            contradiction_records.append(record.as_contradiction_input())
            if record.publication_tier == TIER_REJECTED:
                continue
            prose_records.append({
                "publication_tier": record.publication_tier,
                "sentences_total": record.sentences_total,
                "deletions": record.deletions,
                "prose": record.prose,
                "record_numerals": record.record_numerals})

    aggregate = _pair_metrics(pairs)
    aggregate.update({
        "abstention_precision": M.abstention_precision(events).value,
        "primary_false_positives_on_null_events":
            M.null_event_primary_false_positives(events),
        "ripple_family_recall": M.ripple_family_recall(family_entries).value,
        "firewall_deletion_rate_primary_prose":
            M.firewall_deletion_rate(prose_records, TIER_PRIMARY).value,
        "fabricated_numeral_rate": M.fabricated_numeral_rate(prose_records).value,
        "internal_contradiction_rate":
            M.internal_contradiction_rate(contradiction_records).value,
        # calibration is disabled and locked; there are no probabilities
        "calibration_ece": M.calibration_ece(()),
        "calibration_brier": M.calibration_brier(()),
    })

    unavailable = {name: reason for name, reason in UNAVAILABLE_REASONS.items()
                   if aggregate.get(name) is None}
    return M.MetricReport(
        aggregate=aggregate,
        per_stratum=M.group_by(pairs, "stratum", _pair_metrics),
        per_sector=M.group_by(pairs, "sector", _pair_metrics),
        unavailable=unavailable, unscored=tuple(unscored),
        excluded_pairs=tuple(excluded_pairs), events_scored=len(events))


def _resolvable_families(expectation: EventExpectation, vocabulary,
                         family_map) -> tuple[str, ...]:
    """Expected families translated into the universe's own slugs.

    A term the vocabulary cannot translate at all is DROPPED from the
    denominator rather than counted as a miss -- Session 0's rule: looking
    for a group nobody is classified into scores a guaranteed miss against
    the engine and measures our taxonomy, not its recall.
    """
    out: list[str] = []
    for term in sorted(expectation.ripple_families):
        targets, how = resolve_family(term, vocabulary, family_map)
        if how == "unknown":
            continue
        out.extend(targets)
    return tuple(sorted(set(out)))


__all__ = [
    "HarnessRefusal", "CorpusIntegrity", "EventExpectation", "StageBundle",
    "CompanyRecord", "EventOutput", "METRIC_NAMES", "MIN_LABELERS",
    "REQUIRED_EVENTS", "REQUIRED_NULL_EVENTS", "UNAVAILABLE_REASONS",
    "build_pairs", "cohens_kappa", "corpus_integrity", "load_expectations",
    "run_v5_path", "score", "stored_event_output",
]
