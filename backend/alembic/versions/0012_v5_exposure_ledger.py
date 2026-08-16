"""V5 Phase 1 exposure ledger: company_exposure, company_segment,
company_financials, pass_through_curve, company_modifier, exposure_proposal,
filing_artefact, company_entity_meta, entity_corporate_action,
company_alias_window (+ review-only write guard and reporting views)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-17 00:00:00.000000

WHAT THIS DOES

Creates the V5 Phase 1 ledger tables (docs/v5/02_PHASE_1_exposure_ledger.md
tasks 1.1-1.5, spec 4.1/4.2) and NOTHING else. No existing table is altered,
no column is added to one, and -- the point of the whole phase -- NOT ONE ROW
OF DATA IS WRITTEN. Phase 1 builds machinery; the ledger ships empty and is
filled only by a human approving a proposal that carries a verbatim excerpt
from a filing. tests/phase1/test_migration_0012.py asserts the emptiness
after a full `upgrade head`.

  company_exposure        one sourced exposure of one company to one tag
  company_segment         Ind AS 108 segment note
  company_financials      P&L / borrowings / forex lines, per fiscal period
  pass_through_curve      pass-through as a curve, never a scalar (4.2)
  company_modifier        hedge / cap / levy parameters, sourced
  exposure_proposal       THE ONLY PATH into company_exposure
  filing_artefact         the raw source document, never discarded
  company_entity_meta     the 4.1 `company` columns `companies` lacks
  entity_corporate_action merger/demerger/rename/delisting effective dates
  company_alias_window    aliases WITH a validity window

WHY AN ADJUNCT TABLE INSTEAD OF THE SPEC'S `company` TABLE

This repo already has an ISIN-keyed listed universe (`companies`, plus
`listings` and `company_aliases`). Creating the spec's parallel `company`
table would fork the universe. The missing 4.1 columns (parent_isin, status,
free_float_mcap, adv_20d_inr, listed) therefore live in
`company_entity_meta`, keyed by companies.id -- an additive new table rather
than a `batch_alter_table` on `companies`, because a SQLite batch rebuild
silently drops a table's triggers (0008's warning).

TYPE MAPPING (spec is Postgres, this deployment is SQLite):
  uuid -> TEXT (uuid4 string)   jsonb -> TEXT holding JSON
  numeric -> NUMERIC            timestamptz -> DATETIME
Both CHECK constraints in the spec (`no_selfcertify`, `curve_needs_review`)
are supported by SQLite and are declared on the tables, not emulated.

------------------------------------------------------------------------
TASK 1.4 ON POSTGRES -- THE ROLE DDL, RECORDED VERBATIM FOR THE PORT
------------------------------------------------------------------------
"Approval writes to company_exposure" is a privilege statement. SQLite has
neither roles nor GRANT, so this migration substitutes a trigger-based
capability check (below) and the real DDL is preserved here so the Postgres
port is a transcription rather than a redesign:

    CREATE ROLE newsflo_ledger_reviewer;

    REVOKE INSERT, UPDATE, DELETE ON company_exposure FROM PUBLIC;
    GRANT  INSERT, UPDATE          ON company_exposure TO newsflo_ledger_reviewer;
    GRANT  SELECT                  ON company_exposure TO newsflo_readonly;
    -- DELETE is granted to NOBODY, deliberately. See below.

    -- the nightly staleness job maintains a DERIVED flag, not a claim:
    GRANT  UPDATE (stale, stale_checked_at) ON company_exposure TO newsflo_app;

    REVOKE INSERT, UPDATE ON company_exposure FROM newsflo_extractor;
    GRANT  INSERT, SELECT ON exposure_proposal TO newsflo_extractor;

On Postgres the application connects as `newsflo_ledger_reviewer` ONLY in
app/ledger/review.py.

NOBODY DELETES (fix round 1, I1). No role above is granted DELETE on
`company_exposure`, and the SQLite trigger below refuses it unconditionally
-- from a plain session AND from inside a review session. A human-reviewed
claim about a filing is not something a code path removes: a correction is
an UPDATE inside a review session, which leaves the row, its proposal and
its reviewer behind. A row that must genuinely disappear (a withdrawn
filing, a defrauded reviewer) is a deliberate out-of-band act: drop the
trigger, delete, recreate it -- and say so in writing.

------------------------------------------------------------------------
THE SQLITE SUBSTITUTION
------------------------------------------------------------------------
`company_exposure_review_only_{insert,update}` RAISE(ABORT) unless a TEMP
table `_newsflo_ledger_review_session` exists on the writing CONNECTION.
Only app/ledger/review.py's `review_session()` creates it, and it drops it
in a `finally`. An LLM extractor, a one-off script or the API process is
refused BY THE DATABASE -- which is what the phase file's "do not let an LLM
extractor write directly to the ledger under any circumstance" requires.

The UPDATE trigger is scoped `BEFORE UPDATE OF <claim columns>`: `stale` and
`stale_checked_at` are derived and must stay writable by the nightly job.
Everything else is protected, `exposure_id` and `created_at` included --
re-keying a row or backdating its creation is a rewrite, not a correction
(fix round 1, M1).

`pragma_table_list` requires SQLite >= 3.37 (2021-11) -- same constraint and
same reasoning as migration 0011, whose docstring explains why no other
expression can see the temp schema from inside a trigger.

VIEWS. `extractor_quality` (Task 1.4: approve rate / edit rate per extractor
version -- "falling precision is your signal that an extraction prompt
regressed") and `exposure_coverage` (Task 1.5: companies tagged and % of
sector market cap tagged, per sector and tag). Median exposure age is NOT in
the view: SQLite has no median aggregate, so app/ledger/coverage.py computes
it in Python over the same rows.

DDL DUPLICATION, EXACTLY AS 0008/0011 DO IT. The four CREATE statements
below are duplicated verbatim in app/models.py (whose `after_create` hooks
give create_all-built databases the same guarantees production gets from
this migration). Drift is closed mechanically by
tests/phase1/test_migration_0012.py::test_models_and_0012_ddl_are_byte_
identical, which reads THIS FILE'S SOURCE and compares the normalized SQL.

Guarded creates throughout: tools/migrate_on_boot.py re-runs the whole chain
on every container start, and app/models.py declares these tables on
Base.metadata so create_all() may have built them first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COMPANY_EXPOSURE_INSERT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_exposure_review_only_insert
BEFORE INSERT ON company_exposure
FOR EACH ROW
WHEN (SELECT count(*) FROM pragma_table_list
      WHERE schema = 'temp' AND name = '_newsflo_ledger_review_session') = 0
BEGIN
  SELECT RAISE(ABORT, 'company_exposure is writable only by the review session');
END
"""

_COMPANY_EXPOSURE_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_exposure_review_only_update
BEFORE UPDATE OF exposure_id, company_id, segment_id, exposure_kind,
                 exposure_tag, share_of_base, base_kind, base_value_inr,
                 measurement, source_type, source_url, source_page,
                 as_of_date, freshness_days, confidence, created_by,
                 reviewed_by, proposal_id, created_at
ON company_exposure
FOR EACH ROW
WHEN (SELECT count(*) FROM pragma_table_list
      WHERE schema = 'temp' AND name = '_newsflo_ledger_review_session') = 0
BEGIN
  SELECT RAISE(ABORT, 'company_exposure is writable only by the review session');
END
"""

_COMPANY_EXPOSURE_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_exposure_review_only_delete
BEFORE DELETE ON company_exposure
FOR EACH ROW
BEGIN
  SELECT RAISE(ABORT, 'company_exposure rows are never deleted');
END
"""

_EXTRACTOR_QUALITY_VIEW = """
CREATE VIEW IF NOT EXISTS extractor_quality AS
SELECT created_by AS extractor,
       extractor_version AS extractor_version,
       count(*) AS proposed,
       sum(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) AS approved,
       sum(CASE WHEN status = 'APPROVED' AND edited = 1 THEN 1 ELSE 0 END) AS edited,
       sum(CASE WHEN status IN ('REJECTED', 'REJECTED_UNVERBATIM',
                                'REJECTED_MALFORMED') THEN 1 ELSE 0 END)
         AS rejected,
       sum(CASE WHEN status = 'REJECTED_UNVERBATIM' THEN 1 ELSE 0 END) AS unverbatim,
       sum(CASE WHEN status = 'REJECTED_MALFORMED' THEN 1 ELSE 0 END) AS malformed,
       sum(CASE WHEN status = 'PENDING_REVIEW' THEN 1 ELSE 0 END) AS pending
FROM exposure_proposal
GROUP BY created_by, extractor_version
"""

_EXPOSURE_COVERAGE_VIEW = """
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

_TRIGGERS = (
    _COMPANY_EXPOSURE_INSERT_TRIGGER,
    _COMPANY_EXPOSURE_UPDATE_TRIGGER,
    _COMPANY_EXPOSURE_DELETE_TRIGGER,
)

_VIEWS = (
    _EXTRACTOR_QUALITY_VIEW,
    _EXPOSURE_COVERAGE_VIEW,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'company_entity_meta' not in existing:
        op.create_table(
            'company_entity_meta',
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('parent_isin', sa.String(), nullable=True),
            sa.Column('ownership_fraction', sa.Float(), nullable=True),
            sa.Column('listed', sa.Boolean(), nullable=True),
            sa.Column('status', sa.String(), server_default='ACTIVE', nullable=False),
            sa.Column('entity_kind', sa.String(), nullable=True),
            sa.Column('free_float_mcap', sa.Numeric(), nullable=True),
            sa.Column('adv_20d_inr', sa.Numeric(), nullable=True),
            sa.Column('valid_from', sa.Date(), nullable=True),
            sa.Column('valid_to', sa.Date(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('company_id'),
        )

    if 'entity_corporate_action' not in existing:
        op.create_table(
            'entity_corporate_action',
            sa.Column('action_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('action_type', sa.String(), nullable=False),
            sa.Column('effective_date', sa.Date(), nullable=False),
            sa.Column('successor_isin', sa.String(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('action_id'),
        )
        op.create_index('ix_entity_corporate_action_company_id',
                        'entity_corporate_action', ['company_id'], unique=False)

    if 'company_alias_window' not in existing:
        op.create_table(
            'company_alias_window',
            sa.Column('alias_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('alias', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('normalized', sa.String(), nullable=False),
            sa.Column('valid_from', sa.Date(), nullable=True),
            sa.Column('valid_to', sa.Date(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('alias_id'),
        )
        op.create_index('ix_alias_window_normalized', 'company_alias_window',
                        ['normalized'], unique=False)

    if 'company_exposure' not in existing:
        op.create_table(
            'company_exposure',
            sa.Column('exposure_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('segment_id', sa.String(), nullable=True),
            sa.Column('exposure_kind', sa.String(), nullable=False),
            sa.Column('exposure_tag', sa.String(), nullable=False),
            sa.Column('share_of_base', sa.Numeric(), nullable=False),
            sa.Column('base_kind', sa.String(), nullable=False),
            sa.Column('base_value_inr', sa.Numeric(), nullable=False),
            sa.Column('measurement', sa.String(), nullable=False),
            sa.Column('source_type', sa.String(), nullable=False),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('source_page', sa.String(), nullable=True),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.Column('freshness_days', sa.Integer(), nullable=False),
            sa.Column('confidence', sa.Numeric(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column('reviewed_by', sa.String(), nullable=True),
            sa.Column('proposal_id', sa.String(), nullable=True),
            sa.Column('stale', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('stale_checked_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.CheckConstraint("measurement <> 'MODELLED' OR reviewed_by IS NOT NULL",
                               name='no_selfcertify'),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('exposure_id'),
        )
        op.create_index('ix_company_exposure_tag', 'company_exposure',
                        ['exposure_tag'], unique=False)
        op.create_index('ix_company_exposure_company', 'company_exposure',
                        ['company_id'], unique=False)

    if 'company_segment' not in existing:
        op.create_table(
            'company_segment',
            sa.Column('segment_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('segment_name', sa.String(), nullable=False),
            sa.Column('revenue_inr', sa.Numeric(), nullable=True),
            sa.Column('ebitda_inr', sa.Numeric(), nullable=True),
            sa.Column('revenue_share', sa.Numeric(), nullable=True),
            sa.Column('ebitda_share', sa.Numeric(), nullable=True),
            sa.Column('fiscal_year', sa.Integer(), nullable=False),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('source_page', sa.String(), nullable=True),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('segment_id'),
        )
        op.create_index('ix_company_segment_company_id', 'company_segment',
                        ['company_id'], unique=False)

    if 'company_financials' not in existing:
        op.create_table(
            'company_financials',
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('fiscal_period', sa.String(), nullable=False),
            sa.Column('revenue_inr', sa.Numeric(), nullable=True),
            sa.Column('ebitda_inr', sa.Numeric(), nullable=True),
            sa.Column('pat_inr', sa.Numeric(), nullable=True),
            sa.Column('cogs_inr', sa.Numeric(), nullable=True),
            sa.Column('raw_material_inr', sa.Numeric(), nullable=True),
            sa.Column('power_fuel_inr', sa.Numeric(), nullable=True),
            sa.Column('freight_inr', sa.Numeric(), nullable=True),
            sa.Column('employee_inr', sa.Numeric(), nullable=True),
            sa.Column('gross_debt_inr', sa.Numeric(), nullable=True),
            sa.Column('floating_debt_inr', sa.Numeric(), nullable=True),
            sa.Column('fx_earnings_inr', sa.Numeric(), nullable=True),
            sa.Column('fx_expenditure_inr', sa.Numeric(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=True),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('company_id', 'fiscal_period'),
        )

    if 'pass_through_curve' not in existing:
        op.create_table(
            'pass_through_curve',
            sa.Column('curve_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=True),
            sa.Column('sector_id', sa.String(), nullable=True),
            sa.Column('exposure_tag', sa.String(), nullable=False),
            sa.Column('points', sa.Text(), nullable=False),
            sa.Column('ceiling', sa.Numeric(), nullable=True),
            sa.Column('basis', sa.String(), nullable=False),
            sa.Column('evidence_id', sa.String(), nullable=True),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.Column('reviewed_by', sa.String(), nullable=True),
            sa.CheckConstraint("basis <> 'ESTIMATED' OR reviewed_by IS NOT NULL",
                               name='curve_needs_review'),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('curve_id'),
        )

    if 'company_modifier' not in existing:
        op.create_table(
            'company_modifier',
            sa.Column('modifier_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('modifier_kind', sa.String(), nullable=False),
            sa.Column('applies_to_tag', sa.String(), nullable=False),
            sa.Column('parameters', sa.Text(), nullable=False),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('as_of_date', sa.Date(), nullable=False),
            sa.Column('confidence', sa.Numeric(), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('modifier_id'),
        )
        op.create_index('ix_company_modifier_company_id', 'company_modifier',
                        ['company_id'], unique=False)

    if 'exposure_proposal' not in existing:
        op.create_table(
            'exposure_proposal',
            sa.Column('proposal_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            # NULLABLE for a REJECTED_MALFORMED intake (a row the extractor
            # could not even shape); the proposal_shape CHECK below keeps
            # them mandatory for anything PENDING_REVIEW, which is the only
            # status that can be approved.
            sa.Column('exposure_kind', sa.String(), nullable=True),
            sa.Column('exposure_tag', sa.String(), nullable=True),
            sa.Column('share_of_base', sa.Numeric(), nullable=True),
            sa.Column('base_kind', sa.String(), nullable=True),
            sa.Column('base_value_inr', sa.Numeric(), nullable=True),
            sa.Column('measurement', sa.String(), nullable=True),
            sa.Column('source_type', sa.String(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('source_page', sa.String(), nullable=True),
            sa.Column('excerpt', sa.Text(), nullable=True),
            sa.Column('extraction_confidence', sa.Numeric(), nullable=True),
            sa.Column('model_id', sa.String(), nullable=True),
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column('extractor_version', sa.String(), nullable=True),
            sa.Column('document_sha256', sa.String(), nullable=True),
            sa.Column('as_of_date', sa.Date(), nullable=True),
            sa.Column('raw_payload', sa.Text(), nullable=True),
            sa.Column('status', sa.String(), server_default='PENDING_REVIEW',
                      nullable=False),
            sa.Column('reject_reason', sa.String(), nullable=True),
            sa.Column('edited', sa.Boolean(), server_default='0', nullable=False),
            sa.Column('reviewed_by', sa.String(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('exposure_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.CheckConstraint(
                "status <> 'PENDING_REVIEW' OR (exposure_kind IS NOT NULL AND "
                "base_kind IS NOT NULL AND measurement IS NOT NULL AND "
                "source_type IS NOT NULL)", name='proposal_shape'),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('proposal_id'),
        )
        op.create_index('ix_exposure_proposal_status', 'exposure_proposal',
                        ['status'], unique=False)

    if 'filing_artefact' not in existing:
        op.create_table(
            'filing_artefact',
            sa.Column('artefact_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('source_type', sa.String(), nullable=False),
            sa.Column('media_type', sa.String(), nullable=True),
            sa.Column('content_sha256', sa.String(), nullable=False),
            sa.Column('byte_size', sa.Integer(), nullable=True),
            sa.Column('storage_path', sa.String(), nullable=False),
            sa.Column('fiscal_period', sa.String(), nullable=True),
            sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.PrimaryKeyConstraint('artefact_id'),
            sa.UniqueConstraint('content_sha256', 'source_url',
                                name='uq_artefact_content_url'),
        )

    # Guard and views last: they police tables that must already exist.
    if bind.dialect.name == "sqlite":
        for statement in _TRIGGERS + _VIEWS:
            bind.execute(sa.text(statement))


def downgrade() -> None:
    """Downgrade schema.

    Drops the ledger and everything in it. Unlike an analysis result, an
    approved exposure row is NOT reproducible by re-running anything -- it is
    a human review of a filing. Take a backup before running this.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for name in ("company_exposure_review_only_insert",
                     "company_exposure_review_only_update",
                     "company_exposure_review_only_delete"):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
        for name in ("extractor_quality", "exposure_coverage"):
            bind.execute(sa.text(f"DROP VIEW IF EXISTS {name}"))
    for table in ('filing_artefact', 'exposure_proposal', 'company_modifier',
                  'pass_through_curve', 'company_financials', 'company_segment',
                  'company_exposure', 'company_alias_window',
                  'entity_corporate_action', 'company_entity_meta'):
        op.drop_table(table)
