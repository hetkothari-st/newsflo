"""fact provenance + event geography: alerts.fact_items_json,
alerts.event_geography_scope, alerts.event_geography_regions_json

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-14 00:00:00.000000

WHAT THIS DOES

Three nullable columns on `alerts`, and nothing else.

  * fact_items_json -- the classed stage-1 fact store this alert's graph
    reasoned from: a JSON list of {fact_id, text, fact_class}, where
    fact_class is FACT / DERIVED / INFERENCE / UNKNOWN (app.analysis.
    impact_graph.schemas.FACT_CLASSES). `alerts.facts` already stores the
    PROSE record; this is its structured twin.
  * event_geography_scope -- INDIA / GLOBAL / OTHER_COUNTRY / UNKNOWN.
  * event_geography_regions_json -- a JSON list of the places the ARTICLE
    itself named, in the article's own wording.

ALL NULLABLE, and the writer leaves them NULL rather than writing "[]" or
"UNKNOWN" when nothing was extracted: the entire pre-0009 corpus has no
classed facts and no geography, and a row must not claim an extraction
happened that never did. Readers must treat NULL as "not recorded", never
as "recorded as empty".

ADVISORY DATA. Nothing here is read back into reasoning and no gate check
consults it -- app.analysis.impact_graph.publication_gate.GATE_SEQUENCE is
unchanged by this migration's feature. It exists for audit: given a
published claim, which of the facts behind it did the article actually
state, and where did the event happen.

THIS MIGRATION DOES NOT TOUCH alert_companies. 0008's docstring warns that
any batch_alter_table over `alert_companies` silently drops the §26 gated-
consistency triggers and must re-emit them. This one alters only `alerts`,
so those triggers are untouched and are deliberately NOT re-emitted here
(re-emitting from a migration that never endangered them would just be a
second copy of the DDL to keep in sync).

Guarded add-if-missing, exactly like 0002-0008: app/models.py already
declares these columns, so create_all() may have built them before this
migration runs against that DB, and tools/migrate_on_boot.py re-runs the
whole chain on every container start.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import logging


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


_ALERT_COLUMNS = [
    ("fact_items_json", sa.Text()),
    ("event_geography_scope", sa.String()),
    ("event_geography_regions_json", sa.Text()),
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {col["name"] for col in inspector.get_columns("alerts")}
    missing = [(name, col_type) for name, col_type in _ALERT_COLUMNS if name not in existing]
    if not missing:
        logger.info("[0009] fact-provenance columns already present; nothing to add")
        return
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        for name, col_type in missing:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
    logger.info("[0009] added %s to alerts", ", ".join(name for name, _ in missing))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing = {col["name"] for col in inspector.get_columns("alerts")}
    present = [name for name, _ in reversed(_ALERT_COLUMNS) if name in existing]
    if not present:
        return
    with op.batch_alter_table("alerts", schema=None) as batch_op:
        for name in present:
            batch_op.drop_column(name)
