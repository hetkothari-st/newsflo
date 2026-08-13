"""exposure provenance

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Corrective-v4 Task 6: breaks the exposure self-certification loop. New
# columns on company_node_exposures let a row distinguish an independently-
# sourced relationship (SUPPLY_LINK/MANUAL/CURATED -- Tier C evidence) from
# the system's own MODEL_VERIFIED prior (candidacy only, never evidence),
# and give every prior an expiry (review_after) so acceptance never
# compounds forever. Guarded the same way as 0002's table-add and every
# entry in app.db._ADDED_COLUMNS: models.py already declares these
# columns, so create_all() (legacy init_db() / the db_session test
# fixture) may have built them before this migration ever runs against
# that DB. evidence_id is a bare Integer, same as every other
# bootstrap-added FK-shaped column in this codebase (e.g.
# alert_companies.parent_company_id) -- no DB-level FK constraint is added
# by the guarded-ALTER path; the ORM relationship is documentation, not an
# enforced constraint.
_NEW_COLUMNS = [
    ("review_after", sa.DateTime(timezone=True)),
    ("source_type", sa.String()),
    ("source_url", sa.String()),
    ("source_date", sa.Date()),
    ("evidence_id", sa.Integer()),
    ("verification_version", sa.String()),
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {
        col["name"] for col in inspector.get_columns("company_node_exposures")
    }
    with op.batch_alter_table("company_node_exposures", schema=None) as batch_op:
        for name, col_type in _NEW_COLUMNS:
            if name not in existing:
                batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("company_node_exposures", schema=None) as batch_op:
        for name, _col_type in reversed(_NEW_COLUMNS):
            batch_op.drop_column(name)
