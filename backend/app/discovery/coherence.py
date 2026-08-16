"""TASK 3.6 / addendum A5.2 -- the sector coherence rule.

    "If a mechanism fires and >=3 companies in an industry clear the ripple
     gate, publish the SECTION. If only one clears while peers were rejected
     on DATA GAPS rather than on ECONOMICS, prefer publishing the section
     with a coverage note over publishing a lone name."

The reason this rule exists is credibility, not completeness. A section
containing one paint maker and nothing else does not read as an analysis; it
reads as a bug, and the reader is right, because the other five names are
missing for a reason that has nothing to do with them. Saying so is the
honest version:

    SECONDARY -- TYRES & RUBBER - negative on synthetic rubber and carbon
    black cost
    Apollo Tyres, CEAT, JK Tyre - 2 further names in this sector lack
    company-level input data

THE DISTINCTION THAT KEEPS THE NOTE HONEST. A peer we could not size is a
coverage gap. A peer we DID size and found immaterial is not -- it is an
answer. Counting the second kind would turn "we checked and it is fine" into
"we do not know", which is a lie in our own favour.

PURE. No database, no config file, no clock.
"""
from dataclasses import dataclass

# Rejection reasons that mean "we could not look", as opposed to "we looked
# and the answer was no". Extend this list only with a reason that genuinely
# describes MISSING DATA.
DATA_GAP_REASONS = frozenset({
    "NO_EXPOSURE_ROW",
    "EXPOSURE_STALE",
    "UNCOMPUTABLE_CHANNEL",
    "NO_EBITDA_BASE",
    "INSUFFICIENT_PARAMETER_DATA",
    "ENTITY_UNRESOLVED",
})

# >= this many cleared names and the section stands on its own.
COHERENT_SECTION_SIZE = 3


@dataclass(frozen=True)
class SectionMember:
    company_id: int
    cleared: bool
    rejection_reason: str | None = None


@dataclass(frozen=True)
class SectionDecision:
    industry: str
    publish: bool
    company_ids: tuple[int, ...]
    coverage_note: str | None
    data_gap_peers: int
    economic_peers: int


def section_decision(industry: str, members, *,
                     min_companies: int = 1) -> SectionDecision:
    """Whether to publish a section for `industry`, and with what note."""
    members = tuple(members)
    cleared = tuple(m.company_id for m in members if m.cleared)
    rejected = [m for m in members if not m.cleared]
    data_gap = sum(1 for m in rejected
                   if (m.rejection_reason or "") in DATA_GAP_REASONS)
    economic = len(rejected) - data_gap

    publish = len(cleared) >= max(1, int(min_companies))
    note = None
    if publish and len(cleared) < COHERENT_SECTION_SIZE and data_gap:
        note = (f"{data_gap} further name{'s' if data_gap != 1 else ''} in "
                "this sector lack company-level input data")

    return SectionDecision(industry=industry, publish=publish,
                           company_ids=cleared, coverage_note=note,
                           data_gap_peers=data_gap, economic_peers=economic)
