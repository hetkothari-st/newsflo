from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingestion.finnhub import fetch_new_finnhub_articles
from app.models import Article


def _fake_response(items, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: items)


def _item(**overrides):
    item = {
        "headline": "Reliance Industries Q1 Results Live",
        "summary": "RIL Q1FY27 results announced today.",
        "url": "https://www.livemint.com/market/ril-q1-results",
        "image": "https://www.livemint.com/img/ril.jpg",
        "datetime": int(datetime(2026, 7, 20, 5, 13, tzinfo=timezone.utc).timestamp()),
        "source": "livemint.com",
        "category": "general",
    }
    item.update(overrides)
    return item


def _autoflush_false_session():
    # Mirrors app/db.py's production SessionLocal (autoflush=False) --
    # tests/conftest.py's db_session fixture uses plain sessionmaker()
    # (autoflush=True by default), which would NOT catch a cross-category
    # dedup bug the way production actually behaves. Use this dedicated
    # session for any test that exercises dedup across the two category
    # requests within one fetch_new_finnhub_articles call.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    return Session()


def test_fetch_new_finnhub_articles_inserts_and_dedupes(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()]),
    )

    inserted = fetch_new_finnhub_articles(db_session, "fake-key")
    # Same item returned for both "general" and "merger" categories in this
    # fake -- dedup must collapse it to 1, not insert twice.
    assert inserted == 1

    article = db_session.query(Article).one()
    assert article.source == "livemint.com"
    assert article.url == "https://www.livemint.com/market/ril-q1-results"
    assert article.title == "Reliance Industries Q1 Results Live"
    assert article.content == "RIL Q1FY27 results announced today."
    assert article.image_url == "https://www.livemint.com/img/ril.jpg"
    assert article.status == "NEW"
    assert article.published_at.hour == 5
    assert article.published_at.minute == 13

    inserted_again = fetch_new_finnhub_articles(db_session, "fake-key")
    assert inserted_again == 0


def test_fetch_new_finnhub_articles_dedupes_same_url_across_categories_under_autoflush_false():
    session = _autoflush_false_session()
    try:
        import app.ingestion.finnhub as finnhub_module
        orig_get = finnhub_module.httpx.get
        finnhub_module.httpx.get = lambda url, params=None, timeout=None: _fake_response([_item()])
        try:
            inserted = fetch_new_finnhub_articles(session, "fake-key")
        finally:
            finnhub_module.httpx.get = orig_get
        assert inserted == 1
        assert session.query(Article).count() == 1
    finally:
        session.close()


def test_fetch_new_finnhub_articles_calls_both_categories(db_session, monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["category"])
        return _fake_response([])

    monkeypatch.setattr("app.ingestion.finnhub.httpx.get", fake_get)
    fetch_new_finnhub_articles(db_session, "fake-key")

    assert calls == ["general", "merger"]


def test_fetch_new_finnhub_articles_falls_back_to_generic_source_name(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(source=None)]),
    )

    fetch_new_finnhub_articles(db_session, "fake-key")

    assert db_session.query(Article).one().source == "finnhub"


def test_fetch_new_finnhub_articles_skips_items_without_url(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(url=None)]),
    )

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 0


def test_fetch_new_finnhub_articles_returns_zero_without_an_api_key(db_session, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )

    assert fetch_new_finnhub_articles(db_session, "") == 0
    assert called["n"] == 0


def test_fetch_new_finnhub_articles_swallows_one_category_failure_without_blocking_other(db_session, monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if params["category"] == "general":
            raise httpx.TimeoutException("connect timeout")
        return _fake_response([_item()])

    monkeypatch.setattr("app.ingestion.finnhub.httpx.get", fake_get)

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 1


def test_fetch_new_finnhub_articles_swallows_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()], status_ok=False),
    )

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 0


def test_fetch_new_finnhub_articles_swallows_a_malformed_response(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"error": "invalid api key"},
        ),
    )

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 0
