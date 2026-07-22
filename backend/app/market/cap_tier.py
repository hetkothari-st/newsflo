"""Market-cap tier (docs/NEWS_IMPACT_APP_SPEC.md §4.5): AMFI-style rank
boundaries (top 100 = LARGE, 101-250 = MID, rest = SMALL), recomputed from
LIVE market cap every call -- never a hardcoded company list, never stored
as fixed truth (spec §3.2). Note: this is a distinct axis from
Company.index_tier (Nifty-index-membership tier, seeded once from
app.companies.nifty_indices_seed) -- that field is untouched by this
module."""
from sqlalchemy.orm import Session

from app import config
from app.models import Company


def compute_cap_tiers(companies: list[tuple[str, float]]) -> dict[str, str]:
    """``companies`` is [(ticker, market_cap_cr), ...] with non-null market
    caps. Ranks by market cap descending and buckets by AMFI-style rank
    cutoffs from app.config. Returns {ticker: 'LARGE'|'MID'|'SMALL'}."""
    ranked = sorted(companies, key=lambda tc: tc[1], reverse=True)
    tiers: dict[str, str] = {}
    for rank, (ticker, _cap) in enumerate(ranked, start=1):
        if rank <= config.AMFI_LARGE_CAP_RANK_CUTOFF:
            tiers[ticker] = "LARGE"
        elif rank <= config.AMFI_MID_CAP_RANK_CUTOFF:
            tiers[ticker] = "MID"
        else:
            tiers[ticker] = "SMALL"
    return tiers


def compute_cap_tier_for_ticker(session: Session, ticker: str) -> str | None:
    """Convenience wrapper: rank every Company with a non-null market_cap
    in the DB right now and return this ticker's tier, or None if it has
    no market_cap or isn't found. Queries fresh every call -- cap_tier is
    derived, never stored (spec §3.2)."""
    rows = (
        session.query(Company.ticker, Company.market_cap)
        .filter(Company.market_cap.isnot(None))
        .all()
    )
    tiers = compute_cap_tiers([(t, c) for t, c in rows])
    return tiers.get(ticker)
