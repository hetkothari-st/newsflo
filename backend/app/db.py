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
]


def _add_missing_columns() -> None:
    """Guarded ALTER TABLE for each entry in ``_ADDED_COLUMNS``. SQLite only
    (the only backend this project runs against); a no-op on any other engine.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
                conn.commit()


def init_db() -> None:
    from app import models  # noqa: F401  ensures models are registered on Base

    Base.metadata.create_all(engine)
    _add_missing_columns()
