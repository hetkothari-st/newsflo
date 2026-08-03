import backfill_universe
from app.companies.matching import aliases
from app.models import Alert, AlertCompany, Article, Company, CompanyAlias


def _alert(session):
    """Alert.article_id is nullable=False, so an Article must exist first."""
    article = Article(source="test", url="https://example.test/1", title="t", content="c")
    session.add(article)
    session.commit()
    alert = Alert(article_id=article.id, category="test")
    session.add(alert)
    session.commit()
    return alert


def test_broken_tickers_are_corrected_in_place(db_session):
    company = Company(
        ticker="HPCL.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50",
    )
    db_session.add(company)
    db_session.commit()
    original_id = company.id

    changed = backfill_universe.apply_ticker_corrections(db_session)
    assert ("HPCL.NS", "HINDPETRO.NS") in changed
    refreshed = db_session.get(Company, original_id)
    assert refreshed.ticker == "HINDPETRO.NS"
    assert refreshed.id == original_id


def test_correction_preserves_alert_history(db_session):
    company = Company(
        ticker="OILINDIA.NS", name="Oil India Ltd.", sector="oil_gas", index_tier="NIFTY50",
    )
    db_session.add(company)
    db_session.commit()
    alert = _alert(db_session)
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="POSITIVE",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    ))
    db_session.commit()

    backfill_universe.apply_ticker_corrections(db_session)
    assert db_session.query(AlertCompany).one().company_id == company.id
    assert db_session.get(Company, company.id).ticker == "OIL.NS"


def test_correction_is_skipped_when_target_already_exists(db_session):
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.commit()

    changed = backfill_universe.apply_ticker_corrections(db_session)
    assert ("HPCL.NS", "HINDPETRO.NS") not in changed
    assert db_session.query(Company).filter_by(ticker="HPCL.NS").count() == 1


def test_unknown_ticker_is_flagged_suspended_not_deleted(db_session):
    company = Company(
        ticker="JBCHEPHARM.NS", name="JB Chemicals", sector="pharma", index_tier="NIFTYMIDCAP150",
    )
    db_session.add(company)
    db_session.commit()

    flagged = backfill_universe.flag_missing_tickers(db_session, known_symbols={"RELIANCE"})
    assert flagged == ["JBCHEPHARM.NS"]
    refreshed = db_session.get(Company, company.id)
    assert refreshed is not None
    assert refreshed.tradeability == "SUSPENDED"


def test_merge_moves_alert_history_and_deletes_the_phantom(db_session):
    canonical = Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
    )
    phantom = Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas",
        index_tier="OTHER",
    )
    db_session.add_all([canonical, phantom])
    db_session.commit()
    canonical_id, phantom_id = canonical.id, phantom.id

    alert = _alert(db_session)
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=phantom_id, direction="POSITIVE",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )

    assert db_session.get(Company, phantom_id) is None
    assert db_session.get(Company, canonical_id) is not None
    assert db_session.query(AlertCompany).one().company_id == canonical_id
    assert report[0]["moved"]["alert_companies.company_id"] == 1


def test_merge_refuses_when_the_phantom_has_an_isin(db_session):
    # The safety rule: never delete a company that carries an ISIN.
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
    ))
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas",
        index_tier="OTHER", isin="INE999Z01099",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )
    assert "skipped" in report[0]
    assert db_session.query(Company).filter_by(ticker="HPCL.NS").count() == 1


def test_merge_refuses_when_the_canonical_has_no_isin(db_session):
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="OTHER",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )
    assert "skipped" in report[0]
    assert db_session.query(Company).count() == 2


def test_merge_deletes_derivable_rows_rather_than_reassigning_them(db_session):
    canonical = Company(
        ticker="OIL.NS", name="Oil India Ltd.", sector="oil_gas",
        index_tier="NIFTY50", isin="INE274J01014",
    )
    phantom = Company(
        ticker="OILINDIA.NS", name="Oil India", sector="oil_gas", index_tier="OTHER",
    )
    db_session.add_all([canonical, phantom])
    db_session.commit()
    # Both companies normalize to aliases that would collide on reassignment.
    aliases.rebuild_aliases(db_session)
    assert db_session.query(CompanyAlias).filter_by(company_id=phantom.id).count() > 0

    backfill_universe.merge_duplicate_companies(db_session, [("OILINDIA.NS", "OIL.NS")])

    assert db_session.query(CompanyAlias).filter_by(company_id=phantom.id).count() == 0
    assert db_session.query(CompanyAlias).filter_by(company_id=canonical.id).count() > 0


def test_global_companies_are_never_flagged(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market="GLOBAL",
    ))
    db_session.commit()
    assert backfill_universe.flag_missing_tickers(db_session, known_symbols=set()) == []
