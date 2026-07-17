# Full Article Text Fetching — Design

## Goal

This is sub-project 1 of a 4-part insights-pipeline upgrade (full-text
fetching → relevance filter rework → sector-cascade reasoning → regional
company data / company profiles, in that order — see the parent brainstorm
for the full picture). The user's requested pipeline explicitly starts with
"the model/system should go through the entire news's text, entire news
basically with all the paragraphs etc it has" — but today, neither
ingestion source ever provides that. `app/ingestion/indianapi.py` stores
`content=item.get("summary", "")` (a one-line API summary), and the
disabled RSS poller (`app/ingestion/poller.py`) does the same
(`content=entry.get("summary", "")`). Every existing reasoning step —
filtering, sector inference, company resolution — has only ever seen a
one-line summary, never full article text. This blocks the rest of the
pipeline upgrade regardless of how good the reasoning prompt gets: you
cannot derive "the key factors are a hydrogen train and medical facility
projects" from a one-sentence summary that doesn't mention either.

## Current state (grounded in the actual code)

- `Article.content` (`app/models.py:50`) is `Column(Text, nullable=False,
  default="")` — currently always populated from the source API's short
  summary field, never scraped from the article's own page.
- A directly relevant precedent already exists: `app/ingestion/
  og_image.py::fetch_og_image(url)` scrapes the article's own page for its
  Open Graph/Twitter Card image, using `httpx.get(url, timeout=5.0,
  follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible;
  NewsFloBot/1.0)"})` wrapped in a blanket `try/except Exception: return
  None` — the "never raise, degrade to None" contract used throughout this
  codebase (see `outcomes/price_fetcher.py` for the same pattern elsewhere).
  This design's own fetcher follows that exact same shape.
- `fetch_og_image` is called from `_persist_alert`
  (`app/pipeline.py:254-255`), which only runs *after* an alert has already
  been created — i.e., only for articles that survived filtering and
  analysis and produced a real result. Full-text fetching has a different
  timing requirement (it must happen *before* analysis, since the analysis
  call needs the text as input) — these two fetches are not merged into one
  call site; they legitimately run at different pipeline stages.
- `process_new_articles` (`app/pipeline.py:267-328`) currently calls, in
  order: `filter_new_articles(session)`, then per-`CATEGORIZED` article,
  `analyze_article(claude_client, article.title, article.content)`.
- `Article.status` (`app/models.py:53`) is one of `NEW | FILTERED |
  CATEGORIZED | ANALYZED | ANALYSIS_FAILED`.

## Design

### 1. New fetcher module

`app/ingestion/full_text.py`:

```python
def fetch_full_text(url: str) -> str | None:
    """Fetch the article's own page and extract its main body text via
    trafilatura, or None on any failure (timeout, non-2xx, paywall,
    JS-rendered page trafilatura can't parse, no extractable content).
    Never raises -- same "degrade to None" contract as fetch_og_image.
    """
```

Implementation: `httpx.get(url, timeout=10.0, follow_redirects=True,
headers={"User-Agent": "Mozilla/5.0 (compatible; NewsFloBot/1.0)"})` (same
User-Agent string `fetch_og_image` already uses, same politeness
convention), then `trafilatura.extract(response.text)` — `trafilatura` is a
new dependency (added to `backend/requirements.txt` — actively maintained,
pure-Python, MIT-licensed content-extraction library that strips
nav/ads/boilerplate and keeps the article body). Wrapped in a blanket
`try/except Exception: return None`, matching `fetch_og_image` exactly.
10-second timeout (double `fetch_og_image`'s 5s) since text extraction
reads the full page body, not just `<head>` meta tags — a slower operation
that still needs a hard ceiling so one slow site never stalls the pipeline.

### 2. New `Article` column + one-shot retry guard

Two new nullable columns via the existing manual `_ADDED_COLUMNS` migration
list in `app/db.py` (no Alembic in this project):

```
("articles", "full_content", "TEXT"),
("articles", "full_content_fetch_attempted_at", "TIMESTAMP"),
```

`full_content`: the extracted text, or stays `NULL` if extraction never
succeeded. `full_content_fetch_attempted_at`: set the first time a fetch is
*attempted* for this article (success or failure) — a permanently
unreachable URL (dead link, hard paywall) must not get re-scraped every
pipeline cycle forever. The fetch stage only attempts a URL once: query
`Article.filter_by(status="NEW").filter(Article.full_content_fetch_attempted_at.is_(None))`.

### 3. New pipeline stage, running before the filter

New function in `app/ingestion/full_text.py`:

```python
def fetch_pending_full_text(session: Session) -> None:
    """For every NEW article that hasn't had a fetch attempt yet, try once
    to fetch and extract its full body text. Always marks the attempt
    timestamp regardless of success, so a failing URL is never retried.
    Commits per-article (not batched) so a mid-run crash doesn't lose
    already-fetched articles.
    """
```

Iterates `NEW` articles with `full_content_fetch_attempted_at IS NULL`,
calls `fetch_full_text(article.url)`, sets `article.full_content` (if
non-None) and always sets `article.full_content_fetch_attempted_at =
utcnow()`, commits after each article.

`process_new_articles` (`app/pipeline.py`) calls this as its very first
step, before `filter_new_articles(session)` — per the user's explicit
choice, full text is fetched for *every* new article before filtering, not
only for articles a filter has already admitted, so the (upcoming,
sub-project-2) relevance check also judges off real article text instead
of a thin summary.

### 4. Every text consumer prefers `full_content`, falls back to `content`

A small helper, `article_text(article: Article) -> str`, added alongside
the other small helpers in `app/pipeline.py`:

```python
def article_text(article: Article) -> str:
    return article.full_content or article.content
```

`process_new_articles`'s `analyze_article(claude_client, article.title,
article.content)` call becomes `analyze_article(claude_client,
article.title, article_text(article))`. `filter_new_articles`'s
classification call (built in sub-project 2) uses the same helper. This is
purely additive: an article whose scrape failed falls straight back to
today's existing summary-only behavior — no regression.

## Explicitly out of scope

Sub-projects 2-4 of the roadmap (relevance-filter rework, sector-cascade
reasoning, regional company data / company profiles) — each gets its own
design cycle. Retrying a failed fetch more than once, or on a longer
backoff schedule, is out of scope for this first pass — "attempt once,
degrade to summary-only forever" is the simplest correct behavior and can
be revisited if a large fraction of sources turn out to be unreachable in
practice. Deduplicating the `fetch_og_image`/`fetch_full_text` HTTP calls
into one shared fetch is also out of scope — they run at genuinely
different pipeline stages (before vs. after analysis) for different
subsets of articles, so merging them would change which articles get an
og:image fetch at all.

## Testing

`fetch_full_text`: unit tests mocking `httpx.get` for the timeout/non-2xx/
malformed-HTML-with-no-extractable-content cases (all degrade to `None`),
and one success case with a fixed HTML fixture asserting the extracted
text matches expectations. `fetch_pending_full_text`: a `db_session`-backed
test seeding a few `NEW` articles, mocking `fetch_full_text` to return a
mix of text/`None`, asserting `full_content` and
`full_content_fetch_attempted_at` end up correct for each, and a second
call over the same articles asserts `fetch_full_text` is NOT called again
(the one-shot guard holds). `article_text`: trivial unit tests for the
`full_content or content` fallback. A `process_new_articles`-level
integration test confirming `analyze_article` is actually invoked with the
fetched full text (not the summary) when a fetch succeeded.
