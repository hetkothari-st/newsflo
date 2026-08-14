"""Per-article Gemini token/cost budget (spec doc 1 §13A-B).

One ArticleBudget instance rides through a single analyze_article_v3 run.
Every Gemini call reports its usage here; the engine consults `exceeded`
before each further expansion call. Exceeding the budget is not an error:
the engine stops expanding, keeps what is already verified, and marks the
alert analysis_quality="budget_exhausted" -- never a silent overrun.
"""
import logging
from dataclasses import dataclass, field

from app.config import LLM_MODEL_PRICING_USD_PER_MTOK, settings

logger = logging.getLogger(__name__)


@dataclass
class ArticleBudget:
    article_id: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost_usd: float = 0.0
    calls: int = 0
    per_stage: dict = field(default_factory=dict)
    # Triage-tier ceilings (cost-target work): when set, these override the
    # global settings ceilings for THIS article -- the hard-ceiling
    # mechanism a narrow article's Rs-target rides on.
    max_input_override: int | None = None
    max_output_override: int | None = None

    def record(self, stage: str, *, input_tokens=None, output_tokens=None,
               thinking_tokens=None, cached_tokens=None, model: str | None = None,
               cache_write_tokens=None, semantics: str = "gemini") -> None:
        """Record one provider call.

        `semantics` selects how the token counts relate to each other, which
        differs by provider and is NOT a cosmetic detail (see
        _estimate_cost / _estimate_cost_anthropic):

        - "gemini" (default, every legacy caller): `input_tokens` is
          promptTokenCount, which INCLUDES the cached slice.
        - "anthropic": `input_tokens` is the API's `input_tokens`, which
          EXCLUDES both `cache_read_input_tokens` and
          `cache_creation_input_tokens`.

        NOTE on the input ceiling (honest limitation, deliberately not
        "fixed"): self.input_tokens is a plain sum of what each call
        reported, so for Anthropic calls the cached slice never lands in it.
        The 100k-per-article input ceiling was calibrated in the Gemini era
        against cache-INCLUSIVE numbers, so under Claude the same ceiling
        admits more real prompt tokens. Folding cache_read into the recorded
        input would silently retune that ceiling for every article, so it is
        left alone and documented instead; the cost ceiling below is exact
        for both providers.
        """
        self.calls += 1
        self.input_tokens += input_tokens or 0
        self.output_tokens += (output_tokens or 0) + (thinking_tokens or 0)
        self.thinking_tokens += thinking_tokens or 0
        self.cached_tokens += cached_tokens or 0
        if semantics == "anthropic":
            cost = _estimate_cost_anthropic(
                model, input_tokens or 0, (output_tokens or 0) + (thinking_tokens or 0),
                cached_tokens or 0, cache_write_tokens or 0)
        else:
            cost = _estimate_cost(model, input_tokens or 0,
                                  (output_tokens or 0) + (thinking_tokens or 0),
                                  cached_tokens or 0)
        self.estimated_cost_usd += cost
        stage_bucket = self.per_stage.setdefault(stage, {"input": 0, "output": 0, "cost": 0.0, "calls": 0})
        stage_bucket["input"] += input_tokens or 0
        stage_bucket["output"] += (output_tokens or 0) + (thinking_tokens or 0)
        stage_bucket["cost"] += cost
        stage_bucket["calls"] += 1

    def _over(self, fraction: float) -> bool:
        max_in = self.max_input_override or settings.gemini_max_input_tokens_per_article
        max_out = self.max_output_override or settings.gemini_max_output_tokens_per_article
        max_cost = settings.gemini_max_cost_per_article_usd
        if max_in and self.input_tokens >= max_in * fraction:
            return True
        if max_out and self.output_tokens >= max_out * fraction:
            return True
        if max_cost and self.estimated_cost_usd >= max_cost * fraction:
            return True
        return False

    @property
    def exceeded(self) -> bool:
        return self._over(1.0)

    @property
    def expansion_exhausted(self) -> bool:
        """Soft stop at 75% of any ceiling: expansion (the unbounded part)
        halts here so the REMAINING budget is reserved for verification and
        ranking -- measured 2026-08-11: without the reserve, wide events
        spent the whole budget on recall and skipped the precision stage,
        shipping unverified 35-company lists."""
        return self._over(0.75)

    def summary(self) -> dict:
        return {
            "article_id": self.article_id, "calls": self.calls,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens, "cached_tokens": self.cached_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "per_stage": self.per_stage,
        }


def _estimate_cost(model: str | None, input_tokens: int, output_tokens: int, cached_tokens: int) -> float:
    """GEMINI token semantics. Priced ONLY from
    config.LLM_MODEL_PRICING_USD_PER_MTOK -- an unpriced model contributes 0
    and the token ceilings still bound it (same no-stale-confident-numbers
    stance as that constant's comment).

    The subtraction below is correct for Gemini and ONLY for Gemini:
    `promptTokenCount` INCLUDES `cachedContentTokenCount`, so the
    full-priced slice is the difference. Do not call this for Anthropic
    usage -- see _estimate_cost_anthropic."""
    pricing = LLM_MODEL_PRICING_USD_PER_MTOK.get(model or "")
    if not pricing:
        return 0.0
    uncached = max(0, input_tokens - cached_tokens)
    cost = uncached / 1e6 * pricing.get("input", 0.0)
    cost += cached_tokens / 1e6 * pricing.get("cache_read", pricing.get("input", 0.0))
    cost += output_tokens / 1e6 * pricing.get("output", 0.0)
    return cost


# Anthropic bills a 5-minute-TTL prompt-cache WRITE at 1.25x the model's
# base input rate (cache reads are the ~0.1x rate carried in the pricing
# table as "cache_read"). A model may override the write rate explicitly
# with a "cache_write" key; otherwise it is derived from "input".
_ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25


def _estimate_cost_anthropic(model: str | None, input_tokens: int, output_tokens: int,
                             cache_read_tokens: int, cache_write_tokens: int = 0) -> float:
    """ANTHROPIC token semantics -- three DISJOINT input buckets.

    The Messages API reports `usage.input_tokens` already EXCLUDING both
    `cache_read_input_tokens` and `cache_creation_input_tokens`; the three
    are billed separately and never overlap. Running these numbers through
    _estimate_cost (which subtracts the cached slice) priced billed input at
    $0 the moment the cache warmed, and never billed cache writes at all --
    the bug this function exists to prevent. So: no subtraction anywhere.

    Same pricing stance as _estimate_cost: an unpriced model contributes 0.
    """
    pricing = LLM_MODEL_PRICING_USD_PER_MTOK.get(model or "")
    if not pricing:
        return 0.0
    input_rate = pricing.get("input", 0.0)
    cost = input_tokens / 1e6 * input_rate
    cost += cache_read_tokens / 1e6 * pricing.get("cache_read", input_rate)
    cost += cache_write_tokens / 1e6 * pricing.get(
        "cache_write", input_rate * _ANTHROPIC_CACHE_WRITE_MULTIPLIER)
    cost += output_tokens / 1e6 * pricing.get("output", 0.0)
    return cost
