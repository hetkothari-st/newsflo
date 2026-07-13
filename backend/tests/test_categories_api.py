from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, Article
from app.routers.articles import get_db


def _seed(db_session):
    article = Article(source="test", url="https://example.com/cat", title="t", status="ANALYZED")
    db_session.add(article)
    db_session.commit()
    # Two "oil_energy" (a duplicate) plus "banking" and a free-text category.
    for cat in ["oil_energy", "banking", "oil_energy", "Treasury / Rates"]:
        db_session.add(Alert(article_id=article.id, category=cat))
    db_session.commit()


def test_list_categories_returns_distinct_sorted(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/categories").json()

    # `category` is the raw canonical slug (used for watchlist matching);
    # `label` defaults to the same value in English (no translation row
    # exists for lang="en" -- it's never translated, only display languages
    # get CategoryTranslation rows).
    assert body == [
        {"category": "Treasury / Rates", "label": "Treasury / Rates"},
        {"category": "banking", "label": "banking"},
        {"category": "oil_energy", "label": "oil_energy"},
    ]

    app.dependency_overrides.clear()


def test_list_categories_empty_when_no_alerts(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert client.get("/api/categories").json() == []

    app.dependency_overrides.clear()
