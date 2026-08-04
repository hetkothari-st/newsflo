from datetime import date

from app.companies.universe import loader
from app.models import Company, Listing

AS_OF = date(2026, 8, 3)


def _record(isin, ticker, name, **kw):
    record = {
        "isin": isin, "ticker": ticker, "name": name, "sector": "oil_gas",
        "sub_sector": None,
        "official_sector": "Energy", "official_industry": "Oil, Gas & Consumable Fuels",
        "official_igroup": "Petroleum Products", "official_isubgroup": "Refineries & Marketing",
        "classification_source": "BSE", "classification_as_of": AS_OF,
        "market_cap": 1750000.0, "market_cap_source": "BSE", "market_cap_as_of": AS_OF,
        "eps": None, "ceps": None, "pe": None, "pb": None,
        "opm": None, "npm": None, "roe": None,
        "con_eps": None, "con_ceps": None, "con_pe": None,
        "con_pb": None, "con_opm": None, "con_npm": None, "con_roe": None,
        "financials_source": None, "financials_as_of": None,
        "tradeability": "NORMAL",
        "listings": [{
            "exchange": "NSE", "symbol": ticker.split(".")[0], "scrip_code": None,
            "series": "EQ", "group_code": None, "status": "ACTIVE", "is_sme": False,
            "is_primary": True, "face_value": 10.0, "listed_on": None,
            "source": "NSE", "as_of": AS_OF,
        }],
    }
    record.update(kw)
    return record


def test_creates_company_and_listing(db_session):
    result = loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    assert result["created"] == 1
    company = db_session.query(Company).one()
    assert company.isin == "INE002A01018"
    assert company.market == "INDIA"
    assert company.official_isubgroup == "Refineries & Marketing"
    assert db_session.query(Listing).count() == 1


def test_rerun_updates_rather_than_duplicates(db_session):
    record = _record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")
    loader.upsert_records(db_session, [record])
    result = loader.upsert_records(db_session, [record])
    assert result["created"] == 0
    assert result["updated"] == 1
    assert db_session.query(Company).count() == 1
    assert db_session.query(Listing).count() == 1


def test_matches_existing_company_by_isin_and_preserves_id(db_session):
    existing = Company(
        ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    )
    db_session.add(existing)
    db_session.commit()
    original_id = existing.id

    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    company = db_session.query(Company).one()
    assert company.id == original_id
    assert company.index_tier == "NIFTY50"


def test_matches_existing_company_by_ticker_when_isin_missing(db_session):
    existing = Company(
        ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas",
        index_tier="NIFTY50",
    )
    db_session.add(existing)
    db_session.commit()

    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    assert db_session.query(Company).count() == 1
    assert db_session.query(Company).one().isin == "INE002A01018"


def test_absent_classification_writes_null_not_a_guess(db_session):
    record = _record(
        "INE999Z01011", "NSEONLY.NS", "NSE Only Limited",
        sector="other", official_sector=None, official_industry=None,
        official_igroup=None, official_isubgroup=None,
        classification_source=None, classification_as_of=None,
        market_cap=None, market_cap_source=None, market_cap_as_of=None,
    )
    loader.upsert_records(db_session, [record])
    company = db_session.query(Company).one()
    assert company.official_sector is None
    assert company.classification_source is None
    assert company.market_cap is None


def test_never_overwrites_exchange_cap_with_null(db_session):
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        market_cap=None, market_cap_source=None, market_cap_as_of=None,
    )])
    assert db_session.query(Company).one().market_cap == 1750000.0


def test_absent_classification_never_clobbers_a_stored_one(db_session):
    # The daily master refresh runs with an empty bse_detail/ dir. It must
    # not null out classification written by the monthly detail pass.
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        sector="other", official_sector=None, official_industry=None,
        official_igroup=None, official_isubgroup=None,
        classification_source=None, classification_as_of=None,
    )])
    company = db_session.query(Company).one()
    assert company.official_sector == "Energy"
    assert company.sector == "oil_gas"
    assert company.classification_source == "BSE"


def test_second_exchange_listing_is_added_not_duplicated(db_session):
    record = _record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited")
    loader.upsert_records(db_session, [record])
    record["listings"].append({
        "exchange": "BSE", "symbol": "RELIANCE", "scrip_code": "500325",
        "series": None, "group_code": "A", "status": "ACTIVE", "is_sme": False,
        "is_primary": False, "face_value": 10.0, "listed_on": None,
        "source": "BSE", "as_of": AS_OF,
    })
    loader.upsert_records(db_session, [record])
    assert db_session.query(Company).count() == 1
    assert db_session.query(Listing).count() == 2


def test_record_without_isin_is_skipped(db_session):
    result = loader.upsert_records(db_session, [_record("", "BROKEN.NS", "Broken Ltd")])
    assert result["skipped"] == ["BROKEN.NS"]
    assert db_session.query(Company).count() == 0


def test_ticker_collision_with_a_different_isin_is_skipped(db_session):
    db_session.add(Company(
        ticker="CLASH.NS", name="Existing Ltd", sector="other",
        index_tier="OTHER", isin="INE111Z01010",
    ))
    db_session.commit()
    result = loader.upsert_records(db_session, [_record("INE222Z01011", "CLASH.NS", "New Ltd")])
    assert result["skipped"] == ["CLASH.NS"]
    assert db_session.query(Company).count() == 1


# --- Fix round 1: three Important findings from the SPEC review ------------


def test_reverse_ticker_collision_when_matched_by_isin_is_skipped(db_session):
    """[Important 1] The record is matched by ISIN (to `reliance`), but its
    ticker already belongs to a DIFFERENT company (`other`). Force-writing
    company.ticker would raise the companies.ticker unique constraint; it
    must be skipped and reported instead, and neither row corrupted."""
    reliance = Company(
        ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    )
    other = Company(
        ticker="CLASH2.NS", name="Other Ltd", sector="other",
        index_tier="OTHER", isin="INE444Z01013",
    )
    db_session.add_all([reliance, other])
    db_session.commit()
    reliance_id, other_id = reliance.id, other.id

    result = loader.upsert_records(db_session, [_record(
        "INE002A01018", "CLASH2.NS", "Reliance Industries Limited",
    )])

    assert result["skipped"] == ["CLASH2.NS"]
    assert db_session.query(Company).count() == 2
    assert db_session.get(Company, reliance_id).ticker == "RELIANCE.NS"
    assert db_session.get(Company, reliance_id).isin == "INE002A01018"
    assert db_session.get(Company, other_id).ticker == "CLASH2.NS"
    assert db_session.get(Company, other_id).isin == "INE444Z01013"


def test_listing_symbol_collision_with_another_company_is_skipped(db_session):
    """[Important 2] A stale Listing already holds (NSE, RELIANCE) under a
    different company. The incoming record's own listing for that same
    (exchange, symbol) must be skipped and reported, while the rest of the
    record -- the company row itself -- still loads."""
    other = Company(
        ticker="OTHER.NS", name="Other Ltd", sector="other",
        index_tier="OTHER", isin="INE444Z01013",
    )
    db_session.add(other)
    db_session.commit()
    db_session.add(Listing(
        company_id=other.id, exchange="NSE", symbol="RELIANCE", series="EQ",
        status="ACTIVE", is_sme=False, is_primary=True, face_value=10.0,
        source="NSE", as_of=AS_OF,
    ))
    db_session.commit()

    result = loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
    )])

    assert result["created"] == 1
    assert result["skipped"] == ["NSE:RELIANCE"]
    assert db_session.query(Company).count() == 2
    company = db_session.query(Company).filter_by(isin="INE002A01018").one()
    assert company.ticker == "RELIANCE.NS"
    # Only `other`'s original listing exists; the new company got none.
    assert db_session.query(Listing).count() == 1
    assert db_session.query(Listing).filter_by(company_id=company.id).count() == 0


def test_batch_continues_past_a_mid_batch_collision(db_session):
    """[Important 3] A 3-record batch where the middle record collides
    (same shape as Important 1). The batch must run to completion: records
    1 and 3 committed, the middle one in `skipped`, and upsert_records
    returns its report normally instead of raising and leaving the session
    needing a rollback."""
    reliance = Company(
        ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    )
    clash_owner = Company(
        ticker="CLASHX.NS", name="Clash Owner Ltd", sector="other",
        index_tier="OTHER", isin="INE555Z01014",
    )
    db_session.add_all([reliance, clash_owner])
    db_session.commit()

    records = [
        _record("INE111A01011", "FIRST.NS", "First Ltd"),
        _record("INE002A01018", "CLASHX.NS", "Reliance Industries Limited"),
        _record("INE333A01013", "THIRD.NS", "Third Ltd"),
    ]

    result = loader.upsert_records(db_session, records)

    assert result["created"] == 2
    assert result["skipped"] == ["CLASHX.NS"]
    tickers = {c.ticker for c in db_session.query(Company).all()}
    assert tickers == {"RELIANCE.NS", "CLASHX.NS", "FIRST.NS", "THIRD.NS"}
    assert db_session.query(Company).count() == 4


def test_sub_sector_is_written_with_the_classification(db_session):
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited", sub_sector="refining_marketing")])
    assert db_session.query(Company).one().sub_sector == "refining_marketing"


def test_absent_sub_sector_never_clobbers_a_stored_one(db_session):
    loader.upsert_records(db_session, [_record("INE002A01018", "RELIANCE.NS", "Reliance Industries Limited", sub_sector="refining_marketing")])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        sub_sector=None, official_sector=None, classification_source=None,
    )])
    assert db_session.query(Company).one().sub_sector == "refining_marketing"


def test_financial_ratios_are_written_with_financials_source(db_session):
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        eps=28.98, opm=14.24, con_opm=0.0, con_pb=None,
        financials_source="BSE", financials_as_of=AS_OF,
    )])
    company = db_session.query(Company).one()
    assert company.eps == 28.98
    assert company.opm == 14.24
    assert company.con_opm == 0.0
    assert company.con_pb is None
    assert company.financials_source == "BSE"
    assert company.financials_as_of == AS_OF


def test_absent_financials_never_clobbers_stored_ratios(db_session):
    # The daily master refresh runs with an empty bse_detail/ dir. It must
    # not null out ratios written by the monthly detail pass.
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        eps=28.98, opm=14.24, financials_source="BSE", financials_as_of=AS_OF,
    )])
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        eps=None, opm=None, financials_source=None, financials_as_of=None,
    )])
    company = db_session.query(Company).one()
    assert company.eps == 28.98
    assert company.opm == 14.24
    assert company.financials_source == "BSE"


def test_unmapped_sub_sector_leaves_a_legacy_value_intact(db_session):
    # Spec 6.1: an unmapped ISubGroup must not null out one of the 824 legacy
    # LLM values. This differs from the test above -- here the classification
    # IS present and being written, only sub_sector is None. The legacy value
    # here ("gas_distribution") is a genuine member of oil_gas's taxonomy
    # list -- distinct from the "refining_marketing" the default record's
    # ISubGroup would derive -- so it is a legacy value that still coheres
    # with the (unchanged) sector, not one the [Important 2] coherence guard
    # should clear.
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="OTHER", isin="INE002A01018", sub_sector="gas_distribution",
    ))
    db_session.commit()
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited", sub_sector=None,
    )])
    assert db_session.query(Company).one().sub_sector == "gas_distribution"


# --- Fix round 2: final whole-branch review -------------------------------


def test_sub_sector_not_written_without_classification_source(db_session):
    """[Important 1] A BSE payload can carry ISubGroup/IndustryNew but an
    empty Sector -- classification_source is then falsy and NONE of
    _CLASSIFICATION_FIELDS gets written, but sub_sector was still derivable
    from ISubGroup alone. Writing it anyway half-writes the company.

    The existing company's sector is pre-set to "chemicals" (unchanged by
    this call, since classification_source is falsy) and the incoming
    sub_sector ("specialty_chemicals") IS a valid chemicals sub-sector --
    deliberately chosen so the [Important 2] sector/sub_sector coherence
    guard would NOT catch this on its own, isolating this test to the
    classification_source gate specifically. Probe-confirmed shape (sector
    stuck at "other" with a derived sub_sector) is covered too, just less
    precisely, since "other" has no valid sub-sectors at all and would be
    caught by either guard.
    """
    db_session.add(Company(
        ticker="HALFCO.NS", name="Half Co Ltd", sector="chemicals",
        index_tier="OTHER", isin="INE666Z01015",
    ))
    db_session.commit()

    record = _record(
        "INE666Z01015", "HALFCO.NS", "Half Co Ltd",
        sector="chemicals", official_sector=None, official_industry="Chemicals",
        official_igroup=None, official_isubgroup="Specialty Chemicals",
        classification_source=None, classification_as_of=None,
        sub_sector="specialty_chemicals",
    )
    loader.upsert_records(db_session, [record])
    company = db_session.query(Company).one()
    assert company.sub_sector is None
    assert company.sector == "chemicals"
    assert company.official_isubgroup is None


def test_stale_sub_sector_cleared_when_sector_changes(db_session):
    """[Important 2] A company's BSE sector moves and its new ISubGroup is
    one of the unmapped ones (sub_sector=None in the incoming record) --
    the OLD sub_sector, which belongs to the OLD sector, must not survive
    under the new one. Probe-confirmed shape: sector='infra' with a stale
    auto sub_sector still attached. app.companies.integrity.check_sub_sectors
    (master) flags exactly this incoherence."""
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="auto",
        index_tier="OTHER", isin="INE002A01018", sub_sector="auto_component",
    ))
    db_session.commit()
    loader.upsert_records(db_session, [_record(
        "INE002A01018", "RELIANCE.NS", "Reliance Industries Limited",
        sector="infra", sub_sector=None,
    )])
    company = db_session.query(Company).one()
    assert company.sector == "infra"
    assert company.sub_sector is None
