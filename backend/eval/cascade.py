"""TASK 7.5 -- section 18's routing, evaluated over the DEPLOYED gate.

    1. deterministic short-circuit (index lookup, cached shock template,
       prior identical event)                              -> 0 tokens
    2. stage-result cache                                  -> eval.cost_ledger
    3. small/fast model  -- extraction, classification, entailment judging
    4. frontier model    -- ONLY gate-boundary candidates, MIXED resolution,
                            and PRIMARY-eligible falsification

WHAT DOES THE ELIMINATING. Nothing in this module rejects a candidate: it
asks `app.core.gates.evaluate` over `config/gates.yaml` -- the same call the
reducer makes -- and routes on the answer. That matters, because a cascade
that eliminated candidates by its own private rule would prove that the
CASCADE is cheap while saying nothing about whether the SYSTEM is.

"MARGINAL AT THE GATE BOUNDARY" is defined here, because nothing else in the
repo defines it: a candidate that failed the PRIMARY walk on EXACTLY ONE
rule. One rule away is the case where an adversarial second opinion can
change the answer; three rules away, it cannot, and paying frontier prices
for it is how a budget disappears. A hard-blocked candidate is never
marginal -- the PRIMARY walk never ran, so nothing about it is one rule away.

WHERE THIS LIVES, AND WHY NOT UNDER `app/`. V5 has no serving path (standing
ruling since Phase 0) and the falsifier is deliberately unwired (DATA_GAPS
section 10.3), so there is no production caller to route for. This is the
harness's own orchestration and it is honest about that. When V5 is wired
into a pipeline, this routing moves under `app/` unchanged -- and DATA_GAPS
section 11 records that as an open item rather than pretending it is done.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.core.gates import GateConfig, ImpactDraft, evaluate
from eval.cost_ledger import (
    CACHED, FRONTIER, SHORT_CIRCUIT, SMALL, CallLedger, StageCache,
)

#: The one stage in V5 that spends frontier tokens (Phase 6's falsifier).
FALSIFIER_STAGE = "FALSIFIER"

REASON_SHORT_CIRCUIT = "DETERMINISTIC_SHORT_CIRCUIT"
REASON_PRIMARY = "PRIMARY_ELIGIBLE_FALSIFICATION"
REASON_MIXED = "MIXED_RESOLUTION"
REASON_MARGINAL = "MARGINAL_AT_GATE_BOUNDARY"
REASON_SMALL = "PUBLISHED_BELOW_PRIMARY"

MIXED = "MIXED"


@dataclass(frozen=True)
class Routing:
    candidate_id: str
    tier: str
    reason: str
    gate_tier: str | None = None


@dataclass(frozen=True)
class CascadeRun:
    candidates: int
    routings: tuple[Routing, ...]
    counts: Mapping[str, int]

    @property
    def frontier_ids(self) -> tuple[str, ...]:
        return tuple(r.candidate_id for r in self.routings if r.tier == FRONTIER)


def drafts_from_cohorts(cohorts: Iterable[Mapping[str, Any]]
                        ) -> list[tuple[str, ImpactDraft]]:
    """Expand a fixture's COHORTS into individual drafts.

    A fixture expressed as "150 of this shape" is readable; the same fixture
    expressed as 150 near-identical JSON objects is a file nobody audits.
    """
    out: list[tuple[str, ImpactDraft]] = []
    for cohort in cohorts:
        fields = {k: (tuple(v) if isinstance(v, list) else v)
                  for k, v in cohort["draft"].items()
                  if not str(k).startswith("_")}
        for index in range(int(cohort["count"])):
            out.append((f"{cohort['name']}:{index}", ImpactDraft(**fields)))
    return out


def _failed_primary_rules(result) -> int:
    return sum(1 for rule in result.gate_trace
               if rule.tier == "PRIMARY" and not rule.passed)


def route_candidates(drafts: Sequence[tuple[str, ImpactDraft]],
                     gate_config: GateConfig, *,
                     short_circuit_ids: Iterable[str] = ()) -> CascadeRun:
    """Route every candidate to the cheapest rung that can answer it."""
    known = set(short_circuit_ids)
    routings: list[Routing] = []
    counts = {SHORT_CIRCUIT: 0, CACHED: 0, SMALL: 0, FRONTIER: 0}

    for candidate_id, draft in drafts:
        # rung 1 -- an answer we already have costs nothing to reuse.
        if candidate_id in known:
            routings.append(Routing(candidate_id, SHORT_CIRCUIT,
                                    REASON_SHORT_CIRCUIT))
            counts[SHORT_CIRCUIT] += 1
            continue

        result = evaluate(draft, gate_config)

        if str(draft.net_effect) == MIXED:
            routing = Routing(candidate_id, FRONTIER, REASON_MIXED, result.tier)
        elif result.tier == "PRIMARY":
            routing = Routing(candidate_id, FRONTIER, REASON_PRIMARY, result.tier)
        elif _failed_primary_rules(result) == 1:
            routing = Routing(candidate_id, FRONTIER, REASON_MARGINAL, result.tier)
        elif result.tier == "SECONDARY_RIPPLE":
            routing = Routing(candidate_id, SMALL, REASON_SMALL, result.tier)
        else:
            routing = Routing(
                candidate_id, SHORT_CIRCUIT,
                f"ELIMINATED_BY_GATE:{result.rejection_reason or 'REJECTED'}",
                result.tier)
        routings.append(routing)
        counts[routing.tier] += 1

    return CascadeRun(candidates=len(drafts), routings=tuple(routings),
                      counts=counts)


def run_frontier_stage(run: CascadeRun, *, client, ledger: CallLedger,
                       cache: StageCache | None = None,
                       model_id: str | None = None,
                       prompt_version: str | None = None) -> int:
    """Spend the frontier budget the routing authorised, and only that.

    The client is INJECTED and is called through the ledger's wrapper, so the
    number this returns is the number a bill would show. It is deliberately
    the falsifier's own seam (`generate(prompt) -> str`), not a private one.
    """
    counted = ledger.wrap(client, tier=FRONTIER, stage=FALSIFIER_STAGE,
                          model_id=model_id, prompt_version=prompt_version,
                          cache=cache)
    for candidate_id in run.frontier_ids:
        counted.generate(f"{FALSIFIER_STAGE}:{candidate_id}")
    return len(run.frontier_ids)
