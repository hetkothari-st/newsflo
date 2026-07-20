# TheNewsAPI Ingestion Source — Design

## Goal

Replace IndianAPI (`app/ingestion/indianapi.py`) as the active news
ingestion source with `thenewsapi.com`. This is prompted by two things:
IndianAPI's feed is currently empty in production — its 500-request/month
key has been exhausted by a documented, deliberate 1-minute poll interval
(`app/config.py:51-57`'s own comment: "Explicit product decision to poll
at 1/min anyway... at that rate the 500 budget is exhausted in ~8 hours")
— and, separately, this was already the intended direction: earlier in
this session's larger insights-pipeline brainstorm, the user said they
"may change it to a generic news API... in the future," which is exactly
what `thenewsapi.com` is (categories: general, science, sports, business,
health, entertainment, tech, politics, food, travel — not financial-news-
scoped like IndianAPI). A real API key has already been obtained.

## Current state (grounded in the actual code)

- `app/ingestion/indianapi.py::fetch_new_indianapi_articles(session,
  api_key)` is the active precedent this design mirrors closely: `httpx.get`
  with a timeout, auth via request header, parse the JSON array, dedupe by
  `Article.url`, insert new rows with `status="NEW"`, return the count
  inserted. Never raises — a request/parse failure returns `0` and the
  next scheduler tick retries.
- The RSS-feed poller (`app/ingestion/poller.py` + `sources.py`) is the
  precedent for how this codebase disables-without-deleting an ingestion
  source when swapping to a new one: its import in `scheduler.py` is
  commented out with an explanatory note ("RSS ingestion... is intact and
  fully working, just not wired in below... Swap the
  fetch_new_articles(...) call back in... to revert"), not removed. This
  design disables IndianAPI the same way.
- `scheduler.py::start_scheduler` registers `_run_indianapi_ingestion` on
  its own interval job (`indianapi_poll`, `minutes=
  settings.indianapi_poll_interval_minutes`), separate from the main
  `_run_ingestion_and_analysis` job (`rss_poll` — despite the job id, this
  is the general analysis-cycle job, unrelated to the RSS poller which
  isn't wired in).
- `app/models.py::Article` fields this maps into: `source`, `url`, `title`,
  `content` (short summary — `full_content` is fetched later, see the
  `2026-07-18-full-text-fetching` feature, unaffected by this change),
  `published_at`, `image_url`, `status`.
- `app/config.py::Settings` is where all API keys/intervals live
  (`indianapi_api_key`, `indianapi_poll_interval_minutes`, etc. — same
  `os.environ.get(...)` pattern for every setting).

## thenewsapi.com API (verified via their published docs)

- Base URL: `https://api.thenewsapi.com/v1/news/all` — "find all live and
  historical articles" (broadest endpoint, matches IndianAPI's usage as a
  general feed, not narrowed to top-headlines-only).
- Auth: query parameter `api_token` (NOT a header — different from
  IndianAPI's `x-api-key` header auth, a real mechanical difference this
  design's `httpx.get` call must reflect).
- Relevant query params: `categories` (comma-separated;
  `business,politics,general,tech` per the user's explicit choice — the
  full generic category set, including sports/entertainment/food/travel,
  is deferred until the relevance-filter rework, sub-project 2 of the
  larger pipeline roadmap, actually ships — pulling fully generic
  categories through today's narrow keyword filter would let a lot of
  noise through), `language=en`, `api_token`.
- Response: JSON object with a `data` array (not a bare top-level array
  like IndianAPI's response) of article objects: `uuid`, `title`,
  `description` (short meta-description — the field this design maps to
  `Article.content`, same role IndianAPI's `summary` field played),
  `url`, `image_url`, `published_at`, `source`. No full-body field exists
  on this API either (confirmed via their docs) — the already-shipped
  full-text-fetching feature remains exactly as necessary as before.
- Free tier: 100 requests/day, capped at 3 articles per request
  (confirmed via their pricing page). A 20-minute poll interval yields 72
  requests/day (28% headroom under the cap) and up to ~216 articles/day
  (72 × 3) before dedup.
- Rate limiting: a `429`/`rate_limit_reached` error on too many requests
  in 60 seconds, and a `402`/`usage_limit_reached` error once the daily
  cap is hit — both are just HTTP error statuses, handled by the same
  "never raise, degrade to 0" contract as every other failure mode.

## Design

### 1. New ingestion module

`app/ingestion/thenewsapi.py`:

```python
def fetch_new_thenewsapi_articles(session: Session, api_token: str) -> int:
    """Poll thenewsapi.com's /v1/news/all endpoint for new articles across
    business/politics/general/tech categories, insert any not already
    seen (deduped by url). A request/parse failure never raises -- skip
    this cycle, retry next, same contract as every other ingestion
    source. A missing api_token returns 0 without making a request (the
    100/day free-tier cap makes an accidental unauthenticated/wasted call
    worth guarding against explicitly, same as IndianAPI's key check).
    """
```

Implementation mirrors `fetch_new_indianapi_articles` structurally
(try/except around the request, dedupe-by-url loop, `status="NEW"`
inserts, `session.commit()` once at the end), with the two real
mechanical differences: auth via `params={"api_token": api_token, ...}`
instead of a header, and reading `response.json()["data"]` instead of a
bare top-level list.

Date parsing: thenewsapi's `published_at` is a standard ISO-8601 UTC
timestamp (unlike IndianAPI's naive-and-implicitly-IST format) — parsed
via `datetime.fromisoformat(value.replace("Z", "+00:00"))`, no timezone
inference needed.

### 2. Config

`app/config.py` gains:

```python
thenewsapi_api_key: str = os.environ.get("THENEWSAPI_API_KEY", "")
thenewsapi_poll_interval_minutes: int = int(os.environ.get("THENEWSAPI_POLL_INTERVAL_MINUTES", "20"))
```

`indianapi_api_key`/`indianapi_poll_interval_minutes` are left completely
untouched — that comment block accurately documents a real historical
decision, and touching it serves no purpose now that the module is being
disabled, not deleted.

### 3. Scheduler swap (disable IndianAPI, don't delete)

In `scheduler.py`, following the exact precedent already set for the RSS
poller: comment out `_run_indianapi_ingestion`'s function body's import
and its `scheduler.add_job(...)` registration, with an explanatory note
pointing at this design doc and stating how to revert. Add a new
`_run_thenewsapi_ingestion()` function (same shape as
`_run_indianapi_ingestion`: open a session, call the fetcher, log the
count, close the session, never raise) and register it on its own
interval job (`thenewsapi_poll`, `minutes=
settings.thenewsapi_poll_interval_minutes`), in the same place the
IndianAPI job used to be registered.

### 4. Deployment

`THENEWSAPI_API_KEY` needs to be set as a Railway environment variable on
the `newsflo-app` service before this reaches production — the key was
provided directly by the user in this session, handled the same way the
production DB credential was earlier: never committed to git, set
directly as a Railway variable at deploy time.

## Explicitly out of scope

Broadening `categories` to the full generic set (sports, entertainment,
health, science, food, travel) — deferred until the relevance-filter
rework (sub-project 2 of the larger insights-pipeline roadmap) ships,
since today's narrow keyword filter (`app/filtering/heuristic.py`) isn't
equipped to reject that volume of genuinely irrelevant content cleanly.
Running both IndianAPI and thenewsapi concurrently — user explicitly
chose replace over supplement. Deleting `indianapi.py` outright — kept
disabled-not-deleted, matching this codebase's own established convention
for source swaps.

## Testing

`fetch_new_thenewsapi_articles`: unit tests mirroring
`test_indianapi.py`'s exact structure and coverage — insert-and-dedupe,
fallback source name when absent, skip items without a `url`, return 0
without an api_token (and confirm zero HTTP calls made, load-bearing per
the 100/day cap), swallow a request timeout, swallow an HTTP error
status, swallow a malformed (non-`data`-array) response. A
`scheduler.py`-level check (or manual inspection, matching how the RSS
poller's disablement wasn't itself unit-tested) confirming
`_run_thenewsapi_ingestion` is registered and `_run_indianapi_ingestion`
is not.
