from app.analysis.schemas import SECTORS
from app.companies.global_seed import GLOBAL_COMPANIES, load_global_companies
from app.models import Company


def test_load_global_companies_inserts_all_entries(db_session):
    count = load_global_companies(db_session)

    assert count == len(GLOBAL_COMPANIES)
    rows = db_session.query(Company).filter_by(index_tier="GLOBAL_LARGE_CAP").all()
    assert len(rows) == len(GLOBAL_COMPANIES)


def test_load_global_companies_is_idempotent_upsert(db_session):
    load_global_companies(db_session)
    load_global_companies(db_session)

    rows = db_session.query(Company).filter_by(index_tier="GLOBAL_LARGE_CAP").all()
    assert len(rows) == len(GLOBAL_COMPANIES)  # no duplicates on re-run


def test_every_global_company_sector_is_valid():
    for entry in GLOBAL_COMPANIES:
        assert entry["sector"] in SECTORS, entry


def test_every_global_ticker_is_non_indian():
    # No global seed ticker may end in .NS/.BO, so infer_market classifies
    # them all as GLOBAL.
    for entry in GLOBAL_COMPANIES:
        assert not entry["ticker"].endswith((".NS", ".BO")), entry
