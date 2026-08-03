import shutil
from datetime import date
from pathlib import Path

import ingest_universe
from app.models import Company, CompanyAlias, Listing

FIXTURES = Path(__file__).parent / "fixtures" / "universe" / "2026-08-03"


def test_ingest_from_an_existing_snapshot(tmp_path, db_session):
    destination = tmp_path / "2026-08-03"
    shutil.copytree(FIXTURES, destination)

    result = ingest_universe.run_ingest(
        str(tmp_path), date(2026, 8, 3), db_session, fetch=False,
    )

    # NSE contributes 3 ISINs, BSE contributes 4 of which the INF ETF row is
    # excluded, and RELIANCE is shared -> 5 distinct companies, 6 listings.
    assert result["created"] == 5
    assert db_session.query(Company).count() == 5
    # Reliance is dual-listed: one company, two listings.
    reliance = db_session.query(Company).filter_by(isin="INE002A01018").one()
    assert len(reliance.listings) == 2
    assert db_session.query(Listing).count() == 6
    assert db_session.query(CompanyAlias).count() > 0


def test_ingest_is_idempotent(tmp_path, db_session):
    shutil.copytree(FIXTURES, tmp_path / "2026-08-03")
    ingest_universe.run_ingest(str(tmp_path), date(2026, 8, 3), db_session, fetch=False)
    second = ingest_universe.run_ingest(str(tmp_path), date(2026, 8, 3), db_session, fetch=False)
    assert second["created"] == 0
    assert db_session.query(Company).count() == 5


def test_missing_snapshot_raises_rather_than_ingesting_nothing(tmp_path, db_session):
    try:
        ingest_universe.run_ingest(str(tmp_path), date(2026, 8, 3), db_session, fetch=False)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError for a missing snapshot")
