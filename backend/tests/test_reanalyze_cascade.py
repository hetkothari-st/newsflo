"""Regression coverage for backend/reanalyze_cascade.py's grounding.

Task 8 made grounding (candidate list + ticker enum) inside analyze_article
conditional on a `session` argument, and this script was deliberately left
alone at the time. As originally written it called
`analyze_article(client, title, content)` with no session -- reanalyzing
completely UNGROUNDED, reproducing the exact pre-fix hallucination behavior
this whole precision effort exists to remove. A test that only checks the
script runs without erroring would not catch that regression (it ran fine
either way) -- this asserts the actual session object reaches
analyze_article's call site.
"""
import subprocess
import sys
from pathlib import Path

import reanalyze_cascade
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import (
    Alert,
    AlertCompany,
    AlertCompanyTranslation,
    Article,
    CalibrationSample,
    CarOutcome,
    Company,
    EmailNotification,
    MarketMove,
    User,
    utcnow,
)
from app.pipeline import store_analysis_cache


def test_main_passes_a_real_session_to_analyze_article(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/reanalyze-cascade", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    captured = {}

    def fake_analyze_article(client, title, content, session=None):
        captured["session"] = session
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    # Route the script's module-level singletons at the test's in-memory
    # session/engine instead of a real SessionLocal()/build_client() --
    # main() is not written to accept a session, so it's monkeypatched at
    # the names reanalyze_cascade imported them under.
    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert "session" in captured, "analyze_article was never called"
    assert captured["session"] is not None
    assert captured["session"] is db_session


def test_main_builds_anchor_sub_sectors_before_resolving(db_session, monkeypatch):
    # Guards against a second, hand-rolled copy of the anchor_sub_sectors
    # loop drifting from app.pipeline.build_anchor_sub_sectors -- the exact
    # failure mode called out in the task brief. Asserts the script actually
    # calls the shared helper rather than reimplementing the loop.
    article = Article(source="test", url="https://example.com/reanalyze-cascade-2", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    calls = []
    real_helper = reanalyze_cascade.build_anchor_sub_sectors

    def spy_helper(session, companies):
        calls.append((session, companies))
        return real_helper(session, companies)

    def fake_analyze_article(client, title, content, session=None):
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)
    monkeypatch.setattr(reanalyze_cascade, "build_anchor_sub_sectors", spy_helper)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert len(calls) == 1
    assert calls[0][0] is db_session


def test_deletes_every_dependent_row_before_replacing_alert_companies(db_session, monkeypatch):
    """Regression test for the 4th delete-parent-without-dependents bug in
    this codebase: an earlier version of this script's cleanup cleared only
    AlertCompanyTranslation before deleting an alert's AlertCompany rows,
    leaving CalibrationSample/CarOutcome/EmailNotification rows pointing at
    a company_id (alert_company_id) that no longer exists -- invisible on
    SQLite (FK enforcement off by default), a ForeignKeyViolation on
    Postgres. This test seeds one row in each of the four
    ALERT_COMPANY_DEPENDENTS tables against a single AlertCompany, runs the
    real reanalyze flow, and asserts none of them survive as orphans.
    """
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50")
    user = User(email="u@example.com", hashed_password="x")
    db_session.add_all([company, user])
    db_session.commit()

    article = Article(source="test", url="https://example.com/dependents", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    )
    db_session.add(ac)
    db_session.commit()
    old_ac_id = ac.id

    db_session.add(CalibrationSample(
        alert_company_id=old_ac_id, category="test", company_id=company.id,
        direction="bullish", magnitude_actual=1.5, horizon_days=1,
    ))
    db_session.add(CarOutcome(
        alert_company_id=old_ac_id, company_id=company.id, category="test",
        day0_excess_move_pct=1.0, car_pct=1.0,
    ))
    db_session.add(EmailNotification(user_id=user.id, alert_company_id=old_ac_id))
    db_session.add(AlertCompanyTranslation(alert_company_id=old_ac_id, lang="hi", rationale="r"))
    db_session.commit()

    def fake_analyze_article(client, title, content, session=None):
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert db_session.query(AlertCompany).filter_by(id=old_ac_id).count() == 0
    assert db_session.query(CalibrationSample).filter_by(alert_company_id=old_ac_id).count() == 0
    assert db_session.query(CarOutcome).filter_by(alert_company_id=old_ac_id).count() == 0
    assert db_session.query(EmailNotification).filter_by(alert_company_id=old_ac_id).count() == 0
    assert db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=old_ac_id).count() == 0


def test_reanalysis_leaves_no_orphaned_market_move_rows(db_session, monkeypatch):
    """Regression test for the root cause behind the feed-v2 500: this
    script deleted an alert's AlertCompany rows (and their
    ALERT_COMPANY_DEPENDENTS) but never touched MarketMove, which
    references alert_id/company_id directly rather than
    alert_company_id -- so it isn't covered by that dependents list at
    all. Confirmed live: reanalyzing alert 1447 left 53 orphaned
    MarketMove rows, one of which crashed
    app.market.alert_measurement.compute_alert_measurement's bare next()
    with StopIteration. Seeds one AlertCompany + matching MarketMove, runs
    a real reanalysis that resolves to zero companies (the orphan-producing
    shape), and asserts the MarketMove row does not survive as an orphan.
    """
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/orphan-market-move", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    alert_id = alert.id

    def fake_analyze_article(client, title, content, session=None):
        # Fresh analysis finds nothing -- the exact shape that orphaned
        # MarketMove rows for alert 1447 in production.
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert db_session.query(AlertCompany).filter_by(alert_id=alert_id).count() == 0
    assert db_session.query(MarketMove).filter_by(alert_id=alert_id).count() == 0


def _make_alert_with_company(db_session, *, url: str, ticker: str) -> tuple[Alert, Company]:
    company = Company(ticker=ticker, name=ticker, sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url=url, title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    )
    db_session.add(ac)
    db_session.commit()
    return alert, company


def test_alert_id_targets_only_the_given_alert(db_session, monkeypatch):
    """--alert-id must reanalyze exactly the id(s) given and leave every
    other alert's companies untouched -- unlike bulk mode, which walks
    every alert matching limit/--days."""
    alert1, _ = _make_alert_with_company(db_session, url="https://example.com/a1", ticker="AAA.NS")
    alert2, _ = _make_alert_with_company(db_session, url="https://example.com/a2", ticker="BBB.NS")
    alert1_id, alert2_id = alert1.id, alert2.id
    original_alert2_company_ids = {ac.id for ac in alert2.companies}

    def fake_analyze_article(client, title, content, session=None):
        # Fresh analysis finds nothing -- so a touched alert ends up with
        # zero companies, making "was this alert touched at all" easy to
        # assert on.
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    reanalyze_cascade.main(None, None, False, alert_ids=[alert1_id])

    assert db_session.query(AlertCompany).filter_by(alert_id=alert1_id).count() == 0
    remaining_alert2_ids = {ac.id for ac in db_session.query(AlertCompany).filter_by(alert_id=alert2_id).all()}
    assert remaining_alert2_ids == original_alert2_company_ids


def test_alert_id_mutually_exclusive_with_limit_and_days():
    """Combining --alert-id with the positional limit or --days must be a
    clear argparse error, not a silent pick-one -- run the script as a real
    subprocess so argparse's own exit/stderr path is exercised end to end."""
    script = Path(__file__).resolve().parent.parent / "reanalyze_cascade.py"

    result_with_days = subprocess.run(
        [sys.executable, str(script), "--alert-id", "1", "--days", "5"],
        capture_output=True, text=True, cwd=script.parent,
    )
    assert result_with_days.returncode != 0
    assert "--alert-id" in result_with_days.stderr

    result_with_limit = subprocess.run(
        [sys.executable, str(script), "--alert-id", "1", "10"],
        capture_output=True, text=True, cwd=script.parent,
    )
    assert result_with_limit.returncode != 0
    assert "--alert-id" in result_with_limit.stderr


def test_alert_id_nonexistent_is_reported_and_skipped_not_crashed(db_session, monkeypatch, capsys):
    """A typo'd or already-deleted id must be reported clearly and the run
    must continue with any remaining valid ids, not raise."""
    alert, _ = _make_alert_with_company(db_session, url="https://example.com/exists", ticker="CCC.NS")
    alert_id = alert.id
    missing_id = alert_id + 999999

    def fake_analyze_article(client, title, content, session=None):
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    # Missing id first, then a real one -- proves the loop doesn't abort on
    # the bad id and still processes what follows it.
    reanalyze_cascade.main(None, None, False, alert_ids=[missing_id, alert_id])

    captured = capsys.readouterr()
    assert str(missing_id) in captured.out
    assert "not found" in captured.out
    # The real alert after it was still processed (its companies replaced,
    # in this case with the fresh empty result).
    assert db_session.query(AlertCompany).filter_by(alert_id=alert_id).count() == 0


def test_alert_id_always_clears_the_cache(db_session, monkeypatch, capsys):
    """get_cached_analysis is keyed on a content hash -- without clearing it
    first, --alert-id would replay whatever a prior (possibly pre-fix) run
    cached for this exact article and silently change nothing, defeating
    the entire point of targeting the alert. Asserts analyze_article is
    actually called (i.e. the cache was busted) even though main() is
    called with force=False -- --alert-id must clear regardless of --force.
    """
    alert, _ = _make_alert_with_company(db_session, url="https://example.com/cached", ticker="DDD.NS")
    article = alert.article

    # Seed a stale cached analysis under this article's real content hash.
    store_analysis_cache(db_session, article, AnalysisOutput(category="stale", companies=[], edges=[], gaps=[]))
    db_session.commit()

    calls = []

    def fake_analyze_article(client, title, content, session=None):
        calls.append(1)
        return AnalysisOutput(category="fresh", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", fake_analyze_article)

    reanalyze_cascade.main(None, None, False, alert_ids=[alert.id])

    assert calls == [1], "analyze_article was not called -- the stale cache was not cleared"
    captured = capsys.readouterr()
    assert "using cached analysis" not in captured.out


def _fake_analysis_with_company(ticker: str, direction: str = "bullish") -> AnalysisOutput:
    return AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name=ticker, ticker=ticker, is_direct=True, sector=None,
            direction=direction, magnitude_low=2.0, magnitude_high=4.0, rationale="reasoning",
            key_points=["a point"], confidence_score=85, time_horizon="Short-Term",
        )],
    )


def test_reanalysis_creates_market_move_rows_for_resolved_companies(db_session, monkeypatch):
    """The bug this fixes: reanalyze_cascade.py deleted an alert's stale
    MarketMove rows but never recreated them, so compute_alert_measurement
    (app/routers/feed_v2.py) always returned None for a reanalyzed alert and
    it silently vanished from the feed. An alert that starts with ZERO
    MarketMove rows (the orphan-cleanup shape, or an alert from before
    measurement existed) must end up with one per resolved company after
    reanalysis, exactly like a brand-new alert would via _persist_alert.
    """
    alert, company = _make_alert_with_company(db_session, url="https://example.com/remeasure", ticker="EEE.NS")
    alert_id = alert.id
    assert db_session.query(MarketMove).filter_by(alert_id=alert_id).count() == 0

    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: _fake_analysis_with_company("EEE.NS"),
    )
    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())

    reanalyze_cascade.main(limit=5, days=None, force=False)

    companies_after = db_session.query(AlertCompany).filter_by(alert_id=alert_id).all()
    assert len(companies_after) == 1
    moves_after = db_session.query(MarketMove).filter_by(alert_id=alert_id).all()
    assert len(moves_after) == 1
    assert moves_after[0].company_id == company.id
    assert moves_after[0].alert_id == alert_id


def test_reanalysis_reconciles_direction_the_same_way_the_live_pipeline_does(db_session, monkeypatch):
    """_persist_alert overwrites an AlertCompany's LLM-predicted `direction`
    with the REAL measured direction whenever a real (status=="ok")
    measurement disagrees, and clears the now-stale rationale/key_points on
    a flip (app.pipeline.measure_and_reconcile_alert_companies). Reanalysis
    must apply the exact same reconciliation via the shared helper, or a
    reanalyzed alert's direction/rationale can disagree with what a
    freshly-analyzed alert would show for the identical measured move.
    """
    from app.models import utcnow as _utcnow

    alert, company = _make_alert_with_company(db_session, url="https://example.com/reconcile", ticker="FFF.NS")
    alert_id = alert.id

    # LLM calls it bullish; the real measured move is bearish -- must flip.
    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: _fake_analysis_with_company("FFF.NS", direction="bullish"),
    )

    def fake_measure_bearish(session, company_obj):
        return MarketMove(
            company_id=company_obj.id, benchmark_ticker="^CNXENERGY",
            measurement_status="ok", measured_at=_utcnow(),
            raw_move_pct=-3.0, sector_move_pct=0.1, excess_move_pct=-3.1,
        )

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    # measure_and_reconcile_alert_companies (in app.pipeline) is where the
    # real measure_company_move call lives -- patch it there, same as the
    # autouse conftest stub does for the main pipeline.
    monkeypatch.setattr("app.pipeline.measure_company_move", fake_measure_bearish)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    ac = db_session.query(AlertCompany).filter_by(alert_id=alert_id).one()
    assert ac.direction == "bearish"
    assert ac.rationale is None
    assert ac.key_points_json == "[]"

    move = db_session.query(MarketMove).filter_by(alert_id=alert_id).one()
    assert move.measurement_status == "ok"
    assert move.excess_move_pct == -3.1
