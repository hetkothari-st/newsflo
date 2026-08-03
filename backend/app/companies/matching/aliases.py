"""Builds the company_aliases rows the matcher looks up.

Every alias comes from ingest data (exchange registries, listing symbols)
or the reviewed curated.py file. No LLM is involved -- this is master data,
not per-event data, same discipline as app.companies.business_profile's
"one-time enrichment, never written by the analysis pipeline".
"""
from sqlalchemy.orm import Session

from app.companies.matching.curated import CURATED_TRADE_NAMES
from app.companies.matching.normalize import normalize_name
from app.models import Company, CompanyAlias


def build_aliases_for_company(company: Company) -> list[dict]:
    """All alias candidates for one company, deduplicated by normalized
    form. First writer of a normalized form wins, so the LEGAL name's type
    survives when a symbol happens to normalize identically."""
    candidates: list[tuple[str, str]] = [(company.name, "LEGAL")]

    for listing in company.listings:
        alias_type = "NSE_SYMBOL" if listing.exchange == "NSE" else "BSE_ID"
        candidates.append((listing.symbol, alias_type))

    for trade_name in CURATED_TRADE_NAMES.get(company.ticker, ()):
        candidates.append((trade_name, "TRADE_NAME"))

    seen: set[str] = set()
    rows = []
    for alias, alias_type in candidates:
        normalized = normalize_name(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        rows.append({"alias": alias, "alias_type": alias_type, "normalized": normalized})
    return rows


def rebuild_aliases(session: Session) -> int:
    """Rebuild the alias set for every company. Idempotent: deletes this
    company's existing rows before rewriting, so a rerun after a name change
    doesn't leave a stale alias pointing at the wrong company. Returns the
    total row count."""
    total = 0
    for company in session.query(Company).all():
        session.query(CompanyAlias).filter_by(company_id=company.id).delete()
        for row in build_aliases_for_company(company):
            session.add(CompanyAlias(company_id=company.id, **row))
            total += 1
    session.commit()
    return total
