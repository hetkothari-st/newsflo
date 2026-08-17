"""TASK 2.5 -- the UI contract. NEVER A BARE NUMBER.

The phase file's contract:

    NEGATIVE | NEAR TERM | -3.2% EBITDA (range -6.0% to -1.1%)
    Most sensitive to: pass-through 55% (earnings call disclosure)

Two rules make this more than formatting:

  * a p50 is never rendered without its band. `materiality_line` raises when
    the record carries no band, rather than printing the midpoint alone;
  * the top driver is named WITH ITS SOURCE, because "61% of this call rests
    on a pass-through we took from a sector median" is the sentence that
    lets an analyst argue with the right lever.

ASCII SEPARATOR. The spec renders the separator as a middle dot; this uses
"|" so the string survives every console the repo runs on. The separator is
cosmetic; the band and the source are not.

V5 PHASE 4 adds two things to this contract, and they are the two the phase
file says are worth more than the impact call itself:

  * THE HEADLINE LEADS, THE OTHER TWO ARE THERE. `horizon_lines` renders all
    three horizons in time order with the headline marked. A renderer that
    shows only the headline is showing a V4 record; a renderer that has to
    guess which two were dropped cannot exist, because none were.
  * THE MODIFIERS ARE CHIPS. `modifier_chips` renders every policy modifier
    considered -- applied, unknown-state, unresolvable or not triggered --
    with a link to the notification. "We modelled the windfall levy and could
    not size it" and "there is no windfall levy" must not look the same.

There is no V5 serving path yet (Phase 0 ruling), so this is the surface a
future renderer consumes, and it is tested as such.
"""
from typing import Any, Mapping, Sequence

from app.analysis.sensitivity.config import load_materiality_config
from app.analysis.sensitivity.horizons import HORIZON_ORDER

SOURCE_LABELS = {
    "FILED": "filed disclosure",
    "DISCLOSED_CALL": "earnings call disclosure",
    "SECTOR_PROXY": "sector proxy",
    "MODELLED": "modelled estimate",
}


def _pct(value: float) -> str:
    return f"{value:.1f}%"


# FIX ROUND 1 (concern 4b). An interest-rate channel moves the interest line,
# which sits BELOW EBITDA. §5.1 still measures it against EBITDA_ttm to get a
# comparable percentage, but rendering it as "-2.5% EBITDA" would state
# something false about which line moved.
BASE_PHRASES = {
    ("EBITDA",): "EBITDA",
    ("PRE_TAX_INTEREST_LINE",): "of EBITDA, interest line (below EBITDA)",
}
MIXED_BASE_PHRASE = "of EBITDA, mixed EBITDA and interest line"


def base_phrase(bases: Any) -> str:
    key = tuple(bases or ("EBITDA",))
    if key in BASE_PHRASES:
        return BASE_PHRASES[key]
    return MIXED_BASE_PHRASE


def format_band(band: Mapping[str, Any], bases: Any = ("EBITDA",)) -> str:
    return (f"{_pct(float(band['p50']))} {base_phrase(bases)} "
            f"(range {_pct(float(band['p10']))} to {_pct(float(band['p90']))})")


def format_driver(driver: Mapping[str, Any]) -> str:
    """"pass-through 55% (earnings call disclosure, ev-123)".

    A parameter that is a fraction of something is shown as a percentage;
    anything else (an elasticity, say) is shown as itself -- 150% would be a
    nonsense reading of an elasticity of 1.5.

    FIX ROUND 1 (M3): the evidence id is rendered alongside the source
    category. "Sector proxy" tells an analyst what KIND of number it is; the
    id tells them which document to open and argue with.
    """
    config = load_materiality_config()
    name = str(driver["param"])
    bare = name.split("(")[0]
    point = float(driver["point"])
    value = f"{point * 100:.0f}%" if bare in config.param_bounds else f"{point:g}"
    label = SOURCE_LABELS.get(str(driver["source"]), str(driver["source"]))
    evidence_id = driver.get("evidence_id")
    reference = f"{label}, {evidence_id}" if evidence_id else label
    return f"{name.replace('_', '-')} {value} ({reference})"


def materiality_line(impact) -> str:
    """The two-line contract for one `CompanyImpact`."""
    block = getattr(impact, "sensitivity", None)
    if not block:
        raise ValueError(
            "this impact carries no computed materiality band, so there is no "
            "honest way to render a number for it")
    band = block.get("delta_ebitda_pct") or {}
    if not {"p10", "p50", "p90"} <= set(band):
        raise ValueError("a p50 may never be shown without its p10 and p90")

    horizon = str(impact.headline_horizon).replace("_", " ")
    head = (f"{impact.net_effect} | {horizon} | "
            f"{format_band(band, block.get('materiality_bases'))}")
    drivers = block.get("driver_ranking") or []
    if not drivers:
        return head + "\nMost sensitive to: no parameter with any uncertainty"
    return head + "\nMost sensitive to: " + ", ".join(
        format_driver(driver) for driver in drivers)


# --- V5 PHASE 4 (Task 4.4) --------------------------------------------------

MODIFIER_STATUS_LABELS = {
    "APPLIED": "modelled",
    "UNKNOWN_STATE": "regime unknown, band widened",
    "UNRESOLVED": "could not be sized, band widened",
    "NOT_TRIGGERED": "considered, did not apply",
}


def horizon_lines(impact) -> list[str]:
    """One line per horizon, IN TIME ORDER, with the headline marked.

    All three are always returned, including the ones nobody evaluated, which
    say so. The renderer decides what to collapse behind an expander; it never
    decides what to DROP, because the dropping is the defect (§8).
    """
    out = []
    for horizon in HORIZON_ORDER:
        entry = impact.direction_by_horizon.get(horizon) or {}
        marker = "> " if horizon == impact.headline_horizon else "  "
        label = horizon.replace("_", " ")
        if not entry.get("evaluated"):
            out.append(f"{marker}{label}: not evaluated")
            continue
        magnitude = entry.get("delta_ebitda_pct_p50")
        size = f" {_pct(float(magnitude))}" if magnitude is not None else ""
        out.append(f"{marker}{label}: {entry['direction']} "
                   f"({entry['materiality']}){size}")
    return out


def modifier_chips(impact) -> list[Mapping[str, Any]]:
    """The chips Task 4.4 requires: `{label, modifier_id, modifier_type,
    source_url, status, horizons, note}`, in a stable order.

    A chip whose `source_url` is None is still rendered -- with no link. A
    modifier we applied and cannot cite is a worse thing to hide than to show.
    """
    return [{
        "label": f"{entry['modifier_id']} "
                 f"({MODIFIER_STATUS_LABELS.get(str(entry.get('status')), str(entry.get('status')))})",
        "modifier_id": entry["modifier_id"],
        "modifier_type": entry.get("modifier_type"),
        "source_url": entry.get("source_url"),
        "status": entry.get("status"),
        "horizons": list(entry.get("horizons") or ()),
        "note": entry.get("note") or "",
    } for entry in impact.policy_modifiers_detail]


def impact_lines(impact) -> Sequence[str]:
    """The whole company block a renderer needs: the headline materiality
    line, the three horizons, and the modifier chips."""
    lines = [materiality_line(impact), ""]
    lines.extend(horizon_lines(impact))
    chips = modifier_chips(impact)
    if chips:
        lines.append("")
        lines.append("Policy: " + " | ".join(chip["label"] for chip in chips))
    return lines
