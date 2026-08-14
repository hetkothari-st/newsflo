"""final blueprint: §21/§22 columns, SECONDARY_RIPPLE tier rewrite, §4
contradiction repair, §26 gated-row trigger backstop + alert idempotency key

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14 00:00:00.000000

WHAT THIS DOES, and in WHICH ORDER (the order is load-bearing):

  1. Add columns. alert_companies gets the §21/§22 fields that used to be
     overloaded onto `basis` -- causal_directness, discovery_source,
     evidence_source -- plus edge_relation (the §21 controlled relationship
     type for the company's own edge). company_decision_records gets
     causal_directness so the audit trail records the directness the gate
     evaluated (§11: DIRECT/INDIRECT is NOT derivable from causal_distance).
     alerts gets content_key, the §26 idempotency key. All nullable: the
     legacy corpus has none of these and must stay honestly NULL.
     (alert_companies.confidence_band already exists -- it predates this
     migration and is REUSED, not re-added.)

  2. Tier rewrite (ruling R3). "secondary_deep_dive" (V4) and "secondary"
     (pre-Task-4) name the SAME tier the blueprint now calls
     SECONDARY_RIPPLE. Two dead aliases in the data mean every reader-side
     filter has to know all three names forever, and the one that forgets
     silently drops rows. Rewritten in place, in both alert_companies and
     company_decision_records.

  3. Contradiction repair (§4, the live OIL.NS row: bearish company
     direction sitting on top of a bullish upstream-realization mechanism
     and a positive UI result). `economic_effect` is the ONE authoritative
     field; `direction` is derived from it. Every GATED row whose direction
     contradicts its effect is repaired to the derived value.

  4. Trigger backstop (§26). BEFORE INSERT / BEFORE UPDATE triggers on
     alert_companies that RAISE(ABORT) on exactly the contradictions
     step 3 just repaired, plus the nulling of a gated row's rationale.

STEP 3 MUST PRECEDE STEP 4 (controller ruling, 2026-08-14). The repair is
an UPDATE against exactly the rows the trigger exists to police, and the
trigger it precedes would be evaluated on every one of them. Two failure
modes follow from getting this backwards:
  * the migration itself aborts -- any repair clause whose NEW row is
    momentarily still inconsistent (a multi-column repair, or any future
    extension of this clause) trips the guard and rolls the upgrade back;
  * the corrupt rows become permanently unwritable -- a row the guard is
    installed on top of can no longer be corrected by anything, including
    a later migration, because every UPDATE that touches it re-evaluates
    the same failing condition against NEW.
Repair the data, THEN install the guard that keeps it repaired.

!!! WARNING TO ANY 0009+ MIGRATION AUTHOR !!!
`op.batch_alter_table` on SQLite RECREATES the table (CREATE new -> copy
rows -> DROP old -> RENAME), and SQLite DROPS every trigger attached to a
dropped table. Alembic does NOT copy triggers across a batch rebuild, and
app/models.py's `after_create` DDL hook does NOT fire on one either. So ANY
future migration that batch-alters `alert_companies` -- adding a column,
changing a constraint, anything Alembic implements by rebuild, and
certainly anything with `recreate="always"` -- SILENTLY DROPS THIS ENTIRE
BACKSTOP, leaving the schema looking correct and the §26 guarantee gone.

Such a migration MUST re-emit both triggers at the END of its batch
operation. Copy `_UPDATE_TRIGGER` / `_INSERT_TRIGGER` below verbatim
(migrations must not import app code); the byte-identity test in
tests/test_migrations.py keeps every copy honest.

POSTGRES FOLLOW-UP. The triggers are emitted only when
`bind.dialect.name == "sqlite"`. Postgres has no `CREATE TRIGGER IF NOT
EXISTS` and no `RAISE(ABORT)` in trigger bodies -- it needs a
`CREATE OR REPLACE FUNCTION ... RETURNS trigger` raising an exception plus
`DROP TRIGGER IF EXISTS` / `CREATE TRIGGER` pairs, which is a separate
migration written against a real Postgres target. Steps 1-3 are
dialect-agnostic and DO run everywhere; only step 4 is SQLite-scoped.
Emitting nothing on other dialects is correct rather than half-enforcing.

LITERAL TIER/EFFECT STRINGS BELOW ARE DELIBERATE. A migration is a
statement about the database as it was at a point in time; importing
app.analysis.impact_graph.publication_gate's constants would let a later
refactor silently change what this already-applied migration claims to
have done.

Guarded add-if-missing throughout, exactly like 0002-0007: app/models.py
already declares every column and index here, so `create_all()` may have
built them before this migration ever runs against that DB, and
tools/migrate_on_boot.py re-runs the whole chain on every container start.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


# §21/§22: discovery, causality and evidence each get their own column
# instead of all three being read off `basis = direct_mention`. edge_relation
# is the §21 controlled relationship type (REVENUE_REALIZATION, INPUT_COST,
# REFINING_SPREAD, ...) for this company's own edge -- the real graph
# labelled upstream realization, aviation fuel cost and refining margin all
# as "demand".
_ALERT_COMPANY_COLUMNS = [
    ("causal_directness", sa.String()),   # DIRECT | INDIRECT | REMOTE
    ("discovery_source", sa.String()),    # ARTICLE_MENTION | MECHANISM_MAPPING | ...
    ("evidence_source", sa.String()),     # PRIMARY | STRUCTURED | VERIFIED | ...
    ("edge_relation", sa.String()),       # §21 controlled relation type
    # confidence_band is NOT listed: it already exists (pre-0008) and is
    # reused. The guard below would no-op over it anyway; naming it here
    # would only suggest this migration introduced it.
]

_DECISION_RECORD_COLUMNS = [
    ("causal_directness", sa.String()),
]

# Ruling R3: both dead aliases for the tier now called SECONDARY_RIPPLE.
_DEAD_SECONDARY_TIERS = ("secondary_deep_dive", "secondary")
_SECONDARY_RIPPLE = "secondary_ripple"

# Duplicated verbatim from app/models.py's
# _GATED_CONSISTENCY_{UPDATE,INSERT}_TRIGGER (also exported there as
# models.GATED_ROW_TRIGGER_DDL / models.emit_gated_row_triggers, for
# NON-migration callers). Duplication over import on purpose (see the
# docstring): a migration must not depend on app code that drifts
# underneath it. Drift is closed mechanically instead --
# tests/test_migrations.py's test_models_and_0008_trigger_ddl_are_byte_
# identical reads THIS FILE's source and compares the normalized SQL
# against models.py's, so the two can never silently diverge.
_UPDATE_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS alert_companies_gated_consistency
BEFORE UPDATE ON alert_companies
FOR EACH ROW
WHEN NEW.gate_state IS NOT NULL
 AND (
   (NEW.economic_effect = 'positive' AND NEW.direction = 'bearish')
   OR (NEW.economic_effect = 'negative' AND NEW.direction = 'bullish')
   OR (NEW.rationale IS NULL AND OLD.rationale IS NOT NULL)
 )
BEGIN
  SELECT RAISE(ABORT, 'gated row consistency violation');
END
"""

_INSERT_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS alert_companies_gated_consistency_insert
BEFORE INSERT ON alert_companies
FOR EACH ROW
WHEN NEW.gate_state IS NOT NULL
 AND (
   (NEW.economic_effect = 'positive' AND NEW.direction = 'bearish')
   OR (NEW.economic_effect = 'negative' AND NEW.direction = 'bullish')
 )
BEGIN
  SELECT RAISE(ABORT, 'gated row consistency violation');
END
"""


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- 1. columns ------------------------------------------------------
    existing_ac = {col["name"] for col in inspector.get_columns("alert_companies")}
    missing_ac = [(n, t) for n, t in _ALERT_COMPANY_COLUMNS if n not in existing_ac]
    if missing_ac:
        with op.batch_alter_table("alert_companies", schema=None) as batch_op:
            for name, col_type in missing_ac:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))

    existing_dr = {
        col["name"] for col in inspector.get_columns("company_decision_records")
    }
    missing_dr = [(n, t) for n, t in _DECISION_RECORD_COLUMNS if n not in existing_dr]
    if missing_dr:
        with op.batch_alter_table("company_decision_records", schema=None) as batch_op:
            for name, col_type in missing_dr:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))

    existing_alerts = {col["name"] for col in inspector.get_columns("alerts")}
    if "content_key" not in existing_alerts:
        with op.batch_alter_table("alerts", schema=None) as batch_op:
            batch_op.add_column(sa.Column("content_key", sa.String(), nullable=True))

    # --- 2. tier rewrite (ruling R3) --------------------------------------
    for table in ("alert_companies", "company_decision_records"):
        result = bind.execute(sa.text(
            f"UPDATE {table} SET display_tier = :new "
            "WHERE display_tier IN ('secondary_deep_dive', 'secondary')"
        ), {"new": _SECONDARY_RIPPLE})
        if result.rowcount:
            logger.info(
                "[0008] rewrote %s %s rows from %s to %s",
                result.rowcount, table, "/".join(_DEAD_SECONDARY_TIERS),
                _SECONDARY_RIPPLE)

    # --- 3. contradiction repair (§4) -- BEFORE the trigger (step 4) ------
    # A gated row whose derived direction contradicts its authoritative
    # economic_effect is the exact live OIL.NS defect. Repaired here, while
    # the guard that would refuse the write does not exist yet.
    contradictions = bind.execute(sa.text(
        "SELECT COUNT(*) FROM alert_companies WHERE gate_state IS NOT NULL AND ("
        "(economic_effect = 'positive' AND direction = 'bearish') OR "
        "(economic_effect = 'negative' AND direction = 'bullish'))"
    )).scalar()
    if contradictions:
        bind.execute(sa.text(
            "UPDATE alert_companies SET direction = CASE economic_effect "
            "WHEN 'positive' THEN 'bullish' ELSE 'bearish' END "
            "WHERE gate_state IS NOT NULL AND ("
            "(economic_effect = 'positive' AND direction = 'bearish') OR "
            "(economic_effect = 'negative' AND direction = 'bullish'))"
        ))
        logger.warning(
            "[0008] blueprint Sec4 contradiction repair: %s gated alert_companies "
            "rows had a direction contradicting economic_effect; direction "
            "rewritten to the derived value", contradictions)
    else:
        logger.info("[0008] blueprint Sec4 contradiction repair: 0 rows affected")

    # --- 4. gated-row trigger backstop (§26), SQLite only -----------------
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(_UPDATE_TRIGGER))
        bind.execute(sa.text(_INSERT_TRIGGER))

    # --- 5. idempotency index (§26) ---------------------------------------
    # Partial: the legacy corpus has NULL content_key and legitimately many
    # alerts per article, so a plain unique index would be wrong. Emitted as
    # raw DDL because Alembic's create_index carries the WHERE clause only
    # via dialect kwargs, and this must land identically on SQLite and
    # Postgres (both spell partial indexes the same way).
    existing_alert_indexes = {ix["name"] for ix in inspector.get_indexes("alerts")}
    if "uq_alerts_article_content" not in existing_alert_indexes:
        bind.execute(sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_article_content "
            "ON alerts (article_id, content_key) WHERE content_key IS NOT NULL"
        ))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS uq_alerts_article_content"))
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text(
            "DROP TRIGGER IF EXISTS alert_companies_gated_consistency_insert"))
        bind.execute(sa.text(
            "DROP TRIGGER IF EXISTS alert_companies_gated_consistency"))
    # The tier rewrite and the contradiction repair are NOT reversed: both
    # replaced wrong/ambiguous data with correct data, and there is no
    # record of which rows were which. A downgrade restores the SCHEMA, not
    # the defects.
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        batch_op.drop_column("content_key")
    with op.batch_alter_table("company_decision_records", schema=None) as batch_op:
        for name, _col_type in reversed(_DECISION_RECORD_COLUMNS):
            batch_op.drop_column(name)
    with op.batch_alter_table("alert_companies", schema=None) as batch_op:
        for name, _col_type in reversed(_ALERT_COMPANY_COLUMNS):
            batch_op.drop_column(name)
