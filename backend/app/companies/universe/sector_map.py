"""Official BSE classification -> the app's 12-value closed sector
vocabulary, plus tradeability derivation (spec §5.2, §6).

This module REPLACES the keyword guessing in app.companies.loader's
SECTOR_MAP. That approach bucketed Coal India into oil_gas because its
combined NSE industry string contained "gas" (see loader.py's comment).
Mapping from a discrete official Sector value instead of substring-matching
a free-text industry string removes that entire class of bug.

Pure data + pure functions: no I/O, no DB, no app.models import.
"""

# Keys are BSE's `Sector` field (the SEBI macro-economic sector set),
# lowercased. Values are the app's closed vocabulary -- the same 12 used by
# app.market.sector_indices, app.companies.sub_sectors and
# app.market.ripple_templates. Unmapped -> "other", never a guess.
OFFICIAL_SECTOR_TO_BUCKET = {
    "energy": "oil_gas",
    "oil gas & consumable fuels": "oil_gas",
    "financial services": "banking",
    "information technology": "it",
    "healthcare": "pharma",
    "fast moving consumer goods": "fmcg",
    "consumer durables": "fmcg",
    "consumer services": "fmcg",
    "metals & mining": "metals",
    "telecommunication": "telecom",
    "automobile and auto components": "auto",
    "chemicals": "chemicals",
    "construction": "infra",
    "construction materials": "infra",
    "capital goods": "infra",
    "power": "infra",
    "utilities": "infra",
    "realty": "infra",
    "services": "other",
    "textiles": "other",
    "media entertainment & publication": "other",
    "forest materials": "other",
    "diversified": "other",
}

_NSE_NORMAL_SERIES = {"EQ"}
_BSE_NORMAL_GROUPS = {"A", "B"}
_BSE_SME_GROUPS = {"M", "MT", "MS"}
_BSE_SUSPENDED_GROUPS = {"Z", "ZP"}

# Ordered most- to least-permissive. derive_tradeability picks the best
# listing: a company that is EQ on NSE is normally tradeable even if its
# BSE listing sits in group Z.
_PERMISSIVENESS = ["NORMAL", "RESTRICTED", "SME", "SUSPENDED"]


def map_sector(official_sector: str | None) -> str:
    if not official_sector:
        return "other"
    return OFFICIAL_SECTOR_TO_BUCKET.get(official_sector.strip().lower(), "other")


def listing_tradeability(
    exchange: str, series: str | None, group_code: str | None, status: str | None,
) -> str:
    if (status or "").upper() == "SUSPENDED":
        return "SUSPENDED"
    if exchange == "NSE":
        return "NORMAL" if (series or "").upper() in _NSE_NORMAL_SERIES else "RESTRICTED"
    group = (group_code or "").upper()
    if group in _BSE_SUSPENDED_GROUPS:
        return "SUSPENDED"
    if group in _BSE_SME_GROUPS:
        return "SME"
    if group in _BSE_NORMAL_GROUPS:
        return "NORMAL"
    return "RESTRICTED"


def derive_tradeability(listings: list[dict]) -> str:
    """Most-permissive listing wins. A company with no listings (the
    curated market='GLOBAL' rows) is NORMAL."""
    if not listings:
        return "NORMAL"
    values = [
        listing_tradeability(
            l["exchange"], l.get("series"), l.get("group_code"), l.get("status"),
        )
        for l in listings
    ]
    return min(values, key=_PERMISSIVENESS.index)
