from fastapi.testclient import TestClient

from app.analysis.schemas import CATEGORIES
from app.main import app
from app.routers.articles import get_db


def test_list_categories_returns_the_fixed_taxonomy(db_session):
    # The full CATEGORIES list is always returned, in taxonomy order --
    # unlike before (when this endpoint mirrored whatever distinct
    # Alert.category strings existed in the DB), a category is selectable
    # here even if no alert has used it yet, and no free-text/legacy value
    # an existing alert might still have can leak into the response.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    body = client.get("/api/categories").json()

    assert [c["category"] for c in body] == CATEGORIES
    # English (the default `lang`) falls back to the raw slug -- the
    # client-side CATEGORY_LABEL map is what humanizes it for display.
    assert all(c["label"] == c["category"] for c in body)

    app.dependency_overrides.clear()


def test_list_categories_ignores_db_content_entirely(db_session):
    # Even with zero alerts in the DB, the endpoint still returns the full
    # fixed list -- it no longer derives from Alert.category at all.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert len(client.get("/api/categories").json()) == len(CATEGORIES)

    app.dependency_overrides.clear()
