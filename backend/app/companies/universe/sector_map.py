"""Official BSE classification -> the app's 12-value closed sector
vocabulary, plus tradeability derivation (spec §5.2, §6).

This module REPLACES the keyword guessing in app.companies.loader's
SECTOR_MAP. That approach bucketed Coal India into oil_gas because its
combined NSE industry string contained "gas" (see loader.py's comment).
Mapping from a discrete official Sector value instead of substring-matching
a free-text industry string removes that entire class of bug.

Pure data + pure functions: no I/O, no DB, no app.models import.
"""

# Keyed on BSE's IndustryNew level FIRST, with the coarser Sector level as a
# fallback. The original table was built from the ddlIndustry master, which
# returns IndustryNew names, but was applied to Sector -- so "Consumer
# Discretionary", "Industrials", "Commodities", "Services" and "Diversified"
# all fell through to "other", which was 2,971 production companies. Both
# levels live in one table because their vocabularies do not overlap except
# where they agree (e.g. "Energy").
OFFICIAL_SECTOR_TO_BUCKET = {
    # --- Sector level (coarse) ---
    "energy": "oil_gas",
    "financial services": "banking",
    "information technology": "it",
    "healthcare": "pharma",
    "fast moving consumer goods": "fmcg",
    "telecommunication": "telecom",
    "utilities": "infra",
    "diversified": "other",
    # --- IndustryNew level (finer; takes precedence) ---
    "oil, gas & consumable fuels": "oil_gas",
    "automobile and auto components": "auto",
    "capital goods": "infra",
    "construction": "infra",
    "construction materials": "infra",
    "power": "infra",
    "realty": "construction_realestate",
    "chemicals": "chemicals",
    "metals & mining": "metals",
    "consumer durables": "consumer_durables",
    "consumer services": "fmcg",
    "textiles": "textiles",
    "media, entertainment & publication": "media_entertainment",
    "media entertainment & publication": "media_entertainment",
    "transport services": "railways_transport",
    "transport infrastructure": "railways_transport",
    "agricultural food & other products": "agriculture",
    "fertilizers & agrochemicals": "agriculture",
    "forest materials": "other",
    "services": "other",
}

_NSE_NORMAL_SERIES = {"EQ"}
_BSE_NORMAL_GROUPS = {"A", "B"}
_BSE_SME_GROUPS = {"M", "MT", "MS"}
_BSE_SUSPENDED_GROUPS = {"Z", "ZP"}

# Ordered most- to least-permissive. derive_tradeability picks the best
# listing: a company that is EQ on NSE is normally tradeable even if its
# BSE listing sits in group Z.
_PERMISSIVENESS = ["NORMAL", "RESTRICTED", "SME", "SUSPENDED"]


def map_sector(official_sector: str | None, official_industry: str | None = None) -> str:
    """BSE publishes four classification levels. IndustryNew is the finest one
    whose vocabulary matches this table, so it is tried first; Sector is the
    fallback for rows where IndustryNew is absent or unrecognised.

    Order matters and is the whole point of this function: keying on Sector
    alone left 65% of Indian companies as "other" in production.
    """
    for value in (official_industry, official_sector):
        if not value:
            continue
        bucket = OFFICIAL_SECTOR_TO_BUCKET.get(value.strip().lower())
        if bucket and bucket != "other":
            return bucket
    # Nothing matched to a real sector. Fall back to an explicit "other"
    # mapping if either level has one, else "other" by default -- same result,
    # but it distinguishes "we know this is other" from "we do not know".
    for value in (official_industry, official_sector):
        if value and OFFICIAL_SECTOR_TO_BUCKET.get(value.strip().lower()) == "other":
            return "other"
    return "other"


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
