import csv

from sqlalchemy.orm import Session

from app.models import Company

SECTOR_MAP = {
    "oil": "oil_gas", "gas": "oil_gas", "petroleum": "oil_gas",
    "bank": "banking", "financial": "banking",
    "automobile": "auto", "auto": "auto",
    "software": "it", "information technology": "it",
    "pharmaceutical": "pharma", "healthcare": "pharma",
    "fmcg": "fmcg", "consumer": "fmcg",
    "metal": "metals", "mining": "metals",
    "telecom": "telecom",
    "infrastructure": "infra", "construction": "infra", "power": "infra",
}


def _normalize_sector(industry: str) -> str:
    lowered = industry.strip().lower()
    for keyword, sector in SECTOR_MAP.items():
        if keyword in lowered:
            return sector
    return "other"


def load_companies_from_csv(session: Session, csv_path: str, index_tier: str) -> int:
    count = 0
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticker = f"{row['Symbol'].strip()}.NS"
            sector = _normalize_sector(row["Industry"])
            name = row["Company Name"].strip()

            existing = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if existing:
                existing.name = name
                existing.sector = sector
                existing.index_tier = index_tier
            else:
                session.add(Company(ticker=ticker, name=name, sector=sector, index_tier=index_tier))
            count += 1
    session.commit()
    return count
