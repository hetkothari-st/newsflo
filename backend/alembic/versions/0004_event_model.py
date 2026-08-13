"""event model: cause + expected market sensitivity

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Corrective-v4 Task 10: structured event causation (alerts.event_cause) and
# expected market sensitivity (alert_companies.expected_market_sensitivity)
# as two DISTINCT new concepts -- neither is derived from the other, and
# neither is derived from a measured price move. Guarded the same way as
# 0002/0003: models.py already declares both columns, so create_all() may
# have built them before this migration ever runs against that DB.
_ALERT_COLUMNS = [
    ("event_cause", sa.String()),
]
_ALERT_COMPANY_COLUMNS = [
    ("expected_market_sensitivity", sa.String()),
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_alerts = {col["name"] for col in inspector.get_columns("alerts")}
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        for name, col_type in _ALERT_COLUMNS:
            if name not in existing_alerts:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))

    existing_alert_companies = {col["name"] for col in inspector.get_columns("alert_companies")}
    with op.batch_alter_table("alert_companies", schema=None) as batch_op:
        for name, col_type in _ALERT_COMPANY_COLUMNS:
            if name not in existing_alert_companies:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("alert_companies", schema=None) as batch_op:
        for name, _col_type in reversed(_ALERT_COMPANY_COLUMNS):
            batch_op.drop_column(name)
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        for name, _col_type in reversed(_ALERT_COLUMNS):
            batch_op.drop_column(name)
