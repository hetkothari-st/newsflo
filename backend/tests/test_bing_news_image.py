from types import SimpleNamespace

from app.ingestion.bing_news_image import _title_overlap, fetch_bing_news_image
from app.ingestion.image_filter import resolve_article_image

_RSS = """<rss><channel>
<item>
<title>QatarEnergy buys 33 US LNG cargoes to offset Hormuz disruption: Source</title>
<News:Image>http://www.bing.com/th?id=ONUT.ABC&amp;pid=News</News:Image>
</item>
<item>
<title>Qatar Stock Exchange</title>
</item>
</channel></rss>"""


def _fake_get(text: str, status_code: int = 200):
    def get(url, params=None, timeout=None, follow_redirects=None, headers=None):
        response = SimpleNamespace(text=text, status_code=status_code)
        response.raise_for_status = lambda: None
        return response
    return get


def test_returns_https_sized_image_for_matching_headline(monkeypatch):
    monkeypatch.setattr("app.ingestion.bing_news_image.httpx.get", _fake_get(_RSS))
    result = fetch_bing_news_image("QatarEnergy buys 33 US LNG cargoes")
    assert result == "https://www.bing.com/th?id=ONUT.ABC&pid=News&w=800&h=450&c=14"


def test_rejects_result_whose_title_does_not_match(monkeypatch):
    # A wrong photo is worse than no photo -- low token overlap -> None.
    monkeypatch.setattr("app.ingestion.bing_news_image.httpx.get", _fake_get(_RSS))
    assert fetch_bing_news_image("Completely unrelated banking headline today") is None


def test_returns_none_on_network_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("no route")
    monkeypatch.setattr("app.ingestion.bing_news_image.httpx.get", boom)
    assert fetch_bing_news_image("QatarEnergy buys 33 US LNG cargoes") is None


def test_title_overlap_ignores_stopwords():
    assert _title_overlap("The rise of the machines", "Rise machines everywhere") == 1.0


def test_resolve_falls_back_to_news_search_for_blocked_publishers():
    # og fetch fails (publisher blocks scraping) -> the news-search cache
    # supplies the story's own image.
    result = resolve_article_image(
        "https://www.reuters.com/story",
        "https://static2.finnhub.io/file/finnhub/logo/reuters_logo.jpeg",
        fetch=lambda url: None,
        provided_is_generic=True,
        headline="QatarEnergy buys 33 US LNG cargoes",
        news_search_fetch=lambda headline: "https://www.bing.com/th?id=ONUT.ABC&pid=News&w=800",
    )
    assert result == "https://www.bing.com/th?id=ONUT.ABC&pid=News&w=800"


def test_resolve_keeps_original_when_news_search_finds_nothing():
    result = resolve_article_image(
        "https://www.reuters.com/story",
        "https://static2.finnhub.io/file/finnhub/logo/reuters_logo.jpeg",
        fetch=lambda url: None,
        provided_is_generic=True,
        headline="QatarEnergy buys 33 US LNG cargoes",
        news_search_fetch=lambda headline: None,
    )
    assert result == "https://static2.finnhub.io/file/finnhub/logo/reuters_logo.jpeg"
