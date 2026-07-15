from typing import Optional

from pydantic import BaseModel

SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]
TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]


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
    # 0-100: how directly evidenced THIS company's call is, not a general
    # "how confident is the model" score -- see the prompt rule for exactly
    # what should push this up or down.
    confidence_score: int
    # Exactly one of TIME_HORIZONS -- when the mechanism described in
    # `rationale` actually plays out, not how soon the news was published.
    time_horizon: str


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
