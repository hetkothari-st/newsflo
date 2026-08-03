import json
from datetime import date
from pathlib import Path

from app.companies.universe import normalize

FIXTURES = Path(__file__).parent / "fixtures" / "universe" / "2026-08-03"
AS_OF = date(2026, 8, 3)


def _load():
    nse = normalize.parse_nse_rows((FIXTURES / "nse_equity_l.csv").read_text(encoding="utf-8"))
    bse = normalize.parse_bse_rows((FIXTURES / "bse_scrips.json").read_text(encoding="utf-8"))
    details = {
        p.stem: normalize.parse_bse_detail(p.read_text(encoding="utf-8"))
        for p in (FIXTURES / "bse_detail").glob("*.json")
    }
    return normalize.build_records(nse, bse, details, AS_OF)


def test_inclusion_rule_accepts_equity_isins():
    assert normalize.is_company_isin("INE002A01018") is True
    assert normalize.is_company_isin("IN9002A01018") is True


def test_inclusion_rule_rejects_fund_units_and_junk():
    assert normalize.is_company_isin("INF204KB14I5") is False
    assert normalize.is_company_isin("NA") is False
    assert normalize.is_company_isin("") is False
    assert normalize.is_company_isin(None) is False


def test_etf_units_are_excluded_from_records():
    isins = {r["isin"] for r in _load()}
    assert "INF204KB14I5" not in isins


def test_dual_listed_company_appears_exactly_once():
    records = [r for r in _load() if r["isin"] == "INE002A01018"]
    assert len(records) == 1
    assert len(records[0]["listings"]) == 2


def test_dual_listed_primary_ticker_prefers_nse():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["ticker"] == "RELIANCE.NS"
    primary = [l for l in record["listings"] if l["is_primary"]]
    assert len(primary) == 1 and primary[0]["exchange"] == "NSE"


def test_bse_only_company_gets_bo_ticker():
    record = next(r for r in _load() if r["isin"] == "INE777Z01013")
    assert record["ticker"] == "BSEONLY.BO"
    assert record["tradeability"] == "RESTRICTED"


def test_nse_only_company_gets_ns_ticker_and_no_classification():
    record = next(r for r in _load() if r["isin"] == "INE999Z01011")
    assert record["ticker"] == "NSEONLY.NS"
    assert record["official_sector"] is None
    assert record["classification_source"] is None
    assert record["sector"] == "other"


def test_official_classification_is_stored_verbatim():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["official_sector"] == "Energy"
    assert record["official_isubgroup"] == "Refineries & Marketing"
    assert record["classification_source"] == "BSE"
    assert record["classification_as_of"] == AS_OF
    assert record["sector"] == "oil_gas"


def test_market_cap_comes_from_bse_with_provenance():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["market_cap"] == 1750000.0
    assert record["market_cap_source"] == "BSE"
    assert record["market_cap_as_of"] == AS_OF


def test_blank_market_cap_is_null_not_zero():
    record = next(r for r in _load() if r["isin"] == "INE666Z01014")
    assert record["market_cap"] is None
    assert record["market_cap_source"] is None


def test_sme_group_marks_listing_and_company():
    record = next(r for r in _load() if r["isin"] == "INE666Z01014")
    assert record["tradeability"] == "SME"
    assert record["listings"][0]["is_sme"] is True


def test_nse_be_series_is_restricted():
    record = next(r for r in _load() if r["isin"] == "INE888Z01012")
    assert record["tradeability"] == "RESTRICTED"


def test_legal_name_prefers_bse_issuer_name():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["name"] == "Reliance Industries Limited"


def test_listing_carries_source_and_as_of():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    for listing in record["listings"]:
        assert listing["as_of"] == AS_OF
        assert listing["source"] in ("NSE", "BSE")
