"""Network stage for supply-links: discovers rating announcements on BSE
and fetches the rationale PDFs they attach. Nothing here interprets a PDF
or touches the DB -- extract.py (Task 4+) does that from the snapshot this
module writes.

Reuses app.companies.universe.fetchers.fetch_bytes as the default HTTP
opener -- it already carries the browser headers both BSE hosts require
(the announcements API and the AttachLive PDF host); no header logic is
duplicated here.

Two BSE surprises pinned by Task 1's investigation (see
backend/tests/fixtures/ratings/README.md, probed 2026-08-06):

1. Rating actions are not their own top-level category. They live under
   the broad ``strCat=Company Update``, disambiguated by
   ``subcategory=Credit Rating`` -- the literal ``strCat=Credit Rating``
   guess returns a genuinely-empty (not erroring) result.
2. The endpoint silently caps the requested date span at ~30 days. A
   wider request does not 4xx -- it returns HTTP 200 with
   ``{"Status": false, "Message": "Date range exceeded threshold."}``,
   which a caller that only reads ``Table`` (defaulting missing keys to
   ``[]``) would misread as "no rating actions in this period". This
   module treats that shape as a hard failure (raises) and never sends a
   window wider than ``_MAX_WINDOW_DAYS``.
"""
import json
import re
import time
from datetime import date, timedelta

from app.companies.universe.fetchers import fetch_bytes
from app.companies.supply_links import snapshot

ANNOUNCEMENTS_URL_TEMPLATE = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
    "?pageno={pageno}&strCat=Company+Update&subcategory=Credit+Rating"
    "&strPrevDate={from_date}&strToDate={to_date}&strScrip=&strSearch=P&strType=C"
)
ATTACHMENT_URL_TEMPLATE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"

# Observed rows-per-page on this endpoint (fixtures/ratings/README.md,
# probed 2026-08-06): a page short of this count is the last page.
_PAGE_SIZE = 50
# BSE's undocumented cap is ~30 days; 28 keeps every window comfortably
# under it even if the real threshold is inclusive/exclusive off-by-one.
_MAX_WINDOW_DAYS = 28
# Hard stop on pages-per-window: 40 x 50 rows/page = 2,000 rows for a
# single <=28-day window -- far above the observed 279 rows across the
# full 30-day fixture window. A real BSE pagination bug (repeating the
# last full page for every pageno forever) is a documented, common class
# of upstream bug; this caps the damage to one loud failure instead of an
# unbounded loop.
_MAX_PAGES = 40

# Canonical agency name -> case-insensitive pattern. Checked against
# HEADLINE first (that's where filers actually name the agency), then
# against NEWSSUB as a harmless fallback (NEWSSUB is normally generic LODR
# boilerplate that never names an agency, but nothing stops a filer from
# restating it there too).
_AGENCY_PATTERNS = [
    ("CRISIL", re.compile(r"crisil", re.IGNORECASE)),
    ("ICRA", re.compile(r"icra", re.IGNORECASE)),
    ("CARE", re.compile(r"\bcare\b", re.IGNORECASE)),
    ("IND-RA", re.compile(r"ind-ra|india\s+ratings", re.IGNORECASE)),
    ("ACUITE", re.compile(r"acuit[ée]", re.IGNORECASE)),
    ("INFOMERICS", re.compile(r"infomerics", re.IGNORECASE)),
    ("BRICKWORK", re.compile(r"brickwork", re.IGNORECASE)),
]


def _detect_agency(headline: str, newssub: str) -> str | None:
    for canonical, pattern in _AGENCY_PATTERNS:
        if pattern.search(headline or ""):
            return canonical
    for canonical, pattern in _AGENCY_PATTERNS:
        if pattern.search(newssub or ""):
            return canonical
    return None


def parse_announcements(rows: list[dict]) -> list[dict]:
    """Pure. Keeps rows that (a) name a known rating agency in HEADLINE or
    NEWSSUB and (b) carry an attachment. Rows failing either check are
    dropped -- there is nothing useful to extract from a rating
    announcement with no document, and an unnamed agency can't be
    attributed as the source."""
    parsed = []
    for row in rows:
        attachment = (row.get("ATTACHMENTNAME") or "").strip()
        if not attachment:
            continue
        agency = _detect_agency(row.get("HEADLINE", ""), row.get("NEWSSUB", ""))
        if not agency:
            continue
        parsed.append({
            "scrip_code": str(row.get("SCRIP_CD")),
            "company_name": row.get("SLONGNAME"),
            "agency": agency,
            "news_date": row.get("NEWS_DT"),
            "attachment_url": ATTACHMENT_URL_TEMPLATE.format(name=attachment),
        })
    return parsed


def _date_windows(from_date: date, to_date: date, max_days: int = _MAX_WINDOW_DAYS):
    """Split [from_date, to_date] into consecutive <=max_days windows."""
    windows = []
    start = from_date
    while start <= to_date:
        end = min(start + timedelta(days=max_days - 1), to_date)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


def _raise_if_rejected(payload) -> None:
    if isinstance(payload, dict) and payload.get("Status") is False:
        raise ValueError(
            "BSE rejected the announcements query: "
            f"{payload.get('Message', 'no message')!r}"
        )


def fetch_announcements(root, day: date, from_date: date, to_date: date, opener=None) -> list[dict]:
    """Pages through the pinned (strCat=Company Update, subcategory=Credit
    Rating) query across as many <=28-day windows as the requested span
    needs, concatenates every row, writes the combined result to
    ``snapshot.index_path(root, day)``, and returns it.

    RAISES (does not degrade) on any BSE rejection, including the
    Status:false date-range-exceeded shape -- this is the master index for
    the day; a truncated or misread page must fail loudly rather than
    silently under-report rating actions. Also raises if a single window's
    pager runs past ``_MAX_PAGES`` without reaching a short page or its own
    ``Table1[0].ROWCNT`` total -- a real class of upstream pagination bug
    is the server repeating the last full page for every pageno forever,
    and a runaway pager is a source problem deserving the same loud-failure
    treatment as Status:false, not a silent truncation.
    """
    fetch = opener or fetch_bytes
    rows: list[dict] = []

    for window_start, window_end in _date_windows(from_date, to_date):
        pageno = 1
        window_rows: list[dict] = []
        row_count_target = None
        while True:
            url = ANNOUNCEMENTS_URL_TEMPLATE.format(
                pageno=pageno,
                from_date=window_start.strftime("%Y%m%d"),
                to_date=window_end.strftime("%Y%m%d"),
            )
            payload = json.loads(fetch(url).decode("utf-8"))
            _raise_if_rejected(payload)
            page_rows = payload.get("Table") or []
            window_rows.extend(page_rows)

            table1 = payload.get("Table1") or []
            if table1 and isinstance(table1[0], dict):
                rowcnt = table1[0].get("ROWCNT")
                if isinstance(rowcnt, (int, float)) and not isinstance(rowcnt, bool):
                    row_count_target = rowcnt

            if len(page_rows) < _PAGE_SIZE:
                break
            # Cheaper stop than waiting for a short page: BSE's own
            # reported total for this window has already been reached.
            if row_count_target is not None and len(window_rows) >= row_count_target:
                break

            pageno += 1
            if pageno > _MAX_PAGES:
                raise ValueError(
                    "pagination exceeded _MAX_PAGES; BSE paging likely broken"
                )

        rows.extend(window_rows)

    path = snapshot.index_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def fetch_documents(
    root,
    targets: list[dict],
    opener=None,
    sleep=None,
    throttle_seconds: float = 1.0,
    time_budget_seconds: float | None = None,
    clock=None,
) -> dict:
    """Fetches each target's rationale PDF. Mirrors
    app.companies.universe.fetchers.fetch_bse_details's loop shape:
    resumable via snapshot.fetched_doc_urls, a per-document failure
    degrades (appended to ``failed``) rather than aborting the run, and a
    time budget stops the loop cleanly between documents so a slow run can
    be resumed on the next firing.

    ``targets`` are parsed announcement rows (parse_announcements' output
    shape): each needs at least ``scrip_code`` and ``attachment_url``;
    ``company_name``/``agency``/``news_date`` (when present) are written
    into the ``.meta.json`` sidecar for Task 7's extraction drain.
    """
    fetch = opener or fetch_bytes
    pause = sleep if sleep is not None else time.sleep
    already = snapshot.fetched_doc_urls(root)

    now = clock or time.monotonic
    deadline = (now() + time_budget_seconds) if time_budget_seconds else None

    fetched = 0
    skipped = 0
    failed: list[str] = []
    exhausted = False

    for target in targets:
        url = target["attachment_url"]

        if url in already:
            skipped += 1
            continue

        # Stop cleanly on the budget rather than being killed mid-write --
        # everything fetched so far is on disk and resumable next run.
        if deadline is not None and now() >= deadline:
            exhausted = True
            break

        try:
            payload = fetch(url)
        except Exception:
            failed.append(url)
            continue

        if not payload:
            failed.append(url)
            continue

        pdf_path = snapshot.doc_path(root, target.get("scrip_code"), url)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(payload)
        snapshot.url_sidecar_path(pdf_path).write_text(url, encoding="utf-8")
        meta = {
            "scrip_code": target.get("scrip_code"),
            "company_name": target.get("company_name"),
            "agency": target.get("agency"),
            "news_date": target.get("news_date"),
        }
        snapshot.meta_sidecar_path(pdf_path).write_text(json.dumps(meta), encoding="utf-8")

        already.add(url)
        fetched += 1
        if throttle_seconds:
            pause(throttle_seconds)

    return {
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "exhausted": exhausted,
        "remaining": max(0, len(targets) - skipped - fetched - len(failed)),
    }
