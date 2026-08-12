"""Exposure-based company candidate retrieval (architecture upgrade
2026-08-12 §9): candidate generation must reflect ECONOMIC EXPOSURE, not
only sector membership.

Two deterministic, zero-LLM mechanisms:

1. An exposure ontology mapping economic-node vocabulary (crude price,
   interest rates, consumer demand, ...) to the sectors whose companies
   carry that exposure. An economic node WITHOUT a sector of its own --
   previously a dead end for company mapping -- now retrieves a real
   candidate pool.

2. The CompanyNodeExposure relationship cache queried BY NODE KEY across
   all sectors: a company whose exposure to `crude_oil_price` was verified
   on an earlier event is a candidate on every future event that builds
   that node, regardless of which sector list it would appear in.

Both feed the same downstream rails (ticker enums, MAX_CANDIDATES_PER_CALL,
tradeability filters); nothing here widens what the model may select from
beyond the supplied database.
"""
from sqlalchemy.orm import Session

from app.companies.integrity import DEMO_TICKERS
from app.models import Company

# Keyword -> sectors ontology. Keys are matched as substrings against the
# NORMALIZED node id (snake_case, post-normalize.py), so "crude_price_rise",
# "rising_crude_oil_price" and "crude_supply_disruption" all hit "crude".
# Sector slugs must exist in app.analysis.schemas.SECTORS. Deliberately
# curated, not exhaustive: a wrong hint costs prompt tokens, a missing hint
# only falls back to the sector-node path that exists anyway.
EXPOSURE_SECTOR_HINTS: dict[str, list[str]] = {
    # commodity / input-cost exposure
    "crude": ["oil_gas", "chemicals", "auto", "railways_transport", "agriculture"],
    "oil_price": ["oil_gas", "chemicals", "railways_transport"],
    "fuel": ["railways_transport", "auto", "oil_gas"],
    "aviation": ["railways_transport"],
    "freight": ["railways_transport", "metals"],
    "logistic": ["railways_transport", "infra"],
    "shipping": ["railways_transport", "metals", "oil_gas"],
    "commodity": ["metals", "oil_gas", "agriculture"],
    "steel": ["metals", "infra", "auto", "construction_realestate"],
    "metal": ["metals", "auto", "construction_realestate"],
    "cement": ["infra", "construction_realestate"],
    "coal": ["metals", "oil_gas", "infra"],
    "power": ["infra", "metals"],
    "electricity": ["infra", "metals"],
    "gold": ["consumer_durables", "banking"],
    "fertilizer": ["agriculture", "chemicals"],
    "agri": ["agriculture", "fmcg"],
    "crop": ["agriculture", "fmcg"],
    "monsoon": ["agriculture", "fmcg", "auto"],
    "chemical": ["chemicals"],
    "polymer": ["chemicals", "auto"],
    "textile": ["textiles"],
    "cotton": ["textiles", "agriculture"],
    # rates / credit / financing exposure
    "interest_rate": ["banking", "construction_realestate", "auto", "infra"],
    "repo_rate": ["banking", "construction_realestate", "auto"],
    "monetary": ["banking", "construction_realestate"],
    "credit": ["banking", "construction_realestate", "auto"],
    "lending": ["banking"],
    "liquidity": ["banking"],
    "financing": ["banking", "infra", "construction_realestate"],
    "borrowing_cost": ["banking", "infra", "construction_realestate"],
    "bond_yield": ["banking"],
    # demand-side exposure
    "consumer_demand": ["fmcg", "consumer_durables", "auto", "media_entertainment", "textiles"],
    "consumer_spending": ["fmcg", "consumer_durables", "auto", "media_entertainment"],
    "discretionary": ["consumer_durables", "auto", "media_entertainment", "textiles"],
    "household_income": ["fmcg", "consumer_durables", "banking", "construction_realestate"],
    "rural_demand": ["fmcg", "auto", "agriculture"],
    "urban_demand": ["fmcg", "consumer_durables", "auto"],
    "housing": ["construction_realestate", "banking", "consumer_durables", "metals"],
    "real_estate": ["construction_realestate", "banking"],
    "tourism": ["railways_transport", "media_entertainment"],
    "travel": ["railways_transport"],
    # macro / policy exposure
    "inflation": ["fmcg", "banking", "consumer_durables", "auto"],
    "currency": ["it", "pharma", "oil_gas", "metals", "textiles"],
    "rupee": ["it", "pharma", "oil_gas", "metals", "textiles"],
    "export": ["it", "pharma", "textiles", "chemicals", "metals", "auto", "agriculture"],
    "import": ["oil_gas", "chemicals", "consumer_durables", "metals"],
    "tariff": ["metals", "chemicals", "pharma", "textiles", "it", "auto"],
    "trade": ["metals", "chemicals", "textiles", "it", "pharma"],
    "capex": ["infra", "metals", "banking", "construction_realestate"],
    "infrastructure": ["infra", "metals", "construction_realestate", "banking"],
    "government_spending": ["infra", "defense", "construction_realestate", "metals"],
    "fiscal": ["infra", "banking", "fmcg"],
    "defense": ["defense"],
    "employment": ["fmcg", "banking", "consumer_durables", "it"],
    "unemployment": ["fmcg", "banking", "consumer_durables", "construction_realestate"],
    "wage": ["fmcg", "it", "consumer_durables"],
    "gst": ["fmcg", "auto", "consumer_durables"],
    "tax": ["fmcg", "auto", "consumer_durables", "banking"],
    # sector-adjacent economics
    "pharma": ["pharma"],
    "drug": ["pharma"],
    "healthcare": ["pharma"],
    "telecom": ["telecom"],
    "spectrum": ["telecom"],
    "data_center": ["it", "infra", "telecom"],
    "semiconductor": ["it", "consumer_durables", "auto"],
    "ev_": ["auto", "metals", "infra"],
    "electric_vehicle": ["auto", "metals", "infra"],
    "battery": ["auto", "metals", "chemicals"],
    "media": ["media_entertainment", "telecom"],
    "advertising": ["media_entertainment", "fmcg"],
}


def sectors_for_node(node_id: str, label: str = "") -> list[str]:
    """Deterministic exposure hint: sectors whose companies plausibly carry
    the economic exposure this node describes. Empty when nothing matches --
    the caller then simply has no exposure pool (never an error)."""
    haystack = f"{node_id} {label}".lower().replace(" ", "_")
    sectors: list[str] = []
    for keyword, hinted in EXPOSURE_SECTOR_HINTS.items():
        if keyword in haystack:
            for sector in hinted:
                if sector not in sectors:
                    sectors.append(sector)
    return sectors


def cached_exposed_companies(session: Session, node_key: str, limit: int = 15) -> list[Company]:
    """Companies with a VERIFIED positive exposure to this node key from any
    earlier event, regardless of sector -- the relationship cache used as a
    retrieval index, not just a dedup. Same tradeability rails as the
    sector pools."""
    from app.models import CompanyNodeExposure

    rows = (
        session.query(Company)
        .join(CompanyNodeExposure, CompanyNodeExposure.company_id == Company.id)
        .filter(CompanyNodeExposure.node_key == node_key,
                CompanyNodeExposure.exposure_exists == 1)
        .filter(Company.ticker.notin_(DEMO_TICKERS))
        .filter(Company.market == "INDIA")
        .filter(Company.tradeability == "NORMAL")
        .order_by(CompanyNodeExposure.strength.desc().nullslast(), Company.ticker.asc())
        .limit(limit)
        .all()
    )
    return rows
