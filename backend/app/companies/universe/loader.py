"""Stage 2b of the universe ingest: the only module here that touches the
DB. Upserts canonical records by ISIN.

companies.id is NEVER reassigned -- it is FK'd by alert_companies,
user_watchlist_companies, holdings, market_moves, car_outcomes,
calibration_samples and impact_edges. An existing row is matched by ISIN
first, then by ticker (which is how the pre-ISIN 509 companies are adopted
without losing their alert history).
"""
from sqlalchemy.exc import SQLAlchemyError
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


def _sync_listings(
    session: Session, company: Company, listings: list[dict]
) -> tuple[int, list[str]]:
    """Upsert this company's listings, keyed on (company_id, exchange).

    A listing whose (exchange, symbol) is already owned by a DIFFERENT
    company (a reused/renamed symbol) violates uq_listing_exchange_symbol.
    That single listing is skipped and reported -- degrade, never raise --
    the rest of the record (the company row, its other listings) still
    loads.
    """
    written = 0
    skipped: list[str] = []
    for entry in listings:
        conflict = (
            session.query(Listing)
            .filter_by(exchange=entry["exchange"], symbol=entry["symbol"])
            .filter(Listing.company_id != company.id)
            .one_or_none()
        )
        if conflict is not None:
            skipped.append(f"{entry['exchange']}:{entry['symbol']}")
            continue

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
    return written, skipped


def upsert_records(session: Session, records: list[dict]) -> dict:
    """Create or update one Company (+ its Listings) per record.

    A record is skipped -- never guessed at -- when it has no ISIN, when its
    ticker already belongs to a company with a DIFFERENT ISIN, or when its
    ticker already belongs to a DIFFERENT company entirely (a symbol rename
    or reuse). Skipping keeps the unique constraints intact and surfaces the
    conflict to the caller instead of silently rewriting an unrelated
    company.

    Degrade, never raise: each record is processed in its own try/except.
    A failure on one record rolls back only that record (via
    session.rollback()) and is added to ``skipped`` -- it never aborts the
    rest of the batch, and the function always returns its report rather
    than propagating.
    """
    created = updated = listings_written = 0
    skipped: list[str] = []

    for record in records:
        ticker = record.get("ticker") or "<no-ticker>"

        if not record.get("isin"):
            skipped.append(ticker)
            continue

        # Track this record's would-be effects locally and only fold them
        # into the running totals after a successful commit -- if anything
        # below raises and we roll back, the counters must not reflect work
        # that the database no longer has.
        is_new = False
        record_listings_written = 0
        record_listings_skipped: list[str] = []

        try:
            company = _find_existing(session, record)
            if company is not None and company.isin and company.isin != record["isin"]:
                skipped.append(ticker)
                continue

            # Reverse collision: matched by ISIN, but the incoming ticker
            # already belongs to a DIFFERENT company (a symbol rename/reuse).
            # Force-writing it here would raise the companies.ticker unique
            # constraint -- skip and report instead.
            if company is not None:
                ticker_owner = (
                    session.query(Company).filter_by(ticker=record["ticker"]).one_or_none()
                )
                if ticker_owner is not None and ticker_owner.id != company.id:
                    skipped.append(ticker)
                    continue

            if company is None:
                company = Company(
                    ticker=record["ticker"], name=record["name"], sector=record["sector"],
                    index_tier="OTHER", market="INDIA", isin=record["isin"],
                )
                session.add(company)
                session.flush()  # assign company.id for the listing rows
                is_new = True
            else:
                company.isin = record["isin"]
                company.ticker = record["ticker"]

            for field in _ALWAYS_FIELDS:
                setattr(company, field, record[field])

            if record["classification_source"]:
                for field in _CLASSIFICATION_FIELDS:
                    setattr(company, field, record[field])

            # Spec 6.1: overwrite where we derived something, leave the legacy LLM
            # value alone where we did not. Folding this into
            # _CLASSIFICATION_FIELDS would null out 824 existing values the moment
            # their ISubGroup is unmapped.
            if record["sub_sector"] is not None:
                company.sub_sector = record["sub_sector"]

            # A missing cap must never blank an exchange-published one (spec
            # §6.2) -- a stale real cap beats a nulled-out tier, same rule as
            # app.companies.market_caps.refresh_market_caps.
            if record["market_cap"] is not None:
                company.market_cap = record["market_cap"]
                company.market_cap_source = record["market_cap_source"]
                company.market_cap_as_of = record["market_cap_as_of"]

            record_listings_written, record_listings_skipped = _sync_listings(
                session, company, record["listings"]
            )

            session.commit()
        except SQLAlchemyError:
            session.rollback()
            skipped.append(ticker)
            continue

        if is_new:
            created += 1
        else:
            updated += 1
        listings_written += record_listings_written
        skipped.extend(record_listings_skipped)

    return {
        "created": created, "updated": updated,
        "listings": listings_written, "skipped": skipped,
    }


def apply_amfi_categorisation(session: Session, rows: list[dict], as_of) -> int:
    """Write AMFI's published tier onto companies matched by ISIN.

    Never creates a company: AMFI's list is a categorisation of the
    universe, not a source for it. An ISIN we don't hold is skipped.
    """
    updated = 0
    for row in rows:
        company = session.query(Company).filter_by(isin=row["isin"]).one_or_none()
        if company is None:
            continue
        company.amfi_tier = row["amfi_tier"]
        company.amfi_rank = row["amfi_rank"]
        company.amfi_as_of = as_of
        updated += 1
    session.commit()
    return updated
