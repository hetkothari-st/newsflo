"""Pydantic models + Gemini structured-output JSON schemas for every
impact-graph stage (spec docs 3 §13-14 / 4 §10-11).

Two representations on purpose:
- pydantic models: what the engine validates and passes around.
- SCHEMA_* dicts: the JSON Schema subset Gemini's structured-output mode
  accepts (no $refs, no unions beyond nullable, enums allowed). Kept
  hand-written rather than generated so they stay inside that subset.

Scores are floats in [0,1]; code clamps rather than trusting the model
(spec doc 1 §9: the model proposes, code validates and sorts).
"""
from typing import Optional

from pydantic import BaseModel, Field

from app.analysis.schemas import CATEGORIES, EVENT_TYPES

TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]
PARENT_TYPES = ["event", "economic_node", "sector", "commodity", "policy", "company"]
CHILD_TYPES = ["economic_node", "sector", "commodity", "policy", "company"]
DIRECTIONS = ["bullish", "bearish", "neutral"]


def _clamp(value, low=0.0, high=1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


# --- Stage 1: fact extraction -------------------------------------------

class FactItem(BaseModel):
    fact_id: str  # F1, F2, ... -- stable within the article
    text: str


class EventFacts(BaseModel):
    event: str
    event_status: str = "confirmed"  # confirmed | unconfirmed | rumor | denied
    facts: str  # canonical prose event record (rich, not a tiny summary)
    # Canonical fact store (token-opt spec §6): downstream calls send
    # these compact numbered lines, never the prose block + evidence.
    fact_items: list[FactItem] = Field(default_factory=list)
    quantities: list[str] = Field(default_factory=list)
    named_entities: list[str] = Field(default_factory=list)
    stated_causes: list[str] = Field(default_factory=list)
    stated_consequences: list[str] = Field(default_factory=list)
    article_evidence: list[str] = Field(default_factory=list)  # "article: ..." snippets
    category: str
    event_type: str

    def compact_lines(self, limit: int = 14) -> str:
        """The downstream-call fact block: numbered canonical facts, or a
        clipped prose fallback for pre-optimization cached results."""
        if self.fact_items:
            return "\n".join(f"{f.fact_id}: {f.text}" for f in self.fact_items[:limit])
        return self.facts[:1200]


SCHEMA_FACTS = {
    "type": "object",
    "properties": {
        "event": {"type": "string"},
        "event_status": {"type": "string", "enum": ["confirmed", "unconfirmed", "rumor", "denied"]},
        "facts": {"type": "string"},
        "fact_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact_id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["fact_id", "text"],
            },
        },
        "quantities": {"type": "array", "items": {"type": "string"}},
        "named_entities": {"type": "array", "items": {"type": "string"}},
        "stated_causes": {"type": "array", "items": {"type": "string"}},
        "stated_consequences": {"type": "array", "items": {"type": "string"}},
        "article_evidence": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string", "enum": CATEGORIES},
        "event_type": {"type": "string", "enum": EVENT_TYPES},
    },
    "required": ["event", "event_status", "facts", "fact_items", "category", "event_type"],
}


# --- Graph nodes / edges -------------------------------------------------

class GraphNode(BaseModel):
    node_id: str  # snake_case stable id, e.g. "crude_oil_price"
    node_type: str  # CHILD_TYPES (or "event" for the root, engine-made)
    label: str  # human-readable
    sector: Optional[str] = None  # set when node_type == "sector"


class GraphEdge(BaseModel):
    parent_type: str
    parent_id: str
    child_type: str
    child_id: str
    direction: str
    mechanism: str
    # 0 = "engine has not assigned it yet": _register_edge always overwrites
    # with parent_distance + 1, never trusting the model's own number.
    causal_distance: int = 0
    impact_strength: float = 0.0
    confidence: float = 0.0
    materiality: float = 0.0
    time_horizon: str = "Short-Term"
    verification_status: str = "unverified"

    def clamp(self) -> "GraphEdge":
        self.impact_strength = _clamp(self.impact_strength)
        self.confidence = _clamp(self.confidence)
        self.materiality = _clamp(self.materiality)
        return self

    @property
    def key(self) -> tuple:
        return (self.parent_type, self.parent_id, self.child_type, self.child_id)


_EDGE_PROPS = {
    "parent_type": {"type": "string", "enum": PARENT_TYPES},
    "parent_id": {"type": "string"},
    "child_type": {"type": "string", "enum": CHILD_TYPES},
    "child_id": {"type": "string"},
    "child_label": {"type": "string"},
    "child_sector": {"type": "string"},
    "direction": {"type": "string", "enum": DIRECTIONS},
    "mechanism": {"type": "string"},
    "impact_strength": {"type": "number"},
    "confidence": {"type": "number"},
    "materiality": {"type": "number"},
    "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
}


# --- Stage 2: initial shocks (distance-1 anchor) -------------------------

SCHEMA_SHOCKS = {
    "type": "object",
    "properties": {
        "shocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "shock_id": {"type": "string"},
                    "label": {"type": "string"},
                    "direction": {"type": "string", "enum": DIRECTIONS},
                    "mechanism": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "impact_strength": {"type": "number"},
                    "materiality": {"type": "number"},
                    "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
                },
                "required": ["shock_id", "label", "direction", "mechanism", "confidence"],
            },
        },
        "direct_nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": dict(_EDGE_PROPS),
                "required": ["parent_type", "parent_id", "child_type", "child_id",
                             "direction", "mechanism", "confidence", "materiality"],
            },
        },
    },
    "required": ["shocks", "direct_nodes"],
}


# --- Stage 4: ripple discovery (one hop from the frontier) ---------------

SCHEMA_RIPPLE = {
    "type": "object",
    "properties": {
        "children": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": dict(_EDGE_PROPS),
                "required": ["parent_type", "parent_id", "child_type", "child_id",
                             "direction", "mechanism", "confidence", "materiality"],
            },
        },
    },
    "required": ["children"],
}


# --- Stages 3/5: company mapping ----------------------------------------

NET_DIRECTIONS = ["bullish", "bearish", "mixed", "uncertain", "neutral"]


class GraphCompany(BaseModel):
    ticker: str
    name: str
    direction: str
    impact_strength: float = 0.0
    confidence: float = 0.0
    materiality: float = 0.0
    causal_distance: int = 1
    time_horizon: str = "Short-Term"
    parent_type: str = "event"
    parent_id: str = "event"
    mechanism: str = ""
    rationale: str = ""
    key_points: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    verified: bool = False
    # Net-effect reasoning (token-opt spec P12 -- a QUALITY requirement):
    # competing channels considered before the direction call. mixed /
    # uncertain are valid net outcomes; relative_beneficiary marks "better
    # off than peers" without claiming absolute benefit.
    positive_channels: list[str] = Field(default_factory=list)
    negative_channels: list[str] = Field(default_factory=list)
    net_direction: str = ""  # NET_DIRECTIONS; "" on legacy rows
    relative_beneficiary: bool = False

    def clamp(self) -> "GraphCompany":
        self.impact_strength = _clamp(self.impact_strength)
        self.confidence = _clamp(self.confidence)
        self.materiality = _clamp(self.materiality)
        return self


def schema_companies(valid_tickers: list[str]) -> dict:
    """Company schema with ticker enum-locked to THIS call's candidates --
    the grounding rail (spec doc 1 §8): free-form ticker generation is
    structurally impossible, not merely discouraged.

    COMPACT contract (token-opt P23): required fields are only what the
    product needs -- ticker, direction, scores, mechanism, horizon,
    rationale plus the net-effect channels. Everything else is optional;
    the model writes it only when it has something real (output tokens
    measured as ~half the per-article bill)."""
    return {
        "type": "object",
        "properties": {
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "enum": valid_tickers},
                        "name": {"type": "string"},
                        "direction": {"type": "string", "enum": DIRECTIONS},
                        "impact_strength": {"type": "number"},
                        "confidence": {"type": "number"},
                        "materiality": {"type": "number"},
                        "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
                        "mechanism": {"type": "string"},
                        "rationale": {"type": "string"},
                        "positive_channels": {"type": "array", "items": {"type": "string"}},
                        "negative_channels": {"type": "array", "items": {"type": "string"}},
                        "net_direction": {"type": "string", "enum": NET_DIRECTIONS},
                        "relative_beneficiary": {"type": "boolean"},
                        "key_points": {"type": "array", "items": {"type": "string"}},
                        "reasons": {"type": "array", "items": {"type": "string"}},
                        "evidence_refs": {"type": "array", "items": {"type": "string"}},
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "unknowns": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["ticker", "direction", "impact_strength",
                                 "confidence", "materiality", "time_horizon",
                                 "mechanism", "rationale", "net_direction"],
                },
            },
        },
        "required": ["companies"],
    }


# --- Stage 7: company verification (DIFF contract, token-opt P17) --------

def schema_company_verdicts(valid_tickers: list[str]) -> dict:
    """accept[] / reject[] / corrections{} -- the verifier never repeats
    accepted records, never invents companies (enums), never writes prose
    beyond per-rejection one-liners."""
    return {
        "type": "object",
        "properties": {
            "accept": {"type": "array", "items": {"type": "string", "enum": valid_tickers}},
            "reject": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "enum": valid_tickers},
                        "reason": {"type": "string"},
                    },
                    "required": ["ticker"],
                },
            },
            "corrections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "enum": valid_tickers},
                        "direction": {"type": "string", "enum": DIRECTIONS},
                        "causal_distance": {"type": "integer"},
                        "materiality": {"type": "number"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["ticker"],
                },
            },
        },
        "required": ["accept", "reject"],
    }


# --- Stage 8: edge verification ------------------------------------------

SCHEMA_EDGE_VERDICTS = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "valid": {"type": "boolean"},
                    "missing_intermediate": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "valid"],
            },
        },
    },
    "required": ["verdicts"],
}


# --- Stage 9: ranking -----------------------------------------------------

def schema_ranking(valid_tickers: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "ranked": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "enum": valid_tickers},
                        "bucket": {"type": "string", "enum": [
                            "beneficiary", "adversely_affected", "neutral_mixed",
                        ]},
                        "rank_reason": {"type": "string"},
                    },
                    "required": ["ticker", "bucket"],
                },
            },
        },
        "required": ["ranked"],
    }


# --- Engine result --------------------------------------------------------

class ImpactGraphResult(BaseModel):
    """What the engine hands back to the pipeline. Field names deliberately
    echo the old AnalysisOutput where the concept is the same (category,
    event_type, gaps, facts) so persistence adapts, not rewrites."""
    category: str
    event_type: Optional[str] = None
    facts: str = ""
    event_label: str = ""
    companies: list[GraphCompany] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    ranking: list[dict] = Field(default_factory=list)  # [{ticker, bucket, rank_reason}]
    analysis_provider: str = "gemini"
    analysis_quality: str = "authoritative"  # authoritative | degraded | fallback | budget_exhausted
