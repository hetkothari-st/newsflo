from types import SimpleNamespace

from app.ingestion.poller import fetch_new_articles


def test_fetch_new_articles_inserts_and_dedupes(db_session, monkeypatch):
    feed_entries = [
        {"link": "https://example.com/a", "title": "Story A", "summary": "..."},
        {"link": "https://example.com/a", "title": "Story A duplicate", "summary": "..."},
    ]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    feeds = [{"source": "test_source", "url": "http://feed.test/rss"}]

    inserted = fetch_new_articles(db_session, feeds)
    assert inserted == 1

    inserted_again = fetch_new_articles(db_session, feeds)
    assert inserted_again == 0


def test_fetch_new_articles_skips_entries_without_link(db_session, monkeypatch):
    def fake_parse(url):
        return SimpleNamespace(entries=[{"title": "No link here", "summary": ""}])

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_source", "url": "http://feed.test/rss"}])
    assert inserted == 0
