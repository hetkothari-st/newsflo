"""Shared IST (India Standard Time) date/window helpers.

The app is India-focused (RSS sources, trading calendar) -- "today" and
calendar-day/month boundaries are always IST, regardless of the viewer's
browser timezone or the server host's own local timezone. Used by both
routers/alerts.py (the main feed's "today only" filter) and
routers/calendar.py (month/day bucketing) -- factored out here rather than
one importing from the other, since alerts.py already exports helpers that
calendar.py imports (importing back the other way would be circular).
"""
from datetime import date as date_cls, datetime, timedelta, timezone

from app.pipeline import _as_aware_utc

IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date_cls:
    return datetime.now(timezone.utc).astimezone(IST).date()


def to_ist_date(created_at: datetime) -> date_cls:
    # SQLite round-trips DateTime(timezone=True) columns as naive values
    # (confirmed: Alert.created_at comes back with tzinfo=None even though
    # it was written as an aware UTC datetime) -- .astimezone() on a naive
    # datetime assumes it's already in the *system's local* timezone, which
    # silently no-ops on a server whose local tz happens to be IST. Same
    # SQLite quirk _as_aware_utc exists for in app.pipeline; reuse it rather
    # than re-deriving the same fix here.
    return _as_aware_utc(created_at).astimezone(IST).date()


def day_utc_window(day: date_cls) -> tuple[datetime, datetime]:
    """UTC [start, end) covering every instant that falls in IST calendar
    day `day`."""
    start_ist = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start_ist.astimezone(timezone.utc), (start_ist + timedelta(days=1)).astimezone(timezone.utc)


def month_utc_window(year: int, month: int) -> tuple[datetime, datetime]:
    """UTC [start, end) covering every instant that falls in IST calendar
    month `year`-`month`, so a single UTC-range query can't miss alerts
    created near the IST month boundary. Caller is responsible for
    validating `month` is 1-12."""
    start_ist = datetime(year, month, 1, tzinfo=IST)
    end_ist = datetime(year + 1, 1, 1, tzinfo=IST) if month == 12 else datetime(year, month + 1, 1, tzinfo=IST)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)
