"""Regression coverage for backend/cleanup_orphan_company_refs.py's three
orphan classes -- see the module docstring for the full incident history.
This file focuses on case 3 (added alongside migrate_precision.py's and
reanalyze_cascade.py's MarketMove-orphaning fix): a market_moves row whose
company still exists but whose (alert_id, company_id) pair has no
surviving alert_companies row.
"""
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from cleanup_orphan_company_refs import run_cleanup


def _seed_alert_with_company(db_session, *, ticker: str, url: str) -> tuple[Alert, Company]:
    company = Company(ticker=ticker, name=ticker, sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url=url, title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()
    return alert, company


def test_case3_detects_and_deletes_a_market_move_with_no_surviving_alert_company(db_session):
    alert, company = _seed_alert_with_company(db_session, ticker="A.NS", url="https://example.com/case3-orphan")
    # No AlertCompany row for this alert/company at all -- the exact shape
    # left behind by migrate_precision.py / reanalyze_cascade.py before
    # their MarketMove fixes.
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-1.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    counts = run_cleanup(db_session, dry_run=False)

    assert counts["case3_orphan_market_moves"] == 1
    assert db_session.query(MarketMove).filter_by(alert_id=alert.id, company_id=company.id).count() == 0


def test_case3_leaves_a_market_move_alone_when_its_alert_company_still_exists(db_session):
    alert, company = _seed_alert_with_company(db_session, ticker="B.NS", url="https://example.com/case3-fine")
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    counts = run_cleanup(db_session, dry_run=False)

    assert counts["case3_orphan_market_moves"] == 0
    assert db_session.query(MarketMove).filter_by(alert_id=alert.id, company_id=company.id).count() == 1


def test_case3_does_not_double_count_a_case1_orphan(db_session):
    """A MarketMove whose company_id points at a company that no longer
    exists at all belongs to case 1 (orphaned by a deleted company), not
    case 3 -- case 3 is restricted to company_id IN existing companies, so
    the two never overlap or double-count the same row."""
    alert, company = _seed_alert_with_company(db_session, ticker="C.NS", url="https://example.com/case3-vs-case1")
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=1.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    # Delete the Company row directly (bypassing app.companies.integrity's
    # own cleanup) to reproduce the case-1 orphan shape without also
    # tripping case 3's own detection.
    db_session.query(Company).filter_by(id=company.id).delete(synchronize_session=False)
    db_session.commit()

    counts = run_cleanup(db_session, dry_run=False)

    assert counts["orphan_market_moves"] == 1
    assert counts["case3_orphan_market_moves"] == 0


def test_case3_dry_run_deletes_nothing(db_session):
    alert, company = _seed_alert_with_company(db_session, ticker="D.NS", url="https://example.com/case3-dry-run")
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-1.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    counts = run_cleanup(db_session, dry_run=True)

    assert counts["case3_orphan_market_moves"] == 1
    assert db_session.query(MarketMove).filter_by(alert_id=alert.id, company_id=company.id).count() == 1


def test_case3_is_idempotent(db_session):
    alert, company = _seed_alert_with_company(db_session, ticker="E.NS", url="https://example.com/case3-idempotent")
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-1.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    run_cleanup(db_session, dry_run=False)
    second_pass_counts = run_cleanup(db_session, dry_run=False)

    assert second_pass_counts["case3_orphan_market_moves"] == 0
