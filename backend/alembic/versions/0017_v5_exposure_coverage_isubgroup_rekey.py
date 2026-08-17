"""V5 -- re-key exposure_coverage off companies.sector onto official_isubgroup

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-17

WHY. `exposure_coverage` (migration 0012) grouped on `companies.sector`.
Measured on the 5,321-row companies table: 3,161 rows carry `sector = 'other'`
literally, so the view reported ONE bucket of ~3,000 companies and called it a
sector. Every number it produced for that bucket -- companies tagged, tagged
market cap, percent of sector market cap -- was an average over an arbitrary
third of the listed universe, which is not a coverage measurement of anything.

Same defect, same day, as `app/discovery/engine.py::_industry_of`, and re-keyed
the same way so the two agree on what an industry is:

    official_isubgroup  (exchange classification, 4,669 of 5,321, 190 values)
      else sub_sector   (826 of 5,321, 43 values)
      else sector       (5,321 of 5,321, 11 values, 3,161 of them 'other')

Measured effect on the grouping key: largest bucket 3,035 -> 282, buckets
52 -> 227, and no company becomes unclassifiable (0 NULL keys).

`companies.sector` IS NOT WRITTEN, NOT ALTERED, AND NOT DROPPED. It is read,
last, as the coarsest fallback. No table is touched by this migration at all --
it is DROP VIEW + CREATE VIEW and nothing else.

THE COLUMN IS RENAMED `sector` -> `industry`, deliberately. A column named
`sector` holding an exchange industry subgroup would be the same class of
error this migration exists to fix: a label that no longer describes what it
holds. `app/ledger/coverage.py` is the only reader.

Claimed as 0017 in docs/v5/MIGRATION_CLAIMS.md before this file was created.
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


# The industry key, as one expression. Must stay in step with
# `app/discovery/engine.py::_industry_of` -- pinned by
# tests/phase1/test_migration_0017.py.
_INDUSTRY = (
    "COALESCE(NULLIF(TRIM(COALESCE(c.official_isubgroup, '')), ''), "
    "NULLIF(TRIM(COALESCE(c.sub_sector, '')), ''), c.sector)")
_INDUSTRY_C2 = _INDUSTRY.replace("c.", "c2.")

EXPOSURE_COVERAGE_VIEW_0017 = f"""
CREATE VIEW IF NOT EXISTS exposure_coverage AS
SELECT t.industry AS industry,
       t.exposure_tag AS exposure_tag,
       count(*) AS companies_tagged,
       sum(COALESCE(t.market_cap, 0)) AS tagged_market_cap,
       (SELECT sum(COALESCE(c2.market_cap, 0)) FROM companies c2
         WHERE {_INDUSTRY_C2} = t.industry) AS industry_market_cap
FROM (SELECT DISTINCT {_INDUSTRY} AS industry, e.exposure_tag AS exposure_tag,
             c.id AS company_id, c.market_cap AS market_cap
        FROM company_exposure e JOIN companies c ON c.id = e.company_id) t
GROUP BY t.industry, t.exposure_tag
"""

# Exactly what 0012 created, for the downgrade. Copied rather than imported:
# 0012 is history and must not be reached into, and a downgrade that rebuilds
# something slightly different is not a downgrade.
EXPOSURE_COVERAGE_VIEW_0012 = """
CREATE VIEW IF NOT EXISTS exposure_coverage AS
SELECT t.sector AS sector,
       t.exposure_tag AS exposure_tag,
       count(*) AS companies_tagged,
       sum(COALESCE(t.market_cap, 0)) AS tagged_market_cap,
       (SELECT sum(COALESCE(c2.market_cap, 0)) FROM companies c2
         WHERE c2.sector = t.sector) AS sector_market_cap
FROM (SELECT DISTINCT c.sector AS sector, e.exposure_tag AS exposure_tag,
             c.id AS company_id, c.market_cap AS market_cap
        FROM company_exposure e JOIN companies c ON c.id = e.company_id) t
GROUP BY t.sector, t.exposure_tag
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS exposure_coverage")
    op.execute(EXPOSURE_COVERAGE_VIEW_0017)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS exposure_coverage")
    op.execute(EXPOSURE_COVERAGE_VIEW_0012)
