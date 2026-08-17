"""TASK 7.5 -- the call ledger and the stage-result cache.

Spec section 18's cascade, evaluated in order:

    1. deterministic short-circuit  -> 0 tokens
    2. stage-result cache           -> keyed (stage, input_hash, model_id,
                                              prompt_version)
    3. small/fast model             -> extraction, classification, entailment
    4. frontier model               -> gate-boundary candidates, MIXED
                                       resolution, PRIMARY-eligible falsification

`CallLedger` is a COUNTING WRAPPER, not a client. It is handed whatever
client the caller already has -- in this repo, always an injected object --
and records what tier each call was, which stage made it and whether the
stage cache answered instead. It constructs nothing, imports no provider SDK
and cannot reach a network.

WHY THE COUNT IS A LEDGER RATHER THAN A COUNTER. "Frontier calls per event"
is the budget, but the useful question when it is breached is WHICH STAGE
spent it, so every record carries its stage and the totals split by both.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Mapping

SHORT_CIRCUIT = "SHORT_CIRCUIT"   # rung 1 -- no model at all
CACHED = "CACHED"                 # rung 2 -- a model answered once, long ago
SMALL = "SMALL"                   # rung 3
FRONTIER = "FRONTIER"             # rung 4

#: The tiers a call may be recorded at. Closed on purpose: a typo'd tier
#: would silently create a tier that no budget watches.
TIERS = (SHORT_CIRCUIT, CACHED, SMALL, FRONTIER)


class CascadeBudgetExceeded(AssertionError):
    """More frontier calls per candidate than section 18 permits."""


def input_hash(text: str) -> str:
    """Content address of one prompt. sha256, like every other stable id in
    this repo (`app.core.signals`)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stage_cache_key(*, stage: str, input_hash: str, model_id: str | None,
                    prompt_version: str | None) -> str:
    """Section 18 rung 2's key, all four components, joined unambiguously.

    Every component earns its place: two stages may hash the same input and
    mean different things; the same input on a different MODEL is a different
    answer; and a changed PROMPT VERSION is exactly the case where a stale
    cache hit would hide a regression from the eval harness.
    """
    parts = (stage, input_hash, model_id or "-", prompt_version or "-")
    return "|".join(str(part).replace("|", "\\|") for part in parts)


@dataclass
class StageCache:
    """An in-process stage-result cache. Deliberately not persistent: the
    harness runs offline and a cache that outlived a run would let one
    measurement contaminate the next."""
    entries: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        return self.entries.get(key)

    def put(self, key: str, value: str) -> None:
        self.entries[key] = value

    def __len__(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class CallRecord:
    tier: str
    stage: str
    model_id: str | None = None
    prompt_version: str | None = None
    cache_key: str | None = None
    cached: bool = False


class _CountingClient:
    """The seam, one method wide: `generate(prompt) -> str`, exactly the
    contract `app.analysis.falsifier.engine.JSONClient` declares. Anything
    the falsifier accepts, this accepts, and it adds counting and rung 2."""

    def __init__(self, client: Any, *, ledger: "CallLedger", tier: str,
                 stage: str, model_id: str | None, prompt_version: str | None,
                 cache: StageCache | None):
        self._client = client
        self._ledger = ledger
        self._tier = tier
        self._stage = stage
        self._model_id = model_id
        self._prompt_version = prompt_version
        self._cache = cache

    @property
    def model_id(self) -> str | None:
        return self._model_id

    def generate(self, prompt: str) -> str:
        key = stage_cache_key(stage=self._stage, input_hash=input_hash(prompt),
                              model_id=self._model_id,
                              prompt_version=self._prompt_version)
        if self._cache is not None:
            hit = self._cache.get(key)
            if hit is not None:
                self._ledger.record(self._tier, stage=self._stage,
                                    model_id=self._model_id,
                                    prompt_version=self._prompt_version,
                                    cache_key=key, cached=True)
                return hit
        response = self._client.generate(prompt)
        self._ledger.record(self._tier, stage=self._stage,
                            model_id=self._model_id,
                            prompt_version=self._prompt_version, cache_key=key)
        if self._cache is not None:
            self._cache.put(key, response)
        return response


@dataclass
class CallLedger:
    records: list[CallRecord] = field(default_factory=list)

    # -- recording ---------------------------------------------------------
    def record(self, tier: str, *, stage: str, model_id: str | None = None,
               prompt_version: str | None = None, cache_key: str | None = None,
               cached: bool = False) -> None:
        if tier not in TIERS:
            raise ValueError(
                f"unknown cascade tier {tier!r}; expected one of "
                f"{', '.join(TIERS)}. A tier nobody named is a tier no budget "
                f"watches.")
        self.records.append(CallRecord(
            tier=tier, stage=stage, model_id=model_id,
            prompt_version=prompt_version, cache_key=cache_key, cached=cached))

    def wrap(self, client: Any, *, tier: str, stage: str,
             model_id: str | None = None, prompt_version: str | None = None,
             cache: StageCache | None = None) -> _CountingClient:
        if tier not in TIERS:
            raise ValueError(f"unknown cascade tier {tier!r}")
        return _CountingClient(client, ledger=self, tier=tier, stage=stage,
                               model_id=model_id, prompt_version=prompt_version,
                               cache=cache)

    # -- reading -----------------------------------------------------------
    def _live(self) -> list[CallRecord]:
        """Calls that actually reached a model. A cache hit costs nothing and
        must not be counted as spend -- nor hidden, which is why it is still
        a record."""
        return [r for r in self.records if not r.cached]

    @property
    def frontier_calls(self) -> int:
        return sum(1 for r in self._live() if r.tier == FRONTIER)

    @property
    def small_calls(self) -> int:
        return sum(1 for r in self._live() if r.tier == SMALL)

    @property
    def total_calls(self) -> int:
        return len(self._live())

    @property
    def cache_hits(self) -> int:
        return sum(1 for r in self.records if r.cached)

    @property
    def calls_by_stage(self) -> Mapping[str, int]:
        return Counter(r.stage for r in self._live())

    @property
    def calls_by_tier(self) -> Mapping[str, int]:
        return Counter(r.tier for r in self._live())

    # -- the budget --------------------------------------------------------
    def cascade_ratio(self, candidates: int) -> float | None:
        """`frontier_calls / candidates`, or None over zero candidates -- a
        ratio with no denominator is not 0.0."""
        if not candidates:
            return None
        return self.frontier_calls / candidates

    def assert_within_budget(self, candidates: int, max_ratio: float) -> None:
        ratio = self.cascade_ratio(candidates)
        if ratio is None:
            raise CascadeBudgetExceeded(
                "no candidates: the cascade ratio is undefined and cannot be "
                "reported as within budget")
        if ratio > max_ratio:
            raise CascadeBudgetExceeded(
                f"{self.frontier_calls} frontier call(s) over {candidates} "
                f"candidate(s) = {ratio:.4f}, above the section 18 budget of "
                f"{max_ratio}. The deterministic layers are not eliminating "
                f"what they are supposed to eliminate.")
