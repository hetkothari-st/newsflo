# Finnhub Ingestion Source — Design

## Goal

Replace thenewsapi.com (`app/ingestion/thenewsapi.py`) as the active news
ingestion source with `finnhub.io`. thenewsapi's 100-request/day free-tier
cap has repeatedly exhausted mid-day in production (confirmed the direct
cause of a real outage-in-features earlier this session: zero new
articles analyzed, zero cascade companies shown), and the user has already
obtained a Finnhub API key. User explicitly chose polling over Finnhub's
webhook push option (a webhook secret was also provided but goes unused
under this design — nothing in the codebase reads it).

## Current state (grounded in the actual code)

- `app/ingestion/thenewsapi.py::fetch_new_thenewsapi_articles(session,
  api_token)` is the active precedent this design mirrors closely:
  `httpx.get` with a timeout, auth via query param, parse `response.json()
  ["data"]`, dedupe by `Article.url`, insert new rows with
  `status="NEW"`, return the count inserted. Never raises — a
  request/parse failure returns `0`, the next scheduler tick retries.
- `app/ingestion/indianapi.py` is the precedent for how this codebase
  disables-without-deleting an ingestion source when swapping to a new
  one: its import in `scheduler.py` is commented out with an explanatory
  note ("IndianAPI is disabled (not deleted)... Swap the
  fetch_new_indianapi_articles(...) call back in... to revert"). This
  design disables thenewsapi the same way.
- `scheduler.py::start_scheduler` registers `_run_thenewsapi_ingestion` on
  its own interval job (`thenewsapi_poll`,
  `minutes=settings.thenewsapi_poll_interval_minutes`), separate from the
  main `_run_ingestion_and_analysis` job (`rss_poll` — despite the job id,
  this is the general analysis-cycle job, unrelated to ingestion).
- `app/models.py::Article` fields this maps into: `source`, `url`,
  `title`, `content` (short summary — `full_content` is fetched
  separately, unaffected by this change), `published_at`, `image_url`,
  `status`.
- `app/config.py::Settings` is where all API keys/intervals live, one
  `os.environ.get(...)` field per setting, same pattern for every source.
- `app/log_redaction.py::_SECRET_QUERY_PARAM_PATTERN` already matches
  `token=` (among `api_token`/`api_key`/`key`) in any rendered log
  message — Finnhub's own query-param auth is already covered, no
  redaction change needed.

## finnhub.io API (verified via their published docs)

- Base URL: `https://finnhub.io/api/v1/news` — general market news
  endpoint.
- Auth: query parameter `token` (not a header for this design — same
  query-param shape as thenewsapi, different param name).
- Relevant query param: `category`, one of `general | forex | crypto |
  merger` — no comma-separated multi-category support, unlike thenewsapi.
  Per the user's explicit choice: two separate requests per poll cycle,
  `category=general` and `category=merger`.
- Response: a bare top-level JSON array (not wrapped in a `data` key,
  different from thenewsapi) of objects: `category`, `datetime` (Unix
  epoch seconds, not ISO-8601 — a real mechanical difference from
  thenewsapi's `published_at`), `headline`, `id`, `image`, `related`,
  `source`, `summary`, `url`.
- Free tier: 60 requests/minute. At 2 requests/cycle (general + merger)
  and a 1-minute poll interval, that's 2/60 of the budget per cycle —
  no meaningful exhaustion risk, unlike thenewsapi's tight 100/day math.
- Rate limiting: `429` on too many requests/minute — just an HTTP error
  status, handled by the same "never raise, degrade to 0" contract as
  every other failure mode.

## Design

### 1. New ingestion module

`app/ingestion/finnhub.py`:

```python
def fetch_new_finnhub_articles(session: Session, api_key: str) -> int:
    """Poll finnhub.io's /api/v1/news endpoint (general + merger
    categories) for new articles, insert any not already seen (deduped
    by url). A request/parse failure for either category never raises --
    skip that category this cycle, retry next, same contract as every
    other ingestion source. A missing api_key returns 0 without making
    any request.
    """
```

Implementation mirrors `fetch_new_thenewsapi_articles` structurally
(try/except around each request, dedupe-by-url loop, `status="NEW"`
inserts, one `session.commit()` at the end covering both categories),
with the real mechanical differences:
- Two requests per call, one per category (`general`, `merger`), each
  independently wrapped in try/except — one category's failure doesn't
  block the other.
- Auth via `params={"category": category, "token": api_key}`.
- Response is read as a bare list (`response.json()`), not `["data"]`.
- Field mapping: `headline`→`title`, `summary`→`content`, `url`→`url`,
  `image`→`image_url`, `source`→`source` (falls back to `"finnhub"` if
  blank/absent, same convention as thenewsapi's `"thenewsapi"` fallback).
- Date parsing: `datetime` is a Unix epoch integer (seconds) —
  `datetime.fromtimestamp(value, tz=timezone.utc)`, not the ISO-8601
  string parsing thenewsapi used.
- Same-URL dedup must apply across both categories within one call (a
  story returned by both `general` and `merger` must insert once, not
  twice). The existing per-item `session.query(Article).filter_by
  (url=url).one_or_none()` check alone is **not** sufficient for this: `
  SessionLocal` is configured with `autoflush=False` (`app/db.py:16`), so
  a row added via `session.add(...)` while processing `general` is not
  yet visible to that same query when `merger` is processed next in the
  same call — the row only becomes visible to a fresh query after
  `session.commit()`. Fix: track a local `set()` of URLs seen so far in
  this call (seeded with nothing, added to right after each
  `session.add`), and skip an item if its URL is in that set OR already
  in the DB — both checks required, one for cross-category duplicates
  within this call, one for duplicates from a prior call.

### 2. Config

`app/config.py` gains:

```python
finnhub_api_key: str = os.environ.get("FINNHUB_API_KEY", "")
finnhub_poll_interval_minutes: int = int(os.environ.get("FINNHUB_POLL_INTERVAL_MINUTES", "1"))
```

`thenewsapi_api_key`/`thenewsapi_poll_interval_minutes` are left
completely untouched — same rationale as the indianapi swap: the
existing comment accurately documents a real historical decision, and
touching it serves no purpose now that the module is being disabled, not
deleted.

### 3. Scheduler swap (disable thenewsapi, don't delete)

In `scheduler.py`, following the exact precedent already set for
IndianAPI: comment out the `fetch_new_thenewsapi_articles` import and
`_run_thenewsapi_ingestion`'s `scheduler.add_job(...)` registration, with
an explanatory note pointing at this design doc and stating how to
revert. Add a new `_run_finnhub_ingestion()` function (same shape as
`_run_thenewsapi_ingestion`: open a session, call the fetcher, log the
count, close the session, never raise) and register it on its own
interval job (`finnhub_poll`,
`minutes=settings.finnhub_poll_interval_minutes`), in the same place the
thenewsapi job used to be registered.

### 4. Deployment

`FINNHUB_API_KEY` needs to be set as a Railway environment variable on
the `newsflo-app` service before this reaches production — provided
directly by the user in chat, handled the same way every other
production credential has been this session: never committed to git,
never echoed back, set directly as a Railway variable at deploy time.
The webhook secret the user also provided is **not** set anywhere —
nothing in this design reads it (polling was explicitly chosen over
webhook push).

## Explicitly out of scope

Webhook push ingestion — user explicitly chose polling. Running
thenewsapi and Finnhub concurrently — user explicitly chose replace over
supplement. Deleting `thenewsapi.py` outright — kept disabled-not-deleted,
matching this codebase's own established convention for source swaps.
Pulling Finnhub's `forex`/`crypto` categories — user explicitly scoped to
`general`+`merger`.

## Testing

`fetch_new_finnhub_articles`: unit tests mirroring `test_thenewsapi.py`'s
structure and coverage — insert-and-dedupe, fallback source name when
absent, skip items without a `url`, **a same-URL item returned by both
`general` and `merger` in one call inserts exactly once** (this is the
autoflush=False case above — a test using a `sessionmaker` with
`autoflush=False`, matching production's `SessionLocal`, not the default
test fixture's autoflush-on session, is required to actually exercise
this bug; using the default fixture would pass even with the bug
present),
return 0 without an api_key (confirm zero HTTP calls made), swallow a
request timeout for one category without blocking the other, swallow an
HTTP error status, swallow a malformed (non-list) response. A
`scheduler.py`-level check (or manual inspection, matching how the
IndianAPI/thenewsapi disablement wasn't itself unit-tested) confirming
`_run_finnhub_ingestion` is registered and `_run_thenewsapi_ingestion` is
not.
