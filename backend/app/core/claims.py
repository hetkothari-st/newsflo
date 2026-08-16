"""TASK 0.5 -- claim records (spec §11.1).

A claim is a RECORD before it is a sentence. The four claim types this
system historically fabricated -- PASS_THROUGH, HEDGE, COMPETITIVE, TIMING
-- may only exist when a company-named filing says so. There is no
"reasonable default" branch anywhere in this module: absent evidence yields
UNBOUND, and an UNBOUND claim is a hard REJECT in the gate (spec §11.3).

PURE MODULE. Standard library only.
"""
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import re

CLAIM_TYPES = (
    "COST_EXPOSURE", "REVENUE_EXPOSURE", "PASS_THROUGH", "HEDGE",
    "MATERIALITY", "OFFSET", "REGULATORY", "TIMING", "COMPETITIVE",
)
FACT_CLASSES = ("FACT", "DERIVED", "INFERENCE", "UNKNOWN")

# The four types the current system fabricates most (spec §11.1). No
# exceptions, and this set is deliberately not configurable.
EVIDENCE_REQUIRED_TYPES = frozenset({"PASS_THROUGH", "HEDGE", "COMPETITIVE", "TIMING"})

# Source types that can BIND a claim to a company. A news article, a broker
# note or the model's own prior can never do it.
ACCEPTED_SOURCES = frozenset({
    "ANNUAL_REPORT", "QUARTERLY", "EARNINGS_CALL", "EXCHANGE_FILING",
})

BINDING_STATUSES = ("BOUND", "SECTOR_PROXY", "UNBOUND")

# Ranked worst-first: `weakest_link` names the weakest binding a company
# carries, which is the thing a reader most needs to know.
_BINDING_RANK = {"UNBOUND": 0, "SECTOR_PROXY": 1, "BOUND": 2}

_DIGIT = re.compile(r"\d")


class ClaimVocabularyError(ValueError):
    """A claim outside the controlled vocabulary, or one whose numerals do
    not trace to a stored numeric field."""


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_type: str
    source_name: str
    source_date: str | None
    company_ids: tuple[int, ...]
    quoted_text: str | None = None
    fact_text: str = ""

    def names_company(self, company_id: int | None) -> bool:
        """Company-NAMED evidence, in the §11.1 sense: this artifact is
        about THIS company. Sector-level evidence returns False -- that is
        what makes it a SECTOR_PROXY rather than a binding."""
        return company_id is not None and company_id in self.company_ids


@dataclass(frozen=True)
class Claim:
    claim_id: str
    event_id: str
    company_id: int | None
    claim_type: str
    fact_class: str
    structured: Mapping[str, Any] = field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    created_by: str = ""

    def __post_init__(self):
        if self.claim_type not in CLAIM_TYPES:
            raise ClaimVocabularyError(
                f"{self.claim_type!r} is not a claim type ({CLAIM_TYPES})")
        if self.fact_class not in FACT_CLASSES:
            raise ClaimVocabularyError(
                f"{self.fact_class!r} is not a fact class ({FACT_CLASSES})")
        # Spec §11.1: "Any claim containing a numeral must trace to a stored
        # numeric field. Numerals may not originate in generated text." A
        # digit inside a STRING value of `structured` is generated text.
        for key, value in self.structured.items():
            if isinstance(value, str) and _DIGIT.search(value):
                raise ClaimVocabularyError(
                    f"{self.claim_id}: structured[{key!r}] carries a numeral "
                    "inside text; numerals must be stored as numeric fields")

    @property
    def numerals(self) -> tuple[float, ...]:
        return tuple(float(v) for v in self.structured.values()
                     if isinstance(v, (int, float)) and not isinstance(v, bool))


def binding_status(claim: Claim, evidence: Iterable[Evidence]) -> str:
    """BOUND | SECTOR_PROXY | UNBOUND, per spec §11.1's binding rules.

    Only evidence the claim actually cites counts -- an unrelated artifact
    sitting in the same event does not bind anything. A claim citing nothing
    is UNBOUND regardless of its type.
    """
    cited = [e for e in evidence if e.evidence_id in set(claim.evidence_ids)]
    names_company_from_filing = any(
        e.source_type in ACCEPTED_SOURCES and e.names_company(claim.company_id)
        for e in cited)

    if claim.claim_type in EVIDENCE_REQUIRED_TYPES:
        # No exceptions: these four are the fabrication hot spots.
        return "BOUND" if names_company_from_filing else "UNBOUND"

    if names_company_from_filing:
        return "BOUND"
    if cited:
        # Real artifacts, but none of them is about this company -- the
        # honest label is "we are reasoning from the sector".
        return "SECTOR_PROXY"
    return "UNBOUND"


def weakest_binding(bindings: Iterable[tuple[str, str]]) -> str | None:
    """`(claim_type, binding_status)` pairs -> "claim_type:binding_status"
    for the weakest one, or None when there are no claims at all. Ties break
    on claim_type alphabetically so the value is deterministic."""
    ranked = sorted(bindings, key=lambda pair: (_BINDING_RANK.get(pair[1], 0), pair[0]))
    if not ranked:
        return None
    claim_type, status = ranked[0]
    return f"{claim_type}:{status}"
