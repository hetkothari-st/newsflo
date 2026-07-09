import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Alert, AlertCompany, Article, Company
from app.pipeline import process_new_articles


def test_process_new_articles_creates_alert_end_to_end(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_energy"

    alert_companies = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(alert_companies) == 1
    assert alert_companies[0].company_id == company.id

    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.status == "ANALYZED"


def test_process_new_articles_marks_analysis_failed_after_retries(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/b", title="RBI hikes repo rate", content="")
    db_session.add(article)
    db_session.commit()

    def boom(client, title, content):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline_module, "analyze_article", boom)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.status == "ANALYSIS_FAILED"


def test_process_new_articles_ignores_filtered_articles(db_session, monkeypatch):
    irrelevant = Article(source="test", url="https://example.com/c", title="Cat stuck in tree", content="")
    db_session.add(irrelevant)
    db_session.commit()

    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: (_ for _ in ()).throw(AssertionError("should not be called")))

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=irrelevant.id).one()
    assert refreshed.status == "FILTERED"
