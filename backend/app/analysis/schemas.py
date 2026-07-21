from typing import Optional

from pydantic import BaseModel

SECTORS = [
    "oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra",
    "railways_transport", "construction_realestate", "defense", "agriculture",
    "consumer_durables", "media_entertainment", "chemicals", "textiles", "other",
]
TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]
EVENT_TYPES = [
    "repo_rate_change", "inflation", "crude_oil", "currency_move",
    "government_spending", "earnings", "merger_acquisition", "banking_metrics",
    "other",
]
# The article-level topical bucket shown as a badge on every feed card
# (Alert.category) -- unlike EVENT_TYPES (the specific triggering event) or
# SECTORS (per-company classification), this had NO enum/tool-schema
# constraint until now, so the LLM sometimes returned a full sentence
# instead of a short tag, breaking the badge's layout. The first 9 mirror
# SECTORS exactly (same names) for a single consistent vocabulary across the
# app; the rest cover news that isn't about one sector.
CATEGORIES = [
    "oil_gas", "banking", "auto", "it", "pharma", "fmcg", "metals", "telecom", "infra",
    "macro_policy", "geopolitics", "corporate_event", "market_commentary",
    "other",
]
# How far removed a company's impact is from the article's direct subject.
# "direct" covers both actually-direct mentions AND sector-inference fan-out
# (both are the article's own primary impact, just resolved two different
# ways -- see app.companies.resolution). "indirect_l1"/"indirect_l2" are
# companies the model knows are economically linked (supplier/customer/close
# competitor) to an already-named direct or indirect_l1 company, not
# mentioned in the article itself -- see CompanyMention.parent_ticker.
IMPACT_LEVELS = ["direct", "indirect_l1", "indirect_l2"]

# Precise definitions the model must use for sector inference. Ambiguity here
# (e.g. treating "semiconductor" as close enough to "it") is what causes the
# resolver to attach real reasoning about one company (say, a Korean chip
# maker) to an unrelated company that merely shares a loosely-matched sector
# tag (e.g. an Indian IT services firm). Precision here is load-bearing.
# Moved here (was app.analysis.claude_client.SECTOR_DEFINITIONS) so both
# app.analysis.cascade and app.companies.sector_classification can import it
# without a circular dependency on claude_client.
SECTOR_DEFINITIONS = """
- oil_gas: oil & gas exploration, refining, and marketing companies only.
- banking: deposit-taking banks, NBFCs, and financial services firms only.
- auto: automobile and two-wheeler manufacturers, and auto component makers.
- it: INDIAN IT SERVICES / software consulting / outsourcing firms only \
(e.g. TCS, Infosys, Wipro). Does NOT include semiconductor, chip, or \
hardware manufacturers -- those have no matching sector in this system.
- pharma: pharmaceutical and healthcare companies, including hospitals and diagnostics.
- fmcg: fast-moving consumer goods, food & beverage, personal care.
- metals: metals, mining, and materials companies.
- telecom: telecommunications and network infrastructure operators.
- infra: industrial, infrastructure, construction/EPC, power/utilities, and heavy equipment.
- railways_transport: railways, aviation, shipping, ports, and logistics/road transport operators.
- construction_realestate: real estate developers (residential/commercial property) -- \
NOT EPC/construction contractors, those are infra.
- defense: defense and aerospace manufacturers.
- agriculture: agricultural inputs, fertilizers, agrochemicals, and seed companies.
- consumer_durables: consumer electronics and durable-goods manufacturers (appliances \
etc) -- distinct from fmcg's fast-moving, non-durable goods.
- media_entertainment: media, broadcasting, entertainment, and publishing companies.
- chemicals: specialty and commodity chemical manufacturers.
- textiles: textile and apparel manufacturers.
- other: none of the above.
""".strip()


class FactsResult(BaseModel):
    facts: str
    category: str
    event_type: str


class SectorFinding(BaseModel):
    sector: str
    direction: str  # bullish | bearish
    mechanism: str
    # Set only for a cascade-hop finding (stages 4/6 of the sector-cascade
    # pipeline): the sector this one ripples from. None for a primary/
    # directly-affected sector (stage 2). See app.analysis.cascade.
    parent_sector: Optional[str] = None


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
    # One of IMPACT_LEVELS. Defaults to "direct" so every existing caller
    # (older tests, the dedup-reuse path) validates without change.
    impact_level: str = "direct"
    # For impact_level in (indirect_l1, indirect_l2): the ticker of the
    # already-named company (a direct company for indirect_l1, an indirect_l1
    # company for indirect_l2) this one is economically linked through. None
    # for impact_level="direct". Resolved to a real parent_company_id in
    # app.companies.resolution.
    parent_ticker: Optional[str] = None


class AnalysisOutput(BaseModel):
    category: str
    companies: list[CompanyMention]
    # Article-level event classification, parallel to `category`. Optional
    # at the pydantic layer (defaults to None) for backward compatibility;
    # the tool schema sent to the LLM (RECORD_ANALYSIS_TOOL) still requires
    # it on every real call.
    event_type: Optional[str] = None
    # Cascade sectors whose company lookup failed even after a retry (see
    # app.analysis.cascade._identify_cascade_companies_per_sector). Each
    # dict has keys: sector, impact_level, parent_ticker, attempts,
    # last_error. Defaults to [] so every existing caller (older tests,
    # the dedup-reuse path in pipeline.py) still validates without change.
    gaps: list[dict] = []
