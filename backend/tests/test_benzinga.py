from types import SimpleNamespace

import httpx

from app.ingestion.benzinga import fetch_new_benzinga_articles
from app.models import Article


def _fake_response(json_body, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: json_body)


def _item(**overrides):
    item = {
        "url": "https://www.benzinga.com/markets/a",
        "title": "Story A",
        "teaser": "short summary",
        "body": "<p>Full <strong>story</strong> text.</p>",
        "created": "Fri, 17 Jul 2026 03:10:30 -0400",
        "image": [
            {"size": "thumb", "url": "https://cdn.benzinga.com/thumb.jpg"},
            {"size": "small", "url": "https://cdn.benzinga.com/small.jpg"},
            {"size": "large", "url": "https://cdn.benzinga.com/large.jpg"},
        ],
    }
    item.update(overrides)
    return item


def test_fetch_new_benzinga_articles_inserts_and_dedupes(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.benzinga.httpx.get",
        lambda url, params=None, headers=None, timeout=None: _fake_response([_item()]),
    )

    inserted = fetch_new_benzinga_articles(db_session, "fake-key")
    assert inserted == 1

    article = db_session.query(Article).one()
    assert article.source == "benzinga"
    assert article.url == "https://www.benzinga.com/markets/a"
    assert article.title == "Story A"
    # HTML stripped down to plain text.
    assert article.content == "Full story text."
    assert article.image_url == "https://cdn.benzinga.com/small.jpg"
    assert article.published_at is not None
    assert article.status == "NEW"

    inserted_again = fetch_new_benzinga_articles(db_session, "fake-key")
    assert inserted_again == 0


def test_fetch_new_benzinga_articles_falls_back_to_teaser_when_body_is_empty(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.benzinga.httpx.get",
        lambda url, params=None, headers=None, timeout=None: _fake_response([_item(body="")]),
    )

    fetch_new_benzinga_articles(db_session, "fake-key")

    assert db_session.query(Article).one().content == "short summary"


def test_fetch_new_benzinga_articles_skips_items_without_url(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.benzinga.httpx.get",
        lambda url, params=None, headers=None, timeout=None: _fake_response([_item(url=None)]),
    )

    assert fetch_new_benzinga_articles(db_session, "fake-key") == 0


def test_fetch_new_benzinga_articles_returns_zero_without_an_api_key(db_session, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr("app.ingestion.benzinga.httpx.get", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

    assert fetch_new_benzinga_articles(db_session, "") == 0
    assert called["n"] == 0  # never even attempted the request


def test_fetch_new_benzinga_articles_swallows_a_request_failure(db_session, monkeypatch):
    def raise_timeout(url, params=None, headers=None, timeout=None):
        raise httpx.TimeoutException("connect timeout")

    monkeypatch.setattr("app.ingestion.benzinga.httpx.get", raise_timeout)

    assert fetch_new_benzinga_articles(db_session, "fake-key") == 0


def test_fetch_new_benzinga_articles_swallows_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.benzinga.httpx.get",
        lambda url, params=None, headers=None, timeout=None: _fake_response([_item()], status_ok=False),
    )

    assert fetch_new_benzinga_articles(db_session, "fake-key") == 0


def test_fetch_new_benzinga_articles_swallows_a_non_list_response(db_session, monkeypatch):
    # e.g. an error payload like {"error": "invalid token"} instead of a list.
    monkeypatch.setattr(
        "app.ingestion.benzinga.httpx.get",
        lambda url, params=None, headers=None, timeout=None: _fake_response({"error": "invalid token"}),
    )

    assert fetch_new_benzinga_articles(db_session, "bad-key") == 0
