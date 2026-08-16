"""V5 Phase 3 ripple discovery: valid_exposure_tag, mechanism_edge,
io_coefficient, coverage_gap (+ closed-vocabulary write guard and the
exposure index)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-17 00:00:00.000000

WHAT THIS DOES

Creates the V5 Phase 3 tables (docs/v5/04_PHASE_3_ripple_discovery.md tasks
3.1-3.5, addendum A2.3) and NOTHING else. No existing table is altered and
no column is added to one.

  valid_exposure_tag  the closed exposure vocabulary, spec 6.1
  mechanism_edge      one edge of the causal graph, addendum A2.3
  io_coefficient      direct + Leontief total input coefficients, A2.3
  coverage_gap        empirically reacting industries the graph cannot explain

THE ONE ROW THIS MIGRATION WRITES

`valid_exposure_tag` is populated from `config/exposure_tags.yaml`, and it is
the ONLY table here that ships non-empty. That is deliberate and it is not a
breach of the fabrication guard: a tag name is a WORD this system may use,
not a claim about the world. `input:crude_derivative_rubber` asserts that
"tyres buy synthetic rubber" is expressible; it asserts nothing about any
tyre maker, any coefficient or any filing. The claim that a specific company
carries that exposure lives in `company_exposure`, which still ships empty
and is still filled only by a human approving a verbatim excerpt.

`mechanism_edge`, `io_coefficient` and `coverage_gap` ship EMPTY, and
tests/phase3/test_migration_0013.py asserts it after a full `upgrade head`.
In particular NOT ONE input-output coefficient is written here: the phase
file is explicit that io_coefficient comes from published MOSPI/RBI tables
or the table stays empty (DATA_GAPS section 7).

THE VOCABULARY GUARD -- WHY A TRIGGER AND NOT A CHECK

Task 3.1 asks for a "DB-level CHECK against a valid_exposure_tag table".
A SQLite CHECK constraint cannot reference another table, and a foreign key
would be an unenforced promise here because this repo never sets
`PRAGMA foreign_keys`. So the check is a BEFORE trigger that RAISE(ABORT)s --
refused at the database, on every connection, whatever code holds it. Same
substitution 0008/0011/0012 made for roles.

NEW TRIGGER NAMES ONLY. `company_exposure` already carries three triggers
from 0012; none is touched. SQLite fires every matching BEFORE trigger, so
the vocabulary check composes with 0012's review-capability check.

    -- On Postgres this is a real constraint, and the port is a
    -- transcription rather than a redesign:
    ALTER TABLE company_exposure
      ADD CONSTRAINT company_exposure_tag_fk
      FOREIGN KEY (exposure_tag) REFERENCES valid_exposure_tag (exposure_tag);
    ALTER TABLE mechanism_edge
      ADD CONSTRAINT mechanism_edge_tag_fk
      FOREIGN KEY (exposure_tag) REFERENCES valid_exposure_tag (exposure_tag);

THE EXPOSURE INDEX -- WHY A PLAIN VIEW

Task 3.2 asks for a MATERIALIZED VIEW refreshed concurrently on ledger
write. SQLite has neither. `exposure_index` is a plain VIEW: the join and
the filter are trivial at this scale, and a live view cannot be stale, so
"refresh concurrently" becomes a genuine no-op rather than a silently
skipped step. The covering index the task asks for is expressed on the BASE
TABLE, which is where SQLite can actually use it.

    -- The Postgres DDL, recorded verbatim for the port:
    CREATE MATERIALIZED VIEW exposure_index AS
    SELECT e.exposure_tag, e.exposure_kind, e.company_id, e.share_of_base,
           e.base_value_inr, e.confidence, e.as_of_date, c.adv_20d_inr, c.status
    FROM company_exposure e JOIN company c USING (company_id)
    WHERE e.share_of_base >= 0.02
      AND c.status = 'ACTIVE';

    CREATE INDEX ON exposure_index (exposure_tag, share_of_base DESC);

    -- called after every ledger write (app/ledger/review.py):
    REFRESH MATERIALIZED VIEW CONCURRENTLY exposure_index;

Two adaptations inside that view are worth stating rather than burying.
(1) This repo's company master is `companies` (Phase 1 adaptation), and the
spec's `company.status` / `company.adv_20d_inr` live in the adjunct
`company_entity_meta`, which ships empty -- so the view LEFT JOINs it and
reads an absent row as ACTIVE. That is the honest reading: the universe
loader lists live names, and nothing has been recorded against a company
with no meta row. (2) `exposure_id` is carried through so a caller can trace
an index row back to the filing it came from.

TYPE MAPPING (spec is Postgres, this deployment is SQLite):
  uuid -> TEXT (uuid4 string)   numeric -> NUMERIC   timestamptz -> DATETIME
"""
from pathlib import Path

import sqlalchemy as sa
import yaml
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

# backend/config/exposure_tags.yaml -- read directly rather than through
# app.ledger.exposure_tags, because a migration must not import app code that
# drifts underneath it. tests/phase3/test_migration_0013.py compares what this
# writes against what the loader loads, which is the drift guard.
_TAGS_YAML = Path(__file__).resolve().parents[2] / "config" / "exposure_tags.yaml"

_TRIGGERS = (
    """
CREATE TRIGGER IF NOT EXISTS company_exposure_valid_tag_insert
BEFORE INSERT ON company_exposure
FOR EACH ROW
WHEN (SELECT count(*) FROM valid_exposure_tag
      WHERE exposure_tag = NEW.exposure_tag) = 0
BEGIN
  SELECT RAISE(ABORT, 'exposure_tag is not in the closed vocabulary');
END
""",
    """
CREATE TRIGGER IF NOT EXISTS company_exposure_valid_tag_update
BEFORE UPDATE OF exposure_tag ON company_exposure
FOR EACH ROW
WHEN (SELECT count(*) FROM valid_exposure_tag
      WHERE exposure_tag = NEW.exposure_tag) = 0
BEGIN
  SELECT RAISE(ABORT, 'exposure_tag is not in the closed vocabulary');
END
""",
    """
CREATE TRIGGER IF NOT EXISTS mechanism_edge_valid_tag_insert
BEFORE INSERT ON mechanism_edge
FOR EACH ROW
WHEN (SELECT count(*) FROM valid_exposure_tag
      WHERE exposure_tag = NEW.exposure_tag) = 0
BEGIN
  SELECT RAISE(ABORT, 'exposure_tag is not in the closed vocabulary');
END
""",
    """
CREATE TRIGGER IF NOT EXISTS mechanism_edge_valid_tag_update
BEFORE UPDATE OF exposure_tag ON mechanism_edge
FOR EACH ROW
WHEN (SELECT count(*) FROM valid_exposure_tag
      WHERE exposure_tag = NEW.exposure_tag) = 0
BEGIN
  SELECT RAISE(ABORT, 'exposure_tag is not in the closed vocabulary');
END
""",
)

_VIEWS = (
    """
CREATE VIEW IF NOT EXISTS exposure_index AS
SELECT e.exposure_id AS exposure_id,
       e.exposure_tag AS exposure_tag,
       e.exposure_kind AS exposure_kind,
       e.company_id AS company_id,
       e.share_of_base AS share_of_base,
       e.base_value_inr AS base_value_inr,
       e.confidence AS confidence,
       e.as_of_date AS as_of_date,
       e.freshness_days AS freshness_days,
       m.adv_20d_inr AS adv_20d_inr,
       COALESCE(m.status, 'ACTIVE') AS status
FROM company_exposure e
JOIN companies c ON c.id = e.company_id
LEFT JOIN company_entity_meta m ON m.company_id = e.company_id
WHERE e.share_of_base >= 0.02
  AND COALESCE(m.status, 'ACTIVE') = 'ACTIVE'
""",
    """
CREATE INDEX IF NOT EXISTS ix_company_exposure_tag_share
ON company_exposure (exposure_tag, share_of_base DESC)
""",
)


def _vocabulary_tags() -> list[str]:
    """Flatten config/exposure_tags.yaml to `family:leaf` wire form.

    A leaf is a key with nothing under it, which is exactly how spec 6.1
    writes the vocabulary. Intermediate grouping keys (crude, metals, agri)
    are organisational and do not appear in the tag.
    """
    raw = yaml.safe_load(_TAGS_YAML.read_text(encoding="utf-8"))
    tags: list[str] = []

    def walk(node, trail):
        if node is None:
            return
        for key, value in node.items():
            if value is None:
                tags.append(f"{trail[0]}:{key}")
            else:
                walk(value, trail + (str(key),))

    for family, subtree in (raw.get("families") or {}).items():
        walk(subtree, (str(family),))
    return tags


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if 'valid_exposure_tag' not in existing:
        op.create_table(
            'valid_exposure_tag',
            sa.Column('exposure_tag', sa.String(), nullable=False),
            sa.Column('source', sa.String(), nullable=False),
            sa.Column('registered_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('exposure_tag'),
        )

    if 'mechanism_edge' not in existing:
        op.create_table(
            'mechanism_edge',
            sa.Column('edge_id', sa.String(), nullable=False),
            sa.Column('from_node', sa.String(), nullable=False),
            sa.Column('to_node', sa.String(), nullable=False),
            sa.Column('exposure_tag', sa.String(), nullable=False),
            sa.Column('relationship_type', sa.String(), nullable=False),
            sa.Column('distance', sa.Integer(), nullable=False),
            sa.Column('io_total_coeff', sa.Numeric(), nullable=True),
            sa.Column('derivation', sa.String(), nullable=False),
            sa.Column('reviewed_by', sa.String(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('review_status', sa.String(), server_default='PENDING',
                      nullable=False),
            sa.Column('review_note', sa.Text(), nullable=True),
            sa.Column('confidence', sa.Numeric(), nullable=False),
            sa.Column('effective_from', sa.Date(), nullable=True),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('table_year', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('edge_id'),
        )
        op.create_index('ix_mechanism_edge_from', 'mechanism_edge',
                        ['from_node'], unique=False)
        op.create_index('ix_mechanism_edge_tag', 'mechanism_edge',
                        ['exposure_tag'], unique=False)

    if 'io_coefficient' not in existing:
        op.create_table(
            'io_coefficient',
            sa.Column('source_industry', sa.String(), nullable=False),
            sa.Column('target_industry', sa.String(), nullable=False),
            sa.Column('table_year', sa.Integer(), nullable=False),
            sa.Column('direct_coeff', sa.Numeric(), nullable=False),
            sa.Column('total_coeff', sa.Numeric(), nullable=False),
            sa.Column('source_url', sa.String(), nullable=False),
            sa.Column('loaded_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('source_industry', 'target_industry',
                                    'table_year'),
        )

    if 'coverage_gap' not in existing:
        op.create_table(
            'coverage_gap',
            sa.Column('gap_id', sa.String(), nullable=False),
            sa.Column('variable', sa.String(), nullable=False),
            sa.Column('sign', sa.String(), nullable=False),
            sa.Column('industry', sa.String(), nullable=False),
            sa.Column('window_days', sa.Integer(), nullable=False),
            sa.Column('n', sa.Integer(), nullable=False),
            sa.Column('median_car', sa.Numeric(), nullable=False),
            sa.Column('iqr_low', sa.Numeric(), nullable=True),
            sa.Column('iqr_high', sa.Numeric(), nullable=True),
            sa.Column('sign_consistency', sa.Numeric(), nullable=False),
            sa.Column('p_value', sa.Numeric(), nullable=False),
            sa.Column('industry_mcap', sa.Numeric(), nullable=True),
            sa.Column('priority', sa.Numeric(), nullable=False),
            sa.Column('status', sa.String(), server_default='OPEN',
                      nullable=False),
            sa.Column('computed_at', sa.DateTime(timezone=True),
                      server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
            sa.PrimaryKeyConstraint('gap_id'),
            sa.UniqueConstraint('variable', 'sign', 'industry',
                                name='uq_coverage_gap_variable_sign_industry'),
        )

    # The vocabulary. Idempotent, so re-running the migration over its own
    # output adds nothing and removes nothing.
    for tag in _vocabulary_tags():
        bind.execute(
            sa.text("INSERT OR IGNORE INTO valid_exposure_tag "
                    "(exposure_tag, source) VALUES (:tag, :source)")
            if bind.dialect.name == "sqlite" else
            sa.text("INSERT INTO valid_exposure_tag (exposure_tag, source) "
                    "VALUES (:tag, :source) ON CONFLICT DO NOTHING"),
            {"tag": tag, "source": "config/exposure_tags.yaml"})

    # Guard, view and index last: they police tables that must already exist.
    if bind.dialect.name == "sqlite":
        for statement in _TRIGGERS + _VIEWS:
            bind.execute(sa.text(statement))


def downgrade() -> None:
    """Downgrade schema.

    Drops the vocabulary, the graph and the gap queue. A reviewed
    `mechanism_edge` is a human judgement about how the economy transmits a
    shock and is NOT reproducible by re-running anything. Take a backup
    before running this.
    """
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for name in ("company_exposure_valid_tag_insert",
                     "company_exposure_valid_tag_update",
                     "mechanism_edge_valid_tag_insert",
                     "mechanism_edge_valid_tag_update"):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
        bind.execute(sa.text("DROP VIEW IF EXISTS exposure_index"))
        bind.execute(sa.text("DROP INDEX IF EXISTS ix_company_exposure_tag_share"))
    for table in ('coverage_gap', 'io_coefficient', 'mechanism_edge',
                  'valid_exposure_tag'):
        op.drop_table(table)
