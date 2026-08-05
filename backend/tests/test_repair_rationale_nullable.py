import pytest

import repair_rationale_nullable as script


def test_main_raises_on_non_sqlite_dialect(monkeypatch):
    # This script's approach (RENAME/CreateTable/copy/DROP + legacy_alter_table
    # PRAGMAs) is SQLite-only. Its name invites running it against Postgres
    # during a deploy without checking -- must fail loudly and point at the
    # correct Postgres statement instead of attempting SQLite-only DDL.
    monkeypatch.setattr(script.engine.dialect, "name", "postgresql")

    with pytest.raises(RuntimeError, match="SQLite-only"):
        script.main()


def test_main_error_message_names_the_postgres_statement(monkeypatch):
    monkeypatch.setattr(script.engine.dialect, "name", "postgresql")

    with pytest.raises(RuntimeError, match=r"ALTER TABLE alert_companies ALTER COLUMN rationale DROP NOT NULL"):
        script.main()
