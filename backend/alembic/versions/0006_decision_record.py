"""decision-record completeness + alert_companies dedupe + impact_edges index

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Corrective-v4 Task 18: decision-record completeness (spec Sec54).
# Guarded the same way as 0002/0003/0004/0005: models.py already declares
# every one of these columns, so create_all() may have built them before
# this migration ever runs against that DB.
_DECISION_RECORD_COLUMNS = [
    ("discovery_sources_json", sa.Text()),
    ("gate_inputs_json", sa.Text()),
    ("evidence_ids_json", sa.Text()),
    ("provider", sa.String()),
    ("model", sa.String()),
    ("analysis_quality", sa.String()),
    ("correction_json", sa.Text()),
]

# Review-round fix (Task 18): every table carrying
# ForeignKey("alert_companies.id") -- SQLite has FK enforcement OFF by
# default, so the original pre-dedupe DELETE below would have silently
# orphaned any of these children still pointing at a deleted duplicate row.
# (table, unique columns on that table EXCLUDING alert_company_id itself --
# empty list means alert_company_id alone is unique). Matches app/models.py
# exactly: CalibrationSample(alert_company_id, horizon_days),
# CarOutcome(alert_company_id) alone, EmailNotification(user_id,
# alert_company_id), AlertCompanyTranslation(alert_company_id, lang).
_ALERT_COMPANY_CHILD_TABLES: list[tuple[str, list[str]]] = [
    ("calibration_samples", ["horizon_days"]),
    ("car_outcomes", []),
    ("email_notifications", ["user_id"]),
    ("alert_company_translations", ["lang"]),
]


def _repoint_or_drop_children(bind, loser_id: int, keep_id: int) -> None:
    """Before a duplicate `alert_companies` row is deleted, every child row
    that still points at it must be repointed to the survivor -- or, if the
    survivor already has a row occupying that same unique-constraint slot,
    dropped instead (the survivor's own history wins; a duplicate's child
    row is discarded, never left to violate the child table's own unique
    constraint on UPDATE). Processed one loser at a time, so a later loser
    correctly collides against an EARLIER loser's just-repointed row, not
    only against rows that existed before this migration started."""
    for table, key_cols in _ALERT_COMPANY_CHILD_TABLES:
        select_cols = ", ".join(["id", *key_cols])
        rows = bind.execute(sa.text(
            f"SELECT {select_cols} FROM {table} WHERE alert_company_id = :loser_id"
        ), {"loser_id": loser_id}).fetchall()
        for row in rows:
            child_id = row[0]
            key_values = dict(zip(key_cols, row[1:]))
            if key_cols:
                where_clause = " AND ".join(f"{c} = :{c}" for c in key_cols)
                collision = bind.execute(sa.text(
                    f"SELECT id FROM {table} WHERE alert_company_id = :keep_id AND {where_clause}"
                ), {"keep_id": keep_id, **key_values}).fetchone()
            else:
                collision = bind.execute(sa.text(
                    f"SELECT id FROM {table} WHERE alert_company_id = :keep_id"
                ), {"keep_id": keep_id}).fetchone()
            if collision is not None:
                bind.execute(sa.text(f"DELETE FROM {table} WHERE id = :id"), {"id": child_id})
            else:
                bind.execute(sa.text(
                    f"UPDATE {table} SET alert_company_id = :keep_id WHERE id = :id"
                ), {"keep_id": keep_id, "id": child_id})


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- company_decision_records: new columns + composite lookup index ---
    existing_dr_columns = {col["name"] for col in inspector.get_columns("company_decision_records")}
    existing_dr_indexes = {ix["name"] for ix in inspector.get_indexes("company_decision_records")}
    with op.batch_alter_table("company_decision_records", schema=None) as batch_op:
        for name, col_type in _DECISION_RECORD_COLUMNS:
            if name not in existing_dr_columns:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))
        # LEDGER RULING (corrective-v4 Task 18, supersedes the plan's
        # UniqueConstraint on alert_id/ticker/analysis_version): duplicate-
        # rejection rows (REJECT_DUPLICATE for the same ticker twice in one
        # alert) ARE part of the audit trail, not an integrity violation --
        # a unique constraint would reject exactly the rows this table
        # exists to keep. A composite index supports lookups without
        # constraining cardinality.
        if "ix_decision_alert_ticker" not in existing_dr_indexes:
            batch_op.create_index("ix_decision_alert_ticker", ["alert_id", "ticker"])

    # --- alert_companies: pre-dedupe, then enforce (alert_id, company_id) --
    # LEDGER RULING (plan-gap carry): alert_companies has never enforced
    # this uniqueness -- a bug anywhere upstream that calls
    # _build_alert_company twice for the same candidate silently doubles a
    # company's card on the feed. Legacy rows may already violate it, so
    # duplicates are pre-deleted (keeping the highest id -- the most
    # recently written, and therefore most likely to carry the fullest v4
    # gate/measurement fields) before the constraint is added.
    dupes = bind.execute(sa.text(
        "SELECT alert_id, company_id, MAX(id) AS keep_id "
        "FROM alert_companies GROUP BY alert_id, company_id HAVING COUNT(*) > 1"
    )).fetchall()
    for alert_id, company_id, keep_id in dupes:
        losers = bind.execute(sa.text(
            "SELECT id FROM alert_companies WHERE alert_id = :alert_id "
            "AND company_id = :company_id AND id != :keep_id"
        ), {"alert_id": alert_id, "company_id": company_id, "keep_id": keep_id}).fetchall()
        for (loser_id,) in losers:
            _repoint_or_drop_children(bind, loser_id, keep_id)
        bind.execute(sa.text(
            "DELETE FROM alert_companies WHERE alert_id = :alert_id "
            "AND company_id = :company_id AND id != :keep_id"
        ), {"alert_id": alert_id, "company_id": company_id, "keep_id": keep_id})

    existing_ac_constraints = {
        uq["name"] for uq in inspector.get_unique_constraints("alert_companies")
    }
    if "uq_alert_company_alert_company" not in existing_ac_constraints:
        with op.batch_alter_table("alert_companies", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_alert_company_alert_company", ["alert_id", "company_id"])

    # --- impact_edges: alert_id lookup index -------------------------------
    existing_edge_indexes = {ix["name"] for ix in inspector.get_indexes("impact_edges")}
    if "ix_impact_edges_alert_id" not in existing_edge_indexes:
        with op.batch_alter_table("impact_edges", schema=None) as batch_op:
            batch_op.create_index("ix_impact_edges_alert_id", ["alert_id"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("impact_edges", schema=None) as batch_op:
        batch_op.drop_index("ix_impact_edges_alert_id")
    with op.batch_alter_table("alert_companies", schema=None) as batch_op:
        batch_op.drop_constraint("uq_alert_company_alert_company", type_="unique")
    with op.batch_alter_table("company_decision_records", schema=None) as batch_op:
        batch_op.drop_index("ix_decision_alert_ticker")
        for name, _col_type in reversed(_DECISION_RECORD_COLUMNS):
            batch_op.drop_column(name)
