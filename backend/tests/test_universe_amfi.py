from datetime import date

from app.companies.universe import loader, normalize
from app.models import Company

AS_OF = date(2026, 8, 3)

# Header reflects the REAL AMFI workbook column names, confirmed live on
# 2026-08-03 (https://portal.amfiindia.com/spages/AverageMarketCapitalization30Jun2026.xlsx),
# not the documented "Company Name" / "Average Market Cap" / "Categorization"
# shape the original spec assumed.
CSV = """Sr. No.,Company name,ISIN,Average of All Exchanges (Rs. Cr.),"Categorization as per SEBI Circular dated Oct 6, 2017"
1,Reliance Industries Limited,INE002A01018,1750000.00,Large Cap
2,Some Mid Co Limited,INE111Z01010,45000.00,Mid Cap
3,Some Small Co Limited,INE222Z01011,900.00,Small Cap
"""


def test_parse_amfi_rows_normalizes_the_tier_vocabulary():
    rows = normalize.parse_amfi_rows(CSV)
    assert [r["amfi_tier"] for r in rows] == ["LARGE", "MID", "SMALL"]
    assert rows[0]["isin"] == "INE002A01018"
    assert rows[0]["amfi_rank"] == 1


def test_apply_amfi_sets_tier_rank_and_as_of(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()

    updated = loader.apply_amfi_categorisation(db_session, normalize.parse_amfi_rows(CSV), AS_OF)
    assert updated == 1
    company = db_session.query(Company).one()
    assert company.amfi_tier == "LARGE"
    assert company.amfi_rank == 1
    assert company.amfi_as_of == AS_OF


def test_unknown_isin_is_ignored_not_created(db_session):
    updated = loader.apply_amfi_categorisation(db_session, normalize.parse_amfi_rows(CSV), AS_OF)
    assert updated == 0
    assert db_session.query(Company).count() == 0
