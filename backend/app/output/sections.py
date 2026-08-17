"""TASK 6.2 -- THE DETERMINISTIC SECTION ENGINE (spec §15).

    section_key = (publication_tier, economic_effect, mechanism_id,
                   horizon_bucket)

PURE FUNCTION. No LLM, no disk, no clock, no database -- the taxonomy is
loaded by the impure sibling `section_config.py` and passed in. An LLM has no
role here: it does not name a section, does not assign a company to one, and
does not decide whether one exists.

THE FOUR INVARIANTS, each a test in `tests/phase6/test_sections.py`:

  * a section contains ONLY companies whose (tier, effect, mechanism,
    horizon) matches its key exactly -- true by construction, because a
    section IS a key and companies are grouped by it;
  * MIXED companies get their own section. An integrated energy company is
    never inside "NEGATIVE — OIL MARKETING & REFINING". This is the §15
    data-model fix: with the effect in the key, that placement is
    unrepresentable rather than merely discouraged;
  * empty sections are omitted -- sections are built FROM companies, never
    from the label list, so a mechanism nobody carries produces nothing;
  * no label concatenates a directness with a tier (the Phase 0 lint,
    extended to the rendered strings).

REJECTED IS NOT A TIER HERE. A rejected candidate is shown in the review
console with its reason (invariant 12); it is never a published section.

ORDERING: tier -> |median materiality| descending -> alphabetical. A section
whose companies carry no computed band cannot be ranked by magnitude, so it
sorts AFTER every sized section, alphabetically. It is NOT given a magnitude
of zero (which would read as "no impact") and NOT given the benefit of the
doubt.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

# Publication tiers that can carry a section, in display order. MACRO_CONTEXT
# is listed because §15's ordering names it; a company draft never reaches it
# (invariant 6 -- macro may not carry a company list), so in practice a macro
# section is mechanism-level and arrives from elsewhere.
SECTION_TIER_ORDER = ("PRIMARY", "SECONDARY_RIPPLE", "MACRO_CONTEXT")

# The two effects that are a DIRECTION. MIXED and UNCERTAIN are not, and
# never collapse into one (invariants 8 and 9).
DIRECTIONAL_EFFECTS = ("POSITIVE", "NEGATIVE")

TIER_REJECTED = "REJECTED"


@dataclass(frozen=True)
class SectionKey:
    publication_tier: str
    economic_effect: str
    mechanism_id: str | None
    horizon_bucket: str

    def as_tuple(self) -> tuple:
        return (self.publication_tier, self.economic_effect,
                self.mechanism_id, self.horizon_bucket)


@dataclass(frozen=True)
class Section:
    key: SectionKey
    label: str
    companies: tuple[Mapping[str, Any], ...]
    # |median| of the companies' computed p50, or None when no company in the
    # section carries a computed band.
    median_materiality: float | None


def section_key_for(impact: Any) -> SectionKey:
    """The key, read off the canonical record's OWN fields. Nothing is
    derived: `publication_tier` is the tier, `net_effect` is the effect,
    `mechanism_id` is the mechanism and `headline_horizon` is the horizon
    bucket -- four fields, four questions, never inferred from one another
    (invariant 4)."""
    return SectionKey(
        publication_tier=str(getattr(impact, "publication_tier")),
        economic_effect=str(getattr(impact, "net_effect")),
        mechanism_id=(None if getattr(impact, "mechanism_id") is None
                      else str(getattr(impact, "mechanism_id"))),
        horizon_bucket=str(getattr(impact, "headline_horizon")))


def _magnitude(impact: Any) -> float | None:
    """|p50| of the record's computed band, or None when it has none. Never
    0.0 -- "nobody sized this" and "this is zero" are different statements."""
    block = getattr(impact, "sensitivity", None)
    if not block:
        return None
    try:
        return abs(float((block.get("delta_ebitda_pct") or {})["p50"]))
    except (KeyError, TypeError, ValueError):            # pragma: no cover
        return None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _company_entry(impact: Any) -> dict:
    return {
        "company_id": getattr(impact, "company_id", None),
        "ticker": getattr(impact, "ticker", None),
        "materiality_bucket": getattr(impact, "materiality_bucket", None),
        "delta_ebitda_pct_p50_abs": _magnitude(impact),
        "evidence_grade": getattr(impact, "evidence_grade", None),
        # The four separation fields travel as FOUR keys, never joined.
        "directness": getattr(impact, "directness", None),
        "graph_distance": getattr(impact, "graph_distance", None),
        "discovery_source": getattr(impact, "discovery_source", None),
        "publication_tier": getattr(impact, "publication_tier", None),
    }


def build_sections(impacts: Sequence[Any], taxonomy: Any) -> tuple[Section, ...]:
    """Group published records into sections. PURE and order-independent."""
    grouped: dict[tuple, list[Any]] = {}
    for impact in impacts:
        key = section_key_for(impact)
        if key.publication_tier not in SECTION_TIER_ORDER:
            # REJECTED (and anything else outside the display tiers) is not a
            # section. It is not dropped either -- the console shows it with
            # its reason.
            continue
        grouped.setdefault(key.as_tuple(), []).append(impact)

    sections = []
    for raw_key, members in grouped.items():
        key = SectionKey(*raw_key)
        ordered = sorted(members, key=lambda i: (str(getattr(i, "ticker") or ""),
                                                 getattr(i, "company_id") or 0))
        magnitudes = [m for m in (_magnitude(i) for i in ordered) if m is not None]
        sections.append(Section(
            key=key,
            label=taxonomy.label_for(key.economic_effect, key.mechanism_id),
            companies=tuple(_company_entry(i) for i in ordered),
            median_materiality=_median(magnitudes)))

    return tuple(sorted(sections, key=_sort_key))


def _sort_key(section: Section) -> tuple:
    """tier -> |median materiality| desc -> alphabetical. A section with no
    computed magnitude sorts after every sized one (the 1 below), then
    alphabetically."""
    try:
        tier_rank = SECTION_TIER_ORDER.index(section.key.publication_tier)
    except ValueError:                                   # pragma: no cover
        tier_rank = len(SECTION_TIER_ORDER)
    if section.median_materiality is None:
        # The 1 is what puts the unsized section after every sized one; the
        # 0 that follows is a STRUCTURAL placeholder holding the magnitude
        # slot, never compared against a magnitude (the element before it
        # has already decided the order against any sized section).
        return (tier_rank, 1, 0, section.label)
    return (tier_rank, 0, -section.median_materiality, section.label)


def serialize_sections(sections: Sequence[Section]) -> list[dict]:
    """JSON-safe and deterministic -- the shape the console and any future
    serving path render, and the shape the determinism test compares."""
    return [{
        "key": {"publication_tier": s.key.publication_tier,
                "economic_effect": s.key.economic_effect,
                "mechanism_id": s.key.mechanism_id,
                "horizon_bucket": s.key.horizon_bucket},
        "label": s.label,
        "median_materiality": s.median_materiality,
        "companies": [dict(c) for c in s.companies],
    } for s in sections]


# ---------------------------------------------------------------------------
# §15's zero-PRIMARY state -- a designed state, not an error
# ---------------------------------------------------------------------------

def zero_primary_state(impacts: Sequence[Any], sections: Sequence[Section], *,
                       macro_channel_count: int = 0) -> dict:
    """The counts §15 renders, computed from the record set.

    `macro_channel_count` is supplied by the caller because a macro channel
    is a MECHANISM-level statement and may never carry a company list
    (invariant 6) -- so it cannot be counted off a set of company records.
    It defaults to 0, which is the truthful count when nobody supplies one.
    """
    primary = [i for i in impacts
               if str(getattr(i, "publication_tier")) == "PRIMARY"]
    second_order = [i for i in impacts
                    if str(getattr(i, "publication_tier")) == "SECONDARY_RIPPLE"]
    rejected = [i for i in impacts
                if str(getattr(i, "publication_tier")) == TIER_REJECTED]
    return {
        "zero_primary": not primary,
        "primary_count": len(primary),
        "second_order_count": len(second_order),
        "macro_channel_count": int(macro_channel_count),
        "rejected_count": len(rejected),
        "section_count": len(sections),
    }


def render_zero_primary(state: Mapping[str, Any], taxonomy: Any) -> str:
    """The §15 block, as text. Every word comes from the taxonomy file and
    every number from `state` -- nothing here writes a sentence about the
    world."""
    second_order = int(state["second_order_count"])
    macro = int(state["macro_channel_count"])
    rejected = int(state["rejected_count"])
    bullets = taxonomy.zero_primary["bullets"].format(
        second_order=second_order, macro=macro, rejected=rejected,
        effect_word=taxonomy.plural("effect_word", second_order),
        channel_word=taxonomy.plural("channel_word", macro),
        candidate_word=taxonomy.plural("candidate_word", rejected))
    return "\n".join((taxonomy.zero_primary["headline"],
                      taxonomy.zero_primary["body"], bullets))
