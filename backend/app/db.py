import logging
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


# ---------------------------------------------------------------------------
# Capability scrub on pool check-in (V5 Phase 0 fix round 2, C1)
# ---------------------------------------------------------------------------
# Two write capabilities in this codebase are granted per CONNECTION, as a
# SQLite TEMP table that a BEFORE INSERT/UPDATE trigger looks for:
# `_newsflo_reducer_session` (app/core/impact_writer.py, company_impact) and
# `_newsflo_ledger_review_session` (app/ledger, the exposure ledger).
#
# A TEMP table lives on the connection, and a pooled connection outlives the
# Session that borrowed it. Two ways that ends badly, both empirically
# reproduced on a QueuePool engine:
#   * a `commit()` inside the grant block returns the connection to the pool
#     WITH the token still on it -- the next Session to borrow that
#     connection could write the guarded table;
#   * with more than one pooled connection, a cleanup DROP can execute on a
#     DIFFERENT connection than the one that got the CREATE. It succeeds,
#     changes nothing, and leaves the original privileged for the lifetime
#     of the process.
#
# The grant blocks are written to drop the token before committing (that is
# the primary fix). This listener is the backstop: NO connection may re-enter
# the pool carrying a capability, whatever the code that borrowed it did.
#
# Registered on the Engine CLASS rather than one engine instance so it also
# covers engines built by tests, scripts and tools -- an unguarded engine is
# exactly where this class of bug hides.
CAPABILITY_TEMP_TABLES = (
    "_newsflo_reducer_session",
    "_newsflo_ledger_review_session",
)


def scrub_capability_tables(dbapi_connection, connection_record) -> None:
    """Drop every per-connection capability token. SQLite only (the token
    mechanism does not exist on other backends, where the guarantee comes
    from real role privileges), and EXCEPTION-SAFE: a connection that cannot
    return to the pool would take the process down with it, so a failed drop
    is logged loudly and swallowed."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    for table in CAPABILITY_TEMP_TABLES:
        try:
            dbapi_connection.execute(f"DROP TABLE IF EXISTS temp.{table}")
        except Exception:
            logger.exception(
                "[db] could not scrub capability table %s on connection "
                "check-in -- this connection may still hold a write "
                "capability it should not have", table)


event.listen(Engine, "checkin", scrub_capability_tables)


def get_engine(url: str | None = None):
    url = url or settings.database_url
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # pool_pre_ping: a pooled Postgres connection that sat idle (overnight /
    # weekend) gets silently dropped server-side; without the ping the next
    # request inherits the dead socket and 500s with "connection timed out"
    # (seen live 2026-08-10 on the preview service). The ping costs one
    # round-trip per checkout and replaces the dead connection instead.
    return create_engine(url, pool_pre_ping=True, pool_recycle=300)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Schema evolution is now owned by Alembic (backend/alembic/) -- see
# alembic/versions/0001_baseline.py, generated 2026-08-13 from the model
# metadata as it stood that day. Every schema change from this point forward
# is an Alembic revision, not a new _ADDED_COLUMNS entry.
#
# _ADDED_COLUMNS below is FROZEN as of 2026-08-13 -- do not extend it. It is
# kept only so `init_db()` (used throughout the test suite and by any
# deployment older than the Alembic baseline) keeps producing a schema
# identical to what it always has: create_all() builds new tables in full
# already (models already declare every column below), so this list only
# ever mattered for patching an EXISTING DB file created before a given
# column existed on its model. New columns belong in an Alembic migration,
# generated with `alembic revision --autogenerate`, and a DB that predates
# Alembic adopts it via `alembic stamp 0001` (see tests/test_migrations.py).
SCHEMA_MANAGED_BY = "alembic"

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
    ("companies", "business_desc_source_url", "VARCHAR"),
    ("companies", "business_desc_as_of", "DATE"),
    ("companies", "supply_chain_suppliers_json", "TEXT"),
    ("companies", "supply_chain_customers_json", "TEXT"),
    ("market_moves", "delivery_pct", "FLOAT"),
    ("market_moves", "vol_normalized", "FLOAT"),
    ("market_moves", "materiality", "FLOAT"),
    ("market_moves", "avg_traded_value", "FLOAT"),
    ("car_outcomes", "car_series_json", "TEXT"),
    ("alerts", "is_unconfirmed", "INTEGER"),
    ("alert_company_translations", "why", "TEXT"),
    ("alerts", "facts", "TEXT"),
    ("alerts", "refinement_status", "VARCHAR"),
    ("alerts", "refinement_attempts", "INTEGER DEFAULT 0"),
    ("companies", "market", "VARCHAR NOT NULL DEFAULT 'INDIA'"),
    ("companies", "official_sector", "VARCHAR"),
    ("companies", "official_industry", "VARCHAR"),
    ("companies", "official_igroup", "VARCHAR"),
    ("companies", "official_isubgroup", "VARCHAR"),
    ("companies", "classification_source", "VARCHAR"),
    ("companies", "classification_as_of", "DATE"),
    ("companies", "market_cap_source", "VARCHAR"),
    ("companies", "market_cap_as_of", "DATE"),
    ("companies", "amfi_tier", "VARCHAR"),
    ("companies", "amfi_rank", "INTEGER"),
    ("companies", "amfi_as_of", "DATE"),
    ("companies", "tradeability", "VARCHAR NOT NULL DEFAULT 'NORMAL'"),
    ("companies", "eps", "FLOAT"),
    ("companies", "ceps", "FLOAT"),
    ("companies", "pe", "FLOAT"),
    ("companies", "pb", "FLOAT"),
    ("companies", "opm", "FLOAT"),
    ("companies", "npm", "FLOAT"),
    ("companies", "roe", "FLOAT"),
    ("companies", "con_eps", "FLOAT"),
    ("companies", "con_ceps", "FLOAT"),
    ("companies", "con_pe", "FLOAT"),
    ("companies", "con_pb", "FLOAT"),
    ("companies", "con_opm", "FLOAT"),
    ("companies", "con_npm", "FLOAT"),
    ("companies", "con_roe", "FLOAT"),
    ("companies", "financials_source", "VARCHAR"),
    ("companies", "financials_as_of", "DATE"),
    ("market_moves", "category", "VARCHAR"),
    ("companies", "shares_outstanding", "FLOAT"),
    ("companies", "shares_outstanding_as_of", "DATE"),
    ("articles", "provider", "VARCHAR"),
    ("articles", "provider_article_id", "VARCHAR"),
    ("articles", "url_hash", "VARCHAR"),
    ("articles", "raw_payload", "TEXT"),
    ("articles", "source_category", "VARCHAR"),
    # -- Impact-graph v3 (2026-08-11) --
    ("alerts", "analysis_provider", "VARCHAR"),
    ("alerts", "analysis_quality", "VARCHAR"),
    ("alert_companies", "causal_distance", "INTEGER"),
    ("alert_companies", "impact_strength", "FLOAT"),
    ("alert_companies", "confidence_f", "FLOAT"),
    ("alert_companies", "materiality", "FLOAT"),
    ("alert_companies", "causal_parent_type", "VARCHAR"),
    ("alert_companies", "causal_parent_id", "VARCHAR"),
    ("alert_companies", "mechanism", "TEXT"),
    ("impact_edges", "parent_type", "VARCHAR"),
    ("impact_edges", "child_type", "VARCHAR"),
    ("impact_edges", "causal_distance", "INTEGER"),
    ("impact_edges", "impact_strength", "FLOAT"),
    ("impact_edges", "confidence_f", "FLOAT"),
    ("impact_edges", "materiality", "FLOAT"),
    ("impact_edges", "time_horizon", "VARCHAR"),
    ("impact_edges", "verification_status", "VARCHAR"),
    # -- Token optimization (2026-08-11) --
    ("alert_companies", "channels_json", "TEXT"),
    # -- Architecture upgrade (2026-08-12): 5-way fundamental effect --
    ("alert_companies", "economic_effect", "VARCHAR"),
    ("impact_edges", "economic_effect", "VARCHAR"),
    # -- Per-call cost observability (2026-08-12 §30) --
    ("llm_call_usage", "article_id", "INTEGER"),
    ("llm_call_usage", "stage", "VARCHAR"),
    ("llm_call_usage", "thinking_level", "VARCHAR"),
    ("llm_call_usage", "thinking_tokens", "INTEGER"),
    ("llm_call_usage", "latency_ms", "INTEGER"),
    ("llm_call_usage", "success", "INTEGER"),
    # -- Knowledge-architecture telemetry (cost-opt 2026-08-12 P1) --
    ("llm_call_usage", "parent_node", "VARCHAR"),
    ("llm_call_usage", "mechanism_id", "VARCHAR"),
    ("llm_call_usage", "candidate_count", "INTEGER"),
    ("llm_call_usage", "returned_count", "INTEGER"),
    ("llm_call_usage", "cache_hit", "INTEGER"),
    ("llm_call_usage", "prompt_version", "VARCHAR"),
    ("llm_call_usage", "schema_version", "VARCHAR"),
    ("llm_call_usage", "estimated_cost_usd", "FLOAT"),
    # -- V4 strict publication gate (2026-08-12) --
    ("alert_companies", "display_tier", "VARCHAR"),
    ("alert_companies", "gate_state", "VARCHAR"),
    ("company_node_exposures", "provenance_type", "VARCHAR"),
    ("market_moves", "last_bar_date", "VARCHAR"),
    ("market_moves", "bar_complete", "INTEGER"),
    # -- Fact provenance + event geography (2026-08-14, migration 0009) --
    ("alerts", "fact_items_json", "TEXT"),
    ("alerts", "event_geography_scope", "VARCHAR"),
    ("alerts", "event_geography_regions_json", "TEXT"),
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
    """LEGACY BOOTSTRAP ONLY -- frozen 2026-08-13, do not extend. Guarded
    ALTER TABLE for each entry in the frozen ``_ADDED_COLUMNS`` list, so that
    a DB file created before Alembic existed (or via bare ``init_db()`` in
    tests) still ends up with every column the current models declare.
    create_all() alone only creates missing TABLES, never missing columns on
    one that already exists. Schema changes from 2026-08-13 onward are
    Alembic revisions (backend/alembic/versions/), not new entries here.
    """
    with engine.connect() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = _existing_columns(conn, table)
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
                conn.commit()


# Indexes the multi-source ingestion dedup path needs (see
# app/ingestion/collector.py._already_seen -- per-item lookups by url_hash
# and (provider, provider_article_id) every poll cycle). create_all builds
# these for a brand-new DB via the model's index definitions, but an
# existing DB got the columns from _ADDED_COLUMNS' bare ALTER TABLE, which
# never creates indexes -- so they are ensured explicitly here. IF NOT
# EXISTS is valid on both SQLite and Postgres.
_ENSURED_INDEXES = [
    ("ix_articles_url_hash", "articles", "url_hash"),
    ("ix_articles_provider_article_id", "articles", "provider, provider_article_id"),
]


def _ensure_indexes() -> None:
    with engine.connect() as conn:
        for name, table, columns in _ENSURED_INDEXES:
            conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")
            conn.commit()


def init_db() -> None:
    from app import models  # noqa: F401  ensures models are registered on Base

    Base.metadata.create_all(engine)
    _add_missing_columns()
    _ensure_indexes()
