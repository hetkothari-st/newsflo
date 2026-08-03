"""Stage 2b of the universe ingest: the only module here that touches the
DB. Upserts canonical records by ISIN.

companies.id is NEVER reassigned -- it is FK'd by alert_companies,
user_watchlist_companies, holdings, market_moves, car_outcomes,
calibration_samples and impact_edges. An existing row is matched by ISIN
first, then by ticker (which is how the pre-ISIN 509 companies are adopted
without losing their alert history).
"""
from sqlalchemy.orm import Session

from app.models import Company, Listing

# Always refreshed from the masters -- cheap, fetched daily, always present.
_ALWAYS_FIELDS = ("name", "tradeability")
# Only refreshed when the snapshot actually carries a classification. The
# daily master refresh runs with an empty bse_detail/ dir (the detail pass
# is monthly), so writing these unconditionally would null out every
# company's classification once a day.
_CLASSIFICATION_FIELDS = (
    "sector", "official_sector", "official_industry", "official_igroup",
    "official_isubgroup", "classification_source", "classification_as_of",
)


def _find_existing(session: Session, record: dict) -> Company | None:
    company = session.query(Company).filter_by(isin=record["isin"]).one_or_none()
    if company is not None:
        return company
    return session.query(Company).filter_by(ticker=record["ticker"]).one_or_none()


def _sync_listings(session: Session, company: Company, listings: list[dict]) -> int:
    written = 0
    for entry in listings:
        existing = (
            session.query(Listing)
            .filter_by(company_id=company.id, exchange=entry["exchange"])
            .one_or_none()
        )
        if existing is None:
            existing = Listing(company_id=company.id, exchange=entry["exchange"])
            session.add(existing)
        for field in (
            "symbol", "scrip_code", "series", "group_code", "status",
            "is_sme", "is_primary", "face_value", "listed_on", "source", "as_of",
        ):
            setattr(existing, field, entry[field])
        written += 1
    return written


def upsert_records(session: Session, records: list[dict]) -> dict:
    """Create or update one Company (+ its Listings) per record.

    A record is skipped -- never guessed at -- when it has no ISIN, or when
    its ticker already belongs to a DIFFERENT ISIN. Skipping keeps the
    unique constraint intact and surfaces the conflict to the caller
    instead of silently rewriting an unrelated company.
    """
    created = updated = listings_written = 0
    skipped: list[str] = []

    for record in records:
        if not record.get("isin"):
            skipped.append(record.get("ticker") or "<no-ticker>")
            continue

        company = _find_existing(session, record)
        if company is not None and company.isin and company.isin != record["isin"]:
            skipped.append(record["ticker"])
            continue

        if company is None:
            company = Company(
                ticker=record["ticker"], name=record["name"], sector=record["sector"],
                index_tier="OTHER", market="INDIA", isin=record["isin"],
            )
            session.add(company)
            session.flush()  # assign company.id for the listing rows
            created += 1
        else:
            company.isin = record["isin"]
            company.ticker = record["ticker"]
            updated += 1

        for field in _ALWAYS_FIELDS:
            setattr(company, field, record[field])

        if record["classification_source"]:
            for field in _CLASSIFICATION_FIELDS:
                setattr(company, field, record[field])

        # A missing cap must never blank an exchange-published one (spec
        # §6.2) -- a stale real cap beats a nulled-out tier, same rule as
        # app.companies.market_caps.refresh_market_caps.
        if record["market_cap"] is not None:
            company.market_cap = record["market_cap"]
            company.market_cap_source = record["market_cap_source"]
            company.market_cap_as_of = record["market_cap_as_of"]

        listings_written += _sync_listings(session, company, record["listings"])
        session.commit()

    return {
        "created": created, "updated": updated,
        "listings": listings_written, "skipped": skipped,
    }
