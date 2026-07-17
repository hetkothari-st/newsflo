from types import SimpleNamespace

import httpx

from app.ingestion.indianapi import fetch_new_indianapi_articles
from app.models import Article


def _fake_response(json_body, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: json_body)


def _item(**overrides):
    item = {
        "title": "Reliance Industries Q1 Results Live",
        "summary": "RIL Q1FY27 results announced today.",
        "url": "https://www.livemint.com/market/ril-q1-results",
        "image_url": "https://www.livemint.com/img/ril.jpg",
        "pub_date": "2026-07-17T10:43:00",
        "source": "Live Mint",
        "topics": ["Financial Results"],
    }
    item.update(overrides)
    return item


def test_fetch_new_indianapi_articles_inserts_and_dedupes(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.indianapi.httpx.get",
        lambda url, headers=None, timeout=None: _fake_response([_item()]),
    )

    inserted = fetch_new_indianapi_articles(db_session, "fake-key")
    assert inserted == 1

    article = db_session.query(Article).one()
    assert article.source == "Live Mint"
    assert article.url == "https://www.livemint.com/market/ril-q1-results"
    assert article.title == "Reliance Industries Q1 Results Live"
    assert article.content == "RIL Q1FY27 results announced today."
    assert article.image_url == "https://www.livemint.com/img/ril.jpg"
    assert article.status == "NEW"
    # 2026-07-17T10:43:00 IST (no offset in the source) == 05:13:00 UTC.
    assert article.published_at.hour == 5
    assert article.published_at.minute == 13

    inserted_again = fetch_new_indianapi_articles(db_session, "fake-key")
    assert inserted_again == 0


def test_fetch_new_indianapi_articles_falls_back_to_generic_source_name(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.indianapi.httpx.get",
        lambda url, headers=None, timeout=None: _fake_response([_item(source=None)]),
    )

    fetch_new_indianapi_articles(db_session, "fake-key")

    assert db_session.query(Article).one().source == "indianapi"


def test_fetch_new_indianapi_articles_skips_items_without_url(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.indianapi.httpx.get",
        lambda url, headers=None, timeout=None: _fake_response([_item(url=None)]),
    )

    assert fetch_new_indianapi_articles(db_session, "fake-key") == 0


def test_fetch_new_indianapi_articles_returns_zero_without_an_api_key(db_session, monkeypatch):
    # Load-bearing: this key is capped at 500 requests/month -- a missing
    # key must never silently fall through to an unauthenticated call.
    called = {"n": 0}
    monkeypatch.setattr("app.ingestion.indianapi.httpx.get", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

    assert fetch_new_indianapi_articles(db_session, "") == 0
    assert called["n"] == 0


def test_fetch_new_indianapi_articles_swallows_a_request_failure(db_session, monkeypatch):
    def raise_timeout(url, headers=None, timeout=None):
        raise httpx.TimeoutException("connect timeout")

    monkeypatch.setattr("app.ingestion.indianapi.httpx.get", raise_timeout)

    assert fetch_new_indianapi_articles(db_session, "fake-key") == 0


def test_fetch_new_indianapi_articles_swallows_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.indianapi.httpx.get",
        lambda url, headers=None, timeout=None: _fake_response([_item()], status_ok=False),
    )

    assert fetch_new_indianapi_articles(db_session, "fake-key") == 0


def test_fetch_new_indianapi_articles_swallows_a_non_list_response(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.indianapi.httpx.get",
        lambda url, headers=None, timeout=None: _fake_response({"error": "invalid api key"}),
    )

    assert fetch_new_indianapi_articles(db_session, "bad-key") == 0
