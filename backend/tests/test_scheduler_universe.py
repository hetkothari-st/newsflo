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


def test_jobs_are_registered():
    import inspect
    source = inspect.getsource(scheduler.start_scheduler)
    assert "universe_master_refresh" in source
    assert "universe_detail_refresh" in source
