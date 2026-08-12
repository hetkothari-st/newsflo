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

    # allow_empty=True: this test's fresh analysis deliberately resolves to
    # zero over a non-empty alert, which is exactly the shape the data-loss
    # guard now refuses by default. The guard has its own coverage below;
    # here the empty result is just the simplest way to force a full
    # delete-everything sweep so the dependents cleanup can be asserted.
    reanalyze_cascade.main(limit=5, days=None, force=False, allow_empty=True)

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

    # allow_empty=True: the orphan-producing shape is precisely "replace a
    # non-empty alert with zero companies", which the data-loss guard now
    # blocks by default -- opted into explicitly so this regression stays
    # covered (an operator who genuinely passes --allow-empty must still not
    # be left with orphaned MarketMove rows).
    reanalyze_cascade.main(limit=5, days=None, force=False, allow_empty=True)

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

    # allow_empty=True so the targeted alert really is emptied -- "was this
    # alert touched at all" is the assertion, and the default guard would
    # make an untouched alert1 ambiguous with an untargeted one.
    reanalyze_cascade.main(None, None, False, alert_ids=[alert1_id], allow_empty=True)

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
    reanalyze_cascade.main(None, None, False, alert_ids=[missing_id, alert_id], allow_empty=True)

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

    def fake_measure_bearish(session, company_obj, **kwargs):
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


# ---------------------------------------------------------------------------
# EMPTY-RESULT GUARD -- the data-loss fix.
#
# analyze_article does NOT raise when a middle stage fails: it truncates and
# returns whatever earlier stages produced, so a stage-3 failure yields a
# well-formed AnalysisOutput with an EMPTY companies list. This script used
# to delete the alert's companies first and write that empty result over
# them. Confirmed live on alert 1447: 3 good companies (and their
# calibration/outcome history) replaced with 0.
# ---------------------------------------------------------------------------


def test_zero_company_result_over_a_non_empty_alert_leaves_the_existing_rows_intact(
    db_session, monkeypatch, capsys,
):
    alert, company = _make_alert_with_company(db_session, url="https://example.com/wipe", ticker="GGG.NS")
    alert_id = alert.id
    original_ids = {ac.id for ac in alert.companies}
    assert original_ids

    def failed_stage_analysis(client, title, content, session=None):
        # Exactly what a truncated stage-3 failure returns: no exception,
        # just an empty companies list.
        return AnalysisOutput(category="test", companies=[], edges=[], gaps=[])

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", failed_stage_analysis)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    surviving = {ac.id for ac in db_session.query(AlertCompany).filter_by(alert_id=alert_id).all()}
    assert surviving == original_ids, "the good companies were replaced with zero"

    out = capsys.readouterr().out
    # Reported distinctly from the normal "reanalyzed, now has N" line.
    assert "SKIPPED" in out
    assert "ZERO companies" in out
    assert "--allow-empty" in out
    assert "company count:" not in out


def test_zero_company_result_also_leaves_dependent_history_intact(db_session, monkeypatch):
    """The guard is worth having precisely because the delete cascades:
    CalibrationSample/CarOutcome history is what makes the wipe
    irreversible. None of it may be touched when the guard fires."""
    alert, company = _make_alert_with_company(db_session, url="https://example.com/wipe-deps", ticker="HHH.NS")
    alert_id = alert.id
    ac_id = alert.companies[0].id

    db_session.add(CalibrationSample(
        alert_company_id=ac_id, category="test", company_id=company.id,
        direction="bullish", magnitude_actual=1.5, horizon_days=1,
    ))
    db_session.add(CarOutcome(
        alert_company_id=ac_id, company_id=company.id, category="test",
        day0_excess_move_pct=1.0, car_pct=1.0,
    ))
    db_session.add(MarketMove(
        alert_id=alert_id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: AnalysisOutput(
            category="test", companies=[], edges=[], gaps=[]),
    )

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert db_session.query(AlertCompany).filter_by(id=ac_id).count() == 1
    assert db_session.query(CalibrationSample).filter_by(alert_company_id=ac_id).count() == 1
    assert db_session.query(CarOutcome).filter_by(alert_company_id=ac_id).count() == 1
    assert db_session.query(MarketMove).filter_by(alert_id=alert_id).count() == 1


def test_allow_empty_overrides_the_guard_and_writes_the_empty_result(db_session, monkeypatch, capsys):
    """Zero genuinely IS the right answer sometimes (a reclassified article
    that turns out to affect no listed company). --allow-empty is the
    operator's explicit yes."""
    alert, _ = _make_alert_with_company(db_session, url="https://example.com/allow-empty", ticker="III.NS")
    alert_id = alert.id
    assert db_session.query(AlertCompany).filter_by(alert_id=alert_id).count() == 1

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: AnalysisOutput(
            category="test", companies=[], edges=[], gaps=[]),
    )

    reanalyze_cascade.main(limit=5, days=None, force=False, allow_empty=True)

    assert db_session.query(AlertCompany).filter_by(alert_id=alert_id).count() == 0
    out = capsys.readouterr().out
    assert "company count: 1 -> 0" in out
    assert "ZERO companies" not in out


def test_zero_company_result_over_an_already_empty_alert_is_not_blocked(db_session, monkeypatch, capsys):
    """The guard is about LOSING data. An alert that already has no
    companies has none to lose, so a zero result there is a normal
    (no-op) replacement, not a suspected failure."""
    article = Article(source="test", url="https://example.com/already-empty", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: AnalysisOutput(
            category="test", companies=[], edges=[], gaps=[]),
    )

    reanalyze_cascade.main(limit=5, days=None, force=False)

    out = capsys.readouterr().out
    assert "company count: 0 -> 0" in out
    assert "ZERO companies" not in out


def test_a_raised_stage_leaves_the_existing_companies_and_history_intact(db_session, monkeypatch, capsys):
    """The already-existing skip path: analyze_article raising (a stage-1/2
    failure propagates by design) must not have deleted anything. Verified
    explicitly rather than assumed -- the whole bug class is 'delete first,
    then discover the new answer is bad'."""
    alert, company = _make_alert_with_company(db_session, url="https://example.com/raised", ticker="JJJ.NS")
    alert_id = alert.id
    ac_id = alert.companies[0].id

    db_session.add(CalibrationSample(
        alert_company_id=ac_id, category="test", company_id=company.id,
        direction="bullish", magnitude_actual=1.5, horizon_days=1,
    ))
    db_session.add(MarketMove(
        alert_id=alert_id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.1, excess_move_pct=0.9,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    def raising_analysis(client, title, content, session=None):
        raise ValueError("No record_sectors tool_use block")

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(reanalyze_cascade, "analyze_article", raising_analysis)

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert db_session.query(AlertCompany).filter_by(id=ac_id).count() == 1
    assert db_session.query(CalibrationSample).filter_by(alert_company_id=ac_id).count() == 1
    assert db_session.query(MarketMove).filter_by(alert_id=alert_id).count() == 1

    out = capsys.readouterr().out
    assert "SKIPPED (analysis call failed" in out
    assert "left untouched" in out


def test_a_normal_successful_reanalysis_still_replaces_cleanly(db_session, monkeypatch, capsys):
    """The guard must not get in the way of the ordinary case: a fresh
    analysis with real companies replaces the old rows exactly as before."""
    alert, old_company = _make_alert_with_company(db_session, url="https://example.com/normal", ticker="KKK.NS")
    alert_id = alert.id
    old_company_id = old_company.id

    new_company = Company(ticker="LLL.NS", name="LLL", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(new_company)
    db_session.commit()
    new_company_id = new_company.id

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: _fake_analysis_with_company("LLL.NS"),
    )

    reanalyze_cascade.main(limit=5, days=None, force=False)

    remaining = db_session.query(AlertCompany).filter_by(alert_id=alert_id).all()
    assert len(remaining) == 1
    # Asserted on company_id, not row id: SQLite reuses a deleted rowid, so
    # the replacement row can legitimately land on old_ac_id again.
    assert remaining[0].company_id == new_company_id
    assert remaining[0].company_id != old_company_id, "the old company should have been replaced"

    out = capsys.readouterr().out
    assert "company count: 1 -> 1" in out
    assert "SKIPPED" not in out


def test_a_shrink_that_is_not_a_total_wipe_is_written_but_flagged(db_session, monkeypatch, capsys):
    """Documented, deliberate asymmetry: a partial/truncated analysis is NOT
    distinguishable from a genuinely smaller correct answer at this call
    site (AnalysisOutput carries no truncation marker), and shrinking is the
    intended effect of this script -- the precision work exists to strip
    hallucinated companies. So only a total wipe to zero is blocked; any
    smaller shrink is written and merely flagged for the operator."""
    alert, first = _make_alert_with_company(db_session, url="https://example.com/shrink", ticker="MMM.NS")
    alert_id = alert.id
    second = Company(ticker="NNN.NS", name="NNN", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(second)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert_id, company_id=second.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
    ))
    db_session.commit()
    assert db_session.query(AlertCompany).filter_by(alert_id=alert_id).count() == 2

    monkeypatch.setattr(reanalyze_cascade, "init_db", lambda: None)
    monkeypatch.setattr(reanalyze_cascade, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(reanalyze_cascade, "build_client", lambda *a, **k: object())
    monkeypatch.setattr(
        reanalyze_cascade, "analyze_article",
        lambda client, title, content, session=None: _fake_analysis_with_company("MMM.NS"),
    )

    reanalyze_cascade.main(limit=5, days=None, force=False)

    assert db_session.query(AlertCompany).filter_by(alert_id=alert_id).count() == 1
    out = capsys.readouterr().out
    assert "company count: 2 -> 1" in out
    assert "SHRANK (2 -> 1)" in out


def test_allow_empty_flag_is_off_by_default_and_parsed_from_the_cli():
    """A wrong 'yes' here is irreversible, so the default must be off. Run
    the real CLI so the argparse wiring (not just main's keyword default) is
    what's under test."""
    script = Path(__file__).resolve().parent.parent / "reanalyze_cascade.py"

    help_text = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, cwd=script.parent,
    )
    assert help_text.returncode == 0
    assert "--allow-empty" in help_text.stdout

    parser_defaults = subprocess.run(
        [sys.executable, "-c",
         "import reanalyze_cascade, inspect;"
         "sig = inspect.signature(reanalyze_cascade.reanalyze_alert);"
         "print(sig.parameters['allow_empty'].default);"
         "print(inspect.signature(reanalyze_cascade.main).parameters['allow_empty'].default)"],
        capture_output=True, text=True, cwd=script.parent,
    )
    assert parser_defaults.stdout.split() == ["False", "False"], parser_defaults.stderr
