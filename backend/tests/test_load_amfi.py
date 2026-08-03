from datetime import date

import load_amfi
from app.models import Company

AS_OF = date(2026, 8, 3)

CSV = """Sr. No.,Company name,ISIN,BSE Symbol,BSE 6 month Avg Total Market Cap in (Rs. Crs.),NSE Symbol,NSE 6 month Avg Total Market Cap (Rs. Crs.),MSEI Symbol,MSEI 6 month Avg Total Market Cap in (Rs Crs.),Average of All Exchanges (Rs. Cr.),"Categorization as per SEBI Circular dated Oct 6, 2017"
1,Reliance Industries Ltd,INE002A01018,RELIANCE,1873294.72,RELIANCE,1873278.83,-,,1873286.78,Large Cap
2,Some Mid Co Limited,INE111Z01010,MIDCO,45000.00,MIDCO,45000.00,-,,45000.00,Mid Cap
"""


def test_run_load_parses_and_applies_in_one_call(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()

    result = load_amfi.run_load(CSV, db_session, AS_OF)

    assert result == {"parsed": 2, "updated": 1}
    company = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert company.amfi_tier == "LARGE"
    assert company.amfi_rank == 1
    assert company.amfi_as_of == AS_OF


def test_run_load_with_no_matching_isins_updates_nothing(db_session):
    result = load_amfi.run_load(CSV, db_session, AS_OF)
    assert result == {"parsed": 2, "updated": 0}
    assert db_session.query(Company).count() == 0
