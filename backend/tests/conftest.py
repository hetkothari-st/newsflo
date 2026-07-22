import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401  ensures models are registered on Base


@pytest.fixture()
def db_session():
    # StaticPool keeps a single shared connection for the whole engine, so the
    # in-memory database survives across threads. Needed because FastAPI's
    # TestClient runs sync route handlers in a worker thread, and plain
    # "sqlite:///:memory:" engines default to SingletonThreadPool, which hands
    # a brand-new (table-less) in-memory DB to any thread other than the one
    # that created the schema.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _no_real_og_image_fetch(monkeypatch):
    # process_new_articles fetches each article's og:image over a real HTTP
    # GET (see app/ingestion/og_image.py). Stub it everywhere by default so
    # the suite never makes network calls; app/ingestion/og_image.py's own
    # tests exercise the real function directly and are unaffected since
    # they don't go through app.pipeline.
    monkeypatch.setattr("app.pipeline.fetch_og_image", lambda url: None)


@pytest.fixture(autouse=True)
def _no_real_full_text_fetch(monkeypatch):
    # process_new_articles now calls fetch_pending_full_text for every NEW
    # article, which would otherwise make a real HTTP GET (see
    # app/ingestion/full_text.py). Stub it everywhere by default so the
    # suite never makes network calls; app/ingestion/full_text.py's own
    # tests exercise the real function directly and are unaffected since
    # they don't go through app.pipeline.
    monkeypatch.setattr("app.pipeline.fetch_pending_full_text", lambda session: None)


@pytest.fixture(autouse=True)
def _no_real_feed_fetch(monkeypatch):
    # fetch_new_articles fetches each RSS feed over a real HTTP GET (see
    # app/ingestion/poller.py). Stub it everywhere by default so the suite
    # never makes network calls -- individual tests that care about the
    # fetch itself (test_poller.py) override this via their own
    # monkeypatch.setattr, which takes precedence over this autouse default.
    class _EmptyResponse:
        content = b""
        def raise_for_status(self):
            pass
    monkeypatch.setattr("app.ingestion.poller.httpx.get", lambda url, timeout=None, follow_redirects=None: _EmptyResponse())


@pytest.fixture(autouse=True)
def _no_real_financial_snapshot_fetch(monkeypatch):
    # process_new_articles now calls get_or_fetch_financial_snapshot for
    # every resolved company, which would otherwise make a real yfinance
    # network call in every pipeline test that doesn't care about this
    # feature. Stub it to "no data" by default -- individual tests that DO
    # care about financial-context behavior override this via their own
    # monkeypatch.setattr, which takes precedence over this autouse default.
    monkeypatch.setattr("app.pipeline.get_or_fetch_financial_snapshot", lambda session, ticker: None)


@pytest.fixture(autouse=True)
def _no_real_market_move_fetch(monkeypatch):
    # process_new_articles now calls measure_company_move for every resolved
    # company, which would otherwise make real yfinance network calls in
    # every pipeline test that doesn't care about this feature. Stub it to
    # a no_data MarketMove by default -- tests that DO care about
    # measurement behavior (test_measure.py, test_market_move_wiring.py)
    # override this via their own monkeypatch.setattr, which takes
    # precedence over this autouse default.
    from app.models import MarketMove, utcnow

    def fake_measure(session, company):
        return MarketMove(
            company_id=company.id, benchmark_ticker="^NSEI",
            measurement_status="no_data", measured_at=utcnow(),
        )

    monkeypatch.setattr("app.pipeline.measure_company_move", fake_measure)
