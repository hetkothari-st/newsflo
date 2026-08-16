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

There is no V5 serving path yet (Phase 0 ruling), so this is the surface a
future renderer consumes, and it is tested as such.
"""
from typing import Any, Mapping

from app.analysis.sensitivity.config import load_materiality_config

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
