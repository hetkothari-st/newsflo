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

from pydantic import BaseModel, Field, field_validator

from app.analysis.schemas import CATEGORIES, EVENT_TYPES

# Version stamp for the structured-output schemas (cost-opt spec P1/P12):
# telemetry + cache-fingerprint component. Bump on ANY schema change.
IMPACT_SCHEMA_VERSION = "kg-1"

TIME_HORIZONS = ["Immediate", "Short-Term", "Medium-Term", "Long-Term"]
PARENT_TYPES = ["event", "economic_node", "sector", "commodity", "policy", "company"]
CHILD_TYPES = ["economic_node", "sector", "commodity", "policy", "company"]
DIRECTIONS = ["bullish", "bearish", "neutral"]
# Semantic counterfactual verdict (corrective-v4 Task 9, spec §14): would the
# claimed company impact substantially weaken or disappear if this event had
# not occurred? SUPPORTED/NOT_SUPPORTED/UNCERTAIN -- see
# app.analysis.impact_graph.publication_gate.COUNTERFACTUAL_VERDICTS for the
# gate-side consumer of this same vocabulary.
COUNTERFACTUAL_VERDICTS = ["SUPPORTED", "NOT_SUPPORTED", "UNCERTAIN"]
# Canonical fundamental-effect vocabulary (corrective plan 2026-08-13 task 2,
# superseding the 2026-08-12 §11 5-way that still conflated "neutral" with
# genuine no-material-impact): a DISTINCT five-way enum. mixed ("both real
# channels present"), uncertain ("we don't know enough") and
# no_material_impact ("we know enough to conclude it doesn't matter") never
# collapse into each other. The legacy 3-way `direction` is DERIVED from
# this, never independently generated, and stays compat-only.
ECONOMIC_EFFECTS = ["positive", "negative", "mixed", "uncertain", "no_material_impact"]
# Model-facing enum only: Gemini structured-output schemas still accept the
# legacy "neutral" spelling as INPUT (existing prompts were written against
# it) alongside the canonical five. normalize_effect() maps it to
# "no_material_impact" at the parse boundary -- "neutral" must never be the
# canonical, in-process, or persisted value.
_ECONOMIC_EFFECT_INPUT_ENUM = ECONOMIC_EFFECTS + ["neutral"]
# Channel-audit verdicts (spec §5): the audit exists for coverage, so the
# vocabulary distinguishes "not applicable" from "plausible but uncertain"
# -- uncertain is NOT a discard.
CHANNEL_VERDICTS = ["material", "potential", "not_applicable", "uncertain"]
# Structured event-causation vocabulary (corrective plan 2026-08-13 task 10):
# the article's own ROOT CAUSE for the event, orthogonal to `category`
# (topical bucket) and `event_type` (article-classification tag). "unknown"
# is the honest default -- never invented, see EventFacts._normalize_cause.
EVENT_CAUSES = [
    "supply_shock", "demand_shock", "policy_action", "regulatory_change",
    "geopolitical_event", "company_action", "macro_data_surprise",
    "market_structure_event", "other", "unknown",
]
# Expected market SENSITIVITY (task 10): how likely THIS event is to cause
# meaningful repricing for a given company -- a distinct concept from
# economic_effect (the direction/size of the fundamental impact),
# materiality (worth showing at all) and the market layer's OWN measured
# price move. A model that has no basis to judge sensitivity omits the
# field and gets the honest "UNKNOWN", never a guess.
MARKET_SENSITIVITY_LEVELS = ["HIGH", "MEDIUM", "LOW", "UNKNOWN"]

_EFFECT_TO_DIRECTION = {
    "positive": "bullish", "negative": "bearish",
    "mixed": "neutral", "uncertain": "neutral", "no_material_impact": "neutral",
}
_DIRECTION_TO_EFFECT = {"bullish": "positive", "bearish": "negative", "neutral": "no_material_impact"}


def effect_to_direction(effect: str) -> str:
    return _EFFECT_TO_DIRECTION.get(effect, "neutral")


def direction_to_effect(direction: str) -> str:
    return _DIRECTION_TO_EFFECT.get(direction, "no_material_impact")


def normalize_effect(value: str | None) -> str:
    """Parse-boundary normalizer (corrective plan task 2): "neutral" is a
    legacy/compat alias for "no_material_impact", accepted as INPUT (models
    were prompted with it, old cached rows may carry it) but never the
    canonical vocabulary. Anything else unrecognized falls back to
    "uncertain" -- the honest "we don't know enough" default, never a
    silently invented "no_material_impact"."""
    if value == "neutral":
        return "no_material_impact"
    if value in ECONOMIC_EFFECTS:
        return value
    return "uncertain"


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
    # Structured event causation (task 10): the canonical ROOT CAUSE, kept
    # DISTINCT from category/event_type (topical classification) and from
    # any company's economic_effect (a downstream consequence, not a
    # cause). Never invented -- an omitted or out-of-enum value normalizes
    # to "unknown" via the validator below, the same discipline
    # normalize_effect() applies to economic_effect.
    event_cause: str = "unknown"
    # Magnitude exactly AS STATED by the article -- free text on purpose
    # (a percentage, a currency figure, a unit count, whatever the article
    # actually says), never a code-estimated number. None means the
    # article gave no magnitude at all.
    magnitude: str | None = None
    magnitude_units: str | None = None

    @field_validator("event_cause", mode="before")
    @classmethod
    def _normalize_cause(cls, value):
        """Missing/omitted or any value outside the enum honestly becomes
        "unknown" -- this stage must never invent a cause the article does
        not support."""
        return value if value in EVENT_CAUSES else "unknown"

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
        # Task 10: optional -- an omission is a legitimate "unknown", never
        # required from the model.
        "event_cause": {"type": "string", "enum": EVENT_CAUSES},
        "magnitude": {"type": "string"},
        "magnitude_units": {"type": "string"},
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
    direction: str = ""
    # Fundamental economic effect (spec §11) -- the canonical field; the
    # 3-way `direction` derives from it. Either may arrive from the model;
    # reconcile() fills whichever is missing, deterministically.
    economic_effect: str = ""
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
        return self.reconcile_effect()

    def reconcile_effect(self) -> "GraphEdge":
        """economic_effect is truth; direction is the derived legacy view.
        Mixed/uncertain/no_material_impact are preserved in economic_effect
        even though the 3-way direction collapses all three to neutral. A
        model-supplied "neutral" is the legacy alias, normalized here."""
        if self.economic_effect:
            self.economic_effect = normalize_effect(self.economic_effect)
        if self.economic_effect not in ECONOMIC_EFFECTS:
            self.economic_effect = direction_to_effect(self.direction)
        if self.direction not in DIRECTIONS:
            self.direction = effect_to_direction(self.economic_effect)
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
    "economic_effect": {"type": "string", "enum": _ECONOMIC_EFFECT_INPUT_ENUM},
    "mechanism": {"type": "string"},
    "impact_strength": {"type": "number"},
    "confidence": {"type": "number"},
    "materiality": {"type": "number"},
    "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
}

# Structured channel audit (spec §5/§7): systematic coverage scaffold for
# discovery stages. Verdicts use the 4-way vocabulary -- an `uncertain`
# channel is a candidate for a branch, not a discard.
_CHANNEL_AUDIT = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "channel": {"type": "string"},
            "verdict": {"type": "string", "enum": CHANNEL_VERDICTS},
            "reason": {"type": "string"},
        },
        "required": ["channel", "verdict"],
    },
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
        # Coverage scaffold (spec §5): every ontology channel must be
        # classified, so a channel the model did not think of first is a
        # visible verdict, never a silent absence.
        "channel_audit": _CHANNEL_AUDIT,
    },
    "required": ["shocks", "direct_nodes", "channel_audit"],
}


# --- Narrow-tier single-call graph (shocks + edges + channel audit) ------

SCHEMA_NARROW_GRAPH = {
    "type": "object",
    "properties": {
        "shocks": SCHEMA_SHOCKS["properties"]["shocks"],
        "channel_audit": _CHANNEL_AUDIT,
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": dict(_EDGE_PROPS),
                "required": ["parent_type", "parent_id", "child_type", "child_id",
                             "direction", "mechanism", "confidence", "materiality"],
            },
        },
    },
    "required": ["shocks", "edges"],
}


def schema_companies_batched(valid_tickers: list[str], node_ids: list[str]) -> dict:
    """Company schema for the narrow single-call mode: same grounding rails
    as schema_companies plus a required parent_id enum-locked to THIS
    graph's sector nodes -- the model maps every company to the node whose
    mechanism reaches it."""
    schema = schema_companies(valid_tickers)
    item = schema["properties"]["companies"]["items"]
    item["properties"]["parent_id"] = {"type": "string", "enum": node_ids}
    item["required"] = list(item["required"]) + ["parent_id"]
    return schema


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
    # Optional in schema_companies (token-opt compact contract) -- a model
    # that omits it must not lose the company (live 2026-08-13: every
    # returned company died in registration over the missing name).
    # Defaults to the ticker; the DB row's real name wins downstream.
    name: str = ""

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = self.ticker
    direction: str = ""
    impact_strength: float = 0.0
    confidence: float = 0.0
    # Optional (corrective plan task 2): a model omission must stay
    # representable as "we don't know" rather than being invented as 0.0 --
    # 0.0 and "unknown" are different claims (materiality_grade() already
    # treats None as its own UNKNOWN grade downstream).
    materiality: float | None = None
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
    # Where this candidate came from (spec §35 discovery_sources): "" for
    # the dynamic mapping path, "archetype:<mechanism_id>" for the
    # knowledge path, "subject_fallback" for the deterministic narrow
    # fallback. Provenance for the publication gate's evidence classing.
    discovery_source: str = ""
    # Net-effect reasoning (token-opt spec P12 -- a QUALITY requirement):
    # competing channels considered before the direction call. mixed /
    # uncertain are valid net outcomes; relative_beneficiary marks "better
    # off than peers" without claiming absolute benefit.
    positive_channels: list[str] = Field(default_factory=list)
    negative_channels: list[str] = Field(default_factory=list)
    # Channels that substantially cancel each other for THIS company (final
    # spec §18): what makes a mixed/neutral verdict an ANALYSIS instead of
    # a weak association.
    offsetting_channels: list[str] = Field(default_factory=list)
    net_direction: str = ""  # NET_DIRECTIONS; "" on legacy rows
    relative_beneficiary: bool = False
    # Fundamental economic effect (spec §11/§12) -- canonical 5-way field.
    # Derived from net_direction/direction when the model omits it; the
    # legacy 3-way direction stays the market-facing view.
    economic_effect: str = ""
    # Entity tri-state (corrective-v4 Task 7): the alias matcher found
    # MULTIPLE real, tradeable companies for the entity that named this
    # candidate and could not tiebreak between them -- a different failure
    # from "no company matched at all". The publication gate reads this to
    # emit REJECT_ENTITY_AMBIGUOUS instead of the generic
    # REJECT_UNKNOWN_COMPANY (app.pipeline._gate_candidates). Default False:
    # the normal case is an unambiguous ticker from the enum-locked
    # candidate list.
    entity_ambiguous: bool = False
    # Semantic counterfactual verdict (corrective-v4 Task 9): "" means no
    # verdict has been delivered yet -- the gate's COUNTERFACTUAL_VALID
    # check treats an unrecognized value as REJECT_VALIDATOR_UNAVAILABLE,
    # the same fail-closed stance as an unverified company. Only
    # app.analysis.impact_graph.engine._verify_companies ever writes a real
    # value here (from the verifier's per-ticker verdict map, or an explicit
    # UNCERTAIN fallback when the verifier ran but omitted this ticker); a
    # company the verifier never reached at all keeps "".
    counterfactual: str = ""
    # Expected market sensitivity (task 10): HIGH/MEDIUM/LOW/UNKNOWN --
    # how likely THIS event is to cause meaningful repricing sensitivity
    # for this company. Explicitly NOT the economic effect, NOT
    # materiality, and NOT the measured price move (app.market.measure
    # owns that; this field is set ONLY from the model's own judgment at
    # mapping time and must never be back-derived from a later price
    # observation). Optional in every company schema -- an omission is the
    # honest "UNKNOWN", never a guess.
    expected_market_sensitivity: str = "UNKNOWN"

    @field_validator("expected_market_sensitivity", mode="before")
    @classmethod
    def _normalize_sensitivity(cls, value):
        return value if value in MARKET_SENSITIVITY_LEVELS else "UNKNOWN"

    def clamp(self) -> "GraphCompany":
        self.impact_strength = _clamp(self.impact_strength)
        self.confidence = _clamp(self.confidence)
        # None (omitted) is never invented into 0.0 -- only clamp a value
        # the model actually supplied.
        if self.materiality is not None:
            self.materiality = _clamp(self.materiality)
        return self.reconcile_effect()

    def reconcile_effect(self) -> "GraphCompany":
        """Fill economic_effect from net_direction (which already carries
        mixed/uncertain) or direction; never overwrite a model-supplied
        value. Direction falls back to the effect-derived legacy view. A
        model-supplied "neutral" (on economic_effect or net_direction) is
        the legacy alias, normalized to "no_material_impact" -- mixed and
        uncertain are never collapsed into it."""
        if self.economic_effect:
            self.economic_effect = normalize_effect(self.economic_effect)
        if self.economic_effect not in ECONOMIC_EFFECTS:
            if self.net_direction in ("mixed", "uncertain", "neutral"):
                self.economic_effect = normalize_effect(self.net_direction)
            elif self.net_direction in ("bullish", "bearish"):
                self.economic_effect = direction_to_effect(self.net_direction)
            else:
                self.economic_effect = direction_to_effect(self.direction)
        if self.direction not in DIRECTIONS:
            self.direction = effect_to_direction(self.economic_effect)
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
                        "offsetting_channels": {"type": "array", "items": {"type": "string"}},
                        "net_direction": {"type": "string", "enum": NET_DIRECTIONS},
                        "economic_effect": {"type": "string", "enum": _ECONOMIC_EFFECT_INPUT_ENUM},
                        # Task 10: OPTIONAL -- omission defaults to UNKNOWN
                        # via GraphCompany's own validator, never required.
                        "expected_market_sensitivity": {"type": "string", "enum": MARKET_SENSITIVITY_LEVELS},
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
            # Ticker -> counterfactual verdict (Task 9): a map rather than a
            # per-company object field keeps the accept/reject/corrections
            # contract token-cheap -- one extra key, not a shape change to
            # every existing array. Keys are validated against
            # state.companies in the engine, not trusted as ticker identity
            # on their own.
            "counterfactual": {
                "type": "object",
                "additionalProperties": {"type": "string", "enum": COUNTERFACTUAL_VERDICTS},
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


# --- Completeness audit (architecture upgrade 2026-08-12, spec §13) ------
# The auditor actively searches for MISSING branches; it is not an edge
# verifier. Each missing branch is a full edge proposal plus reason_missing;
# accepted branches re-enter the expansion frontier in code.

SCHEMA_COMPLETENESS = {
    "type": "object",
    "properties": {
        "missing_branches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    **dict(_EDGE_PROPS),
                    "reason_missing": {"type": "string"},
                },
                "required": ["parent_type", "parent_id", "child_type", "child_id",
                             "mechanism", "confidence", "materiality", "reason_missing"],
            },
        },
        # Forced coverage: every ontology channel classified, so a skipped
        # channel is impossible to hide.
        "channel_audit": _CHANNEL_AUDIT,
    },
    "required": ["missing_branches", "channel_audit"],
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
    # Task 10: mirrors event_type's carry-through -- set from
    # facts.event_cause, "unknown" for cached pre-upgrade results
    # deserializing without it.
    event_cause: str = "unknown"
    facts: str = ""
    event_label: str = ""
    # Article-named entities carried through for the publication gate's
    # ARTICLE_SUBJECT evidence classification (spec §9). Default empty so
    # cached pre-upgrade results deserialize unchanged.
    named_entities: list[str] = Field(default_factory=list)
    companies: list[GraphCompany] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    ranking: list[dict] = Field(default_factory=list)  # [{ticker, bucket, rank_reason}]
    analysis_provider: str = "gemini"
    analysis_quality: str = "authoritative"  # authoritative | degraded | fallback | budget_exhausted
    # Observability (spec §30): per-run graph-quality counters --
    # nodes/edges discovered vs pruned, completeness branches, companies
    # considered vs retained, duplicates removed, verification failures.
    metrics: dict = Field(default_factory=dict)
