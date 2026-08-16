"""Gate Zero eval corpus: eval_event, eval_label, eval_event_label,
eval_adjudication

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-17 00:00:00.000000

WHAT THIS DOES

Creates the four tables of the V5 Gate Zero labeled corpus
(docs/v5/08_PHASE_7_eval_harness.md Task 7.1, docs/v5/EXECUTION_CONTRACT.md
§2) and NOTHING else. No existing table is altered, no column is added, no
row is written.

  * eval_event            -- one labeled historical event, its stratum and
                             the article it points at.
  * eval_label            -- one labeler's expectation for one company on
                             one event (PRIMARY / SECONDARY_RIPPLE /
                             MACRO_CONTEXT / ABSENT), with direction,
                             mechanism, materiality and rationale.
  * eval_event_label      -- one labeler's EVENT-LEVEL expectation: the
                             ripple FAMILIES the event should reach. 7.1's
                             per-company table cannot express a family (a
                             family is not a company), so it gets its own
                             table rather than being smuggled into
                             company_ref.
  * eval_adjudication     -- the two labelers' disagreements, resolved.
                             DISPUTED lives here; the scorer excludes
                             DISPUTED pairs from precision denominators and
                             reports them separately as the corpus's own
                             ambiguity rate.

THE TABLES SHIP EMPTY. Labels are human work (two independent labelers,
event-only, no system output) and this migration must never be the place
they appear. A corpus we generated would measure our own imagination --
see docs/v5/00_MASTER_CONTEXT.md's fabrication guard.

SQLITE / SQLALCHEMY ADAPTATIONS from 7.1's Postgres DDL, which this repo
does not use:

  * ``event_id uuid`` -> ``sa.String``. SQLite has no uuid type. The
    tooling mints uuid4 hex strings (app.eval.schema.new_event_id) but the
    importer also accepts human-written ids from a spreadsheet.
  * ``timestamptz`` -> ``sa.DateTime(timezone=True)``, the same spelling
    every other timestamp column in app/models.py uses.
  * ``eval_label.company_id uuid`` -> ``company_ref sa.String``. Labels are
    produced BEFORE entity resolution; forcing a FK to companies.id would
    make an unrecognized ticker an error at labeling time instead of a
    finding at scoring time. No foreign keys at all here, for the same
    reason on ``article_ref``.
  * The enum-ish columns are CHECK constraints (SQLite enforces them)
    rather than Postgres enum types, so the same DDL runs on both backends.

THIS MIGRATION DOES NOT TOUCH alert_companies -- or any other existing
table. 0008's docstring warns that a ``batch_alter_table`` over
alert_companies silently drops the §26 gated-consistency triggers (SQLite
rebuilds the table without copying triggers). Nothing here alters an
existing table, so those triggers are untouched, and
tests/test_gate_zero_tooling.py::
test_migration_leaves_the_gated_row_triggers_installed proves it after a
full ``upgrade head``.

Guarded creates, following 0002's pattern: each CREATE TABLE checks the
inspector first, so re-running the chain (tools/migrate_on_boot.py runs it
on every container start) is a no-op. Unlike 0002's table, these four are
NOT declared on app.db.Base.metadata, so create_all() never builds them --
the guard is here for repeat runs, not for a create_all race.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept as literals rather than imported from app.eval.schema: a migration
# must keep working against the code as it was when the migration ran, so
# migrations in this repo never import application modules (see 0008's
# warning block). test_migration_schema_matches_the_declared_metadata pins
# these to app/eval/schema.py so the two cannot drift.
_STRATA = ("commodity", "policy_regulatory", "company_action", "macro_data",
           "geopolitical", "earnings", "null_event")
_EXPECTED_TIERS = ("PRIMARY", "SECONDARY_RIPPLE", "MACRO_CONTEXT", "ABSENT")
_RESOLUTIONS = ("LABELER_A", "LABELER_B", "MERGED", "DISPUTED")


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'eval_event' not in existing:
        op.create_table(
            'eval_event',
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('stratum', sa.String(), nullable=False),
            sa.Column('article_ref', sa.String(), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.CheckConstraint(_in_clause('stratum', _STRATA),
                               name='ck_eval_event_stratum'),
            sa.PrimaryKeyConstraint('event_id'),
        )

    if 'eval_label' not in existing:
        op.create_table(
            'eval_label',
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('company_ref', sa.String(), nullable=False),
            sa.Column('labeler', sa.String(), nullable=False),
            sa.Column('expected_tier', sa.String(), nullable=False),
            sa.Column('expected_direction', sa.String(), nullable=True),
            sa.Column('expected_mechanism', sa.String(), nullable=True),
            sa.Column('expected_materiality', sa.String(), nullable=True),
            sa.Column('label', sa.String(), nullable=True),
            sa.Column('rationale', sa.Text(), nullable=True),
            sa.Column('labeled_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(_in_clause('expected_tier', _EXPECTED_TIERS),
                               name='ck_eval_label_expected_tier'),
            sa.PrimaryKeyConstraint('event_id', 'company_ref', 'labeler'),
        )

    if 'eval_event_label' not in existing:
        op.create_table(
            'eval_event_label',
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('labeler', sa.String(), nullable=False),
            sa.Column('ripple_families_json', sa.Text(), nullable=True),
            sa.Column('rationale', sa.Text(), nullable=True),
            sa.Column('labeled_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('event_id', 'labeler'),
        )

    if 'eval_adjudication' not in existing:
        op.create_table(
            'eval_adjudication',
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('company_ref', sa.String(), nullable=False),
            sa.Column('resolution', sa.String(), nullable=False),
            sa.Column('resolved_by', sa.String(), nullable=True),
            sa.Column('resolved_note', sa.Text(), nullable=True),
            sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(_in_clause('resolution', _RESOLUTIONS),
                               name='ck_eval_adjudication_resolution'),
            sa.PrimaryKeyConstraint('event_id', 'company_ref'),
        )


def downgrade() -> None:
    """Downgrade schema.

    Drops the corpus tables. Note this DESTROYS labels, which are days of
    human work -- export them with tools/eval_import.py's counterpart
    (a plain SELECT to CSV) before downgrading.
    """
    for table in ('eval_adjudication', 'eval_event_label', 'eval_label', 'eval_event'):
        op.drop_table(table)
