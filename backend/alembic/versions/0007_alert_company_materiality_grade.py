"""alert_companies.materiality_grade (composite grade the gate evaluated)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Final-review finding I3: the gate evaluates a COMPOSITE materiality grade
# (app.analysis.impact_graph.materiality.materiality_grade -- the LLM float
# capped by the company's own exposure ordinal and the evidence tier), but
# nothing persisted it. app.market.ripple_layers then re-derived a grade
# from the naked float alone, so a candidate whose composite grade the gate
# capped to MEDIUM was served to the reader as HIGH -- a number the gate
# never accepted. This column stores the value the gate actually used.
# Nullable: legacy rows (and every ungated row) have no composite grade and
# must stay honestly NULL rather than get one invented for them.
# Guarded like 0002-0006: models.py already declares the column, so
# create_all() may have built it before this migration runs.


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {col["name"] for col in inspector.get_columns("alert_companies")}
    if "materiality_grade" not in existing:
        with op.batch_alter_table("alert_companies", schema=None) as batch_op:
            batch_op.add_column(sa.Column("materiality_grade", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("alert_companies", schema=None) as batch_op:
        batch_op.drop_column("materiality_grade")
