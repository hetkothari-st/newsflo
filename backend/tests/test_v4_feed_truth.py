"""Phase 8 (spec §37/§38/§49, INV-012/015): the API serializes fundamental
impact and market reaction as separate truths, and a valid fundamental
analysis is never hidden just because the price feed failed. Legacy mode
keeps the measured-only feed byte-identical."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_engine
from app.main import app
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


def _seed(db, *, move_status="ok", excess=-2.5, display_tier="primary"):
    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="Crude oil spikes on supply shock", content="c",
                      status="ALERTED")
    company = Company(name="MRF", ticker="MRF.NS", sector="auto", index_tier="NIFTY50")
    db.add_all([article, company])
    db.commit()
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    db.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis",
        basis="direct_mention", economic_effect="negative",
        display_tier=display_tier, gate_state="DISPLAY_ELIGIBLE",
        causal_parent_type="economic_node", causal_parent_id="crude_price",
        causal_distance=1, materiality=0.7, mechanism="crude-linked input costs",
    ))
    db.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status=move_status,
        excess_move_pct=excess if move_status == "ok" else None,
        raw_move_pct=excess if move_status == "ok" else None,
        sector_move_pct=0.0 if move_status == "ok" else None,
        measured_at=utcnow(), category="commodity", bar_complete=1,
    ))
    db.commit()
    return alert


def test_strict_unmeasured_alert_still_served_in_list(client, db_session, strict_mode):
    """INV-015 / spec §49: market-data failure must not erase valid
    fundamental analysis."""
    alert = _seed(db_session, move_status="no_data")

    rows = client.get("/api/feed-v2").json()

    assert [r["id"] for r in rows] == [alert.id]
    row = rows[0]
    assert row["excess_move_pct"] is None
    assert row["market_reaction"]["status"] == "unavailable"
    assert row["market_reaction"]["direction"] == "unknown"


def test_legacy_unmeasured_alert_stays_hidden(client, db_session, legacy_mode):
    _seed(db_session, move_status="no_data")

    assert client.get("/api/feed-v2").json() == []


def test_strict_detail_serves_unmeasured_alert_with_layers(client, db_session, strict_mode):
    alert = _seed(db_session, move_status="no_data")

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["market_reaction"]["status"] == "unavailable"
    assert len(detail["layers"]) == 1
    assert detail["layers"][0]["icon"] == "lose"  # from economic_effect


def test_legacy_detail_404s_unmeasured_alert(client, db_session, legacy_mode):
    alert = _seed(db_session, move_status="no_data")

    assert client.get(f"/api/feed-v2/{alert.id}").status_code == 404


def test_measured_alert_reaction_object_uses_dead_zone(client, db_session, strict_mode):
    """+0.05% excess is FLAT, not a winner (spec §22)."""
    alert = _seed(db_session, move_status="ok", excess=0.05)

    row = client.get("/api/feed-v2").json()[0]

    assert row["market_reaction"]["status"] == "ok"
    assert row["market_reaction"]["direction"] == "flat"
    assert row["excess_move_pct"] == 0.05  # exact value untouched


def test_strict_rows_carry_fundamental_and_reaction_separately(client, db_session, strict_mode):
    """Apollo case end-to-end: negative fundamental + positive reaction,
    both serialized, neither overwriting the other."""
    alert = _seed(db_session, move_status="ok", excess=+2.1)

    detail = client.get(f"/api/feed-v2/{alert.id}").json()
    row = detail["layers"][0]["rows"][0]

    assert row["economic_effect"] == "negative"
    assert row["display_tier"] == "primary"
    assert row["reaction_direction"] == "positive"
    assert row["excess_move_pct"] == 2.1
