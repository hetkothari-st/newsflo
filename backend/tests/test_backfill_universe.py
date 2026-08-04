import hashlib
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SASession

import backfill_universe
from app.companies.matching import aliases
from app.db import Base
from app.models import (
    Alert,
    AlertCompany,
    Article,
    CalibrationSample,
    CarOutcome,
    Company,
    CompanyAlias,
    CompanyIndexMembership,
    Holding,
    ImpactEdge,
    Listing,
    MarketMove,
    User,
    UserWatchlistCompany,
)

FIXTURES = Path(__file__).parent / "fixtures" / "universe" / "2026-08-03"


def _alert(session, url="https://example.test/1"):
    """Alert.article_id is nullable=False, so an Article must exist first.
    Article.url is unique, so a test needing more than one alert passes a
    distinct url per call."""
    article = Article(source="test", url=url, title="t", content="c")
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
    # Force the ORM relationship collection to load, reproducing the
    # reviewer's probe for the StaleDataError fix: if `phantom.aliases` is
    # loaded when the merge's raw-SQL DELETE removes those rows, deleting
    # `phantom` without first expiring the collection makes SQLAlchemy's
    # nullify-on-delete cascade try to UPDATE rows that are already gone,
    # match 0 rows, and raise StaleDataError -> PendingRollbackError.
    assert len(phantom.aliases) > 0

    backfill_universe.merge_duplicate_companies(db_session, [("OILINDIA.NS", "OIL.NS")])

    assert db_session.query(CompanyAlias).filter_by(company_id=phantom.id).count() == 0
    assert db_session.query(CompanyAlias).filter_by(company_id=canonical.id).count() > 0


def test_global_companies_are_never_flagged(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market="GLOBAL",
    ))
    db_session.commit()
    assert backfill_universe.flag_missing_tickers(db_session, known_symbols=set()) == []


def _hindpetro_pair(db_session):
    canonical = Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
    )
    phantom = Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="OTHER",
    )
    db_session.add_all([canonical, phantom])
    db_session.commit()
    return canonical, phantom


def test_merge_reports_not_found_for_missing_phantom_or_canonical(db_session):
    db_session.add(Company(
        ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
        sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
    ))
    db_session.add(Company(
        ticker="OILINDIA.NS", name="Oil India", sector="oil_gas", index_tier="OTHER",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS"), ("OILINDIA.NS", "OIL.NS")],
    )
    # Pair 1: the phantom ticker doesn't exist at all.
    assert report[0] == {"phantom": "HPCL.NS", "skipped": "not found"}
    # Pair 2: the phantom exists but the canonical ticker doesn't.
    assert report[1] == {"phantom": "OILINDIA.NS", "skipped": "not found"}
    assert db_session.query(Company).count() == 2


def test_merge_collision_on_market_moves_deletes_duplicate_and_moves_rest(db_session):
    canonical, phantom = _hindpetro_pair(db_session)
    canonical_id, phantom_id = canonical.id, phantom.id

    shared_alert = _alert(db_session, url="https://example.test/shared")
    phantom_only_alert = _alert(db_session, url="https://example.test/phantom-only")

    # Colliding row: the canonical already has a measurement for this alert.
    db_session.add(MarketMove(
        alert_id=shared_alert.id, company_id=canonical_id,
        benchmark_ticker="^NSEI", measurement_status="ok",
    ))
    db_session.add(MarketMove(
        alert_id=shared_alert.id, company_id=phantom_id,
        benchmark_ticker="^NSEI", measurement_status="ok",
    ))
    # Non-colliding row: only the phantom has a measurement for this one.
    db_session.add(MarketMove(
        alert_id=phantom_only_alert.id, company_id=phantom_id,
        benchmark_ticker="^NSEI", measurement_status="ok",
    ))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )

    assert "skipped" not in report[0]
    assert report[0]["moved"]["market_moves.company_id (deleted duplicate)"] == 1
    assert report[0]["moved"]["market_moves.company_id"] == 1
    remaining = {(m.alert_id, m.company_id) for m in db_session.query(MarketMove).all()}
    assert remaining == {
        (shared_alert.id, canonical_id),
        (phantom_only_alert.id, canonical_id),
    }


def test_merge_collision_on_watchlist_deletes_duplicate_and_moves_rest(db_session):
    canonical, phantom = _hindpetro_pair(db_session)
    canonical_id, phantom_id = canonical.id, phantom.id

    shared_user = User(email="shared-watcher@example.test", hashed_password="x")
    phantom_only_user = User(email="phantom-only-watcher@example.test", hashed_password="x")
    db_session.add_all([shared_user, phantom_only_user])
    db_session.commit()

    # Colliding row: this user already watches the canonical company.
    db_session.add(UserWatchlistCompany(user_id=shared_user.id, company_id=canonical_id))
    db_session.add(UserWatchlistCompany(user_id=shared_user.id, company_id=phantom_id))
    # Non-colliding row: only watches the phantom.
    db_session.add(UserWatchlistCompany(user_id=phantom_only_user.id, company_id=phantom_id))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )

    assert "skipped" not in report[0]
    assert report[0]["moved"]["user_watchlist_companies.company_id (deleted duplicate)"] == 1
    assert report[0]["moved"]["user_watchlist_companies.company_id"] == 1
    remaining = {(w.user_id, w.company_id) for w in db_session.query(UserWatchlistCompany).all()}
    assert remaining == {
        (shared_user.id, canonical_id),
        (phantom_only_user.id, canonical_id),
    }


def test_merge_refuses_on_holdings_collision(db_session):
    # Unlike market_moves/user_watchlist_companies, a Holding carries
    # quantity (and implicitly cost basis) -- deleting or summing a
    # colliding pair would silently destroy or fabricate user financial
    # data, so the whole merge must refuse instead, leaving both companies
    # and both holdings exactly as they were.
    canonical, phantom = _hindpetro_pair(db_session)
    canonical_id, phantom_id = canonical.id, phantom.id

    user = User(email="holder@example.test", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    db_session.add(Holding(user_id=user.id, company_id=canonical_id, quantity=5))
    db_session.add(Holding(user_id=user.id, company_id=phantom_id, quantity=7))
    db_session.commit()

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )

    assert report[0]["skipped"] == "holdings collision -- needs manual reconciliation"
    assert db_session.get(Company, phantom_id) is not None
    assert db_session.get(Company, canonical_id) is not None
    holdings_by_company = {
        h.company_id: h.quantity
        for h in db_session.query(Holding).filter_by(user_id=user.id).all()
    }
    assert holdings_by_company == {phantom_id: 7, canonical_id: 5}


def test_merge_leaves_no_orphans_across_all_fk_columns(db_session):
    canonical, phantom = _hindpetro_pair(db_session)
    canonical_id, phantom_id = canonical.id, phantom.id
    other = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="energy",
        index_tier="NIFTY50", isin="INE002A01018",
    )
    db_session.add(other)
    db_session.commit()
    other_id = other.id

    alert = _alert(db_session)
    user = User(email="orphan-check@example.test", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    db_session.add(CompanyIndexMembership(company_id=phantom_id, index_code="NIFTY500"))
    db_session.add(Listing(
        company_id=phantom_id, exchange="NSE", symbol="HPCLPHANTOM",
        source="test", as_of=date(2026, 8, 3),
    ))
    db_session.add(CompanyAlias(
        company_id=phantom_id, alias="Phantom Alias", alias_type="TRADE_NAME",
        normalized="phantomalias",
    ))
    db_session.commit()

    ac_direct = AlertCompany(
        alert_id=alert.id, company_id=phantom_id, direction="POSITIVE",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    )
    ac_parent = AlertCompany(
        alert_id=alert.id, company_id=other_id, direction="POSITIVE",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        parent_company_id=phantom_id,
    )
    db_session.add_all([ac_direct, ac_parent])
    db_session.commit()

    db_session.add(ImpactEdge(
        alert_id=alert.id, from_company_id=phantom_id, from_node_kind="company",
        from_label="Phantom", to_company_id=other_id, to_node_kind="company",
        to_label="Other", relation="supplier", direction="bullish", note="n",
        source="llm_only",
    ))
    db_session.add(ImpactEdge(
        alert_id=alert.id, from_company_id=other_id, from_node_kind="company",
        from_label="Other", to_company_id=phantom_id, to_node_kind="company",
        to_label="Phantom", relation="customer", direction="bearish", note="n",
        source="llm_only",
    ))
    db_session.add(CalibrationSample(
        alert_company_id=ac_direct.id, category="test", company_id=phantom_id,
        direction="bullish", magnitude_actual=1.5, horizon_days=1,
    ))
    db_session.add(CarOutcome(
        alert_company_id=ac_direct.id, company_id=phantom_id, category="test",
        day0_excess_move_pct=1.0, car_pct=2.0,
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=phantom_id,
        benchmark_ticker="^NSEI", measurement_status="ok",
    ))
    db_session.add(Holding(user_id=user.id, company_id=phantom_id, quantity=7))
    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=phantom_id))
    db_session.commit()

    # Force both derivable relationship collections to load pre-merge --
    # the exact shape of the reviewer's Important-1 probe.
    assert len(phantom.aliases) > 0
    assert len(phantom.listings) > 0

    report = backfill_universe.merge_duplicate_companies(
        db_session, [("HPCL.NS", "HINDPETRO.NS")],
    )

    assert "skipped" not in report[0]
    assert db_session.get(Company, phantom_id) is None

    # All twelve FK columns onto companies.id, across all ten tables: none
    # may still reference the deleted phantom id.
    assert db_session.query(CompanyIndexMembership).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(Listing).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(CompanyAlias).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(AlertCompany).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(AlertCompany).filter_by(parent_company_id=phantom_id).count() == 0
    assert db_session.query(ImpactEdge).filter_by(from_company_id=phantom_id).count() == 0
    assert db_session.query(ImpactEdge).filter_by(to_company_id=phantom_id).count() == 0
    assert db_session.query(CalibrationSample).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(CarOutcome).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(MarketMove).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(Holding).filter_by(company_id=phantom_id).count() == 0
    assert db_session.query(UserWatchlistCompany).filter_by(company_id=phantom_id).count() == 0


def test_curated_global_companies_are_marked(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP",
    ))
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()

    marked = backfill_universe.mark_global_companies(db_session)
    assert marked == 1
    assert db_session.query(Company).filter_by(ticker="AAPL").one().market == "GLOBAL"
    assert db_session.query(Company).filter_by(ticker="RELIANCE.NS").one().market == "INDIA"


def test_isin_invariant_reports_indian_companies_without_isin(db_session):
    db_session.add(Company(
        ticker="NOISIN.NS", name="No Isin Ltd", sector="other", index_tier="OTHER",
    ))
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market="GLOBAL",
    ))
    db_session.commit()

    assert backfill_universe.validate_isin_invariant(db_session) == ["NOISIN.NS"]


def test_isin_invariant_passes_on_a_clean_universe(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", isin="INE002A01018",
    ))
    db_session.commit()
    assert backfill_universe.validate_isin_invariant(db_session) == []


def _file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_dry_run_leaves_the_database_byte_identical(tmp_path):
    """--dry-run must run the real pipeline (apply_ticker_corrections,
    mark_global_companies, merge_duplicate_companies -- including the
    irreversible phantom-company delete, upsert_records, flag_missing_
    tickers, rebuild_aliases) far enough to report a real, non-empty
    result, and STILL leave the on-disk database exactly as it started.
    Uses a real file-backed SQLite DB (not the in-memory db_session
    fixture) so the file's bytes can be hashed before and after -- proof
    that goes beyond "the row counts look right" to "literally nothing was
    written or fsynced".
    """
    db_path = tmp_path / "dry_run_target.db"
    seed_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(seed_engine)

    with SASession(seed_engine) as session:
        # The exact HPCL.NS/HINDPETRO.NS phantom-duplicate scenario backfill
        # is built to resolve, plus alert history riding on the phantom --
        # if the merge (which deletes a company row) leaked past the
        # rollback, this history and row count would visibly change.
        canonical = Company(
            ticker="HINDPETRO.NS", name="Hindustan Petroleum Corporation Ltd.",
            sector="oil_gas", index_tier="NIFTY50", isin="INE094A01015",
        )
        phantom = Company(
            ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="OTHER",
        )
        session.add_all([canonical, phantom])
        session.commit()
        article = Article(source="test", url="https://example.test/dry-run", title="t", content="c")
        session.add(article)
        session.commit()
        alert = Alert(article_id=article.id, category="test")
        session.add(alert)
        session.commit()
        session.add(AlertCompany(
            alert_id=alert.id, company_id=phantom.id, direction="POSITIVE",
            magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        ))
        session.commit()
    seed_engine.dispose()

    before_hash = _file_sha256(db_path)
    before_mtime_size = db_path.stat().st_size

    run_engine = create_engine(f"sqlite:///{db_path}")
    try:
        result = backfill_universe.run(
            root=str(FIXTURES.parent), day=date(2026, 8, 3), dry_run=True, engine=run_engine,
        )
    finally:
        run_engine.dispose()

    # Sanity: the dry run actually exercised the merge path (proving this
    # assertion isn't vacuously true because nothing happened to roll back).
    assert result["merges"]
    assert "skipped" not in result["merges"][0]
    assert result["merges"][0]["phantom"] == "HPCL.NS"
    assert result["merges"][0]["moved"]["alert_companies.company_id"] == 1

    after_hash = _file_sha256(db_path)
    assert db_path.stat().st_size == before_mtime_size
    assert after_hash == before_hash

    # And a fresh read confirms the phantom row (and its alert history)
    # are still exactly where they started -- the merge's delete never
    # actually landed.
    with SASession(create_engine(f"sqlite:///{db_path}")) as verify:
        assert verify.query(Company).filter_by(ticker="HPCL.NS").count() == 1
        assert verify.query(Company).filter_by(ticker="HINDPETRO.NS").count() == 1
        assert verify.query(AlertCompany).count() == 1
