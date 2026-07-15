from sqlalchemy import case
from sqlalchemy.orm import Session

from app.analysis.schemas import CompanyMention
from app.models import Company

TOP_N_SECTOR_COMPANIES = 5

# Portable (SQLite + Postgres) ordering expression: rank companies by index
# tier so sector-inference picks the most prominent companies first. Lower
# rank value = higher priority.
_TIER_RANK = case(
    (Company.index_tier == "NIFTY50", 0),
    (Company.index_tier == "NIFTYNEXT50", 1),
    (Company.index_tier == "NIFTYMIDCAP150", 2),
    (Company.index_tier == "NIFTYSMALLCAP250", 3),
    else_=4,
)


def _to_resolved(company: Company, mention: CompanyMention, basis: str) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        "rationale": mention.rationale,
        "key_points": mention.key_points,
        # Raw LLM value if present, otherwise None -- always overwritten by
        # app.reasoning.confidence.compute_confidence before persistence
        # (see app/pipeline.py::_persist_alert).
        "confidence_score": mention.confidence_score,
        "time_horizon": mention.time_horizon,
        "basis": basis,
        "reasons": mention.reasons,
        "evidence_refs": mention.evidence_refs,
        "risks": mention.risks,
        "assumptions": mention.assumptions,
        "unknowns": mention.unknowns,
        "alternative_hypothesis": mention.alternative_hypothesis,
    }


def _find_direct_company(session: Session, mention: CompanyMention) -> Company | None:
    """Resolve a direct mention to a Company, trying ticker first, then name.

    The analysis model sometimes names a real company it is confident about
    without being confident of the exact ticker symbol. Falling straight
    through to sector-wide inference in that case would discard the model's
    specific reasoning and substitute a generic top-N-by-tier sector pick --
    exactly the kind of unrelated-company mismatch this resolver must avoid.
    Name matching only returns a company when there is exactly ONE candidate
    (either an exact case-insensitive match, or a single company whose name
    contains the mention's name or vice versa) -- an ambiguous match returns
    None rather than guessing, consistent with "omit rather than mismatch".
    """
    if mention.ticker:
        company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
        if company is not None:
            return company
    if not mention.name:
        return None
    name_lower = mention.name.strip().lower()
    if not name_lower:
        return None
    all_companies = session.query(Company).all()
    exact = [c for c in all_companies if c.name.strip().lower() == name_lower]
    if len(exact) == 1:
        return exact[0]
    contains = [c for c in all_companies if name_lower in c.name.lower() or c.name.lower() in name_lower]
    if len(contains) == 1:
        return contains[0]
    return None


def resolve_companies(session: Session, mentions: list[CompanyMention]) -> list[dict]:
    """Resolve every mention to a Company, deduplicated by company_id across
    the WHOLE mentions list.

    Without this, multiple sector-level mentions of the same sector in one
    article (a model deviation actually observed in production: naming 4
    specific companies but marking all of them is_direct=false with the same
    sector) each independently expand to the same top-N sector companies,
    producing severe duplication (one real case: 5 companies x 4 mentions =
    20 rows for a single article). First occurrence wins; later duplicate
    resolutions of an already-resolved company are dropped rather than
    appended again.
    """
    resolved = []
    seen_company_ids: set[int] = set()
    for mention in mentions:
        if mention.is_direct:
            company = _find_direct_company(session, mention)
            if company is None:
                continue
            if company.id in seen_company_ids:
                continue
            seen_company_ids.add(company.id)
            resolved.append(_to_resolved(company, mention, basis="direct_mention"))
        else:
            if not mention.sector:
                continue
            companies = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .order_by(_TIER_RANK.asc(), Company.ticker.asc())
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
            for company in companies:
                if company.id in seen_company_ids:
                    continue
                seen_company_ids.add(company.id)
                resolved.append(_to_resolved(company, mention, basis="sector_inference"))
    return resolved
