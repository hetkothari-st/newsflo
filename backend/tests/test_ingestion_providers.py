"""Per-provider fetch()/normalize() contract tests. Each provider's
normalize is pure (no DB, no network), so these run against plain dicts;
fetch() tests monkeypatch httpx.get exactly the way the legacy
test_finnhub.py did."""
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.ingestion.providers.base import Checkpoint
from app.ingestion.providers.benzinga import BenzingaProvider
from app.ingestion.providers.bse import BseAnnouncementsProvider
from app.ingestion.providers.finnhub import FinnhubProvider
from app.ingestion.providers.gdelt import GdeltProvider
from app.ingestion.providers.indianapi import IndianApiProvider
from app.ingestion.providers.marketaux import MarketauxProvider
from app.ingestion.providers.registry import _PROVIDERS, PROVIDER_REGISTRY
from app.ingestion.providers.rss import NseAnnouncementsProvider, RssProvider


def _response(json_payload, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: json_payload)


# --- registry sanity ---

def test_registry_slugs_are_unique_and_match_providers():
    # The dict comprehension building PROVIDER_REGISTRY silently swallows a
    # duplicate slug -- equal lengths proves no collision happened.
    assert len(PROVIDER_REGISTRY) == len(_PROVIDERS)
    for slug, provider in PROVIDER_REGISTRY.items():
        assert provider.slug == slug
        assert provider.display_name
        assert provider.default_poll_interval_minutes >= 1
        assert provider.max_items_per_poll >= 1


# --- Finnhub (migrated -- field mapping preserved from the legacy fetcher) ---

def test_finnhub_normalize_field_mapping():
    article = FinnhubProvider().normalize({
        "headline": "Reliance Industries Q1 Results Live",
        "summary": "RIL Q1FY27 results announced today.",
        "url": "https://www.livemint.com/market/ril-q1-results",
        "image": "https://www.livemint.com/img/ril.jpg",
        "datetime": int(datetime(2026, 7, 20, 5, 13, tzinfo=timezone.utc).timestamp()),
        "source": "livemint.com",
        "id": 99,
    })
    assert article.source == "livemint.com"
    assert article.title == "Reliance Industries Q1 Results Live"
    assert article.content == "RIL Q1FY27 results announced today."
    assert article.published_at.hour == 5 and article.published_at.minute == 13
    assert article.provider_article_id == "99"


def test_finnhub_normalize_empty_image_to_none():
    # Finnhub returns "image": "" (present, empty) -- must normalize to None
    # so pipeline.py's og:image fallback still triggers.
    assert FinnhubProvider().normalize({"url": "https://x.com/a", "image": ""}).image_url is None


def test_finnhub_normalize_source_fallback_and_missing_url():
    provider = FinnhubProvider()
    assert provider.normalize({"url": "https://x.com/a", "source": None}).source == "finnhub"
    assert provider.normalize({"headline": "no url"}) is None


def test_finnhub_fetch_one_category_failure_never_blocks_the_other(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if params["category"] == "general":
            raise httpx.TimeoutException("connect timeout")
        return _response([{"url": "https://x.com/a"}])

    monkeypatch.setattr("app.ingestion.providers.finnhub.httpx.get", fake_get)
    monkeypatch.setattr("app.ingestion.providers.finnhub.settings.finnhub_api_key", "k")

    assert FinnhubProvider().fetch(Checkpoint()) == [{"url": "https://x.com/a"}]


def test_finnhub_fetch_raises_when_every_category_fails(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise httpx.TimeoutException("down")

    monkeypatch.setattr("app.ingestion.providers.finnhub.httpx.get", fake_get)
    monkeypatch.setattr("app.ingestion.providers.finnhub.settings.finnhub_api_key", "k")

    with pytest.raises(httpx.TimeoutException):
        FinnhubProvider().fetch(Checkpoint())


# --- IndianAPI (migrated -- IST pub_date handling preserved) ---

def test_indianapi_normalize_ist_pub_date_converts_to_utc():
    article = IndianApiProvider().normalize({
        "url": "https://x.com/a", "title": "t", "pub_date": "2026-07-17T10:43:00",
    })
    assert article.published_at == datetime(2026, 7, 17, 5, 13, tzinfo=timezone.utc)


def test_indianapi_fetch_raises_on_non_list_payload(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.providers.indianapi.httpx.get",
        lambda url, headers=None, timeout=None: _response({"error": "bad key"}),
    )
    monkeypatch.setattr("app.ingestion.providers.indianapi.settings.indianapi_api_key", "k")

    with pytest.raises(ValueError):
        IndianApiProvider().fetch(Checkpoint())


# --- Marketaux ---

def test_marketaux_fetch_sends_checkpoint_as_published_after(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured.update(params)
        return _response({"data": []})

    monkeypatch.setattr("app.ingestion.providers.marketaux.httpx.get", fake_get)
    monkeypatch.setattr("app.ingestion.providers.marketaux.settings.marketaux_api_key", "k")

    MarketauxProvider().fetch(Checkpoint(cursor="2026-08-10T11:58:00"))

    assert captured["published_after"] == "2026-08-10T11:58:00"
    assert captured["limit"] == 3


def test_marketaux_checkpoint_advances_with_overlap_from_data_not_wall_clock():
    provider = MarketauxProvider()
    items = [
        {"published_at": "2026-08-10T12:00:00.000000Z"},
        {"published_at": "2026-08-10T11:30:00.000000Z"},
    ]
    checkpoint = provider.next_checkpoint(items, Checkpoint(cursor="old"))
    # max(published) 12:00 minus the 2-minute overlap window.
    assert checkpoint.cursor == "2026-08-10T11:58:00"


def test_marketaux_empty_poll_never_advances_the_checkpoint():
    previous = Checkpoint(cursor="2026-08-10T11:00:00")
    assert MarketauxProvider().next_checkpoint([], previous) is previous


def test_marketaux_normalize_prefers_description_and_keeps_uuid():
    article = MarketauxProvider().normalize({
        "uuid": "u-1", "url": "https://x.com/a", "title": "t",
        "description": "standfirst", "snippet": "trunc",
        "published_at": "2026-08-10T07:21:22.000000Z", "source": "retailgazette.co.uk",
    })
    assert article.content == "standfirst"
    assert article.provider_article_id == "u-1"
    assert article.published_at.tzinfo is not None


# --- Benzinga ---

def test_benzinga_normalize_parses_rfc2822_created_and_picks_large_image():
    article = BenzingaProvider().normalize({
        "id": 61065901,
        "title": "Apple Tests Chips",
        "teaser": "teaser text",
        "body": "",
        "url": "https://www.benzinga.com/a",
        "created": "Mon, 10 Aug 2026 03:15:36 -0400",
        "image": [
            {"size": "thumb", "url": "https://cdn/th.jpg"},
            {"size": "large", "url": "https://cdn/lg.jpg"},
        ],
    })
    assert article.provider_article_id == "61065901"
    assert article.content == "teaser text"  # empty body falls back to teaser
    assert article.image_url == "https://cdn/lg.jpg"
    assert article.published_at.astimezone(timezone.utc).hour == 7


# --- GDELT ---

def test_gdelt_normalize_drops_non_english_and_parses_seendate():
    provider = GdeltProvider()
    assert provider.normalize({"url": "https://x.com/a", "language": "Hindi"}) is None
    article = provider.normalize({
        "url": "https://x.com/a", "title": "t", "language": "English",
        "seendate": "20260810T121500Z", "domain": "reuters.com",
    })
    assert article.source == "reuters.com"
    assert article.content == ""  # artlist has no body; full_text stage scrapes
    assert article.published_at == datetime(2026, 8, 10, 12, 15, tzinfo=timezone.utc)


def test_gdelt_fetch_treats_throttle_text_on_both_queries_as_failure(monkeypatch):
    # GDELT answers over-rate requests with HTTP 200 + plain text -- the
    # json() ValueError on BOTH queries must surface to the breaker.
    def fake_get(url, params=None, timeout=None):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: (_ for _ in ()).throw(ValueError("not json")))

    monkeypatch.setattr("app.ingestion.providers.gdelt.httpx.get", fake_get)
    monkeypatch.setattr("app.ingestion.providers.gdelt.time.sleep", lambda s: None)

    with pytest.raises(ValueError):
        GdeltProvider().fetch(Checkpoint())


# --- BSE ---

def test_bse_normalize_synthesizes_url_and_parses_lodr_category():
    article = BseAnnouncementsProvider().normalize({
        "NEWSID": "5bfca22c-e5d6",
        "NEWSSUB": "B&A Packaging India Ltd - 523186 - Announcement under Regulation 30 (LODR)-Newspaper Publication",
        "HEADLINE": "Pursuant to Regulation 47...",
        "NEWS_DT": "2026-08-10T13:06:50.813",
    })
    assert article.url == "https://www.bseindia.com/corporates/anndet_new.aspx?newsid=5bfca22c-e5d6"
    assert article.provider_article_id == "5bfca22c-e5d6"
    assert article.source_category == "Newspaper Publication"
    # 13:06 IST == 07:36 UTC
    assert article.published_at == datetime(2026, 8, 10, 7, 36, 50, 813000, tzinfo=timezone.utc)


def test_bse_fetch_raises_on_status_false_rejection(monkeypatch):
    # BSE rejects with HTTP 200 + {"Status": false} -- must be a hard
    # failure, not an empty poll (app/companies/supply_links/fetchers.py
    # pinned this quirk).
    monkeypatch.setattr(
        "app.ingestion.providers.bse.httpx.get",
        lambda url, params=None, headers=None, timeout=None: _response(
            {"Status": False, "Message": "Date range exceeded threshold."}
        ),
    )
    with pytest.raises(ValueError, match="rejected"):
        BseAnnouncementsProvider().fetch(Checkpoint())


# --- RSS / NSE ---

_NSE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>NSE News</title>
<item>
<title>United Drilling Tools Limited</title>
<link>https://nsearchives.nseindia.com/corporate/UNIDT_x.pdf</link>
<description>United Drilling Tools Limited has informed the Exchange about Awarding of order(s)/contract(s) |SUBJECT: Awarding of order(s)/contract(s)</description>
<pubDate>10-Aug-2026 11:56:52</pubDate>
</item>
<item>
<title>ICICI Prudential Nifty 50 ETF</title>
<link/>
<description>NAV as on August 07, 2026 is Rs. 278.7073. |SUBJECT: Declaration of NAV</description>
<pubDate>10-Aug-2026 12:07:00</pubDate>
</item>
</channel></rss>"""


def _nse_provider():
    return NseAnnouncementsProvider(
        slug="nse", display_name="NSE", source_name="nse", feed_url="https://nse.example/rss",
    )


def test_nse_fetch_and_normalize_extracts_subject_and_ist_pubdate(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.providers.rss.httpx.get",
        lambda url, timeout=None, follow_redirects=None, headers=None: SimpleNamespace(
            content=_NSE_FEED, raise_for_status=lambda: None,
        ),
    )
    provider = _nse_provider()
    items = provider.fetch(Checkpoint())
    normalized = [provider.normalize(item) for item in items]

    article = normalized[0]
    assert article.title.startswith("United Drilling Tools Limited: ")
    assert "|SUBJECT:" not in article.title and "|SUBJECT:" not in article.content
    assert article.source_category == "Awarding of order(s)/contract(s)"
    # 11:56:52 IST == 06:26:52 UTC
    assert article.published_at == datetime(2026, 8, 10, 6, 26, 52, tzinfo=timezone.utc)
    # Linkless NAV item: nothing to dedup or link to -- dropped.
    assert normalized[1] is None


def test_rss_fetch_raises_on_unparseable_feed(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.providers.rss.httpx.get",
        lambda url, timeout=None, follow_redirects=None, headers=None: SimpleNamespace(
            content=b"<html>not a feed", raise_for_status=lambda: None,
        ),
    )
    provider = RssProvider(slug="pib", display_name="PIB", source_name="pib", feed_url="https://pib.example/rss")
    with pytest.raises(ValueError, match="unparseable"):
        provider.fetch(Checkpoint())


def test_rss_normalize_maps_link_title_summary():
    provider = RssProvider(slug="rbi", display_name="RBI", source_name="rbi", feed_url="https://rbi.example/rss")
    article = provider.normalize({"link": "https://rbi.org.in/pr/1", "title": "Repo unchanged", "summary": "MPC held."})
    assert article.source == "rbi"
    assert article.url == "https://rbi.org.in/pr/1"
    assert article.title == "Repo unchanged"
    assert provider.normalize({"title": "no link"}) is None
