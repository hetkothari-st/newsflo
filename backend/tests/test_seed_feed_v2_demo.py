"""Test the seed_feed_v2_demo.py safety guard."""
import pytest


def test_seed_feed_v2_demo_rejects_non_sqlite_database(monkeypatch):
    """Verify that seed_feed_v2_demo refuses to run against non-SQLite databases."""
    # Monkeypatch settings.database_url to simulate a Postgres production database
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@localhost/prod_db")

    # Import the main function (after patching the settings, so it reads the patched value)
    from seed_feed_v2_demo import main

    # Expect it to exit with code 1
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


def test_seed_feed_v2_demo_allows_sqlite_database(monkeypatch, db_session):
    """Verify that seed_feed_v2_demo allows running against SQLite databases."""
    # Monkeypatch settings.database_url to a local SQLite database
    from app.config import settings

    monkeypatch.setattr(settings, "database_url", "sqlite:///./local.db")

    # Monkeypatch SessionLocal to return our test db_session
    import seed_feed_v2_demo
    monkeypatch.setattr(seed_feed_v2_demo, "SessionLocal", lambda: db_session)

    # Import the main function (after patching the settings and SessionLocal)
    from seed_feed_v2_demo import main

    # This should NOT raise SystemExit -- it should complete successfully
    main()

    # Verify that demo data was inserted (check that we have articles with the demo marker)
    from app.models import Article

    demo_articles = db_session.query(Article).filter(
        Article.url.like("https://demo.feed-v2.local/%")
    ).all()
    assert len(demo_articles) == 4  # DEMO_ROWS has 4 entries
