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
               thinking_tokens=None, cached_tokens=None, model: str | None = None) -> None:
        self.calls += 1
        self.input_tokens += input_tokens or 0
        self.output_tokens += (output_tokens or 0) + (thinking_tokens or 0)
        self.thinking_tokens += thinking_tokens or 0
        self.cached_tokens += cached_tokens or 0
        cost = _estimate_cost(model, input_tokens or 0, (output_tokens or 0) + (thinking_tokens or 0),
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
    """Priced ONLY from config.LLM_MODEL_PRICING_USD_PER_MTOK -- an
    unpriced model contributes 0 and the token ceilings still bound it
    (same no-stale-confident-numbers stance as that constant's comment)."""
    pricing = LLM_MODEL_PRICING_USD_PER_MTOK.get(model or "")
    if not pricing:
        return 0.0
    uncached = max(0, input_tokens - cached_tokens)
    cost = uncached / 1e6 * pricing.get("input", 0.0)
    cost += cached_tokens / 1e6 * pricing.get("cache_read", pricing.get("input", 0.0))
    cost += output_tokens / 1e6 * pricing.get("output", 0.0)
    return cost
