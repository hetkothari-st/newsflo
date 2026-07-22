"""Maps app.reasoning.rulebook.EDGE_RELATIONS (this codebase's existing
ImpactEdge.relation vocabulary) onto docs/NEWS_IMPACT_APP_SPEC.md's
RippleLink.relationship enum (spec §3.1) -- pure, no LLM call. Keeps every
edge's existing `source` provenance (rulebook_verified / rulebook_pruned /
llm_only) untouched; this is a read-time relabeling only, applied by a
later UI phase's grouping logic, never by rewriting ImpactEdge rows.
"""

RIPPLE_RELATIONSHIPS = [
    "BENEFICIARY", "CUSTOMER_INPUT_COST", "SUPPLIER", "SUBSTITUTE", "COMPETITOR", "SECTOR_WIDE",
]

# Documented, deterministic many-to-one mapping -- EDGE_RELATIONS has 10
# finer-grained values, the spec's RippleLink.relationship has 6 coarser
# ones, so this is necessarily lossy. Each choice below is a defensible
# reading of the existing relation's typical usage in
# app.reasoning.rulebook.CHAINS, not a claim of perfect semantic identity.
# SUBSTITUTE has no forward mapping (no existing relation genuinely means
# "alternative/replacement product") -- that's fine, the spec only
# requires every SOURCE value to map somewhere, not every target value to
# be reachable.
_RELATION_TO_RIPPLE_RELATIONSHIP: dict[str, str] = {
    "supplier": "SUPPLIER",
    "customer": "CUSTOMER_INPUT_COST",
    "input_cost": "CUSTOMER_INPUT_COST",
    "competitor": "COMPETITOR",
    "commodity": "BENEFICIARY",
    "demand": "BENEFICIARY",
    "credit_cost": "SECTOR_WIDE",
    "regulation": "SECTOR_WIDE",
    "currency": "SECTOR_WIDE",
    "correlation": "SECTOR_WIDE",
}


def relation_to_ripple_relationship(relation: str) -> str:
    """Maps a known ImpactEdge.relation value to the spec's RippleLink
    enum. An unrecognized relation (should not happen -- EDGE_RELATIONS is
    a closed, enum-constrained vocabulary at the LLM tool-schema layer --
    but defended here anyway) falls back to SECTOR_WIDE, the most
    conservative/general bucket, rather than raising."""
    return _RELATION_TO_RIPPLE_RELATIONSHIP.get(relation, "SECTOR_WIDE")


def is_exposure_only(measurement_status: str | None) -> bool:
    """True when a ripple-linked company has no real measured move
    (measurement_status is None, 'no_data', or 'stale') -- a later UI
    phase must label this as a flagged EXPOSURE, never an impact, and must
    never render a number/score for it (spec: "ripple companies that have
    not moved... show it as a flagged relationship with no number and no
    score -- never a fabricated magnitude")."""
    return measurement_status != "ok"
