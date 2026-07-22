from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

Base = declarative_base()


def get_engine(url: str | None = None):
    url = url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# (table, column, SQL type) for every column added to a model after the dev
# DB file first existed. create_all only creates missing TABLES, never
# missing columns on one that's already there -- there's no Alembic in this
# project -- so each new column must be registered here or it raises "no
# such column" the moment it's queried against an older DB file.
_ADDED_COLUMNS = [
    ("articles", "image_url", "VARCHAR"),
    ("alert_companies", "key_points_json", "TEXT"),
    ("companies", "isin", "VARCHAR"),
    ("users", "email_alerts_enabled", "INTEGER DEFAULT 1"),
    ("companies", "instrument_token", "INTEGER"),
    ("alert_companies", "confidence_score", "INTEGER DEFAULT 50"),
    ("alert_companies", "time_horizon", "VARCHAR DEFAULT 'Short-Term'"),
    ("alerts", "event_type", "VARCHAR"),
    ("alerts", "prompt_version", "VARCHAR"),
    ("alerts", "knowledge_version", "VARCHAR"),
    ("alert_companies", "reasons_json", "TEXT"),
    ("alert_companies", "evidence_refs_json", "TEXT"),
    ("alert_companies", "risks_json", "TEXT"),
    ("alert_companies", "assumptions_json", "TEXT"),
    ("alert_companies", "unknowns_json", "TEXT"),
    ("alert_companies", "alternative_hypothesis", "TEXT"),
    ("alert_companies", "confidence_band", "VARCHAR"),
    ("alert_companies", "confidence_contributors_json", "TEXT"),
    ("alert_companies", "confidence_penalties_json", "TEXT"),
    ("alert_companies", "rulebook_ids_json", "TEXT"),
    ("companies", "sub_sector", "VARCHAR"),
    ("alert_companies", "price_at_analysis", "FLOAT"),
    ("alert_companies", "return_1m", "FLOAT"),
    ("alert_companies", "return_3m", "FLOAT"),
    ("alert_companies", "contradiction_note", "TEXT"),
    ("alert_companies", "impact_level", "VARCHAR DEFAULT 'direct'"),
    ("alert_companies", "parent_company_id", "INTEGER"),
    ("articles", "full_content", "TEXT"),
    ("articles", "full_content_fetch_attempted_at", "TIMESTAMP"),
    ("alerts", "summary_short", "VARCHAR"),
    ("alerts", "summary_long", "TEXT"),
    ("alert_companies", "why", "TEXT"),
    ("companies", "business_desc", "TEXT"),
    ("companies", "supply_chain_suppliers_json", "TEXT"),
    ("companies", "supply_chain_customers_json", "TEXT"),
]


def _existing_columns(conn, table: str) -> set[str]:
    if engine.dialect.name == "sqlite":
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
    # postgresql (production) and any other standard-information_schema backend
    rows = conn.exec_driver_sql(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
    )
    return {row[0] for row in rows}


def _add_missing_columns() -> None:
    """Guarded ALTER TABLE for each entry in ``_ADDED_COLUMNS``. Runs against
    SQLite (local dev) and PostgreSQL (production) -- create_all only creates
    missing TABLES, never missing columns on one that's already there, and
    there's no Alembic in this project, so each new column must be registered
    here or it raises "no such column"/"column does not exist" the moment a
    query touches it against a database whose companies table predates that
    column.
    """
    with engine.connect() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = _existing_columns(conn, table)
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
                conn.commit()


def init_db() -> None:
    from app import models  # noqa: F401  ensures models are registered on Base

    Base.metadata.create_all(engine)
    _add_missing_columns()
