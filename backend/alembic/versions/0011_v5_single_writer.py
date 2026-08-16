"""V5 Phase 0 canonical truth: signal, supported_version, company_impact,
firewall_deletion (+ single-writer / append-only / version-fence triggers)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-17 00:00:00.000000

WHAT THIS DOES

Creates the four V5 Phase 0 tables (docs/v5/01_PHASE_0_canonical_truth.md
tasks 0.1, 0.3, 0.5, 0.6, 0.7) and NOTHING else. No existing table is
altered, no column is added to one, no row of application data is written.

  * signal             -- append-only stage observations (Task 0.1)
  * supported_version  -- the reducer versions allowed to write (Task 0.3)
  * company_impact     -- THE canonical per-company record (Task 0.2/0.7)
  * firewall_deletion  -- every sentence the entailment firewall deleted
                          (Task 0.6)

The ONE row this migration writes is `supported_version('r5.0.0')`: the
version registry is not data about the world, it is the fence that lets the
database reject a stale worker. Without it every canonical write fails.

THIS MIGRATION DOES NOT TOUCH alert_companies -- or any other existing
table. 0008's docstring warns that `batch_alter_table` over alert_companies
silently drops the §26 gated-consistency triggers (SQLite rebuilds a table
without copying triggers). Nothing here alters an existing table, and
tests/phase0/test_migration_0011.py proves both facts after a full
`upgrade head`.

------------------------------------------------------------------------
TASK 0.3 ON POSTGRES -- THE ROLE DDL, RECORDED VERBATIM FOR THE PORT
------------------------------------------------------------------------
The phase file specifies role privileges. SQLite has neither roles nor
GRANT, so this migration substitutes a trigger-based capability check (see
below), and the real DDL is preserved here so the Postgres port is a
transcription rather than a redesign:

    CREATE ROLE newsflo_reducer;
    CREATE ROLE newsflo_readonly;

    REVOKE INSERT, UPDATE, DELETE ON company_impact FROM PUBLIC;
    GRANT  INSERT, UPDATE          ON company_impact TO newsflo_reducer;
    GRANT  SELECT                  ON company_impact TO newsflo_readonly;

    REVOKE UPDATE, DELETE ON signal FROM PUBLIC;   -- append-only
    GRANT  INSERT, SELECT ON signal TO newsflo_reducer;

    ALTER TABLE company_impact
      ADD CONSTRAINT fk_reducer_version
        FOREIGN KEY (reducer_version) REFERENCES supported_version(reducer_version);

On Postgres the application connects as `newsflo_reducer` ONLY in
app/core/impact_writer.py and as `newsflo_readonly` everywhere else.

------------------------------------------------------------------------
THE SQLITE SUBSTITUTION
------------------------------------------------------------------------
1. SINGLE WRITER. `company_impact_reducer_only_{insert,update}` RAISE(ABORT)
   unless a TEMP table `_newsflo_reducer_session` exists on the writing
   CONNECTION. Only app/core/impact_writer.py's `reducer_session()` creates
   it, and it drops it in a `finally`. A stale worker or a one-off script
   holding a write handle to the same file is refused BY THE DATABASE.

   `pragma_table_list` (SQLite >= 3.37, 2021-11) is the only expression a
   trigger may use to see the temp schema: a trigger body cannot reference
   `temp.sqlite_master` at all ("trigger cannot reference objects in
   database temp"), and bare `sqlite_temp_master` resolves to `main`. On an
   older SQLite the CREATE TRIGGER below fails loudly, which is the correct
   outcome: a schema that LOOKS guarded but is not is the failure mode this
   whole task exists to eliminate.

2. VERSION FENCING is `company_impact_version_fence_{insert,update}` rather
   than the FK. The FK is declared (for Postgres, and as documentation) but
   SQLite enforces foreign keys only under `PRAGMA foreign_keys=ON`, which
   this repo never sets -- so an FK alone would be an unenforced promise.
   The trigger also honours `supported_version.active`, which an FK cannot.

3. APPEND-ONLY `signal`: `signal_append_only_{update,delete}` refuse both
   verbs outright. Re-appending is safe because signal ids are content
   addressed (app/core/signals.py), so a replay collides on the primary key
   and the writer's INSERT OR IGNORE makes it a no-op.

DDL DUPLICATION, EXACTLY AS 0008 DOES IT. The six CREATE TRIGGER statements
below are duplicated verbatim in app/models.py (whose `after_create` hooks
give create_all-built databases -- the entire test suite and every fresh dev
DB -- the same guarantees production gets from this migration). A migration
must never import app code that drifts underneath it; drift is closed
mechanically instead by tests/phase0/test_migration_0011.py::
test_models_and_0011_trigger_ddl_are_byte_identical, which reads THIS FILE'S
SOURCE and compares the normalized SQL.

Guarded creates throughout, like 0002 and 0010: tools/migrate_on_boot.py
re-runs the whole chain on every container start, and app/models.py declares
these tables on Base.metadata so create_all() may have built them first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The reducer version this migration registers. A LITERAL on purpose: a
# migration is a statement about the database as it was when it ran, and
# importing app.core.reducer.REDUCER_VERSION would let a later bump silently
# rewrite what this already-applied migration claims to have done.
# tests/phase0/test_migration_0011.py pins it to the running constant.
_REDUCER_VERSION = "r5.0.0"


_COMPANY_IMPACT_INSERT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_impact_reducer_only_insert
BEFORE INSERT ON company_impact
FOR EACH ROW
WHEN (SELECT count(*) FROM pragma_table_list
      WHERE schema = 'temp' AND name = '_newsflo_reducer_session') = 0
BEGIN
  SELECT RAISE(ABORT, 'company_impact is writable only by the reducer session');
END
"""

_COMPANY_IMPACT_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_impact_reducer_only_update
BEFORE UPDATE ON company_impact
FOR EACH ROW
WHEN (SELECT count(*) FROM pragma_table_list
      WHERE schema = 'temp' AND name = '_newsflo_reducer_session') = 0
BEGIN
  SELECT RAISE(ABORT, 'company_impact is writable only by the reducer session');
END
"""

_COMPANY_IMPACT_VERSION_INSERT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_impact_version_fence_insert
BEFORE INSERT ON company_impact
FOR EACH ROW
WHEN (SELECT count(*) FROM supported_version
      WHERE reducer_version = NEW.reducer_version AND active = 1) = 0
BEGIN
  SELECT RAISE(ABORT, 'unsupported reducer_version');
END
"""

_COMPANY_IMPACT_VERSION_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS company_impact_version_fence_update
BEFORE UPDATE ON company_impact
FOR EACH ROW
WHEN (SELECT count(*) FROM supported_version
      WHERE reducer_version = NEW.reducer_version AND active = 1) = 0
BEGIN
  SELECT RAISE(ABORT, 'unsupported reducer_version');
END
"""

_SIGNAL_APPEND_ONLY_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS signal_append_only_update
BEFORE UPDATE ON signal
FOR EACH ROW
BEGIN
  SELECT RAISE(ABORT, 'signal is append-only');
END
"""

_SIGNAL_APPEND_ONLY_DELETE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS signal_append_only_delete
BEFORE DELETE ON signal
FOR EACH ROW
BEGIN
  SELECT RAISE(ABORT, 'signal is append-only');
END
"""

_TRIGGERS = (
    _COMPANY_IMPACT_INSERT_TRIGGER,
    _COMPANY_IMPACT_UPDATE_TRIGGER,
    _COMPANY_IMPACT_VERSION_INSERT_TRIGGER,
    _COMPANY_IMPACT_VERSION_UPDATE_TRIGGER,
    _SIGNAL_APPEND_ONLY_UPDATE_TRIGGER,
    _SIGNAL_APPEND_ONLY_DELETE_TRIGGER,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if 'signal' not in existing:
        op.create_table(
            'signal',
            sa.Column('signal_id', sa.String(), nullable=False),
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=True),
            sa.Column('stage', sa.String(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('payload_json', sa.Text(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column('analysis_version', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('signal_id'),
        )
        op.create_index('ix_signal_event_company', 'signal',
                        ['event_id', 'company_id'], unique=False)

    if 'supported_version' not in existing:
        op.create_table(
            'supported_version',
            sa.Column('reducer_version', sa.String(), nullable=False),
            sa.Column('active', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('reducer_version'),
        )

    if 'company_impact' not in existing:
        op.create_table(
            'company_impact',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('event_id', sa.String(), nullable=False),
            sa.Column('company_id', sa.Integer(), nullable=False),
            sa.Column('ticker', sa.String(), nullable=True),
            sa.Column('isin', sa.String(), nullable=True),
            sa.Column('analysis_version', sa.String(), nullable=False),
            sa.Column('reducer_version', sa.String(), nullable=False),
            sa.Column('reducer_run_seq', sa.Integer(), nullable=False),
            sa.Column('gate_config_version', sa.String(), nullable=True),
            sa.Column('net_effect', sa.String(), nullable=True),
            sa.Column('headline_horizon', sa.String(), nullable=True),
            sa.Column('direction_by_horizon_json', sa.Text(), nullable=True),
            sa.Column('sign_consistency', sa.Float(), nullable=True),
            sa.Column('materiality_bucket', sa.String(), nullable=True),
            sa.Column('mechanism_id', sa.String(), nullable=True),
            sa.Column('channels_json', sa.Text(), nullable=True),
            sa.Column('policy_modifiers_json', sa.Text(), nullable=True),
            sa.Column('evidence_grade', sa.String(), nullable=True),
            sa.Column('weakest_link', sa.String(), nullable=True),
            sa.Column('claim_bindings_json', sa.Text(), nullable=True),
            sa.Column('empirical_status', sa.String(), nullable=True),
            sa.Column('objections_json', sa.Text(), nullable=True),
            # Task 0.7: four questions, four columns, never merged.
            sa.Column('directness', sa.String(), nullable=True),
            sa.Column('graph_distance', sa.Integer(), nullable=True),
            sa.Column('discovery_source', sa.String(), nullable=True),
            sa.Column('publication_tier', sa.String(), nullable=False),
            sa.Column('needs_reanalysis', sa.Boolean(), server_default='0',
                      nullable=False),
            sa.Column('rejection_reason', sa.String(), nullable=True),
            sa.Column('gate_trace_json', sa.Text(), nullable=True),
            sa.Column('decision_trace_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
            sa.ForeignKeyConstraint(['reducer_version'],
                                    ['supported_version.reducer_version'],
                                    name='fk_reducer_version'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('event_id', 'company_id', 'analysis_version',
                                name='uq_impact'),
        )
        op.create_index('ix_company_impact_event', 'company_impact',
                        ['event_id'], unique=False)

    if 'firewall_deletion' not in existing:
        op.create_table(
            'firewall_deletion',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('event_id', sa.String(), nullable=True),
            sa.Column('company_id', sa.Integer(), nullable=True),
            sa.Column('sentence', sa.Text(), nullable=False),
            sa.Column('reason', sa.String(), nullable=False),
            sa.Column('stage', sa.String(), nullable=False),
            sa.Column('model_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )

    # The version fence, without which no canonical write can succeed.
    # INSERT OR IGNORE / ON CONFLICT so a re-run of the chain is a no-op.
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(
            "INSERT OR IGNORE INTO supported_version "
            "(reducer_version, active, created_at) "
            "VALUES (:v, 1, CURRENT_TIMESTAMP)"), {"v": _REDUCER_VERSION})
    else:
        bind.execute(sa.text(
            "INSERT INTO supported_version (reducer_version, active, created_at) "
            "VALUES (:v, true, now()) ON CONFLICT DO NOTHING"),
            {"v": _REDUCER_VERSION})

    # Triggers last: they police tables that must already exist, and the
    # company_impact ones read supported_version.
    if bind.dialect.name == "sqlite":
        for statement in _TRIGGERS:
            bind.execute(sa.text(statement))


def downgrade() -> None:
    """Downgrade schema.

    Drops the V5 tables and their triggers. The signal log and every
    canonical record go with them -- they are reproducible by re-running
    analysis, unlike the labeled corpus 0010 warns about.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for name in ("company_impact_reducer_only_insert",
                     "company_impact_reducer_only_update",
                     "company_impact_version_fence_insert",
                     "company_impact_version_fence_update",
                     "signal_append_only_update",
                     "signal_append_only_delete"):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    for table in ('firewall_deletion', 'company_impact', 'supported_version',
                  'signal'):
        op.drop_table(table)
