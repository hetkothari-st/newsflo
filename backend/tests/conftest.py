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
