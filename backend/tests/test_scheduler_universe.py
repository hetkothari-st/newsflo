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
