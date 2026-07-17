from types import SimpleNamespace

from app.ingestion.full_text import fetch_full_text, fetch_pending_full_text
from app.models import Article


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


def test_fetch_pending_full_text_populates_content_on_success(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/a", title="t", content="summary")
    db_session.add(article)
    db_session.commit()

    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", lambda url: "The full article body.")

    fetch_pending_full_text(db_session)

    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.full_content == "The full article body."
    assert refreshed.full_content_fetch_attempted_at is not None


def test_fetch_pending_full_text_marks_attempt_even_on_failure(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/a", title="t", content="summary")
    db_session.add(article)
    db_session.commit()

    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", lambda url: None)

    fetch_pending_full_text(db_session)

    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.full_content is None
    assert refreshed.full_content_fetch_attempted_at is not None


def test_fetch_pending_full_text_never_retries_an_attempted_article(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/a", title="t", content="summary")
    db_session.add(article)
    db_session.commit()

    call_count = {"n": 0}
    def counting_fetch(url):
        call_count["n"] += 1
        return None
    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", counting_fetch)

    fetch_pending_full_text(db_session)
    fetch_pending_full_text(db_session)

    assert call_count["n"] == 1


def test_fetch_pending_full_text_ignores_non_new_articles(db_session, monkeypatch):
    article = Article(
        source="test", url="https://example.com/a", title="t", content="summary", status="ANALYZED",
    )
    db_session.add(article)
    db_session.commit()

    call_count = {"n": 0}
    def counting_fetch(url):
        call_count["n"] += 1
        return None
    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", counting_fetch)

    fetch_pending_full_text(db_session)

    assert call_count["n"] == 0
