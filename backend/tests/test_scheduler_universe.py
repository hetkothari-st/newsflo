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
    monkeypatch.setattr(
        scheduler.snapshot, "latest_snapshot_day", lambda _root: None,
    )
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

        assert "universe_detail_refresh" in jobs
        assert jobs["universe_detail_refresh"].trigger.interval == timedelta(days=30)
    finally:
        scheduler._scheduler = None
