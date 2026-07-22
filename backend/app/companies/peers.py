"""Same-sector peer lookup for the stock deep-dive's discovery doorway
(docs/NEWS_IMPACT_APP_SPEC.md §2 Level 4, §3.1 Stock.peers). Pure derived
data -- deliberately NOT stored as a Company column, unlike the spec's
literal data model (see this plan's Global Constraints for the
rationale). Peers are 100% derivable from Company.sector at read time;
storing them as a denormalized array would go stale the moment a
company's sector changes or a new peer is seeded, with no independent
value over recomputing it fresh -- same "derived, never persisted as
truth" discipline this architecture already applies to intensity/cap_tier
(see app/market/intensity.py, app/market/cap_tier.py).
"""
from sqlalchemy.orm import Session

from app.models import Company

DEFAULT_PEER_LIMIT = 10


def get_sector_peers(session: Session, company: Company, limit: int = DEFAULT_PEER_LIMIT) -> list[Company]:
    """Every other Company sharing ``company.sector``, ordered by ticker
    for a stable, deterministic result, capped at ``limit``. Excludes
    ``company`` itself. Queried fresh every call."""
    return (
        session.query(Company)
        .filter(Company.sector == company.sector, Company.id != company.id)
        .order_by(Company.ticker.asc())
        .limit(limit)
        .all()
    )
