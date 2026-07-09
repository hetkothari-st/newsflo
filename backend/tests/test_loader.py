import csv

from app.companies.loader import load_companies_from_csv
from app.models import Company


def _write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Symbol", "Company Name", "Industry"])
        writer.writeheader()
        writer.writerows(rows)


def test_load_companies_from_csv_inserts_rows(db_session, tmp_path):
    csv_path = tmp_path / "nifty50.csv"
    _write_csv(csv_path, [
        {"Symbol": "RELIANCE", "Company Name": "Reliance Industries", "Industry": "Petroleum Products"},
        {"Symbol": "HDFCBANK", "Company Name": "HDFC Bank", "Industry": "Banks"},
    ])

    count = load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    assert count == 2
    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert reliance.sector == "oil_gas"
    assert reliance.index_tier == "NIFTY50"


def test_load_companies_from_csv_upserts_on_rerun(db_session, tmp_path):
    csv_path = tmp_path / "nifty50.csv"
    _write_csv(csv_path, [{"Symbol": "RELIANCE", "Company Name": "Reliance Industries", "Industry": "Petroleum Products"}])
    load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    _write_csv(csv_path, [{"Symbol": "RELIANCE", "Company Name": "Reliance Industries Ltd", "Industry": "Petroleum Products"}])
    load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    companies = db_session.query(Company).filter_by(ticker="RELIANCE.NS").all()
    assert len(companies) == 1
    assert companies[0].name == "Reliance Industries Ltd"


def test_load_companies_from_csv_defaults_unknown_industry_to_other(db_session, tmp_path):
    csv_path = tmp_path / "nifty50.csv"
    _write_csv(csv_path, [{"Symbol": "WEIRDCO", "Company Name": "Weird Co", "Industry": "Something Unrecognized"}])

    load_companies_from_csv(db_session, str(csv_path), index_tier="NIFTY50")

    company = db_session.query(Company).filter_by(ticker="WEIRDCO.NS").one()
    assert company.sector == "other"
