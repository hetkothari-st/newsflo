"""market integrity: data_quality, session_state, reaction_significance

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Corrective-v4 Task 14: market-measurement hardening -- three new honesty
# columns on market_moves (data_quality, session_state, reaction_
# significance). Guarded the same way as 0002/0003/0004: models.py already
# declares all three, so create_all() may have built them before this
# migration ever runs against that DB.
_MARKET_MOVE_COLUMNS = [
    ("data_quality", sa.String()),
    ("session_state", sa.String()),
    ("reaction_significance", sa.String()),
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {col["name"] for col in inspector.get_columns("market_moves")}
    with op.batch_alter_table("market_moves", schema=None) as batch_op:
        for name, col_type in _MARKET_MOVE_COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("market_moves", schema=None) as batch_op:
        for name, _col_type in reversed(_MARKET_MOVE_COLUMNS):
            batch_op.drop_column(name)
