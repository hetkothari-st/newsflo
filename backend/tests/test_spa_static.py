"""SPA shell caching: index.html must never be heuristically cached.

Browsers cache responses that lack Cache-Control using a heuristic on
Last-Modified, which pinned users to stale hashed JS bundles across
deploys (new features looked "not deployed" until a hard refresh).
Every text/html response -- "/" and the SPA fallback for client-side
routes -- must carry Cache-Control: no-cache so the shell revalidates
on each load and always references the current bundle.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_root_index_html_is_no_cache():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_spa_fallback_route_is_no_cache():
    client = TestClient(app)
    response = client.get("/alerts/1/charts")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
