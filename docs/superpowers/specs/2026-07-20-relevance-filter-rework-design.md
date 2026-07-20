# Relevance Filter Rework — Design

## Goal

This is sub-project 2 of the larger insights-pipeline roadmap (sub-project
1, full article text fetching, shipped `2026-07-18`). The ingestion source
has since changed too (`2026-07-20`): IndianAPI (financial-news-scoped) was
replaced by thenewsapi.com, a genuinely generic news API (categories
include general/science/sports/business/health/entertainment/tech/
politics/food/travel, currently restricted to `business,politics,general,
tech` specifically because today's keyword filter isn't equipped to reject
a fully generic stream cleanly — see `docs/superpowers/specs/2026-07-20-
thenewsapi-ingestion-source-design.md`'s "Explicitly out of scope"
section). This sub-project is that deferred work: replace the keyword
filter with something that can actually judge relevance, so the category
restriction can eventually be lifted and stories the keyword list was
never going to catch (a government infrastructure announcement, a
company's contract win — see the earlier "ARSS Infrastructure Projects
bags work order" story that was live-confirmed getting wrongly `FILTERED`
in production) get through.

## Current state (grounded in the actual code)

- `app/filtering/heuristic.py::classify_category(title, content)` matches
  `title + content` against a fixed `CATEGORY_KEYWORDS` dict (5 buckets:
  `oil_energy`, `banking`, `auto_ev`, `geopolitics`, `market_news`) and
  returns the first matching bucket name, or `None`. `filter_new_articles`
  sets `status="FILTERED"` on `None`, else `status="CATEGORIZED"` with
  `article.category` set to that bucket name.
- `article.category` (the value the filter assigns) is **write-only** —
  confirmed by grep across the whole backend: the only two writes are this
  filter step and `pipeline.py:263`'s `_persist_alert`, which immediately
  overwrites it with the real LLM-derived category
  (`analysis.category`, from `app.analysis.schemas.CATEGORIES`, a richer
  taxonomy than the filter's 5 buckets). Nothing ever reads the filter-
  assigned value for any purpose. The filter's only real job is the
  admit/reject decision, not category labeling.
- `process_new_articles` (`app/pipeline.py:272`) calls
  `fetch_pending_full_text(session)`, then `filter_new_articles(session)`,
  then analyzes `CATEGORIZED` articles with the same `claude_client`
  object passed into `process_new_articles` itself.
- `article_text(article) -> str` (`app/pipeline.py`, added by the full-
  text-fetching sub-project) returns `article.full_content or
  article.content` — the existing, correct way to read an article's best
  available text anywhere it needs to reach an LLM call.
- `app/analysis/claude_client.py::FALLBACK_MODEL = "llama-3.1-8b-instant"`
  — a small, fast Groq model already wired into this app's `build_client`/
  `FallbackClient` machinery, used today only as a fallback when the
  primary analysis model is rate-limited. This design reuses it directly
  for classification (not as a fallback path — as the primary and only
  model for this specific, deliberately cheap task).
- `build_client(groq_api_keys, anthropic_api_key)` (`claude_client.py`)
  returns an OpenAI-compatible client object (`OpenAI`, `RotatingClient`,
  or `FallbackClient`) — the same object `process_new_articles` already
  holds as `claude_client` and uses for the real analysis call via
  `client.chat.completions.create(model=..., messages=..., ...)`.

## Design

### 1. New module, replaces `heuristic.py`

`app/filtering/relevance.py` (the old file is deleted, not kept — "no
longer a heuristic" is the whole point of this change):

```python
def classify_relevance(client, title: str, content: str) -> bool:
    """Ask a cheap, fast model whether this article could plausibly
    affect any financial/business/economic sector, directly or
    indirectly, anywhere. Never raises -- any failure (API error,
    unparseable response) fails OPEN (returns True, admit the article):
    silently dropping a real story is worse than one wasted downstream
    analysis call on a false positive.
    """
```

Prompt (single user message, no tool-use/schema needed — a plain yes/no
answer is all this call needs, kept deliberately cheap):

```
Does this news plausibly affect any financial, business, or economic
sector -- directly or indirectly -- anywhere in the world? Consider stock
markets, companies, government spending, infrastructure, policy, trade,
or the broader economy relevant. Answer with exactly one word: YES or NO.

Title: {title}

Content: {content}
```

Implementation: `client.chat.completions.create(model=FALLBACK_MODEL,
messages=[{"role": "user", "content": prompt}], max_tokens=5)` (imported
from `app.analysis.claude_client`, reusing the existing constant rather
than duplicating the model name) — `max_tokens=5` is enough for "YES"/"NO"
plus a little slack, keeping the call cheap and fast. Parse
`response.choices[0].message.content` case-insensitively: contains "yes"
→ `True`; anything else (including "no", empty, or a garbled response) →
`False`. Wrapped in a blanket `try/except Exception: return True` — the
fail-open contract, the one deliberate exception in this codebase to the
usual "degrade to a safe negative/empty" pattern, because here the safe
default is admit, not reject.

### 2. `filter_new_articles` signature change

```python
def filter_new_articles(session: Session, client) -> None:
    for article in session.query(Article).filter_by(status="NEW").all():
        if classify_relevance(client, article.title, article_text(article)):
            article.status = "CATEGORIZED"
        else:
            article.status = "FILTERED"
    session.commit()
```

`article.category` is no longer set here at all (confirmed dead — see
"Current state" above). `article_text` is imported from `app.pipeline`
(the same helper the main analysis call already uses) — classification
judges off the full scraped text when available, not just the short API
summary, for the same accuracy reason full-text-fetching was built in the
first place.

### 3. Wiring

In `app/pipeline.py`, the existing call `filter_new_articles(session)`
becomes `filter_new_articles(session, claude_client)` — `claude_client`
is already a parameter of `process_new_articles`, no new client
construction, no new settings/config needed.

## Explicitly out of scope

Broadening thenewsapi's `categories` query param to the full generic set
(sports, entertainment, health, science, food, travel) — this design
makes that safe to do, but actually changing the categories param is a
separate, later decision, not bundled into this sub-project. Sub-projects
3-4 of the roadmap (sector-cascade reasoning, regional company data /
company profiles) — each gets its own design cycle. Any caching/dedup of
repeated classification calls for near-duplicate articles — not needed at
current volume, and the existing `_find_reusable_alert` dedup-by-title
mechanism already short-circuits exact republish cases before they'd ever
reach this filter.

## Testing

`classify_relevance`: unit tests with a fake `client` object (mocking
`.chat.completions.create` the same way `test_claude_client.py` already
mocks LLM calls elsewhere in this codebase) covering: a "YES" response →
`True`, a "NO" response → `False`, mixed-case/whitespace tolerance, and —
the load-bearing case — an exception raised by the client degrades to
`True` (fail-open), not `False`. `filter_new_articles`: a `db_session`-
backed test seeding a few `NEW` articles, mocking `classify_relevance` to
return a mix of `True`/`False`, asserting each ends up `CATEGORIZED`/
`FILTERED` correctly and that `article.category` is never set. A
`process_new_articles`-level integration test confirming the real
`claude_client` object flows through to `filter_new_articles` unchanged
(same object identity, not a fresh client construction).
