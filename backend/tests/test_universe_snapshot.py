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
