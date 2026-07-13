from types import SimpleNamespace

import httpx

from app.ingestion.poller import fetch_new_articles


def _fake_httpx_get(response_content=b"<rss></rss>", raise_error=None):
    def fake_get(url, timeout=None, follow_redirects=None):
        if raise_error is not None:
            raise raise_error
        return SimpleNamespace(content=response_content, raise_for_status=lambda: None)
    return fake_get


def test_fetch_new_articles_inserts_and_dedupes(db_session, monkeypatch):
    feed_entries = [
        {"link": "https://example.com/a", "title": "Story A", "summary": "..."},
        {"link": "https://example.com/a", "title": "Story A duplicate", "summary": "..."},
    ]

    monkeypatch.setattr("app.ingestion.poller.httpx.get", _fake_httpx_get())
    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", lambda content: SimpleNamespace(entries=feed_entries))

    feeds = [{"source": "test_source", "url": "http://feed.test/rss"}]

    inserted = fetch_new_articles(db_session, feeds)
    assert inserted == 1

    inserted_again = fetch_new_articles(db_session, feeds)
    assert inserted_again == 0


def test_fetch_new_articles_skips_entries_without_link(db_session, monkeypatch):
    monkeypatch.setattr("app.ingestion.poller.httpx.get", _fake_httpx_get())
    monkeypatch.setattr(
        "app.ingestion.poller.feedparser.parse",
        lambda content: SimpleNamespace(entries=[{"title": "No link here", "summary": ""}]),
    )

    inserted = fetch_new_articles(db_session, [{"source": "test_source", "url": "http://feed.test/rss"}])
    assert inserted == 0


def test_fetch_new_articles_skips_a_feed_that_times_out_without_blocking_others(db_session, monkeypatch):
    # The bug that caused this fix: feedparser.parse(url) fetching the URL
    # itself has no timeout and can hang forever. A slow/unreachable feed
    # must be skipped (not hang, not crash the whole poll cycle) so the
    # OTHER feeds in the same cycle still get polled.
    calls = {"n": 0}

    def fake_get(url, timeout=None, follow_redirects=None):
        calls["n"] += 1
        if url == "http://slow-feed.test/rss":
            raise httpx.TimeoutException("connect timeout")
        return SimpleNamespace(content=b"<rss></rss>", raise_for_status=lambda: None)

    monkeypatch.setattr("app.ingestion.poller.httpx.get", fake_get)
    monkeypatch.setattr(
        "app.ingestion.poller.feedparser.parse",
        lambda content: SimpleNamespace(entries=[{"link": "https://example.com/ok", "title": "OK story", "summary": ""}]),
    )

    feeds = [
        {"source": "slow", "url": "http://slow-feed.test/rss"},
        {"source": "ok", "url": "http://ok-feed.test/rss"},
    ]

    inserted = fetch_new_articles(db_session, feeds)

    assert calls["n"] == 2  # both feeds were attempted
    assert inserted == 1  # only the working feed's article was inserted


def test_fetch_new_articles_skips_a_feed_that_returns_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.poller.httpx.get",
        _fake_httpx_get(raise_error=httpx.HTTPStatusError("500", request=None, response=None)),
    )
    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", lambda content: (_ for _ in ()).throw(AssertionError("should not parse")))

    inserted = fetch_new_articles(db_session, [{"source": "test_source", "url": "http://feed.test/rss"}])
    assert inserted == 0
