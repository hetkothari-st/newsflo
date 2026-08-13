"""NSE trading-calendar primitives (corrective-v4 Task 14, spec Sec21
hardening): holiday-aware trading-day arithmetic so the stale/gap guards in
app.market.measure count REAL trading sessions, not calendar days. A
holiday cluster (e.g. a Diwali stretch that lands next to a weekend) used
to inflate the plain calendar-day gap enough to false-flag a perfectly
healthy feed as "stale" purely because several non-trading days happened to
fall in a row. Pure date arithmetic; no LLM, no network calls, nothing
here ever writes to the DB.

NSE_HOLIDAYS source: NSE's published trading-holiday circular for 2025
(cross-checked against multiple mirrors: calendarlabs.com/nse-market-
holidays-2025, jainam.in/nse-holidays, business-standard.com's 2025 holiday
coverage -- all agree on the same 14 dates) and the 2026 circular (verified
2026-08-13 against calendarlabs.com/nse-market-holidays-2026 and
groww.in/p/nse-holidays, which independently agree on the same 15 dates
below). Both years' lists were fetched and cross-checked on 2026-08-13; if
NSE issues a correction circular after that date, this module will be
stale until an owner re-verifies it against nseindia.com directly (Markets
> Trading Holidays) -- the authoritative source neither mirror site is.

One 2026 candidate holiday was deliberately DROPPED rather than guessed:
some mirrors list "Jan 15, 2026 -- Maharashtra Municipal Corporation
Election" as an NSE closure. That is a one-off, state-specific closure
(not a standing national holiday) and only one of the two independently
queried sources carried it -- omitting an uncertain date only relaxes the
trading-day count by one; inventing/keeping an unconfirmed one would
silently corrupt it. Needs an owner to confirm against nseindia.com before
being added. Nov 8, 2026 (Diwali Laxmi Pujan) is a Sunday -- a special
one-hour Muhurat trading session, not a weekday closure -- so it is already
covered by the weekend rule and is not listed as a holiday date.

As-of: 2026-08-13.
"""
from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

# NSE cash session bounds (IST). Moved here from app.market.measure so the
# plain weekday check and the holiday-aware check live beside the same
# calendar data; measure.py re-exports these two names for compatibility
# with existing importers.
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)

NSE_HOLIDAYS: set[date] = {
    # -- 2025 (NSE's published trading-holiday list; 14 dates) --
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-Ul-Fitr (Ramzan Id)
    date(2025, 4, 10),   # Shri Mahavir Jayanti
    date(2025, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21),  # Diwali Laxmi Pujan
    date(2025, 10, 22),  # Diwali-Balipratipada
    date(2025, 11, 5),   # Guru Nanak Jayanti
    date(2025, 12, 25),  # Christmas

    # -- 2026 (verified 2026-08-13 against two independent mirrors; 15
    # dates -- see module docstring for the one candidate date dropped) --
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id / Eid-ul-Adha
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali-Balipratipada
    date(2026, 11, 24),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(d: date) -> bool:
    """Monday-Friday and not an NSE holiday. The single source of "is this
    a real trading day" truth -- measure.py's gap/stale guards and
    session_state() below both call this instead of re-deriving weekday
    logic independently."""
    return d.weekday() < 5 and d not in NSE_HOLIDAYS


def session_state(now_ist: datetime) -> str:
    """"open" during the NSE cash session (09:15-15:30 IST) on a trading
    day, "holiday" on a weekday NSE holiday, "closed" otherwise (weekend or
    off-hours on a trading day)."""
    today = now_ist.date()
    if today.weekday() < 5 and today in NSE_HOLIDAYS:
        return "holiday"
    if not is_trading_day(today):
        return "closed"
    return "open" if SESSION_OPEN <= now_ist.time() <= SESSION_CLOSE else "closed"


def trading_days_between(a: date, b: date) -> int:
    """Count of real NSE trading days strictly between ``a`` and ``b``
    (both endpoints excluded; order-independent -- pass either date first).
    Two bars whose dates are genuinely consecutive trading sessions --
    including across a weekend or a multi-day holiday cluster -- always
    return 0 here. That is what lets app.market.measure's gap/stale guards
    tell "long weekend or holiday cluster, perfectly healthy feed" apart
    from "the feed actually has a hole in it"."""
    if a > b:
        a, b = b, a
    count = 0
    cursor = a + timedelta(days=1)
    while cursor < b:
        if is_trading_day(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count
