from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    Alert, AlertCompany, Article, Company, CompanyIndexMembership, Listing, MarketMove,
)
from app.routers.articles import get_db


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def test_dossier_aggregates_listings_indices_news_and_facts(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market="INDIA", market_cap=1_000_000.0, isin="INE002A01018",
        business_desc="Sourced text about Reliance.",
        business_desc_source_url="https://en.wikipedia.org/wiki/Reliance_Industries",
    )
    db_session.add(company)
    db_session.commit()
    db_session.add_all([
        Listing(company_id=company.id, exchange="NSE", symbol="RELIANCE", series="EQ",
                status="ACTIVE", source="NSE", as_of=date(2026, 8, 1)),
        Listing(company_id=company.id, exchange="BSE", symbol="RELIANCE", scrip_code="500325",
                group_code="A", status="ACTIVE", source="BSE", as_of=date(2026, 8, 1)),
        CompanyIndexMembership(company_id=company.id, index_code="NIFTY50"),
    ])
    article = Article(source="test", url="https://example.com/a", title="Crude spikes", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.commit()
    db_session.add_all([
        AlertCompany(alert_id=alert.id, company_id=company.id, direction="bearish",
                     magnitude_low=1.0, magnitude_high=2.0, rationale="r",
                     time_horizon="Short-Term", basis="direct_mention", confidence="llm_estimate"),
        MarketMove(alert_id=alert.id, company_id=company.id, raw_move_pct=-4.0,
                   sector_move_pct=-1.0, excess_move_pct=-3.0,
                   benchmark_ticker="^NSEI", measurement_status="ok"),
    ])
    db_session.commit()

    _override_db(db_session)
    client = TestClient(app)
    response = client.get("/api/companies/by-ticker/RELIANCE.NS/dossier")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE.NS"
    assert {l["exchange"] for l in body["listings"]} == {"NSE", "BSE"}
    bse = next(l for l in body["listings"] if l["exchange"] == "BSE")
    assert bse["scrip_code"] == "500325" and bse["group_code"] == "A"
    assert body["indices"] == ["NIFTY50"]
    assert body["business_desc"] == "Sourced text about Reliance."
    assert body["business_desc_source_url"].startswith("https://en.wikipedia.org/")
    assert len(body["news"]) == 1
    assert body["news"][0]["excess_move_pct"] == -3.0
    assert body["market_cap"] == 1_000_000.0
    assert body["market_cap_source"] == "stored"
    assert body["history_text"] is None  # enrichment not yet run -> hidden section


def test_dossier_unknown_ticker_404s(db_session):
    _override_db(db_session)
    client = TestClient(app)
    response = client.get("/api/companies/by-ticker/NOPE.NS/dossier")
    app.dependency_overrides.clear()
    assert response.status_code == 404


def test_dossier_withholds_unsourced_description(db_session):
    company = Company(
        ticker="LEGACY.NS", name="Legacy Ltd", sector="other", index_tier="OTHER",
        market="INDIA", market_cap=10.0,
        business_desc="LLM-invented text with no source.", business_desc_source_url=None,
    )
    db_session.add(company)
    db_session.commit()

    _override_db(db_session)
    client = TestClient(app)
    body = client.get("/api/companies/by-ticker/LEGACY.NS/dossier").json()
    app.dependency_overrides.clear()
    assert body["business_desc"] is None  # withhold-invented-text gate holds
