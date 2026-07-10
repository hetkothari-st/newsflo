from types import SimpleNamespace

from app.ingestion.og_image import fetch_og_image


def _fake_get(html: str, status_code: int = 200):
    def get(url, timeout=None, follow_redirects=None, headers=None):
        response = SimpleNamespace(text=html, status_code=status_code)
        response.raise_for_status = lambda: None
        if status_code >= 400:
            def _raise():
                raise Exception("http error")
            response.raise_for_status = _raise
        return response
    return get


def test_returns_og_image_when_present(monkeypatch):
    html = '<html><head><meta property="og:image" content="https://example.com/pic.jpg"></head></html>'
    monkeypatch.setattr("app.ingestion.og_image.httpx.get", _fake_get(html))
    assert fetch_og_image("https://example.com/a") == "https://example.com/pic.jpg"


def test_falls_back_to_twitter_image(monkeypatch):
    html = '<html><head><meta name="twitter:image" content="https://example.com/tw.jpg"></head></html>'
    monkeypatch.setattr("app.ingestion.og_image.httpx.get", _fake_get(html))
    assert fetch_og_image("https://example.com/a") == "https://example.com/tw.jpg"


def test_returns_none_when_no_image_meta(monkeypatch):
    html = "<html><head><title>No image here</title></head></html>"
    monkeypatch.setattr("app.ingestion.og_image.httpx.get", _fake_get(html))
    assert fetch_og_image("https://example.com/a") is None


def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr("app.ingestion.og_image.httpx.get", _fake_get("", status_code=404))
    assert fetch_og_image("https://example.com/missing") is None


def test_returns_none_on_network_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("no route")
    monkeypatch.setattr("app.ingestion.og_image.httpx.get", boom)
    assert fetch_og_image("https://example.com/down") is None
