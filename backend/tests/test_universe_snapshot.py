from datetime import date

from app.companies.universe import snapshot


def test_snapshot_dir_is_dated(tmp_path):
    path = snapshot.snapshot_dir(str(tmp_path), date(2026, 8, 3))
    assert path.name == "2026-08-03"


def test_master_and_detail_paths_are_separated(tmp_path):
    day = date(2026, 8, 3)
    master = snapshot.master_path(str(tmp_path), day, "nse_equity_l.csv")
    detail = snapshot.detail_path(str(tmp_path), day, "500325")
    assert master.name == "nse_equity_l.csv"
    assert detail.parent.name == "bse_detail"
    assert detail.name == "500325.json"


def test_fetched_scrip_codes_is_empty_before_any_fetch(tmp_path):
    assert snapshot.fetched_scrip_codes(str(tmp_path), date(2026, 8, 3)) == set()


def test_fetched_scrip_codes_reports_what_is_on_disk(tmp_path):
    day = date(2026, 8, 3)
    path = snapshot.detail_path(str(tmp_path), day, "500325")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert snapshot.fetched_scrip_codes(str(tmp_path), day) == {"500325"}


def test_latest_snapshot_day_picks_the_newest(tmp_path):
    for name in ("2026-07-01", "2026-08-03", "2026-06-15"):
        (tmp_path / name).mkdir()
    assert snapshot.latest_snapshot_day(str(tmp_path)) == date(2026, 8, 3)


def test_latest_snapshot_day_is_none_when_empty(tmp_path):
    assert snapshot.latest_snapshot_day(str(tmp_path)) is None


def test_latest_snapshot_day_ignores_non_date_directories(tmp_path):
    (tmp_path / "scratch").mkdir()
    (tmp_path / "2026-08-03").mkdir()
    assert snapshot.latest_snapshot_day(str(tmp_path)) == date(2026, 8, 3)


def test_latest_detail_day_is_none_when_no_snapshots(tmp_path):
    assert snapshot.latest_detail_day(str(tmp_path)) is None


def test_latest_detail_day_ignores_days_with_no_detail_dir(tmp_path):
    # A master-only day (the daily refresh's fresh, detail-empty directory)
    # must not be picked as the detail day.
    (tmp_path / "2026-08-03").mkdir()
    assert snapshot.latest_detail_day(str(tmp_path)) is None


def test_latest_detail_day_ignores_days_with_an_empty_detail_dir(tmp_path):
    (tmp_path / "2026-08-03" / snapshot.DETAIL_DIRNAME).mkdir(parents=True)
    assert snapshot.latest_detail_day(str(tmp_path)) is None


def test_latest_detail_day_picks_the_newest_day_that_actually_has_details(tmp_path):
    # Day B (newer) is a master-only refresh with an empty bse_detail/.
    # Day A (older) is where the monthly detail pass actually landed.
    # This is exactly the daily-drift scenario: latest_snapshot_day would
    # return B, but the classification files only exist under A.
    day_a = date(2026, 7, 1)
    day_b = date(2026, 8, 3)
    detail_a = snapshot.detail_path(str(tmp_path), day_a, "500325")
    detail_a.parent.mkdir(parents=True, exist_ok=True)
    detail_a.write_text("{}", encoding="utf-8")
    (tmp_path / day_b.isoformat() / snapshot.DETAIL_DIRNAME).mkdir(parents=True)

    assert snapshot.latest_snapshot_day(str(tmp_path)) == day_b
    assert snapshot.latest_detail_day(str(tmp_path)) == day_a


def _detail_day(root, day, code="500001"):
    path = snapshot.detail_path(str(root), day, code)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def test_detail_target_day_continues_an_in_progress_pass(tmp_path):
    """The daily master refresh makes a fresh empty directory every morning.
    The detail pass must keep filling yesterday's, or it restarts forever."""
    _detail_day(tmp_path, date(2026, 8, 5))
    (tmp_path / "2026-08-08").mkdir()
    assert snapshot.detail_target_day(str(tmp_path), date(2026, 8, 8)) == date(2026, 8, 5)


def test_detail_target_day_starts_fresh_once_the_pass_is_stale(tmp_path):
    _detail_day(tmp_path, date(2026, 6, 1))
    (tmp_path / "2026-08-08").mkdir()
    assert snapshot.detail_target_day(str(tmp_path), date(2026, 8, 8)) == date(2026, 8, 8)


def test_detail_target_day_falls_back_to_the_newest_snapshot(tmp_path):
    (tmp_path / "2026-08-08").mkdir()
    assert snapshot.detail_target_day(str(tmp_path), date(2026, 8, 8)) == date(2026, 8, 8)


def test_detail_target_day_is_none_without_any_snapshot(tmp_path):
    assert snapshot.detail_target_day(str(tmp_path), date(2026, 8, 8)) is None
