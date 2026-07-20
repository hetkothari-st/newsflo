from types import SimpleNamespace

import httpx

from app.ingestion.thenewsapi import fetch_new_thenewsapi_articles
from app.models import Article


def _fake_response(data, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    body = {"meta": {"found": len(data), "returned": len(data), "limit": 3, "page": 1}, "data": data}
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: body)


def _item(**overrides):
    item = {
        "title": "Reliance Industries Q1 Results Live",
        "description": "RIL Q1FY27 results announced today.",
        "url": "https://www.livemint.com/market/ril-q1-results",
        "image_url": "https://www.livemint.com/img/ril.jpg",
        "published_at": "2026-07-20T05:13:00.000000Z",
        "source": "livemint.com",
    }
    item.update(overrides)
    return item


def test_fetch_new_thenewsapi_articles_inserts_and_dedupes(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()]),
    )

    inserted = fetch_new_thenewsapi_articles(db_session, "fake-token")
    assert inserted == 1

    article = db_session.query(Article).one()
    assert article.source == "livemint.com"
    assert article.url == "https://www.livemint.com/market/ril-q1-results"
    assert article.title == "Reliance Industries Q1 Results Live"
    assert article.content == "RIL Q1FY27 results announced today."
    assert article.image_url == "https://www.livemint.com/img/ril.jpg"
    assert article.status == "NEW"
    # 2026-07-20T05:13:00.000000Z is already UTC -- no offset inference needed.
    assert article.published_at.hour == 5
    assert article.published_at.minute == 13

    inserted_again = fetch_new_thenewsapi_articles(db_session, "fake-token")
    assert inserted_again == 0


def test_fetch_new_thenewsapi_articles_falls_back_to_generic_source_name(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(source=None)]),
    )

    fetch_new_thenewsapi_articles(db_session, "fake-token")

    assert db_session.query(Article).one().source == "thenewsapi"


def test_fetch_new_thenewsapi_articles_skips_items_without_url(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(url=None)]),
    )

    assert fetch_new_thenewsapi_articles(db_session, "fake-token") == 0


def test_fetch_new_thenewsapi_articles_returns_zero_without_an_api_token(db_session, monkeypatch):
    # Load-bearing: free tier is capped at 100 requests/day -- a missing
    # token must never silently fall through to a wasted call.
    called = {"n": 0}
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )

    assert fetch_new_thenewsapi_articles(db_session, "") == 0
    assert called["n"] == 0


def test_fetch_new_thenewsapi_articles_swallows_a_request_failure(db_session, monkeypatch):
    def raise_timeout(url, params=None, timeout=None):
        raise httpx.TimeoutException("connect timeout")

    monkeypatch.setattr("app.ingestion.thenewsapi.httpx.get", raise_timeout)

    assert fetch_new_thenewsapi_articles(db_session, "fake-token") == 0


def test_fetch_new_thenewsapi_articles_swallows_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()], status_ok=False),
    )

    assert fetch_new_thenewsapi_articles(db_session, "fake-token") == 0


def test_fetch_new_thenewsapi_articles_swallows_a_malformed_response(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"error": "invalid api key"},
        ),
    )

    assert fetch_new_thenewsapi_articles(db_session, "bad-token") == 0
