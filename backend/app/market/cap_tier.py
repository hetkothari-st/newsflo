"""Market-cap tier (docs/NEWS_IMPACT_APP_SPEC.md §4.5): AMFI-style rank
boundaries (top 100 = LARGE, 101-250 = MID, 251-500 = SMALL, 501+ = MICRO),
recomputed from LIVE market cap every call -- never a hardcoded company
list, never stored as fixed truth (spec §3.2). Note: this is a distinct
axis from Company.index_tier (Nifty-index-membership tier, seeded once from
app.companies.nifty_indices_seed) -- that field is untouched by this
module."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import config
from app.models import Company


def compute_cap_tiers(companies: list[tuple[str, float]]) -> dict[str, str]:
    """``companies`` is [(ticker, market_cap_cr), ...] with non-null market
    caps. Ranks by market cap descending and buckets by AMFI-style rank
    cutoffs from app.config: rank 501+ (config.MICRO_CAP_RANK_CUTOFF) is
    MICRO -- NSE's published Nifty Microcap 250 index methodology (ranks
    501-750), not an invented rupee floor. Returns
    {ticker: 'LARGE'|'MID'|'SMALL'|'MICRO'}.

    Sort key is (cap descending, ticker ascending) -- a total order.
    Neither caller queries its pool with an ORDER BY, so two exactly-tied
    market caps would otherwise rank by whatever physical row order the DB
    happens to return them in, which is stable-but-arbitrary on SQLite and
    genuinely unstable across Postgres query plans. A tie straddling rank
    100/250/500 could then flip a company's tier between calls (or between
    compute_cap_tier_for_ticker and cap_tier_map, resurrecting the exact
    disagreement the staleness-pool fix above was written to prevent).
    Breaking ties by ticker makes the result independent of row order."""
    ranked = sorted(companies, key=lambda tc: (-tc[1], tc[0]))
    tiers: dict[str, str] = {}
    for rank, (ticker, _cap) in enumerate(ranked, start=1):
        if rank <= config.AMFI_LARGE_CAP_RANK_CUTOFF:
            tiers[ticker] = "LARGE"
        elif rank <= config.AMFI_MID_CAP_RANK_CUTOFF:
            tiers[ticker] = "MID"
        elif rank <= config.MICRO_CAP_RANK_CUTOFF:
            tiers[ticker] = "SMALL"
        else:
            tiers[ticker] = "MICRO"
    return tiers


def compute_cap_tier_for_ticker(session: Session, ticker: str) -> str | None:
    """Convenience wrapper: rank every ``market == 'INDIA'`` Company with a
    non-null market_cap in the DB right now and return this ticker's tier,
    or None if it has no market_cap, isn't Indian, or isn't found. Queries
    fresh every call -- cap_tier is derived, never stored (spec §3.2).

    The pool is India-only because the AMFI-style rank cutoffs
    (config.AMFI_LARGE_CAP_RANK_CUTOFF etc.) are an India-only construct:
    they approximate AMFI's actual published LARGE/MID/SMALL universe,
    which only ranks Indian-listed companies. Mixing in
    ``market == 'GLOBAL'`` rows (curated non-Indian companies, often with
    market caps in a different currency/scale) would shift every Indian
    company's rank and silently misclassify them -- a foreign mega-cap
    could bump a real Indian large-cap into MID. A GLOBAL ticker is simply
    absent from the pool, so this returns None for it, consistent with
    resolve_cap_tier's own "no tier for non-Indian companies" rule."""
    rows = (
        session.query(Company.ticker, Company.market_cap)
        .filter(Company.market == "INDIA", Company.market_cap.isnot(None))
        .all()
    )
    tiers = compute_cap_tiers([(t, c) for t, c in rows])
    return tiers.get(ticker)


@dataclass(frozen=True)
class CapTier:
    tier: str
    source: str
    as_of: date | None


def _is_stale(as_of: date | None, max_age_days: int, today: date) -> bool:
    """A missing as_of is treated as stale: an undated value cannot be shown
    as current."""
    if as_of is None:
        return True
    return (today - as_of) > timedelta(days=max_age_days)


def resolve_cap_tier(session: Session, company: Company, today: date | None = None) -> CapTier | None:
    """The single entry point for a company's cap tier (spec §7).

    Precedence: AMFI's published tier where present and fresh, otherwise the
    tier derived from exchange-published caps. Returns None -- never a
    guess -- when the company is not Indian, has no market cap, or its cap
    is too stale to rank honestly.

    AMFI publishes only LARGE/MID/SMALL; MICRO is a subdivision of AMFI's
    open-ended SMALL band using NSE's index methodology, and the reported
    source says so rather than crediting AMFI with a label it never
    published.
    """
    today = today or date.today()
    if company.market != "INDIA":
        return None
    if company.market_cap is None:
        return None
    if _is_stale(company.market_cap_as_of, config.MARKET_CAP_MAX_AGE_DAYS, today):
        return None

    derived = compute_cap_tier_for_ticker(session, company.ticker)
    if derived is None:
        return None

    amfi_fresh = (
        company.amfi_tier
        and not _is_stale(company.amfi_as_of, config.AMFI_MAX_AGE_DAYS, today)
    )
    if not amfi_fresh:
        source = f"derived from {company.market_cap_source or 'unknown'} {company.market_cap_as_of.isoformat()}"
        return CapTier(derived, source, company.market_cap_as_of)

    amfi_stamp = f"AMFI {company.amfi_as_of.isoformat()}"
    if company.amfi_tier == "SMALL" and derived == "MICRO":
        return CapTier("MICRO", f"{amfi_stamp} + NSE index methodology", company.amfi_as_of)
    return CapTier(company.amfi_tier, amfi_stamp, company.amfi_as_of)


def cap_tier_map(session: Session, today: date | None = None) -> dict[str, str]:
    """{ticker: tier} for every Indian company with a fresh market cap.

    The batch counterpart to resolve_cap_tier, for callers that tag many
    companies at once (app.market.discovery, app.market.ripple_layers).
    Applies the same precedence and the same staleness rule -- a ticker
    absent from the result has no honest tier and must render as "no data",
    never as a default bucket.

    The ranking pool is every ``market == 'INDIA'`` company with a non-null
    market_cap, staleness notwithstanding -- the same pool
    compute_cap_tier_for_ticker uses for a single-company lookup. A stale
    company's cap still occupies a rank slot (it did trade at that
    valuation once; excluding it would shift every other company's rank),
    it just never itself receives a tier. Filtering the pool down to fresh
    rows before ranking would give this function a different rank order
    than resolve_cap_tier computes for the exact same ticker -- the two
    entry points would disagree.
    """
    today = today or date.today()
    companies = (
        session.query(Company)
        .filter(Company.market == "INDIA")
        .filter(Company.market_cap.isnot(None))
        .all()
    )
    derived = compute_cap_tiers([(c.ticker, c.market_cap) for c in companies])

    tiers: dict[str, str] = {}
    for company in companies:
        if _is_stale(company.market_cap_as_of, config.MARKET_CAP_MAX_AGE_DAYS, today):
            continue
        base = derived.get(company.ticker)
        if base is None:
            continue
        amfi_fresh = (
            company.amfi_tier
            and not _is_stale(company.amfi_as_of, config.AMFI_MAX_AGE_DAYS, today)
        )
        if not amfi_fresh:
            tiers[company.ticker] = base
        elif company.amfi_tier == "SMALL" and base == "MICRO":
            tiers[company.ticker] = "MICRO"
        else:
            tiers[company.ticker] = company.amfi_tier
    return tiers
