from typing import Optional

from pydantic import BaseModel

SECTORS = ["oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra", "other"]


class CompanyMention(BaseModel):
    name: str
    ticker: Optional[str] = None
    is_direct: bool
    sector: Optional[str] = None
    direction: str  # bullish | bearish
    magnitude_low: float
    magnitude_high: float
    rationale: str


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
