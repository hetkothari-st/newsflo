from typing import Optional

from pydantic import BaseModel

SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]
TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]
EVENT_TYPES = [
    "repo_rate_change", "inflation", "crude_oil", "currency_move",
    "government_spending", "earnings", "merger_acquisition", "banking_metrics",
    "other",
]


class CompanyMention(BaseModel):
    name: str
    ticker: Optional[str] = None
    is_direct: bool
    sector: Optional[str] = None
    direction: str  # bullish | bearish
    magnitude_low: float
    magnitude_high: float
    rationale: str
    # Short, scannable version of `rationale` for the feed UI -- the full
    # paragraph is kept for anyone who wants the depth, but a feed of alerts
    # is unreadable if every card is a paragraph. Defaults to empty for any
    # caller not yet passing it (older tests, older stored data).
    key_points: list[str] = []
    # No longer LLM-provided -- computed deterministically by
    # app.reasoning.confidence.compute_confidence and overwritten before
    # persistence (see app/pipeline.py::_persist_alert). Optional here only
    # so any caller not yet passing it (older tests, older stored data)
    # still validates.
    confidence_score: Optional[int] = None
    # Exactly one of TIME_HORIZONS -- when the mechanism described in
    # `rationale` actually plays out, not how soon the news was published.
    time_horizon: str
    # Evidence-discipline fields (see docs/superpowers/specs/2026-07-15-
    # reasoning-engine-upgrade-design.md). All default to empty/None so
    # existing callers that don't pass them still validate.
    reasons: list[str] = []
    evidence_refs: list[str] = []
    risks: list[str] = []
    assumptions: list[str] = []
    unknowns: list[str] = []
    alternative_hypothesis: Optional[str] = None


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    # Article-level event classification, parallel to `category`. Optional
    # at the pydantic layer (defaults to None) for backward compatibility;
    # the tool schema sent to the LLM (RECORD_ANALYSIS_TOOL) still requires
    # it on every real call.
    event_type: Optional[str] = None
