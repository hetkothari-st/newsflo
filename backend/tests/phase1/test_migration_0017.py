"""Migration 0017 -- `exposure_coverage` re-keyed onto the industry
fall-through.

The defect: the view grouped on `companies.sector`, which is the string
'other' for 3,161 of 5,321 companies. One bucket held roughly a third of the
listed universe and the view called it a sector, so every figure it reported
for that bucket was an average over an arbitrary set.

THE THING THESE TESTS EXIST TO CATCH is not the re-key itself -- it is the
three copies of the key expression drifting apart. It lives in migration 0017
(DDL), in `app/models.py` (create_all DDL) and in
`app/ledger/coverage.py::_INDUSTRY_SQL` (the age join). If the join's copy
drifts from the view's, `median_exposure_age_days` silently becomes None on
every row: the dict lookup misses, nothing raises, and a column of Nones reads
exactly like a ledger with no ages yet.
"""
import importlib.util
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / \
    "0017_v5_exposure_coverage_isubgroup_rekey.py"


def _load():
    spec = importlib.util.spec_from_file_location("_mig_0017", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize(sql: str) -> str:
    return " ".join(sql.split())


def test_the_revision_chain_is_0016_to_0017():
    module = _load()
    assert module.revision == "0017"
    assert module.down_revision == "0016"


def test_the_migration_touches_no_table():
    """DROP VIEW + CREATE VIEW and nothing else. `companies.sector` in
    particular is not written, altered or dropped -- it is read, last."""
    body = MIGRATION.read_text(encoding="utf-8").split('"""', 2)[-1]
    for verb in ("batch_alter_table", "op.alter_column", "op.add_column",
                 "op.drop_column", "op.create_table", "op.drop_table",
                 "UPDATE ", "DELETE "):
        assert verb not in body, f"0017 calls {verb}"


def test_the_key_expression_is_identical_in_all_three_places():
    """Migration DDL, models.py DDL, and the coverage age join."""
    from app.ledger.coverage import _INDUSTRY_SQL
    from app.models import _EXPOSURE_COVERAGE_INDUSTRY

    module = _load()
    key = _normalize(module._INDUSTRY)

    assert _normalize(_EXPOSURE_COVERAGE_INDUSTRY) == key, (
        "app/models.py's industry key has drifted from migration 0017")
    assert _normalize(_INDUSTRY_SQL) == f"{key} AS industry", (
        "app/ledger/coverage.py's age join key has drifted from the view -- "
        "every median_exposure_age_days would silently become None")


def test_the_key_matches_discovery_engines_resolution_order():
    """`_industry_of` and this view must agree on what an industry IS.

    Checked as the ORDER of the three column names in the SQL, because the
    engine resolves them in Python and the view in SQL -- the two cannot be
    compared as text, but their precedence can.
    """
    module = _load()
    order = [name for name in re.findall(
        r"official_isubgroup|sub_sector|sector", module._INDUSTRY)]
    # `sector` appears once as itself; the other two lead it.
    assert order[0] == "official_isubgroup"
    assert order[1] == "sub_sector"
    assert order[-1] == "sector"


def test_the_view_groups_by_industry_and_reports_industry_market_cap():
    module = _load()
    sql = _normalize(module.EXPOSURE_COVERAGE_VIEW_0017)
    assert "GROUP BY t.industry, t.exposure_tag" in sql
    assert "AS industry_market_cap" in sql
    assert "AS sector_market_cap" not in sql, (
        "a column named sector_market_cap that holds an industry total is the "
        "same class of defect this migration fixes")


def test_the_downgrade_restores_0012s_view_exactly():
    module = _load()
    twelve = (BACKEND / "alembic" / "versions"
              / "0012_v5_exposure_ledger.py").read_text(encoding="utf-8")
    found = re.findall(
        r'^_EXPOSURE_COVERAGE_VIEW = """(.*?)"""', twelve,
        flags=re.MULTILINE | re.DOTALL)
    assert len(found) == 1
    assert _normalize(found[0]) == _normalize(module.EXPOSURE_COVERAGE_VIEW_0012), (
        "0017's downgrade would rebuild a different view than 0012 created")


def test_the_view_builds_and_is_queryable_from_models_ddl(tmp_path):
    """The DDL parses against the real schema and exposes the new columns.

    SQLite does not validate a view body at CREATE time, so a view naming a
    column that does not exist is created happily and fails on first SELECT.
    This SELECTs it.

    The BEHAVIOURAL assertion -- that two companies sharing `sector = 'other'`
    land in different rows -- lives in
    `test_coverage_metrics.py::test_coverage_splits_an_other_sector_by_official_isubgroup`,
    which drives the real ledger fixtures through `review_session` and the
    `company_exposure` INSERT triggers. Reproducing that here with raw INSERTs
    would mean bypassing those triggers, and a test that routes around the
    guarantees is not evidence about the system that has them.
    """
    from app import models  # noqa: F401
    from app.db import Base

    url = f"sqlite:///{tmp_path / 'v.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    for ddl in models.V5_LEDGER_DDL:
        with engine.begin() as conn:
            conn.execute(text(ddl))

    assert "exposure_coverage" in set(inspect(engine).get_view_names())

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT industry, exposure_tag, companies_tagged, "
            "       tagged_market_cap, industry_market_cap "
            "FROM exposure_coverage")).all()
    assert rows == []      # empty ledger, and an empty ledger reports nothing
    engine.dispose()
