"""Stage 1 of the universe ingest: network only. Writes raw source
responses verbatim into a dated snapshot dir and returns the path. Nothing
here touches the DB or interprets a payload beyond an emptiness check.

Unlike the rest of the market plumbing, these fetchers RAISE on failure
rather than degrading. A source that changed shape or went away must fail
loudly at stage 1, before anything reaches the database -- silently loading
a truncated snapshot would corrupt the universe (spec §10).

Both exchanges reject non-browser User-Agents; BSE additionally requires a
Referer header. Verified against live endpoints on 2026-08-03.
"""
import ssl
import time
import urllib.request
from datetime import date
from pathlib import Path

import certifi

from app.companies.universe import snapshot

NSE_EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_SCRIP_LIST_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)
BSE_DETAIL_URL_TEMPLATE = (
    "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w"
    "?quotetype=EQ&scripcode={scrip_code}&seriesid="
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/csv, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """Default transport. Tests inject a fake opener instead of calling
    this. certifi is required -- see CLAUDE.md on bare
    ssl.create_default_context failing without a CA bundle."""
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context).read()


def _write_master(root: str, day: date, name: str, payload: bytes) -> Path:
    if not payload:
        raise ValueError(f"empty payload for {name}; refusing to write snapshot")
    path = snapshot.master_path(root, day, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def fetch_nse_equity_list(root: str, day: date, opener=None) -> Path:
    fetch = opener or fetch_bytes
    return _write_master(root, day, "nse_equity_l.csv", fetch(NSE_EQUITY_L_URL))


def fetch_bse_scrip_list(root: str, day: date, opener=None) -> Path:
    fetch = opener or fetch_bytes
    return _write_master(root, day, "bse_scrips.json", fetch(BSE_SCRIP_LIST_URL))


_BACKOFF_BASE_SECONDS = 2.0
# Give up on the whole pass once this many scrips in a row have failed every
# retry. Measured 2026-08-05: BSE answers ~2 of 18 requests from Railway's
# egress IP while answering 18 of 18 from a normal connection. Without this
# guard the monthly job walks all ~4,700 scrips at three 60s timeouts each --
# days of wall-clock to accomplish nothing. A blocked source must be a fast,
# loud failure, not a slow silent one.
_ABORT_AFTER_CONSECUTIVE_FAILURES = 50


def fetch_bse_details(
    root: str,
    day: date,
    scrip_codes: list[str],
    opener=None,
    sleep=None,
    throttle_seconds: float = 0.3,
    max_retries: int = 3,
    abort_after_consecutive_failures: int = _ABORT_AFTER_CONSECUTIVE_FAILURES,
    time_budget_seconds: float | None = None,
    clock=None,
) -> dict:
    """Fetch the official 4-level classification for each scrip, one call
    each (~5,000 for a full run). Resumable: codes already on disk for
    ``day`` are skipped, so a rate-limit partway through costs only the
    remainder.

    Unlike the master fetchers, a per-scrip failure does NOT raise -- one
    dead scrip must not cost the other 4,999. The code is recorded in
    ``failed`` and its company is later ingested with NULL classification
    rather than a guessed sector.
    """
    fetch = opener or fetch_bytes
    pause = sleep if sleep is not None else time.sleep
    already = snapshot.fetched_scrip_codes(root, day)

    now = clock or time.monotonic
    deadline = (now() + time_budget_seconds) if time_budget_seconds else None

    fetched = 0
    skipped = 0
    failed: list[str] = []
    consecutive_failures = 0
    aborted = False
    exhausted = False

    for scrip_code in scrip_codes:
        if scrip_code in already:
            skipped += 1
            continue

        if (
            abort_after_consecutive_failures
            and consecutive_failures >= abort_after_consecutive_failures
        ):
            aborted = True
            break

        # Stop cleanly on the budget rather than being killed mid-write.
        # Everything fetched so far is on disk, so the next firing resumes
        # from here -- this is what lets a slow, throttled source be
        # consumed over several short daily runs instead of one long one.
        if deadline is not None and now() >= deadline:
            exhausted = True
            break

        payload = None
        for attempt in range(max_retries):
            try:
                payload = fetch(BSE_DETAIL_URL_TEMPLATE.format(scrip_code=scrip_code))
                break
            except Exception:
                if attempt == max_retries - 1:
                    break
                pause(_BACKOFF_BASE_SECONDS * (2 ** attempt))

        if not payload:
            failed.append(scrip_code)
            consecutive_failures += 1
            continue

        consecutive_failures = 0
        path = snapshot.detail_path(root, day, scrip_code)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        fetched += 1
        if throttle_seconds:
            pause(throttle_seconds)

    # `aborted` means the source refused us, NOT that these scrips have no
    # classification. The caller must not treat the run as complete: the
    # loader's per-field write guards already leave existing classifications
    # alone when a detail file is absent, so an aborted pass degrades to
    # "nothing new today" rather than blanking what is already stored.
    return {
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "aborted": aborted,
        "exhausted": exhausted,
        "remaining": max(
            0, len(scrip_codes) - skipped - fetched - len(failed),
        ),
    }
