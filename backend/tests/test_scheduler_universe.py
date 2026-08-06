from datetime import timedelta

import app.scheduler as scheduler


def test_master_refresh_never_raises(monkeypatch):
    def boom(*_a, **_kw):
        raise OSError("nse down")

    monkeypatch.setattr(scheduler.fetchers, "fetch_nse_equity_list", boom)
    # A dead exchange must not kill the scheduler thread -- same contract as
    # every other job in this module.
    scheduler._run_universe_master_refresh()


def test_detail_refresh_never_raises(monkeypatch):
    # Patch the function the job actually calls to choose its day. Patching
    # an internal of it is not enough: detail_target_day also consults
    # latest_detail_day, which reads the real data/universe directory, so a
    # developer machine holding a partial snapshot turned this unit test
    # into a live 45-minute BSE fetch.
    monkeypatch.setattr(
        scheduler.snapshot, "detail_target_day", lambda _root, _today: None,
    )
    scheduler._run_universe_detail_refresh()


def test_detail_refresh_does_no_network_when_there_is_no_snapshot(monkeypatch):
    """The guard above is load-bearing -- assert it, so the seam cannot
    silently move again."""
    monkeypatch.setattr(
        scheduler.snapshot, "detail_target_day", lambda _root, _today: None,
    )

    def explode(*args, **kwargs):
        raise AssertionError("detail refresh must not fetch without a snapshot")

    monkeypatch.setattr(scheduler.fetchers, "fetch_bse_details", explode)
    scheduler._run_universe_detail_refresh()


def test_jobs_are_registered(monkeypatch):
    """Assert against the LIVE job registry (scheduler.get_jobs()), not
    source text. A source-text assertion ("the string appears somewhere in
    start_scheduler") is exactly why the day-mismatch bug in
    _run_universe_detail_refresh survived twenty reviews -- the daily job
    and the monthly job were both registered and both mentioned in the
    source, so the string check passed even though the monthly job's output
    was silently never consumed by the daily one. Checking the real
    APScheduler job objects (ids + trigger intervals) at least proves the
    jobs exist with the intended cadence, which a grep can't.

    BackgroundScheduler.start is monkeypatched to a no-op so this test never
    spins up a real background thread or executes any job body (no network,
    no DB writes) -- add_job's bookkeeping (and therefore get_jobs()) works
    identically whether or not the scheduler has actually started.
    """
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self: None)
    try:
        scheduler.start_scheduler()
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}

        assert "universe_master_refresh" in jobs
        assert jobs["universe_master_refresh"].trigger.interval == timedelta(hours=24)

        # Daily, not monthly: BSE throttles us to roughly half throughput, so
        # the pass runs on a 45-minute budget each day and resumes into the
        # same dated directory until it completes.
        assert "universe_detail_refresh" in jobs
        assert jobs["universe_detail_refresh"].trigger.interval == timedelta(hours=24)
    finally:
        scheduler._scheduler = None


def test_business_profile_refresh_is_no_longer_scheduled():
    # It fabricated a business description for every company with a NULL one,
    # every 6 hours. After the universe ingest that is ~5,140 companies.
    assert not hasattr(scheduler, "_run_business_profile_refresh")


def test_event_volatility_refresh_is_registered_nightly(monkeypatch):
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self: None)
    try:
        scheduler.start_scheduler()
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert "event_volatility_refresh" in jobs
        assert jobs["event_volatility_refresh"].trigger.interval == timedelta(hours=24)
    finally:
        scheduler._scheduler = None


def test_event_volatility_refresh_never_raises_and_does_no_network(monkeypatch):
    """Rebuild reads the DB only. Any urllib call from this job is a bug.

    A bare monkeypatch of urllib.request.urlopen is not enough on its own:
    the job body wraps everything in try/except Exception, so an
    AssertionError raised by an accidental network call would be swallowed
    right alongside a legitimate DB error, and this test would pass either
    way. Stubbing rebuild() and asserting it is called exactly once proves
    the job wrapper calls rebuild() exactly once with no network call
    before it, and that nothing on that path swallowed an exception. It
    does NOT prove the real rebuild() body is network-free -- fake_rebuild
    never inspects rebuild's internals, so a stray urlopen call added AFTER
    rebuild() returns would still be swallowed here and pass. rebuild()'s
    network-freedom rests on it being plain SQLAlchemy ORM code (see
    app/market/event_volatility.py), not on this test.
    """
    import urllib.request

    def explode(*args, **kwargs):
        raise AssertionError("event volatility refresh must not touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", explode)

    calls = []

    def fake_rebuild(session, as_of):
        calls.append(as_of)
        return {"facts": 0, "deleted": 0, "inserted": 0}

    monkeypatch.setattr("app.market.event_volatility.rebuild", fake_rebuild)

    scheduler._run_event_volatility_refresh()

    assert len(calls) == 1


def test_supply_link_jobs_are_registered_daily(monkeypatch):
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self: None)
    try:
        scheduler.start_scheduler()
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert "rating_filings_poll" in jobs
        assert jobs["rating_filings_poll"].trigger.interval == timedelta(hours=24)
        assert "supply_links_refresh" in jobs
        assert jobs["supply_links_refresh"].trigger.interval == timedelta(hours=24)
    finally:
        scheduler._scheduler = None


def test_supply_links_refresh_never_raises_without_snapshots(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler.supply_snapshot, "DEFAULT_ROOT", str(tmp_path))
    scheduler._run_supply_links_refresh()  # empty root: no docs, no crash


def test_registered_job_ids_do_not_include_the_profile_refresh(monkeypatch):
    # Assert on the scheduler's own registry, not on source text -- a prior
    # review found a getsource-based assertion hid a real defect for 20 tasks.
    #
    # start_scheduler() builds its own BackgroundScheduler internally and
    # publishes it via the module-level app.scheduler._scheduler global --
    # it does not read a scheduler pre-assigned onto the module by the
    # caller. So, same pattern as test_jobs_are_registered above: patch
    # BackgroundScheduler.start to a no-op (no real thread, no job bodies
    # executed) and inspect the live registry after the call.
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self: None)
    try:
        scheduler.start_scheduler()
        job_ids = {job.id for job in scheduler._scheduler.get_jobs()}
        assert "business_profile_refresh" not in job_ids
    finally:
        scheduler._scheduler = None


# --- Task 7 review fix: per-doc isolation in the extraction drain ----------
#
# Reproduced failure: extract.py's gate() (pre-dedupe-fix) could yield two
# (name, evidence) entries for the same counterparty name, which
# loader.apply_extraction then tried to INSERT twice, hitting
# uq_supply_link_company_relation_counterparty and raising IntegrityError.
# The job's single outer try/except caught it at the OUTER level, which
# aborted the entire remaining queue for the day (every doc after the
# poisoned one silently never processed) -- and since the poisoned doc was
# never marked extracted, it re-poisoned every subsequent run at the same
# glob position forever. The per-doc try/except must isolate exactly one
# document's failure, roll back the session, count it "errored", and leave
# it pending (no mark_extracted) while every other document in the same run
# still gets processed.


def test_supply_links_refresh_isolates_a_poisoned_doc(monkeypatch, tmp_path, db_session, caplog):
    import json
    import logging
    from datetime import date as date_cls

    from app.companies.supply_links import extract as supply_extract, loader as supply_loader
    from app.models import Company, Listing, SupplyLink

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(scheduler.supply_snapshot, "DEFAULT_ROOT", str(tmp_path))
    monkeypatch.setattr(scheduler, "build_client", lambda *a, **kw: object())

    poisoned = Company(ticker="POISON.NS", name="Poison Ltd", sector="other", index_tier="OTHER")
    healthy = Company(ticker="HEALTHY.NS", name="Healthy Ltd", sector="other", index_tier="OTHER")
    db_session.add_all([poisoned, healthy])
    db_session.flush()
    db_session.add_all([
        Listing(company_id=poisoned.id, exchange="BSE", symbol="POISON", scrip_code="111",
                source="test", as_of=date_cls(2026, 1, 1)),
        Listing(company_id=healthy.id, exchange="BSE", symbol="HEALTHY", scrip_code="222",
                source="test", as_of=date_cls(2026, 1, 1)),
    ])
    db_session.commit()
    # Captured before the job runs and closes db_session (it's shared with
    # this test via the SessionLocal monkeypatch above) -- querying with
    # these plain ints afterwards avoids touching the now-detached ORM
    # instances' attributes.
    poisoned_id, healthy_id = poisoned.id, healthy.id

    def _write_doc(scrip_code, name):
        url = f"https://x/AttachLive/{scrip_code}.pdf"
        pdf_path = scheduler.supply_snapshot.doc_path(str(tmp_path), scrip_code, url)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        scheduler.supply_snapshot.url_sidecar_path(pdf_path).write_text(url, encoding="utf-8")
        scheduler.supply_snapshot.meta_sidecar_path(pdf_path).write_text(
            json.dumps({
                "scrip_code": scrip_code, "company_name": name,
                "agency": "CRISIL", "news_date": "2026-08-06T00:00:00",
            }),
            encoding="utf-8",
        )
        return pdf_path

    poisoned_pdf = _write_doc("111", "Poison Ltd")
    healthy_pdf = _write_doc("222", "Healthy Ltd")

    monkeypatch.setattr(supply_extract, "pdf_text", lambda _p: "some rationale text")
    monkeypatch.setattr(
        supply_extract, "extract_profile",
        lambda client, name, text: {"business_summary": None, "suppliers": [], "customers": []},
    )

    def fake_apply_extraction(session, company, profile, *, source_url, source_agency, as_of):
        if company.ticker == "POISON.NS":
            raise RuntimeError("simulated duplicate-counterparty IntegrityError")
        session.add(SupplyLink(
            company_id=company.id, relation="CUSTOMER", counterparty_name="Some Buyer",
            evidence="q", source_url=source_url, source_agency=source_agency, as_of=as_of,
        ))
        session.commit()
        return {"links_written": 1, "links_kept_older": 0, "desc_written": 0, "desc_kept": 0}

    monkeypatch.setattr(supply_loader, "apply_extraction", fake_apply_extraction)

    caplog.set_level(logging.INFO, logger="app.scheduler")

    scheduler._run_supply_links_refresh()  # must not raise despite the poisoned doc

    assert "errored=1" in caplog.text
    assert "extracted=1" in caplog.text
    # Healthy doc: processed and marked done.
    assert scheduler.supply_snapshot.done_marker_path(healthy_pdf).exists()
    assert db_session.query(SupplyLink).filter_by(company_id=healthy_id).count() == 1
    # Poisoned doc: left pending (no .done marker) for a genuine retry.
    assert not scheduler.supply_snapshot.done_marker_path(poisoned_pdf).exists()
    assert db_session.query(SupplyLink).filter_by(company_id=poisoned_id).count() == 0
