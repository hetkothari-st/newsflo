"""Stage 1: network only. Pulls candidate articles from Wikipedia and
writes each one verbatim into a dated snapshot dir. No DB, no parsing
beyond what is needed to page through the API.

Like the universe fetchers, these RAISE rather than degrade: a source that
changed shape must fail before anything reaches the database.

Candidate pool = the two exchange-listing categories. That is a bounded,
already-curated set of ~900 articles. It is not the whole universe and is
not meant to be -- see the module docstring in __init__ for why a broader
name-driven search is the wrong lever. Coverage grows by an article gaining
an infobox, not by us guessing harder.
"""
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import certifi

from app.companies.descriptions import snapshot

API = "https://en.wikipedia.org/w/api.php"

# Wikipedia asks automated clients to identify themselves with a contact.
# An anonymous or browser-spoofing UA is against their robot policy and gets
# rate-limited hard.
HEADERS = {
    "User-Agent": "newsflo-universe/1.0 (https://github.com/newsflo; ainaman2512@gmail.com)",
    "Accept": "application/json",
}

LISTING_CATEGORIES = (
    "Category:Companies listed on the National Stock Exchange of India",
    "Category:Companies listed on the Bombay Stock Exchange",
)

# extracts caps at 20 titles per request regardless of what you ask for.
BATCH_SIZE = 20
THROTTLE_SECONDS = 0.4
# The search pass is one request per company over thousands of companies,
# where the batched page fetch is one request per twenty articles. Slower
# on purpose -- it is the only pass long enough for politeness to matter.
SEARCH_THROTTLE_SECONDS = 1.0
SEARCH_RESULTS_PER_COMPANY = 3


def fetch_bytes(url: str, timeout: int = 60) -> bytes:
    """Default transport. Tests inject a fake opener instead. certifi is
    required -- see CLAUDE.md on bare ssl.create_default_context."""
    request = urllib.request.Request(url, headers=HEADERS)
    context = ssl.create_default_context(cafile=certifi.where())
    return urllib.request.urlopen(request, timeout=timeout, context=context).read()


def _api(params: dict, opener=None) -> dict:
    fetch = opener or fetch_bytes
    params = {"format": "json", "formatversion": "2", **params}
    payload = fetch(f"{API}?{urllib.parse.urlencode(params)}")
    if not payload:
        raise ValueError("empty response from the Wikipedia API")
    data = json.loads(payload)
    if "error" in data:
        raise ValueError(f"Wikipedia API error: {data['error']}")
    return data


def fetch_category_titles(category: str, opener=None) -> list[str]:
    """Every mainspace article in ``category``, following continuations."""
    titles: list[str] = []
    continuation: dict = {}
    while True:
        data = _api(
            {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": category,
                "cmlimit": "500",
                "cmnamespace": "0",
                **continuation,
            },
            opener=opener,
        )
        members = data.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members)
        if "continue" not in data:
            break
        continuation = data["continue"]
        time.sleep(THROTTLE_SECONDS)
    return titles


def candidate_titles(opener=None) -> list[str]:
    """Union of the listing categories, order-stable and de-duplicated."""
    seen: dict[str, None] = {}
    for category in LISTING_CATEGORIES:
        for title in fetch_category_titles(category, opener=opener):
            seen.setdefault(title, None)
        time.sleep(THROTTLE_SECONDS)
    return list(seen)


def search_titles(query: str, opener=None) -> list[str]:
    """Top article titles for a free-text query.

    These are CANDIDATES, never answers. Wikipedia's search happily returns
    a plausible-looking article for a company it has never heard of, which
    is exactly the failure mode this subsystem exists to prevent -- so every
    hit still has to prove itself by carrying the company's own exchange
    code. The search only widens the pool; extract+loader still decide.
    """
    data = _api(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(SEARCH_RESULTS_PER_COMPANY),
            "srnamespace": "0",
        },
        opener=opener,
    )
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def search_for_companies(root: str, day: date, companies: list[tuple[str, str]],
                         opener=None, progress=None) -> list[str]:
    """Search Wikipedia for each ``(ticker, name)`` and return the union of
    candidate titles. Resumable per company: a ticker already searched today
    is read back off disk instead of re-queried."""
    already = snapshot.searched_tickers(root, day)
    titles: dict[str, None] = {}
    directory = snapshot.search_dir(root, day)
    directory.mkdir(parents=True, exist_ok=True)

    for index, (ticker, name) in enumerate(companies):
        path = snapshot.search_path(root, day, ticker)
        if ticker in already:
            try:
                for title in json.loads(path.read_text(encoding="utf-8")):
                    titles.setdefault(title, None)
            except (ValueError, OSError):
                pass  # unreadable cache entry: fall through and re-search
            else:
                continue
        try:
            hits = search_titles(name, opener=opener)
        except Exception:
            # One bad query must not end a multi-thousand-company pass. No
            # file is written, so a rerun retries this company.
            hits = None
        if hits is not None:
            path.write_text(json.dumps(hits, ensure_ascii=False), encoding="utf-8")
            for title in hits:
                titles.setdefault(title, None)
        if progress and index % 100 == 0:
            progress(index, len(companies))
        time.sleep(SEARCH_THROTTLE_SECONDS)
    return list(titles)


def _write_page(root: str, day: date, title: str, record: dict) -> Path:
    path = snapshot.page_path(root, day, title)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write via a temp file in the same directory, then replace. A torn JSON
    # file survives on disk and is silently skipped by every later run,
    # which looks identical to "this article has no infobox".
    temp = path.with_suffix(".json.part")
    temp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return path


def fetch_pages(root: str, day: date, titles: list[str], opener=None,
                progress=None) -> int:
    """Snapshot each title's wikitext and lead extract. Skips titles already
    on disk, so a rerun after an interruption resumes. Returns the number of
    pages newly written."""
    pending = [t for t in titles if t not in snapshot.fetched_titles(root, day)]
    written = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        data = _api(
            {
                "action": "query",
                "prop": "revisions|extracts",
                "rvprop": "content|ids|timestamp",
                "rvslots": "main",
                "exintro": "1",
                "explaintext": "1",
                "exlimit": str(BATCH_SIZE),
                "titles": "|".join(batch),
            },
            opener=opener,
        )
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            revision = revisions[0]
            _write_page(
                root,
                day,
                page["title"],
                {
                    "title": page["title"],
                    "pageid": page.get("pageid"),
                    "revid": revision.get("revid"),
                    "timestamp": revision.get("timestamp"),
                    "wikitext": revision.get("slots", {}).get("main", {}).get("content", ""),
                    "extract": page.get("extract", ""),
                },
            )
            written += 1
        if progress:
            progress(min(start + BATCH_SIZE, len(pending)), len(pending))
        time.sleep(THROTTLE_SECONDS)
    return written
