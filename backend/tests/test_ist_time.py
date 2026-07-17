from datetime import datetime, timezone

from app.ist_time import day_utc_window, month_utc_window, to_ist_date, today_ist


def test_today_ist_is_consistent_with_to_ist_date_of_now():
    # today_ist() is `to_ist_date(datetime.now(utc))` -- both must agree on
    # "now", exercising the real IST offset rather than a mocked clock.
    assert today_ist() == to_ist_date(datetime.now(timezone.utc))


def test_to_ist_date_rolls_over_at_ist_midnight_not_utc_midnight():
    # 23:45 UTC is already the next day in IST (+5:30) -- must roll over.
    assert to_ist_date(datetime(2026, 7, 16, 23, 45, tzinfo=timezone.utc)).isoformat() == "2026-07-17"
    assert to_ist_date(datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)).isoformat() == "2026-07-16"


def test_to_ist_date_treats_naive_datetime_as_utc():
    # SQLite round-trips DateTime(timezone=True) columns as naive -- must
    # not be (mis)treated as the host machine's local time.
    naive = datetime(2026, 7, 16, 23, 45)
    assert naive.tzinfo is None
    assert to_ist_date(naive).isoformat() == "2026-07-17"


def test_day_utc_window_covers_exactly_one_ist_calendar_day():
    from datetime import date
    start, end = day_utc_window(date(2026, 7, 16))
    # 2026-07-16 00:00 IST == 2026-07-15 18:30 UTC.
    assert start == datetime(2026, 7, 15, 18, 30, tzinfo=timezone.utc)
    assert end == datetime(2026, 7, 16, 18, 30, tzinfo=timezone.utc)


def test_month_utc_window_handles_december_rollover():
    start, end = month_utc_window(2026, 12)
    assert start == datetime(2026, 11, 30, 18, 30, tzinfo=timezone.utc)
    assert end == datetime(2026, 12, 31, 18, 30, tzinfo=timezone.utc)
