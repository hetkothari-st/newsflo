from sqlalchemy.orm import Session

from app.analysis.schemas import CompanyMention
from app.models import Company

TOP_N_SECTOR_COMPANIES = 5


def _to_resolved(company: Company, mention: CompanyMention, basis: str) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        "rationale": mention.rationale,
        "basis": basis,
    }


def resolve_companies(session: Session, mentions: list[CompanyMention]) -> list[dict]:
    resolved = []
    for mention in mentions:
        if mention.is_direct:
            if not mention.ticker:
                continue
            company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
            if company is None:
                continue
            resolved.append(_to_resolved(company, mention, basis="direct_mention"))
        else:
            if not mention.sector:
                continue
            companies = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .order_by(Company.market_cap.desc())
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
            for company in companies:
                resolved.append(_to_resolved(company, mention, basis="sector_inference"))
    return resolved
