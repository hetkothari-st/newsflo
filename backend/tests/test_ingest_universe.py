import shutil
from datetime import date
from pathlib import Path

import ingest_universe
from app.companies.universe import snapshot
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


def test_ingest_reads_classification_from_an_earlier_detail_day(tmp_path, db_session):
    """The monthly official-classification pass writes into whatever
    snapshot day was latest AT THE TIME IT RAN. The next day's daily master
    refresh creates a brand new dated directory with its own EMPTY
    bse_detail/. Without falling back to the latest day that actually HAS
    details, the classification files fetched a day earlier are never
    consumed by any ingest -- confirmed by this test failing before the
    snapshot.latest_detail_day fix.
    """
    day_a = date(2026, 7, 1)  # where the monthly detail pass actually landed
    day_b = date(2026, 8, 3)  # today's fresh master-only snapshot

    shutil.copytree(FIXTURES, tmp_path / day_a.isoformat())
    # Day B has its own masters but an EMPTY bse_detail/ -- the state
    # _run_universe_master_refresh leaves behind every day.
    (tmp_path / day_b.isoformat() / snapshot.DETAIL_DIRNAME).mkdir(parents=True)
    shutil.copy(FIXTURES / "nse_equity_l.csv", tmp_path / day_b.isoformat() / "nse_equity_l.csv")
    shutil.copy(FIXTURES / "bse_scrips.json", tmp_path / day_b.isoformat() / "bse_scrips.json")

    result = ingest_universe.run_ingest(str(tmp_path), day_b, db_session, fetch=False)
    assert result["created"] == 5

    reliance = db_session.query(Company).filter_by(isin="INE002A01018").one()
    assert reliance.official_sector == "Energy"
    assert reliance.classification_source == "BSE"
    # normalize.build_records stamps classification_as_of with the ingest's
    # own ``day`` (day_b) regardless of which day the detail files were
    # physically fetched on -- that stamping behaviour is unchanged by this
    # fix. What this test guards is that the classification CONTENT (from
    # day_a's detail files) is found and applied at all.
    assert reliance.classification_as_of == day_b
