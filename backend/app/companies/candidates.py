"""Real-company candidate retrieval for the analysis prompts.

Without this the model names companies purely from parametric memory: it has
no list to select from, so it both invents links (a food-delivery company on
a crude-oil story) and returns nothing at all when it cannot recall a name
(61% of alerts had zero companies). Giving it the actual DB rows -- ticker,
name, sub-sector, and one-line business description -- converts the task from
recall to selection, and lets the tool schema enum-constrain `ticker` to
tickers that provably resolve.

Ordering is by real size (market cap), same as app.companies.resolution's
fan-out branch, so that when a sector has more companies than the limit, the
ones that survive are the prominent, liquid names an analyst would actually
consider -- and so the candidate list an analyst sees agrees with which
companies the fan-out could actually pick.
"""
from sqlalchemy.orm import Session

from app.companies.integrity import DEMO_TICKERS
from app.models import Company

# Per sector. Large enough that a real answer is almost always present,
# small enough that several sectors still fit one prompt alongside the
# rationale instructions.
MAX_CANDIDATES_PER_SECTOR = 40


def candidate_companies(
    session: Session, sectors: list[str], limit_per_sector: int = MAX_CANDIDATES_PER_SECTOR,
) -> list[Company]:
    """Every plausible company for the given sectors, most prominent first,
    deduplicated by ticker across sectors and with demo/seed and non-
    tradeable-Indian rows excluded. Order is stable (market cap, then
    ticker) so the same inputs always produce the same prompt -- a prompt
    that reshuffles between runs makes a regression impossible to
    attribute."""
    seen: set[str] = set()
    result: list[Company] = []
    for sector in sectors:
        rows = (
            session.query(Company)
            .filter_by(sector=sector)
            .filter(Company.ticker.notin_(DEMO_TICKERS))
            # Same market/tradeability restriction as
            # app.companies.resolution.resolve_companies' fan-out branch --
            # without it, RESTRICTED/SME/SUSPENDED/GLOBAL rows are eligible
            # both for the prompt text and for the tool schema's ticker
            # enum, so the model can be enum-constrained into a set with no
            # real Indian companies in it at all.
            .filter(Company.market == "INDIA")
            .filter(Company.tradeability == "NORMAL")
            .order_by(Company.market_cap.desc().nullslast(), Company.ticker.asc())
            .limit(limit_per_sector)
            .all()
        )
        for company in rows:
            if company.ticker in seen:
                continue
            seen.add(company.ticker)
            result.append(company)
    return result


def format_candidates(companies: list[Company]) -> str:
    """One line per company for prompt injection. A missing sub_sector or
    business_desc is omitted rather than rendered as "None" -- a literal
    "None" in the prompt reads as a real value to the model."""
    lines = []
    for company in companies:
        parts = [f"- {company.ticker} ({company.name}"]
        if company.sub_sector:
            parts.append(f", {company.sub_sector}")
        parts.append(")")
        line = "".join(parts)
        if company.business_desc:
            line += f": {company.business_desc}"
        lines.append(line)
    return "\n".join(lines)


def candidate_tickers(companies: list[Company]) -> list[str]:
    return [c.ticker for c in companies]
