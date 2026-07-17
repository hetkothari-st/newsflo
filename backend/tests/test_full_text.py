from types import SimpleNamespace

from app.ingestion.full_text import fetch_full_text


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


def test_returns_extracted_text_on_success(monkeypatch):
    html = "<html><body><article>Full article body text.</article></body></html>"
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get(html))
    monkeypatch.setattr("app.ingestion.full_text.trafilatura.extract", lambda h: "Full article body text.")
    assert fetch_full_text("https://example.com/a") == "Full article body text."


def test_returns_none_when_extraction_finds_nothing(monkeypatch):
    html = "<html><body></body></html>"
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get(html))
    monkeypatch.setattr("app.ingestion.full_text.trafilatura.extract", lambda h: None)
    assert fetch_full_text("https://example.com/a") is None


def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get("", status_code=404))
    assert fetch_full_text("https://example.com/missing") is None


def test_returns_none_on_network_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("no route")
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", boom)
    assert fetch_full_text("https://example.com/down") is None


def test_returns_none_when_extraction_raises(monkeypatch):
    html = "<html><body>malformed</body></html>"
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get(html))
    def boom(h):
        raise ValueError("parse error")
    monkeypatch.setattr("app.ingestion.full_text.trafilatura.extract", boom)
    assert fetch_full_text("https://example.com/a") is None
