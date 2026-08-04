import json
from datetime import date
from pathlib import Path

import pytest

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
    # Fixture Mktcap is "1750000.00" (Rs crore, BSE's published unit) ->
    # normalized to absolute rupees (x 1e7) to match yfinance's unit.
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["market_cap"] == 1750000.0 * 1e7
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


def test_numeric_scrip_cd_and_mktcap_still_produce_cap_and_classification():
    """BSE's JSON does not guarantee SCRIP_CD/Mktcap come back as strings.
    Built inline (not in the fixture files) to isolate this from the fixed
    dataset the other assertions rely on."""
    bse_json = json.dumps([{
        "SCRIP_CD": 590002, "Scrip_Name": "Numeric Co Ltd", "Status": "Active",
        "GROUP": "A", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE555Z01015",
        "INDUSTRY": None, "scrip_id": "NUMCO", "Segment": "Equity",
        "Issuer_Name": "Numeric Co Limited", "Mktcap": 999.5,
    }])
    detail_json = json.dumps({
        "SecurityId": "NUMCO", "SecurityCode": "590002", "ISIN": "INE555Z01015",
        "Industry": "Some Industry", "Group": "A", "Sector": "Information Technology",
        "IndustryNew": "IT - Software", "IGroup": "IT Services", "ISubGroup": "IT Consulting",
    })
    bse_rows = normalize.parse_bse_rows(bse_json)
    details = {"590002": normalize.parse_bse_detail(detail_json)}
    record = normalize.build_records([], bse_rows, details, AS_OF)[0]

    assert record["market_cap"] == 999.5 * 1e7
    assert record["market_cap_source"] == "BSE"
    assert record["market_cap_as_of"] == AS_OF
    assert record["official_sector"] == "Information Technology"
    assert record["classification_source"] == "BSE"
    assert record["sector"] == "it"


def test_comma_grouped_market_cap_string_parses_correctly():
    bse_json = json.dumps([{
        "SCRIP_CD": "590003", "Scrip_Name": "Comma Cap Ltd", "Status": "Active",
        "GROUP": "A", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE555Z01016",
        "INDUSTRY": None, "scrip_id": "COMMACO", "Segment": "Equity",
        "Issuer_Name": "Comma Cap Limited", "Mktcap": "1,32,904.62",
    }])
    bse_rows = normalize.parse_bse_rows(bse_json)
    record = normalize.build_records([], bse_rows, {}, AS_OF)[0]

    assert record["market_cap"] == 132904.62 * 1e7
    assert record["market_cap_source"] == "BSE"


def test_bse_crore_market_cap_is_normalized_to_absolute_rupees():
    # RELIANCE's real live BSE Mktcap on 2026-08-03: "1771409.32" (Rs
    # crore). Must land in Company.market_cap as absolute rupees, the same
    # unit yfinance's fast_info["marketCap"] already uses for the 42 caps
    # already in production.
    bse_json = json.dumps([{
        "SCRIP_CD": "500325", "Scrip_Name": "Reliance Industries Ltd", "Status": "Active",
        "GROUP": "A", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE002A01018",
        "INDUSTRY": None, "scrip_id": "RELIANCE", "Segment": "Equity",
        "Issuer_Name": "Reliance Industries Limited", "Mktcap": "1771409.32",
    }])
    bse_rows = normalize.parse_bse_rows(bse_json)
    record = normalize.build_records([], bse_rows, {}, AS_OF)[0]

    assert record["market_cap"] == pytest.approx(1.771409_32e13)


def test_infinite_market_cap_is_rejected_not_ranked_first():
    bse_json = json.dumps([{
        "SCRIP_CD": "590004", "Scrip_Name": "Infinite Cap Ltd", "Status": "Active",
        "GROUP": "A", "FACE_VALUE": "10.00", "ISIN_NUMBER": "INE555Z01017",
        "INDUSTRY": None, "scrip_id": "INFCO", "Segment": "Equity",
        "Issuer_Name": "Infinite Cap Limited", "Mktcap": "inf",
    }])
    bse_rows = normalize.parse_bse_rows(bse_json)
    record = normalize.build_records([], bse_rows, {}, AS_OF)[0]

    assert record["market_cap"] is None
    assert record["market_cap_source"] is None


def test_mixed_bse_and_yfinance_unit_population_ranks_correctly():
    """A regression for the unit-mixing bug: 403 BSE-crore-sourced large/mid
    caps plus one yfinance-absolute-rupee microcap (~Rs 300 crore) must rank
    the microcap outside LARGE. Before the fix, the un-normalized BSE pool
    (raw crore numbers, e.g. ~50,000) was numerically smaller than the raw
    yfinance absolute number (~3,000,000,000), so the microcap (never
    actually the biggest company) came out ranked #1 -- LARGE.
    """
    from app.market import cap_tier

    bse_rows_json = [
        {
            "SCRIP_CD": str(600000 + i), "Scrip_Name": f"BSE Co {i}", "Status": "Active",
            "GROUP": "A", "FACE_VALUE": "10.00", "ISIN_NUMBER": f"INE{i:06d}Z01011",
            "INDUSTRY": None, "scrip_id": f"BSECO{i}", "Segment": "Equity",
            "Issuer_Name": f"BSE Co {i} Limited",
            "Mktcap": str(50000 - i),  # crore; 403 companies, descending
        }
        for i in range(403)
    ]
    bse_rows = normalize.parse_bse_rows(json.dumps(bse_rows_json))
    bse_records = normalize.build_records([], bse_rows, {}, AS_OF)

    # yfinance-sourced microcap: ~Rs 300 crore in ABSOLUTE rupees already
    # (this is what app.companies.market_caps.refresh_market_caps writes
    # directly to Company.market_cap -- normalize.py is never involved for
    # this half of the population, hence the raw absolute-rupee number here).
    microcap_cap = 300 * 1e7  # ~Rs 300 crore, absolute rupees

    pool = [(r["ticker"], r["market_cap"]) for r in bse_records]
    pool.append(("MICROCAP.NS", microcap_cap))

    tiers = cap_tier.compute_cap_tiers(pool)
    assert tiers["MICROCAP.NS"] != "LARGE"
    # The genuine largest BSE company (rank 1 by crore value) must still be
    # LARGE. BSE-only listings get a ".BO" ticker (no NSE row was fed in).
    assert tiers["BSECO0.BO"] == "LARGE"


def test_sub_sector_is_derived_from_isubgroup():
    record = next(r for r in _load() if r["isin"] == "INE002A01018")
    assert record["sub_sector"] == "refining_marketing"


def test_sub_sector_is_none_without_a_detail_payload():
    record = next(r for r in _load() if r["isin"] == "INE999Z01011")
    assert record["sub_sector"] is None
