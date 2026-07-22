"""Maps each of app.analysis.schemas.SECTORS (18 values) to the NSE sector
index used as its excess-move benchmark (docs/NEWS_IMPACT_APP_SPEC.md §3,
§5). Sectors with no clean NSE sectoral index available on Yahoo Finance
fall back to the Nifty 50 (^NSEI) -- FALLBACK_SECTORS records exactly which
ones, so the UI can say "vs Nifty 50" instead of implying a sector index
that doesn't exist.

Every ticker in this map must be verified against a real yfinance call
before being trusted in production -- see backend/verify_sector_indices.py.
"""

NIFTY50_TICKER = "^NSEI"

SECTOR_INDEX_MAP: dict[str, str] = {
    "banking": "^NSEBANK",
    "it": "^CNXIT",
    "auto": "^CNXAUTO",
    "pharma": "^CNXPHARMA",
    "metals": "^CNXMETAL",
    "fmcg": "^CNXFMCG",
    "infra": "^CNXINFRA",
    "oil_gas": "^CNXENERGY",
    # No dedicated NSE transport/logistics index on Yahoo Finance -- infra
    # (EPC/industrials/utilities) is the closest sectoral proxy available.
    "railways_transport": "^CNXINFRA",
    "construction_realestate": "^CNXREALTY",
    "media_entertainment": "^CNXMEDIA",
    # No clean NSE sectoral index for these on Yahoo Finance -- Nifty 50 is
    # the fallback benchmark. Keep this list in sync with FALLBACK_SECTORS.
    "telecom": NIFTY50_TICKER,
    "defense": NIFTY50_TICKER,
    "agriculture": NIFTY50_TICKER,
    "consumer_durables": NIFTY50_TICKER,
    "chemicals": NIFTY50_TICKER,
    "textiles": NIFTY50_TICKER,
    "other": NIFTY50_TICKER,
}

# Sectors whose SECTOR_INDEX_MAP value is the Nifty 50 fallback rather than a
# real sector index -- must exactly match the sectors mapped to
# NIFTY50_TICKER above.
FALLBACK_SECTORS = frozenset({
    "telecom", "defense", "agriculture", "consumer_durables", "chemicals", "textiles", "other",
})


def benchmark_ticker_for_sector(sector: str) -> str:
    """The sector-index ticker to use as this sector's excess-move
    benchmark, or Nifty 50 if the sector has no clean NSE sectoral index
    (including any sector value not present in SECTOR_INDEX_MAP at all --
    never guess, fall back to the market)."""
    return SECTOR_INDEX_MAP.get(sector, NIFTY50_TICKER)


def is_fallback_benchmark(sector: str) -> bool:
    """True when benchmark_ticker_for_sector(sector) is the Nifty 50
    fallback rather than a real sector index -- lets the UI say "vs Nifty
    50" instead of implying a sector index exists."""
    return sector in FALLBACK_SECTORS or sector not in SECTOR_INDEX_MAP
